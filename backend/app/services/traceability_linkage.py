"""Module 17 Phase 4 (Test Cases & Implementation Plan 2.0 - Traceability).

The spec's own instruction: provide Requirement -> Implementation Task ->
Test Case traceability. Per this module's own Phase 1 decision (see
TestCaseRead/ImplementationTaskRead's own docstrings), requirement_references
and risk_references are deliberately NOT AI-generated - asking the AI to
cite a Requirement/Risk ID at generation time would mean citing IDs that
don't exist yet (they're only assigned once _persist_result flushes each
row), the exact hallucination-by-construction risk Module 15's own
"AI never invents a file path, code enforces the label" rule exists to
avoid. Instead this mirrors app/services/repository_linkage.py's own
established pattern exactly: a small, locally-tuned keyword-overlap
tokenizer, computed fresh on every response, never stored anywhere.

Unlike repository_linkage (which links against RepositoryFinding rows that
live outside the analysis being built), the Requirement and Risk rows here
are already sitting right on the same AnalysisRead response being
annotated - no separate query is needed, since a test case/task can only
ever be traceable to a requirement/risk from its own analysis (tying an
artifact to a requirement from some OTHER analysis/version would violate
the architecture lock's own "never tied to the wrong version" rule).

A small tokenizer is duplicated here rather than importing
repository_linkage's own private `_tokenize` - this app's established
convention (see that module's own docstring) is that a module's
underscore-prefixed helpers are its own business, and a second, small,
locally-tuned copy is preferred over reaching into another module's
internals.

Computed fresh on every response, never stored. An analysis with no
requirements/risks at all (or one where nothing shares meaningful words
with a given test case/task) ends up with empty reference lists - the
same honest "nothing found" outcome repository_linkage treats as valid.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.schemas.requirement import RequirementRead
from app.schemas.risk import RiskRead

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "this", "that", "from", "into",
    "when", "then", "than", "have", "has", "had", "will", "would", "should", "could",
    "can", "not", "are", "was", "were", "been", "being", "its", "their", "them", "they",
    "you", "your", "our", "ours", "also", "each", "any", "all", "some", "other", "more",
    "most", "use", "used", "using", "via", "per", "let", "need", "needs", "needed",
    "add", "adds", "added", "new", "make", "makes", "made", "get", "gets", "set", "sets",
}

_TOKEN_RE = re.compile(r"[^A-Za-z0-9]+")

# Same reasoning as repository_linkage._MIN_SHARED_TOKENS: one shared word
# (often a generic one like "user" or "checkout") is too weak a signal to
# present as a real traceability link.
_MIN_SHARED_TOKENS = 2


def _tokenize(*texts: str | None) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        if not text:
            continue
        for raw in _TOKEN_RE.split(text):
            word = raw.lower()
            if len(word) < 3 or word in _STOPWORDS:
                continue
            tokens.add(word)
    return tokens


def _requirement_tokens(requirement: RequirementRead) -> set[str]:
    return _tokenize(requirement.description, requirement.evidence)


def _risk_tokens(risk: RiskRead) -> set[str]:
    return _tokenize(risk.description, risk.mitigation, risk.evidence)


def requirement_references(item_text: str, requirements: Iterable[RequirementRead]) -> list[str]:
    """"REQ-<id>" for every requirement whose own description/evidence
    shares at least `_MIN_SHARED_TOKENS` meaningful words with `item_text`,
    most-overlapping first. The "REQ-" prefix mirrors TestCase.test_id's
    own "TC-001" human-readable style - <id> is the requirement's real
    database id, so a "REQ-7" reference points at exactly one row, never
    an ambiguous label."""
    item_tokens = _tokenize(item_text)
    if not item_tokens:
        return []
    scored: list[tuple[RequirementRead, int]] = []
    for requirement in requirements:
        overlap = len(item_tokens & _requirement_tokens(requirement))
        if overlap >= _MIN_SHARED_TOKENS:
            scored.append((requirement, overlap))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [f"REQ-{requirement.id}" for requirement, _overlap in scored]


def risk_references(item_text: str, risks: Iterable[RiskRead]) -> list[str]:
    """Same as requirement_references above, but against this analysis's
    own Risk rows - "RISK-<id>"."""
    item_tokens = _tokenize(item_text)
    if not item_tokens:
        return []
    scored: list[tuple[RiskRead, int]] = []
    for risk in risks:
        overlap = len(item_tokens & _risk_tokens(risk))
        if overlap >= _MIN_SHARED_TOKENS:
            scored.append((risk, overlap))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [f"RISK-{risk.id}" for risk, _overlap in scored]


def annotate_analysis_response(response) -> None:
    """Mutates an already-built AnalysisRead in place, setting every test
    case's requirement_references/risk_references and every implementation
    task's requirement_references - mirrors repository_linkage.
    annotate_analysis_response's own "build the Pydantic object, then set
    computed fields on it directly" pattern. A no-op when this analysis has
    neither requirements nor risks of its own (every reference list simply
    stays at its schema default of [])."""
    requirements = response.requirements
    risks = response.risks
    if not requirements and not risks:
        return

    for test_case in response.test_cases:
        text = f"{test_case.title} {test_case.description} {test_case.expected_result}"
        test_case.requirement_references = requirement_references(text, requirements)
        test_case.risk_references = risk_references(text, risks)

    for task in response.implementation_tasks:
        text = f"{task.task} {task.description}"
        task.requirement_references = requirement_references(text, requirements)
