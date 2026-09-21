import { apiRequest } from './client'

// Module 18 Phase 3/4 (Notifications, My Work & Personal Engineering
// Queue): "what's on my plate right now" - see backend/app/api/my_work.py.
// Every one of these is scoped to the signed-in user automatically (the
// backend reads it off the auth token) - there's no user id parameter
// anywhere here.

export function getMyWorkSummary(token) {
  return apiRequest('/api/my-work/summary', { token })
}

export function getMyChangeRequests(token) {
  return apiRequest('/api/my-work/change-requests', { token })
}

export function getMyApprovals(token, { all = false } = {}) {
  const query = all ? '?status=all' : ''
  return apiRequest(`/api/my-work/approvals${query}`, { token })
}

export function getMyReviews(token) {
  return apiRequest('/api/my-work/reviews', { token })
}

export function getMyAssignments(token) {
  return apiRequest('/api/my-work/assignments', { token })
}

export function getChangesRequestedFromMe(token) {
  return apiRequest('/api/my-work/changes-requested', { token })
}

export function getMyMentions(token) {
  return apiRequest('/api/my-work/mentions', { token })
}

export function getOverdueItems(token) {
  return apiRequest('/api/my-work/overdue', { token })
}
