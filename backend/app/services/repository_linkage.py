"""Module 15 Phase 5 (Repository Intelligence - Integration).

The spec's own instruction for this phase: repository findings should
"feed" the existing Impact Analysis / Dependencies / Risk / Implementation
Plan / Test Cases sections - and explicitly "do not create duplicate
impact systems." Combined with the POST-MODULE-12 architecture lock's own
priority order (data integrity > version correctness > permissions >
auditability > workflow correctness > AI correctness > UI polish), the
safest reading of "feed" is the most conservative one: never invent a new
table, a new impact model, or a second AI call - only *group* repository
findings that already exist (already vetted by Module 15 Phase 3's
hallucination guard, already carrying their own honest, code-computed
confidence label) underneath whichever existing analysis item they
actually seem to be about.

"Seem to be about" is deliberately dumb and auditable rather than clever:
the exact same kind of keyword-overlap heuristic
app/services/repository_matcher.py already uses to shortlist candidate
files before ever calling the AI (no embeddings, no vector database, no
RAG - per the module's own "do not introduce unnecessary infrastructure"
rule). A small tokenizer is duplicated here rather than importing
repository_matcher's own private `_tokenize` - this app's established
convention (see e.g. every app/schemas/*.py file) is that a module's
underscore-prefixed helpers are its own business, and a second, small,
locally-tuned copy is preferred over reaching into another module's
internals.

Computed fresh on every response, never stored anywhere - same rule as
is_outdated/workflow_recommendation/repository_finding_outdated_reasons
elsewhere in this app. An analysis run before any repository scan/match
existed, or one that shares no real words with anything the matcher found,
ends up with every related_files list empty - the same honest "nothing
found" outcome this module treats as valid everywhere else, not an error.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.models.repository_finding import RepositoryFinding

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "this", "that", "from", "into",
    "when", "then", "than", "have", "has", "had", "will", "would", "should", "could",
    "can", "not", "are", "was", "were", "been", "being", "its", "their", "them", "they",
    "you", "your", "our", "ours", "also", "each", "any", "all", "some", "other", "more",
    "most", "use", "used", "using", "via", "per", "let", "need", "needs", "needed",
    "add", "adds", "added", "new", "make", "makes", "made", "get", "gets", "set", "sets",
}

_TOKEN_RE = re.compile(r"[^A-Za-z0-9]+")

# Sharing just one word (often a generic one like "user" or "data") is too
# weak a signal to present as "this file relates to this analysis item" -
# two independent shared words is a meaningfully stronger, still-cheap bar.
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


def _finding_tokens(finding: RepositoryFinding) -> set[str]:
    return _tokenize(finding.file_path, finding.reason, finding.evidence)


def related_files(item_text: str, findings: Iterable[RepositoryFinding]) -> list[str]:
    """The file_path of every repository finding whose own file
    path/reason/evidence shares at least `_MIN_SHARED_TOKENS` meaningful
    words with `item_text`, most-overlapping (then most-confident) first.
    Empty list - the common case - is an honest "nothing in the repository
    scan looks connected to this," never an error."""
    item_tokens = _tokenize(item_text)
    if not item_tokens:
        return []
    scored: list[tuple[RepositoryFinding, int]] = []
    for finding in findings:
        overlap = len(item_tokens & _finding_tokens(finding))
        if overlap >= _MIN_SHARED_TOKENS:
            scored.append((finding, overlap))
    scored.sort(key=lambda pair: (pair[1], pair[0].confidence), reverse=True)
    return [finding.file_path for finding, _overlap in scored]


def annotate_analysis_response(response, findings: list[RepositoryFinding]) -> None:
    """Mutates an already-built AnalysisRead in place, setting every child
    item's `related_files` - mirrors this app's own established "build the
    Pydantic object, then set computed fields on it directly" pattern
    (AnalysisRead.is_outdated/workflow_recommendation,
    RepositoryFindingRead.is_outdated/outdated_reasons). A no-op when
    `findings` is empty (no scan/match has ever run for this change
    request's current analysis yet) - every related_files list simply
    stays at its schema default of [].

    Deliberately does not touch requirements, security_findings, or
    clarification_questions - the spec names Impact Analysis, Dependencies,
    Risk, Implementation Plan, and Test Cases specifically; affected
    components are included too since "which components does this touch"
    is the most direct analog of this module's own headline question."""
    if not findings:
        return

    for component in response.affected_components:
        component.related_files = related_files(f"{component.component_name} {component.reason}", findings)
    for assessment in response.impact_assessments:
        assessment.related_files = related_files(assessment.description, findings)
    for dependency in response.dependencies:
        dependency.related_files = related_files(f"{dependency.dependency_name} {dependency.reason}", findings)
    for risk in response.risks:
        risk.related_files = related_files(f"{risk.description} {risk.mitigation}", findings)
    for test_case in response.test_cases:
        test_case.related_files = related_files(f"{test_case.title} {test_case.description}", findings)
    for task in response.implementation_tasks:
        task.related_files = related_files(f"{task.task} {task.description}", findings)
