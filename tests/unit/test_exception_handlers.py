from typing import Annotated

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AfterValidator, BaseModel

from app.core.exceptions import NotFoundError, register_exception_handlers
from app.core.middleware import RequestIDMiddleware


def _reject(value: str) -> str:
    raise ValueError("too short")


_Rejected = Annotated[str, AfterValidator(_reject)]


class _Body(BaseModel):
    password: _Rejected
    nickname: _Rejected


def _build_test_app() -> FastAPI:
    """A throwaway app, not the real one — proves the handler wiring in
    isolation, with no database or network dependency (15.1). Includes
    RequestIDMiddleware because that's what actually populates
    request.state.request_id from the incoming header (16.2) — without it
    the handler would only ever see its own generated fallback id.
    """
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise NotFoundError("Employee not found.")

    @app.post("/validate")
    def validate(body: _Body):
        return body

    return app


def test_app_error_returns_the_spec_envelope_with_request_id_header():
    client = TestClient(_build_test_app())

    response = client.get("/boom", headers={"X-Request-ID": "test-request-id-123"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "test-request-id-123"
    body = response.json()
    assert body == {
        "error": {
            "code": "not_found",
            "message": "Employee not found.",
            "details": None,
            "request_id": "test-request-id-123",
        }
    }


def test_app_error_generates_a_request_id_when_none_was_sent():
    client = TestClient(_build_test_app())

    response = client.get("/boom")

    assert response.status_code == 404
    request_id = response.json()["error"]["request_id"]
    assert request_id  # a fallback id is generated, never blank
    assert response.headers["X-Request-ID"] == request_id


def test_a_custom_validator_failure_returns_422_not_500_and_redacts_sensitive_input():
    """Hardening pass: Pydantic's own `errors()` puts the exception object
    a raising AfterValidator threw into `ctx.error` — not JSON-serializable,
    so JSONResponse used to crash building the 422 into an unhandled 500 for
    ANY custom-validated field (not just passwords). It also echoes the raw
    submitted value back in `input`, which is exactly what CLAUDE.md rule 10
    forbids for a password/token/PAN/Aadhaar/bank field. Both are fixed by
    _sanitize_validation_errors; this proves it end to end, over HTTP."""
    client = TestClient(_build_test_app())

    response = client.post("/validate", json={"password": "hunter2", "nickname": "short"})

    assert response.status_code == 422  # not 500 — this is the crash regression test
    errors = response.json()["error"]["details"]["errors"]
    assert len(errors) == 2
    by_field = {tuple(e["loc"])[-1]: e for e in errors}
    assert "ctx" not in by_field["password"]  # the non-serializable bit is gone
    assert by_field["password"]["input"] == "***redacted***"
    assert by_field["nickname"]["input"] == "short"  # non-sensitive fields still echo
