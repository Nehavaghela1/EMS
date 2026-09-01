"""Spec 9.5: POST /auth/login is limited to 10/minute/IP."""


def test_hammering_login_returns_429_after_the_limit(client):
    responses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpassword1"},
        )
        for _ in range(15)
    ]

    codes = [r.status_code for r in responses]
    assert codes[:10] == [401] * 10
    assert all(code == 429 for code in codes[10:])

    body = responses[-1].json()
    assert body["error"]["code"] == "rate_limited"
