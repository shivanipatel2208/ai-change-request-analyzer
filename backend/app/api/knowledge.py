"""Module 16 (Project Knowledge Base & RAG): upload, list, chunk, embed,
and search knowledge-base documents.

Phase 1 (Foundation): upload/list/get.
Phase 2 (Parsing + Chunking): upload now parses+chunks synchronously; a
reprocess endpoint retries a failed document; a chunks endpoint previews
the result.
Phase 3 (Embedding + Vector Search): an explicit embed endpoint (a
separate, network-calling step - see knowledge_embeddings.py's own
docstring for why it isn't chained into upload) and a search endpoint.

Any authenticated user can use any of this for now - the same starting
point Module 15's own api/repository.py set for its first phase ("per-CR
permission checks arrive once a scan's findings are actually tied to
one"). This module's own Phase 7 security pass is where real role-based
restriction (who may upload/delete vs who may only view) gets decided and
enforced, per this module's own spec section 9.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User
from app.schemas.knowledge_chunk import KnowledgeChunkRead
from app.schemas.knowledge_document import KnowledgeDocumentRead
from app.schemas.knowledge_search import KnowledgeSearchResult
from app.services.knowledge_chunker import process_document
from app.services.knowledge_documents import KnowledgeDocumentError, save_uploaded_document
from app.services.knowledge_embeddings import KnowledgeEmbeddingError, embed_document, search_chunks

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _get_document_or_404(db: Session, document_id: int) -> KnowledgeDocument:
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found.")
    return document


@router.post("/documents", response_model=KnowledgeDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocument:
    """Saves the uploaded file to disk, creates its KnowledgeDocument row,
    and immediately parses+chunks it (Module 16 Phase 2) - synchronous,
    since parsing/chunking is pure, fast, local text processing with no
    external call, matching this app's "no queue/worker" rule. The
    returned document's `status` therefore already reflects the outcome:
    "ready" (chunked successfully - see chunk_count) or "failed" (see
    error_message) rather than always coming back "uploaded". Rejects
    unsupported extensions, empty files, and oversized files with a 400
    before any of that even starts (see knowledge_documents.py's own
    validation) - those are upload-time rejections, distinct from a
    parsing failure on an otherwise valid, accepted file."""
    content = await file.read()
    try:
        document = save_uploaded_document(
            db,
            original_filename=file.filename or "document",
            content=content,
            uploaded_by=current_user.id,
        )
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return process_document(db, document)


@router.post("/documents/{document_id}/reprocess", response_model=KnowledgeDocumentRead)
def reprocess_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocument:
    """Re-runs parsing+chunking for one already-uploaded document - the
    deliberate, explicit retry action for a document that came back
    FAILED (e.g. after fixing whatever made it unparseable and re-
    uploading the file under the same title isn't practical), rather than
    ever silently retrying on its own."""
    document = _get_document_or_404(db, document_id)
    return process_document(db, document)


@router.post("/documents/{document_id}/embed", response_model=KnowledgeDocumentRead)
def embed_document_endpoint(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocument:
    """Embeds (or re-embeds) every chunk of one document via the
    configured AI provider (Module 16 Phase 3) - a separate, explicitly-
    triggered step from upload/chunking, since this one makes a real
    network call to an AI provider rather than being pure local text
    processing (see knowledge_embeddings.py's own docstring for why).
    Returns the same KnowledgeDocumentRead shape as every other document
    endpoint - embeddings themselves are never exposed in any API
    response (see KnowledgeChunkRead's own docstring)."""
    document = _get_document_or_404(db, document_id)
    try:
        return embed_document(db, document)
    except KnowledgeEmbeddingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/search", response_model=list[KnowledgeSearchResult])
def search_knowledge_base(
    q: str = Query(..., min_length=1, description="The search query to find relevant knowledge-base chunks for."),
    top_k: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Embeds `q` and ranks every already-embedded chunk (from a non-
    archived document) by cosine similarity to it - Module 16 Phase 3's
    own manual search endpoint, and the same retrieval Phase 4's CR
    analysis integration will call internally to gather grounding
    context."""
    try:
        return search_chunks(db, q, top_k=top_k)
    except KnowledgeEmbeddingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/documents/{document_id}/chunks", response_model=list[KnowledgeChunkRead])
def list_document_chunks(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeChunk]:
    """Every chunk belonging to one document, in original document order
    - lets the frontend (Phase 6) preview a document's content, and gives
    a direct way to verify parsing/chunking without needing the retrieval
    step (Phase 3/4) built yet."""
    document = _get_document_or_404(db, document_id)
    # is_embedded is a computed field, not a real attribute on the
    # KnowledgeChunk ORM model (see knowledge_chunk.py's own schema
    # docstring) - automatic from_attributes mapping would silently default
    # it to False for every chunk, so each KnowledgeChunkRead is built
    # explicitly here instead.
    return [
        KnowledgeChunkRead(
            id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            section_label=chunk.section_label,
            content=chunk.content,
            char_count=chunk.char_count,
            is_embedded=chunk.embedding is not None,
        )
        for chunk in document.chunks
    ]


@router.get("/documents", response_model=list[KnowledgeDocumentRead])
def list_documents(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeDocument]:
    """Every document, newest first - archived documents are left out
    unless `include_archived=true` is passed (same "hidden, not deleted"
    idea as ChangeRequest never being hard-deleted elsewhere in this app).
    The Knowledge Base page uses the default view; a future "show
    archived" toggle there is what `include_archived` is for."""
    query = db.query(KnowledgeDocument)
    if not include_archived:
        query = query.filter(KnowledgeDocument.archived.is_(False))
    return query.order_by(KnowledgeDocument.uploaded_at.desc()).all()


@router.post("/documents/{document_id}/archive", response_model=KnowledgeDocumentRead)
def archive_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocument:
    """Marks a document archived - it drops out of the default list and
    out of search/analysis retrieval (knowledge_embeddings.py::search_chunks
    already filters on KnowledgeDocument.archived), but its file, chunks,
    and embeddings are all left exactly as they are so unarchiving is
    instant and lossless. Never a hard delete - matches this app's
    established "archive, don't destroy" pattern (ChangeRequest, and this
    module's own KnowledgeEvidence rows, which snapshot a document's title
    specifically so they stay meaningful even after it's archived)."""
    document = _get_document_or_404(db, document_id)
    document.archived = True
    db.commit()
    db.refresh(document)
    return document


@router.post("/documents/{document_id}/unarchive", response_model=KnowledgeDocumentRead)
def unarchive_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocument:
    """Reverses archive_document - the document reappears in the default
    list and becomes eligible for search/analysis retrieval again."""
    document = _get_document_or_404(db, document_id)
    document.archived = False
    db.commit()
    db.refresh(document)
    return document


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentRead)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocument:
    return _get_document_or_404(db, document_id)
