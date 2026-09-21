"""Module 16 Phase 3 (Project Knowledge Base & RAG - Embedding + Vector
Search): turns a document's already-chunked text into real AI embeddings
via this app's existing swappable AIProvider abstraction, and does brute-
force cosine-similarity search over them.

Deliberately NOT triggered automatically by upload/chunking (Phase 2) -
embedding needs a network call to an AI provider, unlike parsing/chunking
which is pure local text processing. Keeping it a separate, explicitly-
triggered step means:
  * Phase 1/2's own tests stay network-free - they never call a real AI
    provider, matching this app's established testing pattern (the
    analysis engine and repository-matching tests always monkeypatch
    get_ai_provider rather than hitting a real API - see
    tests/test_module15_phase3.py and tests/test_module16_phase3.py for
    this phase's own version of that same pattern).
  * A slow/failed/rate-limited embedding call never blocks or corrupts an
    otherwise-successful upload+chunk - a document already sitting at
    "ready" (chunked - see knowledge_chunker.py) stays exactly that
    regardless of what happens here.

No vector database - each chunk's embedding is stored as a JSON-encoded
list[float] on KnowledgeChunk.embedding (same "one text column, not a new
table" pattern used throughout this app - ChangeRequest.tags,
IndexedFile's Phase 2 columns), and search is brute-force cosine
similarity computed in pure Python. Perfectly fine at hackathon scale (a
handful of documents, at most a few hundred chunks) and avoids the
"unnecessary infrastructure" this module's own spec explicitly warns
against (no Pinecone/pgvector/FAISS/etc).
"""
import json
import math
from typing import List

from sqlalchemy.orm import Session

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.ai.factory import get_ai_provider


class KnowledgeEmbeddingError(Exception):
    """Raised when embeddings can't be produced right now - the
    configured AI provider isn't set up, doesn't support embed() at all,
    or a network/provider call failed. Caught by the API layer and turned
    into a 400 with a plain-language reason, never a bare 500."""


def embed_document(db: Session, document: KnowledgeDocument) -> KnowledgeDocument:
    """Embeds every chunk of one document - re-embedding replaces each
    chunk's prior vector, if any, rather than leaving old and new vectors
    both sitting around. Raises KnowledgeEmbeddingError on any failure;
    nothing about the document or its chunks is changed in that case, so
    a failed embed attempt never leaves a document half-embedded (the
    chunk loop below only assigns vectors after the provider call has
    already returned a complete, correctly-sized result for all of
    them)."""
    chunks: List[KnowledgeChunk] = list(document.chunks)
    if not chunks:
        raise KnowledgeEmbeddingError("This document has no chunks to embed yet - process it first.")

    provider = get_ai_provider()
    try:
        vectors = provider.embed([chunk.content for chunk in chunks])
    except NotImplementedError as exc:
        raise KnowledgeEmbeddingError(str(exc)) from exc
    except KnowledgeEmbeddingError:
        raise
    except Exception as exc:  # noqa: BLE001 - any provider/network failure becomes one clean, catchable error
        raise KnowledgeEmbeddingError(f"Embedding failed: {exc}") from exc

    if len(vectors) != len(chunks):
        raise KnowledgeEmbeddingError(
            f"Embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks."
        )

    for chunk, vector in zip(chunks, vectors):
        chunk.embedding = json.dumps(vector)
    db.commit()
    db.refresh(document)
    return document


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_chunks(db: Session, query: str, *, top_k: int = 5, min_score: float = 0.0) -> List[dict]:
    """Embeds `query` with the configured AI provider, then ranks every
    embedded, non-archived document's chunk by cosine similarity to it -
    brute force, fine at hackathon scale (see module docstring). A chunk
    belonging to an archived document, or one that hasn't been embedded
    yet, is silently excluded from ranking (never an error) - same as an
    archived document already being excluded from the default document
    list in api/knowledge.py::list_documents.

    `min_score` (default 0.0 - no filtering) drops any result scoring
    below it before truncating to `top_k`. The manual search endpoint
    (api/knowledge.py::search_knowledge_base) leaves this at 0.0 - a
    person searching may still want to see the closest results even if
    weak. app/services/analysis_engine.py::_retrieve_knowledge_context
    passes a real threshold instead: injecting a barely-related chunk into
    the AI's prompt as "Relevant Documentation" risks exactly the
    fabrication this module's own spec warns against (section 6 - "Do not
    fabricate project facts"), so grounding context should only ever be
    genuinely relevant, not merely "the least-bad thing on file." A
    deliberately simple, adjustable heuristic - not a scientifically tuned
    cutoff.

    Returns the top `top_k` results (after the `min_score` filter) as
    plain dicts (not ORM objects, since each carries a computed similarity
    score alongside the chunk/document data), ordered by similarity,
    highest first. Returns [] for a blank query rather than embedding an
    empty string."""
    if not query or not query.strip():
        return []

    provider = get_ai_provider()
    try:
        query_vector = provider.embed([query])[0]
    except NotImplementedError as exc:
        raise KnowledgeEmbeddingError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise KnowledgeEmbeddingError(f"Embedding the search query failed: {exc}") from exc

    candidates = (
        db.query(KnowledgeChunk)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .filter(KnowledgeDocument.archived.is_(False))
        .filter(KnowledgeChunk.embedding.isnot(None))
        .all()
    )

    scored = []
    for chunk in candidates:
        try:
            vector = json.loads(chunk.embedding)
        except (TypeError, ValueError):
            continue
        score = _cosine_similarity(query_vector, vector)
        if score >= min_score:
            scored.append((score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    results = []
    for score, chunk in scored[:top_k]:
        document = chunk.document
        results.append(
            {
                "score": score,
                "chunk_id": chunk.id,
                "document_id": document.id,
                "document_title": document.title,
                "section_label": chunk.section_label,
                "content": chunk.content,
            }
        )
    return results
