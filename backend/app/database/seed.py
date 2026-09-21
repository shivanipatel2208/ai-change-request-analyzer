"""Optional demo data - NOT run automatically on startup. Handy for manually
poking at the database (or the dashboard) without waiting on the AI module
to exist. Safe to run more than once - skips seeding if the demo user
already exists.

Run with (from backend/):

    python -m app.database.seed
"""
from datetime import datetime, timedelta

from app.database.init_db import init_db
from app.database.session import SessionLocal
from app.models import Analysis, ChangeRequest, ClarificationQuestion, User
from app.models.enums import ApprovalRecommendation, ChangeRequestStatus, ComplexityLevel, Priority, UserRole

DEMO_EMAIL = "demo@alight.com"


def _days_ago(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def seed_demo_data() -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if existing:
            print("Demo data already present - skipping.")
            return

        demo_user = User(
            name="Demo User",
            email=DEMO_EMAIL,
            password_hash="not-a-real-hash",  # placeholder - not meant to be logged into
            role=UserRole.ENGINEER,
        )
        db.add(demo_user)
        db.flush()  # assigns demo_user.id without committing yet

        # A spread of requests across statuses, priorities, and (for most of
        # them) an analysis with a different risk/category/complexity - gives
        # the dashboard real variety to render instead of all-zero charts.
        change_requests = [
            ChangeRequest(
                title="Add dark mode to the POS dashboard",
                description=(
                    "Staff have asked for a dark theme option in the POS dashboard "
                    "to reduce eye strain during night shifts."
                ),
                business_objective="Improve staff comfort and reduce eye strain during night shifts.",
                priority=Priority.MEDIUM,
                status=ChangeRequestStatus.DRAFT,
                created_by=demo_user.id,
                created_at=_days_ago(1),
                updated_at=_days_ago(1),
            ),
            ChangeRequest(
                title="Migrate payment processing to new gateway",
                description="Replace the current payment gateway integration with the new provider's API.",
                business_objective="Lower per-transaction processing fees.",
                priority=Priority.HIGH,
                status=ChangeRequestStatus.IN_REVIEW,
                created_by=demo_user.id,
                created_at=_days_ago(6),
                updated_at=_days_ago(2),
            ),
            ChangeRequest(
                title="Fix inventory count rounding bug",
                description="Fractional inventory counts are rounding incorrectly on the stock report.",
                business_objective="Ensure stock reports match actual inventory.",
                priority=Priority.LOW,
                status=ChangeRequestStatus.APPROVED,
                created_by=demo_user.id,
                created_at=_days_ago(10),
                updated_at=_days_ago(9),
            ),
            ChangeRequest(
                title="Add role-based access control to admin panel",
                description="Restrict admin panel sections by user role instead of a single admin flag.",
                business_objective="Reduce risk of accidental or unauthorized changes by staff.",
                priority=Priority.HIGH,
                status=ChangeRequestStatus.SUBMITTED,
                created_by=demo_user.id,
                created_at=_days_ago(3),
                updated_at=_days_ago(3),
            ),
            ChangeRequest(
                title="Upgrade PostgreSQL to v16",
                description="Upgrade the production database engine to the latest major version.",
                business_objective="Stay on a supported database version.",
                priority=Priority.MEDIUM,
                status=ChangeRequestStatus.REJECTED,
                created_by=demo_user.id,
                created_at=_days_ago(14),
                updated_at=_days_ago(12),
            ),
            ChangeRequest(
                title="Add barcode scanner API endpoint",
                description="Expose an endpoint the handheld scanner hardware can call directly.",
                business_objective="Speed up receiving workflow.",
                priority=Priority.MEDIUM,
                status=ChangeRequestStatus.IMPLEMENTED,
                created_by=demo_user.id,
                created_at=_days_ago(20),
                updated_at=_days_ago(15),
            ),
        ]
        db.add_all(change_requests)
        db.flush()  # assigns ids without committing yet

        payment_cr, inventory_cr, rbac_cr, postgres_cr, barcode_cr = change_requests[1:]

        analyses = [
            Analysis(
                change_request_id=payment_cr.id,
                summary="High-impact integration change touching payment flow and third-party API.",
                category="Integration",
                complexity=ComplexityLevel.HIGH,
                risk_score=82.0,
                confidence_score=74.0,
                recommendation=ApprovalRecommendation.NEEDS_MORE_INFO,
                created_at=_days_ago(2),
            ),
            Analysis(
                change_request_id=inventory_cr.id,
                summary="Small, well-contained rounding fix in one report calculation.",
                category="Bug Fix",
                complexity=ComplexityLevel.LOW,
                risk_score=12.0,
                confidence_score=91.0,
                recommendation=ApprovalRecommendation.APPROVE,
                created_at=_days_ago(9),
            ),
            Analysis(
                change_request_id=rbac_cr.id,
                summary="Access-control change with meaningful security surface area.",
                category="Security",
                complexity=ComplexityLevel.HIGH,
                risk_score=61.0,
                confidence_score=68.0,
                recommendation=ApprovalRecommendation.APPROVE_WITH_CONDITIONS,
                created_at=_days_ago(3),
            ),
            Analysis(
                change_request_id=postgres_cr.id,
                summary="Infrastructure upgrade with moderate compatibility risk.",
                category="Infrastructure",
                complexity=ComplexityLevel.MEDIUM,
                risk_score=45.0,
                confidence_score=70.0,
                recommendation=ApprovalRecommendation.REJECT,
                created_at=_days_ago(12),
            ),
            Analysis(
                change_request_id=barcode_cr.id,
                summary="New, narrowly-scoped API endpoint with existing auth reused.",
                category="API",
                complexity=ComplexityLevel.MEDIUM,
                risk_score=33.0,
                confidence_score=80.0,
                recommendation=ApprovalRecommendation.APPROVE,
                created_at=_days_ago(15),
            ),
        ]
        db.add_all(analyses)
        db.flush()

        payment_analysis = analyses[0]
        db.add_all(
            [
                ClarificationQuestion(
                    analysis_id=payment_analysis.id,
                    question="Which fallback happens if the new gateway's API is unreachable mid-transaction?",
                    priority=Priority.HIGH,
                    reason="Payment failures need a defined fallback before this can be approved.",
                    resolved=False,
                ),
                ClarificationQuestion(
                    analysis_id=payment_analysis.id,
                    question="Has the new gateway been confirmed PCI-DSS compliant?",
                    priority=Priority.HIGH,
                    reason="Compliance must be confirmed for anything touching card data.",
                    resolved=True,
                ),
            ]
        )

        db.commit()
        print(
            f"Seeded demo user (id={demo_user.id}), {len(change_requests)} change requests, "
            f"{len(analyses)} analyses, and 2 clarification questions."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
