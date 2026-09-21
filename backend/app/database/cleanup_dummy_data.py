"""One-time cleanup for the dev database (backend/data/app.db): delete
every account except the ONE you name, along with everything only the
other accounts touched - the seeded demo accounts (seed_demo.py),
seed_bulk.py's bot accounts, seed.py's background demo user, and anything
you clicked around and created through the app under any other login.
What's left afterward is exactly the account you named and whatever it
created.

This is a different, broader tool than cleanup_test_users.py, which only
ever targets pytest's own known email patterns (accounts like
"ai-<hex>@example.com") and leaves every real account - demo or
otherwise - alone. This one flips that around: you name the one account
to keep, and every other account is gone, regardless of how it got there.

Runs in passes:

  1. Delete every change request NOT created by the kept account. Each
     model's own SQLAlchemy relationship cascade (see
     app/models/change_request.py) takes its versions, history, analyses
     (and everything under an analysis - requirements, risks, test cases,
     security findings, implementation tasks, clarification questions,
     etc.), assignments, approvals, and comments down with it; this script
     only additionally clears the notifications that pointed at that
     change request, since Notification isn't one of those cascading
     relationships.
  2. Scrub any lingering reference to a non-kept account from what the
     kept account's OWN change requests still hold - e.g. another
     account's comment, assignment, or approval on the kept account's CR,
     or as the reviewer/editor of one of its analysis's requirements/test
     cases/security findings/implementation tasks. A record that requires
     a valid user to exist (a comment, an assignment, an approval) is
     deleted outright; a record that only references one optionally
     (history's actor, a version's "changed by", a reviewed/edited-by
     field) has just that reference cleared, so the CR's own content and
     audit trail stay intact.
  3. Delete every remaining non-kept account, after clearing their own
     outgoing notifications and any stray optional reference to them
     elsewhere in the database (a knowledge document they uploaded, a
     repository scan they triggered, an admin audit log entry, a system
     setting they last changed).

Usage (from inside backend/):

    python -m app.database.cleanup_dummy_data --keep-email test@alight.com            # dry run - report only, deletes nothing
    python -m app.database.cleanup_dummy_data --keep-email test@alight.com --apply    # actually delete everything else
"""
from __future__ import annotations

import argparse

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database.session import SessionLocal, engine
from app.models.approval import Approval
from app.models.change_request import ChangeRequest
from app.models.change_request_assignment import ChangeRequestAssignment
from app.models.change_request_history import ChangeRequestHistory
from app.models.change_request_version import ChangeRequestVersion
from app.models.comment import ChangeRequestComment
from app.models.implementation_task import ImplementationTask
from app.models.knowledge_document import KnowledgeDocument
from app.models.notification import Notification
from app.models.repository_scan import RepositoryScan
from app.models.requirement import Requirement
from app.models.security_finding import SecurityFinding
from app.models.system_audit_log import SystemAuditLog
from app.models.system_setting import SystemSetting
from app.models.test_case import TestCase
from app.models.user import User


def _find_keep_user(db: Session, email: str) -> User:
    # Case-insensitive - registration doesn't normalize casing, and typing
    # the email slightly differently than you signed up with shouldn't
    # accidentally match nothing (or, far worse, nothing and then this
    # script has no "keep" account at all).
    user = db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()
    if user is None:
        raise SystemExit(
            f"No account found with email {email!r}. Nothing was touched - "
            "double check the email against what you actually registered with."
        )
    return user


def _cleanup_foreign_change_requests(db: Session, keep_user_id: int, apply: bool) -> None:
    crs = db.query(ChangeRequest).filter(ChangeRequest.created_by != keep_user_id).all()
    if not crs:
        print("No change requests to remove - everything left is already the kept account's own.\n")
        return

    verb = "Deleting" if apply else "Would delete"
    print(
        f"{verb} {len(crs)} change request(s) not created by the kept account (and everything under them)"
        f"{'' if apply else ' (dry run - nothing deleted yet)'}:"
    )
    for cr in crs:
        print(f"  - CR #{cr.id}: {cr.title!r}")

    if not apply:
        print()
        return

    deleted_notifications = 0
    for cr in crs:
        deleted_notifications += db.query(Notification).filter(Notification.change_request_id == cr.id).delete()
        db.delete(cr)
    db.commit()
    print(f"Deleted {len(crs)} change request(s) and {deleted_notifications} notification(s) referencing them.\n")


def _scrub_foreign_references_on_kept_data(db: Session, keep_user_id: int, foreign_ids: set[int], apply: bool) -> None:
    """After pass 1, the only change requests left are the kept account's
    own - but something on one of them can still point at an account
    that's about to be deleted (a comment, an assignment, an approval, a
    reviewer/editor field). Handled here so pass 3 never hits a
    foreign-key error, and so a NOT NULL column is never left dangling."""
    verb = "Would remove" if not apply else "Removing"

    comments = db.query(ChangeRequestComment).filter(ChangeRequestComment.user_id.in_(foreign_ids))
    n = comments.count()
    if n:
        print(f"{verb} {n} comment(s) on your own change request(s) authored by an account being deleted.")
        if apply:
            comments.delete(synchronize_session=False)

    assignments = db.query(ChangeRequestAssignment).filter(
        or_(ChangeRequestAssignment.user_id.in_(foreign_ids), ChangeRequestAssignment.assigned_by.in_(foreign_ids))
    )
    n = assignments.count()
    if n:
        print(f"{verb} {n} assignment(s) involving an account being deleted.")
        if apply:
            assignments.delete(synchronize_session=False)

    approvals = db.query(Approval).filter(
        or_(Approval.approver_id.in_(foreign_ids), Approval.requested_by.in_(foreign_ids))
    )
    n = approvals.count()
    if n:
        print(f"{verb} {n} approval(s) involving an account being deleted.")
        if apply:
            approvals.delete(synchronize_session=False)

    history = db.query(ChangeRequestHistory).filter(ChangeRequestHistory.user_id.in_(foreign_ids))
    n = history.count()
    if n:
        print(
            f"{verb} the actor on {n} history/audit event(s) - the events themselves "
            "are kept, just no longer attributed to a deleted account."
        )
        if apply:
            history.update({ChangeRequestHistory.user_id: None}, synchronize_session=False)

    versions = db.query(ChangeRequestVersion).filter(ChangeRequestVersion.changed_by.in_(foreign_ids))
    n = versions.count()
    if n:
        print(f"{verb} reattributing {n} version snapshot(s) to the kept account (changed_by can't be empty).")
        if apply:
            versions.update({ChangeRequestVersion.changed_by: keep_user_id}, synchronize_session=False)

    for model, column, label in [
        (SecurityFinding, SecurityFinding.reviewed_by, "security finding reviewer"),
        (TestCase, TestCase.edited_by, "test case editor"),
        (Requirement, Requirement.reviewed_by, "requirement reviewer"),
        (ImplementationTask, ImplementationTask.edited_by, "implementation task editor"),
    ]:
        q = db.query(model).filter(column.in_(foreign_ids))
        n = q.count()
        if n:
            print(f"{verb} the {label} field on {n} row(s) referencing an account being deleted.")
            if apply:
                q.update({column: None}, synchronize_session=False)

    if apply:
        db.commit()
    print()


def _clear_stray_optional_references(db: Session, foreign_ids: set[int], apply: bool) -> None:
    """Optional references to a soon-to-be-deleted account that live
    outside the change-request world entirely. The row itself (a
    knowledge document, a repo scan, an audit log entry, a system
    setting) is real content worth keeping even once whoever touched it
    is gone, so this only clears the reference, never the row."""
    verb = "Would clear" if not apply else "Clearing"
    for model, column, label in [
        (KnowledgeDocument, KnowledgeDocument.uploaded_by, "knowledge document uploader"),
        (RepositoryScan, RepositoryScan.triggered_by, "repository scan trigger"),
        (SystemAuditLog, SystemAuditLog.actor_user_id, "audit log actor"),
        (SystemSetting, SystemSetting.updated_by, "system setting editor"),
    ]:
        q = db.query(model).filter(column.in_(foreign_ids))
        n = q.count()
        if n:
            print(f"{verb} the {label} field on {n} row(s).")
            if apply:
                q.update({column: None}, synchronize_session=False)
    if apply:
        db.commit()
    print()


def _cleanup_foreign_users(db: Session, keep_user_id: int, apply: bool) -> None:
    foreign_users = db.query(User).filter(User.id != keep_user_id).all()
    if not foreign_users:
        print("No other accounts exist - nothing left to delete.")
        return

    foreign_ids = {u.id for u in foreign_users}
    _scrub_foreign_references_on_kept_data(db, keep_user_id, foreign_ids, apply)
    _clear_stray_optional_references(db, foreign_ids, apply)

    verb = "Deleting" if apply else "Would delete"
    print(f"{verb} {len(foreign_users)} account(s){'' if apply else ' (dry run - nothing deleted yet)'}:")
    for user in foreign_users:
        print(f"  - #{user.id} {user.name} <{user.email}>")

    if not apply:
        print("\nRun again with --apply to actually delete these.")
        return

    deleted_notifications = 0
    for user in foreign_users:
        deleted_notifications += db.query(Notification).filter(Notification.user_id == user.id).delete()
        db.delete(user)
    db.commit()
    print(f"\nDone - deleted {len(foreign_users)} account(s) and {deleted_notifications} notification(s) sent to them.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--keep-email", required=True, help="Email of the ONE account to keep - every other account is removed."
    )
    parser.add_argument("--apply", action="store_true", help="Actually delete data (default: dry run only).")
    args = parser.parse_args()

    print(f"Database: {engine.url}\n")

    db = SessionLocal()
    try:
        keep_user = _find_keep_user(db, args.keep_email)
        print(f"Keeping account: #{keep_user.id} {keep_user.name} <{keep_user.email}>\n")

        _cleanup_foreign_change_requests(db, keep_user.id, args.apply)
        _cleanup_foreign_users(db, keep_user.id, args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
