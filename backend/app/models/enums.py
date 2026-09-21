"""Shared controlled-vocabulary enums used across the ORM models.

Kept as plain Python str-Enums (not free-text columns) for the fields the
app itself relies on for logic/filtering. Fields that hold AI-generated,
open-ended text (e.g. Analysis.category) are deliberately left as plain
strings instead - see the comment on that column.
"""
import enum

from sqlalchemy import Enum as SAEnum


def sa_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Build a SQLAlchemy Enum column type that stores the member's *value*
    (e.g. "medium") rather than its name (e.g. "MEDIUM"), and gives the
    underlying CHECK constraint / DB type a unique name.
    """
    return SAEnum(enum_cls, name=name, values_callable=lambda obj: [e.value for e in obj])


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    PRODUCT_MANAGER = "product_manager"  # displayed as "Manager" - see
    # app/services/workflow_rules.py::USER_ROLE_LABELS. Kept as the
    # existing wire value (never renamed - see this file's own module
    # docstring) rather than adding a new, confusingly-similar "manager"
    # member for Module 21's practical role list.
    REVIEWER = "reviewer"
    # --- Module 21 (Administration & Configuration) - additive only, same
    # convention as every other enum extension in this app. These three
    # complete the spec's practical role list (Admin/Requester/Engineer/
    # Reviewer/Security Reviewer/Approver/Manager) - the other four already
    # existed above.
    REQUESTER = "requester"
    SECURITY_REVIEWER = "security_reviewer"
    APPROVER = "approver"


class Priority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChangeRequestStatus(str, enum.Enum):
    # Every new change request starts here (Module 4) and stays until a
    # later module runs an AI analysis on it and/or a reviewer acts on it.
    PENDING_ANALYSIS = "pending_analysis"
    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"  # "Under Review" in the Module 12 workflow UI
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"
    # --- Module 12 (Enterprise Workflow) - additive only, see
    # app/services/workflow_rules.py for the allowed-transition graph that
    # ties these (and the ones above) together into one lifecycle:
    # Draft -> Submitted -> Pending Analysis -> Analyzed -> Under Review ->
    # Changes Requested / Approval Required -> Approved/Rejected ->
    # Implementation Planned -> In Progress -> Implemented -> Validated ->
    # Closed, with Cancelled reachable from most non-terminal states.
    ANALYZED = "analyzed"
    CHANGES_REQUESTED = "changes_requested"
    APPROVAL_REQUIRED = "approval_required"
    IMPLEMENTATION_PLANNED = "implementation_planned"
    IN_PROGRESS = "in_progress"
    VALIDATED = "validated"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ComplexityLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class ApprovalRecommendation(str, enum.Enum):
    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    NEEDS_MORE_INFO = "needs_more_info"
    REJECT = "reject"
    # Added for Module 6 (AI Analysis Engine) - the spec's exact wording for
    # "there are open questions that need answers before this can be
    # approved" is "REQUIRES_CLARIFICATION", which is distinct enough from
    # the older NEEDS_MORE_INFO to keep both rather than rename (renaming
    # would change the meaning of NEEDS_MORE_INFO values already sitting in
    # the 3000+ seeded rows).
    REQUIRES_CLARIFICATION = "requires_clarification"


class RequirementType(str, enum.Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    TECHNICAL = "technical"
    BUSINESS = "business"


class ComponentType(str, enum.Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    API = "api"
    INFRASTRUCTURE = "infrastructure"
    THIRD_PARTY = "third_party"
    OTHER = "other"


class ImpactLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DependencyType(str, enum.Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    SERVICE = "service"
    LIBRARY = "library"
    DATABASE = "database"
    API = "api"


# --- Module 14 (Analysis & Impact Intelligence) ------------------------


class DependencyRelationship(str, enum.Enum):
    """How directly this change actually relies on the dependency -
    separate from `DependencyType` above, which is a *category* (service,
    library, ...) rather than a directness rating. DIRECT: this change
    itself calls/uses it. INDIRECT: something this change touches relies
    on it, one step removed. POTENTIAL: plausible but not confidently
    established from the change request as written - see
    analysis_engine.py's "do not invent dependencies" prompt rule; this is
    the AI's way of saying "maybe" instead of asserting a dependency it
    isn't sure about."""

    DIRECT = "direct"
    INDIRECT = "indirect"
    POTENTIAL = "potential"


class ConfidenceLevel(str, enum.Enum):
    """A coarse Low/Medium/High confidence rating - deliberately not the
    finer-grained 0-100 `confidence` float used elsewhere (Requirement,
    Risk, AffectedComponent), because Complexity and Effort are already
    plain-language estimates on purpose ("a range, not fake precision" -
    see Analysis.effort_estimate); pairing that with a fake-precise numeric
    confidence would undercut the same point. Three values only (no
    CRITICAL, unlike Severity) - a confidence rating has no "critical"
    equivalent."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImpactCategory(str, enum.Enum):
    """Module 14 Phase 4: the 7 fixed lenses every analysis assesses impact
    through (see app/models/impact_assessment.py). Distinct from
    `RiskCategory` below - a Risk is a specific thing that could go wrong
    ("the migration could corrupt data"), while an ImpactAssessment
    describes the change's general effect through one lens regardless of
    whether anything goes wrong ("this touches customer-facing billing
    flows"). Also distinct from `ImpactLevel` - this says *what kind* of
    impact, `ImpactLevel` says *how much*."""

    BUSINESS = "business"
    TECHNICAL = "technical"
    CUSTOMER = "customer"
    OPERATIONAL = "operational"
    SECURITY = "security"
    DATA = "data"
    PERFORMANCE = "performance"


class SecurityCategory(str, enum.Enum):
    """Module 14 Phase 5: the 9 fixed lenses a Security finding is
    classified under - replaces the old free-text `Analysis.security_analysis`
    concerns list (kept, nullable, for analyses that predate this table)
    with a real per-category structured finding (see
    app/models/security_finding.py)."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    DATA_PROTECTION = "data_protection"
    SECRETS = "secrets"
    API_SECURITY = "api_security"
    RATE_LIMITING = "rate_limiting"
    PRIVACY = "privacy"
    AUDIT_LOGGING = "audit_logging"
    COMPLIANCE = "compliance"


class KnowledgeDocumentStatus(str, enum.Enum):
    """Module 16 (Project Knowledge Base & RAG): a document's lifecycle
    from upload to searchable. Mirrors RepositoryScanStatus's own
    philosophy - a failed parse/chunk/embed pass is a real, visible,
    permanently recorded state (FAILED + error_message on the document),
    never a silently-dropped upload and never quietly retried in place.

    UPLOADED: the file is saved to disk and a row exists, but parsing/
    chunking/embedding hasn't run yet (or is queued to run next).
    PROCESSING: parsing/chunking/embedding is actively running for this
    document right now.
    READY: fully parsed, chunked, and embedded - eligible for retrieval.
    FAILED: processing was attempted and did not complete; error_message
    on the document explains why. A failed document is never silently
    retried - re-processing it is a deliberate, explicit action.
    """

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SecurityFindingStatus(str, enum.Enum):
    """Module 14 Phase 5: OPEN/NOT_APPLICABLE are the only two values the AI
    itself is ever allowed to set (see
    app/schemas/ai_analysis.py::SecurityFindingItem.normalize_status) -
    ACKNOWLEDGED/RESOLVED are reserved for a human reviewer to set later
    (Module 14 Phase 6's "same reviewed-by-a-human pattern" applied to
    Requirement certainty, applied here to this field instead)."""

    OPEN = "open"
    NOT_APPLICABLE = "not_applicable"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ReviewStatus(str, enum.Enum):
    """Module 14 Phase 6: a human reviewer's verdict on an AI-generated
    Requirement - entirely separate from the AI's own `certainty` (Known/
    Inferred/Unknown) on that same row, which reviewing never touches
    (architecture lock: "AI may recommend but never perform human
    approval" - the AI's certainty/confidence/evidence stay the permanent
    record of what the AI said; this is the separate record of what a
    human then did about it). No "unreviewed" member on purpose: a NULL
    `Requirement.review_status` already means "no human has reviewed this
    yet" without needing a dedicated value for it (same nullable-for-
    pre-existing-rows reasoning as `certainty` itself)."""

    CONFIRMED = "confirmed"
    NEEDS_CLARIFICATION = "needs_clarification"


class RiskCategory(str, enum.Enum):
    TECHNICAL = "technical"
    SECURITY = "security"
    BUSINESS = "business"
    OPERATIONAL = "operational"
    COMPLIANCE = "compliance"
    PERFORMANCE = "performance"
    # Added for Module 6 (AI Analysis Engine) - the spec's risk-analysis
    # categories are security/data/performance/availability/integration/
    # regression/compliance/operational. TECHNICAL and BUSINESS above predate
    # that spec and are kept (additive-only enum changes) in case anything
    # already stored used them.
    DATA = "data"
    AVAILABILITY = "availability"
    INTEGRATION = "integration"
    REGRESSION = "regression"


class Severity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TestType(str, enum.Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    REGRESSION = "regression"
    PERFORMANCE = "performance"
    SECURITY = "security"
    MANUAL = "manual"
    # --- Module 17 (Test Cases & Implementation Plan 2.0) ---------------
    # The spec's own list of test types to draw from - additive-only, same
    # reasoning as every other enum extension in this app (existing seeded
    # TestCase rows using the 7 values above stay perfectly valid). FUNCTIONAL
    # is deliberately not added: MANUAL/UNIT/INTEGRATION/E2E already cover
    # "this is a normal functional test" better than one more generic value
    # would, and the spec's own list is a menu to draw from ("do not
    # generate irrelevant tests"), not a mandate to add every named type.
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    API = "api"
    UI = "ui"
    DATA_VALIDATION = "data_validation"


# --- Module 12 (Enterprise Workflow) ----------------------------------
#
# A per-CR "who's involved" role, distinct from the account-wide UserRole
# above. UserRole answers "what kind of account is this"; AssignmentRole
# answers "what is this person responsible for on THIS change request" -
# the same user can hold different assignment roles on different CRs.


class AssignmentRole(str, enum.Enum):
    REQUESTER = "requester"
    OWNER = "owner"
    TECHNICAL_LEAD = "technical_lead"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    SECURITY_REVIEWER = "security_reviewer"
    QA_OWNER = "qa_owner"
    IMPLEMENTATION_OWNER = "implementation_owner"


class ApprovalType(str, enum.Enum):
    """What kind of sign-off an Approval record represents. Deliberately a
    short, generic list (not one entry per possible reviewer title) - the
    approval matrix in workflow_rules.py maps risk/category to a subset of
    these rather than inventing new types per rule."""

    TECHNICAL = "technical"
    SECURITY = "security"
    PRODUCT = "product"
    ENGINEERING_MANAGER = "engineering_manager"
    DIRECTOR = "director"
    QA = "qa"
    DBA = "dba"
    RELEASE = "release"
    GENERAL = "general"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    CANCELLED = "cancelled"


class HistoryAction(str, enum.Enum):
    """One entry per kind of event the Activity/Audit timeline can show -
    see app/models/change_request_history.py."""

    CREATED = "created"
    FIELD_CHANGED = "field_changed"
    STATUS_CHANGED = "status_changed"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    APPROVAL_INVALIDATED = "approval_invalidated"
    # Module 12 Phase 4: a still-pending approval request withdrawn by
    # whoever could have requested it (Owner/Technical Lead/Admin) -
    # distinct from APPROVAL_INVALIDATED (the CR changed under it) and from
    # REJECTED (the approver said no) - nobody weighed in, it was pulled.
    APPROVAL_CANCELLED = "approval_cancelled"
    COMMENT_ADDED = "comment_added"
    MENTIONED = "mentioned"
    AI_ANALYSIS_COMPLETED = "ai_analysis_completed"
    AI_ANALYSIS_INVALIDATED = "ai_analysis_invalidated"
    VERSION_CREATED = "version_created"
    REPORT_GENERATED = "report_generated"
    REMINDER_SENT = "reminder_sent"
    # Module 13 Phase 4: recorded ALONGSIDE the normal APPROVED/REJECTED/
    # CHANGES_REQUESTED event (never instead of it) whenever that decision
    # didn't match what the AI's own recommendation on the relevant
    # analysis would suggest - see
    # app/services/workflow_rules.py::overrides_ai_recommendation. Purely
    # a record of the fact, never a block on the decision itself - "AI
    # recommends, humans decide" means a human is never wrong for
    # disagreeing with the AI, but it should still be visible on the
    # audit trail when they did.
    AI_RECOMMENDATION_OVERRIDDEN = "ai_recommendation_overridden"
    # Module 14 Phase 6: a human reviewer marked a Requirement Confirmed/
    # Needs Clarification, or moved a Security finding's Status forward
    # (e.g. Acknowledged/Resolved) - see app/api/change_requests.py's
    # review_requirement / update_security_finding_status endpoints.
    REQUIREMENT_REVIEWED = "requirement_reviewed"
    SECURITY_FINDING_STATUS_CHANGED = "security_finding_status_changed"
    # Module 17 (Test Cases & Implementation Plan 2.0) Phase 6: an
    # authorized human edited one AI-generated test case or implementation
    # task. Recorded the same way every other human edit in this app is -
    # old_value/new_value on this append-only row - which is what actually
    # satisfies "never overwrite AI provenance": the AI's original wording
    # stays permanently readable here even after the live row is updated to
    # the human's edit, exactly like a normal ChangeRequest field edit.
    TEST_CASE_EDITED = "test_case_edited"
    IMPLEMENTATION_TASK_EDITED = "implementation_task_edited"
    # Someone answered one of the AI's own clarification questions right on
    # the Missing Information tab - see app/api/change_requests.py's
    # answer_clarification_question. This is what actually flips that
    # question's resolved flag; before this existed resolved could never be
    # set to True by anything.
    CLARIFICATION_ANSWERED = "clarification_answered"
    # Module 19 (Engineering Change Analytics): a POST .../analyze call that
    # raised AnalysisError (provider not configured, provider call failed,
    # malformed/invalid AI response, ...) - recorded the same way a
    # successful analysis is (actor_label="AI Analyzer", no user_id), so
    # "AI analysis failures" on the new analytics dashboard is a real,
    # traceable count rather than an invented statistic. Failures from
    # before this module existed are simply not counted - there was nowhere
    # for them to have been recorded.
    AI_ANALYSIS_FAILED = "ai_analysis_failed"


# --- Module 13 (AI Analysis 2.0) ---------------------------------------
#
# Every AI finding that could plausibly be wrong should say how sure it is,
# not just how much (confidence is the "how much"; Certainty is the "what
# kind of statement is this" - see analysis_engine.py's system prompt for
# the exact definitions given to the AI).


class Certainty(str, enum.Enum):
    KNOWN = "known"  # explicitly stated in the change request, or directly implied by it
    INFERRED = "inferred"  # a reasonable conclusion the AI drew, not stated outright
    UNKNOWN = "unknown"  # cannot be determined from the change request as written


# --- Module 15 (Repository Intelligence) --------------------------------


class RepositoryScanStatus(str, enum.Enum):
    """A RepositoryScan's outcome (app/models/repository_scan.py). FAILED is
    reserved for the walk itself blowing up partway through (e.g. the
    configured path became unreadable mid-scan) - an individual file that
    can't be read/decoded is just skipped and counted in `skipped_count`,
    never enough on its own to fail the whole scan. Mirrors the "existing
    good data is never silently destroyed by a failed run" rule Module 13
    Phase 3 already applies to AI analysis failures: a FAILED scan is its
    own new row, and whatever the last COMPLETED scan indexed stays exactly
    as it was."""

    COMPLETED = "completed"
    FAILED = "failed"


class FileMatchLabel(str, enum.Enum):
    """Module 15 Phase 3 (CR -> File Matching): the hedged, code-enforced
    headline for a RepositoryFinding - computed purely from its numeric
    `confidence` score (see from_confidence() below), never trusted from
    the AI's own wording. The module's own spec is explicit: "never claim
    certainty without evidence" - use "potentially affected"/"likely
    affected"/"possibly related", never "definitely affected" unless
    there's strong evidence. The simplest way to actually guarantee that,
    rather than just asking the AI nicely, is to never give this
    vocabulary a "definitely affected" value at all - no code path can
    ever emit one, regardless of how confident the AI's own reasoning
    text sounds."""

    POSSIBLY_RELATED = "possibly_related"
    POTENTIALLY_AFFECTED = "potentially_affected"
    LIKELY_AFFECTED = "likely_affected"

    @classmethod
    def from_confidence(cls, confidence: float) -> "FileMatchLabel":
        if confidence >= 75:
            return cls.LIKELY_AFFECTED
        if confidence >= 45:
            return cls.POTENTIALLY_AFFECTED
        return cls.POSSIBLY_RELATED


class NotificationType(str, enum.Enum):
    ASSIGNED = "assigned"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    MENTIONED = "mentioned"
    STATUS_CHANGED = "status_changed"
    ANALYSIS_OUTDATED = "analysis_outdated"
    # Module 13 Phase 3: distinct from ANALYSIS_OUTDATED above. That one
    # fires the moment a CR is *edited* ("your last analysis no longer
    # matches the current version"). This one fires after a *re-analysis*
    # completes and the new result is materially different from the one it
    # replaced (bigger risk bucket, new recommendation, etc - see
    # app/services/analysis_delta.py::compare_analyses's
    # is_significant_change) - "the numbers actually got worse/better", not
    # just "the CR changed shape underneath the old analysis."
    ANALYSIS_SIGNIFICANTLY_CHANGED = "analysis_significantly_changed"
    REAPPROVAL_REQUIRED = "reapproval_required"
    REMINDER = "reminder"
    COMMENT_ADDED = "comment_added"
    # --- Module 18 Phase 1 (Notifications, My Work & Personal Engineering
    # Queue) -----------------------------------------------------------
    # Fires once, ever, per Approval - the moment a re-analysis lands the
    # change request in a strictly higher risk bucket than it was in
    # before (see app/services/analysis_delta.py). Distinct from
    # ANALYSIS_SIGNIFICANTLY_CHANGED above: that one is a general "the
    # numbers moved" notice; this one is specifically "the risk got
    # worse", which is worth its own, more urgent-reading event.
    RISK_ESCALATED = "risk_escalated"
    # Fires the first time a change request is ever analyzed (never on a
    # later re-analysis - that's what ANALYSIS_SIGNIFICANTLY_CHANGED /
    # RISK_ESCALATED already cover) - "your change request has been
    # analyzed" for whoever's watching it, not just the person who
    # clicked Analyze.
    ANALYSIS_COMPLETED = "analysis_completed"
    # A still-PENDING approval's own due_date is close (see
    # app/services/approvals.py::approval_due_status) or has already
    # passed. Distinct from REMINDER above, which is a human deliberately
    # nudging someone via the "remind" button - this one is a computed,
    # automatic notice, fired at most once per approval (see
    # app/services/deadlines.py).
    DEADLINE_APPROACHING = "deadline_approaching"


# --- Module 21 (Administration & Configuration) --------------------------
#
# Distinct from HistoryAction above: HistoryAction is scoped to ONE change
# request (its own change_request_id column is required); the events below
# are system-level - who an admin is, what role someone got, whether a
# rule changed - and belong to no single change request. See
# app/models/system_audit_log.py.


class AdminAuditAction(str, enum.Enum):
    USER_CREATED = "user_created"
    USER_ROLE_CHANGED = "user_role_changed"
    USER_ACTIVATED = "user_activated"
    USER_DEACTIVATED = "user_deactivated"
    PERMISSION_CHANGED = "permission_changed"
    APPROVAL_RULE_CREATED = "approval_rule_created"
    APPROVAL_RULE_UPDATED = "approval_rule_updated"
    APPROVAL_RULE_DELETED = "approval_rule_deleted"
    SYSTEM_SETTING_CHANGED = "system_setting_changed"


class Capability(str, enum.Enum):
    """The 9 actions the spec's permissions matrix (section 3) names -
    what app/services/permissions.py checks a role against before an
    endpoint proceeds. Deliberately this short, fixed list - not one
    capability per API route - matching the spec's own "do not
    overengineer" framing for section 4's approval rules, applied the same
    way here."""

    CR_CREATE = "cr_create"
    CR_EDIT = "cr_edit"
    STATUS_CHANGE = "status_change"
    ASSIGNMENT = "assignment"
    APPROVAL = "approval"
    REJECTION = "rejection"
    COMMENTS = "comments"
    REPORTS = "reports"
    ADMINISTRATION = "administration"


class ApprovalRuleType(str, enum.Enum):
    """What an ApprovalRule matches against - see
    app/models/approval_rule.py. RISK matches a risk bucket
    (low/medium/high/critical, the same buckets workflow_rules.risk_bucket
    already computes); CATEGORY matches a keyword found in the analysis
    category / target system / title (the same haystack the old hardcoded
    _CATEGORY_KEYWORD_APPROVALS matched against)."""

    RISK = "risk"
    CATEGORY = "category"
