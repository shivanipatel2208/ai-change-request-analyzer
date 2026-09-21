"""Module 18 Phase 3 (Notifications, My Work & Personal Engineering Queue):
response shapes for GET /api/my-work/* - a personal dashboard built
entirely from data Module 12 (assignments/approvals/history) and Module 18
Phase 1/2 (due dates, notifications) already own. No new tables here -
every one of these is a read, never a write.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.enums import ApprovalStatus, ApprovalType, AssignmentRole, Priority


class MyChangeRequestItem(BaseModel):
    """One row of "My Change Requests" - CRs the current user personally
    created. status is the same computed effective status
    (pending_analysis/requires_clarification/completed/approved/draft)
    list_change_requests already returns, not the raw DB column."""

    id: int
    title: str
    status: str
    priority: Priority
    risk: Optional[str] = None
    created_at: datetime


class MyApprovalItem(BaseModel):
    """One row of "My Approvals" (spec section 4) - every sign-off ever
    tagged to the current user, across every change request, regardless of
    which CR it's on. due_date/due_status mirror ApprovalRead's own fields
    (app/services/approvals.py::approval_due_status) - computed fresh, never
    stored."""

    id: int
    change_request_id: int
    change_request_title: str
    approval_type: ApprovalType
    approval_type_label: str
    status: ApprovalStatus
    status_label: str
    requested_by_name: str
    requested_at: datetime
    due_date: Optional[datetime] = None
    due_status: Optional[str] = None
    risk: Optional[str] = None


class MyReviewItem(BaseModel):
    """One row of "My Reviews" (spec section 5) - a change request where
    the current user holds at least one of Reviewer/Technical Lead/
    Security Reviewer/Owner. `roles` lists every role they hold on this
    specific CR (a person can hold more than one)."""

    change_request_id: int
    title: str
    status: str
    priority: Priority
    risk: Optional[str] = None
    roles: list[AssignmentRole]


class MyAssignmentItem(BaseModel):
    """One row of "My Assignments" - every change request the current user
    holds ANY assignment role on (broader than My Reviews above, which is
    limited to the four review-flavored roles)."""

    change_request_id: int
    title: str
    status: str
    priority: Priority
    risk: Optional[str] = None
    roles: list[AssignmentRole]


class ChangesRequestedItem(BaseModel):
    """One row of "Changes Requested From Me" - a change request the
    current user personally OWNS (created) where an approver has responded
    Changes Requested. This is "someone is waiting on ME to revise and
    resubmit" - the opposite direction from My Approvals, where the
    current user is the one being asked to decide on someone else's work."""

    change_request_id: int
    title: str
    approval_type: ApprovalType
    approval_type_label: str
    approver_name: str
    responded_at: Optional[datetime] = None
    comment: Optional[str] = None


class MyWorkSummary(BaseModel):
    """Cheap counts only, for an overview strip at the top of the My Work
    page - the actual rows for each section come from that section's own
    dedicated endpoint, fetched only once its tab is opened (spec section 7:
    efficient, never "load everything up front")."""

    my_change_requests: int
    my_approvals_pending: int
    my_reviews: int
    my_assignments: int
    changes_requested_from_me: int
    unread_mentions: int
    overdue_approvals: int
