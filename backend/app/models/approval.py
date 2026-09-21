"""Approval model (Module 12) - one sign-off request on a change request,
e.g. "Priya, Security Approval, Pending". Created when someone with
permission tags an approver (POST .../approvals/request); moved to
Approved/Rejected/Changes Requested by that approver, never by anyone
else or by the AI (see app/services/workflow_rules.py - "AI recommends,
humans decide").

cr_version records which CR version this approval was requested against.
If the change request is edited again after that (current_version moves
past cr_version), the approval is stale with respect to the latest edit -
see approval invalidation logic in app/services/approvals.py.

Module 18 Phase 1 (Notifications, My Work & Personal Engineering Queue):
due_date is an optional target date the requester can set when tagging an
approver (e.g. "please respond by Friday") - nullable so every approval
requested before this module rolled out simply has no due date, never a
fabricated one. Purely informational, like everything else on this row -
it never blocks a response and is never required. Whether a still-pending
approval counts as "overdue" or "due soon" is never stored here; it's
computed fresh at read time (see app/services/approvals.py::
approval_due_status), the same "never a stored boolean that can drift"
rule is_outdated/is_analysis_outdated already follow elsewhere in this app.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import ApprovalStatus, ApprovalType, sa_enum


class Approval(Base):
    __tablename__ = "change_request_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), nullable=False, index=True
    )
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    approval_type: Mapped[ApprovalType] = mapped_column(sa_enum(ApprovalType, "approval_type"), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        sa_enum(ApprovalStatus, "approval_status"), default=ApprovalStatus.PENDING, nullable=False, index=True
    )
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cr_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Module 18 Phase 1 - see this model's own docstring above.
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    change_request: Mapped["ChangeRequest"] = relationship(back_populates="approvals")
    approver: Mapped["User"] = relationship(foreign_keys=[approver_id])
    requested_by_user: Mapped["User"] = relationship(foreign_keys=[requested_by])

    def __repr__(self) -> str:
        return f"<Approval cr={self.change_request_id} type={self.approval_type} status={self.status}>"
