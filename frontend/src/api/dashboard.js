import { apiRequest } from './client'

export function getDashboardSummary(token) {
  return apiRequest('/dashboard/summary', { token })
}

// Clicking a dashboard tile: the change requests actually counted for that
// tile (see backend/app/api/dashboard.py's own drill-down endpoint - same
// classification the tile's own number comes from, never a second count).
// `options` mirrors the backend's own query params - dateFrom/dateTo filter
// by the change request's created date, page/pageSize paginate (pageSize is
// capped server-side at 10, matching the popup's rows-per-page dropdown).
export function getDashboardDrillDown(metric, token, options = {}) {
  const { dateFrom, dateTo, page, pageSize } = options
  const params = new URLSearchParams({ metric })
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  if (page) params.set('page', String(page))
  if (pageSize) params.set('page_size', String(pageSize))
  return apiRequest(`/dashboard/drill-down?${params.toString()}`, { token })
}
