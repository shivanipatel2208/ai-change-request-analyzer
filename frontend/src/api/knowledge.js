import { apiRequest, API_BASE_URL, ApiError } from './client'

// Module 16 (Project Knowledge Base & RAG): upload, list, chunk-preview,
// embed, search, and archive knowledge-base documents via
// backend/app/api/knowledge.py. Mirrors the thin-wrapper shape of every
// other endpoint module here (see repository.js) - the one exception is
// uploadKnowledgeDocument, which can't reuse apiRequest() since that
// helper always JSON-encodes its body and sets a JSON Content-Type;
// uploading a file needs a multipart/form-data body with no explicit
// Content-Type header (the browser sets its own, boundary included).

/** Every non-archived knowledge document, newest first. Pass
 * includeArchived=true to also see archived ones (e.g. for an "show
 * archived" toggle). */
export function listKnowledgeDocuments(token, { includeArchived = false } = {}) {
  const query = includeArchived ? '?include_archived=true' : ''
  return apiRequest(`/api/knowledge/documents${query}`, { token })
}

/** One knowledge document's own metadata (status, chunk_count, etc). */
export function getKnowledgeDocument(id, token) {
  return apiRequest(`/api/knowledge/documents/${id}`, { token })
}

/** Uploads a file (a browser File/Blob object) as a new knowledge
 * document - the backend saves it, then immediately parses+chunks it, so
 * the response already reflects "ready" or "failed" rather than always
 * coming back "uploaded". Thrown errors are ApiError, same shape as
 * apiRequest's, so callers can handle both the same way. */
export async function uploadKnowledgeDocument(file, token) {
  const formData = new FormData()
  formData.append('file', file)

  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/knowledge/documents`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: formData,
    })
  } catch {
    throw new ApiError('Could not reach the backend. Is it running?', 0)
  }

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await response.json() : null

  if (!response.ok) {
    const detail = data?.detail
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join(' ')
      : detail || `Upload failed with status ${response.status}`
    throw new ApiError(message, response.status)
  }

  return data
}

/** Retries parsing+chunking for a document that came back "failed" - the
 * explicit retry action, never automatic. */
export function reprocessKnowledgeDocument(id, token) {
  return apiRequest(`/api/knowledge/documents/${id}/reprocess`, { method: 'POST', token })
}

/** Embeds (or re-embeds) every chunk of a document via the configured AI
 * provider - a separate, explicit, network-calling step from upload. */
export function embedKnowledgeDocument(id, token) {
  return apiRequest(`/api/knowledge/documents/${id}/embed`, { method: 'POST', token })
}

/** Marks a document archived - it drops out of the default list and out
 * of search/analysis retrieval, but its file/chunks/embeddings are kept
 * intact so unarchiving is instant. */
export function archiveKnowledgeDocument(id, token) {
  return apiRequest(`/api/knowledge/documents/${id}/archive`, { method: 'POST', token })
}

/** Reverses archiveKnowledgeDocument. */
export function unarchiveKnowledgeDocument(id, token) {
  return apiRequest(`/api/knowledge/documents/${id}/unarchive`, { method: 'POST', token })
}

/** Every chunk belonging to one document, in original document order,
 * each reporting is_embedded (never the raw vector itself) - lets the
 * Knowledge Base page preview a document's parsed content. */
export function getKnowledgeDocumentChunks(id, token) {
  return apiRequest(`/api/knowledge/documents/${id}/chunks`, { token })
}

/** Ranks every already-embedded, non-archived chunk by similarity to
 * `query` - the same manual search a person can run themselves, distinct
 * from the automatic retrieval CR analysis does internally. */
export function searchKnowledgeBase(query, token, { topK = 5 } = {}) {
  const params = new URLSearchParams({ q: query, top_k: String(topK) })
  return apiRequest(`/api/knowledge/search?${params.toString()}`, { token })
}
