import { ApiError, API_BASE_URL, apiRequest } from './client'

// Module 24: Reports section. Every "report" here is a computed view over
// data that already exists elsewhere (see backend/app/services/
// report_registry.py) - there's no separate reports database to talk to,
// and no "generate" call either: a report is recorded automatically the
// moment an analysis completes (see app/api/change_requests.py::
// analyze_change_request on the backend), so this file only ever reads.

export function listReports(token, params = {}) {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  if (params.status) query.set('status', params.status)
  if (params.risk) query.set('risk', params.risk)
  if (params.version != null && params.version !== '') query.set('version', params.version)
  if (params.generatedBy != null && params.generatedBy !== '') query.set('generated_by', params.generatedBy)
  if (params.dateFrom) query.set('date_from', params.dateFrom)
  if (params.dateTo) query.set('date_to', params.dateTo)
  const qs = query.toString()
  return apiRequest(`/api/reports${qs ? `?${qs}` : ''}`, { token })
}

export function getReportStats(token) {
  return apiRequest('/api/reports/stats', { token })
}

export function getReport(reportId, token) {
  return apiRequest(`/api/reports/${reportId}`, { token })
}

export function listReportsForChangeRequest(changeRequestId, token) {
  return apiRequest(`/api/change-requests/${changeRequestId}/reports`, { token })
}

/** Fetches the PDF for an already-generated report row and triggers a
 * browser download - mirrors app/api/analysis.js::downloadReport exactly
 * (not built on apiRequest(), since this response is binary, not JSON). */
export async function downloadReportById(reportId, token, fallbackFilename) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/reports/${reportId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
  } catch {
    throw new ApiError('Could not reach the backend. Is it running?', 0)
  }

  if (!response.ok) {
    let detail
    try {
      detail = (await response.json())?.detail
    } catch {
      detail = null
    }
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join(' ')
      : typeof detail === 'string'
        ? detail
        : detail?.message || `Report download failed with status ${response.status}`
    throw new ApiError(message, response.status, detail)
  }

  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : fallbackFilename || `report-${reportId}.pdf`

  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
