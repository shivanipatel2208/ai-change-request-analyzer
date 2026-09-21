import { useEffect, useState } from 'react'
import { getDashboardDrillDown, getDashboardSummary } from '../api/dashboard'
import DistributionChart from '../components/DistributionChart'
import EmptyState from '../components/EmptyState'
import MetricCard from '../components/MetricCard'
import Modal from '../components/Modal'
import RecentRequestsTable from '../components/RecentRequestsTable'
import { useAuth } from '../context/AuthContext'
import '../styles/dashboard.css'
import '../styles/change-requests-list.css'
import '../styles/change-request-form.css'

const RISK_ORDER = [
  { key: 'low', label: 'Low', color: '#12b76a' },
  { key: 'medium', label: 'Medium', color: '#f79009' },
  { key: 'high', label: 'High', color: '#f04438' },
  { key: 'critical', label: 'Critical', color: '#b42318' },
  { key: 'not_analyzed', label: 'Not analyzed', color: '#98a2b3' },
]

const CATEGORY_ORDER = ['Feature', 'Bug Fix', 'Security', 'Database', 'API', 'Infrastructure', 'Integration', 'Other']

// The 5 clickable tiles: each maps to a `metric` value the backend's
// /dashboard/drill-down endpoint understands (see backend/app/api/
// dashboard.py) and the heading its table should show once clicked.
const DRILLDOWN_TITLES = {
  total: 'All Change Requests',
  pending_analysis: 'Pending Analysis',
  high_risk: 'High Risk Changes',
  approved: 'Approved Changes',
  requires_clarification: 'Requires Clarification',
}

// The popup's rows-per-page dropdown - capped at 10 to match the backend's
// own page_size ceiling (spec: "page dropdown till 10").
const PAGE_SIZE_OPTIONS = [5, 10]

export default function DashboardPage({ onNavigate, onOpenChangeRequest }) {
  const { token } = useAuth()
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  // Module: clickable dashboard tiles. Selecting a tile a second time
  // closes its table again - `selectedMetric` is the single source of
  // truth for both "which tile is highlighted" and "which table shows."
  const [selectedMetric, setSelectedMetric] = useState(null)
  const [drillDown, setDrillDown] = useState(null)
  const [drillDownLoading, setDrillDownLoading] = useState(false)
  const [drillDownError, setDrillDownError] = useState(null)

  // The popup's own filter/pagination controls (spec: "give option of the
  // filter to select the date range, page dropdown till 10"). All reset
  // together whenever the popup closes, so reopening a different tile never
  // carries over a stale date range or page number.
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    getDashboardSummary(token)
      .then((data) => {
        if (!cancelled) setSummary(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load the dashboard.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [token])

  useEffect(() => {
    if (!selectedMetric) {
      setDrillDown(null)
      setDrillDownError(null)
      return undefined
    }
    let cancelled = false
    setDrillDownLoading(true)
    setDrillDownError(null)
    getDashboardDrillDown(selectedMetric, token, { dateFrom, dateTo, page, pageSize })
      .then((data) => {
        if (!cancelled) setDrillDown(data)
      })
      .catch((err) => {
        if (!cancelled) setDrillDownError(err.message || 'Could not load that list.')
      })
      .finally(() => {
        if (!cancelled) setDrillDownLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedMetric, token, dateFrom, dateTo, page, pageSize])

  // Changing the tile, the date range, or rows-per-page always jumps back
  // to page 1 - otherwise "page 3" from a longer list could land out of
  // range for a shorter, newly-filtered one.
  useEffect(() => {
    setPage(1)
  }, [selectedMetric, dateFrom, dateTo, pageSize])

  function toggleTile(metric) {
    if (selectedMetric === metric) {
      closeDrillDown()
    } else {
      setSelectedMetric(metric)
    }
  }

  function closeDrillDown() {
    setSelectedMetric(null)
    setDateFrom('')
    setDateTo('')
    setPage(1)
    setPageSize(10)
  }

  if (loading) {
    return (
      <div className="dashboard-shell">
        <p className="dashboard-status-text">Loading dashboard…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="dashboard-shell">
        <p className="dashboard-status-text dashboard-status-text--error">{error}</p>
      </div>
    )
  }

  const { metrics, risk_distribution: riskDistribution, category_breakdown: categoryBreakdown, recent_change_requests: recent } =
    summary

  if (metrics.total_change_requests === 0) {
    return (
      <div className="dashboard-shell">
        <EmptyState onCreateClick={() => onNavigate('new-analysis')} />
      </div>
    )
  }

  const riskData = RISK_ORDER.map((row) => ({
    label: row.label,
    count: riskDistribution[row.key] || 0,
    color: row.color,
  }))

  const categoryData = CATEGORY_ORDER.map((label) => ({
    label,
    count: categoryBreakdown[label] || 0,
  }))

  // Pagination summary for the popup's footer - "Showing 1-10 of 23" plus
  // whether there's another page to move to. Guarded against `drillDown`
  // being null (still loading, or errored) with sensible zero defaults.
  const drillDownTotal = drillDown ? drillDown.total : 0
  const rangeStart = drillDownTotal === 0 ? 0 : (page - 1) * pageSize + 1
  const rangeEnd = drillDown ? rangeStart + drillDown.items.length - 1 : 0
  const hasNextPage = drillDown ? rangeEnd < drillDownTotal : false

  return (
    <div className="dashboard-shell">
      <div className="dashboard-heading">
        <h1>Dashboard</h1>
        <p>An overview of every change request tracked in the system.</p>
      </div>

      <div className="metric-grid">
        <MetricCard
          label="Total Change Requests"
          value={metrics.total_change_requests}
          onClick={() => toggleTile('total')}
          active={selectedMetric === 'total'}
        />
        <MetricCard
          label="Pending Analysis"
          value={metrics.pending_analysis}
          tone="neutral"
          onClick={() => toggleTile('pending_analysis')}
          active={selectedMetric === 'pending_analysis'}
        />
        <MetricCard
          label="High Risk Changes"
          value={metrics.high_risk_changes}
          tone="danger"
          onClick={() => toggleTile('high_risk')}
          active={selectedMetric === 'high_risk'}
        />
        <MetricCard
          label="Approved Changes"
          value={metrics.approved_changes}
          tone="success"
          onClick={() => toggleTile('approved')}
          active={selectedMetric === 'approved'}
        />
        <MetricCard
          label="Requires Clarification"
          value={metrics.requires_clarification}
          tone="warning"
          onClick={() => toggleTile('requires_clarification')}
          active={selectedMetric === 'requires_clarification'}
        />
      </div>

      {selectedMetric && (
        <Modal
          title={`${DRILLDOWN_TITLES[selectedMetric]}${drillDown ? ` (${drillDown.total})` : ''}`}
          onClose={closeDrillDown}
          actions={
            <>
              <span className="drilldown-pagination-info">
                {drillDown ? `Showing ${rangeStart}–${rangeEnd} of ${drillDownTotal}` : ' '}
              </span>
              <div className="drilldown-pagination-controls">
                <button
                  type="button"
                  className="cr-btn cr-btn--ghost cr-btn--small"
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  disabled={page <= 1}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="cr-btn cr-btn--ghost cr-btn--small"
                  onClick={() => setPage((current) => current + 1)}
                  disabled={!hasNextPage}
                >
                  Next
                </button>
                <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={closeDrillDown}>
                  Close
                </button>
              </div>
            </>
          }
        >
          <div className="drilldown-filters">
            <label className="drilldown-filter-field">
              <span>From</span>
              <input
                type="date"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </label>
            <label className="drilldown-filter-field">
              <span>To</span>
              <input
                type="date"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={(event) => setDateTo(event.target.value)}
              />
            </label>
            <label className="drilldown-filter-field">
              <span>Rows per page</span>
              <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
            </label>
            {(dateFrom || dateTo) && (
              <button
                type="button"
                className="cr-btn cr-btn--ghost cr-btn--small"
                onClick={() => {
                  setDateFrom('')
                  setDateTo('')
                }}
              >
                Clear dates
              </button>
            )}
          </div>

          {drillDownLoading && <p className="dashboard-status-text">Loading…</p>}
          {drillDownError && <p className="dashboard-status-text dashboard-status-text--error">{drillDownError}</p>}
          {!drillDownLoading && !drillDownError && drillDown && (
            <RecentRequestsTable
              items={drillDown.items}
              emptyMessage="No change requests match this filter."
              onRowClick={onOpenChangeRequest}
              bare
            />
          )}
        </Modal>
      )}

      <div className="chart-grid">
        <DistributionChart
          title="Risk Overview"
          data={riskData}
          emptyLabel="No analyzed change requests yet."
        />
        <DistributionChart
          title="Change Category Overview"
          data={categoryData}
          emptyLabel="No categorized change requests yet."
        />
      </div>

      <RecentRequestsTable items={recent} />
    </div>
  )
}
