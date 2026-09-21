import { useEffect, useState } from 'react'
import {
  getChangesRequestedFromMe,
  getMyApprovals,
  getMyAssignments,
  getMyChangeRequests,
  getMyMentions,
  getMyReviews,
  getMyWorkSummary,
  getOverdueItems,
} from '../api/myWork'
import { respondToApproval } from '../api/approvals'
import { useAuth } from '../context/AuthContext'
import MetricCard from '../components/MetricCard'
import '../styles/dashboard.css'
import '../styles/change-requests-list.css'
import '../styles/analysis-dashboard.css'
import '../styles/workflow.css'
import '../styles/my-work.css'

// Mirrors ChangeRequestsPage.jsx's own label/class maps (module-local by
// the same convention, rather than a shared import - see that file).
const STATUS_LABELS = {
  draft: 'Draft',
  pending_analysis: 'Pending Analysis',
  requires_clarification: 'Requires Clarification',
  completed: 'Completed',
  approved: 'Approved',
}
const STATUS_CLASS = {
  draft: 'badge--gray',
  pending_analysis: 'badge--indigo',
  requires_clarification: 'badge--amber',
  completed: 'badge--teal',
  approved: 'badge--green',
}
const PRIORITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }
const PRIORITY_CLASS = { low: 'badge--green', medium: 'badge--amber', high: 'badge--orange', critical: 'badge--red' }
const RISK_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }
const RISK_CLASS = { low: 'badge--green', medium: 'badge--amber', high: 'badge--orange', critical: 'badge--red' }

// Module 18 Phase 1's own two due_status values.
const DUE_LABELS = { overdue: 'Overdue', due_soon: 'Due soon' }
const DUE_CLASS = { overdue: 'badge--red', due_soon: 'badge--amber' }

const ROLE_LABELS = {
  requester: 'Requester',
  owner: 'Owner',
  technical_lead: 'Technical Lead',
  reviewer: 'Reviewer',
  approver: 'Approver',
  security_reviewer: 'Security Reviewer',
  qa_owner: 'QA Owner',
  implementation_owner: 'Implementation Owner',
}

const TABS = [
  { key: 'change-requests', label: 'My Change Requests', summaryKey: 'my_change_requests' },
  { key: 'approvals', label: 'My Approvals', summaryKey: 'my_approvals_pending' },
  { key: 'reviews', label: 'My Reviews', summaryKey: 'my_reviews' },
  { key: 'assignments', label: 'My Assignments', summaryKey: 'my_assignments' },
  { key: 'changes-requested', label: 'Changes Requested From Me', summaryKey: 'changes_requested_from_me' },
  { key: 'mentions', label: 'Mentions', summaryKey: 'unread_mentions' },
  { key: 'overdue', label: 'Overdue Items', summaryKey: 'overdue_approvals' },
]

function formatDate(isoString) {
  if (!isoString) return '—'
  try {
    return new Date(isoString).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return isoString
  }
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

function RiskBadge({ risk }) {
  if (!risk) return <span className="table-muted">—</span>
  return <span className={`badge ${RISK_CLASS[risk] || 'badge--gray'}`}>{RISK_LABELS[risk] || risk}</span>
}

function DueBadge({ dueStatus, dueDate }) {
  if (!dueDate) return <span className="table-muted">—</span>
  if (!dueStatus) return <span className="table-muted">{formatDate(dueDate)}</span>
  return (
    <span className={`badge ${DUE_CLASS[dueStatus] || 'badge--gray'}`}>
      {DUE_LABELS[dueStatus] || dueStatus} · {formatDate(dueDate)}
    </span>
  )
}

function RolesCell({ roles }) {
  if (!roles || roles.length === 0) return <span className="table-muted">—</span>
  return <>{roles.map((r) => ROLE_LABELS[r] || r).join(', ')}</>
}

/** Module 18 Phase 5: the CR/Approval Type/Risk/Requested By/Due Date/
 * Status table (spec section 4) gets its Actions column from this shared
 * cell - Approve (one click, no comment), Reject/Request Changes (open an
 * inline comment box, comment required - same rule
 * app/services/workflow_rules.py::APPROVAL_REASON_REQUIRED already
 * enforces server-side), and View CR. Used by both the My Approvals and
 * Overdue Items tables since both list the same underlying approval rows. */
function ApprovalActionsCell({
  item,
  isResponding,
  respondStatus,
  respondComment,
  respondSubmitting,
  respondError,
  onOpenRespondForm,
  onCloseRespondForm,
  onSubmitResponse,
  onSetRespondComment,
  onOpenCr,
}) {
  if (isResponding) {
    return (
      <div className="respond-form" onClick={(e) => e.stopPropagation()}>
        {respondError && <p className="cr-form-error">{respondError}</p>}
        <p className="version-row-meta">
          {respondStatus === 'rejected' ? 'Rejecting' : 'Requesting changes'} - a comment is required.
        </p>
        <textarea
          rows={2}
          value={respondComment}
          onChange={(e) => onSetRespondComment(e.target.value)}
          aria-label="Comment"
        />
        <div className="status-form-row">
          <button
            type="button"
            className="cr-btn cr-btn--primary cr-btn--small"
            disabled={respondSubmitting || !respondComment.trim()}
            onClick={() => onSubmitResponse(item, respondStatus, respondComment)}
          >
            {respondSubmitting ? 'Submitting…' : 'Submit'}
          </button>
          <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={onCloseRespondForm}>
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="approval-actions-cell" onClick={(e) => e.stopPropagation()}>
      {item.status === 'pending' && (
        <>
          <button
            type="button"
            className="cr-btn cr-btn--primary cr-btn--small"
            disabled={respondSubmitting}
            onClick={() => onSubmitResponse(item, 'approved', null)}
          >
            Approve
          </button>
          <button
            type="button"
            className="cr-btn cr-btn--secondary cr-btn--small"
            disabled={respondSubmitting}
            onClick={() => onOpenRespondForm(item, 'rejected')}
          >
            Reject
          </button>
          <button
            type="button"
            className="cr-btn cr-btn--secondary cr-btn--small"
            disabled={respondSubmitting}
            onClick={() => onOpenRespondForm(item, 'changes_requested')}
          >
            Request Changes
          </button>
        </>
      )}
      <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={() => onOpenCr(item.change_request_id)}>
        View CR
      </button>
    </div>
  )
}

/** Module 18 Phase 4 (Notifications, My Work & Personal Engineering
 * Queue): the personal "what's on my plate" dashboard - My Change
 * Requests, My Approvals, My Reviews, My Assignments, Changes Requested
 * From Me, Mentions, and Overdue Items, each fetched from its own
 * dedicated, efficiently-filtered backend endpoint (see
 * backend/app/api/my_work.py) and lazily loaded only once its tab is
 * actually opened - never all seven sections fetched up front.
 *
 * Approve/Reject/Request Changes actions on My Approvals (and Overdue
 * Items, the same underlying approval rows) are wired up as of Phase 5,
 * reusing the same POST .../approvals/{id}/respond endpoint and
 * respondToApproval() helper Module 12's own ChangeRequestDetail.jsx page
 * already uses - no second response pathway. The priority highlighting
 * spec section 6 asks for (Overdue/Due Soon/High Risk/Critical Risk/
 * Waiting for Me) is computed already by the backend and just rendered
 * here as badges. */
export default function MyWorkPage({ onOpenChangeRequest }) {
  const { token } = useAuth()
  const [activeTab, setActiveTab] = useState('approvals')
  const [summary, setSummary] = useState(null)
  const [dataByTab, setDataByTab] = useState({})
  const [loadingTab, setLoadingTab] = useState(null)
  const [error, setError] = useState(null)
  const [approvalsShowAll, setApprovalsShowAll] = useState(false)

  // Module 18 Phase 5: which pending approval's Approve/Reject/Request-
  // Changes form is open, plus that one form's own fields - only one open
  // at a time, mirrors ChangeRequestDetail.jsx's own respond-form state.
  const [respondingApprovalId, setRespondingApprovalId] = useState(null)
  const [respondStatus, setRespondStatus] = useState('approved')
  const [respondComment, setRespondComment] = useState('')
  const [respondSubmitting, setRespondSubmitting] = useState(false)
  const [respondError, setRespondError] = useState(null)

  function loadSummary() {
    getMyWorkSummary(token)
      .then(setSummary)
      .catch(() => {})
  }

  function loadTab(tab, { force = false } = {}) {
    if (!force && dataByTab[tab] !== undefined) return
    setLoadingTab(tab)
    setError(null)

    const fetcher = {
      'change-requests': () => getMyChangeRequests(token),
      approvals: () => getMyApprovals(token, { all: approvalsShowAll }),
      reviews: () => getMyReviews(token),
      assignments: () => getMyAssignments(token),
      'changes-requested': () => getChangesRequestedFromMe(token),
      mentions: () => getMyMentions(token),
      overdue: () => getOverdueItems(token),
    }[tab]

    fetcher()
      .then((data) => setDataByTab((prev) => ({ ...prev, [tab]: data })))
      .catch((err) => setError(err.message || 'Could not load this list.'))
      .finally(() => setLoadingTab(null))
  }

  useEffect(() => {
    if (!token) return
    loadSummary()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  useEffect(() => {
    if (!token) return
    loadTab(activeTab)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, activeTab])

  function toggleApprovalsShowAll(nextValue) {
    setApprovalsShowAll(nextValue)
    // Refetch immediately with the new filter rather than waiting for a
    // dependency-driven effect (which would also re-fire once on mount).
    setLoadingTab('approvals')
    setError(null)
    getMyApprovals(token, { all: nextValue })
      .then((data) => setDataByTab((prev) => ({ ...prev, approvals: data })))
      .catch((err) => setError(err.message || 'Could not load this list.'))
      .finally(() => setLoadingTab(null))
  }

  function openCr(id) {
    onOpenChangeRequest?.(id)
  }

  // Wraps setActiveTab so switching tabs always closes whatever respond
  // form happened to be open on the previous tab's table.
  function selectTab(key) {
    setRespondingApprovalId(null)
    setRespondError(null)
    setActiveTab(key)
  }

  function openRespondForm(item, status) {
    setRespondingApprovalId(item.id)
    setRespondStatus(status)
    setRespondComment('')
    setRespondError(null)
  }

  function closeRespondForm() {
    setRespondingApprovalId(null)
    setRespondComment('')
    setRespondError(null)
  }

  // Shared by the quick "Approve" button (no comment needed) and the
  // Reject/Request Changes inline forms (comment required) - same
  // POST .../approvals/{id}/respond endpoint Module 12's own
  // ChangeRequestDetail.jsx page already uses, never a second pathway.
  async function submitResponse(item, status, comment) {
    setRespondSubmitting(true)
    setRespondError(null)
    try {
      const payload = { status }
      if (comment && comment.trim()) payload.comment = comment.trim()
      await respondToApproval(item.change_request_id, item.id, payload, token)
      setRespondingApprovalId(null)
      setRespondComment('')
      loadTab(activeTab, { force: true })
      loadSummary()
    } catch (err) {
      setRespondError(err.message || 'Could not submit this response. Please try again.')
    } finally {
      setRespondSubmitting(false)
    }
  }

  const rows = dataByTab[activeTab]
  const isLoading = loadingTab === activeTab && rows === undefined

  return (
    <div className="dashboard-shell">
      <div className="dashboard-heading">
        <h1>My Work</h1>
        <p>Your personal engineering queue - what's on your plate right now, in one place.</p>
      </div>

      {summary && (
        <div className="metric-grid">
          {TABS.map((tab) => (
            <div
              key={tab.key}
              className="metric-card-clickable"
              role="button"
              tabIndex={0}
              onClick={() => selectTab(tab.key)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') selectTab(tab.key)
              }}
            >
              <MetricCard
                label={tab.label}
                value={summary[tab.summaryKey] ?? 0}
                tone={tab.key === 'overdue' && summary.overdue_approvals > 0 ? 'danger' : 'default'}
              />
            </div>
          ))}
        </div>
      )}

      <div className="ad-tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            className={`ad-tab${activeTab === tab.key ? ' ad-tab--active' : ''}`}
            onClick={() => selectTab(tab.key)}
          >
            {tab.label}
            {summary && summary[tab.summaryKey] > 0 && (
              <span className="ad-tab-count">{summary[tab.summaryKey]}</span>
            )}
          </button>
        ))}
      </div>

      {activeTab === 'approvals' && (
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', color: '#667085', marginBottom: '0.75rem' }}>
          <input
            type="checkbox"
            checked={approvalsShowAll}
            onChange={(e) => toggleApprovalsShowAll(e.target.checked)}
          />
          Show every approval (including already-decided ones)
        </label>
      )}

      {isLoading && <p className="dashboard-status-text">Loading…</p>}
      {error && <p className="dashboard-status-text dashboard-status-text--error">{error}</p>}

      {!isLoading && !error && rows && rows.length === 0 && (
        <div className="dashboard-empty">
          <h2 className="dashboard-empty-title">Nothing here</h2>
          <p className="dashboard-empty-subtitle">
            {activeTab === 'approvals' && !approvalsShowAll
              ? "You're all caught up - no approvals waiting on you."
              : "Nothing to show in this section right now."}
          </p>
        </div>
      )}

      {!isLoading && !error && rows && rows.length > 0 && activeTab === 'change-requests' && (
        <TableCard>
          <thead>
            <tr>
              <th>ID</th>
              <th>Title</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Risk</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id} className="cr-list-row" onClick={() => openCr(item.id)}>
                <td className="requests-table-id">#{item.id}</td>
                <td className="requests-table-title">{item.title}</td>
                <td>
                  <span className={`badge ${PRIORITY_CLASS[item.priority] || 'badge--gray'}`}>
                    {PRIORITY_LABELS[item.priority] || item.priority}
                  </span>
                </td>
                <td>
                  <span className={`badge ${STATUS_CLASS[item.status] || 'badge--gray'}`}>
                    {STATUS_LABELS[item.status] || item.status}
                  </span>
                </td>
                <td>
                  <RiskBadge risk={item.risk} />
                </td>
                <td className="table-muted">{formatDate(item.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      )}

      {!isLoading && !error && rows && rows.length > 0 && activeTab === 'approvals' && (
        <TableCard>
          <thead>
            <tr>
              <th>CR</th>
              <th>Approval Type</th>
              <th>Risk</th>
              <th>Requested By</th>
              <th>Due Date</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id} className="cr-list-row" onClick={() => openCr(item.change_request_id)}>
                <td className="requests-table-title">
                  #{item.change_request_id} · {item.change_request_title}
                </td>
                <td>{item.approval_type_label}</td>
                <td>
                  <RiskBadge risk={item.risk} />
                </td>
                <td>{item.requested_by_name}</td>
                <td>
                  <DueBadge dueStatus={item.due_status} dueDate={item.due_date} />
                </td>
                <td>
                  <span className="badge badge--gray">{item.status_label}</span>
                  {item.status === 'pending' && <span className="badge badge--indigo waiting-badge">Waiting for you</span>}
                </td>
                <td>
                  <ApprovalActionsCell
                    item={item}
                    isResponding={respondingApprovalId === item.id}
                    respondStatus={respondStatus}
                    respondComment={respondComment}
                    respondSubmitting={respondSubmitting}
                    respondError={respondError}
                    onOpenRespondForm={openRespondForm}
                    onCloseRespondForm={closeRespondForm}
                    onSubmitResponse={submitResponse}
                    onSetRespondComment={setRespondComment}
                    onOpenCr={openCr}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      )}

      {!isLoading && !error && rows && rows.length > 0 && (activeTab === 'reviews' || activeTab === 'assignments') && (
        <TableCard>
          <thead>
            <tr>
              <th>CR</th>
              <th>Your Role(s)</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Risk</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.change_request_id} className="cr-list-row" onClick={() => openCr(item.change_request_id)}>
                <td className="requests-table-title">
                  #{item.change_request_id} · {item.title}
                </td>
                <td>
                  <RolesCell roles={item.roles} />
                </td>
                <td>
                  <span className={`badge ${PRIORITY_CLASS[item.priority] || 'badge--gray'}`}>
                    {PRIORITY_LABELS[item.priority] || item.priority}
                  </span>
                </td>
                <td>
                  <span className={`badge ${STATUS_CLASS[item.status] || 'badge--gray'}`}>
                    {STATUS_LABELS[item.status] || item.status}
                  </span>
                </td>
                <td>
                  <RiskBadge risk={item.risk} />
                </td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      )}

      {!isLoading && !error && rows && rows.length > 0 && activeTab === 'changes-requested' && (
        <TableCard>
          <thead>
            <tr>
              <th>CR</th>
              <th>Approval Type</th>
              <th>Responded By</th>
              <th>When</th>
              <th>Their Comment</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item, idx) => (
              <tr
                key={`${item.change_request_id}-${idx}`}
                className="cr-list-row"
                onClick={() => openCr(item.change_request_id)}
              >
                <td className="requests-table-title">
                  #{item.change_request_id} · {item.title}
                </td>
                <td>{item.approval_type_label}</td>
                <td>{item.approver_name}</td>
                <td className="table-muted">{formatDateTime(item.responded_at)}</td>
                <td>{item.comment || <span className="table-muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      )}

      {!isLoading && !error && rows && rows.length > 0 && activeTab === 'mentions' && (
        <ul className="notifications-list">
          {rows.map((n) => (
            <li
              key={n.id}
              className={`notification-row${n.is_read ? '' : ' notification-row--unread'}`}
              onClick={() => n.change_request_id != null && openCr(n.change_request_id)}
              role={n.change_request_id != null ? 'button' : undefined}
              tabIndex={n.change_request_id != null ? 0 : undefined}
            >
              <div className="notification-row-main">
                <strong>{n.title}</strong>
                {!n.is_read && <span className="notification-dot" aria-hidden="true" />}
              </div>
              <p className="cr-detail-text">{n.message}</p>
              <div className="notification-row-footer">
                <span className="version-row-meta">{formatDateTime(n.created_at)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!isLoading && !error && rows && rows.length > 0 && activeTab === 'overdue' && (
        <TableCard>
          <thead>
            <tr>
              <th>CR</th>
              <th>Approval Type</th>
              <th>Risk</th>
              <th>Requested By</th>
              <th>Due Date</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id} className="cr-list-row" onClick={() => openCr(item.change_request_id)}>
                <td className="requests-table-title">
                  #{item.change_request_id} · {item.change_request_title}
                </td>
                <td>{item.approval_type_label}</td>
                <td>
                  <RiskBadge risk={item.risk} />
                </td>
                <td>{item.requested_by_name}</td>
                <td>
                  <DueBadge dueStatus="overdue" dueDate={item.due_date} />
                </td>
                <td>
                  <ApprovalActionsCell
                    item={item}
                    isResponding={respondingApprovalId === item.id}
                    respondStatus={respondStatus}
                    respondComment={respondComment}
                    respondSubmitting={respondSubmitting}
                    respondError={respondError}
                    onOpenRespondForm={openRespondForm}
                    onCloseRespondForm={closeRespondForm}
                    onSubmitResponse={submitResponse}
                    onSetRespondComment={setRespondComment}
                    onOpenCr={openCr}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      )}
    </div>
  )
}

function TableCard({ children }) {
  return (
    <div className="table-card cr-table-card">
      <div className="table-scroll">
        <table className="requests-table">{children}</table>
      </div>
    </div>
  )
}
