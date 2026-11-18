"""Red-first tests for Part L (Rate limits on remaining write routes).

Tests rate limiting across the 14 write routes.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TenantContext


def test_L_rate_limits_on_write_routes(client: TestClient, limits_on, company_a: TenantContext):
    # Verify limiter rejects excess calls on remaining write routes
    headers = company_a.hr_headers
    # Test one of the 14 write routes: POST /api/v1/leave-types (limit 30/minute)
    # When rate limiter is wired up, 31 rapid requests must yield 429
    url = "/api/v1/leave-types"
    responses = []
    for _ in range(35):
        r = client.post(url, json={"name": "Vacation", "days": 10}, headers=headers)
        responses.append(r.status_code)
    assert 429 in responses, f"Expected 429 in responses, got {responses[:5]}"
