"""Pydantic schemas for the admin API (Module 21). User listing itself
reuses the existing UserRead schema (app/schemas/user.py) - no need for a
parallel "admin view of a user" shape when the plain one already excludes
password_hash and already carries is_active.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import AdminAuditAction, ApprovalRuleType, Capability, UserRole


class AdminUserCreate(BaseModel):
    """POST /api/admin/users body - an admin creating an account directly,
    as opposed to /auth/register (self-service signup). Every field
    required; role defaults to Engineer the same way self-registration
    always has, but an admin can set any role immediately instead of
    creating-then-editing.

    email is a plain str (not pydantic's EmailStr) - same convention as
    RegisterRequest/LoginRequest in app/schemas/auth.py, which never added
    the extra email-validator dependency EmailStr requires."""

    name: str
    email: str
    password: str
    role: UserRole = UserRole.ENGINEER

    @field_validator("email")
    @classmethod
    def email_not_blank(cls, value: str) -> str:
        value = value.strip()
        if "@" not in value or len(value) < 5:
            raise ValueError("A valid email address is required.")
        return value

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Name is required.")
        return value

    @field_validator("password")
    @classmethod
    def password_length(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return value


class AdminUserUpdate(BaseModel):
    """PATCH /api/admin/users/{id} body - partial update semantics (only
    fields actually present in the request are touched), same convention
    as ChangeRequestUpdate. role and is_active can be changed independently
    or together in one call."""

    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class SystemAuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: Optional[int] = None
    actor_label: Optional[str] = None
    # Not an ORM column - the API layer fills this in from the actor
    # relationship (or actor_label, for a system actor with no user_id)
    # before constructing this schema, so the frontend never has to make a
    # second call just to show a name in the audit log.
    actor_name: Optional[str] = None
    action: AdminAuditAction
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail: Optional[str] = None
    created_at: datetime

    @field_validator("action", mode="before")
    @classmethod
    def _action_value(cls, value):
        return value.value if hasattr(value, "value") else value


class SystemAuditLogResponse(BaseModel):
    items: List[SystemAuditLogRead]
    total: int
    limit: int
    offset: int


class RolePermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: UserRole
    capability: Capability
    allowed: bool


class RolePermissionUpdate(BaseModel):
    """One entry in the PUT /api/admin/permissions bulk-update body."""

    role: UserRole
    capability: Capability
    allowed: bool


class RolePermissionBulkUpdate(BaseModel):
    permissions: List[RolePermissionUpdate]


class ApprovalRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_type: ApprovalRuleType
    match_value: str
    approval_types: List[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("approval_types", mode="before")
    @classmethod
    def _parse_approval_types(cls, value):
        import json

        if isinstance(value, str):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return []
        return value


class ApprovalRuleCreate(BaseModel):
    rule_type: ApprovalRuleType
    match_value: str
    approval_types: List[str]
    enabled: bool = True

    @field_validator("match_value")
    @classmethod
    def match_value_not_blank(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("This field can't be blank.")
        return value

    @field_validator("approval_types")
    @classmethod
    def approval_types_not_empty(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("At least one required approval type must be selected.")
        return value


class ApprovalRuleUpdate(BaseModel):
    match_value: Optional[str] = None
    approval_types: Optional[List[str]] = None
    enabled: Optional[bool] = None

    @field_validator("match_value")
    @classmethod
    def match_value_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if not value:
            raise ValueError("This field can't be blank.")
        return value


# --- System settings (spec section 5) -------------------------------------


class AIProviderInfo(BaseModel):
    provider: str
    model: str
    api_key_configured: bool
    embeddings_supported: bool


class RepositoryInfo(BaseModel):
    repository_root: str
    last_scan_status: Optional[str] = None
    last_scan_file_count: Optional[int] = None
    last_scan_at: Optional[datetime] = None


class KnowledgeBaseInfo(BaseModel):
    embedding_model: str
    embeddings_supported: bool
    document_count: int


class SystemSettingsRead(BaseModel):
    """GET /api/admin/system-settings - cr_categories is the one genuinely
    editable setting (see PUT .../system-settings/cr-categories); the rest
    are read-only .env-derived info panels - see
    app/services/system_settings.py's own module docstring for why."""

    cr_categories: List[str]
    ai_provider: AIProviderInfo
    repository: RepositoryInfo
    knowledge_base: KnowledgeBaseInfo


class CrCategoriesUpdate(BaseModel):
    categories: List[str]

    @field_validator("categories")
    @classmethod
    def categories_not_empty(cls, value: List[str]) -> List[str]:
        cleaned = [v.strip() for v in value if v and v.strip()]
        if not cleaned:
            raise ValueError("At least one category is required.")
        # De-duplicate while preserving order - a category list is a
        # simple reference vocabulary, not something meant to hold the
        # same name twice.
        seen = set()
        deduped = []
        for item in cleaned:
            if item.lower() in seen:
                continue
            seen.add(item.lower())
            deduped.append(item)
        return deduped
