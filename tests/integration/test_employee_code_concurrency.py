"""Spec 11.2: two HR admins creating an employee at the same instant must
not both get the same sequence number. Proved by actually racing real
concurrent database connections against the row-locked `UPDATE ...
RETURNING` — not by reading the code and asserting it looks atomic.

This test intentionally does NOT use the `db`/`client` fixtures: those share
a single connection wrapped in one savepoint-scoped transaction (15.2),
which would serialize every "concurrent" write on the same connection and
prove nothing about real row-locking. Real concurrency needs real, separate
connections, so this talks to the test database directly and cleans up
after itself.
"""

import threading
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.identity.models import Company, CompanyStatus
from app.modules.identity.repository import CompanyRepository

CONCURRENT_REQUESTS = 12


def test_employee_code_generation_is_concurrency_safe():
    engine = create_engine(
        settings.TEST_DATABASE_URL, pool_size=CONCURRENT_REQUESTS, max_overflow=5
    )
    try:
        with Session(engine) as setup:
            company = Company(
                name="Concurrency Co",
                code=f"CONC{uuid.uuid4().hex[:5].upper()}",
                email=f"concurrency-{uuid.uuid4().hex[:8]}@example.com",
                status=CompanyStatus.active,
            )
            setup.add(company)
            setup.commit()
            company_id = company.id

        results: list[int] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(CONCURRENT_REQUESTS)

        def worker() -> None:
            try:
                barrier.wait()  # line every connection up before any of them writes
                with Session(engine) as session:
                    seq, _code = CompanyRepository(session).increment_employee_seq(company_id)
                    session.commit()
                    results.append(seq)
            except BaseException as exc:  # noqa: BLE001 — collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(CONCURRENT_REQUESTS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        # Every concurrent request got a distinct sequence number, 1..N with
        # no gaps and no duplicate — exactly what the row lock guarantees
        # and what count(*) + 1 could never guarantee under real contention.
        assert sorted(results) == list(range(1, CONCURRENT_REQUESTS + 1))

        with Session(engine) as cleanup:
            cleanup.delete(cleanup.get(Company, company_id))
            cleanup.commit()
    finally:
        engine.dispose()
