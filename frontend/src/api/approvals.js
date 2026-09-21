import { apiRequest } from './client'

// Module 12 Phase 4: approvals - tagging a real person for a specific kind
// of sign-off, and that person's own Approve/Reject/Request Changes
// response. See backend/app/api/change_requests.py's "approvals" section.

export function listApprovals(id, token) {
  return apiRequest(`/api/change-requests/${id}/approvals`, { token })
}

export function getRecommendedApprovals(id, token) {
  return apiRequest(`/api/change-requests/${id}/approvals/recommended`, { token })
}

export function createApprovalRequest(id, payload, token) {
  return apiRequest(`/api/change-requests/${id}/approvals`, { method: 'POST', body: payload, token })
}

export function respondToApproval(id, approvalId, payload, token) {
  return apiRequest(`/api/change-requests/${id}/approvals/${approvalId}/respond`, {
    method: 'POST',
    body: payload,
    token,
  })
}

export function cancelApprovalRequest(id, approvalId, token) {
  return apiRequest(`/api/change-requests/${id}/approvals/${approvalId}`, { method: 'DELETE', token })
}
