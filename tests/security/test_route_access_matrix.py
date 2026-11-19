import re
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.modules.identity.models import UserRole
from tests.conftest import _make_tenant, _make_user_headers
from tests.security.route_policy import (
    AUTH_ROUTES,
    AUTHENTICATED,
    PLATFORM_ROUTES,
    POLICY,
    PUBLIC,
    PUBLIC_ROUTES,
    REFERENCE_READ_ROUTES,
    extract_guards_from_route,
    extract_roles_from_route,
)


def _discover_app_routes(application: Any) -> list[tuple[str, str, Any]]:
    """Walks the FastAPI application at test time to discover all endpoints."""

    def _walk(router: Any, prefix: str = "") -> list[tuple[str, str, Any]]:
        discovered: list[tuple[str, str, Any]] = []
        for r in router.routes:
            if "IncludedRouter" in type(r).__name__:
                discovered.extend(_walk(r.original_router, prefix + r.include_context.prefix))
            elif hasattr(r, "endpoint"):
                p = prefix + r.path
                if len(p) > 1 and p.endswith("/"):
                    p = p[:-1]
                methods = r.methods - {"HEAD", "OPTIONS"} if hasattr(r, "methods") else set()
                for m in methods:
                    discovered.append((m, p, r))
        return discovered

    all_routes = _walk(application)
    # Filter out auto-generated documentation endpoints
    return [
        (m, p, r)
        for (m, p, r) in all_routes
        if not p.startswith(("/docs", "/redoc", "/openapi.json"))
    ]


@pytest.fixture(scope="module")
def discovered_routes():
    return _discover_app_routes(app)


@pytest.fixture
def role_test_headers(db: Session):
    """Generates authentic tokens/headers for each UserRole in a test company."""
    tenant = _make_tenant(db, name="Route Matrix Tenant", code=f"RMT{uuid.uuid4().hex[:5].upper()}")
    owner_headers = _make_user_headers(db, tenant.company_id, UserRole.owner)

    sa_code = f"PAC{uuid.uuid4().hex[:5].upper()}"
    sa_tenant = _make_tenant(db, name="Platform Admin Co", code=sa_code)
    sa_headers = _make_user_headers(db, sa_tenant.company_id, UserRole.super_admin)
    db.commit()

    return {
        UserRole.super_admin: sa_headers,
        UserRole.owner: owner_headers,
        UserRole.hr_admin: tenant.hr_headers,
        UserRole.manager: tenant.manager_headers,
        UserRole.employee: tenant.employee_headers,
    }


def test_route_policy_completeness(discovered_routes):
    """
    Test 2.a Completeness:
    - Discovered routes == POLICY keys.
    - Fail in both directions:
      * Discovered routes missing from POLICY
      * Extra routes in POLICY that do not exist in app
    """
    discovered_keys = {(m, p) for m, p, _ in discovered_routes}
    policy_keys = set(POLICY.keys())

    missing_in_policy = discovered_keys - policy_keys
    assert not missing_in_policy, f"Discovered routes missing from policy: {missing_in_policy}"

    extra_in_policy = policy_keys - discovered_keys
    assert not extra_in_policy, f"Policy entries not found in discovered routes: {extra_in_policy}"


def test_route_policy_roles_match_code(discovered_routes):
    """
    Test 2.b Roles:
    - For each ROLES entry, the roles extracted from the code via require_role
      must equal the declared roles in POLICY.
    - Fail on any difference.
    """
    mismatches = []
    for m, p, r in discovered_routes:
        policy = POLICY[(m, p)]
        code_roles = extract_roles_from_route(r)

        if isinstance(policy, tuple):
            if code_roles is None:
                mismatches.append(
                    f"{m} {p}: declared ROLES {policy} in policy, but no require_role found in code"
                )
            elif set(code_roles) != set(policy):
                mismatches.append(
                    f"{m} {p}: policy declared roles {policy} != code extracted roles {code_roles}"
                )
        else:
            if code_roles is not None:
                mismatches.append(
                    f"{m} {p}: declared {policy} in policy, but code requires roles {code_roles}"
                )

    assert not mismatches, f"Role declaration mismatches found ({len(mismatches)}):\n" + "\n".join(
        mismatches
    )


def test_public_routes_pinned(discovered_routes):
    """
    Test 2.d:
    - Pin the PUBLIC list to the exact routes in the policy.
    """
    discovered_public = {key for key, policy in POLICY.items() if policy == PUBLIC}
    assert discovered_public == PUBLIC_ROUTES, (
        f"Discovered public routes do not match pinned PUBLIC_ROUTES! Diff: "
        f"{discovered_public.symmetric_difference(PUBLIC_ROUTES)}"
    )


def test_no_token_returns_401(client: TestClient, discovered_routes):
    """
    Test 2.c:
    - Every non-PUBLIC route returns 401 when called with no authentication token.
    """
    dummy_uuid = str(uuid.uuid4())
    non_401_failures = []

    for m, p, _ in discovered_routes:
        if POLICY[(m, p)] == PUBLIC:
            continue

        resolved_path = re.sub(r"\{[^}]+\}", dummy_uuid, p)
        response = client.request(m, resolved_path)
        if response.status_code != 401:
            snippet = response.text[:100]
            non_401_failures.append(
                f"{m} {p} (resolved: {resolved_path}) returned {response.status_code}: {snippet}"
            )

    assert not non_401_failures, (
        "Non-public routes did not return 401 with no token:\n" + "\n".join(non_401_failures)
    )


def test_wrong_role_returns_403(client: TestClient, discovered_routes, role_test_headers):
    """
    Test 2.c:
    - For every ROLES route, a user of each role NOT in the tuple gets 403.
    - Uses dummy path ids.
    - If a route returns anything other than 403, list it as a failure and do not hide it.
    """
    dummy_uuid = str(uuid.uuid4())
    failures = []

    for m, p, _ in discovered_routes:
        policy = POLICY[(m, p)]
        if policy in (PUBLIC, AUTHENTICATED):
            continue

        allowed_roles_tuple: tuple[UserRole, ...] = policy
        # In require_company_role:
        # hr_admin automatically expands to include owner.
        effective_allowed = list(allowed_roles_tuple)
        if UserRole.hr_admin in allowed_roles_tuple and UserRole.owner not in effective_allowed:
            effective_allowed.append(UserRole.owner)

        disallowed_roles = [r for r in UserRole if r not in effective_allowed]
        resolved_path = re.sub(r"\{[^}]+\}", dummy_uuid, p)

        for role in disallowed_roles:
            headers = role_test_headers[role]
            response = client.request(m, resolved_path, headers=headers)
            if response.status_code != 403:
                failures.append(
                    f"Expected 403 for {role.value} on {m} {p} (resolved: {resolved_path}), "
                    f"got {response.status_code}: {response.text[:100]}"
                )

    assert not failures, f"Role access failures encountered ({len(failures)}):\n" + "\n".join(
        failures
    )


def test_route_policy_central_guards(discovered_routes):
    """
    C1: Make it impossible to add a leaky route later.
    Extend route policy verification so the suite FAILS if any route:
    - uses neither require_company_role nor require_platform_role
      (unless public/auth/reference read);
    - or is a COMPANY route that lists super_admin;
    - or is a PLATFORM route that lists any other role.
    """
    failures = []

    for m, p, r in discovered_routes:
        key = (m, p)
        if key in PUBLIC_ROUTES or key in AUTH_ROUTES:
            continue
        if key in REFERENCE_READ_ROUTES:
            # A5: Statutory rate reads stay readable by hr_admin and super_admin
            continue

        guards = extract_guards_from_route(r)
        policy = POLICY.get(key)
        is_platform = key in PLATFORM_ROUTES or p.startswith("/api/v1/platform/stats")

        # 1. Route must use exactly one central guard
        if "require_company_role" not in guards and "require_platform_role" not in guards:
            failures.append(
                f"{m} {p}: uses neither require_company_role nor require_platform_role "
                f"(guards: {guards})"
            )
            continue
        if "require_company_role" in guards and "require_platform_role" in guards:
            failures.append(f"{m} {p}: mixes both require_company_role and require_platform_role")
            continue

        if is_platform:
            # 2. PLATFORM route checks
            if "require_platform_role" not in guards:
                failures.append(
                    f"PLATFORM route {m} {p} does not use require_platform_role (guards: {guards})"
                )
            if isinstance(policy, tuple):
                non_sa = [role for role in policy if role != UserRole.super_admin]
                if non_sa:
                    failures.append(
                        f"PLATFORM route {m} {p} lists roles other than super_admin: {non_sa}"
                    )
            elif policy != AUTHENTICATED:
                failures.append(f"PLATFORM route {m} {p} unexpected policy: {policy}")
        else:
            # 3. COMPANY route checks
            if "require_company_role" not in guards:
                failures.append(
                    f"COMPANY route {m} {p} does not use require_company_role (guards: {guards})"
                )
            if isinstance(policy, tuple):
                if UserRole.super_admin in policy:
                    failures.append(f"COMPANY route {m} {p} lists super_admin in policy: {policy}")

    assert not failures, (
        f"Route policy guard enforcement failures ({len(failures)}):\n" + "\n".join(failures)
    )
