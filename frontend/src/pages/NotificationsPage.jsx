import { useEffect, useState } from 'react'
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '../api/notifications'
import { useAuth } from '../context/AuthContext'
import '../styles/dashboard.css'
import '../styles/workflow.css'

// Mirrors app/models/enums.py::NotificationType.
const TYPE_LABELS = {
  assigned: 'Assigned',
  approval_requested: 'Approval Requested',
  approved: 'Approved',
  rejected: 'Rejected',
  changes_requested: 'Changes Requested',
  mentioned: 'Mentioned',
  status_changed: 'Status Changed',
  analysis_outdated: 'Analysis Outdated',
  reapproval_required: 'Re-approval Needed',
  reminder: 'Reminder',
  comment_added: 'New Comment',
  // Module 18 Phase 1/2 (Notifications, My Work & Personal Engineering Queue).
  risk_escalated: 'Risk Escalated',
  analysis_completed: 'Analysis Completed',
  deadline_approaching: 'Deadline Approaching',
}

const TYPE_CLASS = {
  assigned: 'badge--indigo',
  approval_requested: 'badge--indigo',
  approved: 'badge--green',
  rejected: 'badge--red',
  changes_requested: 'badge--amber',
  mentioned: 'badge--blue',
  status_changed: 'badge--gray',
  analysis_outdated: 'badge--amber',
  reapproval_required: 'badge--amber',
  reminder: 'badge--blue',
  comment_added: 'badge--gray',
  // Module 18 Phase 1/2.
  risk_escalated: 'badge--red',
  analysis_completed: 'badge--green',
  deadline_approaching: 'badge--amber',
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

/** Module 12 Phase 5: a user's own in-app notification inbox - assigned to
 * a CR, tagged for (or reminded about) an approval, an approval was
 * responded to, a CR's status changed, @mentioned or commented on, an AI
 * analysis went outdated, or a re-approval is needed. Clicking a
 * notification that references a change request marks it read and jumps
 * straight to that change request. */
export default function NotificationsPage({ onOpenChangeRequest }) {
  const { token } = useAuth()
  const [notifications, setNotifications] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [markingAll, setMarkingAll] = useState(false)

  function load() {
    setLoading(true)
    setError(null)
    listNotifications(token, { unreadOnly, limit: 100 })
      .then(setNotifications)
      .catch((err) => setError(err.message || 'Could not load notifications.'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, unreadOnly])

  function handleOpen(notification) {
    if (!notification.is_read) {
      markNotificationRead(notification.id, token)
        .then((updated) => {
          setNotifications((prev) => (prev || []).map((n) => (n.id === updated.id ? updated : n)))
        })
        .catch(() => {})
    }
    if (notification.change_request_id != null) {
      onOpenChangeRequest?.(notification.change_request_id)
    }
  }

  function handleMarkRead(event, notification) {
    event.stopPropagation()
    markNotificationRead(notification.id, token)
      .then((updated) => {
        setNotifications((prev) => (prev || []).map((n) => (n.id === updated.id ? updated : n)))
      })
      .catch(() => {})
  }

  async function handleMarkAllRead() {
    setMarkingAll(true)
    try {
      await markAllNotificationsRead(token)
      load()
    } catch {
      // best-effort - nothing to show the user beyond the list not updating
    } finally {
      setMarkingAll(false)
    }
  }

  const unreadCount = (notifications || []).filter((n) => !n.is_read).length

  return (
    <div className="dashboard-shell">
      <div className="dashboard-heading" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1>Notifications</h1>
          <p>Assignments, approvals, mentions, status changes, and outdated analyses - all in one place.</p>
        </div>
        <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', color: '#667085' }}>
            <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
            Unread only
          </label>
          <button
            type="button"
            className="cr-btn cr-btn--secondary cr-btn--small"
            onClick={handleMarkAllRead}
            disabled={markingAll || unreadCount === 0}
          >
            {markingAll ? 'Marking…' : 'Mark all read'}
          </button>
        </div>
      </div>

      {loading && <p className="dashboard-status-text">Loading notifications…</p>}
      {error && <p className="dashboard-status-text dashboard-status-text--error">{error}</p>}

      {notifications && notifications.length === 0 && (
        <div className="dashboard-empty">
          <h2 className="dashboard-empty-title">
            {unreadOnly ? 'No unread notifications' : 'No notifications yet'}
          </h2>
          <p className="dashboard-empty-subtitle">
            You&apos;ll see updates here when you&apos;re assigned, tagged for approval, @mentioned, or a change
            request you&apos;re involved in changes.
          </p>
        </div>
      )}

      {notifications && notifications.length > 0 && (
        <ul className="notifications-list">
          {notifications.map((n) => (
            <li
              key={n.id}
              className={`notification-row${n.is_read ? '' : ' notification-row--unread'}`}
              onClick={() => handleOpen(n)}
              role={n.change_request_id != null ? 'button' : undefined}
              tabIndex={n.change_request_id != null ? 0 : undefined}
            >
              <div className="notification-row-main">
                <span className={`badge ${TYPE_CLASS[n.type] || 'badge--gray'}`}>
                  {TYPE_LABELS[n.type] || n.type}
                </span>
                <strong>{n.title}</strong>
                {!n.is_read && <span className="notification-dot" aria-hidden="true" />}
              </div>
              <p className="cr-detail-text">{n.message}</p>
              <div className="notification-row-footer">
                <span className="version-row-meta">{formatDateTime(n.created_at)}</span>
                {!n.is_read && (
                  <button
                    type="button"
                    className="cr-btn cr-btn--ghost cr-btn--small"
                    onClick={(e) => handleMarkRead(e, n)}
                  >
                    Mark read
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
