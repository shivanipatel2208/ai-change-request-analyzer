import { useEffect, useRef, useState } from 'react'
import {
  getUnreadNotificationCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '../api/notifications'
import { useAuth } from '../context/AuthContext'
import BackendStatusBadge from './BackendStatusBadge'
import '../styles/workflow.css'
import './header.css'

// Module 21: 'settings' is the Administration section (AdminPage.jsx) -
// admin-only, so the render below filters it out of the list for every
// other role. Left in this shared array (rather than a separate admin-only
// list) so AuthenticatedHome's activeLabel lookup keeps working unchanged.
export const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'change-requests', label: 'Change Requests' },
  { key: 'new-analysis', label: 'New Analysis' },
  { key: 'my-work', label: 'My Work' },
  // Module 24: real page (ReportsPage.jsx) - statistics, search/filter, and
  // the report list. No manual "generate" step: a report appears here
  // automatically the moment a change request is analyzed. Placed right
  // after My Work, matching the order the project owner suggested.
  { key: 'reports', label: 'Reports' },
  { key: 'analytics', label: 'Analytics' },
  { key: 'notifications', label: 'Notifications' },
  { key: 'knowledge-base', label: 'Knowledge Base' },
  { key: 'settings', label: 'Settings' },
]

// Module 23: 'Repository' and 'Reports' used to be separate nav items here,
// but neither was ever its own page - both landed on the generic "built in
// a later module" placeholder even though the real features exist
// elsewhere (Repository Intelligence is a tab inside a change request's
// own Analysis Dashboard; the report is downloaded via the "Download
// Report" button on that same Analysis Dashboard page). Removed rather
// than left as dead links a demo could click into. See DEMO.md for where
// each actually is.

// Module 18 Phase 6's own recent-notifications dropdown only ever shows a
// handful - the full, paginated inbox is still the Notifications page.
const RECENT_LIMIT = 8

function initials(name) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  const first = parts[0]?.[0] ?? ''
  const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
  return (first + last).toUpperCase()
}

function formatRelative(isoString) {
  if (!isoString) return ''
  const then = new Date(isoString).getTime()
  if (Number.isNaN(then)) return ''
  const diffMs = Date.now() - then
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(isoString).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** Left-hand navigation sidebar for the authenticated app. (This used to be
 * a top header bar - kept the file/component name so nothing importing it
 * had to change, only what it renders.) Brand + notification bell at top,
 * primary nav in the middle, backend status + user/logout pinned at the
 * bottom. No router - `activeView` / `onNavigate` are plain local state
 * from the app shell.
 *
 * Module 18 Phase 6: the bell button next to the logo is the spec's
 * "notification center in the application header" - unread count, recent
 * notifications, mark as read, mark all as read, link to CR - all reusing
 * the same GET /api/notifications, /unread-count, PUT /{id}/read and
 * PUT /read-all endpoints the full Notifications page already uses (no
 * second notification pathway). The "Notifications" nav item below it
 * still opens that full, paginated page - the bell is only a quick-glance
 * dropdown over the most recent few. */
export default function AppHeader({ activeView, onNavigate, onOpenChangeRequest, user, onLogout }) {
  const { token } = useAuth()
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifOpen, setNotifOpen] = useState(false)
  const [recentNotifications, setRecentNotifications] = useState(null)
  const [recentError, setRecentError] = useState(null)
  const [loadingRecent, setLoadingRecent] = useState(false)
  const [markingAll, setMarkingAll] = useState(false)
  const dropdownRef = useRef(null)

  // Module 12 Phase 5: a lightweight poll for the notification badge - not
  // worth a websocket/SSE setup for a hackathon, and refreshes often enough
  // (every 30s, plus whenever the Notifications page itself is left) to
  // feel current.
  useEffect(() => {
    if (!token) return undefined
    let cancelled = false
    function poll() {
      getUnreadNotificationCount(token)
        .then((data) => {
          if (!cancelled) setUnreadCount(data.count || 0)
        })
        .catch(() => {})
    }
    poll()
    const handle = setInterval(poll, 30000)
    return () => {
      cancelled = true
      clearInterval(handle)
    }
  }, [token, activeView])

  // Close the dropdown on an outside click, same convention any menu/
  // popover in this app would use.
  useEffect(() => {
    if (!notifOpen) return undefined
    function handleDocumentClick(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setNotifOpen(false)
      }
    }
    document.addEventListener('mousedown', handleDocumentClick)
    return () => document.removeEventListener('mousedown', handleDocumentClick)
  }, [notifOpen])

  function loadRecent() {
    setLoadingRecent(true)
    setRecentError(null)
    listNotifications(token, { limit: RECENT_LIMIT })
      .then(setRecentNotifications)
      .catch((err) => setRecentError(err.message || 'Could not load notifications.'))
      .finally(() => setLoadingRecent(false))
  }

  function toggleNotifOpen() {
    setNotifOpen((prev) => {
      const next = !prev
      if (next) loadRecent()
      return next
    })
  }

  function handleOpenNotification(notification) {
    if (!notification.is_read) {
      markNotificationRead(notification.id, token)
        .then((updated) => {
          setRecentNotifications((prev) => (prev || []).map((n) => (n.id === updated.id ? updated : n)))
          setUnreadCount((count) => Math.max(0, count - 1))
        })
        .catch(() => {})
    }
    setNotifOpen(false)
    if (notification.change_request_id != null) {
      onOpenChangeRequest?.(notification.change_request_id)
    } else {
      onNavigate('notifications')
    }
  }

  async function handleMarkAllRead(event) {
    event.stopPropagation()
    setMarkingAll(true)
    try {
      await markAllNotificationsRead(token)
      setUnreadCount(0)
      setRecentNotifications((prev) => (prev || []).map((n) => ({ ...n, is_read: true })))
    } catch {
      // best-effort - nothing to show beyond the list not updating
    } finally {
      setMarkingAll(false)
    }
  }

  function handleViewAll(event) {
    event.stopPropagation()
    setNotifOpen(false)
    onNavigate('notifications')
  }

  return (
    <aside className="app-sidebar">
      <div className="app-sidebar-brand">
        <span className="app-sidebar-logo-mark">AI</span>
        <span className="app-sidebar-logo-word">Change Request Analyzer</span>

        <div className="notif-bell-wrap" ref={dropdownRef}>
          <button
            type="button"
            className="notif-bell-btn"
            onClick={toggleNotifOpen}
            aria-haspopup="true"
            aria-expanded={notifOpen}
            aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
          >
            <span aria-hidden="true">🔔</span>
            {unreadCount > 0 && (
              <span className="notif-bell-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
            )}
          </button>

          {notifOpen && (
            <div className="notif-dropdown" role="menu">
              <div className="notif-dropdown-header">
                <strong>Notifications</strong>
                <button
                  type="button"
                  className="cr-btn cr-btn--ghost cr-btn--small"
                  onClick={handleMarkAllRead}
                  disabled={markingAll || unreadCount === 0}
                >
                  {markingAll ? 'Marking…' : 'Mark all read'}
                </button>
              </div>

              {loadingRecent && <p className="notif-dropdown-status">Loading…</p>}
              {recentError && <p className="notif-dropdown-status notif-dropdown-status--error">{recentError}</p>}

              {!loadingRecent && !recentError && recentNotifications && recentNotifications.length === 0 && (
                <p className="notif-dropdown-status">You're all caught up - no notifications yet.</p>
              )}

              {!loadingRecent && !recentError && recentNotifications && recentNotifications.length > 0 && (
                <ul className="notif-dropdown-list">
                  {recentNotifications.map((n) => (
                    <li key={n.id}>
                      <button
                        type="button"
                        className={`notif-dropdown-item${n.is_read ? '' : ' notif-dropdown-item--unread'}`}
                        onClick={() => handleOpenNotification(n)}
                      >
                        <span className="notif-dropdown-item-top">
                          <span className="notif-dropdown-item-title">{n.title}</span>
                          {!n.is_read && <span className="notification-dot" aria-hidden="true" />}
                        </span>
                        <span className="notif-dropdown-item-message">{n.message}</span>
                        <span className="notif-dropdown-item-time">{formatRelative(n.created_at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <button type="button" className="notif-dropdown-footer" onClick={handleViewAll}>
                View all notifications
              </button>
            </div>
          )}
        </div>
      </div>

      <nav className="app-sidebar-nav" aria-label="Primary">
        {NAV_ITEMS.filter((item) => item.key !== 'settings' || user?.role === 'admin').map((item) => (
          <button
            key={item.key}
            type="button"
            className={`app-sidebar-link${activeView === item.key ? ' app-sidebar-link--active' : ''}`}
            onClick={() => onNavigate(item.key)}
          >
            {item.label}
            {item.key === 'notifications' && unreadCount > 0 && (
              <span className="app-sidebar-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
            )}
          </button>
        ))}
      </nav>

      <div className="app-sidebar-footer">
        <BackendStatusBadge />

        <div className="app-sidebar-user">
          <span className="app-sidebar-avatar">{initials(user?.name)}</span>
          <div className="app-sidebar-user-info">
            <span className="app-sidebar-user-name">{user?.name}</span>
            <span className="app-sidebar-user-role">{user?.role}</span>
          </div>
        </div>

        <button type="button" className="app-sidebar-logout" onClick={onLogout}>
          Log out
        </button>
      </div>
    </aside>
  )
}
