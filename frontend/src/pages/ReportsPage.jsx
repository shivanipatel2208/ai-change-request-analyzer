import { useEffect, useState } from 'react'
import { downloadReportById, getReportStats, listReports } from '../api/reports'
import { listUsers } from '../api/users'
import { useAuth } from '../context/AuthContext'
import MetricCard from '../components/MetricCard'
import ReportDetailPage from './ReportDetailPage'
import '../styles/dashboard.css'
import '../styles/change-request-form.css'
import '../styles/change-requests-list.css'
import '../styles/workflow.css'
import '../styles/my-work.css'

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'submitted', label: 'Submitted' },
  { value: 'pending_analysis', label: 'Pending Analysis' },
  { value: 'analyzed', label: 'Analyzed' },
  { value: 'in_review', label: 'Under Review' },
  { value: 'changes_requested', label: 'Changes Requested' },
  { value: 'approval_required', label: 'Approval Required' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'implementation_planned', label: 'Implementation Planned' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'implemented', label: 'Implemented' },
  { value: 'validated', label: 'Validated' },
  { value: 'closed', label: 'Closed' },
  { value: 'cancelled', label: 'Cancelled' },
]

const RISK_OPTIONS = [
  { value: '', label: 'All risk levels' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
]

const RISK_CLASS = { low: 'badge--green', medium: 'badge--amber', high: 'badge--orange', critical: 'badge--red' }

// Mirrors app/services/workflow_rules.py::STATUS_LABELS' own status set -
// kept in sync manually, same convention as every other label/class map
// already in this codebase (e.g. components/ChangeRequestDetail.jsx's own
// STATUS_CLASS).
const STATUS_CLASS = {
  draft: 'badge--gray',
  submitted: 'badge--indigo',
  pending_analysis: 'badge--indigo',
  analyzed: 'badge--blue',
  in_review: 'badge--indigo',
  changes_requested: 'badge--amber',
  approval_required: 'badge--amber',
  approved: 'badge--green',
  rejected: 'badge--red',
  implementation_planned: 'badge--teal',
  in_progress: 'badge--teal',
  implemented: 'badge--teal',
  validated: 'badge--green',
  closed: 'badge--gray',
  cancelled: 'badge--gray',
}

function formatDateTime(isoString) {
  if (!isoString) return '—'
  try {
    return new Date(isoString).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return isoString
  }
}

const emptyFilters = { search: '', status: '', risk: '', version: '', generatedBy: '', dateFrom: '', dateTo: '' }

/** Module 24: the Reports section - statistics, search/filter, and the
 * report list, all reading from GET /api/reports* (see backend/app/
 * services/report_registry.py - reports are a computed view over the
 * existing audit trail, not their own table).
 *
 * There is deliberately no "Generate Report" action anywhere on this page:
 * a report is never a separate, manual step - the moment an analysis
 * completes for a change request (Analyze or Re-analyze, on the Analysis
 * Dashboard), it automatically shows up here (confirmed with the project
 * owner). "View" opens the report's PDF via ReportDetailPage's metadata
 * card + embedded PDF; "Download" saves it. */
export default function ReportsPage({ onOpenChangeRequest, onNavigate }) {
  const { token } = useAuth()

  const [filters, setFilters] = useState(emptyFilters)
  const [searchInput, setSearchInput] = useState('')
  const [stats, setStats] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const [users, setUsers] = useState([])
  const [selectedReportId, setSelectedReportId] = useState(null)

  const [rowBusyId, setRowBusyId] = useState(null)
  const [rowError, setRowError] = useState(null)

  useEffect(() => {
    if (!token) return
    listUsers(token)
      .then(setUsers)
      .catch(() => {})
  }, [token])

  useEffect(() => {
    const handle = setTimeout(() => {
      setFilters((prev) => ({ ...prev, search: searchInput.trim() }))
    }, 350)
    return () => clearTimeout(handle)
  }, [searchInput])

  useEffect(() => {
    if (!token) return
    getReportStats(token)
      .then(setStats)
      .catch(() => {})
  }, [token, refreshToken])

  useEffect(() => {
    if (!token) return
    let cancelled = false
    setLoading(true)
    setError(null)
    listReports(token, filters)
      .then((response) => {
        if (!cancelled) setData(response)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load reports.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [token, filters, refreshToken])

  function updateFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }

  function clearFilters() {
    setSearchInput('')
    setFilters(emptyFilters)
  }

  const filtersActive = Boolean(
    filters.search || filters.status || filters.risk || filters.version || filters.generatedBy || filters.dateFrom || filters.dateTo
  )

  async function handleDownload(row) {
    setRowBusyId(row.report_id)
    setRowError(null)
    try {
      await downloadReportById(
        row.report_id,
        token,
        `${row.change_request_code}-v${row.version}-report.pdf`
      )
    } catch (err) {
      setRowError(err.message || 'Could not download this report.')
    } finally {
      setRowBusyId(null)
    }
  }

  if (selectedReportId != null) {
    return (
      <ReportDetailPage
        reportId={selectedReportId}
        onBack={() => {
          setSelectedReportId(null)
          setRefreshToken((k) => k + 1)
        }}
        onOpenChangeRequest={onOpenChangeRequest}
      />
    )
  }

  const total = data?.total ?? 0
  const items = data?.items ?? []

  return (
    <div className="cr-list-shell">
      <div className="cr-list-heading">
        <div>
          <h1>Reports</h1>
          <p>Every report generated from a Change Request analysis, in one place.</p>
        </div>
      </div>

      {stats && (
        <div className="metric-grid">
          <MetricCard label="Total Reports" value={stats.total_reports} />
          <MetricCard label="CRs With Reports" value={stats.change_requests_with_reports} />
          <MetricCard label="Generated Last 7 Days" value={stats.recent_reports} />
          <MetricCard
            label="Outdated (Newer CR Version Exists)"
            value={stats.outdated_reports}
            tone={stats.outdated_reports > 0 ? 'danger' : 'default'}
          />
        </div>
      )}

      <div className="cr-toolbar">
        <input
          type="text"
          className="cr-search-input"
          placeholder="Search by CR id, CR code, or title…"
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
          value={filters.risk}
          onChange={(e) => updateFilter('risk', e.target.value)}
          aria-label="Filter by risk"
        >
          {RISK_OPTIONS.map((option) => (
            <option key={option.value || 'all'} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <input
          type="number"
          min="1"
          className="cr-filter-select"
          style={{ width: '7rem' }}
          placeholder="Version"
          value={filters.version}
          onChange={(e) => updateFilter('version', e.target.value)}
          aria-label="Filter by version"
        />
        <select
          className="cr-filter-select"
          value={filters.generatedBy}
          onChange={(e) => updateFilter('generatedBy', e.target.value)}
          aria-label="Filter by who generated it"
        >
          <option value="">Anyone</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </select>
        <input
          type="date"
          className="cr-filter-select"
          value={filters.dateFrom}
          onChange={(e) => updateFilter('dateFrom', e.target.value)}
          aria-label="From date"
        />
        <input
          type="date"
          className="cr-filter-select"
          value={filters.dateTo}
          onChange={(e) => updateFilter('dateTo', e.target.value)}
          aria-label="To date"
        />
      </div>

      {rowError && <p className="cr-list-status-text cr-list-status-text--error">{rowError}</p>}
      {loading && <p className="cr-list-status-text">Loading reports…</p>}
      {error && <p className="cr-list-status-text cr-list-status-text--error">Unable to load reports. {error}</p>}

      {!loading && !error && total === 0 && (
        <div className="cr-list-empty">
          {filtersActive ? (
            <>
              <p className="cr-list-empty-title">No reports match your filters.</p>
              <button type="button" className="cr-btn cr-btn--secondary" onClick={clearFilters}>
                Clear filters
              </button>
            </>
          ) : (
            <>
              <p className="cr-list-empty-title">No reports yet</p>
              <p className="cr-detail-text">
                Reports appear here automatically once a Change Request has been analyzed - there's nothing
                separate to generate.
              </p>
              <button type="button" className="cr-btn cr-btn--primary" onClick={() => onNavigate?.('change-requests')}>
                View Change Requests
              </button>
            </>
          )}
        </div>
      )}

      {!loading && !error && total > 0 && (
        <div className="table-card cr-table-card">
          <div className="table-scroll">
            <table className="requests-table">
              <thead>
                <tr>
                  <th>Report</th>
                  <th>CR ID</th>
                  <th>CR Title</th>
                  <th>Version</th>
                  <th>Risk</th>
                  <th>Status</th>
                  <th>Generated By</th>
                  <th>Generated At</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.report_id} className="cr-list-row">
                    <td className="requests-table-title">
                      {row.change_request_code} · v{row.version}
                      {row.is_historical_pull && <span className="badge badge--indigo" style={{ marginLeft: '0.4rem' }}>Historical</span>}
                      {!row.is_current_version && (
                        <span className="badge badge--amber" style={{ marginLeft: '0.4rem' }} title="A newer version of this change request now exists.">
                          Outdated
                        </span>
                      )}
                    </td>
                    <td className="table-muted">#{row.change_request_id}</td>
                    <td>{row.change_request_title}</td>
                    <td className="table-muted">v{row.version}</td>
                    <td>
                      {row.risk_bucket ? (
                        <span className={`badge ${RISK_CLASS[row.risk_bucket.toLowerCase()] || 'badge--gray'}`}>
                          {row.risk_bucket}
                        </span>
                      ) : (
                        <span className="table-muted">Not analyzed</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${STATUS_CLASS[row.cr_status] || 'badge--gray'}`}>{row.cr_status_label}</span>
                    </td>
                    <td>{row.generated_by_name}</td>
                    <td className="table-muted">{formatDateTime(row.generated_at)}</td>
                    <td>
                      <div className="approval-actions-cell">
                        <button
                          type="button"
                          className="cr-btn cr-btn--ghost cr-btn--small"
                          onClick={() => setSelectedReportId(row.report_id)}
                        >
                          View
                        </button>
                        <button
                          type="button"
                          className="cr-btn cr-btn--secondary cr-btn--small"
                          disabled={rowBusyId === row.report_id}
                          onClick={() => handleDownload(row)}
                        >
                          {rowBusyId === row.report_id ? 'Working…' : 'Download'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
