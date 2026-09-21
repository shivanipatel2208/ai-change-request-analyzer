"""Module 15 Phase 3 (Repository Intelligence - CR -> File Matching).

Answers this module's own headline question - "which source files may
actually be affected by this change request?" - in two stages, both kept
deliberately lightweight (no vector database, no embeddings, no RAG
infrastructure, per the module's own spec: "do not introduce unnecessary
infrastructure"):

  1. A pure-Python, deterministic keyword-overlap scoring pass shortlists
     the most plausibly relevant files out of however many a scan indexed
     (see _score_candidates below). This is what keeps the AI call itself
     cheap and bounded - a repository with hundreds of indexed files is
     never sent to the AI wholesale, only its most plausible ~25.
  2. The shortlisted candidates' own extracted structure (Module 15 Phase
     2's imports/functions/classes/api_routes/database_references/
     config_references - never raw file contents) is handed to the AI
     alongside the change request's own text, asking it to name which of
     THOSE specific candidates are actually affected, with a reason and
     evidence grounded in what was actually extracted.

Mirrors app/services/analysis_engine.py's own shape closely on purpose
(build prompt -> call provider -> parse/validate JSON -> persist), so
this reads as "the same kind of AI call the app already makes," not a new
pattern to learn. The one deliberate difference: a persisted finding's
headline "how sure" label (FileMatchLabel) is computed by code from the
numeric confidence score, never trusted from the AI's own wording - see
that enum's own docstring for why.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analysis import Analysis
from app.models.change_request import ChangeRequest
from app.models.enums import FileMatchLabel
from app.models.indexed_file import IndexedFile
from app.models.repository_finding import RepositoryFinding
from app.models.repository_scan import RepositoryScan
from app.schemas.repository_finding import RepositoryMatchResult
from app.services.ai.factory import get_ai_provider

MAX_CANDIDATE_FILES = 25
MAX_SYMBOLS_PER_FIELD = 12

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "this", "that", "from", "into",
    "when", "then", "than", "have", "has", "had", "will", "would", "should", "could",
    "can", "not", "are", "was", "were", "been", "being", "its", "their", "them", "they",
    "you", "your", "our", "ours", "also", "each", "any", "all", "some", "other", "more",
    "most", "use", "used", "using", "via", "per", "let", "need", "needs", "needed",
    "add", "adds", "added", "new", "make", "makes", "made", "get", "gets", "set", "sets",
}

_TOKEN_RE = re.compile(r"[^A-Za-z0-9]+")


class RepositoryMatchError(Exception):
    """Raised for any failure running a repository match. `status_code`
    mirrors AnalysisError's own convention (503 not configured, 504
    timeout, 502 other provider failure, 422 bad response shape)."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _tokenize(*texts: Optional[str]) -> set[str]:
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


def _load_list(column: Optional[str]) -> list[str]:
    if not column:
        return []
    try:
        return json.loads(column)
    except (TypeError, ValueError):
        return []


def _file_tokens(indexed_file: IndexedFile) -> set[str]:
    parts = [indexed_file.file_path, indexed_file.language or ""]
    for column in (
        indexed_file.imports, indexed_file.functions, indexed_file.classes,
        indexed_file.api_routes, indexed_file.database_references, indexed_file.config_references,
    ):
        parts.extend(_load_list(column))
    return _tokenize(*parts)


def _query_tokens(change_request: ChangeRequest, analysis: Analysis) -> set[str]:
    parts = [change_request.title, change_request.description, change_request.business_objective,
             analysis.summary, analysis.category]
    parts.extend(requirement.description for requirement in analysis.requirements)
    return _tokenize(*parts)


def _score_candidates(query_tokens: set[str], indexed_files: list[IndexedFile]) -> list[IndexedFile]:
    """Ranks every indexed file by how many meaningful tokens it shares
    with the change request's own text - a cheap, fully deterministic
    stand-in for semantic search that needs no embeddings/vector store.
    Only files with at least one shared token are candidates at all; a
    change request that shares nothing with anything in the repository
    yields no candidates, and that's a valid, honest outcome (see
    run_repository_match's early return below), not an error."""
    scored = []
    for indexed_file in indexed_files:
        overlap = len(query_tokens & _file_tokens(indexed_file))
        if overlap > 0:
            scored.append((indexed_file, overlap))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [indexed_file for indexed_file, _score in scored[:MAX_CANDIDATE_FILES]]


def _candidate_digest(indexed_file: IndexedFile) -> dict:
    return {
        "file_path": indexed_file.file_path,
        "language": indexed_file.language,
        "imports": _load_list(indexed_file.imports)[:MAX_SYMBOLS_PER_FIELD],
        "functions": _load_list(indexed_file.functions)[:MAX_SYMBOLS_PER_FIELD],
        "classes": _load_list(indexed_file.classes)[:MAX_SYMBOLS_PER_FIELD],
        "api_routes": _load_list(indexed_file.api_routes)[:MAX_SYMBOLS_PER_FIELD],
        "database_references": _load_list(indexed_file.database_references)[:MAX_SYMBOLS_PER_FIELD],
        "config_references": _load_list(indexed_file.config_references)[:MAX_SYMBOLS_PER_FIELD],
    }


_SYSTEM_PROMPT = """You are assisting a software change-request analyzer. You will be given a change \
request's own description/requirements and a shortlist of candidate source files, each with its \
extracted imports/functions/classes/API routes/database and config references - never its raw source \
code. Decide which of these SPECIFIC candidate files are plausibly affected by the change request, \
and respond with ONLY a JSON object of this exact shape:

{"matches": [{"file_path": "<one of the given candidate file_path values, EXACTLY as given>", \
"impact_level": "low|medium|high|critical", "confidence": <0-100>, \
"reason": "<one sentence, grounded in the change request>", \
"evidence": "<the specific import/function/class/route/reference that justifies this, or \
'file name relevance' if the match is only by naming>"}]}

Rules:
- Only include a file if there is a real, checkable connection to the change request: a shared \
concept in its own imports/functions/classes/routes/references, or a strong file-name/path match. \
Never include a file just because it seems plausible in general.
- `file_path` must be copied EXACTLY from the candidates you were given - never invent a path that \
wasn't in the candidate list.
- Do not claim more certainty than the evidence supports. If the connection is only suggestive, say \
so honestly rather than overstating it - a lower confidence score is expected and fine. Never assert \
a file is "definitely" affected.
- If none of the candidates are genuinely relevant, respond with {"matches": []} - an empty result is \
a valid, honest answer, not a failure.
- Respond with ONLY the JSON object - no markdown fences, no commentary."""


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _build_user_prompt(change_request: ChangeRequest, analysis: Analysis, candidates: list[IndexedFile]) -> str:
    payload = {
        "change_request": {
            "title": change_request.title,
            "description": change_request.description,
            "business_objective": change_request.business_objective,
        },
        "analysis_summary": analysis.summary,
        "analysis_category": analysis.category,
        "requirements": [r.description for r in analysis.requirements],
        "candidate_files": [_candidate_digest(f) for f in candidates],
    }
    return json.dumps(payload, indent=2)


def run_repository_match(
    db: Session,
    change_request: ChangeRequest,
    analysis: Analysis,
    scan: RepositoryScan,
) -> list[RepositoryFinding]:
    """Matches `change_request` (via its given `analysis`) against the
    files `scan` indexed, persists the result as new RepositoryFinding
    rows, and returns them.

    Re-running this for the exact same (change request, analysis, scan)
    triple replaces that triple's own prior findings (an idempotent
    re-run, not an ever-growing pile of duplicates) - but never touches a
    finding tied to a DIFFERENT analysis or scan, which stays exactly as
    it was, the same "old data is real history, never silently
    destroyed" rule Module 13 Phase 3 applies to AI re-analysis.

    Raises RepositoryMatchError on any AI-call failure - nothing is
    persisted or deleted before a successful, validated response comes
    back, mirroring analysis_engine.run_analysis()'s own failure
    handling exactly."""
    indexed_files = list(scan.files)
    query_tokens = _query_tokens(change_request, analysis)
    candidates = _score_candidates(query_tokens, indexed_files)

    if not candidates:
        _replace_findings(db, change_request, analysis, scan, [])
        return []

    provider = get_ai_provider()
    if not provider.is_configured():
        raise RepositoryMatchError(
            "The AI provider isn't configured yet - set ANTHROPIC_API_KEY in backend/.env and restart the backend.",
            status_code=503,
        )

    settings = get_settings()
    user_prompt = _build_user_prompt(change_request, analysis, candidates)

    try:
        raw_text = provider.complete(
            user_prompt,
            system=_SYSTEM_PROMPT,
            max_tokens=2048,
            timeout=settings.ai_request_timeout_seconds,
        )
    except RepositoryMatchError:
        raise
    except Exception as exc:  # noqa: BLE001 - any SDK/network error becomes a clean RepositoryMatchError
        exc_name = type(exc).__name__
        if "Timeout" in exc_name or "timeout" in str(exc).lower():
            raise RepositoryMatchError(
                f"The AI provider took too long to respond (over {settings.ai_request_timeout_seconds}s). "
                "Please try again.",
                status_code=504,
            ) from exc
        raise RepositoryMatchError(f"The AI provider call failed: {exc}.", status_code=502) from exc

    cleaned = _extract_json(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RepositoryMatchError(
            f"The AI response wasn't valid JSON ({exc}). This usually clears up on retry.", status_code=422
        ) from exc

    try:
        result = RepositoryMatchResult.model_validate(parsed)
    except ValidationError as exc:
        raise RepositoryMatchError(
            f"The AI response didn't match the expected format: {exc}", status_code=422
        ) from exc

    candidates_by_path = {f.file_path: f for f in candidates}
    kept_matches = [(candidates_by_path[m.file_path], m) for m in result.matches if m.file_path in candidates_by_path]

    return _replace_findings(db, change_request, analysis, scan, kept_matches)


def _replace_findings(
    db: Session,
    change_request: ChangeRequest,
    analysis: Analysis,
    scan: RepositoryScan,
    kept_matches: list,
) -> list[RepositoryFinding]:
    db.query(RepositoryFinding).filter(
        RepositoryFinding.change_request_id == change_request.id,
        RepositoryFinding.analysis_id == analysis.id,
        RepositoryFinding.repository_scan_id == scan.id,
    ).delete()

    findings: list[RepositoryFinding] = []
    for indexed_file, match in kept_matches:
        finding = RepositoryFinding(
            change_request_id=change_request.id,
            change_request_version=change_request.current_version or 1,
            analysis_id=analysis.id,
            repository_scan_id=scan.id,
            indexed_file_id=indexed_file.id,
            impact_level=match.impact_level,
            confidence=match.confidence,
            match_label=FileMatchLabel.from_confidence(match.confidence),
            reason=match.reason,
            evidence=match.evidence,
            created_at=datetime.utcnow(),
        )
        db.add(finding)
        findings.append(finding)

    db.commit()
    for finding in findings:
        db.refresh(finding)
    return findings
