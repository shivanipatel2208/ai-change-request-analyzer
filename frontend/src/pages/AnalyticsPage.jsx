import { useEffect, useMemo, useState } from 'react'
import {
  getAIAnalytics,
  getApprovalBottlenecks,
  getChangeAnalytics,
  getExecutiveAndWorkflowMetrics,
  getRiskAnalytics,
  getWorkloadAnalytics,
} from '../api/analytics'
import { listUsers } from '../api/users'
import DistributionChart from '../components/DistributionChart'
import MetricCard from '../components/MetricCard'
import RiskTrendChart from '../components/RiskTrendChart'
import { useAuth } from '../context/AuthContext'
import '../styles/dashboard.css'
import '../styles/analytics.css'

/** Module 19 (Engineering Change Analytics), Phase 6: the frontend for all
 * 5 backend endpoints Phases 2-5 built (executive+workflow, risk, approval
 * bottlenecks, change analytics, workload, AI). Every section here reads
 * ONLY what those endpoints return - no client-side math invents a number
 * the backend didn't already compute, per the spec's own "every metric
 * should be traceable to real database records" rule.
 *
 * One shared filter bar (spec section 8) drives all 6 API calls together -
 * changing a filter re-fetches every section at once, so every card on the
 * page always describes the exact same slice of the data. No charting
 * library is used anywhere on this page (see DistributionChart.jsx's own
 * docstring and this page's new RiskTrendChart) - proportional CSS bars
 * only, matching this project's existing dashboard.
 */

const STATUS_OPTIONS = [
  { value: '', label: 'Any status' },
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

const PRIORITY_OPTIONS = [
  { value: '', label: 'Any priority' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
]

const RISK_OPTIONS = [
  { value: '', label: 'Any risk' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
]

const CATEGORY_OPTIONS = [
  { value: '', label: 'Any category' },
  { value: 'Feature', label: 'Feature' },
  { value: 'Bug Fix', label: 'Bug Fix' },
  { value: 'Security', label: 'Security' },
  { value: 'Database', label: 'Database' },
  { value: 'API', label: 'API' },
  { value: 'Infrastructure', label: 'Infrastructure' },
  { value: 'Integration', label: 'Integration' },
  { value: 'Other', label: 'Other' },
]

const RISK_ROW_ORDER = [
  { key: 'low', label: 'Low', color: '#12b76a' },
  { key: 'medium', label: 'Medium', color: '#f79009' },
  { key: 'high', label: 'High', color: '#f04438' },
  { key: 'critical', label: 'Critical', color: '#b42318' },
  { key: 'not_analyzed', label: 'Not analyzed', color: '#98a2b3' },
]

const DEFAULT_FILTERS = {
  dateFrom: '',
  dateTo: '',
  status: '',
  priority: '',
  risk: '',
  category: '',
  ownerId: '',
}

function formatHours(value) {
  if (value === null || value === undefined) return 'No data yet'
  if (value < 1) return `${Math.round(value * 60)}m`
  return `${value.toFixed(1)}h`
}

function formatPercent(value) {
  if (value === null || value === undefined) return '—'
  return `${Math.round(value * 100)}%`
}

function formatConfidence(value) {
  if (value === null || value === undefined) return '—'
  return `${Math.round(value)}%`
}

function formatCount(value) {
  return value === null || value === undefined ? '—' : value
}

export default function AnalyticsPage() {
  const { token } = useAuth()
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [users, setUsers] = useState([])
  const [executive, setExecutive] = useState(null)
  const [risk, setRisk] = useState(null)
  const [bottlenecks, setBottlenecks] = useState(null)
  const [changeAnalytics, setChangeAnalytics] = useState(null)
  const [workload, setWorkload] = useState(null)
  const [aiAnalytics, setAiAnalytics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    listUsers(token)
      .then((rows) => setUsers(rows || []))
      .catch(() => setUsers([]))
  }, [token])

  const queryFilters = useMemo(
    () => ({
      // date_to is inclusive of the whole day the user picked - anchoring
      // it to end-of-day (not midnight) avoids silently excluding change
      // requests created later that same day.
      dateFrom: filters.dateFrom ? new Date(`${filters.dateFrom}T00:00:00`).toISOString() : '',
      dateTo: filters.dateTo ? new Date(`${filters.dateTo}T23:59:59.999`).toISOString() : '',
      status: filters.status,
      priority: filters.priority,
      risk: filters.risk,
      category: filters.category,
      ownerId: filters.ownerId,
    }),
    [filters]
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([
      getExecutiveAndWorkflowMetrics(token, queryFilters),
      getRiskAnalytics(token, queryFilters),
      getApprovalBottlenecks(token, queryFilters),
      getChangeAnalytics(token, queryFilters),
      getWorkloadAnalytics(token, queryFilters),
      getAIAnalytics(token, queryFilters),
    ])
      .then(([execData, riskData, bottleneckData, changeData, workloadData, aiData]) => {
        if (cancelled) return
        setExecutive(execData)
        setRisk(riskData)
        setBottlenecks(bottleneckData)
        setChangeAnalytics(changeData)
        setWorkload(workloadData)
        setAiAnalytics(aiData)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load analytics.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [token, queryFilters])

  function updateFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }

  function clearFilters() {
    setFilters(DEFAULT_FILTERS)
  }

  const hasActiveFilters = Object.values(filters).some((value) => value !== '')

  const riskData = risk
    ? RISK_ROW_ORDER.map((row) => ({
        label: row.label,
        count: risk.current_distribution[row.key] || 0,
        color: row.color,
      }))
    : []

  return (
    <div className="dashboard-shell analytics-shell">
      <div className="dashboard-heading">
        <h1>Engineering Change Analytics</h1>
        <p>Real-time metrics computed directly from the database - nothing here is estimated or invented.</p>
      </div>

      <div className="analytics-filter-bar">
        <div className="analytics-filter">
          <label htmlFor="analytics-date-from">From</label>
          <input
            id="analytics-date-from"
            type="date"
            value={filters.dateFrom}
            onChange={(e) => updateFilter('dateFrom', e.target.value)}
          />
        </div>
        <div className="analytics-filter">
          <label htmlFor="analytics-date-to">To</label>
          <input
            id="analytics-date-to"
            type="date"
            value={filters.dateTo}
            onChange={(e) => updateFilter('dateTo', e.target.value)}
          />
        </div>
        <div className="analytics-filter">
          <label htmlFor="analytics-status">Status</label>
          <select id="analytics-status" value={filters.status} onChange={(e) => updateFilter('status', e.target.value)}>
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div className="analytics-filter">
          <label htmlFor="analytics-priority">Priority</label>
          <select
            id="analytics-priority"
            value={filters.priority}
            onChange={(e) => updateFilter('priority', e.target.value)}
          >
            {PRIORITY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div className="analytics-filter">
          <label htmlFor="analytics-risk">Risk</label>
          <select id="analytics-risk" value={filters.risk} onChange={(e) => updateFilter('risk', e.target.value)}>
            {RISK_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div className="analytics-filter">
          <label htmlFor="analytics-category">Category</label>
          <select
            id="analytics-category"
            value={filters.category}
            onChange={(e) => updateFilter('category', e.target.value)}
          >
            {CATEGORY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div className="analytics-filter">
          <label htmlFor="analytics-owner">Owner</label>
          <select id="analytics-owner" value={filters.ownerId} onChange={(e) => updateFilter('ownerId', e.target.value)}>
            <option value="">Any owner</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </div>
        {hasActiveFilters && (
          <button type="button" className="analytics-clear-filters" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="dashboard-status-text dashboard-status-text--error">{error}</p>}
      {loading && !executive && <p className="dashboard-status-text">Loading analytics…</p>}

      {executive && (
        <>
          <h2 className="analytics-section-title">Executive Metrics</h2>
          <div className="metric-grid analytics-metric-grid-7">
            <MetricCard label="Total CRs" value={executive.executive.total} />
            <MetricCard label="Open" value={executive.executive.open} tone="neutral" />
            <MetricCard label="Pending Approval" value={executive.executive.pending_approval} tone="warning" />
            <MetricCard label="Approved" value={executive.executive.approved} tone="success" />
            <MetricCard label="Rejected" value={executive.executive.rejected} tone="danger" />
            <MetricCard label="In Progress" value={executive.executive.in_progress} tone="neutral" />
            <MetricCard label="Closed" value={executive.executive.closed} tone="success" />
          </div>

          <h2 className="analytics-section-title">Workflow Metrics</h2>
          <div className="metric-grid analytics-metric-grid-6">
            <MetricCard label="Avg. Time to Analysis" value={formatHours(executive.workflow.avg_time_to_analysis_hours)} />
            <MetricCard label="Avg. Approval Time" value={formatHours(executive.workflow.avg_approval_time_hours)} />
            <MetricCard
              label="Avg. Time to Implementation"
              value={formatHours(executive.workflow.avg_time_to_implementation_hours)}
            />
            <MetricCard label="Avg. Time to Closure" value={formatHours(executive.workflow.avg_time_to_closure_hours)} />
            <MetricCard label="Waiting for Approval" value={executive.workflow.crs_waiting_for_approval} tone="warning" />
            <MetricCard label="Changes Requested" value={executive.workflow.crs_with_requested_changes} tone="warning" />
          </div>
        </>
      )}

      {risk && (
        <>
          <h2 className="analytics-section-title">Risk Analytics</h2>
          <div className="chart-grid">
            <DistributionChart title="Current Risk Distribution" data={riskData} emptyLabel="No change requests yet." />
            <RiskTrendChart data={risk.over_time} emptyLabel="No analyzed change requests yet." />
          </div>
        </>
      )}

      {bottlenecks && (
        <>
          <h2 className="analytics-section-title">Approval Bottlenecks</h2>
          <div className="chart-grid">
            <div className="chart-card">
              <h2 className="chart-card-title">Pending Approvals by Type</h2>
              {Object.keys(bottlenecks.pending_by_type).length === 0 ? (
                <p className="chart-empty">No pending approvals.</p>
              ) : (
                <ul className="analytics-simple-list">
                  {Object.entries(bottlenecks.pending_by_type).map(([label, count]) => (
                    <li key={label}>
                      <span>{label}</span>
                      <span>{count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="chart-card">
              <h2 className="chart-card-title">Pending Approvals by Person</h2>
              {bottlenecks.pending_by_person.length === 0 ? (
                <p className="chart-empty">No pending approvals.</p>
              ) : (
                <ul className="analytics-simple-list">
                  {bottlenecks.pending_by_person.map((entry) => (
                    <li key={entry.approver_name}>
                      <span>{entry.approver_name}</span>
                      <span>{entry.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="chart-card">
              <h2 className="chart-card-title">Avg. Approval Duration by Type</h2>
              {Object.keys(bottlenecks.avg_duration_hours_by_type).length === 0 ? (
                <p className="chart-empty">No resolved approvals yet.</p>
              ) : (
                <ul className="analytics-simple-list">
                  {Object.entries(bottlenecks.avg_duration_hours_by_type).map(([label, hours]) => (
                    <li key={label}>
                      <span>{label}</span>
                      <span>{formatHours(hours)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="chart-card">
              <h2 className="chart-card-title">Most Common Approval Blockers</h2>
              {bottlenecks.most_common_blockers.length === 0 ? (
                <p className="chart-empty">No rejections or changes-requested responses yet.</p>
              ) : (
                <ul className="analytics-simple-list">
                  {bottlenecks.most_common_blockers.map((entry) => (
                    <li key={entry.approval_type_label}>
                      <span>{entry.approval_type_label}</span>
                      <span>{entry.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}

      {changeAnalytics && (
        <>
          <h2 className="analytics-section-title">Change Analytics</h2>
          <div className="metric-grid analytics-metric-grid-3">
            <MetricCard label="CRs with Multiple Revisions" value={changeAnalytics.crs_with_multiple_revisions} />
            <MetricCard
              label="Avg. Versions per CR"
              value={changeAnalytics.avg_versions_per_cr === null ? '—' : changeAnalytics.avg_versions_per_cr.toFixed(1)}
            />
            <MetricCard
              label="Returned for Clarification"
              value={changeAnalytics.crs_returned_for_clarification}
              tone="warning"
            />
          </div>
          <div className="chart-grid">
            <div className="chart-card">
              <h2 className="chart-card-title">Most Frequently Changed Fields</h2>
              {changeAnalytics.most_changed_fields.length === 0 ? (
                <p className="chart-empty">No field edits recorded yet.</p>
              ) : (
                <ul className="analytics-simple-list">
                  {changeAnalytics.most_changed_fields.map((entry) => (
                    <li key={entry.field_label}>
                      <span>{entry.field_label}</span>
                      <span>{entry.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}

      {workload && (
        <>
          <h2 className="analytics-section-title">Workload</h2>
          <div className="metric-grid analytics-metric-grid-3">
            <MetricCard label="Pending Reviews" value={workload.pending_reviews} />
            <MetricCard label="Pending Approvals" value={workload.pending_approvals} tone="warning" />
            <MetricCard label="Overdue Tasks" value={workload.overdue_tasks} tone="danger" />
          </div>
          <div className="chart-grid">
            <div className="chart-card">
              <h2 className="chart-card-title">Change Requests per Owner</h2>
              <p className="analytics-note">Excludes this app's own bulk load-test data.</p>
              {workload.crs_per_owner.length === 0 ? (
                <p className="chart-empty">No change requests match these filters.</p>
              ) : (
                <ul className="analytics-simple-list">
                  {workload.crs_per_owner.map((entry) => (
                    <li key={entry.owner_name}>
                      <span>{entry.owner_name}</span>
                      <span>{entry.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}

      {aiAnalytics && (
        <>
          <h2 className="analytics-section-title">AI Recommendation Statistics</h2>
          <p className="analytics-note">
            These describe what the AI recommended and did, not whether it was right - this app doesn't record
            ground-truth outcomes, so no "accuracy" figure is shown here.
          </p>
          <div className="metric-grid analytics-metric-grid-6">
            <MetricCard label="Number of Analyses" value={formatCount(aiAnalytics.total_analyses)} />
            <MetricCard label="Re-analysis Rate" value={formatPercent(aiAnalytics.re_analysis_rate)} />
            <MetricCard label="Avg. Confidence" value={formatConfidence(aiAnalytics.average_confidence)} />
            <MetricCard label="Risk Changes After Edits" value={formatCount(aiAnalytics.risk_changes_after_edits)} />
            <MetricCard label="AI-Recommended Approvals" value={formatCount(aiAnalytics.ai_recommended_approvals)} />
            <MetricCard label="AI Analysis Failures" value={formatCount(aiAnalytics.ai_analysis_failures)} tone="danger" />
          </div>
        </>
      )}
    </div>
  )
}
