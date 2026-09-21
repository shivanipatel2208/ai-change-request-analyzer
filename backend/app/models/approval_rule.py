"""ApprovalRule model (Module 21 spec section 4) - the admin-editable
version of what used to be the hardcoded _RISK_BASELINE /
_CATEGORY_KEYWORD_APPROVALS tuples in app/services/workflow_rules.py.
Still "a simple, readable config, not a rule engine" (same phrase that
module's own docstring already used) - just database rows now instead of
Python constants, so an admin can view/add/edit/disable them without a
code change.

RISK rows: match_value is one of "low"/"medium"/"high"/"critical" (the
same bucket labels workflow_rules.risk_bucket() already returns).
CATEGORY rows: match_value is a lowercase keyword matched against the
analysis category / target system / title (same haystack the old
hardcoded keyword list matched against).

required_approval_types() in workflow_rules.py takes the currently-enabled
rules as a plain list (the same "caller owns the query, this module stays
pure rule logic" convention every other per-CR permission helper in that
file already follows) rather than querying the database itself.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.enums import ApprovalRuleType, sa_enum


class ApprovalRule(Base):
    __tablename__ = "approval_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_type: Mapped[ApprovalRuleType] = mapped_column(
        sa_enum(ApprovalRuleType, "approval_rule_type"), nullable=False, index=True
    )
    match_value: Mapped[str] = mapped_column(String(255), nullable=False)
    # JSON-encoded list of ApprovalType values (e.g.
    # '["security", "engineering_manager"]") - same "store as a JSON
    # string column" convention as ChangeRequest.tags, not a separate
    # many-to-many join table for what's a short, rarely-changed list.
    approval_types: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<ApprovalRule {self.rule_type}={self.match_value!r}>"
