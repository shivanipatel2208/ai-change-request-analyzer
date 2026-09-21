import { Fragment, useEffect, useState } from 'react'
import {
  archiveKnowledgeDocument,
  embedKnowledgeDocument,
  getKnowledgeDocumentChunks,
  listKnowledgeDocuments,
  reprocessKnowledgeDocument,
  searchKnowledgeBase,
  unarchiveKnowledgeDocument,
  uploadKnowledgeDocument,
} from '../api/knowledge'
import { useAuth } from '../context/AuthContext'
// Reuses the exact same .cr-list-shell / .cr-toolbar / .table-card /
// .requests-table / .badge / .cr-btn / .cr-analysis-list classes every
// other list page here already defines, rather than inventing a second
// set - only knowledge-base.css adds the handful of rules genuinely new
// to this page (the upload control, the search-results panel).
import '../styles/dashboard.css'
import '../styles/change-request-form.css'
import '../styles/change-requests-list.css'
import '../styles/workflow.css'
import '../styles/knowledge-base.css'

const STATUS_LABELS = { uploaded: 'Uploaded', processing: 'Processing', ready: 'Ready', failed: 'Failed' }
const STATUS_CLASS = {
  uploaded: 'badge--gray',
  processing: 'badge--blue',
  ready: 'badge--green',
  failed: 'badge--red',
}

const ALLOWED_EXTENSIONS = ['.txt', '.md', '.pdf']

function formatDate(isoString) {
  if (!isoString) return '—'
  try {
    return new Date(isoString).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return isoString
  }
}

/** One document's inline, expandable chunk preview - fetched lazily the
 * first time a row is expanded, then cached in the parent's chunksById so
 * re-expanding doesn't re-fetch. Shows each chunk's section label and
 * whether it's been embedded yet (never the raw vector itself - see
 * knowledge_chunk.py's own schema docstring for why). */
function ChunkPreview({ chunks, loading, error }) {
  if (loading) return <p className="cr-list-status-text">Loading chunks…</p>
  if (error) return <p className="cr-list-status-text cr-list-status-text--error">{error}</p>
  if (!chunks || chunks.length === 0) {
    return <p className="ad-empty">This document has no chunks yet.</p>
  }
  return (
    <ul className="cr-analysis-list kb-chunk-list">
      {chunks.map((chunk) => (
        <li key={chunk.id} className="cr-analysis-list-item">
          <span className={`badge ${chunk.is_embedded ? 'badge--green' : 'badge--gray'}`}>
            {chunk.is_embedded ? 'Embedded' : 'Not embedded'}
          </span>
          <div>
            <p className="cr-analysis-list-tag">
              {chunk.section_label || `Chunk ${chunk.chunk_index + 1}`} · {chunk.char_count} chars
            </p>
            <p className="cr-analysis-list-text">{chunk.content}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}

/** Module 16 Frontend phase: the Knowledge Base page - upload documents
 * (.txt/.md/.pdf), see their parse/embed status, search the knowledge
 * base directly, preview a document's parsed chunks, and archive/
 * unarchive documents. Everything shown here is read straight from the
 * backend (Module 16 Phases 1-3) - no client-side chunking, embedding, or
 * scoring logic lives in this file. */
export default function KnowledgeBasePage() {
  const { token } = useAuth()

  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const [showArchived, setShowArchived] = useState(false)

  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)

  const [actionBusyId, setActionBusyId] = useState(null)
  const [actionError, setActionError] = useState(null)

  const [expandedId, setExpandedId] = useState(null)
  const [chunksById, setChunksById] = useState({})
  const [chunksLoadingId, setChunksLoadingId] = useState(null)
  const [chunksError, setChunksError] = useState(null)

  const [searchInput, setSearchInput] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(null)
  const [searchResults, setSearchResults] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)

    listKnowledgeDocuments(token, { includeArchived: showArchived })
      .then((response) => {
        if (!cancelled) setDocuments(response)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.message || 'Could not load the knowledge base.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [token, showArchived, refreshToken])

  function refresh() {
    setRefreshToken((k) => k + 1)
  }

  function handleFileChosen(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    const extension = `.${file.name.split('.').pop()?.toLowerCase()}`
    if (!ALLOWED_EXTENSIONS.includes(extension)) {
      setUploadError(`Unsupported file type "${extension}" - only .txt, .md, and .pdf are accepted.`)
      return
    }

    setUploading(true)
    setUploadError(null)
    uploadKnowledgeDocument(file, token)
      .then(() => refresh())
      .catch((err) => setUploadError(err.message || 'Upload failed.'))
      .finally(() => setUploading(false))
  }

  function runAction(id, action) {
    setActionBusyId(id)
    setActionError(null)
    action()
      .then(() => refresh())
      .catch((err) => setActionError(err.message || 'That action failed.'))
      .finally(() => setActionBusyId(null))
  }

  function toggleExpanded(doc) {
    if (expandedId === doc.id) {
      setExpandedId(null)
      return
    }
    setExpandedId(doc.id)
    if (chunksById[doc.id]) return

    setChunksLoadingId(doc.id)
    setChunksError(null)
    getKnowledgeDocumentChunks(doc.id, token)
      .then((chunks) => setChunksById((prev) => ({ ...prev, [doc.id]: chunks })))
      .catch((err) => setChunksError(err.message || 'Could not load this document’s chunks.'))
      .finally(() => setChunksLoadingId(null))
  }

  function handleSearchSubmit(e) {
    e.preventDefault()
    const query = searchInput.trim()
    if (!query) return

    setSearching(true)
    setSearchError(null)
    searchKnowledgeBase(query, token)
      .then((results) => setSearchResults(results))
      .catch((err) => setSearchError(err.message || 'Search failed.'))
      .finally(() => setSearching(false))
  }

  function clearSearch() {
    setSearchInput('')
    setSearchResults(null)
    setSearchError(null)
  }

  return (
    <div className="cr-list-shell">
      <div className="cr-list-heading">
        <div>
          <h1>Knowledge Base</h1>
          <p>Upload project documentation so CR analysis can ground itself in what your team already knows.</p>
        </div>
        <div className="kb-upload-control">
          <input
            type="file"
            accept=".txt,.md,.pdf"
            onChange={handleFileChosen}
            className="kb-file-input"
            id="kb-file-input"
          />
          <label htmlFor="kb-file-input" className="cr-btn cr-btn--primary">
            {uploading ? 'Uploading…' : '+ Upload Document'}
          </label>
        </div>
      </div>
      {uploadError && <p className="cr-form-error">{uploadError}</p>}

      <form className="cr-toolbar" onSubmit={handleSearchSubmit}>
        <input
          type="text"
          className="cr-search-input"
          placeholder="Search the knowledge base (e.g. “OTP rate limiting”)…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <button type="submit" className="cr-btn cr-btn--secondary" disabled={searching || !searchInput.trim()}>
          {searching ? 'Searching…' : 'Search'}
        </button>
        {searchResults != null && (
          <button type="button" className="cr-btn cr-btn--ghost" onClick={clearSearch}>
            Clear
          </button>
        )}
        <label className="cr-toolbar-checkbox">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived
        </label>
      </form>

      {searchError && <p className="cr-form-error">{searchError}</p>}

      {searchResults != null && (
        <div className="cr-detail-section kb-search-results">
          <h2 className="cr-section-title">Search Results</h2>
          {searchResults.length === 0 ? (
            <p className="ad-empty">Nothing in the knowledge base is relevant to that search.</p>
          ) : (
            <ul className="cr-analysis-list">
              {searchResults.map((result) => (
                <li key={result.chunk_id} className="cr-analysis-list-item">
                  <div>
                    <p className="cr-analysis-list-tag">
                      {result.document_title}
                      {result.section_label ? ` · ${result.section_label}` : ''} ·{' '}
                      {Math.round(result.score * 100)}% match
                    </p>
                    <p className="cr-analysis-list-text">{result.content}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {loading && <p className="cr-list-status-text">Loading knowledge base…</p>}
      {loadError && <p className="cr-list-status-text cr-list-status-text--error">{loadError}</p>}
      {actionError && <p className="cr-form-error">{actionError}</p>}

      {!loading && !loadError && documents.length === 0 && (
        <div className="cr-list-empty">
          <p className="cr-list-empty-title">
            {showArchived ? 'No documents at all yet.' : 'No documents yet.'}
          </p>
          <p className="cr-list-status-text">
            Upload a .txt, .md, or .pdf file above to start building your team&apos;s knowledge base.
          </p>
        </div>
      )}

      {!loading && !loadError && documents.length > 0 && (
        <div className="table-card cr-table-card">
          <div className="table-scroll">
            <table className="requests-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Chunks</th>
                  <th>Uploaded</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => {
                  const busy = actionBusyId === doc.id
                  return (
                    <Fragment key={doc.id}>
                      <tr className="cr-list-row" onClick={() => toggleExpanded(doc)}>
                        <td className="requests-table-title">
                          {doc.title}
                          {doc.archived && <span className="badge badge--gray kb-inline-badge">Archived</span>}
                        </td>
                        <td>
                          <span className={`badge ${STATUS_CLASS[doc.status] || 'badge--gray'}`}>
                            {STATUS_LABELS[doc.status] || doc.status}
                          </span>
                          {doc.status === 'failed' && doc.error_message && (
                            <p className="cr-analysis-list-mitigation">{doc.error_message}</p>
                          )}
                        </td>
                        <td className="table-muted">{doc.chunk_count}</td>
                        <td className="table-muted">{formatDate(doc.uploaded_at)}</td>
                        <td className="kb-actions" onClick={(e) => e.stopPropagation()}>
                          {doc.status === 'failed' && (
                            <button
                              type="button"
                              className="cr-btn cr-btn--secondary cr-btn--small"
                              disabled={busy}
                              onClick={() => runAction(doc.id, () => reprocessKnowledgeDocument(doc.id, token))}
                            >
                              Reprocess
                            </button>
                          )}
                          {doc.status === 'ready' && (
                            <button
                              type="button"
                              className="cr-btn cr-btn--secondary cr-btn--small"
                              disabled={busy}
                              onClick={() => runAction(doc.id, () => embedKnowledgeDocument(doc.id, token))}
                            >
                              {doc.chunk_count > 0 ? 'Embed / Re-embed' : 'Embed'}
                            </button>
                          )}
                          {doc.archived ? (
                            <button
                              type="button"
                              className="cr-btn cr-btn--secondary cr-btn--small"
                              disabled={busy}
                              onClick={() => runAction(doc.id, () => unarchiveKnowledgeDocument(doc.id, token))}
                            >
                              Unarchive
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="cr-btn cr-btn--secondary cr-btn--small"
                              disabled={busy}
                              onClick={() => runAction(doc.id, () => archiveKnowledgeDocument(doc.id, token))}
                            >
                              Archive
                            </button>
                          )}
                        </td>
                      </tr>
                      {expandedId === doc.id && (
                        <tr className="kb-preview-row">
                          <td colSpan={5}>
                            <ChunkPreview
                              chunks={chunksById[doc.id]}
                              loading={chunksLoadingId === doc.id}
                              error={chunksLoadingId === doc.id ? null : chunksError}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
