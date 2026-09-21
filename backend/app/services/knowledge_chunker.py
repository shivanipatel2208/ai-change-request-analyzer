"""Module 16 Phase 2 (Project Knowledge Base & RAG - Parsing + Chunking).

Turns an uploaded document's file on disk into an ordered list of
KnowledgeChunk rows: extract plain text (format-specific), split it into
labeled sections wherever the format has natural structure, then split
each section into deterministic, size-bounded chunks. No AI is involved in
this step - it's pure text processing, so it runs synchronously right
after upload (see process_document()'s only caller,
app/api/knowledge.py::upload_document) - no queue/worker needed, matching
this app's "no unnecessary infrastructure" rule.

Per-format extraction (extract_sections):
  * .txt: read as one unlabeled section - a plain text file has no
    natural internal structure to label sections by.
  * .md: split on markdown headings (# through ######) - each heading's
    own text becomes that section's label; any content before the first
    heading is one leading unlabeled section. A markdown file with no
    headings at all falls back to being treated as one plain section,
    same as .txt.
  * .pdf: each page becomes one section labeled "Page N" (via pypdf).

Chunking (chunk_sections / _chunk_section_text): a section's text is split
into paragraph-accumulated chunks capped at MAX_CHUNK_CHARS - paragraphs
(blank-line-separated) are never split across two chunks unless a single
paragraph alone exceeds the cap, in which case it's hard-split into fixed-
size pieces. This keeps chunks topically coherent without needing a
heavier NLP-aware splitter, matching the module's own spec instruction to
"use the simplest reliable architecture."

Failure (a corrupt/unreadable PDF, an unreadable text encoding, a document
with no extractable text at all) is caught by process_document() and
recorded as KnowledgeDocumentStatus.FAILED with error_message set -
mirroring app/services/repository_scanner.py's own "a per-item problem is
a recorded state, never an unhandled crash" pattern. A document's `status`
only ever describes parsing/chunking here in Phase 2 - Module 16 Phase 3
(Embedding) fills in each chunk's own `embedding` field afterwards without
needing a further document-level status of its own.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.enums import KnowledgeDocumentStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.knowledge_documents import document_file_path

# A chunk's content is capped at this many characters - generous enough to
# keep a paragraph or two of real documentation together (useful, coherent
# context for the AI in later phases), small enough that Phase 3's
# embedding calls and Phase 4's prompt payloads stay cheap and fast.
MAX_CHUNK_CHARS = 1200

_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


class KnowledgeParsingError(Exception):
    """Raised for a document that can't be parsed at all (corrupt PDF,
    unreadable file, no extractable text). Always caught by
    process_document() and recorded as a FAILED document with this
    message as error_message - never raised out to the API layer
    directly."""


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise KnowledgeParsingError(f"Could not read file: {exc}") from exc


def _extract_markdown_sections(text: str) -> List[Tuple[Optional[str], str]]:
    """Splits markdown text on headings - one section per heading, plus a
    leading unlabeled section for any content before the first heading.
    Sections with no non-whitespace content (e.g. a heading immediately
    followed by another heading) are dropped rather than producing an
    empty chunk."""
    lines = text.splitlines()
    raw_sections: List[Tuple[Optional[str], List[str]]] = []
    current_label: Optional[str] = None
    current_lines: List[str] = []

    for line in lines:
        match = _MARKDOWN_HEADING_RE.match(line)
        if match:
            raw_sections.append((current_label, current_lines))
            current_label = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    raw_sections.append((current_label, current_lines))

    sections = []
    for label, body_lines in raw_sections:
        body = "\n".join(body_lines).strip()
        if body:
            sections.append((label, body))
    return sections


def _extract_pdf_sections(path: Path) -> List[Tuple[Optional[str], str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on an installed extra
        raise KnowledgeParsingError(
            "PDF support requires the 'pypdf' package - run `pip install -r requirements.txt`."
        ) from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - pypdf raises several distinct error types for a bad/corrupt PDF
        raise KnowledgeParsingError(f"Could not open PDF: {exc}") from exc

    sections: List[Tuple[Optional[str], str]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001 - one unreadable page shouldn't fail the whole document
            text = ""
        if text:
            sections.append((f"Page {page_number}", text))

    if not sections:
        raise KnowledgeParsingError("No extractable text found in this PDF (it may be a scanned image).")

    return sections


def extract_sections(path: Path, extension: str) -> List[Tuple[Optional[str], str]]:
    """Returns an ordered list of (section_label, section_text) pairs for
    the given file - the unit chunk_sections() splits within, and the
    unit Module 16 Phase 5's source-attribution "Section: ..." line reads
    directly from a resulting chunk's own section_label."""
    if extension == ".pdf":
        return _extract_pdf_sections(path)

    text = _read_text_file(path)
    if extension == ".md":
        sections = _extract_markdown_sections(text)
        if sections:
            return sections
        # A markdown file with no headings at all is just one big section,
        # same handling as a plain .txt file.
        stripped = text.strip()
        return [(None, stripped)] if stripped else []

    stripped = text.strip()
    return [(None, stripped)] if stripped else []


def _split_paragraph(paragraph: str) -> List[str]:
    """Hard-splits a single paragraph longer than MAX_CHUNK_CHARS into
    fixed-size pieces - only reached for the rare paragraph that alone
    exceeds the cap (e.g. one long unbroken block of text with no blank
    lines). Together these pieces reconstruct the paragraph exactly, with
    nothing dropped."""
    return [paragraph[i : i + MAX_CHUNK_CHARS] for i in range(0, len(paragraph), MAX_CHUNK_CHARS)]


def _chunk_section_text(text: str) -> List[str]:
    """Splits one section's text into paragraph-accumulated chunks capped
    at MAX_CHUNK_CHARS - a paragraph (blank-line-separated) is never split
    across two chunks unless it alone exceeds the cap."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    current = ""

    for paragraph in paragraphs:
        pieces = _split_paragraph(paragraph) if len(paragraph) > MAX_CHUNK_CHARS else [paragraph]
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) > MAX_CHUNK_CHARS and current:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)

    return chunks


def chunk_sections(sections: List[Tuple[Optional[str], str]]) -> List[Tuple[Optional[str], str]]:
    """Expands each (section_label, section_text) pair into one or more
    (section_label, chunk_text) pairs, in original order - a long section
    yields several chunks that all share its own section_label."""
    result: List[Tuple[Optional[str], str]] = []
    for label, text in sections:
        for chunk_text in _chunk_section_text(text):
            result.append((label, chunk_text))
    return result


def process_document(db: Session, document: KnowledgeDocument) -> KnowledgeDocument:
    """Parses, chunks, and persists chunks for one document, updating its
    status along the way (UPLOADED/FAILED -> PROCESSING -> READY/FAILED).
    Safe to call again on any document, including one that already has
    chunks (e.g. a manual re-process after fixing a bad upload) - existing
    chunks are replaced, never left to accumulate duplicates alongside a
    fresh set, and never removed unless a full new set is ready to take
    their place."""
    document.status = KnowledgeDocumentStatus.PROCESSING
    document.error_message = None
    db.commit()

    try:
        path = document_file_path(document)
        sections = extract_sections(path, document.extension)
        chunk_pairs = chunk_sections(sections)
        if not chunk_pairs:
            raise KnowledgeParsingError("No text content could be extracted from this document.")

        for existing in list(document.chunks):
            db.delete(existing)
        db.flush()

        for index, (label, content) in enumerate(chunk_pairs):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=content,
                    section_label=label,
                    char_count=len(content),
                )
            )

        document.status = KnowledgeDocumentStatus.READY
        document.chunk_count = len(chunk_pairs)
        document.processed_at = datetime.utcnow()
        db.commit()
        db.refresh(document)
        return document
    except Exception as exc:  # noqa: BLE001 - any parsing/chunking failure is a recorded FAILED state, never a crash
        db.rollback()
        document.status = KnowledgeDocumentStatus.FAILED
        document.error_message = str(exc)
        document.processed_at = datetime.utcnow()
        db.commit()
        db.refresh(document)
        return document
