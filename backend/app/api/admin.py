"""Module 21 (Administration & Configuration): the admin section's API.

Every endpoint in this router requires require_admin (app/api/deps.py) -
an authenticated, active Admin account. Nothing here replaces the existing
authentication system (Module 1) or the per-change-request permission
helpers already in app/services/workflow_rules.py - this is purely
account/role/permission/approval-rule/system-setting administration, one
level above any single change request.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_admin
from app.core.security import hash_password
from app.database.session import get_db
from app.models.approval_rule import ApprovalRule
from app.models.enums import AdminAuditAction, ApprovalType, Capability, UserRole
from app.models.role_permission import RolePermission
from app.models.system_audit_log import SystemAuditLog
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserUpdate,
    ApprovalRuleCreate,
    ApprovalRuleRead,
    ApprovalRuleUpdate,
    CrCategoriesUpdate,
    RolePermissionBulkUpdate,
    RolePermissionRead,
    SystemAuditLogRead,
    SystemAuditLogResponse,
    SystemSettingsRead,
)
from app.schemas.user import UserRead
from app.services import admin_audit, system_settings
from app.services.permissions import LOCKED_CAPABILITIES
from app.services.workflow_rules import APPROVAL_TYPE_LABELS, USER_ROLE_LABELS

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- User management (spec section 1) ------------------------------------


@router.get("/users", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[User]:
    return db.query(User).order_by(User.name).all()


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists."
        )

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Module 22: same narrow race as app/api/auth.py::register - two
        # admin-create-user calls (or one of these racing a self-service
        # /auth/register) for the same email can both pass the .first()
        # check above before either writes. Without this, the second
        # flush would raise an uncaught IntegrityError (the unique
        # constraint on User.email) instead of the same clean 409 the
        # normal duplicate-email path above already returns.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists."
        )
    admin_audit.record(
        db,
        action=AdminAuditAction.USER_CREATED,
        actor_user_id=current_user.id,
        target_type="user",
        target_id=str(user.id),
        detail=f"{current_user.name} created {user.name} ({user.email}) as {USER_ROLE_LABELS.get(user.role, user.role.value)}.",
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return user

    if "is_active" in changes and changes["is_active"] is False and user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't deactivate your own account.",
        )
    if (
        "role" in changes
        and changes["role"] != UserRole.ADMIN
        and user.id == current_user.id
        and user.role == UserRole.ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't remove your own Admin role.",
        )

    if "role" in changes and changes["role"] != user.role:
        old_role_label = USER_ROLE_LABELS.get(user.role, user.role.value)
        user.role = changes["role"]
        new_role_label = USER_ROLE_LABELS.get(user.role, user.role.value)
        admin_audit.record(
            db,
            action=AdminAuditAction.USER_ROLE_CHANGED,
            actor_user_id=current_user.id,
            target_type="user",
            target_id=str(user.id),
            detail=f"{current_user.name} changed {user.name}'s role from {old_role_label} to {new_role_label}.",
        )

    if "is_active" in changes and changes["is_active"] != (user.is_active is not False):
        user.is_active = changes["is_active"]
        admin_audit.record(
            db,
            action=AdminAuditAction.USER_ACTIVATED if user.is_active else AdminAuditAction.USER_DEACTIVATED,
            actor_user_id=current_user.id,
            target_type="user",
            target_id=str(user.id),
            detail=f"{current_user.name} {'activated' if user.is_active else 'deactivated'} {user.name} ({user.email}).",
        )

    db.commit()
    db.refresh(user)
    return user


# --- System-level audit log (spec section 6) ------------------------------


@router.get("/audit-log", response_model=SystemAuditLogResponse)
def list_audit_log(
    actor_user_id: Optional[int] = Query(None),
    action: Optional[AdminAuditAction] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> SystemAuditLogResponse:
    query = db.query(SystemAuditLog).options(selectinload(SystemAuditLog.actor))
    if actor_user_id is not None:
        query = query.filter(SystemAuditLog.actor_user_id == actor_user_id)
    if action is not None:
        query = query.filter(SystemAuditLog.action == action)

    total = query.count()
    rows = query.order_by(SystemAuditLog.created_at.desc()).offset(offset).limit(limit).all()
    items = [
        SystemAuditLogRead(
            id=row.id,
            actor_user_id=row.actor_user_id,
            actor_label=row.actor_label,
            actor_name=row.actor.name if row.actor else row.actor_label,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            detail=row.detail,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return SystemAuditLogResponse(items=items, total=total, limit=limit, offset=offset)


# --- Permissions matrix (spec section 3) ----------------------------------


@router.get("/permissions", response_model=list[RolePermissionRead])
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[RolePermission]:
    """Every (role, capability) row - init_db seeds all of them on
    startup, so this is always the complete matrix, not a sparse list the
    frontend has to fill gaps in."""
    return db.query(RolePermission).order_by(RolePermission.role, RolePermission.capability).all()


@router.put("/permissions", response_model=list[RolePermissionRead])
def update_permissions(
    payload: RolePermissionBulkUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[RolePermission]:
    """Bulk-update a set of (role, capability) -> allowed pairs in one
    call - the frontend's permissions matrix saves every checkbox that
    changed at once, not one request per cell. Administration can never be
    changed through this endpoint, in either direction (see
    app/services/permissions.py::LOCKED_CAPABILITIES's own docstring) -
    it stays hardcoded True for Admin and False for everyone else, so an
    admin can never accidentally lock every admin out of the admin section."""
    locked = [p for p in payload.permissions if p.capability in LOCKED_CAPABILITIES]
    if locked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administration access can't be changed - it's always Admin-only.",
        )

    changed_rows: list[RolePermission] = []
    for entry in payload.permissions:
        row = (
            db.query(RolePermission)
            .filter(RolePermission.role == entry.role, RolePermission.capability == entry.capability)
            .first()
        )
        if row is None:
            row = RolePermission(role=entry.role, capability=entry.capability, allowed=entry.allowed)
            db.add(row)
            db.flush()
        elif row.allowed == entry.allowed:
            continue
        else:
            row.allowed = entry.allowed
        changed_rows.append(row)

    if changed_rows:
        role_label = lambda r: USER_ROLE_LABELS.get(r, r.value)  # noqa: E731
        summary = "; ".join(
            f"{role_label(row.role)} / {row.capability.value.replace('_', ' ')} -> {'allowed' if row.allowed else 'blocked'}"
            for row in changed_rows
        )
        admin_audit.record(
            db,
            action=AdminAuditAction.PERMISSION_CHANGED,
            actor_user_id=current_user.id,
            target_type="role_permission",
            detail=f"{current_user.name} updated permissions: {summary}.",
        )
        db.commit()

    return db.query(RolePermission).order_by(RolePermission.role, RolePermission.capability).all()


# --- Approval rules (spec section 4) --------------------------------------


def _validate_approval_types(values: list[str]) -> None:
    valid = {t.value for t in ApprovalType}
    unknown = [v for v in values if v not in valid]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown approval type(s): {', '.join(unknown)}. Valid types: {', '.join(sorted(valid))}.",
        )


def _approval_rule_summary(rule: ApprovalRule) -> str:
    labels = ", ".join(
        APPROVAL_TYPE_LABELS.get(ApprovalType(v), v) for v in json.loads(rule.approval_types)
    )
    kind = "Risk level" if rule.rule_type.value == "risk" else "Category keyword"
    return f'{kind} "{rule.match_value}" -> {labels}'


@router.get("/approval-rules", response_model=list[ApprovalRuleRead])
def list_approval_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[ApprovalRule]:
    return db.query(ApprovalRule).order_by(ApprovalRule.rule_type, ApprovalRule.match_value).all()


@router.post("/approval-rules", response_model=ApprovalRuleRead, status_code=status.HTTP_201_CREATED)
def create_approval_rule(
    payload: ApprovalRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalRule:
    _validate_approval_types(payload.approval_types)
    if payload.rule_type.value == "risk" and payload.match_value not in {"low", "medium", "high", "critical"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A risk rule's match value must be one of: low, medium, high, critical.",
        )

    rule = ApprovalRule(
        rule_type=payload.rule_type,
        match_value=payload.match_value,
        approval_types=json.dumps(payload.approval_types),
        enabled=payload.enabled,
    )
    db.add(rule)
    db.flush()
    admin_audit.record(
        db,
        action=AdminAuditAction.APPROVAL_RULE_CREATED,
        actor_user_id=current_user.id,
        target_type="approval_rule",
        target_id=str(rule.id),
        detail=f"{current_user.name} added an approval rule: {_approval_rule_summary(rule)}.",
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/approval-rules/{rule_id}", response_model=ApprovalRuleRead)
def update_approval_rule(
    rule_id: int,
    payload: ApprovalRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ApprovalRule:
    rule = db.get(ApprovalRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval rule not found.")

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return rule

    if "approval_types" in changes:
        _validate_approval_types(changes["approval_types"])
        rule.approval_types = json.dumps(changes["approval_types"])
    if "match_value" in changes:
        if rule.rule_type.value == "risk" and changes["match_value"] not in {"low", "medium", "high", "critical"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A risk rule's match value must be one of: low, medium, high, critical.",
            )
        rule.match_value = changes["match_value"]
    if "enabled" in changes:
        rule.enabled = changes["enabled"]

    db.flush()
    admin_audit.record(
        db,
        action=AdminAuditAction.APPROVAL_RULE_UPDATED,
        actor_user_id=current_user.id,
        target_type="approval_rule",
        target_id=str(rule.id),
        detail=f"{current_user.name} updated an approval rule: {_approval_rule_summary(rule)} "
        f"({'enabled' if rule.enabled else 'disabled'}).",
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/approval-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_approval_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Response:
    rule = db.get(ApprovalRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval rule not found.")

    summary = _approval_rule_summary(rule)
    db.delete(rule)
    admin_audit.record(
        db,
        action=AdminAuditAction.APPROVAL_RULE_DELETED,
        actor_user_id=current_user.id,
        target_type="approval_rule",
        target_id=str(rule_id),
        detail=f"{current_user.name} deleted an approval rule: {summary}.",
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- System settings (spec section 5) -------------------------------------


@router.get("/system-settings", response_model=SystemSettingsRead)
def get_system_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> SystemSettingsRead:
    """cr_categories is genuinely editable (see the PUT endpoint below);
    ai_provider/repository/knowledge_base are read-only .env-derived info -
    see app/services/system_settings.py's own module docstring for why
    Priority values and workflow transitions aren't surfaced here at all."""
    return SystemSettingsRead(
        cr_categories=system_settings.get_cr_categories(db),
        ai_provider=system_settings.get_ai_provider_info(),
        repository=system_settings.get_repository_info(db),
        knowledge_base=system_settings.get_knowledge_base_info(db),
    )


@router.put("/system-settings/cr-categories", response_model=list[str])
def update_cr_categories(
    payload: CrCategoriesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[str]:
    system_settings.set_cr_categories(db, payload.categories, updated_by=current_user.id)
    admin_audit.record(
        db,
        action=AdminAuditAction.SYSTEM_SETTING_CHANGED,
        actor_user_id=current_user.id,
        target_type="system_setting",
        target_id=system_settings.CR_CATEGORIES_KEY,
        detail=f"{current_user.name} updated the change request categories list: {', '.join(payload.categories)}.",
    )
    db.commit()
    return payload.categories
