import { apiRequest } from './client'

// Module 12 Phase 5: the discussion thread on a change request - a flat
// two-level thread (top-level comments plus their direct replies, spec:
// "reply where practical"). See backend/app/api/change_requests.py's
// "comments" section.

export function listComments(id, token) {
  return apiRequest(`/api/change-requests/${id}/comments`, { token })
}

export function createComment(id, payload, token) {
  return apiRequest(`/api/change-requests/${id}/comments`, { method: 'POST', body: payload, token })
}

export function resolveComment(id, commentId, resolved, token) {
  return apiRequest(`/api/change-requests/${id}/comments/${commentId}/resolve`, {
    method: 'PUT',
    body: { resolved },
    token,
  })
}

export function deleteComment(id, commentId, token) {
  return apiRequest(`/api/change-requests/${id}/comments/${commentId}`, { method: 'DELETE', token })
}
