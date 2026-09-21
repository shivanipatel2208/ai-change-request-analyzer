"""Module 6 - AI Analysis Engine: the schema for the AI's structured JSON output.

This is what the raw text response from the AI provider gets parsed and
validated against (`AIAnalysisResult.model_validate_json(...)`), *before*
any of it is trusted or persisted. If the AI's response doesn't match this
shape, validation fails loudly and the analysis engine reports a clean
error instead of saving garbage.

Field names mirror the exact JSON structure specified for this module, and
enum-typed fields reuse the app's existing controlled vocabularies
(app.models.enums) wherever one already fits, so persistence (mapping this
onto Analysis + its child tables) is a straightforward field-by-field copy.

A smaller/local model (e.g. Ollama) occasionally writes a "no answer"
placeholder - "None", "Not provided", "N/A" - into a field that's supposed
to be a real enum value or number, instead of actually picking one or
omitting the field. Rather than hard-failing on every one of those, the
helpers below substitute a conservative default and keep going - that's
still "handle validation errors gracefully" (the spec's own words), just
with fewer needless failures. A response that's wrong in some *other* way
still fails validation as before.
"""
import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import (
    AssignmentRole,
    Certainty,
    ComplexityLevel,
    ComponentType,
    ConfidenceLevel,
    DependencyRelationship,
    DependencyType,
    ImpactCategory,
    ImpactLevel,
    Priority,
    RequirementType,
    RiskCategory,
    SecurityCategory,
    SecurityFindingStatus,
    Severity,
    TestType,
)

# Module 14 Phase 4 - the fixed set (and display order) every analysis must
# cover; see AIAnalysisResult.fill_missing_impact_categories below for why
# a missing one is filled in rather than left out.
IMPACT_CATEGORIES_ORDER = ["business", "technical", "customer", "operational", "security", "data", "performance"]

# Module 14 Phase 5 - same idea as IMPACT_CATEGORIES_ORDER above, but for
# Security findings; see AIAnalysisResult.fill_missing_security_categories.
SECURITY_CATEGORIES_ORDER = [
    "authentication",
    "authorization",
    "data_protection",
    "secrets",
    "api_security",
    "rate_limiting",
    "privacy",
    "audit_logging",
    "compliance",
]

_NULLISH = {
    "none",
    "n a",
    "na",
    "not provided",
    "not applicable",
    "unknown",
    "null",
    "",
    "not specified",
    "none specified",
    "tbd",
}

# Test-type near-misses actually seen in real AI responses (or trivially
# likely, given the same pattern) - each maps a plausible-but-not-exact name
# onto the TestType member closest to what it obviously meant, rather than
# failing the whole analysis over a naming choice. Every other unrecognized
# value still fails loudly, as intended (see this file's own docstring).
_TEST_TYPE_VALUES = {member.value for member in TestType}
_TEST_TYPE_SYNONYMS = {
    # DATA_VALIDATION is the only member of this enum that isn't a single
    # obvious word - seen in practice shortened to just "validation".
    "validation": "data_validation",
    "input_validation": "data_validation",
    "data_validate": "data_validation",
    # This enum deliberately has no separate FUNCTIONAL member (see
    # TestType's own docstring) - MANUAL is what a "functional" test (also
    # seen in practice), or a "smoke"/"sanity"/"acceptance"/"uat" one,
    # becomes here.
    "functional": "manual",
    "smoke": "manual",
    "sanity": "manual",
    "acceptance": "manual",
    "uat": "manual",
    "end_to_end": "e2e",
    "load": "performance",
    "stress": "performance",
}


def _normalize(value):
    """Lowercase/underscore-normalize an incoming string for enum matching.
    Returns None for a "no answer" placeholder (see module docstring) so
    callers can substitute a field-appropriate default instead of failing.
    Also treats a literal "a|b|c" echoed back verbatim (a smaller model
    sometimes copies the pipe-separated option list from the prompt instead
    of picking one) as "no answer" too, for the same reason."""
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if "|" in cleaned:
            return None
        cleaned = cleaned.replace("_", " ").replace("-", " ").replace("/", " ")
        cleaned = " ".join(cleaned.split())
        if cleaned in _NULLISH:
            return None
        return cleaned.replace(" ", "_")
    return value


def _clean_effort_text(value):
    """Effort-estimate fields are free text (no fixed vocabulary), so
    _normalize()'s enum handling doesn't apply - but the same weaker/local
    model habit shows up here differently: the JSON shape given to it uses
    illustrative example text like "e.g. 5-8 developer-days" for these
    fields, and a smaller model sometimes echoes that "e.g. ..." formatting
    back verbatim (with the numbers changed) instead of just answering
    directly. Stripping a leading "e.g."/"eg" recovers the real estimate
    without discarding it; an empty result after stripping falls back to
    the field's own "Insufficient information." default."""
    if isinstance(value, str):
        cleaned = re.sub(r"^\s*e\.?g\.?\s*[:,-]?\s*", "", value, flags=re.IGNORECASE).strip()
        return cleaned or None
    return value


def _normalize_certainty(value):
    """Certainty gets its own normalizer rather than reusing _normalize()
    above: "unknown" is a genuine, meaningful value here (the AI is
    explicitly allowed to say "I can't determine this"), whereas everywhere
    else in this file "unknown" is treated as a placeholder for "no answer
    given." Reusing _normalize() would silently turn a real "unknown"
    certainty into the inferred default below - the opposite of what
    Module 13 needs."""
    if isinstance(value, str):
        cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
        if cleaned in ("known", "inferred", "unknown"):
            return cleaned
    return None


def _normalize_security_status(value):
    """SecurityFindingStatus gets its own normalizer for the same reason
    _normalize_certainty() above exists: "not_applicable" is a genuine,
    meaningful value here (Module 14 Phase 5 - a category can genuinely
    not apply to a given change), but "not applicable" is ALSO a member of
    the generic _NULLISH placeholder set above (used everywhere else in
    this file to mean "no real answer given"). Reusing _normalize() would
    silently turn a real "not_applicable" status into the "open" default
    below - discovered via test_module14_phase5.py's
    test_pre_module_14_phase5_shaped_response_fills_all_categories, which
    failed for exactly this reason until this dedicated normalizer was
    added."""
    if isinstance(value, str):
        cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
        if cleaned in ("open", "not_applicable", "acknowledged", "resolved"):
            return cleaned
    return None


def _safe_float(value, default: float):
    """Same idea as _normalize but for numeric fields (probability, score,
    confidence) - a stray "Not provided" string becomes `default` instead
    of a validation error."""
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in _NULLISH:
            return default
        try:
            return float(cleaned)
        except ValueError:
            return default
    return value


class ClassificationResult(BaseModel):
    category: str = Field(..., description="One of the Module 6 classification categories.")
    confidence: float = Field(..., ge=0, le=1)
    reason: str

    @field_validator("confidence", mode="before")
    @classmethod
    def safe_confidence(cls, value):
        return _safe_float(value, default=0.5)


class RequirementItem(BaseModel):
    # "business_objective" and "acceptance_criteria" don't have their own
    # RequirementType value - they're stored as BUSINESS / FUNCTIONAL
    # respectively (see analysis_engine.py) with a label kept in the text.
    category: str = Field(
        ..., description="business_objective | functional | non_functional | constraint | assumption | acceptance_criteria"
    )
    description: str
    priority: Priority = Priority.MEDIUM
    # --- Module 13 (AI Analysis 2.0) ---
    certainty: Certainty = Certainty.INFERRED
    confidence: float = Field(70.0, ge=0, le=100)
    evidence: str = ""

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return _normalize(value) or "functional"

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value):
        return _normalize(value) or "medium"

    @field_validator("certainty", mode="before")
    @classmethod
    def normalize_certainty(cls, value):
        return _normalize_certainty(value) or "inferred"

    @field_validator("confidence", mode="before")
    @classmethod
    def safe_confidence(cls, value):
        return _safe_float(value, default=70.0)


class AffectedComponentItem(BaseModel):
    name: str
    type: ComponentType
    impact_level: ImpactLevel
    reason: str
    confidence: float = Field(..., ge=0, le=100)
    # Module 13 (AI Analysis 2.0)
    certainty: Certainty = Certainty.INFERRED
    # Module 14 (Analysis & Impact Intelligence) - what specifically in the
    # change request grounds this component being affected at all, same
    # role `evidence` already plays for Requirement/Risk.
    evidence: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return _normalize(value) or "other"

    @field_validator("impact_level", mode="before")
    @classmethod
    def normalize_impact(cls, value):
        return _normalize(value) or "low"

    @field_validator("confidence", mode="before")
    @classmethod
    def safe_confidence(cls, value):
        return _safe_float(value, default=50.0)

    @field_validator("certainty", mode="before")
    @classmethod
    def normalize_certainty(cls, value):
        return _normalize_certainty(value) or "inferred"


class DependencyItem(BaseModel):
    name: str
    type: DependencyType
    impact_level: ImpactLevel
    reason: str
    # --- Module 14 (Analysis & Impact Intelligence) ---
    # How directly this change actually relies on it (see
    # app.models.enums.DependencyRelationship) - distinct from `type` above,
    # which is a category (service/library/...), not a directness rating.
    # Defaults to "direct" only because that's this field's most common,
    # least-surprising value absent other information - NOT a license to
    # guess a dependency into existence in the first place; see the "do not
    # invent dependencies" system-prompt rule in analysis_engine.py, which
    # governs whether an item belongs in this list at all.
    relationship: DependencyRelationship = DependencyRelationship.DIRECT
    risk: Severity = Severity.LOW

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return _normalize(value) or "internal"

    @field_validator("impact_level", mode="before")
    @classmethod
    def normalize_impact(cls, value):
        return _normalize(value) or "low"

    @field_validator("relationship", mode="before")
    @classmethod
    def normalize_relationship(cls, value):
        return _normalize(value) or "direct"

    @field_validator("risk", mode="before")
    @classmethod
    def normalize_risk(cls, value):
        return _normalize(value) or "low"


class RiskItem(BaseModel):
    category: RiskCategory
    description: str
    severity: Severity
    probability: float = Field(..., ge=0, le=1)
    score: float = Field(..., ge=0, le=100)
    explanation: str = ""
    mitigation: str = "Insufficient information."
    # --- Module 13 (AI Analysis 2.0) ---
    # Distinct from `probability`: probability is "how likely is this risk
    # to happen", confidence is "how sure is the AI about this assessment
    # at all."
    certainty: Certainty = Certainty.INFERRED
    confidence: float = Field(70.0, ge=0, le=100)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return _normalize(value) or "operational"

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value):
        return _normalize(value) or "medium"

    @field_validator("probability", mode="before")
    @classmethod
    def safe_probability(cls, value):
        # Defaults to a mid-range "genuinely uncertain" value rather than
        # 0 - a risk the model couldn't quantify shouldn't silently read as
        # "no risk."
        return _safe_float(value, default=0.5)

    @field_validator("score", mode="before")
    @classmethod
    def safe_score(cls, value):
        return _safe_float(value, default=50.0)

    @field_validator("certainty", mode="before")
    @classmethod
    def normalize_certainty(cls, value):
        return _normalize_certainty(value) or "inferred"

    @field_validator("confidence", mode="before")
    @classmethod
    def safe_confidence(cls, value):
        return _safe_float(value, default=70.0)


class ImpactAssessmentItem(BaseModel):
    """Module 14 Phase 4: one structured finding for one of the 7 fixed
    impact lenses (see app.models.enums.ImpactCategory). Distinct from a
    RiskItem - this describes the change's general effect through this
    lens, not a specific thing that could go wrong."""

    category: ImpactCategory
    impact_level: ImpactLevel
    description: str
    certainty: Certainty = Certainty.INFERRED
    confidence: float = Field(70.0, ge=0, le=100)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return _normalize(value) or "technical"

    @field_validator("impact_level", mode="before")
    @classmethod
    def normalize_impact(cls, value):
        return _normalize(value) or "medium"

    @field_validator("certainty", mode="before")
    @classmethod
    def normalize_certainty(cls, value):
        return _normalize_certainty(value) or "inferred"

    @field_validator("confidence", mode="before")
    @classmethod
    def safe_confidence(cls, value):
        return _safe_float(value, default=70.0)


class SecurityFindingItem(BaseModel):
    """Module 14 Phase 5: one structured finding for one of the 9 fixed
    security lenses (see app.models.enums.SecurityCategory). Replaces the
    old flat concerns-list approach (SecurityAnalysis below, kept only for
    analyses that predate this) with a real per-category finding."""

    category: SecurityCategory
    finding: str
    severity: Severity
    evidence: str = "Insufficient information."
    recommendation: str = "Insufficient information."
    # Only the AI-settable subset - see SecurityFindingStatus's docstring.
    status: SecurityFindingStatus = SecurityFindingStatus.OPEN

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return _normalize(value) or "compliance"

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value):
        return _normalize(value) or "medium"

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value):
        normalized = _normalize_security_status(value) or "open"
        # The AI is never allowed to claim "acknowledged"/"resolved" -
        # those are reserved for a human reviewer (Module 14 Phase 6).
        return normalized if normalized in ("open", "not_applicable") else "open"


class SecurityAnalysis(BaseModel):
    concerns: List[str] = []
    summary: str = ""


class ComplexityResult(BaseModel):
    level: ComplexityLevel
    reasoning: str
    # Module 14 (Analysis & Impact Intelligence) - a coarse Low/Medium/High
    # rating of how sure the AI is in `level` itself, distinct from the
    # overall classification confidence.
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value):
        return _normalize(value) or "medium"

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):
        return _normalize(value) or "medium"


class EffortEstimate(BaseModel):
    backend: str = "Insufficient information."
    frontend: str = "Insufficient information."
    testing: str = "Insufficient information."
    total: str = "Insufficient information."
    # Module 14 (Analysis & Impact Intelligence) - same role as
    # ComplexityResult.confidence above, but for the effort estimate.
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM

    @field_validator("backend", "frontend", "testing", "total", mode="before")
    @classmethod
    def clean_effort(cls, value):
        return _clean_effort_text(value) or "Insufficient information."

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):
        return _normalize(value) or "medium"


class MissingInformationItem(BaseModel):
    question: str
    # Module 6 spec's own wording ("Critical / Important / Nice to have")
    # rather than the app's Priority enum - mapped onto Priority in
    # analysis_engine.py (critical->CRITICAL, important->HIGH,
    # nice_to_have->LOW) since there's no dedicated column for it.
    priority: str = Field(..., description="critical | important | nice_to_have")
    reason: str

    @field_validator("priority", mode="before")
    @classmethod
    def normalize(cls, value):
        value = _normalize(value) or "important"
        if value in ("nice_to_have", "nice-to-have", "nicetohave", "nice_to_have."):
            return "nice_to_have"
        return value


def _coerce_steps(value):
    """steps must end up as a List[str] here so analysis_engine.py can
    JSON-encode it straight into TestCase.steps (see that column's own
    docstring for why it's stored as JSON text). A weaker/local model
    occasionally returns one newline- or numbered-list-separated string
    instead of a real JSON array - split that into individual step
    strings (stripping any "1." / "2)" numbering it added) rather than
    persisting one giant blob as a single "step". A genuine empty/missing
    answer becomes an empty list, never a validation error."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        lines = [re.sub(r"^\s*\d+[\.\)]\s*", "", line).strip() for line in value.splitlines()]
        return [line for line in lines if line]
    return []


class TestCaseItem(BaseModel):
    id: str
    title: str
    type: TestType
    priority: Priority = Priority.MEDIUM
    description: str
    expected_result: str = "Insufficient information."
    # --- Module 17 (Test Cases & Implementation Plan 2.0) Phase 2 --------
    # Both optional: a change too simple/vague to need real setup steps
    # still gets an honest "None." rather than an invented precondition,
    # and `steps` legitimately empty means the AI didn't have enough to
    # give concrete steps (same "never invent, say so instead" rule as
    # everywhere else in this file).
    preconditions: Optional[str] = None
    steps: List[str] = Field(default_factory=list)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        normalized = _normalize(value) or "manual"
        if normalized in _TEST_TYPE_VALUES:
            return normalized
        # A trailing "_test" ("unit_test", "negative_test", "boundary_test",
        # ...) is a very common way the AI names these that this enum's own
        # values never include - strip it and try again before falling back
        # to the explicit synonym table above.
        if normalized.endswith("_test"):
            stripped = normalized[: -len("_test")]
            if stripped in _TEST_TYPE_VALUES:
                return stripped
            normalized = stripped
        return _TEST_TYPE_SYNONYMS.get(normalized, normalized)

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value):
        return _normalize(value) or "medium"

    @field_validator("preconditions", mode="before")
    @classmethod
    def normalize_preconditions(cls, value):
        # Reuses _clean_effort_text: same "strip a stray leading 'e.g.'
        # and treat an empty result as no answer" behavior, just applied
        # to a free-text field other than an effort estimate.
        return _clean_effort_text(value)

    @field_validator("steps", mode="before")
    @classmethod
    def coerce_steps(cls, value):
        return _coerce_steps(value)


class ImplementationTaskItem(BaseModel):
    task: str
    description: str
    component: str = "Unspecified"
    priority: Priority = Priority.MEDIUM
    estimated_effort: str = "Insufficient information."
    dependencies: Optional[str] = None
    # --- Module 17 (Test Cases & Implementation Plan 2.0) Phase 3 --------
    # A suggestion only, never an actual assignment - see
    # ImplementationTask.owner_suggestion's own docstring for the
    # architecture-lock reasoning. None means the AI had no well-founded
    # suggestion, never a guess just to fill the field.
    owner_suggestion: Optional[AssignmentRole] = None

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value):
        return _normalize(value) or "medium"

    @field_validator("estimated_effort", mode="before")
    @classmethod
    def clean_effort(cls, value):
        return _clean_effort_text(value) or "Insufficient information."

    @field_validator("owner_suggestion", mode="before")
    @classmethod
    def normalize_owner_suggestion(cls, value):
        # Reuses the generic placeholder-detection _normalize() already
        # relies on everywhere else in this file, but - unlike every other
        # normalize_* validator here - has NO fallback default: an
        # unrecognized or placeholder value becomes None (no suggestion)
        # rather than a fabricated role, since this is Module 12's own
        # controlled AssignmentRole vocabulary, not a free-text guess.
        normalized = _normalize(value)
        if normalized in {role.value for role in AssignmentRole}:
            return normalized
        return None


class RecommendationResult(BaseModel):
    # APPROVE | APPROVE_WITH_CONDITIONS | REQUIRES_CLARIFICATION - kept as a
    # plain string (validated against the allowed set below) rather than the
    # ApprovalRecommendation enum directly, because that enum also carries
    # older values (NEEDS_MORE_INFO, REJECT) this module never emits.
    decision: str
    reasoning: str

    @field_validator("decision", mode="before")
    @classmethod
    def normalize(cls, value):
        # No safe default here reads as "approve" - if the model genuinely
        # couldn't decide, "requires_clarification" is the only safe
        # fallback (never silently approves something).
        return _normalize(value) or "requires_clarification"

    @field_validator("decision")
    @classmethod
    def decision_allowed(cls, value: str) -> str:
        allowed = {"approve", "approve_with_conditions", "requires_clarification"}
        if value not in allowed:
            raise ValueError(f"recommendation.decision must be one of {sorted(allowed)}, got {value!r}")
        return value


class AIAnalysisResult(BaseModel):
    """The full structured output the AI must return for one change request."""

    summary: str
    classification: ClassificationResult
    requirements: List[RequirementItem] = []
    affected_components: List[AffectedComponentItem] = []
    dependencies: List[DependencyItem] = []
    risks: List[RiskItem] = []
    # Module 14 Phase 4
    impact_assessments: List[ImpactAssessmentItem] = []
    # Module 14 Phase 5 - `security_analysis` (the old flat blob) is kept
    # alongside the new structured list below, purely as a short executive-
    # summary sentence the frontend can still show above the structured
    # cards - not a second source of the same finding-level detail.
    security_findings: List[SecurityFindingItem] = []
    security_analysis: SecurityAnalysis = SecurityAnalysis()
    complexity: ComplexityResult
    effort: EffortEstimate = EffortEstimate()
    missing_information: List[MissingInformationItem] = []
    test_cases: List[TestCaseItem] = []
    implementation_plan: List[ImplementationTaskItem] = []
    recommendation: RecommendationResult

    @model_validator(mode="after")
    def drop_placeholder_list_items(self):
        """A weaker/local model sometimes says "there are none" by adding a
        single list item whose *name* is itself the placeholder text (e.g.
        a dependency literally named "None specified") instead of just
        returning an empty list. name/description fields aren't enum-typed
        so nothing above catches this - left as-is, it persists as a fake
        dependency/component and renders as a real node in Module 8's
        impact graph. Drop any item whose name is itself a "no answer"
        placeholder rather than a real name, reusing the same _normalize()
        placeholder detection used everywhere else in this file."""
        self.affected_components = [c for c in self.affected_components if _normalize(c.name) is not None]
        self.dependencies = [d for d in self.dependencies if _normalize(d.name) is not None]
        return self

    @model_validator(mode="after")
    def fill_missing_impact_categories(self):
        """Module 14 Phase 4: the spec calls for a card per lens - Business,
        Technical, Customer, Operational, Security, Data, Performance -
        every time, not just whichever ones the AI happened to mention. If
        a weaker/local model (or a genuinely uneventful change) leaves one
        out, fill it with an honest "no assessment given" placeholder
        (unknown certainty, 0 confidence, medium impact) rather than
        silently rendering six cards instead of seven - same "avoid false
        precision, never invent" rule this file follows everywhere else,
        just applied to *which categories exist* instead of *what a field
        says*. A duplicate category from the AI is left as a second entry
        rather than dropped - the frontend only reads the first match per
        category, so it's harmless, and dropping data the AI actually gave
        wouldn't fit "AI correctness" (never discard a real finding)."""
        seen = {item.category.value for item in self.impact_assessments}
        for category in IMPACT_CATEGORIES_ORDER:
            if category not in seen:
                self.impact_assessments.append(
                    ImpactAssessmentItem(
                        category=category,
                        impact_level="medium",
                        description="Insufficient information.",
                        certainty="unknown",
                        confidence=0.0,
                    )
                )
        return self

    @model_validator(mode="after")
    def fill_missing_security_categories(self):
        """Module 14 Phase 5: same reasoning as fill_missing_impact_categories
        above, applied to the 9 fixed Security lenses - a category the AI
        left out gets an honest "nothing flagged" placeholder (severity
        low, status not_applicable) instead of silently rendering fewer
        than 9 cards."""
        seen = {item.category.value for item in self.security_findings}
        for category in SECURITY_CATEGORIES_ORDER:
            if category not in seen:
                self.security_findings.append(
                    SecurityFindingItem(
                        category=category,
                        finding="No security concern was identified for this category.",
                        severity="low",
                        evidence="Insufficient information.",
                        recommendation="No specific recommendation.",
                        status="not_applicable",
                    )
                )
        return self
