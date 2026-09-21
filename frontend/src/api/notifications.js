import { apiRequest } from './client'

// Module 12 Phase 5: a user's own in-app notification inbox. See
// backend/app/api/notifications.py.

export function listNotifications(token, { unreadOnly = false, limit } = {}) {
  const params = new URLSearchParams()
  if (unreadOnly) params.set('unread_only', 'true')
  if (limit) params.set('limit', String(limit))
  const query = params.toString()
  return apiRequest(`/api/notifications${query ? `?${query}` : ''}`, { token })
}

export function getUnreadNotificationCount(token) {
  return apiRequest('/api/notifications/unread-count', { token })
}

export function markNotificationRead(notificationId, token) {
  return apiRequest(`/api/notifications/${notificationId}/read`, { method: 'PUT', token })
}

export function markAllNotificationsRead(token) {
  return apiRequest('/api/notifications/read-all', { method: 'PUT', token })
}
