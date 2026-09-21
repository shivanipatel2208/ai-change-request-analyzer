"""Module 23: hackathon demo data.

Distinct from `seed.py` (background-only, unloggable-into demo user) and
`seed_bulk.py` (3000 anonymous bot accounts for dashboard-at-scale load
testing) - this script's job is different: it creates 5 REAL, LOGGABLE-IN
demo accounts covering this app's five practical roles, one flagship change
request ("Add OTP-based authentication for customers") left deliberately
FRESH and unanalyzed so a presenter runs its AI analysis live, and a handful
of supporting change requests spanning different statuses/priorities/risks
so the Dashboard, CR list, Analytics, and Admin sections all have real
variety to show - see DEMO.md for the actual presentation script.

Every event this script writes (change requests, versions, audit history,
approvals, assignments, comments, notifications) is created through this
project's own real service-layer functions wherever one exists
(app/services/history.py, notify.py, approvals.py, comments.py,
versioning.py) - the exact same code path the live app itself uses - so
none of it is a fabricated shortcut. The one place this script deliberately
does NOT go through the live app's own rules is setting a change request's
`status` field directly rather than through the guarded PUT .../status
endpoint - the same convention `seed.py`/`seed_bulk.py` already use for
background data, since there's no "seed this CR straight into Approved"
service function and there doesn't need to be one.

Safe to run more than once - skips seeding entirely if the demo Admin
account already exists.

Run with (from backend/):

    python -m app.database.seed_demo

Demo credentials (see DEMO.md for the full table): every seeded demo
account shares the password below. These are local, throwaway demo
credentials only - never real ones.
"""
from datetime import datetime, timedelta

from app.core.security import hash_password
from app.database.init_db import init_db
from app.database.session import SessionLocal
from app.models import (
    AffectedComponent,
    Analysis,
    ChangeRequest,
    ChangeRequestVersion,
    Dependency,
    ImpactAssessment,
    ImplementationTask,
    Requirement,
    Risk,
    SecurityFinding,
    TestCase,
    User,
)
from app.models.change_request_assignment import ChangeRequestAssignment
from app.models.enums import (
    ApprovalRecommendation,
    ApprovalStatus,
    ApprovalType,
    AssignmentRole,
    Certainty,
    ChangeRequestStatus,
    ComplexityLevel,
    ComponentType,
    DependencyType,
    HistoryAction,
    ImpactCategory,
    ImpactLevel,
    NotificationType,
    Priority,
    RequirementType,
    RiskCategory,
    SecurityCategory,
    SecurityFindingStatus,
    Severity,
    TestType,
    UserRole,
)
from app.services import approvals as approvals_service
from app.services import comments as comments_service
from app.services import history as history_service
from app.services import notify as notify_service
from app.services import versioning
from app.services import workflow_rules

DEMO_PASSWORD = "AlightDemo123!"  # shared by every seeded demo account - local/throwaway only
ADMIN_EMAIL = "admin@alight.com"


def _days_ago(days: int, hours: int = 0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours)


def _make_user(db, *, name: str, email: str, role: UserRole) -> User:
    user = User(name=name, email=email, password_hash=hash_password(DEMO_PASSWORD), role=role)
    db.add(user)
    db.flush()
    return user


def _create_cr(db, creator: User, *, created_at: datetime, status: ChangeRequestStatus, **fields) -> ChangeRequest:
    """Mirrors app/api/change_requests.py::create_change_request exactly -
    a version 1 snapshot plus a real CREATED history event - so every
    seeded change request has an honest audit trail from the moment it
    exists, not just a bare row with no history behind it."""
    cr = ChangeRequest(
        created_by=creator.id,
        status=status,
        current_version=1,
        created_at=created_at,
        updated_at=created_at,
        **fields,
    )
    db.add(cr)
    db.flush()
    db.add(
        ChangeRequestVersion(
            change_request_id=cr.id,
            version_number=1,
            changed_by=creator.id,
            change_summary="Change request created.",
            snapshot=workflow_rules.build_snapshot(cr),
            created_at=created_at,
        )
    )
    event = history_service.record_event(
        db,
        change_request_id=cr.id,
        action=HistoryAction.CREATED,
        user_id=creator.id,
        version_number=1,
    )
    event.created_at = created_at
    return cr


def _transition_status(
    db, cr: ChangeRequest, actor: User, new_status: ChangeRequestStatus, *, at: datetime, reason: str | None = None
) -> None:
    """Mirrors app/api/change_requests.py::change_status's own history +
    notification side effects exactly (minus the legality/permission
    checks, which don't apply to seed data - same convention seed.py /
    seed_bulk.py already use for setting status directly)."""
    old_label = workflow_rules.STATUS_LABELS.get(cr.status, cr.status.value)
    new_label = workflow_rules.STATUS_LABELS.get(new_status, new_status.value)
    cr.status = new_status
    event = history_service.record_event(
        db,
        change_request_id=cr.id,
        action=HistoryAction.STATUS_CHANGED,
        user_id=actor.id,
        old_value=old_label,
        new_value=new_label,
        reason=reason,
        version_number=cr.current_version or 1,
    )
    event.created_at = at
    interested_ids = {cr.created_by} | {a.user_id for a in cr.assignments}
    interested_ids.discard(actor.id)
    for user_id in interested_ids:
        notify_service.notify(
            db,
            user_id=user_id,
            type=NotificationType.STATUS_CHANGED,
            title=f"CR-{cr.id} moved to {new_label}",
            message=f'{actor.name} moved "{cr.title}" to {new_label}.',
            change_request_id=cr.id,
        )


def _assign(db, cr: ChangeRequest, *, target: User, role: AssignmentRole, assigned_by: User, at: datetime) -> None:
    """Mirrors the real POST .../assignments endpoint's own history +
    notification side effects."""
    db.add(ChangeRequestAssignment(change_request_id=cr.id, user_id=target.id, role=role, assigned_by=assigned_by.id))
    db.flush()
    role_label = workflow_rules.ROLE_LABELS.get(role, role.value)
    event = history_service.record_event(
        db,
        change_request_id=cr.id,
        action=HistoryAction.ASSIGNED,
        user_id=assigned_by.id,
        new_value=f"{target.name} as {role_label}",
        version_number=cr.current_version or 1,
    )
    event.created_at = at
    if target.id != assigned_by.id:
        notify_service.notify(
            db,
            user_id=target.id,
            type=NotificationType.ASSIGNED,
            title=f"You were assigned to CR-{cr.id}",
            message=f'{assigned_by.name} assigned you as {role_label} on "{cr.title}".',
            change_request_id=cr.id,
        )


def _request_approval(
    db, cr: ChangeRequest, *, approval_type: ApprovalType, approver: User, requested_by: User, at: datetime
):
    """Mirrors the real POST .../approvals endpoint's own notification."""
    approval = approvals_service.request_approval(
        db, cr, approval_type=approval_type, approver=approver, requested_by=requested_by
    )
    approval.requested_at = at
    type_label = workflow_rules.APPROVAL_TYPE_LABELS.get(approval_type, approval_type.value)
    if approver.id != requested_by.id:
        notify_service.notify(
            db,
            user_id=approver.id,
            type=NotificationType.APPROVAL_REQUESTED,
            title=f"{type_label} approval requested on CR-{cr.id}",
            message=f'{requested_by.name} asked you for {type_label} approval on "{cr.title}".',
            change_request_id=cr.id,
        )
    return approval


def _respond_approval(db, cr: ChangeRequest, approval, *, new_status: ApprovalStatus, comment: str, responder: User, at: datetime):
    """Mirrors the real POST .../approvals/{id}/respond endpoint's own
    notification."""
    approvals_service.respond_to_approval(db, cr, approval, new_status=new_status, comment=comment, responder=responder)
    approval.responded_at = at
    type_label = workflow_rules.APPROVAL_TYPE_LABELS.get(approval.approval_type, approval.approval_type.value)
    response_type = {
        ApprovalStatus.APPROVED: NotificationType.APPROVED,
        ApprovalStatus.REJECTED: NotificationType.REJECTED,
        ApprovalStatus.CHANGES_REQUESTED: NotificationType.CHANGES_REQUESTED,
    }[new_status]
    if approval.requested_by != responder.id:
        status_label = workflow_rules.APPROVAL_STATUS_LABELS.get(new_status, new_status.value)
        notify_service.notify(
            db,
            user_id=approval.requested_by,
            type=response_type,
            title=f"{type_label} approval {status_label.lower()} on CR-{cr.id}",
            message=f"{responder.name} marked the {type_label} approval you requested as {status_label}.",
            change_request_id=cr.id,
        )


def _comment(db, cr: ChangeRequest, *, author: User, body: str, at: datetime):
    """comments_service.create_comment already records history and sends
    every notification (mentions + interested parties) - see its own
    docstring in app/services/comments.py."""
    comment = comments_service.create_comment(db, cr, author=author, body=body)
    comment.created_at = at
    return comment


def _seed_analysis(
    db,
    cr: ChangeRequest,
    *,
    summary: str,
    category: str,
    complexity: ComplexityLevel,
    risk_score: float,
    confidence_score: float,
    recommendation: ApprovalRecommendation,
    at: datetime,
    requirements: list[dict],
    risks: list[dict],
    impacts: list[dict],
    security_findings: list[dict],
    test_cases: list[dict],
    tasks: list[dict],
    affected_components: list[dict] | None = None,
    dependencies: list[dict] | None = None,
) -> Analysis:
    """Directly seeds an Analysis and its child rows for background/demo
    variety (no real AI call - this is clearly-labeled seed data, same
    spirit as the pre-existing seed.py). Mirrors
    app/services/analysis_engine.py's own two side effects after a real
    analysis completes: an AI_ANALYSIS_COMPLETED history event attributed
    to the system actor "AI Analyzer" (never a human), and auto-advancing
    a Pending Analysis change request straight to Analyzed."""
    analysis = Analysis(
        change_request_id=cr.id,
        change_request_version=cr.current_version or 1,
        summary=summary,
        category=category,
        complexity=complexity,
        risk_score=risk_score,
        confidence_score=confidence_score,
        recommendation=recommendation,
        created_at=at,
    )
    db.add(analysis)
    db.flush()

    for r in requirements:
        db.add(Requirement(analysis_id=analysis.id, **r))
    for r in risks:
        db.add(Risk(analysis_id=analysis.id, **r))
    for i in impacts:
        db.add(ImpactAssessment(analysis_id=analysis.id, **i))
    for s in security_findings:
        db.add(SecurityFinding(analysis_id=analysis.id, **s))
    for t in test_cases:
        db.add(TestCase(analysis_id=analysis.id, **t))
    for t in tasks:
        db.add(ImplementationTask(analysis_id=analysis.id, **t))
    for c in affected_components or []:
        db.add(AffectedComponent(analysis_id=analysis.id, **c))
    for d in dependencies or []:
        db.add(Dependency(analysis_id=analysis.id, **d))

    event = history_service.record_event(
        db,
        change_request_id=cr.id,
        action=HistoryAction.AI_ANALYSIS_COMPLETED,
        actor_label="AI Analyzer",
        new_value=f"Risk score: {round(risk_score)}/100, Complexity: {complexity.value}",
        version_number=cr.current_version or 1,
    )
    event.created_at = at
    if cr.status == ChangeRequestStatus.PENDING_ANALYSIS:
        cr.status = ChangeRequestStatus.ANALYZED
    return analysis


def seed_demo_data() -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if existing:
            print("Demo data already present - skipping.")
            return

        # --- 1. The five demo accounts (spec section 4) --------------------
        admin = _make_user(db, name="Ava Chen", email=ADMIN_EMAIL, role=UserRole.ADMIN)
        manager = _make_user(db, name="Jordan Blake", email="manager@alight.com", role=UserRole.PRODUCT_MANAGER)
        engineer = _make_user(db, name="Liam Carter", email="engineer@alight.com", role=UserRole.ENGINEER)
        security_reviewer = _make_user(
            db, name="Priya Nair", email="security@alight.com", role=UserRole.SECURITY_REVIEWER
        )
        requester = _make_user(db, name="Sofia Reyes", email="requester@alight.com", role=UserRole.REQUESTER)

        # --- 2. The flagship demo CR - fresh, unanalyzed (spec section 1) --
        # Deliberately NOT analyzed here: the presenter runs AI Analysis on
        # this one live, on stage, so the audience sees a real model call -
        # never a canned response standing in for one (spec section 7).
        otp_cr = _create_cr(
            db,
            requester,
            created_at=_days_ago(0, hours=1),
            status=ChangeRequestStatus.PENDING_ANALYSIS,
            title="Add OTP-based authentication for customers",
            description=(
                "Add one-time-password (OTP) verification to customer login on the loyalty portal. "
                "The OTP is sent by SMS to the customer's registered mobile number and must be entered "
                "within a defined expiry window. Requirements: OTP sent to the registered mobile number; "
                "the OTP expires after a defined period; a maximum number of retry attempts before the "
                "code is invalidated; OTP values are never stored in plain text; rate limiting on both "
                "OTP requests and verification attempts to prevent abuse; and every OTP request, "
                "verification attempt, and outcome is written to the audit log."
            ),
            business_objective="Reduce account-takeover fraud on customer logins without adding a hard password-reset burden.",
            priority=Priority.HIGH,
            requested_by="Customer Experience team",
            target_system="Customer Loyalty Portal",
            customer_impact="Customers will see a new verification step at login when signing in from a new device.",
            compliance_requirements="Must not log or store the raw OTP value anywhere, including application logs.",
        )

        # --- 3. Supporting CRs (spec section 3: several CRs, different
        # statuses/priorities/risks, pending + completed + changes-requested
        # approvals, comments, notifications, version history, closed CRs) -

        # A: Analyzed, HIGH risk, a PENDING Technical approval, two versions
        # (a real seeded edit), an assignment, and a comment with an
        # @mention - the richest supporting CR, good for a quick detour if
        # a judge asks "show me another one."
        ledger_cr = _create_cr(
            db,
            requester,
            created_at=_days_ago(8),
            status=ChangeRequestStatus.PENDING_ANALYSIS,
            title="Migrate loyalty points ledger to new database schema",
            description=(
                "Migrate the loyalty points ledger table to a new normalized schema to support "
                "multi-currency point balances. Requires a one-time backfill of existing balances "
                "and a brief read-only maintenance window during cutover."
            ),
            business_objective="Unblock multi-currency loyalty support requested by three regional teams.",
            priority=Priority.HIGH,
            requested_by="Loyalty Platform team",
            target_system="Loyalty Service",
            technical_impact="Touches the production loyalty database directly during cutover.",
        )
        _seed_analysis(
            db,
            ledger_cr,
            at=_days_ago(8),
            summary="Direct schema migration on the production loyalty ledger with a live cutover window.",
            category="Database",
            complexity=ComplexityLevel.HIGH,
            risk_score=72.0,
            confidence_score=76.0,
            recommendation=ApprovalRecommendation.APPROVE_WITH_CONDITIONS,
            requirements=[
                dict(
                    requirement_type=RequirementType.FUNCTIONAL,
                    description="Existing point balances must be backfilled into the new schema with zero data loss.",
                    priority=Priority.HIGH,
                    certainty=Certainty.KNOWN,
                    confidence=90.0,
                ),
                dict(
                    requirement_type=RequirementType.NON_FUNCTIONAL,
                    description="Cutover maintenance window must be read-only, not a full outage.",
                    priority=Priority.HIGH,
                    certainty=Certainty.INFERRED,
                    confidence=70.0,
                ),
            ],
            risks=[
                dict(
                    category=RiskCategory.DATA,
                    description="A failed backfill could corrupt or double-count customer point balances.",
                    severity=Severity.HIGH,
                    probability=0.3,
                    score=72.0,
                    mitigation="Run the backfill against a full production snapshot first and diff the totals before cutover.",
                ),
            ],
            impacts=[
                dict(category=ImpactCategory.TECHNICAL, impact_level=ImpactLevel.HIGH, description="Schema change touches the core ledger table.", certainty=Certainty.KNOWN, confidence=90.0),
                dict(category=ImpactCategory.DATA, impact_level=ImpactLevel.HIGH, description="Requires a full backfill of historical balances.", certainty=Certainty.KNOWN, confidence=85.0),
                dict(category=ImpactCategory.CUSTOMER, impact_level=ImpactLevel.MEDIUM, description="Brief read-only window during cutover.", certainty=Certainty.INFERRED, confidence=65.0),
            ],
            security_findings=[
                dict(category=SecurityCategory.DATA_PROTECTION, finding="Backfill script will handle customer balance data at rest.", severity=Severity.MEDIUM, evidence="Migration touches the loyalty_ledger table directly.", recommendation="Run the backfill inside the existing encrypted database connection, no new export step.", status=SecurityFindingStatus.OPEN),
                dict(category=SecurityCategory.AUDIT_LOGGING, finding="Cutover should be logged as a distinct operational event.", severity=Severity.LOW, evidence="No dedicated migration-event logging exists today.", recommendation="Log migration start/end and row counts to the ops audit log.", status=SecurityFindingStatus.OPEN),
            ],
            test_cases=[
                dict(test_id="TC-101", title="Backfilled balances match pre-migration totals", test_type=TestType.INTEGRATION, priority=Priority.HIGH, description="Sum balances before and after migration.", expected_result="Totals match exactly, per customer and in aggregate."),
                dict(test_id="TC-102", title="Writes are rejected during the read-only window", test_type=TestType.INTEGRATION, priority=Priority.MEDIUM, description="Attempt a balance write during cutover.", expected_result="Write is cleanly rejected, not silently dropped."),
            ],
            tasks=[
                dict(task="Write and dry-run the backfill script", description="Backfill existing balances into the new schema against a snapshot.", component="Loyalty Service", priority=Priority.HIGH, estimated_effort="2 days"),
                dict(task="Add pre/post migration balance reconciliation", description="Automated diff of total balances before and after cutover.", component="Loyalty Service", priority=Priority.HIGH, estimated_effort="1 day"),
            ],
            affected_components=[
                dict(component_name="Loyalty Service", component_type=ComponentType.BACKEND, impact_level=ImpactLevel.HIGH, reason="Owns the ledger table being migrated.", confidence=92.0),
                dict(component_name="Loyalty Database", component_type=ComponentType.DATABASE, impact_level=ImpactLevel.HIGH, reason="Schema change and backfill run directly against it.", confidence=95.0),
            ],
            dependencies=[
                dict(dependency_name="Loyalty Database", dependency_type=DependencyType.DATABASE, impact_level=ImpactLevel.HIGH, reason="Migration must complete before any dependent read/write path is safe."),
            ],
        )
        # A real seeded edit -> version 2, so version history + the
        # outdated-analysis flag are both visible without touching this CR.
        versioning.apply_change_request_update(
            db,
            ledger_cr,
            {"description": ledger_cr.description + " Also adds a rollback script in case cutover needs to be reverted."},
            user=engineer,
        )
        _assign(db, ledger_cr, target=engineer, role=AssignmentRole.OWNER, assigned_by=requester, at=_days_ago(6))
        _assign(db, ledger_cr, target=security_reviewer, role=AssignmentRole.SECURITY_REVIEWER, assigned_by=requester, at=_days_ago(6))
        _comment(
            db, ledger_cr, author=engineer, at=_days_ago(5),
            body="@Priya Nair can you take a look at the backfill script before we request approval? It touches customer balance data directly.",
        )
        _request_approval(db, ledger_cr, approval_type=ApprovalType.TECHNICAL, approver=manager, requested_by=engineer, at=_days_ago(4))

        # B: fully Approved - a completed approval, closed-out lifecycle so
        # far, MEDIUM risk.
        currency_cr = _create_cr(
            db,
            requester,
            created_at=_days_ago(12),
            status=ChangeRequestStatus.PENDING_ANALYSIS,
            title="Add multi-currency support to POS checkout",
            description="Allow POS checkout to accept and total payments in a customer's local currency, not just USD.",
            business_objective="Support three new regional store openings this quarter.",
            priority=Priority.MEDIUM,
            requested_by="Regional Expansion team",
            target_system="POS Checkout",
        )
        _seed_analysis(
            db, currency_cr, at=_days_ago(12),
            summary="Adds currency selection and conversion display to an existing, well-tested checkout flow.",
            category="Feature",
            complexity=ComplexityLevel.MEDIUM,
            risk_score=44.0,
            confidence_score=82.0,
            recommendation=ApprovalRecommendation.APPROVE,
            requirements=[
                dict(requirement_type=RequirementType.FUNCTIONAL, description="Checkout totals display in the customer's selected currency.", priority=Priority.HIGH, certainty=Certainty.KNOWN, confidence=88.0),
            ],
            risks=[
                dict(category=RiskCategory.BUSINESS, description="Incorrect exchange-rate rounding could under- or over-charge customers.", severity=Severity.MEDIUM, probability=0.25, score=44.0, mitigation="Use the existing finance-approved rounding library, not a new implementation."),
            ],
            impacts=[
                dict(category=ImpactCategory.CUSTOMER, impact_level=ImpactLevel.MEDIUM, description="Visible pricing change at checkout.", certainty=Certainty.KNOWN, confidence=85.0),
                dict(category=ImpactCategory.BUSINESS, impact_level=ImpactLevel.MEDIUM, description="Unblocks three regional store openings.", certainty=Certainty.KNOWN, confidence=80.0),
            ],
            security_findings=[
                dict(category=SecurityCategory.API_SECURITY, finding="New currency-rate lookup calls an external rates API.", severity=Severity.LOW, evidence="No existing outbound integration for exchange rates.", recommendation="Cache rates and fail closed to the last known-good rate on lookup failure.", status=SecurityFindingStatus.OPEN),
            ],
            test_cases=[
                dict(test_id="TC-201", title="Checkout total converts correctly to a selected currency", test_type=TestType.INTEGRATION, priority=Priority.HIGH, description="Select a non-USD currency at checkout.", expected_result="Total matches the current exchange rate within rounding tolerance."),
            ],
            tasks=[
                dict(task="Add currency selector to checkout UI", description="Let staff select the transaction currency at checkout.", component="POS Checkout", priority=Priority.MEDIUM, estimated_effort="3 days"),
            ],
        )
        approval_b = _request_approval(db, currency_cr, approval_type=ApprovalType.PRODUCT, approver=manager, requested_by=requester, at=_days_ago(10))
        _respond_approval(db, currency_cr, approval_b, new_status=ApprovalStatus.APPROVED, comment="Looks good - rounding approach matches finance's requirement.", responder=manager, at=_days_ago(9))
        _transition_status(db, currency_cr, manager, ChangeRequestStatus.APPROVED, at=_days_ago(9))

        # C: Changes Requested - shows the "request changes" state (spec
        # section 3) explicitly, with the reviewer's comment attached.
        sync_cr = _create_cr(
            db,
            requester,
            created_at=_days_ago(7),
            status=ChangeRequestStatus.PENDING_ANALYSIS,
            title="Refactor inventory sync job for the new warehouse integration",
            description="Rework the nightly inventory sync job so it can also pull stock levels from the new third-party warehouse system.",
            business_objective="Support the new outsourced warehouse partner going live next month.",
            priority=Priority.MEDIUM,
            requested_by="Warehouse Operations team",
            target_system="Inventory Sync Service",
        )
        _seed_analysis(
            db, sync_cr, at=_days_ago(7),
            summary="Adds a second inbound data source to an existing nightly batch job.",
            category="Integration",
            complexity=ComplexityLevel.MEDIUM,
            risk_score=54.0,
            confidence_score=71.0,
            recommendation=ApprovalRecommendation.NEEDS_MORE_INFO,
            requirements=[
                dict(requirement_type=RequirementType.FUNCTIONAL, description="Nightly job reconciles stock levels from both the existing and new warehouse systems.", priority=Priority.HIGH, certainty=Certainty.KNOWN, confidence=84.0),
            ],
            risks=[
                dict(category=RiskCategory.OPERATIONAL, description="A malformed feed from the new partner could silently zero out stock counts.", severity=Severity.HIGH, probability=0.35, score=54.0, mitigation="Reject and alert on any feed with an implausible swing in total stock, rather than applying it."),
            ],
            impacts=[
                dict(category=ImpactCategory.OPERATIONAL, impact_level=ImpactLevel.MEDIUM, description="Adds a new dependency to the nightly batch job.", certainty=Certainty.KNOWN, confidence=80.0),
            ],
            security_findings=[
                dict(category=SecurityCategory.API_SECURITY, finding="New partner feed is pulled over an external SFTP connection.", severity=Severity.MEDIUM, evidence="No existing external SFTP integration on this job today.", recommendation="Confirm the partner's SFTP endpoint uses key-based auth, not a shared password.", status=SecurityFindingStatus.OPEN),
            ],
            test_cases=[
                dict(test_id="TC-301", title="Malformed partner feed is rejected, not applied", test_type=TestType.INTEGRATION, priority=Priority.HIGH, description="Feed the job a feed with an implausible stock swing.", expected_result="Job rejects the feed and alerts, existing stock levels unchanged."),
            ],
            tasks=[
                dict(task="Add feed sanity-check before applying stock updates", description="Reject a feed whose totals move implausibly versus the prior run.", component="Inventory Sync Service", priority=Priority.HIGH, estimated_effort="2 days"),
            ],
        )
        approval_c = _request_approval(db, sync_cr, approval_type=ApprovalType.TECHNICAL, approver=engineer, requested_by=requester, at=_days_ago(5))
        _respond_approval(
            db, sync_cr, approval_c, new_status=ApprovalStatus.CHANGES_REQUESTED,
            comment="Please add the feed sanity-check as a hard gate before this goes further, not just a task on the plan.",
            responder=engineer, at=_days_ago(4),
        )
        _transition_status(db, sync_cr, engineer, ChangeRequestStatus.CHANGES_REQUESTED, at=_days_ago(4))

        # D: fully Closed - complete lifecycle, LOW risk, older.
        legacy_cr = _create_cr(
            db,
            requester,
            created_at=_days_ago(30),
            status=ChangeRequestStatus.PENDING_ANALYSIS,
            title="Decommission legacy reporting service",
            description="Retire the old nightly reporting service now that Analytics (Module 19) fully replaces its reports.",
            business_objective="Reduce infrastructure cost and maintenance burden of an unused service.",
            priority=Priority.LOW,
            requested_by="Platform team",
            target_system="Legacy Reporting Service",
        )
        _seed_analysis(
            db, legacy_cr, at=_days_ago(30),
            summary="Removal of an already-unused internal service with no remaining consumers.",
            category="Maintenance",
            complexity=ComplexityLevel.LOW,
            risk_score=14.0,
            confidence_score=93.0,
            recommendation=ApprovalRecommendation.APPROVE,
            requirements=[
                dict(requirement_type=RequirementType.TECHNICAL, description="Confirm no remaining consumers before shutdown.", priority=Priority.MEDIUM, certainty=Certainty.KNOWN, confidence=90.0),
            ],
            risks=[
                dict(category=RiskCategory.OPERATIONAL, description="An undiscovered consumer could still depend on this service.", severity=Severity.LOW, probability=0.1, score=14.0, mitigation="Leave the service reachable but logging-only for two weeks before final shutdown."),
            ],
            impacts=[
                dict(category=ImpactCategory.TECHNICAL, impact_level=ImpactLevel.LOW, description="Removes one internal service and its scheduled job.", certainty=Certainty.KNOWN, confidence=90.0),
            ],
            security_findings=[
                dict(category=SecurityCategory.COMPLIANCE, finding="Service holds historical report data that must be retained per policy.", severity=Severity.LOW, evidence="Reports database has not been reviewed for a retention policy.", recommendation="Archive the historical reports database before decommissioning the service itself.", status=SecurityFindingStatus.OPEN),
            ],
            test_cases=[
                dict(test_id="TC-401", title="No remaining callers after shutdown", test_type=TestType.MANUAL, priority=Priority.MEDIUM, description="Monitor access logs for two weeks post-shutdown.", expected_result="Zero requests to the decommissioned service."),
            ],
            tasks=[
                dict(task="Archive historical reports database", description="Export and archive report history before final shutdown.", component="Legacy Reporting Service", priority=Priority.MEDIUM, estimated_effort="1 day"),
            ],
        )
        approval_d = _request_approval(db, legacy_cr, approval_type=ApprovalType.ENGINEERING_MANAGER, approver=manager, requested_by=requester, at=_days_ago(28))
        _respond_approval(db, legacy_cr, approval_d, new_status=ApprovalStatus.APPROVED, comment="Approved - archive the report history first as noted.", responder=manager, at=_days_ago(27))
        for status, at in (
            (ChangeRequestStatus.APPROVED, _days_ago(27)),
            (ChangeRequestStatus.IMPLEMENTATION_PLANNED, _days_ago(20)),
            (ChangeRequestStatus.IN_PROGRESS, _days_ago(15)),
            (ChangeRequestStatus.IMPLEMENTED, _days_ago(5)),
            (ChangeRequestStatus.VALIDATED, _days_ago(3)),
            (ChangeRequestStatus.CLOSED, _days_ago(2)),
        ):
            _transition_status(db, legacy_cr, engineer, status, at=at)

        # E: simple Draft, LOW priority/risk - quick background variety,
        # no analysis yet.
        _create_cr(
            db,
            requester,
            created_at=_days_ago(1),
            status=ChangeRequestStatus.DRAFT,
            title="Add dark mode toggle to staff dashboard",
            description="Staff have asked for a dark theme option in the internal dashboard to reduce eye strain during night shifts.",
            business_objective="Improve staff comfort during night-shift use.",
            priority=Priority.LOW,
            requested_by="Store Operations team",
            target_system="Staff Dashboard",
        )

        # F: mid-lifecycle, In Progress, MEDIUM risk - shows implementation
        # in flight rather than only start/end states.
        sso_cr = _create_cr(
            db,
            requester,
            created_at=_days_ago(15),
            status=ChangeRequestStatus.PENDING_ANALYSIS,
            title="Enable SSO login for admin portal",
            description="Replace the admin portal's separate login with single sign-on against the corporate identity provider.",
            business_objective="Reduce credential sprawl and simplify offboarding for admin accounts.",
            priority=Priority.MEDIUM,
            requested_by="IT Security team",
            target_system="Admin Portal",
        )
        _seed_analysis(
            db, sso_cr, at=_days_ago(15),
            summary="Replaces a self-contained login form with an external identity provider integration.",
            category="Security",
            complexity=ComplexityLevel.MEDIUM,
            risk_score=41.0,
            confidence_score=79.0,
            recommendation=ApprovalRecommendation.APPROVE,
            requirements=[
                dict(requirement_type=RequirementType.FUNCTIONAL, description="Admin accounts log in through the corporate identity provider instead of a local password.", priority=Priority.HIGH, certainty=Certainty.KNOWN, confidence=88.0),
            ],
            risks=[
                dict(category=RiskCategory.SECURITY, description="A misconfigured SSO integration could lock out all admin accounts at once.", severity=Severity.MEDIUM, probability=0.2, score=41.0, mitigation="Keep the existing local-login path available for one admin break-glass account during rollout."),
            ],
            impacts=[
                dict(category=ImpactCategory.SECURITY, impact_level=ImpactLevel.MEDIUM, description="Centralizes admin authentication through the corporate IdP.", certainty=Certainty.KNOWN, confidence=85.0),
            ],
            security_findings=[
                dict(category=SecurityCategory.AUTHENTICATION, finding="Admin login currently uses a locally-stored password, not SSO.", severity=Severity.MEDIUM, evidence="Admin portal has its own login form today.", recommendation="Migrate to the corporate IdP and keep one documented break-glass account.", status=SecurityFindingStatus.OPEN),
            ],
            test_cases=[
                dict(test_id="TC-501", title="Admin can log in via SSO", test_type=TestType.E2E, priority=Priority.HIGH, description="Log in to the admin portal via the corporate IdP.", expected_result="Successful login lands on the admin dashboard."),
            ],
            tasks=[
                dict(task="Integrate corporate IdP for admin login", description="Replace the local login form with an SSO redirect flow.", component="Admin Portal", priority=Priority.MEDIUM, estimated_effort="3 days"),
            ],
        )
        _assign(db, sso_cr, target=engineer, role=AssignmentRole.TECHNICAL_LEAD, assigned_by=requester, at=_days_ago(13))
        for status, at in (
            (ChangeRequestStatus.APPROVAL_REQUIRED, _days_ago(12)),
            (ChangeRequestStatus.APPROVED, _days_ago(11)),
            (ChangeRequestStatus.IMPLEMENTATION_PLANNED, _days_ago(9)),
            (ChangeRequestStatus.IN_PROGRESS, _days_ago(3)),
        ):
            _transition_status(db, sso_cr, engineer, status, at=at)

        db.commit()
        print(
            "Seeded 5 demo accounts (admin/manager/engineer/security/requester@alight.com, "
            f'password "{DEMO_PASSWORD}") and 7 change requests, including the flagship '
            f'"{otp_cr.title}" (CR-{otp_cr.id}), left unanalyzed for a live demo. See DEMO.md.'
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
