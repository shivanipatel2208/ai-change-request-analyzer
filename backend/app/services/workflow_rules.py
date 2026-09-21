"""Module 12 (Enterprise Workflow) - the rules that keep the workflow from
being "anything can change to anything, whenever, by anyone":

  * the status lifecycle's allowed transitions (STATUS_TRANSITIONS)
  * which transitions require a typed reason (REASON_REQUIRED_STATUSES)
  * the approval matrix (required_approval_types) - a simple, readable
    config, not a rule *engine* (the spec explicitly says not to
    overengineer this)
  * "is the current AI analysis outdated" (is_analysis_outdated)
  * per-CR permission helpers built on top of the account-wide UserRole
    plus ChangeRequestAssignment rows (assignment_roles_for /
    can_edit_change_request / can_manage_workflow / can_assign_users /
    can_request_approval)

Nothing here talks to the database except assignment_roles_for(), which
takes an already-loaded list of ChangeRequestAssignment rows rather than
querying itself - callers own the query/session, this module stays pure
rule logic that's easy to unit test.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from app.models.analysis import Analysis
from app.models.approval_rule import ApprovalRule
from app.models.change_request import ChangeRequest
from app.models.change_request_assignment import ChangeRequestAssignment
from app.models.enums import (
    ApprovalRecommendation,
    ApprovalRuleType,
    AssignmentRole,
    ApprovalStatus,
    ChangeRequestStatus,
    ApprovalType,
    UserRole,
)
from app.models.user import User

CRS = ChangeRequestStatus

# --- Status lifecycle --------------------------------------------------
#
# Draft -> Submitted -> Pending Analysis -> Analyzed -> Under Review ->
#   {Changes Requested, Approval Required} -> Approved/Rejected ->
#   Implementation Planned -> In Progress -> Implemented -> Validated ->
#   Closed. Cancelled is reachable from every non-terminal state.
#
# IN_REVIEW is this app's existing enum member for what the spec calls
# "Under Review" (kept, not renamed, to avoid breaking any CR already
# stored with that value - Module 12 only adds new status values, never
# renames existing ones).
STATUS_TRANSITIONS: dict[ChangeRequestStatus, set[ChangeRequestStatus]] = {
    CRS.DRAFT: {CRS.SUBMITTED, CRS.CANCELLED},
    CRS.SUBMITTED: {CRS.PENDING_ANALYSIS, CRS.CANCELLED},
    CRS.PENDING_ANALYSIS: {CRS.ANALYZED, CRS.CANCELLED},
    CRS.ANALYZED: {CRS.IN_REVIEW, CRS.CANCELLED},
    CRS.IN_REVIEW: {CRS.CHANGES_REQUESTED, CRS.APPROVAL_REQUIRED, CRS.CANCELLED},
    # After feedback is addressed: either straight back under review, or
    # through a re-analysis first if the edit was substantial enough to
    # warrant one (both are valid next steps, not a fixed sequence).
    CRS.CHANGES_REQUESTED: {CRS.IN_REVIEW, CRS.ANALYZED, CRS.CANCELLED},
    CRS.APPROVAL_REQUIRED: {CRS.APPROVED, CRS.REJECTED, CRS.CHANGES_REQUESTED, CRS.CANCELLED},
    CRS.APPROVED: {CRS.IMPLEMENTATION_PLANNED, CRS.CANCELLED},
    # A rejected CR isn't necessarily dead - it can be revised and
    # resubmitted through the same Changes Requested path as any other
    # feedback loop.
    CRS.REJECTED: {CRS.CHANGES_REQUESTED, CRS.CANCELLED},
    CRS.IMPLEMENTATION_PLANNED: {CRS.IN_PROGRESS, CRS.CANCELLED},
    CRS.IN_PROGRESS: {CRS.IMPLEMENTED, CRS.CANCELLED},
    CRS.IMPLEMENTED: {CRS.VALIDATED, CRS.CANCELLED},
    CRS.VALIDATED: {CRS.CLOSED},
    CRS.CLOSED: set(),
    CRS.CANCELLED: set(),
}

# Transitions INTO one of these statuses must carry a non-empty `reason` -
# these are exactly the "something went wrong / needs explanation" turns
# (spec section 8's own example is Under Review -> Changes Requested).
REASON_REQUIRED_STATUSES: set[ChangeRequestStatus] = {
    CRS.CHANGES_REQUESTED,
    CRS.REJECTED,
    CRS.CANCELLED,
}


def can_transition(current: ChangeRequestStatus, target: ChangeRequestStatus) -> bool:
    if current == target:
        return False
    return target in STATUS_TRANSITIONS.get(current, set())


def reason_required(target: ChangeRequestStatus) -> bool:
    return target in REASON_REQUIRED_STATUSES


def available_transitions(current: ChangeRequestStatus) -> list[ChangeRequestStatus]:
    """The statuses `current` can legally move to next, in a stable
    (alphabetical) order - what the "Change Status" picker offers."""
    return sorted(STATUS_TRANSITIONS.get(current, set()), key=lambda s: s.value)


# Human-facing labels for the raw status column (distinct from the older,
# derived "effective_status" used elsewhere - see app/api/change_requests.py
# ::_effective_status). Every ChangeRequestStatus member must have one.
STATUS_LABELS: dict[ChangeRequestStatus, str] = {
    CRS.DRAFT: "Draft",
    CRS.SUBMITTED: "Submitted",
    CRS.PENDING_ANALYSIS: "Pending Analysis",
    CRS.ANALYZED: "Analyzed",
    CRS.IN_REVIEW: "Under Review",
    CRS.CHANGES_REQUESTED: "Changes Requested",
    CRS.APPROVAL_REQUIRED: "Approval Required",
    CRS.APPROVED: "Approved",
    CRS.REJECTED: "Rejected",
    CRS.IMPLEMENTATION_PLANNED: "Implementation Planned",
    CRS.IN_PROGRESS: "In Progress",
    CRS.IMPLEMENTED: "Implemented",
    CRS.VALIDATED: "Validated",
    CRS.CLOSED: "Closed",
    CRS.CANCELLED: "Cancelled",
}

# Human-facing labels for AssignmentRole - used in history lines ("assigned
# Priya Shah as Technical Lead") and by the frontend's assignment picker.
ROLE_LABELS: dict[AssignmentRole, str] = {
    AssignmentRole.REQUESTER: "Requester",
    AssignmentRole.OWNER: "Owner",
    AssignmentRole.TECHNICAL_LEAD: "Technical Lead",
    AssignmentRole.REVIEWER: "Reviewer",
    AssignmentRole.APPROVER: "Approver",
    AssignmentRole.SECURITY_REVIEWER: "Security Reviewer",
    AssignmentRole.QA_OWNER: "QA Owner",
    AssignmentRole.IMPLEMENTATION_OWNER: "Implementation Owner",
}

# Module 21 (Administration & Configuration): human-facing labels for the
# account-wide UserRole - PRODUCT_MANAGER displays as "Manager" (the spec's
# practical role list) rather than adding a second, confusingly-similar
# enum member for the same real-world role.
USER_ROLE_LABELS: dict[UserRole, str] = {
    UserRole.ADMIN: "Admin",
    UserRole.REQUESTER: "Requester",
    UserRole.ENGINEER: "Engineer",
    UserRole.REVIEWER: "Reviewer",
    UserRole.SECURITY_REVIEWER: "Security Reviewer",
    UserRole.APPROVER: "Approver",
    UserRole.PRODUCT_MANAGER: "Manager",
}


# --- AI analysis version awareness --------------------------------------


def is_analysis_outdated(change_request: ChangeRequest, latest_analysis: Optional[Analysis]) -> bool:
    """True if there's no analysis yet, or the CR has been edited (its
    version bumped) since the most recent analysis was run."""
    if latest_analysis is None:
        return False  # "no analysis" and "outdated analysis" are different banners
    cr_version = change_request.current_version or 1
    analysis_version = latest_analysis.change_request_version or 1
    return analysis_version != cr_version


def repository_finding_outdated_reasons(
    change_request: ChangeRequest,
    finding_change_request_version: int,
    finding_analysis_id: int,
    finding_repository_scan_id: int,
    *,
    latest_analysis_id: Optional[int],
    latest_repository_scan_id: Optional[int],
) -> list[str]:
    """Module 15 Phase 4: why (if at all) a RepositoryFinding may no longer
    reflect reality. Three independent things can have moved on since it
    was generated - the change request itself was edited, a newer AI
    analysis was run, or a newer repository scan was taken - and any ONE
    of them is enough to warn about. Returns every reason that actually
    applies (an empty list means still current) rather than collapsing to
    a single boolean, the same "computed fresh per request, never stored"
    rule is_analysis_outdated() above already follows - a finding's own
    row never changes once written, only what's said about it."""
    reasons: list[str] = []
    cr_version = change_request.current_version or 1
    if finding_change_request_version != cr_version:
        reasons.append("The change request has been edited since this finding was generated.")
    if latest_analysis_id is not None and finding_analysis_id != latest_analysis_id:
        reasons.append("A newer AI analysis has been run for this change request.")
    if latest_repository_scan_id is not None and finding_repository_scan_id != latest_repository_scan_id:
        reasons.append("A newer repository scan is available.")
    return reasons


# --- Approval matrix -----------------------------------------------------
#
# A plain, readable config - not a rule engine. Risk sets a baseline
# ("who always needs to sign off at this risk level"); category/keyword
# matches add more approvers on top when the change touches something
# specific (security, database, customer-facing, etc). This only computes
# a *recommendation* - see app/services/approvals.py for where a human
# turns that into actual Approval rows by tagging real people.
#
# Module 21 (Administration & Configuration) made this admin-editable: the
# risk-bucket and category-keyword mappings below are now the SEEDED
# DEFAULTS for the real, database-backed app.models.approval_rule.py rows
# (see app/database/init_db.py::_seed_approval_rules) rather than the only
# source of truth. required_approval_types() takes the currently-enabled
# ApprovalRule rows as a plain argument - the same "caller owns the query,
# this module stays pure rule logic" convention every other permission
# helper in this file already follows (see assignment_roles_for's own
# comment) - and falls back to these exact constants when no rules are
# passed at all, so any caller not yet updated to load rules keeps
# behaving exactly as before.

_RISK_BASELINE: tuple[tuple[float, set[ApprovalType]], ...] = (
    (75, {ApprovalType.ENGINEERING_MANAGER, ApprovalType.SECURITY, ApprovalType.DIRECTOR}),  # critical
    (50, {ApprovalType.ENGINEERING_MANAGER, ApprovalType.SECURITY}),  # high
    (25, {ApprovalType.ENGINEERING_MANAGER}),  # medium
)
_LOW_RISK_BASELINE = {ApprovalType.TECHNICAL}  # "Team Lead approval" - low risk

_CATEGORY_KEYWORD_APPROVALS: tuple[tuple[str, ApprovalType], ...] = (
    ("security", ApprovalType.SECURITY),
    ("database", ApprovalType.DBA),
    ("db", ApprovalType.DBA),
    ("infrastructure", ApprovalType.RELEASE),
    ("production", ApprovalType.RELEASE),
    ("api", ApprovalType.TECHNICAL),
    # Customer-facing: no dedicated column exists for this, so it's
    # inferred from the target system / category naming - a reasonable,
    # non-overengineered heuristic rather than a new required field.
    ("customer", ApprovalType.PRODUCT),
    ("mobile app", ApprovalType.PRODUCT),
    ("storefront", ApprovalType.PRODUCT),
    ("checkout", ApprovalType.PRODUCT),
    ("pos frontend", ApprovalType.PRODUCT),
)

# Every DEFAULT_APPROVAL_RULE_SEEDS entry becomes one ApprovalRule row on
# first startup (see init_db.py) - "risk" rows built from _RISK_BASELINE/
# _LOW_RISK_BASELINE, "category" rows built from _CATEGORY_KEYWORD_APPROVALS,
# one row per keyword so an admin can edit/disable them individually.
DEFAULT_APPROVAL_RULE_SEEDS: tuple[tuple[str, str, list[str]], ...] = (
    ("risk", "critical", sorted(t.value for t in _RISK_BASELINE[0][1])),
    ("risk", "high", sorted(t.value for t in _RISK_BASELINE[1][1])),
    ("risk", "medium", sorted(t.value for t in _RISK_BASELINE[2][1])),
    ("risk", "low", sorted(t.value for t in _LOW_RISK_BASELINE)),
) + tuple((("category", keyword, [approval_type.value]) for keyword, approval_type in _CATEGORY_KEYWORD_APPROVALS))


def _risk_baseline(risk_score: float) -> set[ApprovalType]:
    for threshold, approvals in _RISK_BASELINE:
        if risk_score >= threshold:
            return set(approvals)
    return set(_LOW_RISK_BASELINE)


# Module 13 (AI Analysis 2.0): moved here from app/api/change_requests.py
# (where it started as a private, list-endpoint-only helper) so
# app/services/analysis_delta.py can share the exact same thresholds - one
# definition of what "high risk" means, not two that could drift apart.
_RISK_BUCKETS: tuple[tuple[float, str], ...] = (
    (75, "critical"),
    (50, "high"),
    (25, "medium"),
)


def risk_bucket(score: float) -> str:
    for threshold, label in _RISK_BUCKETS:
        if score >= threshold:
            return label
    return "low"


# Module 18 Phase 2 (Notifications, My Work & Personal Engineering Queue):
# a plain ordering over the same four bucket labels risk_bucket() already
# returns, so "did risk get WORSE" can be answered with a simple integer
# comparison rather than re-deriving/hardcoding the low->critical order a
# second time somewhere else.
_RISK_BUCKET_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def risk_bucket_rank(bucket: str) -> int:
    return _RISK_BUCKET_RANK.get(bucket, 0)


APPROVAL_TYPE_LABELS: dict[ApprovalType, str] = {
    ApprovalType.TECHNICAL: "Technical",
    ApprovalType.SECURITY: "Security",
    ApprovalType.PRODUCT: "Product",
    ApprovalType.ENGINEERING_MANAGER: "Engineering Manager",
    ApprovalType.DIRECTOR: "Director",
    ApprovalType.QA: "QA",
    ApprovalType.DBA: "DBA",
    ApprovalType.RELEASE: "Release",
    ApprovalType.GENERAL: "General",
}

APPROVAL_STATUS_LABELS: dict[ApprovalStatus, str] = {
    ApprovalStatus.PENDING: "Pending",
    ApprovalStatus.APPROVED: "Approved",
    ApprovalStatus.REJECTED: "Rejected",
    ApprovalStatus.CHANGES_REQUESTED: "Changes Requested",
    ApprovalStatus.CANCELLED: "Cancelled",
}

# A responder (the tagged approver, and only the tagged approver - see
# app/models/approval.py) may only move a PENDING approval to one of these -
# never back to PENDING, and never to CANCELLED (that's a request-side
# withdrawal, not a response - see app/services/approvals.py::cancel_approval).
APPROVAL_RESPONSE_STATUSES: set[ApprovalStatus] = {
    ApprovalStatus.APPROVED,
    ApprovalStatus.REJECTED,
    ApprovalStatus.CHANGES_REQUESTED,
}

# Same "explain what went wrong" rule as REASON_REQUIRED_STATUSES above,
# applied to an approval response instead of a CR status transition.
APPROVAL_REASON_REQUIRED: set[ApprovalStatus] = {
    ApprovalStatus.REJECTED,
    ApprovalStatus.CHANGES_REQUESTED,
}


def _approval_types_from_json(raw: str) -> set[ApprovalType]:
    try:
        values = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        values = []
    result = set()
    for value in values:
        try:
            result.add(ApprovalType(value))
        except ValueError:
            continue  # an unrecognized value in the row - skip rather than crash a report/recommendation
    return result


def required_approval_types(
    change_request: ChangeRequest,
    analysis: Analysis,
    rules: Optional[Iterable[ApprovalRule]] = None,
) -> set[ApprovalType]:
    """AI-driven approval RECOMMENDATION only (spec section 14/29 - this
    never grants an approval, it only says which ones a human should go
    request).

    `rules` is the CURRENTLY ENABLED set of admin-configured ApprovalRule
    rows (Module 21) - the caller loads them from the database (same
    "caller owns the query" convention as assignment_roles_for above) and
    passes them in. When `rules` is None (no caller updated yet, or a unit
    test exercising this function directly), this falls back to the exact
    hardcoded matrix Module 21 seeded those rows from, so behavior never
    silently changes for a caller that hasn't been updated.

    One thing stays hardcoded either way, deliberately not exposed as an
    editable rule: if the AI itself flagged a security risk on this
    analysis, Security approval is always added. That's not a "risk level"
    or "keyword" match - it's a structural fact about what the AI actually
    found - so it doesn't fit either rule shape section 4 asks for, and
    silently NOT requiring security sign-off on an AI-flagged security risk
    would be a real safety regression an admin could make by accident."""
    haystack = " ".join(
        filter(None, [analysis.category, change_request.target_system, change_request.title])
    ).lower()

    if rules is None:
        required = _risk_baseline(analysis.risk_score)
        for keyword, approval_type in _CATEGORY_KEYWORD_APPROVALS:
            if keyword in haystack:
                required.add(approval_type)
    else:
        required = set()
        bucket = risk_bucket(analysis.risk_score)
        for rule in rules:
            if not rule.enabled:
                continue
            if rule.rule_type == ApprovalRuleType.RISK and rule.match_value == bucket:
                required |= _approval_types_from_json(rule.approval_types)
            elif rule.rule_type == ApprovalRuleType.CATEGORY and rule.match_value in haystack:
                required |= _approval_types_from_json(rule.approval_types)

    if any((r.category is not None and r.category.value == "security") for r in analysis.risks):
        required.add(ApprovalType.SECURITY)

    return required


def format_approval_types(types: Iterable[ApprovalType]) -> str:
    """Human-readable list of approval types, e.g. "Engineering Manager and
    Security" or "None" - the one shared formatter for "which approvals are
    required," used by both the analysis-to-analysis diff
    (app/services/analysis_delta.py) and the workflow recommendation text
    below, so the two places that describe a set of required approvals in
    prose can't drift into two different phrasings."""
    labels = sorted(APPROVAL_TYPE_LABELS.get(t, t.value) for t in types)
    if not labels:
        return "None"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" and {labels[-1]}"


# --- Module 13 Phase 4: workflow recommendation text + human-override ----
#
# "Workflow recommendation text" is computed, not AI-written - the same
# choice he made for Phase 2's analysis-to-analysis diff (no extra AI call
# on every read, and it's never wrong about which approvals the numbers
# actually require). It only restates what `analysis.recommendation` /
# `required_approval_types()` already say, in one plain sentence, so a
# reviewer doesn't have to piece the two together themselves.

RECOMMENDATION_LABELS: dict[ApprovalRecommendation, str] = {
    ApprovalRecommendation.APPROVE: "Approve",
    ApprovalRecommendation.APPROVE_WITH_CONDITIONS: "Approve with Conditions",
    ApprovalRecommendation.NEEDS_MORE_INFO: "Needs More Information",
    ApprovalRecommendation.REQUIRES_CLARIFICATION: "Requires Clarification",
    ApprovalRecommendation.REJECT: "Reject",
}

# What a human decision "in line with" a given AI recommendation looks
# like - used only to detect a human override for the audit trail
# (overrides_ai_recommendation, below), never to block or auto-decide
# anything. A human can decide however they want; this only makes it
# visible on the record when they didn't follow the AI ("AI recommends,
# humans decide" - a decision humans make is never wrong for disagreeing).
_ALIGNED_APPROVAL_STATUS: dict[ApprovalRecommendation, ApprovalStatus] = {
    ApprovalRecommendation.APPROVE: ApprovalStatus.APPROVED,
    ApprovalRecommendation.APPROVE_WITH_CONDITIONS: ApprovalStatus.APPROVED,
    ApprovalRecommendation.NEEDS_MORE_INFO: ApprovalStatus.CHANGES_REQUESTED,
    ApprovalRecommendation.REQUIRES_CLARIFICATION: ApprovalStatus.CHANGES_REQUESTED,
    ApprovalRecommendation.REJECT: ApprovalStatus.REJECTED,
}


def recommendation_summary(
    change_request: ChangeRequest,
    analysis: Analysis,
    rules: Optional[Iterable[ApprovalRule]] = None,
) -> str:
    """One computed sentence combining the AI's own recommendation with
    what it actually takes to move this change request forward at this
    risk level - shown alongside (never in place of) the raw
    `recommendation` / `recommendation_reasoning` fields already on the
    analysis. `rules` is passed straight through to required_approval_types
    (Module 21) - see that function's own docstring."""
    rec_label = RECOMMENDATION_LABELS.get(analysis.recommendation, "No recommendation yet")
    bucket = risk_bucket(analysis.risk_score).capitalize()
    approvals = required_approval_types(change_request, analysis, rules)

    if not approvals:
        approvals_clause = "no formal approval is required at this risk level"
    else:
        approvals_clause = f"requires {format_approval_types(approvals)} approval before it can proceed"

    return f"AI recommends: {rec_label} ({bucket} risk) - {approvals_clause}."


def overrides_ai_recommendation(
    recommendation: Optional[ApprovalRecommendation], decided_status: ApprovalStatus
) -> bool:
    """True when a human's approval decision doesn't match what the AI's
    own recommendation would suggest (see _ALIGNED_APPROVAL_STATUS above) -
    purely descriptive and auditable, never enforced; a human is never
    blocked from deciding either way. No recommendation on record (e.g.
    this approval predates any analysis) means there's nothing to have
    overridden."""
    if recommendation is None:
        return False
    return _ALIGNED_APPROVAL_STATUS.get(recommendation) != decided_status


# --- Per-CR permissions ---------------------------------------------------
#
# UserRole (account-wide: admin/engineer/product_manager/reviewer) answers
# "what kind of account is this"; ChangeRequestAssignment (per-CR) answers
# "what is this person responsible for on THIS change request." Both feed
# into the helpers below - deliberately simple boolean checks, not a
# generic permissions/RBAC framework.


def assignment_roles_for(
    user: User, assignments: Iterable[ChangeRequestAssignment]
) -> set[AssignmentRole]:
    return {a.role for a in assignments if a.user_id == user.id}


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def is_active_user(user: User) -> bool:
    """Module 21: NULL (every account that existed before this column did)
    and True both mean active - only an explicit False, set by an admin
    deactivating the account, means inactive. See the column's own
    docstring on app/models/user.py::User.is_active."""
    return user.is_active is not False


def can_edit_change_request(
    user: User, change_request: ChangeRequest, assignments: Iterable[ChangeRequestAssignment]
) -> bool:
    """Requester + Owner + Technical Lead + Admin can edit (spec section 9).
    Reviewers/Approvers/QA/Security can comment and act on their own
    approvals, but not edit CR fields directly."""
    if is_admin(user):
        return True
    if change_request.created_by == user.id:
        return True
    roles = assignment_roles_for(user, assignments)
    return bool(roles & {AssignmentRole.OWNER, AssignmentRole.TECHNICAL_LEAD})


def can_manage_workflow(
    user: User, change_request: ChangeRequest, assignments: Iterable[ChangeRequestAssignment]
) -> bool:
    """Change status, assign reviewers, request approval - the CR Owner's
    job (spec section 9), plus Admin."""
    if is_admin(user):
        return True
    if change_request.created_by == user.id:
        return True
    roles = assignment_roles_for(user, assignments)
    return bool(roles & {AssignmentRole.OWNER, AssignmentRole.TECHNICAL_LEAD})


def can_assign_users(
    user: User, change_request: ChangeRequest, assignments: Iterable[ChangeRequestAssignment]
) -> bool:
    return can_manage_workflow(user, change_request, assignments)


def can_request_approval(
    user: User, change_request: ChangeRequest, assignments: Iterable[ChangeRequestAssignment]
) -> bool:
    return can_manage_workflow(user, change_request, assignments)


def can_review_analysis_findings(
    user: User, change_request: ChangeRequest, assignments: Iterable[ChangeRequestAssignment]
) -> bool:
    """Module 14 Phase 6: who may mark a Requirement Confirmed/Needs
    Clarification, or change a Security finding's Status. Broader than
    can_manage_workflow (the CR Owner's specific job) - reviewing AI
    findings is meant to be shared with anyone actually doing the
    technical/security review of this change, not just whoever is driving
    its workflow, so Reviewer and Security Reviewer are included here too."""
    if is_admin(user):
        return True
    if change_request.created_by == user.id:
        return True
    roles = assignment_roles_for(user, assignments)
    return bool(
        roles
        & {
            AssignmentRole.OWNER,
            AssignmentRole.TECHNICAL_LEAD,
            AssignmentRole.REVIEWER,
            AssignmentRole.SECURITY_REVIEWER,
        }
    )


# --- Editable fields / versioning snapshot --------------------------------
#
# The single source of truth for "what counts as an editable CR field" -
# used both by the PUT /change-requests/{id} handler (to know what it's
# allowed to touch and diff) and by init_db.py's one-time backfill (to
# build a Version 1 snapshot for CRs that existed before this module).
# Order here is display order for the edit form / history / diff views.

EDITABLE_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    "business_objective",
    "priority",
    "requested_by",
    "target_system",
    "desired_deadline",
    "business_impact",
    "technical_impact",
    "customer_impact",
    "environment",
    "dependencies_note",
    "compliance_requirements",
    "tags",
)

FIELD_LABELS: dict[str, str] = {
    "title": "Title",
    "description": "Description",
    "business_objective": "Business Objective",
    "priority": "Priority",
    "requested_by": "Requested By",
    "target_system": "Target System",
    "desired_deadline": "Desired Deadline",
    "business_impact": "Business Impact",
    "technical_impact": "Technical Impact",
    "customer_impact": "Customer Impact",
    "environment": "Environment",
    "dependencies_note": "Dependencies",
    "compliance_requirements": "Compliance Requirements",
    "tags": "Tags",
}


def normalize_field_value(field: str, value: Any) -> Any:
    """Turns a raw field value - however it arrives, whether read off a
    ChangeRequest ORM object (an enum member, a date object, a JSON-encoded
    tags string) or a freshly-validated PUT payload (an enum member, a
    date object, a real list) - into one comparable, JSON-safe shape.
    Used for both the version snapshot and for diffing old vs new values
    on an edit, so "did this field actually change" and "what does the
    stored snapshot look like" always agree."""
    if value is None:
        return None
    if field == "priority":
        return value.value if hasattr(value, "value") else value
    if field == "desired_deadline":
        return value.isoformat() if hasattr(value, "isoformat") else value
    if field == "tags":
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return value
        return list(value) if value else None
    return value


def _field_snapshot_value(change_request: ChangeRequest, field: str) -> Any:
    return normalize_field_value(field, getattr(change_request, field))


def build_snapshot(change_request: ChangeRequest) -> str:
    """A JSON object of every editable field's current value - what gets
    stored on a ChangeRequestVersion row and diffed by Compare Versions."""
    data = {field: _field_snapshot_value(change_request, field) for field in EDITABLE_FIELDS}
    return json.dumps(data)
