"""User model - an account that can submit and review change requests."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.enums import UserRole, sa_enum


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        sa_enum(UserRole, "user_role"), default=UserRole.ENGINEER, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # Module 21 (Administration & Configuration): nullable (not
    # nullable=False) on purpose, same reasoning as ChangeRequest.
    # current_version - a plain ALTER TABLE ADD COLUMN on everyone's
    # existing database leaves every pre-existing row NULL, and there's no
    # honest "was this account active before this column existed" answer
    # other than "yes." So NULL and True both mean active; only an
    # explicit False (set by an admin deactivating the account) means
    # inactive - see app/services/workflow_rules.py::is_active_user(),
    # the one place that reads this column.
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, default=True, nullable=True)

    change_requests: Mapped[List["ChangeRequest"]] = relationship(back_populates="creator")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
