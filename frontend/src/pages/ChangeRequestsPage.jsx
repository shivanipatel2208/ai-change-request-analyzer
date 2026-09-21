import { useEffect, useState } from 'react'
import { listChangeRequests } from '../api/changeRequests'
import ChangeRequestDetail from '../components/ChangeRequestDetail'
import AnalysisDashboardPage from './AnalysisDashboardPage'
import EditChangeRequestPage from './EditChangeRequestPage'
import { useAuth } from '../context/AuthContext'
// Reuses the .badge / .table-card / .requests-table classes (dashboard.css)
// and the .cr-btn / breadcrumb classes (change-request-form.css, Module 4)
// rather than redefining them.
import '../styles/dashboard.css'
import '../styles/change-request-form.css'
import '../styles/change-requests-list.css'

const PAGE_SIZE = 25

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'pending_analysis', label: 'Pending Analysis' },
  { value: 'analyzing', label: 'Analyzing' },
  { value: 'requires_clarification', label: 'Requires Clarification' },
  { value: 'completed', label: 'Completed' },
  { value: 'approved', label: 'Approved' },
]

const PRIORITY_OPTIONS = [
  { value: '', label: 'All priorities' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
]

const STATUS_LABELS = {
  draft: 'Draft',
  pending_analysis: 'Pending Analysis',
  analyzing: 'Analyzing',
  requires_clarification: 'Requires Clarification',
  completed: 'Completed',
  approved: 'Approved',
}

const STATUS_CLASS = {
  draft: 'badge--gray',
  pending_analysis: 'badge--indigo',
  analyzing: 'badge--blue',
  requires_clarification: 'badge--amber',
  completed: 'badge--teal',
  approved: 'badge--green',
}

const PRIORITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }
const PRIORITY_CLASS = {
  low: 'badge--green',
  medium: 'badge--amber',
  high: 'badge--orange',
  critical: 'badge--red',
}

const RISK_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }
const RISK_CLASS = {
  low: 'badge--green',
  medium: 'badge--amber',
  high: 'badge--orange',
  critical: 'badge--red',
}

const COMPLEXITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', very_high: 'Very High' }

function formatDate(isoString) {
  try {
    return new Date(isoString).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return isoString
  }
}

const emptyFilters = { search: '', status: '', priority: '', assignedToMe: false, sort: 'newest' }

/** Module 5: the full Change Requests list - search, filter, sort,
 * pagination, and a master-detail panel (click a row to open it). Reads
 * only - no AI logic lives here. */
export default function ChangeRequestsPage({ onNavigate, jumpToId, onJumpHandled }) {
  const { token } = useAuth()
  const [filters, setFilters] = useState(emptyFilters)
  const [searchInput, setSearchInput] = useState('')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [dashboardId, setDashboardId] = useState(null)
  const [editId, setEditId] = useState(null)
  // Bumped every time we come back to this list from a change request's
  // detail/edit/dashboard view, so the list re-fetches instead of showing
  // whatever it last loaded (e.g. a status that changed while we were away
  // analyzing or editing that change request).
  const [refreshToken, setRefreshToken] = useState(0)

  // Debounce the free-text search box so we're not firing a request on
  // every keystroke - everything else applies immediately.
  useEffect(() => {
    const handle = setTimeout(() => {
      setFilters((prev) => ({ ...prev, search: searchInput.trim() }))
      setOffset(0)
    }, 350)
    return () => clearTimeout(handle)
  }, [searchInput])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    listChangeRequests(token, { ...filters, limit: PAGE_SIZE, offset })
      .then((response) => {
        if (!cancelled) setData(response)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load change requests.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [token, filters, offset, refreshToken])

  // A notification (or anything else outside this page) can ask to jump
  // straight to one change request's detail view - consume it once and
  // report back so the caller doesn't keep re-triggering it.
  useEffect(() => {
    if (jumpToId != null) {
      setDashboardId(null)
      setEditId(null)
      setSelectedId(jumpToId)
      onJumpHandled?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpToId])

  function updateFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setOffset(0)
  }

  function clearFilters() {
    setSearchInput('')
    setFilters(emptyFilters)
    setOffset(0)
  }

  const filtersActive = Boolean(filters.search || filters.status || filters.priority || filters.assignedToMe)

  if (dashboardId != null) {
    return (
      <AnalysisDashboardPage
        id={dashboardId}
        onBackToDetail={() => setDashboardId(null)}
        onBackToList={() => {
          setDashboardId(null)
          setSelectedId(null)
          setRefreshToken((k) => k + 1)
        }}
      />
    )
  }

  if (editId != null) {
    return (
      <EditChangeRequestPage
        id={editId}
        onCancel={() => setEditId(null)}
        onSaved={() => {
          setEditId(null)
          setRefreshToken((k) => k + 1)
        }}
      />
    )
  }

  if (selectedId != null) {
    return (
      <ChangeRequestDetail
        id={selectedId}
        onBack={() => {
          setSelectedId(null)
          setRefreshToken((k) => k + 1)
        }}
        onOpenDashboard={(id) => setDashboardId(id)}
        onEdit={(id) => setEditId(id)}
      />
    )
  }

  const total = data?.total ?? 0
  const items = data?.items ?? []
  const rangeStart = total === 0 ? 0 : offset + 1
  const rangeEnd = Math.min(offset + PAGE_SIZE, total)

  return (
    <div className="cr-list-shell">
      <div className="cr-list-heading">
        <div>
          <h1>Change Requests</h1>
          <p>Every change request tracked in the system.</p>
        </div>
        <button type="button" className="cr-btn cr-btn--primary" onClick={() => onNavigate('new-analysis')}>
          + New Change Request
        </button>
      </div>

      <div className="cr-toolbar">
        <input
          type="text"
          className="cr-search-input"
          placeholder="Search by ticket number, title, description, requester, or system…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <select
          className="cr-filter-select"
          value={filters.status}
          onChange={(e) => updateFilter('status', e.target.value)}
          aria-label="Filter by status"
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value || 'all'} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          className="cr-filter-select"
          value={filters.priority}
          onChange={(e) => updateFilter('priority', e.target.value)}
          aria-label="Filter by priority"
        >
          {PRIORITY_OPTIONS.map((option) => (
            <option key={option.value || 'all'} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          className="cr-filter-select"
          value={filters.sort}
          onChange={(e) => updateFilter('sort', e.target.value)}
          aria-label="Sort by date"
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
        </select>
        <label className="cr-toolbar-checkbox">
          <input
            type="checkbox"
            checked={filters.assignedToMe}
            onChange={(e) => updateFilter('assignedToMe', e.target.checked)}
          />
          Assigned to me
        </label>
      </div>

      {loading && <p className="cr-list-status-text">Loading change requests…</p>}
      {error && <p className="cr-list-status-text cr-list-status-text--error">{error}</p>}

      {!loading && !error && total === 0 && (
        <div className="cr-list-empty">
          {filtersActive ? (
            <>
              <p className="cr-list-empty-title">No change requests match your filters.</p>
              <button type="button" className="cr-btn cr-btn--secondary" onClick={clearFilters}>
                Clear filters
              </button>
            </>
          ) : (
            <>
              <p className="cr-list-empty-title">No change requests yet.</p>
              <button
                type="button"
                className="cr-btn cr-btn--primary"
                onClick={() => onNavigate('new-analysis')}
              >
                + New Change Request
              </button>
            </>
          )}
        </div>
      )}

      {!loading && !error && total > 0 && (
        <>
          <div className="table-card cr-table-card">
            <div className="table-scroll">
              <table className="requests-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Title</th>
                    <th>Category</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Risk</th>
                    <th>Complexity</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="cr-list-row" onClick={() => setSelectedId(item.id)}>
                      <td className="requests-table-id">#{item.id}</td>
                      <td className="requests-table-title">{item.title}</td>
                      <td>{item.category || <span className="table-muted">Not analyzed</span>}</td>
                      <td>
                        <span className={`badge ${PRIORITY_CLASS[item.priority] || 'badge--gray'}`}>
                          {PRIORITY_LABELS[item.priority] || item.priority}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${STATUS_CLASS[item.effective_status] || 'badge--gray'}`}>
                          {STATUS_LABELS[item.effective_status] || item.effective_status}
                        </span>
                      </td>
                      <td>
                        {item.risk ? (
                          <span className={`badge ${RISK_CLASS[item.risk] || 'badge--gray'}`}>
                            {RISK_LABELS[item.risk] || item.risk}
                          </span>
                        ) : (
                          <span className="table-muted">—</span>
                        )}
                      </td>
                      <td className="table-muted">
                        {item.complexity ? COMPLEXITY_LABELS[item.complexity] || item.complexity : '—'}
                      </td>
                      <td className="table-muted">{formatDate(item.created_at)}</td>
                      <td>
                        <button type="button" className="cr-open-link">
                          Open →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="cr-pagination">
            <span className="cr-pagination-summary">
              Showing {rangeStart}–{rangeEnd} of {total}
            </span>
            <div className="cr-pagination-buttons">
              <button
                type="button"
                className="cr-btn cr-btn--secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </button>
              <button
                type="button"
                className="cr-btn cr-btn--secondary"
                disabled={rangeEnd >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
