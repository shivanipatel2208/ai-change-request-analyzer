"""Module 13 Phase 2 (AI Analysis 2.0): a computed - not AI-written - diff
between two Analysis rows for the same change request.

Computed over AI-written was his own choice (Phase 2 planning): no extra
AI call/cost on every re-analysis, and it's never wrong about the numbers.
The honest tradeoff of that choice: the added/removed requirement and
affected-component lists below match by normalized text, not by meaning -
a requirement the AI worded slightly differently on the next run shows up
as one "removed" + one "added", not one "changed". That's a real
limitation of a computed diff (see PROJECT_REPORT.md's Known Limitations
once this phase is folded in), not a bug to fix here.

Reuses FieldComparison (app/services/versioning.py) - the exact same
field/label/old_value/new_value/status shape the CR-version "Compare
Versions" feature already uses - rather than inventing a second diff
shape for the same idea (architecture-lock rule 17: avoid duplicate
concepts).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from app.models.analysis import Analysis
from app.models.approval_rule import ApprovalRule
from app.models.change_request import ChangeRequest
from app.services.versioning import FieldComparison
from app.services.workflow_rules import format_approval_types, required_approval_types, risk_bucket


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _field(field: str, label: str, old, new) -> FieldComparison:
    old_s = "" if old is None else str(old)
    new_s = "" if new is None else str(new)
    return FieldComparison(
        field=field,
        label=label,
        old_value=old_s or None,
        new_value=new_s or None,
        status="unchanged" if old_s == new_s else "changed",
    )


@dataclass
class AnalysisDelta:
    fields: list[FieldComparison]
    requirements_added: list[str]
    requirements_removed: list[str]
    affected_components_added: list[str]
    affected_components_removed: list[str]
    is_significant_change: bool
    significant_change_reasons: list[str]
    # Module 18 Phase 2 (Notifications, My Work & Personal Engineering
    # Queue): the same two bucket values already computed below for the
    # "Risk" row in `fields` - broken out as their own typed fields so a
    # caller (app/api/change_requests.py's RISK_ESCALATED check) can
    # compare them directly rather than re-parsing significant_change_
    # reasons' own prose, or re-deriving risk_bucket() from the raw scores
    # a second time.
    risk_bucket_before: str
    risk_bucket_after: str


def compare_analyses(
    change_request: ChangeRequest,
    analysis_a: Analysis,
    analysis_b: Analysis,
    rules: Optional[Iterable[ApprovalRule]] = None,
) -> AnalysisDelta:
    """analysis_a is the earlier analysis, analysis_b the later one - both
    are/were real, persisted analyses (this never compares against
    anything hypothetical or in-progress). `rules` is passed straight
    through to required_approval_types (Module 21) - see that function's
    own docstring."""
    approvals_a = required_approval_types(change_request, analysis_a, rules)
    approvals_b = required_approval_types(change_request, analysis_b, rules)

    bucket_a = risk_bucket(analysis_a.risk_score)
    bucket_b = risk_bucket(analysis_b.risk_score)

    fields = [
        _field("risk_bucket", "Risk", bucket_a.capitalize(), bucket_b.capitalize()),
        _field("risk_score", "Risk score (0-100)", round(analysis_a.risk_score), round(analysis_b.risk_score)),
        _field(
            "complexity",
            "Complexity",
            analysis_a.complexity.value.replace("_", " ").title(),
            analysis_b.complexity.value.replace("_", " ").title(),
        ),
        _field(
            "confidence_score",
            "Classification confidence (0-100)",
            round(analysis_a.confidence_score),
            round(analysis_b.confidence_score),
        ),
        _field("category", "Classification", analysis_a.category, analysis_b.category),
        _field(
            "recommendation",
            "Recommendation",
            analysis_a.recommendation.value if analysis_a.recommendation else None,
            analysis_b.recommendation.value if analysis_b.recommendation else None,
        ),
        _field("effort_estimate", "Effort estimate", analysis_a.effort_estimate, analysis_b.effort_estimate),
        _field("recommended_approvals", "Recommended approvals", format_approval_types(approvals_a), format_approval_types(approvals_b)),
        _field("requirement_count", "Requirements", len(analysis_a.requirements), len(analysis_b.requirements)),
        _field(
            "affected_component_count",
            "Affected components",
            len(analysis_a.affected_components),
            len(analysis_b.affected_components),
        ),
        _field("risk_count", "Risks identified", len(analysis_a.risks), len(analysis_b.risks)),
        _field("test_case_count", "Test cases", len(analysis_a.test_cases), len(analysis_b.test_cases)),
        _field(
            "implementation_task_count",
            "Implementation tasks",
            len(analysis_a.implementation_tasks),
            len(analysis_b.implementation_tasks),
        ),
    ]

    reqs_a = {_normalize_text(r.description): r.description for r in analysis_a.requirements}
    reqs_b = {_normalize_text(r.description): r.description for r in analysis_b.requirements}
    requirements_added = sorted(reqs_b[k] for k in reqs_b.keys() - reqs_a.keys())
    requirements_removed = sorted(reqs_a[k] for k in reqs_a.keys() - reqs_b.keys())

    comps_a = {_normalize_text(c.component_name): c.component_name for c in analysis_a.affected_components}
    comps_b = {_normalize_text(c.component_name): c.component_name for c in analysis_b.affected_components}
    components_added = sorted(comps_b[k] for k in comps_b.keys() - comps_a.keys())
    components_removed = sorted(comps_a[k] for k in comps_a.keys() - comps_b.keys())

    reasons: list[str] = []
    if bucket_a != bucket_b:
        reasons.append(f"Risk moved from {bucket_a} to {bucket_b}.")
    if analysis_a.complexity != analysis_b.complexity:
        reasons.append(f"Complexity changed from {analysis_a.complexity.value} to {analysis_b.complexity.value}.")
    if analysis_a.recommendation != analysis_b.recommendation:
        old_rec = analysis_a.recommendation.value if analysis_a.recommendation else "none"
        new_rec = analysis_b.recommendation.value if analysis_b.recommendation else "none"
        reasons.append(f"Recommendation changed from {old_rec} to {new_rec}.")
    if approvals_a != approvals_b:
        reasons.append(f"Recommended approvals changed from [{format_approval_types(approvals_a)}] to [{format_approval_types(approvals_b)}].")

    return AnalysisDelta(
        fields=fields,
        requirements_added=requirements_added,
        requirements_removed=requirements_removed,
        affected_components_added=components_added,
        affected_components_removed=components_removed,
        is_significant_change=bool(reasons),
        significant_change_reasons=reasons,
        risk_bucket_before=bucket_a,
        risk_bucket_after=bucket_b,
    )
