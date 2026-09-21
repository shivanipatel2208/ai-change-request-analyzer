"""Bulk synthetic data generator - NOT run automatically. Creates thousands
of realistic-but-clearly-fake change requests (with analyses and
clarification questions) so the dashboard's metrics, risk buckets, category
breakdown, and recent-requests list can all be stress-tested against real
volume - not just the handful of rows seed.py adds.

Every synthetic row is created by one of 5 "Load Test Bot" users
(loadtest1@alight.com .. loadtest5@alight.com) so it's obvious in the data
which rows are load-test filler versus real accounts like yours.

Safe to run more than once - skips (and does nothing) if the bulk synthetic
users already exist. To reset and regenerate, stop the backend and delete
backend/data/app.db, then run init_db again.

Run with (from backend/):

    python -m app.database.seed_bulk           # 3000 change requests
    python -m app.database.seed_bulk 5000       # custom count

This can take anywhere from ~15 seconds to a couple of minutes depending on
your machine - it prints progress every 500 rows so you can see it's working.
"""
import random
import sys
from datetime import datetime, timedelta

from app.database.init_db import init_db
from app.database.session import SessionLocal
from app.models import Analysis, ChangeRequest, ClarificationQuestion, User
from app.models.enums import (
    ApprovalRecommendation,
    ChangeRequestStatus,
    ComplexityLevel,
    Priority,
    UserRole,
)

DEFAULT_COUNT = 3000
CHUNK_SIZE = 500

BULK_USER_EMAILS = [f"loadtest{i}@alight.com" for i in range(1, 6)]

VERBS = [
    "Add", "Update", "Fix", "Remove", "Refactor", "Migrate", "Optimize",
    "Integrate", "Deprecate", "Harden", "Redesign", "Simplify", "Automate",
    "Rebuild", "Extend", "Consolidate", "Streamline",
]
SUBJECTS = [
    "checkout flow", "inventory sync", "user authentication", "reporting dashboard",
    "payment gateway", "loyalty program", "barcode scanner integration", "admin panel",
    "notification service", "search indexing", "tax calculation", "refund workflow",
    "kiosk UI", "printer integration", "menu management", "order queue",
    "table management", "employee scheduling", "customer profiles", "email templates",
    "delivery tracking", "gift card system", "multi-location sync", "offline mode",
    "receipt printing", "self-checkout flow", "franchise reporting", "API rate limiting",
]

CANONICAL_CATEGORIES = ["Feature", "Bug Fix", "Security", "Database", "API", "Infrastructure", "Integration"]
UNUSUAL_CATEGORIES = ["Documentation", "UX Research", "Performance Tuning", "Localization", "Cleanup"]

QUESTION_TEMPLATES = [
    "What is the rollback plan if this fails in production?",
    "Has this been tested against the largest customer's data volume?",
    "Does this require a database migration, and if so, is it reversible?",
    "Are there any third-party dependencies this introduces?",
    "What is the expected impact on existing API consumers?",
    "Has security reviewed the data this change touches?",
]


def _random_datetime_within(days_back: int) -> datetime:
    return datetime.utcnow() - timedelta(days=random.uniform(0, days_back), hours=random.uniform(0, 23))


def seed_bulk_data(count: int = DEFAULT_COUNT) -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == BULK_USER_EMAILS[0]).first()
        if existing:
            print(
                "Bulk synthetic data already present - skipping. "
                "(Delete backend/data/app.db and restart the backend to reset everything.)"
            )
            return

        users = [
            User(name=f"Load Test Bot {i}", email=email, password_hash="not-a-real-hash", role=UserRole.ENGINEER)
            for i, email in enumerate(BULK_USER_EMAILS, start=1)
        ]
        db.add_all(users)
        db.flush()
        user_ids = [u.id for u in users]

        statuses = list(ChangeRequestStatus)
        priorities = list(Priority)
        complexities = list(ComplexityLevel)
        recommendations = list(ApprovalRecommendation)

        total_analyses = 0
        total_questions = 0

        for start in range(0, count, CHUNK_SIZE):
            batch_end = min(start + CHUNK_SIZE, count)
            batch_change_requests = []

            for _ in range(start, batch_end):
                verb = random.choice(VERBS)
                subject = random.choice(SUBJECTS)
                created_at = _random_datetime_within(365)
                cr = ChangeRequest(
                    title=f"{verb} {subject}",
                    description=(
                        f"{verb} {subject} to improve reliability, performance, or usability "
                        f"across the platform. (Synthetic load-test data.)"
                    ),
                    business_objective=f"Support the {subject} initiative.",
                    priority=random.choice(priorities),
                    status=random.choice(statuses),
                    created_by=random.choice(user_ids),
                    created_at=created_at,
                    updated_at=created_at,
                )
                batch_change_requests.append(cr)

            db.add_all(batch_change_requests)
            db.flush()  # assigns ids for the FKs below

            batch_analyses = []
            for cr in batch_change_requests:
                # ~80% of requests have been analyzed at least once; the rest
                # stay "pending analysis" - both states need real coverage.
                if random.random() >= 0.8:
                    continue

                num_analyses = 2 if random.random() < 0.1 else 1  # ~10% re-analyzed
                analysis_time = cr.created_at
                for _ in range(num_analyses):
                    analysis_time = analysis_time + timedelta(hours=random.uniform(1, 72))
                    category = (
                        random.choice(CANONICAL_CATEGORIES)
                        if random.random() < 0.85
                        else random.choice(UNUSUAL_CATEGORIES)
                    )
                    recommendation = random.choice(recommendations) if random.random() < 0.8 else None

                    batch_analyses.append(
                        Analysis(
                            change_request_id=cr.id,
                            summary=f"Synthetic analysis of: {cr.title}.",
                            category=category,
                            complexity=random.choice(complexities),
                            risk_score=round(random.uniform(0, 100), 1),
                            confidence_score=round(random.uniform(40, 99), 1),
                            recommendation=recommendation,
                            created_at=analysis_time,
                        )
                    )

            db.add_all(batch_analyses)
            db.flush()  # assigns ids for the clarification questions below
            total_analyses += len(batch_analyses)

            batch_questions = []
            for analysis in batch_analyses:
                num_questions = random.choices([0, 1, 2, 3], weights=[40, 30, 20, 10])[0]
                for _ in range(num_questions):
                    batch_questions.append(
                        ClarificationQuestion(
                            analysis_id=analysis.id,
                            question=random.choice(QUESTION_TEMPLATES),
                            priority=random.choice(priorities),
                            reason="Needs confirmation before this can be safely approved.",
                            resolved=random.random() < 0.5,
                        )
                    )
            db.add_all(batch_questions)
            total_questions += len(batch_questions)

            db.commit()
            print(f"  ...inserted {batch_end}/{count} change requests so far")

        print(
            f"Done. Added {count} change requests, {total_analyses} analyses, and "
            f"{total_questions} clarification questions, owned by 5 synthetic 'Load Test Bot' users."
        )
    finally:
        db.close()


if __name__ == "__main__":
    requested_count = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_COUNT
    seed_bulk_data(requested_count)
