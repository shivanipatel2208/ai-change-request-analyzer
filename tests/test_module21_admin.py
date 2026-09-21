"""Verifies Module 21 (Administration & Configuration).

Following this project's established HTTP-only testing convention, every
admin behavior is verified the same way every other endpoint in this suite
is - through the real API (registering real users via /auth/register, then
promoting/demoting/deactivating them directly through SessionLocal the
same way test_workflow_foundation.py's own test_admin_can_always_edit does)
and real HTTP calls, never by calling internal functions where an endpoint
exists to exercise instead. The one exception is required_approval_types()
itself (spec section 4's "a custom rule actually changes recommended
approvals") - that pure function is already unit-tested directly by
test_workflow_foundation.py, so this file follows the same convention to
prove a rule ADDED THROUGH THE REAL ADMIN API changes its result, without
needing a full AI-analysis pipeline just to get an Analysis row.

Covers spec section 8's test list:
  - Role permissions actually blocking disallowed roles
  - Admin access (every /api/admin/* endpoint requires an admin)
  - Unauthorized API calls (a non-admin gets 403 from every admin endpoint)
  - Approval rules (an admin-created rule changes recommended approvals)
  - User deactivation (login refused, existing token stops working)
  - Existing CR access (a deactivated user's own change requests/history
    stay fully visible to everyone else, unaffected)

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import app
from app.models.analysis import Analysis
from app.models.approval_rule import ApprovalRule
from app.models.enums import ApprovalType, ComplexityLevel, UserRole
from app.models.role_permission import RolePermission
from app.models.user import User
from app.services import workflow_rules

client = TestClient(app)


def _unique_email(tag: str = "m21") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@alight.com"


def _register(role: str = None, name: str = "Module21 Tester") -> tuple[dict, int, str]:
    """Registers a real account through the real endpoint (self-service
    signup always makes an Engineer, same as every other test file in this
    suite), then - only if a non-default role was asked for - promotes it
    directly through the database, the same way
    test_workflow_foundation.py::test_admin_can_always_edit does. Returns
    (auth headers, user id, email). The already-issued JWT stays valid
    across the role change because get_current_user looks the user up
    fresh from the database on every request - no new token needed."""
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    user_id = body["user"]["id"]
    if role is not None:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            user.role = UserRole(role)
            db.commit()
    return {"Authorization": f"Bearer {body['access_token']}"}, user_id, email


def _admin() -> tuple[dict, int]:
    headers, user_id, _ = _register(role="admin")
    return headers, user_id


def _create_cr(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add loyalty points sync job",
        "description": "Nightly job to reconcile loyalty points between the POS and the loyalty service.",
        "business_objective": "Keep loyalty balances accurate across systems.",
        "priority": "medium",
        "requested_by": "Casey Alight",
        "target_system": "Loyalty Service",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


# --- Admin access / unauthorized API calls (spec section 8) ---------------


def test_non_admin_gets_403_from_every_admin_endpoint():
    headers, _, _ = _register()  # plain Engineer

    calls = [
        ("GET", "/api/admin/users", None),
        ("POST", "/api/admin/users", {"name": "X", "email": _unique_email(), "password": "supersecret123"}),
        ("PATCH", "/api/admin/users/1", {"is_active": False}),
        ("GET", "/api/admin/audit-log", None),
        ("GET", "/api/admin/permissions", None),
        ("PUT", "/api/admin/permissions", {"permissions": []}),
        ("GET", "/api/admin/approval-rules", None),
        (
            "POST",
            "/api/admin/approval-rules",
            {"rule_type": "risk", "match_value": "low", "approval_types": ["qa"]},
        ),
        ("PATCH", "/api/admin/approval-rules/1", {"enabled": False}),
        ("DELETE", "/api/admin/approval-rules/1", None),
        ("GET", "/api/admin/system-settings", None),
        ("PUT", "/api/admin/system-settings/cr-categories", {"categories": ["Feature"]}),
    ]
    for method, path, body in calls:
        response = client.request(method, path, json=body, headers=headers)
        assert response.status_code == 403, f"{method} {path} should be 403 for a non-admin, got {response.status_code}"


def test_unauthenticated_call_gets_401_not_403():
    # No Authorization header at all - should fail at authentication, before
    # the admin-role check even runs.
    response = client.get("/api/admin/users")
    assert response.status_code == 401


def test_admin_can_reach_every_admin_endpoint():
    headers, _ = _admin()

    assert client.get("/api/admin/users", headers=headers).status_code == 200
    assert client.get("/api/admin/audit-log", headers=headers).status_code == 200
    assert client.get("/api/admin/permissions", headers=headers).status_code == 200
    assert client.get("/api/admin/approval-rules", headers=headers).status_code == 200
    assert client.get("/api/admin/system-settings", headers=headers).status_code == 200

    created = client.post(
        "/api/admin/users",
        json={"name": "New Hire", "email": _unique_email(), "password": "supersecret123", "role": "engineer"},
        headers=headers,
    )
    assert created.status_code == 201
    assert "password" not in created.json() and "password_hash" not in created.json()


def test_administration_capability_can_never_be_edited_through_permissions_endpoint():
    headers, _ = _admin()
    response = client.put(
        "/api/admin/permissions",
        json={"permissions": [{"role": "engineer", "capability": "administration", "allowed": True}]},
        headers=headers,
    )
    assert response.status_code == 400


# --- Role permissions actually blocking disallowed roles -------------------


def test_permissions_matrix_actually_blocks_and_unblocks_cr_creation():
    admin_headers, _ = _admin()
    requester_headers, _, _ = _register(role="requester")

    # Default permissions (seeded True for every non-Administration
    # capability) - a Requester can create a CR out of the box.
    ok = client.post(
        "/api/change-requests",
        json={
            "title": "Requester-created CR",
            "description": "A CR created while cr_create is still allowed for Requester.",
            "priority": "low",
            "requested_by": "Casey Alight",
            "target_system": "POS Backend",
        },
        headers=requester_headers,
    )
    assert ok.status_code == 201

    # Admin turns cr_create OFF for Requester.
    updated = client.put(
        "/api/admin/permissions",
        json={"permissions": [{"role": "requester", "capability": "cr_create", "allowed": False}]},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    row = next(p for p in updated.json() if p["role"] == "requester" and p["capability"] == "cr_create")
    assert row["allowed"] is False

    blocked = client.post(
        "/api/change-requests",
        json={
            "title": "Should be blocked",
            "description": "A CR create attempt after cr_create was turned off for Requester.",
            "priority": "low",
            "requested_by": "Casey Alight",
            "target_system": "POS Backend",
        },
        headers=requester_headers,
    )
    assert blocked.status_code == 403

    # An Engineer (untouched by the change above) is unaffected.
    engineer_headers, _, _ = _register(role="engineer")
    still_ok = client.post(
        "/api/change-requests",
        json={
            "title": "Engineer-created CR",
            "description": "Engineer's cr_create permission was never touched.",
            "priority": "low",
            "requested_by": "Casey Alight",
            "target_system": "POS Backend",
        },
        headers=engineer_headers,
    )
    assert still_ok.status_code == 201

    # Turn it back on - Requester can create again.
    restored = client.put(
        "/api/admin/permissions",
        json={"permissions": [{"role": "requester", "capability": "cr_create", "allowed": True}]},
        headers=admin_headers,
    )
    assert restored.status_code == 200
    restored_again = client.post(
        "/api/change-requests",
        json={
            "title": "Requester-created CR again",
            "description": "A CR created after cr_create was turned back on for Requester.",
            "priority": "low",
            "requested_by": "Casey Alight",
            "target_system": "POS Backend",
        },
        headers=requester_headers,
    )
    assert restored_again.status_code == 201


def test_admin_is_never_blocked_by_the_permissions_matrix():
    admin_headers, _ = _admin()
    # Turn cr_create off for Admin too - has_permission() still bypasses
    # the matrix entirely for an admin (same superuser convention as
    # is_admin() everywhere else in this app).
    client.put(
        "/api/admin/permissions",
        json={"permissions": [{"role": "admin", "capability": "cr_create", "allowed": False}]},
        headers=admin_headers,
    )
    response = client.post(
        "/api/change-requests",
        json={
            "title": "Admin-created CR",
            "description": "Admins bypass the permissions matrix entirely.",
            "priority": "low",
            "requested_by": "Casey Alight",
            "target_system": "POS Backend",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201


# --- Approval rules (spec section 4) ---------------------------------------


def _fake_low_risk_analysis() -> Analysis:
    analysis = Analysis(
        change_request_id=0,
        summary="s",
        category="Feature",
        complexity=ComplexityLevel.LOW,
        risk_score=10,  # risk_bucket(10) == "low"
        confidence_score=90,
    )
    analysis.risks = []
    return analysis


def test_admin_created_approval_rule_actually_changes_recommended_approvals():
    admin_headers, _ = _admin()
    from app.models.change_request import ChangeRequest

    cr = ChangeRequest(title="t", description="d", target_system="Reporting Dashboard")

    # Before the custom rule exists, a low-risk CR with no admin-configured
    # rules for "low" requires nothing (rules=[] - no fallback to the old
    # hardcoded matrix once rules are being passed at all).
    before = workflow_rules.required_approval_types(cr, _fake_low_risk_analysis(), rules=[])
    assert before == set()

    created = client.post(
        "/api/admin/approval-rules",
        json={"rule_type": "risk", "match_value": "low", "approval_types": ["qa"], "enabled": True},
        headers=admin_headers,
    )
    assert created.status_code == 201
    rule_id = created.json()["id"]

    with SessionLocal() as db:
        rules = db.query(ApprovalRule).filter(ApprovalRule.id == rule_id).all()
        after = workflow_rules.required_approval_types(cr, _fake_low_risk_analysis(), rules=rules)
    assert after == {ApprovalType.QA}

    # Disabling the rule through the real PATCH endpoint takes it back out.
    disabled = client.patch(
        f"/api/admin/approval-rules/{rule_id}", json={"enabled": False}, headers=admin_headers
    )
    assert disabled.status_code == 200
    with SessionLocal() as db:
        rules = db.query(ApprovalRule).filter(ApprovalRule.id == rule_id).all()
        after_disabled = workflow_rules.required_approval_types(cr, _fake_low_risk_analysis(), rules=rules)
    assert after_disabled == set()

    # Clean up so this rule doesn't leak into other tests in this file that
    # exercise a fresh low-risk CR through the real recommended-approvals
    # endpoint.
    client.delete(f"/api/admin/approval-rules/{rule_id}", headers=admin_headers)


def test_approval_rule_create_rejects_unknown_risk_bucket_and_unknown_approval_type():
    admin_headers, _ = _admin()

    bad_bucket = client.post(
        "/api/admin/approval-rules",
        json={"rule_type": "risk", "match_value": "extreme", "approval_types": ["qa"]},
        headers=admin_headers,
    )
    assert bad_bucket.status_code == 422

    bad_type = client.post(
        "/api/admin/approval-rules",
        json={"rule_type": "category", "match_value": "checkout", "approval_types": ["not_a_real_type"]},
        headers=admin_headers,
    )
    assert bad_type.status_code == 422


# --- User deactivation (spec section 1/8) ----------------------------------


def test_deactivated_user_cannot_log_in_and_loses_existing_token_access():
    admin_headers, _ = _admin()
    headers, user_id, email = _register()
    password = "supersecret123"

    # Token works before deactivation.
    assert client.get("/auth/me", headers=headers).status_code == 200

    deactivate = client.patch(f"/api/admin/users/{user_id}", json={"is_active": False}, headers=admin_headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    # The already-issued token now fails on its very next request.
    still_using_old_token = client.get("/auth/me", headers=headers)
    assert still_using_old_token.status_code == 401

    # A fresh login attempt is refused with 403 (account exists, wrong
    # state) rather than a generic 401 (which would look like a bad
    # password).
    login_attempt = client.post("/auth/login", json={"email": email, "password": password})
    assert login_attempt.status_code == 403

    # Re-activating restores both.
    reactivate = client.patch(f"/api/admin/users/{user_id}", json={"is_active": True}, headers=admin_headers)
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True
    login_again = client.post("/auth/login", json={"email": email, "password": password})
    assert login_again.status_code == 200


def test_admin_cannot_deactivate_or_demote_their_own_account():
    admin_headers, admin_id = _admin()

    self_deactivate = client.patch(f"/api/admin/users/{admin_id}", json={"is_active": False}, headers=admin_headers)
    assert self_deactivate.status_code == 400

    self_demote = client.patch(f"/api/admin/users/{admin_id}", json={"role": "engineer"}, headers=admin_headers)
    assert self_demote.status_code == 400


def test_wrong_password_still_gives_generic_401_not_a_deactivated_hint():
    # Guards against leaking "this account exists but is deactivated" to a
    # wrong-password guess - a deactivated account with the WRONG password
    # still gets the same generic 401 an active account would.
    admin_headers, _ = _admin()
    headers, user_id, email = _register()
    client.patch(f"/api/admin/users/{user_id}", json={"is_active": False}, headers=admin_headers)

    response = client.post("/auth/login", json={"email": email, "password": "totally-wrong-password"})
    assert response.status_code == 401


# --- Existing CR access (spec section 8) -----------------------------------


def test_deactivated_users_existing_change_requests_and_history_stay_visible_to_others():
    admin_headers, _ = _admin()
    creator_headers, creator_id, _ = _register(name="Soon Deactivated")
    created = _create_cr(creator_headers)
    cr_id = created["id"]

    deactivate = client.patch(f"/api/admin/users/{creator_id}", json={"is_active": False}, headers=admin_headers)
    assert deactivate.status_code == 200

    other_headers, _, _ = _register(name="Unrelated Viewer")

    detail = client.get(f"/api/change-requests/{cr_id}", headers=other_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == cr_id

    history = client.get(f"/api/change-requests/{cr_id}/history", headers=other_headers)
    assert history.status_code == 200

    listing = client.get("/api/change-requests", headers=other_headers)
    assert listing.status_code == 200
    assert any(item["id"] == cr_id for item in listing.json()["items"])

    # Admin can see it too.
    admin_view = client.get(f"/api/change-requests/{cr_id}", headers=admin_headers)
    assert admin_view.status_code == 200


# --- Roles reused / labels (spec section 2) --------------------------------


def test_manager_role_reuses_product_manager_wire_value():
    # Module 21's "Manager" role is a display label over the existing
    # product_manager wire value, not a new enum member - a user created
    # with role=product_manager round-trips correctly through the admin
    # API and is a real, valid role for permission checks.
    admin_headers, _ = _admin()
    created = client.post(
        "/api/admin/users",
        json={
            "name": "A Manager",
            "email": _unique_email(),
            "password": "supersecret123",
            "role": "product_manager",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    assert created.json()["role"] == "product_manager"

    with SessionLocal() as db:
        row = (
            db.query(RolePermission)
            .filter(RolePermission.role == UserRole.PRODUCT_MANAGER)
            .first()
        )
        assert row is not None  # init_db seeded a permissions row for this role too


# --- System settings (spec section 5) --------------------------------------


def test_cr_categories_are_editable_but_secrets_are_never_exposed():
    admin_headers, _ = _admin()

    settings = client.get("/api/admin/system-settings", headers=admin_headers).json()
    assert "cr_categories" in settings
    assert "api_key_configured" in settings["ai_provider"]
    # Never a raw key anywhere in the response.
    assert "api_key" not in settings["ai_provider"]
    assert "secret" not in str(settings).lower()

    new_categories = settings["cr_categories"] + ["Integration Test Category"]
    updated = client.put(
        "/api/admin/system-settings/cr-categories", json={"categories": new_categories}, headers=admin_headers
    )
    assert updated.status_code == 200
    assert "Integration Test Category" in updated.json()

    empty = client.put("/api/admin/system-settings/cr-categories", json={"categories": []}, headers=admin_headers)
    assert empty.status_code == 422
