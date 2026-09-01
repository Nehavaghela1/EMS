from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import NotFoundError, register_exception_handlers
from app.core.middleware import RequestIDMiddleware


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
