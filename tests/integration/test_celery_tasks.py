"""Spec 13's actual claim to prove: a task queued via `.delay()` completes
asynchronously, on a real worker process talking to a real broker, while
the caller that queued it never blocks. `CELERY_TASK_ALWAYS_EAGER` (13.3)
would hide exactly this — so this test does NOT use eager mode. It starts a
real `celery worker` subprocess against the real Redis broker/backend this
project already runs, submits the trivial task WP-09's gate names, and
polls for the result — proving it by running it, not by reading the code.
"""

import subprocess
import sys
import time

import pytest

from app.core.config import settings
from app.workers.tasks.example import add

WORKER_STARTUP_TIMEOUT_SECONDS = 20
TASK_RESULT_TIMEOUT_SECONDS = 15


@pytest.fixture
def real_celery_worker():
    if settings.CELERY_TASK_ALWAYS_EAGER:
        pytest.skip("CELERY_TASK_ALWAYS_EAGER=true would hide the exact bug this test checks for")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.workers.celery_app",
            "worker",
            "--pool=solo",
            "--concurrency=1",
            "-l",
            "info",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + WORKER_STARTUP_TIMEOUT_SECONDS
        ready = False
        while time.monotonic() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if "ready" in line.lower():
                ready = True
                break
            if proc.poll() is not None:
                break
        if not ready:
            proc.terminate()
            pytest.fail("Celery worker did not report ready in time")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_trivial_task_completes_asynchronously_on_a_real_worker(real_celery_worker):
    async_result = add.delay(2, 3)

    # The call above returned immediately with a handle, not a result — the
    # caller was never blocked waiting for the worker.
    assert async_result.id

    deadline = time.monotonic() + TASK_RESULT_TIMEOUT_SECONDS
    while not async_result.ready() and time.monotonic() < deadline:
        time.sleep(0.2)

    assert async_result.ready(), "task did not complete within the timeout"
    assert async_result.successful()
    assert async_result.get(timeout=1) == 5
