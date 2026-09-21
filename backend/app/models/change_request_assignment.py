"""ChangeRequestAssignment model (Module 12) - "who's responsible for what"
on a change request: Requester, Owner, Technical Lead, Reviewer, Approver,
Security Reviewer, QA Owner, Implementation Owner (app.models.enums.
AssignmentRole). A CR is not required to have every role filled, and
REVIEWER/APPROVER can have more than one person - so this is a plain list
of (user, role) rows per CR rather than fixed columns on ChangeRequest.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import AssignmentRole, sa_enum


class ChangeRequestAssignment(Base):
    __tablename__ = "change_request_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[AssignmentRole] = mapped_column(sa_enum(AssignmentRole, "assignment_role"), nullable=False)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    change_request: Mapped["ChangeRequest"] = relationship(back_populates="assignments")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    assigned_by_user: Mapped["User"] = relationship(foreign_keys=[assigned_by])

    def __repr__(self) -> str:
        return f"<ChangeRequestAssignment cr={self.change_request_id} user={self.user_id} role={self.role}>"
