"""Spec 9.5's whole table, not just login — hardening pass: forgot-password
and check-username were previously implemented against the wrong numbers
(5/minute for both, instead of the spec's 3/hour and 20/minute), and
POST /auth/refresh had no limit applied at all despite the spec naming
30/minute/IP for it. All four are now exact."""


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


def test_forgot_password_is_limited_to_3_per_hour(client):
    responses = [
        client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
        for _ in range(5)
    ]
    codes = [r.status_code for r in responses]
    assert codes[:3] == [200] * 3
    assert all(code == 429 for code in codes[3:])


def test_check_username_is_limited_to_20_per_minute(client):
    responses = [client.get(f"/api/v1/auth/check-username/probe-{i}") for i in range(22)]
    codes = [r.status_code for r in responses]
    assert codes[:20] == [200] * 20
    assert all(code == 429 for code in codes[20:])


def test_refresh_is_limited_to_30_per_minute(client):
    responses = [
        client.post("/api/v1/auth/refresh", cookies={"refresh_token": "not-a-real-token"})
        for _ in range(32)
    ]
    codes = [r.status_code for r in responses]
    assert codes[:30] == [401] * 30
    assert all(code == 429 for code in codes[30:])
