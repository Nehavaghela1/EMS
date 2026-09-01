from app.core.exceptions import AppError, ConflictError, NotFoundError


def test_app_error_carries_message_and_optional_details():
    err = AppError("something went wrong", details={"field": "email"})

    assert err.message == "something went wrong"
    assert err.details == {"field": "email"}


def test_subclasses_have_their_own_status_code_and_code():
    assert NotFoundError.status_code == 404
    assert NotFoundError.code == "not_found"
    assert ConflictError.status_code == 409
    assert ConflictError.code == "conflict"
