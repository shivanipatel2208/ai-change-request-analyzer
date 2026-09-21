import { apiRequest } from './client'

// Module 19 (Engineering Change Analytics): every endpoint here shares the
// same filter shape (spec section 8) - see buildQuery() below - so calling
// all 6 with the same `filters` object always describes the same slice of
// the data, no matter which section of the dashboard is asking.

/** Turns the page's one shared filter state into a query string every
 * analytics endpoint accepts identically. Keys are omitted entirely when
 * empty/undefined rather than sent as blank strings - the backend treats a
 * missing filter as "no restriction", never as "match nothing". */
function buildQuery(filters = {}) {
  const params = new URLSearchParams()
  if (filters.dateFrom) params.set('date_from', filters.dateFrom)
  if (filters.dateTo) params.set('date_to', filters.dateTo)
  if (filters.status) params.set('status', filters.status)
  if (filters.priority) params.set('priority', filters.priority)
  if (filters.risk) params.set('risk', filters.risk)
  if (filters.category) params.set('category', filters.category)
  if (filters.ownerId) params.set('owner_id', filters.ownerId)
  const query = params.toString()
  return query ? `?${query}` : ''
}

export function getExecutiveAndWorkflowMetrics(token, filters) {
  return apiRequest(`/api/analytics/executive${buildQuery(filters)}`, { token })
}

export function getRiskAnalytics(token, filters) {
  return apiRequest(`/api/analytics/risk${buildQuery(filters)}`, { token })
}

export function getApprovalBottlenecks(token, filters) {
  return apiRequest(`/api/analytics/approval-bottlenecks${buildQuery(filters)}`, { token })
}

export function getChangeAnalytics(token, filters) {
  return apiRequest(`/api/analytics/change${buildQuery(filters)}`, { token })
}

export function getWorkloadAnalytics(token, filters) {
  return apiRequest(`/api/analytics/workload${buildQuery(filters)}`, { token })
}

export function getAIAnalytics(token, filters) {
  return apiRequest(`/api/analytics/ai${buildQuery(filters)}`, { token })
}
