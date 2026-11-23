"""Tests for PART R: Sentry error tracking and sensitive data scrubber.

R1: Wire Sentry behind a single DSN setting, off when DSN is absent so dev and tests are unaffected.
R2: Scrub before sending: no password, token, Aadhaar, PAN, bank account,
    authorization header, or cookie may leave the process. Write the scrubber yourself.
R3: Tag events with company_id and request_id, never employee name or email.
R4: Tests:
    - the scrubber removes every sensitive field from a representative payload;
    - with no DSN configured nothing is initialised and no network call is attempted.
"""

from unittest.mock import patch

from app.core.sentry import init_sentry, scrub_data, sentry_before_send


def test_r2_scrubber_removes_every_sensitive_field() -> None:
    representative_payload = {
        "password": "SuperSecretPassword123!",
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$dummyhash",
        "hashed_password": "hashed_val",
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy",
        "access_token": "actoken123",
        "refresh_token": "reftoken456",
        "activation_token": "act123",
        "reset_token": "rst789",
        "aadhaar": "1234 5678 9012",
        "aadhaar_number": "123456789012",
        "pan": "ABCDE1234F",
        "pan_number": "XYZPQ9876R",
        "bank_account": "9876543210123",
        "account_number": "112233445566",
        "account_number_enc": b"binary_enc",
        "authorization": "Bearer eyJhbGciOiJIUzI1Ni...",
        "cookie": "session_id=abcdef123456; csrf=xyz",
        "set-cookie": "token=secret_val",
        "nested": {
            "user_password": "nested_password",
            "employee_pan": "ABCDE1234F",
            "free_text": (
                "Here is Aadhaar 9999 8888 7777 and PAN ABCDE1234F and auth Bearer secret_tok"
            ),
        },
        "safe_field": "safe_value",
        "count": 42,
    }

    scrubbed = scrub_data(representative_payload)

    # 1. Direct keys scrubbed
    assert scrubbed["password"] == "[SCRUBBED]"
    assert scrubbed["password_hash"] == "[SCRUBBED]"
    assert scrubbed["hashed_password"] == "[SCRUBBED]"
    assert scrubbed["token"] == "[SCRUBBED]"
    assert scrubbed["access_token"] == "[SCRUBBED]"
    assert scrubbed["refresh_token"] == "[SCRUBBED]"
    assert scrubbed["activation_token"] == "[SCRUBBED]"
    assert scrubbed["reset_token"] == "[SCRUBBED]"
    assert scrubbed["aadhaar"] == "[SCRUBBED]"
    assert scrubbed["aadhaar_number"] == "[SCRUBBED]"
    assert scrubbed["pan"] == "[SCRUBBED]"
    assert scrubbed["pan_number"] == "[SCRUBBED]"
    assert scrubbed["bank_account"] == "[SCRUBBED]"
    assert scrubbed["account_number"] == "[SCRUBBED]"
    assert scrubbed["account_number_enc"] == "[SCRUBBED]"
    assert scrubbed["authorization"] == "[SCRUBBED]"
    assert scrubbed["cookie"] == "[SCRUBBED]"
    assert scrubbed["set-cookie"] == "[SCRUBBED]"

    # 2. Nested keys scrubbed
    assert scrubbed["nested"]["user_password"] == "[SCRUBBED]"
    assert scrubbed["nested"]["employee_pan"] == "[SCRUBBED]"

    # 3. Text patterns inside strings scrubbed
    free_text = scrubbed["nested"]["free_text"]
    assert "9999 8888 7777" not in free_text
    assert "[SCRUBBED_AADHAAR]" in free_text
    assert "ABCDE1234F" not in free_text
    assert "[SCRUBBED_PAN]" in free_text
    assert "Bearer [SCRUBBED]" in free_text

    # 4. Safe fields preserved
    assert scrubbed["safe_field"] == "safe_value"
    assert scrubbed["count"] == 42


def test_r2_r3_sentry_before_send_strips_pii_and_anonymizes_user() -> None:
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret_jwt_token",
                "Cookie": "jwt=session_secret",
                "Content-Type": "application/json",
            },
            "cookies": "jwt=session_secret",
            "data": {
                "password": "plain_password",
                "pan": "ABCDE1234F",
            },
        },
        "user": {
            "id": "12345",
            "email": "employee@example.com",
            "name": "Jane Doe",
            "username": "janedoe",
        },
        "extra": {
            "bank_account": "1234567890",
        },
    }

    result = sentry_before_send(event, {})
    assert result is not None

    # Headers and cookies scrubbed
    headers = result["request"]["headers"]
    assert headers["Authorization"] == "[SCRUBBED]"
    assert headers["Cookie"] == "[SCRUBBED]"
    assert headers["Content-Type"] == "application/json"
    assert result["request"]["cookies"] == "[SCRUBBED]"
    assert result["request"]["data"]["password"] == "[SCRUBBED]"
    assert result["request"]["data"]["pan"] == "[SCRUBBED]"
    assert result["extra"]["bank_account"] == "[SCRUBBED]"

    # User email, name, username stripped completely
    user = result["user"]
    assert "email" not in user
    assert "name" not in user
    assert "username" not in user
    assert user["id"] == "12345"


def test_r4_no_dsn_configured_nothing_initialized() -> None:
    with patch("app.core.sentry.settings") as mock_settings:
        mock_settings.SENTRY_DSN = None
        with patch("sentry_sdk.init") as mock_init:
            initialized = init_sentry()
            assert initialized is False
            mock_init.assert_not_called()


def test_r1_dsn_configured_initializes_sentry() -> None:
    with patch("app.core.sentry.settings") as mock_settings:
        mock_settings.SENTRY_DSN = "https://public@sentry.example.com/1"
        mock_settings.ENVIRONMENT = "test"
        with patch("sentry_sdk.init") as mock_init:
            initialized = init_sentry()
            assert initialized is True
            mock_init.assert_called_once()
            _, kwargs = mock_init.call_args
            assert kwargs["dsn"] == "https://public@sentry.example.com/1"
            assert kwargs["send_default_pii"] is False
            assert callable(kwargs["before_send"])
