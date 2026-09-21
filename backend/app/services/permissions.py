"""Module 21 spec section 3: role -> capability permissions. A plain
lookup table (RolePermission rows), not a rule engine - the same "simple,
readable config" philosophy workflow_rules.py's approval matrix already
uses for section 4.

DEFAULT_PERMISSIONS below is what every role could already do before this
module existed: shipping this never silently takes anything away on day
one (init_db seeds exactly these values - see
app/database/init_db.py::_seed_role_permissions). From there, an admin can
tighten (or loosen, except Administration) individual role/capability
pairs through PUT /api/admin/permissions.

Administration is deliberately excluded from what an admin can edit
through that endpoint (see app/api/admin.py) - it's hardcoded True for
Admin and False for everyone else, always, so an admin can never
accidentally lock every admin account out of the admin section itself.

This module never talks to the database except has_permission(), which
takes an already-open Session the same way every other permission helper
in this app does (see workflow_rules.py's own module docstring) - callers
own the session, this stays a small, readable rule check.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.enums import Capability, UserRole
from app.models.role_permission import RolePermission
from app.models.user import User
from app.services.workflow_rules import is_admin

# Every (role, capability) pair, and what it defaults to - matches how the
# app already behaved before Module 21: none of these 9 actions were ever
# gated by ACCOUNT role before now (they were gated by per-change-request
# ownership/assignment instead, which still applies underneath - see each
# endpoint's existing can_edit_change_request / can_manage_workflow /
# approval-ownership checks, none of which this module replaces).
# Administration is the one exception - only Admin could ever reach
# /api/admin/* (it didn't exist before this module), so False is the only
# honest default for every other role.
DEFAULT_PERMISSIONS: dict[tuple[UserRole, Capability], bool] = {
    (role, capability): (capability != Capability.ADMINISTRATION or role == UserRole.ADMIN)
    for role in UserRole
    for capability in Capability
}

# Never editable through PUT /api/admin/permissions, in either direction -
# see this module's own docstring above.
LOCKED_CAPABILITIES: set[Capability] = {Capability.ADMINISTRATION}


def has_permission(db: Session, user: User, capability: Capability) -> bool:
    """Admin always has every capability (same "admin is a superuser"
    convention as workflow_rules.is_admin's use everywhere else in this
    app), regardless of what the matrix says - so an admin can never be
    accidentally locked out of the app by a permissions row. Every other
    role reads its stored row; a role/capability pair with no stored row
    at all (shouldn't happen - init_db seeds every combination) falls back
    to the same default the matrix was seeded with, never a silent deny."""
    if is_admin(user):
        return True
    row = (
        db.query(RolePermission)
        .filter(RolePermission.role == user.role, RolePermission.capability == capability)
        .first()
    )
    if row is not None:
        return row.allowed
    return DEFAULT_PERMISSIONS.get((user.role, capability), True)
