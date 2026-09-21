"""Module 12 (Enterprise Workflow), Phase 1: the foundation - new tables
(versions, audit history, assignments, approvals, comments, notifications),
the expanded status lifecycle, the approval matrix, the "is analysis
outdated" check, and the per-CR permission helpers. No new API endpoints
yet (those come in later phases) - this exercises the models and
app/services/workflow_rules.py directly.

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import app
from app.models.analysis import Analysis
from app.models.approval import Approval
from app.models.change_request import ChangeRequest
from app.models.change_request_assignment import ChangeRequestAssignment
from app.models.change_request_history import ChangeRequestHistory
from app.models.change_request_version import ChangeRequestVersion
from app.models.comment import ChangeRequestComment
from app.models.enums import (
    ApprovalStatus,
    ApprovalType,
    AssignmentRole,
    ChangeRequestStatus,
    ComplexityLevel,
    HistoryAction,
    NotificationType,
    Priority,
    RiskCategory,
    Severity,
    UserRole,
)
from app.models.notification import Notification
from app.models.risk import Risk
from app.models.user import User
from app.services import workflow_rules

client = TestClient(app)


def _unique_email() -> str:
    return f"wf-{uuid.uuid4().hex[:10]}@example.com"


def _auth(role: str = "engineer") -> tuple[dict, int]:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Workflow Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _create_cr_via_api(headers: dict, **overrides) -> dict:
    payload = {
        "title": "Add OTP authentication",
        "description": "Allow customers to log in using OTP sent to their registered mobile number.",
        "priority": "medium",
        "requested_by": "Shivani",
        "target_system": "Mobile App",
    }
    payload.update(overrides)
    response = client.post("/api/change-requests", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


# --- New rows get a real version 1 without needing the backfill --------


def test_new_change_request_gets_current_version_1():
    headers, _ = _auth()
    created = _create_cr_via_api(headers)
    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        assert cr.current_version == 1


# --- Backfill: existing rows (current_version left NULL, as a pre-Module-12
# row would be) get fixed up by init_db() -----------------------------------


def test_backfill_gives_pre_existing_rows_version_1_and_a_baseline_version_and_history():
    headers, user_id = _auth()
    created = _create_cr_via_api(headers)

    # Simulate a CR that existed before this column/table existed: null out
    # current_version and remove the version/history rows create_change_request()
    # itself now writes, the way a real pre-Module-12 row would sit in the
    # database before init_db() ever ran the backfill (no version or history
    # rows at all, since those tables didn't exist yet either).
    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        cr.current_version = None
        db.query(ChangeRequestVersion).filter(ChangeRequestVersion.change_request_id == cr.id).delete()
        db.query(ChangeRequestHistory).filter(ChangeRequestHistory.change_request_id == cr.id).delete()
        db.commit()

    init_db()  # re-run - this is what happens on every backend startup

    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        assert cr.current_version == 1

        version = (
            db.query(ChangeRequestVersion)
            .filter(ChangeRequestVersion.change_request_id == cr.id, ChangeRequestVersion.version_number == 1)
            .first()
        )
        assert version is not None
        assert version.change_summary == "Initial version imported."
        assert '"title"' in version.snapshot

        created_event = (
            db.query(ChangeRequestHistory)
            .filter(
                ChangeRequestHistory.change_request_id == cr.id,
                ChangeRequestHistory.action == HistoryAction.CREATED,
            )
            .first()
        )
        assert created_event is not None
        assert created_event.user_id == user_id


def test_backfill_is_idempotent_no_duplicate_version_rows():
    headers, _ = _auth()
    created = _create_cr_via_api(headers)
    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        cr.current_version = None
        db.query(ChangeRequestVersion).filter(ChangeRequestVersion.change_request_id == cr.id).delete()
        db.query(ChangeRequestHistory).filter(ChangeRequestHistory.change_request_id == cr.id).delete()
        db.commit()

    init_db()
    init_db()  # running it twice in a row must not double up

    with SessionLocal() as db:
        count = (
            db.query(ChangeRequestVersion)
            .filter(ChangeRequestVersion.change_request_id == created["id"])
            .count()
        )
        assert count == 1


def test_backfill_does_not_duplicate_the_version_and_history_rows_creation_already_wrote():
    """Regression guard: create_change_request() already writes a version-1
    row and a CREATED history event for every brand-new CR. If current_version
    alone ever ends up NULL on such a row (without its version/history rows
    being touched), the backfill must recognize they already exist rather
    than blindly inserting a second set."""
    headers, user_id = _auth()
    created = _create_cr_via_api(headers)

    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        cr.current_version = None
        db.commit()

    init_db()

    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        assert cr.current_version == 1

        versions = (
            db.query(ChangeRequestVersion)
            .filter(ChangeRequestVersion.change_request_id == cr.id, ChangeRequestVersion.version_number == 1)
            .all()
        )
        assert len(versions) == 1
        assert versions[0].change_summary == "Change request created."  # the original, not overwritten

        created_events = (
            db.query(ChangeRequestHistory)
            .filter(
                ChangeRequestHistory.change_request_id == cr.id,
                ChangeRequestHistory.action == HistoryAction.CREATED,
            )
            .all()
        )
        assert len(created_events) == 1
        assert created_events[0].user_id == user_id


# --- Status transition graph ------------------------------------------


def test_valid_transitions_allowed():
    assert workflow_rules.can_transition(ChangeRequestStatus.IN_REVIEW, ChangeRequestStatus.CHANGES_REQUESTED)
    assert workflow_rules.can_transition(ChangeRequestStatus.IN_REVIEW, ChangeRequestStatus.APPROVAL_REQUIRED)
    assert workflow_rules.can_transition(ChangeRequestStatus.APPROVAL_REQUIRED, ChangeRequestStatus.APPROVED)
    assert workflow_rules.can_transition(ChangeRequestStatus.VALIDATED, ChangeRequestStatus.CLOSED)


def test_invalid_transitions_rejected():
    # Can't skip straight from Draft to Approved.
    assert not workflow_rules.can_transition(ChangeRequestStatus.DRAFT, ChangeRequestStatus.APPROVED)
    # Closed is terminal.
    assert not workflow_rules.can_transition(ChangeRequestStatus.CLOSED, ChangeRequestStatus.IN_PROGRESS)
    # No-op "transition" to the same status isn't a transition.
    assert not workflow_rules.can_transition(ChangeRequestStatus.APPROVED, ChangeRequestStatus.APPROVED)


def test_reason_required_for_sensitive_transitions():
    assert workflow_rules.reason_required(ChangeRequestStatus.CHANGES_REQUESTED)
    assert workflow_rules.reason_required(ChangeRequestStatus.REJECTED)
    assert workflow_rules.reason_required(ChangeRequestStatus.CANCELLED)
    assert not workflow_rules.reason_required(ChangeRequestStatus.APPROVED)


# --- Approval matrix (AI-driven recommendation, never an auto-approval) ---


def _fake_analysis(risk_score: float, category: str = "Feature", security_risk: bool = False) -> Analysis:
    analysis = Analysis(
        change_request_id=0,
        summary="s",
        category=category,
        complexity=ComplexityLevel.MEDIUM,
        risk_score=risk_score,
        confidence_score=90,
    )
    if security_risk:
        analysis.risks = [
            Risk(category=RiskCategory.SECURITY, severity=Severity.HIGH, probability=0.5, score=80, description="d")
        ]
    else:
        analysis.risks = []
    return analysis


def test_low_risk_requires_only_technical_approval():
    cr = ChangeRequest(title="t", description="d", target_system="Reporting Dashboard")
    required = workflow_rules.required_approval_types(cr, _fake_analysis(10, category="Feature"))
    assert required == {ApprovalType.TECHNICAL}


def test_critical_risk_requires_manager_security_and_director():
    cr = ChangeRequest(title="t", description="d", target_system="Reporting Dashboard")
    required = workflow_rules.required_approval_types(cr, _fake_analysis(90, category="Feature"))
    assert {ApprovalType.ENGINEERING_MANAGER, ApprovalType.SECURITY, ApprovalType.DIRECTOR} <= required


def test_security_finding_always_adds_security_approval_even_at_low_risk():
    cr = ChangeRequest(title="t", description="d", target_system="Reporting Dashboard")
    required = workflow_rules.required_approval_types(cr, _fake_analysis(10, category="Feature", security_risk=True))
    assert ApprovalType.SECURITY in required


def test_customer_facing_target_system_adds_product_approval():
    cr = ChangeRequest(title="t", description="d", target_system="Mobile App")
    required = workflow_rules.required_approval_types(cr, _fake_analysis(10, category="Feature"))
    assert ApprovalType.PRODUCT in required


# --- AI analysis version awareness --------------------------------------


def test_analysis_outdated_when_cr_version_moves_past_it():
    cr = ChangeRequest(title="t", description="d")
    cr.current_version = 2
    analysis = _fake_analysis(10)
    analysis.change_request_version = 1
    assert workflow_rules.is_analysis_outdated(cr, analysis)


def test_analysis_up_to_date_when_versions_match():
    cr = ChangeRequest(title="t", description="d")
    cr.current_version = 3
    analysis = _fake_analysis(10)
    analysis.change_request_version = 3
    assert not workflow_rules.is_analysis_outdated(cr, analysis)


def test_no_analysis_is_not_reported_as_outdated():
    cr = ChangeRequest(title="t", description="d")
    cr.current_version = 1
    assert not workflow_rules.is_analysis_outdated(cr, None)


# --- Permissions -----------------------------------------------------------


def test_creator_can_edit_own_cr():
    headers, user_id = _auth()
    created = _create_cr_via_api(headers)
    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        user = db.get(User, user_id)
        assert workflow_rules.can_edit_change_request(user, cr, [])


def test_unrelated_user_cannot_edit():
    headers, _ = _auth()
    created = _create_cr_via_api(headers)
    other_headers, other_id = _auth()
    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        other_user = db.get(User, other_id)
        assert not workflow_rules.can_edit_change_request(other_user, cr, [])


def test_assigned_owner_can_edit_even_if_not_creator():
    headers, _ = _auth()
    created = _create_cr_via_api(headers)
    owner_headers, owner_id = _auth()
    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        owner_user = db.get(User, owner_id)
        assignment = ChangeRequestAssignment(
            change_request_id=cr.id, user_id=owner_id, role=AssignmentRole.OWNER, assigned_by=owner_id
        )
        assert workflow_rules.can_edit_change_request(owner_user, cr, [assignment])


def test_admin_can_always_edit():
    headers, _ = _auth()
    created = _create_cr_via_api(headers)
    with SessionLocal() as db:
        cr = db.get(ChangeRequest, created["id"])
        admin = User(name="Admin", email=_unique_email(), password_hash="x", role=UserRole.ADMIN)
        db.add(admin)
        db.commit()
        db.refresh(admin)
        assert workflow_rules.can_edit_change_request(admin, cr, [])


# --- New tables round-trip through real relationships -----------------


def test_history_version_assignment_approval_comment_notification_roundtrip():
    headers, user_id = _auth()
    created = _create_cr_via_api(headers)
    cr_id = created["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)

        db.add(
            ChangeRequestHistory(
                change_request_id=cr_id,
                user_id=user_id,
                action=HistoryAction.FIELD_CHANGED,
                field_name="priority",
                old_value="medium",
                new_value="high",
                reason=None,
            )
        )
        db.add(
            ChangeRequestVersion(
                change_request_id=cr_id,
                version_number=2,
                changed_by=user_id,
                change_summary="Priority changed from Medium to High",
                snapshot="{}",
            )
        )
        db.add(
            ChangeRequestAssignment(
                change_request_id=cr_id, user_id=user_id, role=AssignmentRole.SECURITY_REVIEWER, assigned_by=user_id
            )
        )
        approval = Approval(
            change_request_id=cr_id,
            approver_id=user_id,
            approval_type=ApprovalType.SECURITY,
            status=ApprovalStatus.PENDING,
            requested_by=user_id,
            cr_version=1,
        )
        db.add(approval)
        db.add(ChangeRequestComment(change_request_id=cr_id, user_id=user_id, body="Please define OTP retry limits."))
        db.add(
            Notification(
                user_id=user_id,
                type=NotificationType.APPROVAL_REQUESTED,
                title="Approval requested",
                message="You were tagged for Security Approval.",
                change_request_id=cr_id,
            )
        )
        db.commit()

        cr = db.get(ChangeRequest, cr_id)
        assert len(cr.history) >= 1
        assert any(v.version_number == 2 for v in cr.versions)
        assert any(a.role == AssignmentRole.SECURITY_REVIEWER for a in cr.assignments)
        assert any(a.approval_type == ApprovalType.SECURITY for a in cr.approvals)
        assert len(cr.comments) == 1
        assert cr.comments[0].body.startswith("Please define")

        notification = db.query(Notification).filter(Notification.change_request_id == cr_id).first()
        assert notification is not None
        assert notification.is_read is False
