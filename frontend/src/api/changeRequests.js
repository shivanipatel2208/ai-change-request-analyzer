import { apiRequest } from './client'

export function createChangeRequest(payload, token) {
  return apiRequest('/api/change-requests', { method: 'POST', body: payload, token })
}

export function listChangeRequests(token, params = {}) {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  if (params.status) query.set('status', params.status)
  if (params.priority) query.set('priority', params.priority)
  if (params.assignedToMe) query.set('assigned_to_me', 'true')
  if (params.sort) query.set('sort', params.sort)
  if (params.limit != null) query.set('limit', params.limit)
  if (params.offset != null) query.set('offset', params.offset)
  const qs = query.toString()
  return apiRequest(`/api/change-requests${qs ? `?${qs}` : ''}`, { token })
}

export function getChangeRequest(id, token) {
  return apiRequest(`/api/change-requests/${id}`, { token })
}

// --- Module 12 Phase 2: editing, versioning, audit history ---------------

export function updateChangeRequest(id, payload, token) {
  return apiRequest(`/api/change-requests/${id}`, { method: 'PUT', body: payload, token })
}

export function getChangeRequestHistory(id, token) {
  return apiRequest(`/api/change-requests/${id}/history`, { token })
}

export function getChangeRequestVersions(id, token) {
  return apiRequest(`/api/change-requests/${id}/versions`, { token })
}

export function getChangeRequestVersion(id, versionNumber, token) {
  return apiRequest(`/api/change-requests/${id}/versions/${versionNumber}`, { token })
}

export function compareChangeRequestVersions(id, fromVersion, toVersion, token) {
  const query = new URLSearchParams({ from: fromVersion, to: toVersion })
  return apiRequest(`/api/change-requests/${id}/compare?${query.toString()}`, { token })
}

// --- Module 12 Phase 3: status workflow + assignments ---------------------

export function changeChangeRequestStatus(id, payload, token) {
  return apiRequest(`/api/change-requests/${id}/status`, { method: 'PUT', body: payload, token })
}

export function listChangeRequestAssignments(id, token) {
  return apiRequest(`/api/change-requests/${id}/assignments`, { token })
}

export function createChangeRequestAssignment(id, payload, token) {
  return apiRequest(`/api/change-requests/${id}/assignments`, { method: 'POST', body: payload, token })
}

export function deleteChangeRequestAssignment(id, assignmentId, token) {
  return apiRequest(`/api/change-requests/${id}/assignments/${assignmentId}`, { method: 'DELETE', token })
}
