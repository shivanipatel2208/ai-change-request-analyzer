"""Database initialization - creates all tables if they don't already exist,
and adds any columns a model gained since its table was first created.

Hackathon-simple: no migration framework (Alembic etc.). Base.metadata.
create_all() is idempotent and handles brand-new tables, but it does NOT add
columns to a table that already exists - so when a later module adds a
field to an existing model (e.g. ChangeRequest.target_system in Module 4),
the real SQLite file on disk needs those columns added too, or the app
breaks against anyone's existing database. _add_missing_columns() below
closes that one gap with plain ALTER TABLE statements, safe to run on every
startup.

Called automatically on API startup (see app/main.py), and can also be run
directly:

    python -m app.database.init_db
"""
import json

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app import models  # noqa: F401 - importing registers every model on Base.metadata
from app.database.session import Base, engine


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand new table - create_all() just created it with every column

            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                column_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'))
                print(f"  (migrated) added column: {table.name}.{column.name}")


def _backfill_workflow_data() -> None:
    """Module 12 (Enterprise Workflow): give every pre-existing row a
    sensible starting point instead of leaving the new columns NULL.

    - Every ChangeRequest with no current_version gets current_version=1,
      a Version 1 snapshot (change_summary "Initial version imported."),
      and a matching CREATED history event - a real, honest baseline
      rather than inventing fake prior user actions (spec section 35: "do
      not invent fake user actions").
    - Every Analysis with no change_request_version is associated with
      version 1 (the best-effort baseline - there's no way to know which
      historical CR version an analysis older than this column actually
      ran against).

    Idempotent: every check is "IS NULL", so this is a no-op on every
    startup after the first time it runs on a given database. It's also
    guarded per-row against a version-1 / CREATED row that already exists -
    since Module 12's create_change_request() now creates those itself for
    every brand-new change request, this only ever fills in what's
    genuinely missing (a real pre-Module-12 row) rather than ever
    duplicating what creation already wrote.
    """
    from app.models.analysis import Analysis
    from app.models.change_request import ChangeRequest
    from app.models.change_request_history import ChangeRequestHistory
    from app.models.change_request_version import ChangeRequestVersion
    from app.models.enums import HistoryAction
    from app.services.workflow_rules import build_snapshot

    with Session(engine) as session:
        change_requests = (
            session.query(ChangeRequest).filter(ChangeRequest.current_version.is_(None)).all()
        )
        for change_request in change_requests:
            change_request.current_version = 1

            has_version_1 = (
                session.query(ChangeRequestVersion)
                .filter(
                    ChangeRequestVersion.change_request_id == change_request.id,
                    ChangeRequestVersion.version_number == 1,
                )
                .first()
                is not None
            )
            if not has_version_1:
                session.add(
                    ChangeRequestVersion(
                        change_request_id=change_request.id,
                        version_number=1,
                        changed_by=change_request.created_by,
                        created_at=change_request.created_at,
                        change_summary="Initial version imported.",
                        snapshot=build_snapshot(change_request),
                    )
                )

            has_created_event = (
                session.query(ChangeRequestHistory)
                .filter(
                    ChangeRequestHistory.change_request_id == change_request.id,
                    ChangeRequestHistory.action == HistoryAction.CREATED,
                )
                .first()
                is not None
            )
            if not has_created_event:
                session.add(
                    ChangeRequestHistory(
                        change_request_id=change_request.id,
                        user_id=change_request.created_by,
                        action=HistoryAction.CREATED,
                        reason=None,
                        version_number=1,
                        created_at=change_request.created_at,
                    )
                )
        if change_requests:
            print(f"  (migrated) backfilled version 1 for {len(change_requests)} existing change request(s)")

        analyses = session.query(Analysis).filter(Analysis.change_request_version.is_(None)).all()
        for analysis in analyses:
            analysis.change_request_version = 1
        if analyses:
            print(f"  (migrated) backfilled analysis version for {len(analyses)} existing analysis row(s)")

        session.commit()


def _seed_role_permissions() -> None:
    """Module 21: give every (role, capability) pair a real row, seeded
    from app/services/permissions.py::DEFAULT_PERMISSIONS - the exact
    values the app already behaved with before this module existed (see
    that module's own docstring). Only ever INSERTs a pair that has no row
    yet; an admin's later edit through PUT /api/admin/permissions is never
    overwritten by a later server restart."""
    from app.models.role_permission import RolePermission
    from app.services.permissions import DEFAULT_PERMISSIONS

    with Session(engine) as session:
        existing = {(row.role, row.capability) for row in session.query(RolePermission).all()}
        added = 0
        for (role, capability), allowed in DEFAULT_PERMISSIONS.items():
            if (role, capability) in existing:
                continue
            session.add(RolePermission(role=role, capability=capability, allowed=allowed))
            added += 1
        if added:
            session.commit()
            print(f"  (migrated) seeded {added} role permission default(s)")


def _seed_approval_rules() -> None:
    """Module 21 spec section 4: seed the admin-editable approval rules
    table from workflow_rules.DEFAULT_APPROVAL_RULE_SEEDS - the exact
    risk/category -> approval-type mapping the app already used before
    this module existed (see that constant's own docstring). Guarded by
    "only if the table is completely empty," not a per-row check like
    _seed_role_permissions - these rows are meant to be freely added to,
    edited, and DELETED by an admin, and a per-row re-seed would silently
    resurrect a rule an admin deliberately deleted."""
    import json

    from app.models.approval_rule import ApprovalRule
    from app.models.enums import ApprovalRuleType
    from app.services.workflow_rules import DEFAULT_APPROVAL_RULE_SEEDS

    with Session(engine) as session:
        if session.query(ApprovalRule).first() is not None:
            return
        for rule_type, match_value, approval_types in DEFAULT_APPROVAL_RULE_SEEDS:
            session.add(
                ApprovalRule(
                    rule_type=ApprovalRuleType(rule_type),
                    match_value=match_value,
                    approval_types=json.dumps(approval_types),
                    enabled=True,
                )
            )
        session.commit()
        print(f"  (migrated) seeded {len(DEFAULT_APPROVAL_RULE_SEEDS)} default approval rule(s)")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    _backfill_workflow_data()
    _seed_role_permissions()
    _seed_approval_rules()


if __name__ == "__main__":
    init_db()
    print("Database initialized (tables created, and any new columns added, as needed).")
