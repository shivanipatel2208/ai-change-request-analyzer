"""RolePermission model (Module 21 spec section 3) - a plain (role,
capability) -> allowed lookup table, not a rule engine. Seeded on startup
(see app/database/init_db.py::_seed_role_permissions) with defaults that
match how the app already behaved before this module existed, so shipping
this never silently changes what anyone could already do; from then on an
admin can flip individual rows via PUT /api/admin/permissions.

One row per (role, capability) pair that's been explicitly set. A pair
with no row at all is treated as "not allowed" by
app/services/permissions.py::has_permission - but init_db seeds every
combination on first run, so in practice every pair always has a row.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.enums import Capability, UserRole, sa_enum


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role", "capability", name="uq_role_permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[UserRole] = mapped_column(sa_enum(UserRole, "role_permission_role"), nullable=False, index=True)
    capability: Mapped[Capability] = mapped_column(
        sa_enum(Capability, "role_permission_capability"), nullable=False, index=True
    )
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<RolePermission role={self.role} capability={self.capability} allowed={self.allowed}>"
