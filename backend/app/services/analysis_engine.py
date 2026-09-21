"""Module 6 - AI Analysis Engine.

The one place that: builds a prompt from a change request's *real* stored
fields (nothing invented), calls the configured AI provider, parses and
validates the response as JSON matching `AIAnalysisResult`
(app/schemas/ai_analysis.py), and persists it across `Analysis` and its
child tables (Requirement, AffectedComponent, Dependency, Risk,
ClarificationQuestion, TestCase, ImplementationTask - all pre-existing
tables from Module 1).

Deliberately does NOT touch repository files, GitHub, or RAG - the prompt
only ever includes what's already in the `change_requests` row.

Module 13 (AI Analysis 2.0) Phase 1 additions: Requirement/AffectedComponent/
Risk findings now each carry a `certainty` (known/inferred/unknown) label
and a per-finding `confidence`; Requirement and Risk also carry an
`evidence` string. See app/schemas/ai_analysis.py's `_normalize_certainty`
for why "unknown" gets its own normalizer instead of reusing the generic
placeholder-detection every other enum field here relies on.

Module 14 (Analysis & Impact Intelligence) Phase 2 additions:
AffectedComponent also carries `evidence` now (the same role it plays on
Requirement/Risk); Dependency carries `relationship` (direct/indirect/
potential - how directly this change actually relies on it) and `risk`
(a severity rating of relying on it), plus an explicit "do not invent
dependencies" system-prompt rule.

Module 14 Phase 3 additions: Analysis carries a coarse Low/Medium/High
`complexity_confidence` and `effort_confidence` - deliberately not a
finer-grained numeric confidence, since Complexity/Effort are already
plain-language estimates on purpose ("a range, not fake precision").

Module 14 Phase 4 additions: a new ImpactAssessment child table - one
structured finding per fixed lens (Business/Technical/Customer/
Operational/Security/Data/Performance, see app.models.enums.ImpactCategory)
with its own impact_level/certainty/confidence, replacing the frontend's
old habit of assembling a "Business Impact"/"Technical Impact" narrative
out of other fields.

Module 14 Phase 5 additions: a new SecurityFinding child table - one
structured finding per fixed lens (Authentication/Authorization/Data
Protection/Secrets/API Security/Rate Limiting/Privacy/Audit Logging/
Compliance, see app.models.enums.SecurityCategory) with its own severity/
evidence/recommendation/status, alongside (not replacing) the older flat
`security_analysis` blob - that column stays purely so pre-Phase-5
analyses keep rendering something in the Security tab.

Module 17 (Test Cases & Implementation Plan 2.0) Phase 2 additions: each
TestCase now also carries `preconditions` (free text, "None." if nothing
beyond a normal starting state is required) and `steps` (an ordered list,
JSON-encoded in storage - see TestCase.steps's own docstring). The system
prompt now also tells the AI to ground each test case in this same
analysis's own requirements/impact/risks/security findings rather than
generic boilerplate, and to use only the test types genuinely relevant to
this change (the type menu was widened to negative/boundary/api/ui/
data_validation in Phase 1, but nothing requires using all of them).

Module 17 Phase 3 additions: each ImplementationTask now also carries
`owner_suggestion` - reusing Module 12's own AssignmentRole vocabulary as
a *suggestion* only (never a real assignment - that stays Module 12's
own assignments system, per the architecture lock). The system prompt now
also tells the AI to break the plan into phase-oriented tasks only where a
phase is genuinely relevant to this change, and to suggest an owner only
when the task itself clearly calls for a particular kind of person.
"""
import json
import re
from datetime import datetime
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analysis import Analysis
from app.models.affected_component import AffectedComponent
from app.models.change_request import ChangeRequest
from app.models.clarification_question import ClarificationQuestion
from app.models.dependency import Dependency
from app.models.enums import (
    ApprovalRecommendation,
    AssignmentRole,
    ChangeRequestStatus,
    HistoryAction,
    Priority,
    RequirementType,
)
from app.models.impact_assessment import ImpactAssessment
from app.models.implementation_task import ImplementationTask
from app.models.knowledge_evidence import KnowledgeEvidence
from app.models.requirement import Requirement
from app.models.risk import Risk
from app.models.security_finding import SecurityFinding
from app.models.test_case import TestCase
from app.schemas.ai_analysis import AIAnalysisResult
from app.services import history
from app.services.ai.factory import get_ai_provider
from app.services.knowledge_embeddings import KnowledgeEmbeddingError, search_chunks


class AnalysisError(Exception):
    """Raised for any failure running an AI analysis. `status_code` tells
    the API layer which HTTP status to respond with:
    - 503: provider isn't configured (no API key)
    - 504: the provider call timed out
    - 502: the provider call failed for some other reason
    - 422: the provider responded, but the response wasn't valid JSON, or
      didn't match the required schema
    """

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


CLASSIFICATION_CATEGORIES = [
    "Feature Enhancement",
    "Bug Fix",
    "Security",
    "Database",
    "API",
    "UI/UX",
    "Infrastructure",
    "Configuration",
    "Compliance",
    "Performance",
    "Integration",
]

RISK_CATEGORIES = [
    "security",
    "data",
    "performance",
    "availability",
    "integration",
    "regression",
    "compliance",
    "operational",
]

AFFECTED_COMPONENT_TYPES = ["frontend", "backend", "database", "api", "infrastructure", "third_party", "other"]
DEPENDENCY_TYPES = ["internal", "external", "service", "library", "database", "api"]
DEPENDENCY_RELATIONSHIPS = ["direct", "indirect", "potential"]
# Module 17 (Test Cases & Implementation Plan 2.0) Phase 2 added the last
# five values (negative/boundary/api/ui/data_validation) - a menu to draw
# from, not a mandate to use every one on every change (see the "never pad
# with irrelevant types" prompt guidance below, and TestType's own
# docstring in app/models/enums.py).
TEST_TYPES = [
    "unit",
    "integration",
    "e2e",
    "regression",
    "performance",
    "security",
    "manual",
    "negative",
    "boundary",
    "api",
    "ui",
    "data_validation",
]
IMPACT_CATEGORIES = ["business", "technical", "customer", "operational", "security", "data", "performance"]
SECURITY_CATEGORIES = [
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
# Module 17 Phase 3 - Module 12's own per-CR role vocabulary (see
# app.models.enums.AssignmentRole), reused here as a menu of *suggestions*
# only - see ImplementationTask.owner_suggestion's own docstring for why
# this never becomes a second, parallel ownership system.
OWNER_SUGGESTIONS = [role.value for role in AssignmentRole]

_SYSTEM_PROMPT = f"""You are an AI change-request analyst for a software engineering team. You are \
given ONE change request as submitted by a user. You may ALSO be given a "Relevant Documentation" \
section below the change request (Module 16 - Project Knowledge Base & RAG): excerpts retrieved from \
the team's own project knowledge base (architecture docs, API docs, engineering guidelines, security \
policies, deployment docs, etc.) - real project documentation, not something you invented, included only \
when the team's knowledge base actually had something plausibly related to this specific change. Beyond \
the change request and that optional documentation section, you have nothing else - no repository, no \
codebase, no architecture diagrams beyond what a provided excerpt itself contains, no other tickets.

Critical rule - do not hallucinate: beyond the change request and any Relevant Documentation section \
actually provided below, you have NOT been given any repository files, source code, API definitions, \
database schemas, or system architecture. Never invent or assume specifics about them (file names, \
endpoint paths, table names, class names, etc.) beyond what a provided documentation excerpt itself \
states. Where an assessment would require that kind of information and neither the change request nor \
the provided documentation covers it, say so explicitly (e.g. "Insufficient information.") rather than \
guessing. In your writing, clearly distinguish three kinds of statements: facts provided in the request \
(or in a provided documentation excerpt), your own inference/judgment based on those facts, and things \
that are simply unknown.

When a Relevant Documentation section is provided and a specific excerpt in it genuinely supports part \
of your assessment, you may mark that part "known" (per the certainty rules below) and should cite the \
excerpt's own "Source" and "Section" (exactly as given) directly in the relevant field's own evidence/ \
reason text - for example: "Per Security Guidelines.pdf, Section: OTP Authentication, rate-limiting is \
required for OTP attempts." Never treat an excerpt as confirming something it doesn't actually say, and \
never cite a Source/Section that wasn't actually given to you in this exact prompt. If no Relevant \
Documentation section is provided at all, or nothing in it is actually relevant to a given point, that \
point remains "inferred" or "unknown" exactly as it would with no documentation at all - never invent \
supporting documentation that wasn't given to you.

Respond with ONLY a single valid JSON object - no markdown code fences, no commentary before or after \
it. It must match this exact shape:

{{
  "summary": "2-4 sentence plain-language summary of the change request",
  "classification": {{"category": one of {CLASSIFICATION_CATEGORIES}, "confidence": 0.0-1.0, "reason": "why"}},
  "requirements": [
    {{"category": "business_objective|functional|non_functional|constraint|assumption|acceptance_criteria",
      "description": "...", "priority": "low|medium|high|critical",
      "certainty": "known|inferred|unknown", "confidence": 0-100, "evidence": "..."}}
  ],
  "affected_components": [
    {{"name": "...", "type": one of {AFFECTED_COMPONENT_TYPES}, "impact_level": "low|medium|high|critical",
      "reason": "...", "confidence": 0-100, "certainty": "known|inferred|unknown", "evidence": "..."}}
  ],
  "dependencies": [
    {{"name": "...", "type": one of {DEPENDENCY_TYPES}, "impact_level": "low|medium|high|critical", "reason": "...",
      "relationship": one of {DEPENDENCY_RELATIONSHIPS}, "risk": "low|medium|high|critical"}}
  ],
  "risks": [
    {{"category": one of {RISK_CATEGORIES}, "description": "...", "severity": "low|medium|high|critical",
      "probability": 0.0-1.0, "score": 0-100, "explanation": "...", "mitigation": "...",
      "certainty": "known|inferred|unknown", "confidence": 0-100}}
  ],
  "impact_assessments": [
    {{"category": one of {IMPACT_CATEGORIES}, "impact_level": "low|medium|high|critical", "description": "...",
      "certainty": "known|inferred|unknown", "confidence": 0-100}}
  ],
  "security_findings": [
    {{"category": one of {SECURITY_CATEGORIES}, "finding": "...", "severity": "low|medium|high|critical",
      "evidence": "...", "recommendation": "...", "status": "open|not_applicable"}}
  ],
  "security_analysis": {{"concerns": ["..."], "summary": "..."}},
  "complexity": {{"level": "low|medium|high|very_high", "reasoning": "...", "confidence": "low|medium|high"}},
  "effort": {{"backend": "<your estimate>", "frontend": "<your estimate>", "testing": "<your estimate>",
             "total": "<your estimate>", "confidence": "low|medium|high"}},
  "missing_information": [
    {{"question": "...", "priority": "critical|important|nice_to_have", "reason": "..."}}
  ],
  "test_cases": [
    {{"id": "TC-001", "title": "...", "type": one of {TEST_TYPES}, "priority": "low|medium|high|critical",
      "description": "...", "preconditions": "... or 'None.'", "steps": ["step 1", "step 2", "..."],
      "expected_result": "..."}}
  ],
  "implementation_plan": [
    {{"task": "...", "description": "...", "component": "...", "priority": "low|medium|high|critical",
      "estimated_effort": "<your estimate>", "dependencies": "optional, references to earlier tasks or null",
      "owner_suggestion": one of {OWNER_SUGGESTIONS}, or null if you can't make a well-founded suggestion}}
  ],
  "recommendation": {{"decision": "approve|approve_with_conditions|requires_clarification", "reasoning": "..."}}
}}

Wherever this shape shows options separated by "|" (for example "low|medium|high|critical"), that is a \
list of your choices, not literal text - pick exactly ONE of those words as your answer. Never output \
the "|" character itself, and never output placeholder text like "none", "n/a", "not specified", or \
"tbd" for a field that requires picking one of a fixed set of options - always pick the closest real \
option instead.

Wherever this shape asks for "certainty", pick exactly one of: "known" (explicitly stated in the change \
request, or a direct, unambiguous implication of what's stated), "inferred" (a reasonable judgment call \
you made that isn't stated outright), or "unknown" (you genuinely cannot determine this from the change \
request as written - this is a legitimate answer, not a failure to answer). Wherever this shape also asks \
for "confidence" (a separate 0-100 number), that measures how sure you are in your own assessment itself, \
independent of the certainty label - for example a component you're not sure is even affected can still \
carry a stated confidence about that guess. Do not mark something "known" just because you're confident \
in it; a well-reasoned inference is still "inferred" no matter how confident you are in it.

"impact_assessments" must contain exactly one entry for EACH of the {len(IMPACT_CATEGORIES)} categories listed \
above ({", ".join(IMPACT_CATEGORIES)}) - never fewer, never more than one per category. Each entry describes \
the change's general effect through that one lens specifically, independent of the risks list above: a risk is a \
specific thing that could go wrong, while an impact assessment describes what the change touches or affects \
through that lens even if nothing goes wrong (for example, "customer" impact describes how customers experience \
this change, not a risk of a customer-facing outage). If a given lens genuinely has little or no impact for this \
change, say so honestly (a "low" impact_level with a description explaining why) rather than omitting that \
category or inflating its impact to seem more thorough.

"security_findings" must contain exactly one entry for EACH of the {len(SECURITY_CATEGORIES)} categories listed \
above ({", ".join(SECURITY_CATEGORIES)}) - never fewer, never more than one per category. "finding" states what you \
observed for that category from the change request as written (or the honest absence of a concern - never invent \
a vulnerability that isn't grounded in the request). "evidence" is what specifically in the change request grounds \
this finding, the same role it plays for requirements/risks/components elsewhere in this shape. "recommendation" is \
a concrete, actionable suggestion, not a restatement of the finding. "status" must be exactly "open" (a real, \
unresolved concern exists for this category) or "not_applicable" (this category genuinely doesn't apply to this \
change) - never any other value; a human reviewer, not you, is the one who later marks a finding "acknowledged" or \
"resolved".

Only list a dependency if it is a well-founded conclusion from the change request as written - never \
invent a dependency with no plausible connection to it just to fill out the list. For each dependency, \
"relationship" says how directly this change actually relies on it: "direct" (this change itself uses \
it), "indirect" (something this change touches relies on it, one step removed), or "potential" (plausible \
but not confidently established - use this rather than asserting certainty you don't have). "risk" is a \
separate low/medium/high/critical rating of how risky relying on this specific dependency is, independent \
of "impact_level" (which rates how much *this change* would be affected if this dependency were wrong or \
unavailable). "evidence" on an affected component works the same way it does for requirements and risks - \
what in the change request specifically grounds this component being affected at all.

For "test_cases": ground each one in the requirements, impact assessments, risks, and security findings \
you identified above (and any Relevant Documentation actually provided) - a real concern from this \
specific analysis, never generic boilerplate a change like this "usually" gets. Use whichever of the test \
types listed above are genuinely relevant to this change - unlike impact_assessments/security_findings \
above, this list has no fixed required size or one-per-category rule, so never pad it with irrelevant \
types just to appear thorough, and never omit a type (e.g. "security") that a risk or finding above \
clearly calls for. "preconditions" is any setup or starting state the steps below assume (login state, \
existing data, feature flags) - state "None." if nothing beyond a normal starting state is required, \
never invent a specific one. "steps" is an ordered list of short, concrete, literally-followable actions \
(never a single paragraph); leave it an empty list only if the change is too vague to describe any.

For "implementation_plan": break the work into phase-oriented tasks (for example: requirement \
clarification, architecture/design, backend changes, database changes, frontend changes, security, \
testing, deployment, validation) only where a phase is actually relevant to this specific change - never \
emit a task for a phase this change doesn't genuinely touch (a change with no data-model impact gets no \
database task). "owner_suggestion" is only ever a suggestion of what kind of person is best suited to a \
task, never an actual assignment (a human always makes the real assignment separately, through the \
project's own review process) - pick one of {OWNER_SUGGESTIONS} only when the task itself clearly calls \
for that kind of owner (for example a security-hardening task suggesting security_reviewer, a task that \
is itself testing suggesting qa_owner), and leave it null rather than guessing when nothing about the \
task points to a particular kind of owner.

Wherever this shape shows "<your estimate>", replace it with your own honest plain-language estimate - \
never output the literal text "<your estimate>". Effort estimates must be ranges in plain language \
(such as a number of days or weeks), never fake single-number precision, and never prefixed with the \
words "e.g." or "eg" - just state the range directly. If the change request is too vague to assess a \
section meaningfully, still return that section with an honest, minimal answer (an empty list, or \
"Insufficient information." as the reasoning/estimate) rather than omitting the key or inventing detail.

The "confidence" on "complexity" and on "effort" is a coarse low/medium/high rating of how sure you are \
in that specific level/estimate, not the same thing as the overall classification confidence above - a \
vague change request should usually get a lower complexity/effort confidence even if you're still willing \
to give your best-guess level and range. Never let a low confidence talk you into a fake-precise number \
instead of a range - state your honest range and rate your confidence in it separately."""


def _build_user_prompt(change_request: ChangeRequest, *, knowledge_chunks: Optional[list] = None) -> str:
    """Everything the AI is allowed to know about this change - the
    change request's own stored fields, verbatim, plus (Module 16 -
    Project Knowledge Base & RAG) an optional "Relevant Documentation"
    section built from `knowledge_chunks` - whatever
    knowledge_embeddings.search_chunks() retrieved for this change
    request, if anything. Nothing else, ever."""
    lines = [
        f"Title: {change_request.title}",
        f"Description: {change_request.description}",
        f"Business Objective: {change_request.business_objective or 'Not provided.'}",
        f"Priority: {change_request.priority.value}",
        f"Requested By: {change_request.requested_by or 'Not provided.'}",
        f"Target System: {change_request.target_system or 'Not provided.'}",
        f"Desired Deadline: {change_request.desired_deadline.isoformat() if change_request.desired_deadline else 'Not provided.'}",
    ]
    prompt = "Analyze this change request:\n\n" + "\n".join(lines)

    if knowledge_chunks:
        doc_lines = [
            "\n\nRelevant Documentation (retrieved from the team's own project knowledge base - use only "
            "where genuinely relevant; if it doesn't confirm something, that thing is still \"unknown\" or "
            "\"inferred\", never fabricated):"
        ]
        for chunk in knowledge_chunks:
            doc_lines.append(
                f"\nSource: {chunk['document_title']}\n"
                f"Section: {chunk['section_label'] or 'N/A'}\n"
                f"{chunk['content']}"
            )
        prompt += "\n".join(doc_lines)

    return prompt


def _extract_json(text: str) -> str:
    """Strip a ```json ... ``` (or bare ```...```) fence if the model wrapped
    its response in one despite being told not to - cheap robustness that
    doesn't change what we accept as valid."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


_MISSING_INFO_PRIORITY = {
    "critical": Priority.CRITICAL,
    "important": Priority.HIGH,
    "nice_to_have": Priority.LOW,
}

_REQUIREMENT_CATEGORY_MAP = {
    "business_objective": (RequirementType.BUSINESS, "Business Objective"),
    "functional": (RequirementType.FUNCTIONAL, None),
    "non_functional": (RequirementType.NON_FUNCTIONAL, None),
    "constraint": (RequirementType.TECHNICAL, "Constraint"),
    "assumption": (RequirementType.TECHNICAL, "Assumption"),
    "acceptance_criteria": (RequirementType.FUNCTIONAL, "Acceptance Criteria"),
}

_RECOMMENDATION_MAP = {
    "approve": ApprovalRecommendation.APPROVE,
    "approve_with_conditions": ApprovalRecommendation.APPROVE_WITH_CONDITIONS,
    "requires_clarification": ApprovalRecommendation.REQUIRES_CLARIFICATION,
}


def _overall_risk_score(result: AIAnalysisResult) -> float:
    """One 0-100 number to represent the change's overall risk (used by the
    dashboard and the change-requests list). Uses the single worst
    individual risk rather than an average, so one severe risk can't get
    diluted into an unremarkable-looking overall score."""
    if not result.risks:
        return 5.0
    return max(risk.score for risk in result.risks)


def _persist_result(
    db: Session,
    change_request: ChangeRequest,
    result: AIAnalysisResult,
    raw_text: str,
    *,
    knowledge_chunks: Optional[list] = None,
) -> Analysis:
    analysis = Analysis(
        change_request_id=change_request.id,
        summary=result.summary,
        category=result.classification.category,
        complexity=result.complexity.level,
        risk_score=_overall_risk_score(result),
        confidence_score=result.classification.confidence * 100,
        recommendation=_RECOMMENDATION_MAP.get(result.recommendation.decision),
        classification_reason=result.classification.reason,
        complexity_reasoning=result.complexity.reasoning,
        complexity_confidence=result.complexity.confidence,
        security_analysis=json.dumps(result.security_analysis.model_dump()),
        effort_estimate=(
            f"Backend: {result.effort.backend}, Frontend: {result.effort.frontend}, "
            f"Testing: {result.effort.testing}, Total: {result.effort.total}"
        ),
        effort_confidence=result.effort.confidence,
        recommendation_reasoning=result.recommendation.reasoning,
        raw_ai_response=raw_text,
        # Module 12: which CR version this analysis covers - lets the UI
        # detect "the CR changed since this analysis ran" (see
        # app/services/workflow_rules.py::is_analysis_outdated).
        change_request_version=change_request.current_version or 1,
    )
    db.add(analysis)
    db.flush()  # assigns analysis.id without committing yet

    for item in result.requirements:
        req_type, label = _REQUIREMENT_CATEGORY_MAP.get(item.category, (RequirementType.FUNCTIONAL, None))
        description = f"[{label}] {item.description}" if label else item.description
        db.add(
            Requirement(
                analysis_id=analysis.id,
                requirement_type=req_type,
                description=description,
                priority=item.priority,
                certainty=item.certainty,
                confidence=item.confidence,
                evidence=item.evidence or None,
            )
        )

    for item in result.affected_components:
        db.add(
            AffectedComponent(
                analysis_id=analysis.id,
                component_name=item.name,
                component_type=item.type,
                impact_level=item.impact_level,
                reason=item.reason,
                confidence=item.confidence,
                certainty=item.certainty,
                evidence=item.evidence or None,
            )
        )

    for item in result.dependencies:
        db.add(
            Dependency(
                analysis_id=analysis.id,
                dependency_name=item.name,
                dependency_type=item.type,
                impact_level=item.impact_level,
                reason=item.reason,
                relationship_type=item.relationship,
                risk_severity=item.risk,
            )
        )

    for item in result.risks:
        description = f"{item.description} {item.explanation}".strip() if item.explanation else item.description
        db.add(
            Risk(
                analysis_id=analysis.id,
                category=item.category,
                description=description,
                severity=item.severity,
                probability=item.probability,
                score=item.score,
                mitigation=item.mitigation,
                certainty=item.certainty,
                confidence=item.confidence,
                # `explanation` is the AI's stated reasoning for this risk -
                # already folded into `description` above for backward
                # compatibility with Module 6, and stored again here,
                # verbatim, as this risk's evidence.
                evidence=item.explanation or None,
            )
        )

    for item in result.impact_assessments:
        db.add(
            ImpactAssessment(
                analysis_id=analysis.id,
                category=item.category,
                impact_level=item.impact_level,
                description=item.description,
                certainty=item.certainty,
                confidence=item.confidence,
            )
        )

    for item in result.security_findings:
        db.add(
            SecurityFinding(
                analysis_id=analysis.id,
                category=item.category,
                finding=item.finding,
                severity=item.severity,
                evidence=item.evidence,
                recommendation=item.recommendation,
                status=item.status,
            )
        )

    for item in result.missing_information:
        db.add(
            ClarificationQuestion(
                analysis_id=analysis.id,
                question=item.question,
                priority=_MISSING_INFO_PRIORITY.get(item.priority, Priority.MEDIUM),
                reason=item.reason,
                resolved=False,
            )
        )

    for item in result.test_cases:
        db.add(
            TestCase(
                analysis_id=analysis.id,
                test_id=item.id,
                title=item.title,
                test_type=item.type,
                priority=item.priority,
                description=item.description,
                expected_result=item.expected_result,
                # Module 17 Phase 2 - preconditions is free text (already
                # normalized to None for "no answer" - see TestCaseItem's
                # own validator); steps is JSON-encoded the same way
                # ChangeRequest.tags already is (see TestCase.steps's own
                # docstring), an empty list persisting as "[]", never null.
                preconditions=item.preconditions,
                steps=json.dumps(item.steps),
            )
        )

    for item in result.implementation_plan:
        db.add(
            ImplementationTask(
                analysis_id=analysis.id,
                task=item.task,
                description=item.description,
                component=item.component,
                priority=item.priority,
                estimated_effort=item.estimated_effort,
                dependencies=item.dependencies,
                # Module 17 Phase 3 - already normalized to a real
                # AssignmentRole or None by ImplementationTaskItem's own
                # validator; never a fabricated value.
                owner_suggestion=item.owner_suggestion,
            )
        )

    # Module 12: record the event on the Activity timeline as its own
    # system actor ("AI Analyzer"), not attributed to whichever human
    # clicked Analyze/Re-analyze - matches the spec's own timeline example
    # ("AI Analyzer - Analysis completed - Risk: High"). Also: the very
    # first successful analysis moves a CR out of Pending Analysis into
    # Analyzed automatically (the natural next step in the lifecycle);
    # re-analyzing a CR that's already further along (in review, changes
    # requested, etc) does NOT force its status backwards.
    history.record_event(
        db,
        change_request_id=change_request.id,
        action=HistoryAction.AI_ANALYSIS_COMPLETED,
        actor_label="AI Analyzer",
        new_value=f"Risk score: {round(analysis.risk_score)}/100, Complexity: {analysis.complexity.value}",
        version_number=change_request.current_version or 1,
    )
    if change_request.status == ChangeRequestStatus.PENDING_ANALYSIS:
        change_request.status = ChangeRequestStatus.ANALYZED

    # Module 16 (Project Knowledge Base & RAG) - Phase 4/5: record exactly
    # which knowledge-base chunks were retrieved and handed to the AI as
    # context for this specific analysis run, so "Evidence Used" (the
    # module's own spec section 8) can show real sources rather than the
    # AI's own unverifiable say-so. Snapshots document_title/section_label/
    # content/score at retrieval time - see
    # app/models/knowledge_evidence.py's own docstring for why this isn't
    # only a live foreign key to KnowledgeChunk.
    now = datetime.utcnow()
    for chunk in knowledge_chunks or []:
        db.add(
            KnowledgeEvidence(
                analysis_id=analysis.id,
                document_id=chunk["document_id"],
                chunk_id=chunk["chunk_id"],
                document_title=chunk["document_title"],
                section_label=chunk["section_label"],
                content_snippet=chunk["content"],
                similarity_score=chunk["score"],
                change_request_version=change_request.current_version or 1,
                retrieved_at=now,
            )
        )

    db.commit()
    db.refresh(analysis)
    return analysis


def _retrieve_knowledge_context(db: Session, change_request: ChangeRequest) -> list:
    """Module 16 (Project Knowledge Base & RAG) Phase 4: retrieves
    knowledge-base chunks plausibly relevant to this change request, to
    ground the AI's analysis in real project documentation rather than
    only what the change request itself states.

    "Extract relevant concepts" (the module's own spec section 4, step 1)
    is done the simplest reliable way per that same spec's own instruction
    - the change request's own title/description/business objective ARE
    the concepts, fed directly into the same semantic search built in
    Phase 3, rather than a separate NLP extraction step.

    Never lets a knowledge-base problem - nothing embedded yet, the
    configured AI provider doesn't support embeddings, a network hiccup -
    fail the analysis itself: retrieval is optional grounding, not a hard
    dependency of the core analysis feature. Returns [] in any of those
    cases, exactly as if the knowledge base were simply empty."""
    query_parts = [change_request.title, change_request.description, change_request.business_objective]
    query = " ".join(part for part in query_parts if part)
    try:
        # min_score: only genuinely relevant chunks become grounding
        # context - see search_chunks's own docstring for why this
        # differs from the manual search endpoint's default of 0.0.
        return search_chunks(db, query, top_k=5, min_score=0.2)
    except KnowledgeEmbeddingError:
        return []
    except Exception:  # noqa: BLE001 - retrieval is optional grounding, never a reason to fail the analysis
        return []


def run_analysis(db: Session, change_request: ChangeRequest) -> Analysis:
    """Analyze one change request end-to-end: call the AI, validate its
    response, persist it, and return the new Analysis row. Raises
    AnalysisError (with an appropriate status_code) on any failure - the
    caller decides how to surface that to the client.

    Module 13 Phase 3 (AI-failure safety): nothing about a failed run
    touches the database - _persist_result() is the only place that writes
    an Analysis row, and every raise below happens before it's ever
    called. So if this change request already had an analysis, that
    analysis is still exactly as it was: still the latest one, still what
    every other endpoint (GET .../analysis, the report, the dashboard)
    reads. `_prior_note()` below just says so in the error message itself,
    rather than leaving a failed re-analyze click looking like it might
    have silently wiped something out."""
    prior_analysis = (
        db.query(Analysis)
        .filter(Analysis.change_request_id == change_request.id)
        .order_by(Analysis.created_at.desc())
        .first()
    )

    def _prior_note() -> str:
        if prior_analysis is None:
            return ""
        version = prior_analysis.change_request_version or 1
        return f" Its existing analysis (from Version {version}) is untouched and still available."

    provider = get_ai_provider()
    if not provider.is_configured():
        raise AnalysisError(
            "The AI provider isn't configured yet - set ANTHROPIC_API_KEY in backend/.env and "
            f"restart the backend.{_prior_note()}",
            status_code=503,
        )

    settings = get_settings()
    knowledge_chunks = _retrieve_knowledge_context(db, change_request)
    user_prompt = _build_user_prompt(change_request, knowledge_chunks=knowledge_chunks)

    try:
        raw_text = provider.complete(
            user_prompt,
            system=_SYSTEM_PROMPT,
            max_tokens=4096,
            timeout=settings.ai_request_timeout_seconds,
        )
    except AnalysisError:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any SDK/network error becomes a clean AnalysisError
        exc_name = type(exc).__name__
        if "Timeout" in exc_name or "timeout" in str(exc).lower():
            raise AnalysisError(
                f"The AI provider took too long to respond (over {settings.ai_request_timeout_seconds}s). "
                f"Please try again.{_prior_note()}",
                status_code=504,
            ) from exc
        raise AnalysisError(f"The AI provider call failed: {exc}.{_prior_note()}", status_code=502) from exc

    cleaned = _extract_json(raw_text)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AnalysisError(
            f"The AI response wasn't valid JSON ({exc}). This usually clears up on retry.{_prior_note()}",
            status_code=422,
        ) from exc

    try:
        result = AIAnalysisResult.model_validate(parsed)
    except ValidationError as exc:
        raise AnalysisError(
            f"The AI response didn't match the expected analysis format: {exc}{_prior_note()}",
            status_code=422,
        ) from exc

    return _persist_result(db, change_request, result, raw_text, knowledge_chunks=knowledge_chunks)
