import { useEffect, useRef, useState } from 'react'
import { analyzeChangeRequest } from '../api/analysis'
import {
  cancelApprovalRequest,
  createApprovalRequest,
  getRecommendedApprovals,
  listApprovals,
  respondToApproval,
} from '../api/approvals'
import {
  changeChangeRequestStatus,
  compareChangeRequestVersions,
  createChangeRequestAssignment,
  deleteChangeRequestAssignment,
  getChangeRequest,
  getChangeRequestHistory,
  getChangeRequestVersions,
  listChangeRequestAssignments,
} from '../api/changeRequests'
import { createComment, deleteComment, listComments, resolveComment } from '../api/comments'
import { listUsers } from '../api/users'
import { useAuth } from '../context/AuthContext'
// Reuses the .badge classes (dashboard.css) and the .cr-btn / breadcrumb /
// .cr-analyze-notice classes (change-request-form.css, Module 4).
import '../styles/dashboard.css'
import '../styles/change-request-form.css'
import '../styles/change-requests-list.css'
import '../styles/workflow.css'

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

// Mirrors app/services/workflow_rules.py::ROLE_LABELS - kept in sync
// manually, same as the other label maps in this file.
const ROLE_OPTIONS = [
  { value: 'requester', label: 'Requester' },
  { value: 'owner', label: 'Owner' },
  { value: 'technical_lead', label: 'Technical Lead' },
  { value: 'reviewer', label: 'Reviewer' },
  { value: 'approver', label: 'Approver' },
  { value: 'security_reviewer', label: 'Security Reviewer' },
  { value: 'qa_owner', label: 'QA Owner' },
  { value: 'implementation_owner', label: 'Implementation Owner' },
]

// Module 12 Phase 4: mirrors app/services/workflow_rules.py::
// APPROVAL_TYPE_LABELS - what kind of sign-off can be requested.
const APPROVAL_TYPE_OPTIONS = [
  { value: 'technical', label: 'Technical' },
  { value: 'security', label: 'Security' },
  { value: 'product', label: 'Product' },
  { value: 'engineering_manager', label: 'Engineering Manager' },
  { value: 'director', label: 'Director' },
  { value: 'qa', label: 'QA' },
  { value: 'dba', label: 'DBA' },
  { value: 'release', label: 'Release' },
  { value: 'general', label: 'General' },
]

// Mirrors app/services/workflow_rules.py::APPROVAL_STATUS_LABELS.
const APPROVAL_STATUS_LABELS = {
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  changes_requested: 'Changes Requested',
  cancelled: 'Cancelled',
}

const APPROVAL_STATUS_CLASS = {
  pending: 'badge--indigo',
  approved: 'badge--green',
  rejected: 'badge--red',
  changes_requested: 'badge--amber',
  cancelled: 'badge--gray',
}

// A response can only move a pending approval to one of these three - see
// app/services/workflow_rules.py::APPROVAL_RESPONSE_STATUSES /
// APPROVAL_REASON_REQUIRED (the last two require a comment).
const APPROVAL_RESPONSE_OPTIONS = [
  { value: 'approved', label: 'Approve' },
  { value: 'rejected', label: 'Reject' },
  { value: 'changes_requested', label: 'Request Changes' },
]
const APPROVAL_REASON_REQUIRED = new Set(['rejected', 'changes_requested'])

const RECOMMENDATION_LABELS = {
  approve: 'Approve',
  approve_with_conditions: 'Approve with conditions',
  requires_clarification: 'Requires clarification',
  needs_more_info: 'Needs more info',
  reject: 'Reject',
}

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

const HISTORY_ACTION_VERBS = {
  created: 'created this change request',
  field_changed: null, // rendered specially below (shows the field/old/new)
  version_created: null,
  ai_analysis_completed: null,
  ai_analysis_invalidated: null,
  status_changed: 'changed the status',
  assigned: 'assigned a team member',
  unassigned: 'removed a team member',
  approval_requested: 'requested an approval',
  approved: 'approved this change request',
  rejected: 'rejected this change request',
  changes_requested: 'requested changes',
  approval_invalidated: 'invalidated an approval',
  approval_cancelled: 'cancelled an approval request',
  comment_added: 'added a comment',
  mentioned: 'mentioned someone',
  report_generated: 'generated a report',
  reminder_sent: 'sent a reminder',
}

/** One line of the Activity/Audit timeline (Module 12 Phase 2, spec section
 * 17) - who did what, when, and (for field-level edits) the real old/new
 * value, never a vague "updated" line. */
function HistoryLine({ event, currentUserId }) {
  const who = event.actor_label || (event.user_id === currentUserId ? 'You' : `User #${event.user_id ?? '?'}`)

  let sentence
  if (event.action === 'field_changed') {
    sentence = (
      <>
        <strong>{who}</strong> changed <strong>{event.field_name}</strong>
      </>
    )
  } else if (event.action === 'version_created') {
    sentence = (
      <>
        <strong>{who}</strong> saved a new version
      </>
    )
  } else if (event.action === 'ai_analysis_completed') {
    sentence = (
      <>
        <strong>{who}</strong> completed an AI analysis
      </>
    )
  } else if (event.action === 'ai_analysis_invalidated') {
    sentence = (
      <>
        <strong>{who}</strong> - the previous AI analysis is now outdated
      </>
    )
  } else {
    sentence = (
      <>
        <strong>{who}</strong> {HISTORY_ACTION_VERBS[event.action] || event.action}
      </>
    )
  }

  return (
    <li className="history-item">
      <span className="history-dot" aria-hidden="true" />
      <div className="history-body">
        <p className="history-line">{sentence}</p>
        {(event.old_value || event.new_value) && (
          <p className="history-value-change">
            {event.old_value && <span className="from-value">{event.old_value}</span>}
            {event.old_value && event.new_value && ' → '}
            {event.new_value && <span className="to-value">{event.new_value}</span>}
          </p>
        )}
        {event.reason && <p className="history-value-change">Reason: {event.reason}</p>}
        <p className="history-meta">
          {formatDateTime(event.created_at)}
          {event.version_number ? ` · v${event.version_number}` : ''}
        </p>
      </div>
    </li>
  )
}

/** A plain <textarea> that pops up a filtered list of people right below
 * it whenever the caret sits inside an "@mention" in progress - arrow
 * keys + Enter/Tab (or a click) insert "@Full Name " at that spot, no
 * need to type the exact name from memory. Mentions are still just plain
 * text either way - the backend (app/services/mentions.py) parses them
 * back out of the comment body at write time, so typing "@Full Name" by
 * hand works exactly the same as picking it from this list. */
function MentionTextarea({ id, value, onChange, users, placeholder, rows }) {
  const textareaRef = useRef(null)
  const [suggestions, setSuggestions] = useState([])
  const [mentionStart, setMentionStart] = useState(null)
  const [highlightIndex, setHighlightIndex] = useState(0)

  function refreshSuggestions(text, cursorPos) {
    const upToCursor = text.slice(0, cursorPos)
    const lastAt = upToCursor.lastIndexOf('@')
    const query = lastAt === -1 ? null : upToCursor.slice(lastAt + 1)
    // Not mid-mention if there's no "@" before the caret, or the text
    // since that "@" already moved on (a newline, or another "@").
    if (query == null || query.includes('\n') || query.includes('@')) {
      setSuggestions([])
      setMentionStart(null)
      return
    }
    const lowerQuery = query.toLowerCase()
    const matches = (users || []).filter((u) => u.name.toLowerCase().includes(lowerQuery)).slice(0, 6)
    setSuggestions(matches)
    setMentionStart(matches.length > 0 ? lastAt : null)
    setHighlightIndex(0)
  }

  function chooseSuggestion(person) {
    if (mentionStart == null || !textareaRef.current) return
    const cursorPos = textareaRef.current.selectionStart
    const before = value.slice(0, mentionStart)
    const after = value.slice(cursorPos)
    const inserted = `@${person.name} `
    onChange(before + inserted + after)
    setSuggestions([])
    setMentionStart(null)
    requestAnimationFrame(() => {
      const pos = before.length + inserted.length
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(pos, pos)
    })
  }

  function handleKeyDown(event) {
    if (suggestions.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlightIndex((i) => (i + 1) % suggestions.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlightIndex((i) => (i - 1 + suggestions.length) % suggestions.length)
    } else if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      chooseSuggestion(suggestions[highlightIndex])
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setSuggestions([])
      setMentionStart(null)
    }
  }

  return (
    <div className="mention-input-wrap">
      <textarea
        id={id}
        ref={textareaRef}
        rows={rows}
        placeholder={placeholder}
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          refreshSuggestions(e.target.value, e.target.selectionStart)
        }}
        onKeyDown={handleKeyDown}
        onSelect={(e) => refreshSuggestions(e.target.value, e.target.selectionStart)}
        onBlur={() => window.setTimeout(() => setSuggestions([]), 150)}
      />
      {suggestions.length > 0 && (
        <ul className="mention-suggestions">
          {suggestions.map((person, index) => (
            <li key={person.id}>
              <button
                type="button"
                className={`mention-suggestion${index === highlightIndex ? ' mention-suggestion--active' : ''}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => chooseSuggestion(person)}
              >
                {person.name} <span className="version-row-meta">({person.email})</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Master-detail panel shown in place of the table when a row is selected.
 * Module 5 built this as a read view of GET /api/change-requests/{id}.
 * Module 6 wired the "Analyze Change" button to the real AI Analysis Engine
 * (POST .../analyze) and added a compact summary card once an analysis
 * exists. Module 7 moved the full requirement-by-requirement breakdown out
 * to its own dedicated AnalysisDashboardPage - this panel now only shows
 * the compact summary plus a CTA into that page, instead of duplicating
 * every section inline. */
export default function ChangeRequestDetail({ id, onBack, onOpenDashboard, onEdit }) {
  const { token, user } = useAuth()
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  // Module 12 Phase 6: the page grew a lot of sections (workflow status,
  // assignments, approvals, analysis, versions, history, comments) - tabs
  // group them so a first-time visitor isn't faced with one long stacked
  // page. Description/Details/Workflow Status/Assignments/Approvals/
  // Analysis stay together under Overview (they're all "about this
  // request as it stands today"); Versions + Activity History move under
  // one Versions & Activity tab (both are "what happened over time");
  // Comments gets its own tab since it's a separate, active conversation.
  const [activeTab, setActiveTab] = useState('overview')

  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState(null)

  const [history, setHistory] = useState(null)
  const [historyError, setHistoryError] = useState(null)
  const [versions, setVersions] = useState(null)
  const [versionsError, setVersionsError] = useState(null)
  const [compareVersion, setCompareVersion] = useState(null) // version_number being compared to its predecessor
  const [compareResult, setCompareResult] = useState(null)
  const [compareLoading, setCompareLoading] = useState(false)

  // Module 12 Phase 3: status workflow + assignments
  const [statusChoice, setStatusChoice] = useState('')
  const [statusReason, setStatusReason] = useState('')
  const [statusSubmitting, setStatusSubmitting] = useState(false)
  const [statusError, setStatusError] = useState(null)

  const [assignments, setAssignments] = useState(null)
  const [assignmentsError, setAssignmentsError] = useState(null)
  const [users, setUsers] = useState(null)
  const [newAssigneeUserId, setNewAssigneeUserId] = useState('')
  const [newAssigneeRole, setNewAssigneeRole] = useState('reviewer')
  const [assignSubmitting, setAssignSubmitting] = useState(false)
  const [assignError, setAssignError] = useState(null)
  const [removingAssignmentId, setRemovingAssignmentId] = useState(null)

  // Module 12 Phase 4: approvals
  const [approvals, setApprovals] = useState(null)
  const [approvalsError, setApprovalsError] = useState(null)
  const [recommendedApprovals, setRecommendedApprovals] = useState([])
  const [newApprovalType, setNewApprovalType] = useState('')
  const [newApprovalUserId, setNewApprovalUserId] = useState('')
  const [newApprovalComment, setNewApprovalComment] = useState('')
  // Module 18 Phase 5: entirely optional, mirrors app/models/approval.py's
  // own due_date docstring - most approval requests still set nothing here.
  const [newApprovalDueDate, setNewApprovalDueDate] = useState('')
  const [requestingApproval, setRequestingApproval] = useState(false)
  const [requestApprovalError, setRequestApprovalError] = useState(null)
  const [cancellingApprovalId, setCancellingApprovalId] = useState(null)
  // Which pending approval's Approve/Reject/Request-Changes form is open,
  // plus that one form's own fields - only one open at a time.
  const [respondingApprovalId, setRespondingApprovalId] = useState(null)
  const [respondStatus, setRespondStatus] = useState('approved')
  const [respondComment, setRespondComment] = useState('')
  const [respondSubmitting, setRespondSubmitting] = useState(false)
  const [respondError, setRespondError] = useState(null)

  // Module 12 Phase 5: comments, mentions, notifications
  const [comments, setComments] = useState(null)
  const [commentsError, setCommentsError] = useState(null)
  const [newCommentBody, setNewCommentBody] = useState('')
  const [postingComment, setPostingComment] = useState(false)
  const [postCommentError, setPostCommentError] = useState(null)
  const [replyingToId, setReplyingToId] = useState(null)
  const [replyBody, setReplyBody] = useState('')
  const [postingReply, setPostingReply] = useState(false)
  const [replyError, setReplyError] = useState(null)
  const [commentActionError, setCommentActionError] = useState(null)
  const [busyCommentId, setBusyCommentId] = useState(null)

  function loadDetail() {
    setLoading(true)
    setError(null)
    return getChangeRequest(id, token)
      .then((data) => {
        setDetail(data)
        return data
      })
      .catch((err) => {
        setError(err.message || 'Could not load this change request.')
        return null
      })
      .finally(() => setLoading(false))
  }

  function loadHistoryAndVersions() {
    setHistoryError(null)
    getChangeRequestHistory(id, token)
      .then(setHistory)
      .catch((err) => setHistoryError(err.message || 'Could not load activity history.'))

    setVersionsError(null)
    getChangeRequestVersions(id, token)
      .then(setVersions)
      .catch((err) => setVersionsError(err.message || 'Could not load versions.'))
  }

  function loadAssignments() {
    setAssignmentsError(null)
    listChangeRequestAssignments(id, token)
      .then(setAssignments)
      .catch((err) => setAssignmentsError(err.message || 'Could not load assignments.'))
  }

  function loadApprovals() {
    setApprovalsError(null)
    listApprovals(id, token)
      .then(setApprovals)
      .catch((err) => setApprovalsError(err.message || 'Could not load approvals.'))

    // Purely informational (AI recommends, humans decide) - a failure here
    // just means the "AI recommends" hints don't show, not worth its own
    // error banner.
    getRecommendedApprovals(id, token)
      .then(setRecommendedApprovals)
      .catch(() => setRecommendedApprovals([]))
  }

  function loadComments() {
    setCommentsError(null)
    listComments(id, token)
      .then(setComments)
      .catch((err) => setCommentsError(err.message || 'Could not load comments.'))
  }

  useEffect(() => {
    setDetail(null)
    setAnalyzeError(null)
    setHistory(null)
    setVersions(null)
    setCompareVersion(null)
    setCompareResult(null)
    setStatusChoice('')
    setStatusReason('')
    setStatusError(null)
    setAssignments(null)
    setAssignError(null)
    setApprovals(null)
    setApprovalsError(null)
    setRecommendedApprovals([])
    setNewApprovalType('')
    setNewApprovalUserId('')
    setNewApprovalComment('')
    setNewApprovalDueDate('')
    setRequestApprovalError(null)
    setRespondingApprovalId(null)
    setRespondError(null)
    setComments(null)
    setCommentsError(null)
    setNewCommentBody('')
    setPostCommentError(null)
    setReplyingToId(null)
    setReplyBody('')
    setReplyError(null)
    setCommentActionError(null)
    setActiveTab('overview')
    loadDetail()
    loadHistoryAndVersions()
    loadAssignments()
    loadApprovals()
    loadComments()
    listUsers(token).then(setUsers).catch(() => setUsers([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, token])

  function handleToggleCompare(versionNumber) {
    if (compareVersion === versionNumber) {
      setCompareVersion(null)
      setCompareResult(null)
      return
    }
    setCompareVersion(versionNumber)
    setCompareResult(null)
    setCompareLoading(true)
    compareChangeRequestVersions(id, versionNumber - 1, versionNumber, token)
      .then(setCompareResult)
      .catch((err) => setCompareResult({ error: err.message || 'Could not compare these versions.' }))
      .finally(() => setCompareLoading(false))
  }

  async function handleAnalyze() {
    setAnalyzing(true)
    setAnalyzeError(null)
    try {
      await analyzeChangeRequest(id, token)
      await loadDetail()
      loadHistoryAndVersions()
    } catch (err) {
      setAnalyzeError(err.message || 'Analysis failed. Please try again.')
    } finally {
      setAnalyzing(false)
    }
  }

  const selectedTransition = detail?.available_transitions.find((t) => t.status === statusChoice)

  async function handleStatusSubmit(event) {
    event.preventDefault()
    if (!statusChoice) return
    setStatusSubmitting(true)
    setStatusError(null)
    try {
      const payload = { status: statusChoice }
      if (statusReason.trim()) payload.reason = statusReason.trim()
      const updated = await changeChangeRequestStatus(id, payload, token)
      setDetail(updated)
      setStatusChoice('')
      setStatusReason('')
      loadHistoryAndVersions()
    } catch (err) {
      setStatusError(err.message || 'Could not update the status. Please try again.')
    } finally {
      setStatusSubmitting(false)
    }
  }

  async function handleAssignSubmit(event) {
    event.preventDefault()
    if (!newAssigneeUserId) return
    setAssignSubmitting(true)
    setAssignError(null)
    try {
      await createChangeRequestAssignment(
        id,
        { user_id: Number(newAssigneeUserId), role: newAssigneeRole },
        token
      )
      setNewAssigneeUserId('')
      loadAssignments()
      loadHistoryAndVersions()
    } catch (err) {
      setAssignError(err.message || 'Could not assign this user. Please try again.')
    } finally {
      setAssignSubmitting(false)
    }
  }

  async function handleRemoveAssignment(assignmentId) {
    setRemovingAssignmentId(assignmentId)
    setAssignError(null)
    try {
      await deleteChangeRequestAssignment(id, assignmentId, token)
      loadAssignments()
      loadHistoryAndVersions()
    } catch (err) {
      setAssignError(err.message || 'Could not remove this assignment. Please try again.')
    } finally {
      setRemovingAssignmentId(null)
    }
  }

  async function handleRequestApproval(event) {
    event.preventDefault()
    if (!newApprovalType || !newApprovalUserId) return
    setRequestingApproval(true)
    setRequestApprovalError(null)
    try {
      const payload = { approval_type: newApprovalType, approver_user_id: Number(newApprovalUserId) }
      if (newApprovalComment.trim()) payload.comment = newApprovalComment.trim()
      if (newApprovalDueDate) payload.due_date = new Date(newApprovalDueDate).toISOString()
      await createApprovalRequest(id, payload, token)
      setNewApprovalType('')
      setNewApprovalUserId('')
      setNewApprovalComment('')
      setNewApprovalDueDate('')
      loadApprovals()
      loadHistoryAndVersions()
    } catch (err) {
      setRequestApprovalError(err.message || 'Could not request this approval. Please try again.')
    } finally {
      setRequestingApproval(false)
    }
  }

  function openRespondForm(approval) {
    setRespondingApprovalId(approval.id)
    setRespondStatus('approved')
    setRespondComment('')
    setRespondError(null)
  }

  async function handleRespondSubmit(event, approvalId) {
    event.preventDefault()
    setRespondSubmitting(true)
    setRespondError(null)
    try {
      const payload = { status: respondStatus }
      if (respondComment.trim()) payload.comment = respondComment.trim()
      await respondToApproval(id, approvalId, payload, token)
      setRespondingApprovalId(null)
      setRespondComment('')
      loadApprovals()
      loadHistoryAndVersions()
    } catch (err) {
      setRespondError(err.message || 'Could not submit this response. Please try again.')
    } finally {
      setRespondSubmitting(false)
    }
  }

  async function handleCancelApproval(approvalId) {
    setCancellingApprovalId(approvalId)
    setApprovalsError(null)
    try {
      await cancelApprovalRequest(id, approvalId, token)
      loadApprovals()
      loadHistoryAndVersions()
    } catch (err) {
      setApprovalsError(err.message || 'Could not cancel this approval request. Please try again.')
    } finally {
      setCancellingApprovalId(null)
    }
  }

  async function handlePostComment(event) {
    event.preventDefault()
    if (!newCommentBody.trim()) return
    setPostingComment(true)
    setPostCommentError(null)
    try {
      await createComment(id, { body: newCommentBody.trim() }, token)
      setNewCommentBody('')
      loadComments()
      loadHistoryAndVersions()
    } catch (err) {
      setPostCommentError(err.message || 'Could not post this comment. Please try again.')
    } finally {
      setPostingComment(false)
    }
  }

  function openReplyForm(commentId) {
    setReplyingToId(commentId)
    setReplyBody('')
    setReplyError(null)
  }

  async function handlePostReply(event, parentId) {
    event.preventDefault()
    if (!replyBody.trim()) return
    setPostingReply(true)
    setReplyError(null)
    try {
      await createComment(id, { body: replyBody.trim(), parent_id: parentId }, token)
      setReplyingToId(null)
      setReplyBody('')
      loadComments()
      loadHistoryAndVersions()
    } catch (err) {
      setReplyError(err.message || 'Could not post this reply. Please try again.')
    } finally {
      setPostingReply(false)
    }
  }

  async function handleToggleResolved(comment) {
    setBusyCommentId(comment.id)
    setCommentActionError(null)
    try {
      await resolveComment(id, comment.id, !comment.resolved, token)
      loadComments()
    } catch (err) {
      setCommentActionError(err.message || 'Could not update this comment. Please try again.')
    } finally {
      setBusyCommentId(null)
    }
  }

  async function handleDeleteComment(comment) {
    setBusyCommentId(comment.id)
    setCommentActionError(null)
    try {
      await deleteComment(id, comment.id, token)
      loadComments()
      loadHistoryAndVersions()
    } catch (err) {
      setCommentActionError(err.message || 'Could not delete this comment. Please try again.')
    } finally {
      setBusyCommentId(null)
    }
  }

  const topLevelComments = (comments || []).filter((c) => c.parent_id == null)
  function repliesTo(commentId) {
    return (comments || []).filter((c) => c.parent_id === commentId)
  }
  function mentionedNames(comment) {
    if (!comment.mentioned_user_ids?.length || !users) return null
    return comment.mentioned_user_ids
      .map((uid) => users.find((u) => u.id === uid)?.name)
      .filter(Boolean)
      .join(', ')
  }

  return (
    <div className="cr-detail-shell">
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        <button type="button" className="breadcrumb-link" onClick={onBack}>
          Change Requests
        </button>
        <span className="breadcrumb-separator">/</span>
        <span className="breadcrumb-current">{detail ? `#${detail.id}` : `#${id}`}</span>
      </nav>

      {loading && <p className="cr-list-status-text">Loading change request…</p>}
      {error && <p className="cr-list-status-text cr-list-status-text--error">{error}</p>}

      {detail && (
        <>
          <div className="cr-detail-heading">
            <div>
              <h1>{detail.title}</h1>
              <div className="cr-detail-badges">
                <span className={`badge ${STATUS_CLASS[detail.effective_status] || 'badge--gray'}`}>
                  {STATUS_LABELS[detail.effective_status] || detail.effective_status}
                </span>
                <span className={`badge ${PRIORITY_CLASS[detail.priority] || 'badge--gray'}`}>
                  {PRIORITY_LABELS[detail.priority] || detail.priority} priority
                </span>
                <span className="badge version-badge">v{detail.current_version || 1}</span>
              </div>
            </div>
            <button type="button" className="cr-btn cr-btn--secondary" onClick={() => onEdit?.(id)}>
              Edit
            </button>
          </div>

          {detail.is_analysis_outdated && (
            <div className="outdated-banner">
              <span className="outdated-banner-text">
                <span className="outdated-banner-icon" aria-hidden="true">
                  ⚠
                </span>
                <span>
                  <strong>AI analysis outdated.</strong> This request has changed since its last analysis ran -
                  re-analyze to get results that reflect the current version.
                </span>
              </span>
              <button
                type="button"
                className="cr-btn cr-btn--primary cr-btn--small"
                onClick={handleAnalyze}
                disabled={analyzing}
              >
                {analyzing ? 'Re-analyzing…' : 'Re-analyze'}
              </button>
            </div>
          )}

          <div className="cr-detail-tabs" role="tablist" aria-label="Change request sections">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'overview'}
              className={`cr-detail-tab${activeTab === 'overview' ? ' cr-detail-tab--active' : ''}`}
              onClick={() => setActiveTab('overview')}
            >
              Overview
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'activity'}
              className={`cr-detail-tab${activeTab === 'activity' ? ' cr-detail-tab--active' : ''}`}
              onClick={() => setActiveTab('activity')}
            >
              Versions &amp; Activity
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'comments'}
              className={`cr-detail-tab${activeTab === 'comments' ? ' cr-detail-tab--active' : ''}`}
              onClick={() => setActiveTab('comments')}
            >
              Comments{comments && comments.length > 0 ? ` (${comments.length})` : ''}
            </button>
          </div>

          {activeTab === 'overview' && (
            <>
          <section className="cr-detail-section">
            <h2 className="cr-section-title">Description</h2>
            <p className="cr-detail-text">{detail.description}</p>
            {detail.business_objective && (
              <>
                <h2 className="cr-section-title cr-section-title--spaced">Business Objective</h2>
                <p className="cr-detail-text">{detail.business_objective}</p>
              </>
            )}
          </section>

          <section className="cr-detail-section">
            <h2 className="cr-section-title">Details</h2>
            <dl className="cr-detail-grid">
              <dt>Requested By</dt>
              <dd>{detail.requested_by || '—'}</dd>
              <dt>Target System</dt>
              <dd>{detail.target_system || '—'}</dd>
              <dt>Desired Deadline</dt>
              <dd>{formatDate(detail.desired_deadline)}</dd>
              <dt>Created</dt>
              <dd>{formatDate(detail.created_at)}</dd>
              <dt>Last Updated</dt>
              <dd>{formatDate(detail.updated_at)}</dd>
            </dl>
          </section>

          <section className="cr-detail-section">
            <h2 className="cr-section-title">Workflow Status</h2>
            <p className="cr-detail-text">
              Current status: <strong>{detail.status_label}</strong>
            </p>
            {detail.available_transitions.length > 0 ? (
              <form className="status-form" onSubmit={handleStatusSubmit}>
                {statusError && <p className="cr-form-error">{statusError}</p>}
                <div className="status-form-row">
                  <select
                    className="cr-filter-select"
                    value={statusChoice}
                    onChange={(e) => {
                      setStatusChoice(e.target.value)
                      setStatusReason('')
                    }}
                    aria-label="Move to status"
                  >
                    <option value="">Move to…</option>
                    {detail.available_transitions.map((t) => (
                      <option key={t.status} value={t.status}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    className="cr-btn cr-btn--secondary cr-btn--small"
                    disabled={!statusChoice || statusSubmitting}
                  >
                    {statusSubmitting ? 'Updating…' : 'Update Status'}
                  </button>
                </div>
                {selectedTransition?.requires_reason && (
                  <div className="cr-field">
                    <label htmlFor="status-reason">
                      Reason <span className="cr-optional-tag">required for this change</span>
                    </label>
                    <textarea
                      id="status-reason"
                      rows={2}
                      value={statusReason}
                      onChange={(e) => setStatusReason(e.target.value)}
                    />
                  </div>
                )}
              </form>
            ) : (
              <p className="no-changes-note">This is a final status - no further transitions are available.</p>
            )}
          </section>

          <section className="cr-detail-section">
            <h2 className="cr-section-title">Team &amp; Assignments</h2>
            {assignmentsError && <p className="cr-list-status-text cr-list-status-text--error">{assignmentsError}</p>}
            {assignments && assignments.length > 0 ? (
              <ul className="assignments-list">
                {assignments.map((a) => (
                  <li key={a.id} className="assignment-row">
                    <span>
                      <strong>{a.role_label}</strong> — {a.user_name}
                      <span className="version-row-meta"> ({a.user_email})</span>
                    </span>
                    <button
                      type="button"
                      className="cr-btn cr-btn--ghost cr-btn--small"
                      onClick={() => handleRemoveAssignment(a.id)}
                      disabled={removingAssignmentId === a.id}
                    >
                      {removingAssignmentId === a.id ? 'Removing…' : 'Remove'}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              assignments && <p className="cr-detail-text">No one is assigned to this request yet.</p>
            )}

            <form className="assign-form" onSubmit={handleAssignSubmit}>
              {assignError && <p className="cr-form-error">{assignError}</p>}
              <div className="status-form-row">
                <select
                  className="cr-filter-select"
                  value={newAssigneeRole}
                  onChange={(e) => setNewAssigneeRole(e.target.value)}
                  aria-label="Role to assign"
                >
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
                <select
                  className="cr-filter-select"
                  value={newAssigneeUserId}
                  onChange={(e) => setNewAssigneeUserId(e.target.value)}
                  aria-label="Person to assign"
                >
                  <option value="">Select a person…</option>
                  {(users || []).map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} ({u.email})
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  className="cr-btn cr-btn--secondary cr-btn--small"
                  disabled={!newAssigneeUserId || assignSubmitting}
                >
                  {assignSubmitting ? 'Assigning…' : 'Assign'}
                </button>
              </div>
            </form>
          </section>

          <section className="cr-detail-section">
            <h2 className="cr-section-title">Approvals</h2>
            {recommendedApprovals.length > 0 && (
              <p className="cr-detail-text approvals-recommendation">
                AI recommends: {recommendedApprovals.map((r) => r.label).join(', ')} approval
                {recommendedApprovals.length > 1 ? 's' : ''}.{' '}
                <span className="cr-optional-tag">the AI never requests these itself - you choose who to tag</span>
                {/* Module 22: recommended_approvals.is_outdated - this
                    recommendation was computed from an analysis that no
                    longer matches the change request's current version. */}
                {recommendedApprovals[0]?.is_outdated && (
                  <span className="badge badge--amber" title="The change request has been edited since this analysis ran.">
                    May be outdated
                  </span>
                )}
              </p>
            )}
            {approvalsError && <p className="cr-list-status-text cr-list-status-text--error">{approvalsError}</p>}
            {approvals && approvals.length > 0 ? (
              <ul className="approvals-list">
                {approvals.map((a) => {
                  const isApprover = a.approver_id === user?.id
                  const isResponding = respondingApprovalId === a.id
                  return (
                    <li key={a.id} className="approval-row">
                      <div className="approval-row-main">
                        <span>
                          <strong>{a.approval_type_label}</strong> — {a.approver_name}
                          <span className="version-row-meta"> ({a.approver_email})</span>
                        </span>
                        <span className={`badge ${APPROVAL_STATUS_CLASS[a.status] || 'badge--gray'}`}>
                          {APPROVAL_STATUS_LABELS[a.status] || a.status}
                        </span>
                        {a.is_outdated && <span className="badge badge--amber">Outdated</span>}
                        {a.overrode_ai_recommendation && (
                          <span className="badge badge--red" title="This decision didn't match what the AI recommended">
                            Overrode AI
                          </span>
                        )}
                      </div>
                      <p className="version-row-meta">
                        Requested by {a.requested_by_name} on {formatDateTime(a.requested_at)}
                        {a.responded_at ? ` · responded ${formatDateTime(a.responded_at)}` : ''}
                      </p>
                      {/* Module 13 Phase 4: what the AI recommended on the analysis this
                          approval was actually requested against (by cr_version) - purely
                          informational, never a constraint on the approver's decision. */}
                      {a.ai_recommendation && (
                        <p className="version-row-meta">AI recommended: {a.ai_recommendation}</p>
                      )}
                      {a.comment && <p className="history-value-change">Comment: {a.comment}</p>}

                      {a.status === 'pending' && isApprover && !isResponding && (
                        <button
                          type="button"
                          className="cr-btn cr-btn--secondary cr-btn--small"
                          onClick={() => openRespondForm(a)}
                        >
                          Respond
                        </button>
                      )}

                      {a.status === 'pending' && isApprover && isResponding && (
                        <form className="respond-form" onSubmit={(e) => handleRespondSubmit(e, a.id)}>
                          {respondError && <p className="cr-form-error">{respondError}</p>}
                          <div className="status-form-row">
                            <select
                              className="cr-filter-select"
                              value={respondStatus}
                              onChange={(e) => setRespondStatus(e.target.value)}
                              aria-label="Your response"
                            >
                              {APPROVAL_RESPONSE_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>
                                  {o.label}
                                </option>
                              ))}
                            </select>
                            <button type="submit" className="cr-btn cr-btn--primary cr-btn--small" disabled={respondSubmitting}>
                              {respondSubmitting ? 'Submitting…' : 'Submit'}
                            </button>
                            <button
                              type="button"
                              className="cr-btn cr-btn--ghost cr-btn--small"
                              onClick={() => setRespondingApprovalId(null)}
                            >
                              Cancel
                            </button>
                          </div>
                          {APPROVAL_REASON_REQUIRED.has(respondStatus) && (
                            <div className="cr-field">
                              <label htmlFor={`respond-comment-${a.id}`}>
                                Comment <span className="cr-optional-tag">required for this response</span>
                              </label>
                              <textarea
                                id={`respond-comment-${a.id}`}
                                rows={2}
                                value={respondComment}
                                onChange={(e) => setRespondComment(e.target.value)}
                              />
                            </div>
                          )}
                        </form>
                      )}

                      {a.status === 'pending' && !isApprover && (
                        <button
                          type="button"
                          className="cr-btn cr-btn--ghost cr-btn--small"
                          onClick={() => handleCancelApproval(a.id)}
                          disabled={cancellingApprovalId === a.id}
                        >
                          {cancellingApprovalId === a.id ? 'Cancelling…' : 'Cancel Request'}
                        </button>
                      )}
                    </li>
                  )
                })}
              </ul>
            ) : (
              approvals && <p className="cr-detail-text">No approvals have been requested yet.</p>
            )}

            <form className="assign-form" onSubmit={handleRequestApproval}>
              {requestApprovalError && <p className="cr-form-error">{requestApprovalError}</p>}
              <div className="status-form-row">
                <select
                  className="cr-filter-select"
                  value={newApprovalType}
                  onChange={(e) => setNewApprovalType(e.target.value)}
                  aria-label="Type of approval"
                >
                  <option value="">Approval type…</option>
                  {APPROVAL_TYPE_OPTIONS.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                      {recommendedApprovals.some((r) => r.approval_type === t.value) ? ' (AI recommends)' : ''}
                    </option>
                  ))}
                </select>
                <select
                  className="cr-filter-select"
                  value={newApprovalUserId}
                  onChange={(e) => setNewApprovalUserId(e.target.value)}
                  aria-label="Approver"
                >
                  <option value="">Select a person…</option>
                  {(users || []).map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} ({u.email})
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  className="cr-btn cr-btn--secondary cr-btn--small"
                  disabled={!newApprovalType || !newApprovalUserId || requestingApproval}
                >
                  {requestingApproval ? 'Requesting…' : 'Request Approval'}
                </button>
              </div>
              <div className="cr-field">
                <label htmlFor="approval-comment">
                  Note to approver <span className="cr-optional-tag">optional</span>
                </label>
                <textarea
                  id="approval-comment"
                  rows={2}
                  value={newApprovalComment}
                  onChange={(e) => setNewApprovalComment(e.target.value)}
                />
              </div>
              <div className="cr-field">
                <label htmlFor="approval-due-date">
                  Due date <span className="cr-optional-tag">optional</span>
                </label>
                <input
                  id="approval-due-date"
                  type="date"
                  className="cr-filter-select"
                  value={newApprovalDueDate}
                  onChange={(e) => setNewApprovalDueDate(e.target.value)}
                />
              </div>
            </form>
          </section>

          <section className="cr-detail-section">
            <h2 className="cr-section-title">Analysis</h2>
            {detail.latest_analysis ? (
              <div className="cr-analysis-block">
                <p className="cr-detail-text">{detail.latest_analysis.summary}</p>
                <dl className="cr-detail-grid">
                  <dt>Category</dt>
                  <dd>{detail.latest_analysis.category}</dd>
                  <dt>Complexity</dt>
                  <dd className="cr-capitalize">{detail.latest_analysis.complexity.replace('_', ' ')}</dd>
                  <dt>Risk Score</dt>
                  <dd>{detail.latest_analysis.risk_score}/100</dd>
                  <dt>Confidence</dt>
                  <dd>{detail.latest_analysis.confidence_score}/100</dd>
                  <dt>Recommendation</dt>
                  <dd>
                    {detail.latest_analysis.recommendation
                      ? RECOMMENDATION_LABELS[detail.latest_analysis.recommendation] ||
                        detail.latest_analysis.recommendation
                      : '—'}
                  </dd>
                </dl>

                {detail.latest_analysis.clarification_questions.length > 0 && (
                  <>
                    <h3 className="cr-section-title cr-section-title--spaced">Clarification Questions</h3>
                    <ul className="cr-question-list">
                      {detail.latest_analysis.clarification_questions.map((q) => (
                        <li key={q.id} className="cr-question-item">
                          <span className={`badge ${q.resolved ? 'badge--green' : 'badge--amber'}`}>
                            {q.resolved ? 'Resolved' : 'Open'}
                          </span>
                          <div>
                            <p className="cr-question-text">{q.question}</p>
                            <p className="cr-question-reason">{q.reason}</p>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </>
                )}

                <div className="cr-form-actions cr-form-actions--left">
                  <button
                    type="button"
                    className="cr-btn cr-btn--primary"
                    onClick={() => onOpenDashboard?.(id)}
                  >
                    View Full AI Analysis Dashboard →
                  </button>
                  <button
                    type="button"
                    className="cr-btn cr-btn--secondary"
                    onClick={handleAnalyze}
                    disabled={analyzing}
                  >
                    {analyzing ? 'Re-analyzing…' : 'Re-analyze'}
                  </button>
                </div>
                {analyzeError && <p className="cr-form-error">{analyzeError}</p>}
              </div>
            ) : (
              <div className="cr-no-analysis">
                <p className="cr-detail-text">This request hasn&apos;t been analyzed yet.</p>
                <button
                  type="button"
                  className="cr-btn cr-btn--primary"
                  onClick={handleAnalyze}
                  disabled={analyzing}
                >
                  {analyzing ? 'Analyzing… this can take up to a minute' : 'Analyze Change'}
                </button>
                {analyzeError && <p className="cr-form-error">{analyzeError}</p>}
              </div>
            )}
          </section>
            </>
          )}

          {activeTab === 'activity' && (
            <>
          <section className="cr-detail-section">
            <h2 className="cr-section-title">Versions</h2>
            {versionsError && <p className="cr-list-status-text cr-list-status-text--error">{versionsError}</p>}
            {versions && versions.length > 0 && (
              <ul className="versions-list">
                {versions.map((version) => (
                  <li key={version.version_number}>
                    <div className="version-row">
                      <div className="version-row-main">
                        <span className="version-row-number">Version {version.version_number}</span>
                        <span className="version-row-summary">{version.change_summary}</span>
                        <span className="version-row-meta">{formatDateTime(version.created_at)}</span>
                      </div>
                      {version.version_number > 1 && (
                        <button
                          type="button"
                          className="cr-btn cr-btn--secondary cr-btn--small"
                          onClick={() => handleToggleCompare(version.version_number)}
                        >
                          {compareVersion === version.version_number ? 'Hide changes' : 'View changes'}
                        </button>
                      )}
                    </div>

                    {compareVersion === version.version_number && (
                      <div className="cr-detail-section" style={{ marginTop: '0.5rem' }}>
                        {compareLoading && <p className="cr-list-status-text">Comparing…</p>}
                        {compareResult?.error && (
                          <p className="cr-list-status-text cr-list-status-text--error">{compareResult.error}</p>
                        )}
                        {compareResult?.fields && (
                          <table className="compare-table">
                            <thead>
                              <tr>
                                <th>Field</th>
                                <th>Version {compareResult.from_version}</th>
                                <th>Version {compareResult.to_version}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {compareResult.fields
                                .filter((f) => f.status !== 'unchanged')
                                .map((f) => (
                                  <tr key={f.field} className={`compare-row--${f.status}`}>
                                    <td>{f.label}</td>
                                    <td className="compare-old">{f.old_value ?? '—'}</td>
                                    <td className="compare-new">{f.new_value ?? '—'}</td>
                                  </tr>
                                ))}
                              {compareResult.fields.every((f) => f.status === 'unchanged') && (
                                <tr>
                                  <td colSpan={3} className="compare-row--unchanged">
                                    No field differences between these versions.
                                  </td>
                                </tr>
                              )}
                            </tbody>
                          </table>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="cr-detail-section">
            <h2 className="cr-section-title">Activity History</h2>
            {historyError && <p className="cr-list-status-text cr-list-status-text--error">{historyError}</p>}
            {history && history.length > 0 ? (
              <ul className="history-list">
                {history.map((event) => (
                  <HistoryLine key={event.id} event={event} currentUserId={user?.id} />
                ))}
              </ul>
            ) : (
              history && <p className="cr-detail-text">No activity recorded yet.</p>
            )}
          </section>
            </>
          )}

          {activeTab === 'comments' && (
          <section className="cr-detail-section">
            <h2 className="cr-section-title">Comments</h2>
            {commentsError && <p className="cr-list-status-text cr-list-status-text--error">{commentsError}</p>}
            {commentActionError && <p className="cr-form-error">{commentActionError}</p>}

            {topLevelComments.length > 0 ? (
              <ul className="comments-list">
                {topLevelComments.map((c) => {
                  const isAuthor = c.user_id === user?.id
                  const mentioned = mentionedNames(c)
                  return (
                    <li key={c.id} className="comment-row">
                      <div className="comment-row-header">
                        <strong>{c.user_name}</strong>
                        <span className="version-row-meta">{formatDateTime(c.created_at)}</span>
                        {c.resolved && <span className="badge badge--green">Resolved</span>}
                      </div>
                      <p className="cr-detail-text comment-body">{c.body}</p>
                      {mentioned && <p className="version-row-meta">Notified: {mentioned}</p>}
                      <div className="comment-row-actions">
                        <button
                          type="button"
                          className="cr-btn cr-btn--ghost cr-btn--small"
                          onClick={() => openReplyForm(c.id)}
                        >
                          Reply
                        </button>
                        <button
                          type="button"
                          className="cr-btn cr-btn--ghost cr-btn--small"
                          onClick={() => handleToggleResolved(c)}
                          disabled={busyCommentId === c.id}
                        >
                          {c.resolved ? 'Reopen' : 'Resolve'}
                        </button>
                        {isAuthor && (
                          <button
                            type="button"
                            className="cr-btn cr-btn--ghost cr-btn--small"
                            onClick={() => handleDeleteComment(c)}
                            disabled={busyCommentId === c.id}
                          >
                            Delete
                          </button>
                        )}
                      </div>

                      {replyingToId === c.id && (
                        <form className="respond-form comment-reply-form" onSubmit={(e) => handlePostReply(e, c.id)}>
                          {replyError && <p className="cr-form-error">{replyError}</p>}
                          <MentionTextarea
                            rows={2}
                            placeholder="Write a reply… type @ to mention someone"
                            value={replyBody}
                            onChange={setReplyBody}
                            users={users}
                          />
                          <div className="status-form-row">
                            <button
                              type="submit"
                              className="cr-btn cr-btn--primary cr-btn--small"
                              disabled={!replyBody.trim() || postingReply}
                            >
                              {postingReply ? 'Posting…' : 'Post Reply'}
                            </button>
                            <button
                              type="button"
                              className="cr-btn cr-btn--ghost cr-btn--small"
                              onClick={() => setReplyingToId(null)}
                            >
                              Cancel
                            </button>
                          </div>
                        </form>
                      )}

                      {repliesTo(c.id).length > 0 && (
                        <ul className="comment-replies-list">
                          {repliesTo(c.id).map((r) => {
                            const replyIsAuthor = r.user_id === user?.id
                            const replyMentioned = mentionedNames(r)
                            return (
                              <li key={r.id} className="comment-row comment-row--reply">
                                <div className="comment-row-header">
                                  <strong>{r.user_name}</strong>
                                  <span className="version-row-meta">{formatDateTime(r.created_at)}</span>
                                  {r.resolved && <span className="badge badge--green">Resolved</span>}
                                </div>
                                <p className="cr-detail-text comment-body">{r.body}</p>
                                {replyMentioned && <p className="version-row-meta">Notified: {replyMentioned}</p>}
                                <div className="comment-row-actions">
                                  <button
                                    type="button"
                                    className="cr-btn cr-btn--ghost cr-btn--small"
                                    onClick={() => handleToggleResolved(r)}
                                    disabled={busyCommentId === r.id}
                                  >
                                    {r.resolved ? 'Reopen' : 'Resolve'}
                                  </button>
                                  {replyIsAuthor && (
                                    <button
                                      type="button"
                                      className="cr-btn cr-btn--ghost cr-btn--small"
                                      onClick={() => handleDeleteComment(r)}
                                      disabled={busyCommentId === r.id}
                                    >
                                      Delete
                                    </button>
                                  )}
                                </div>
                              </li>
                            )
                          })}
                        </ul>
                      )}
                    </li>
                  )
                })}
              </ul>
            ) : (
              comments && <p className="cr-detail-text">No comments yet - start the discussion below.</p>
            )}

            <form className="assign-form" onSubmit={handlePostComment}>
              {postCommentError && <p className="cr-form-error">{postCommentError}</p>}
              <div className="cr-field">
                <label htmlFor="new-comment-body">Add a comment</label>
                <MentionTextarea
                  id="new-comment-body"
                  rows={3}
                  placeholder="Write a comment… type @ to mention someone"
                  value={newCommentBody}
                  onChange={setNewCommentBody}
                  users={users}
                />
              </div>
              <div className="status-form-row">
                <button
                  type="submit"
                  className="cr-btn cr-btn--primary cr-btn--small"
                  disabled={!newCommentBody.trim() || postingComment}
                >
                  {postingComment ? 'Posting…' : 'Post Comment'}
                </button>
              </div>
            </form>
          </section>
          )}
        </>
      )}
    </div>
  )
}
