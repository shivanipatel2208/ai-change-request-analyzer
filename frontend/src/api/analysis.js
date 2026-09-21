import { ApiError, API_BASE_URL, apiRequest } from './client'

// Module 6: AI Analysis Engine endpoints.

export function analyzeChangeRequest(id, token) {
  return apiRequest(`/api/change-requests/${id}/analyze`, { method: 'POST', token })
}

export function getAnalysis(id, token) {
  return apiRequest(`/api/change-requests/${id}/analysis`, { token })
}

// Module 14 Phase 6: an authorized human's verdict on one extracted
// requirement (Confirmed / Needs Clarification) - never touches the AI's
// own certainty/confidence/evidence on that row.
export function reviewRequirement(id, requirementId, payload, token) {
  return apiRequest(`/api/change-requests/${id}/requirements/${requirementId}/review`, {
    method: 'PATCH',
    body: payload,
    token,
  })
}

// Supplies the missing information the AI itself asked for, right on the
// Missing Information tab - open to anyone who can comment on this change
// request, not gated to a reviewer role. Always marks the question
// resolved; can be called again on an already-answered question to
// correct it.
export function answerClarificationQuestion(id, questionId, answer, token) {
  return apiRequest(`/api/change-requests/${id}/clarification-questions/${questionId}/answer`, {
    method: 'PATCH',
    body: { answer },
    token,
  })
}

// Module 14 Phase 6: moves a Security finding's Status (the AI itself can
// only ever set Open/Not Applicable - a human sets Acknowledged/Resolved,
// or reopens/corrects it, here).
export function updateSecurityFindingStatus(id, findingId, payload, token) {
  return apiRequest(`/api/change-requests/${id}/security-findings/${findingId}/status`, {
    method: 'PATCH',
    body: payload,
    token,
  })
}

// Module 17 Phase 6: an authorized human correcting/refining one
// AI-generated test case in place. Every field is optional - only send
// what actually changed (see TestCaseUpdate's own docstring); the AI's
// prior wording is preserved on the audit trail, never overwritten.
export function updateTestCase(id, testCaseId, payload, token) {
  return apiRequest(`/api/change-requests/${id}/test-cases/${testCaseId}`, {
    method: 'PATCH',
    body: payload,
    token,
  })
}

// Module 17 Phase 6: same as updateTestCase above, for one implementation
// task.
export function updateImplementationTask(id, taskId, payload, token) {
  return apiRequest(`/api/change-requests/${id}/implementation-tasks/${taskId}`, {
    method: 'PATCH',
    body: payload,
    token,
  })
}

// Module 13 Phase 2: every analysis ever run for this change request,
// newest first - a lightweight summary (no requirements/risks/etc.), just
// enough to list past analyses and pick one to compare against the one
// immediately before it.
export function getAnalysisHistory(id, token) {
  return apiRequest(`/api/change-requests/${id}/analyses`, { token })
}

/** Module 13 Phase 2: a computed (not AI-written) diff between two
 * analyses of the same change request. Both `from` and `to` are optional -
 * passing only `to` compares it against whichever analysis ran
 * immediately before it. */
export function compareAnalyses(id, { from, to } = {}, token) {
  const params = new URLSearchParams()
  if (from != null) params.set('from', from)
  if (to != null) params.set('to', to)
  const qs = params.toString()
  return apiRequest(`/api/change-requests/${id}/analysis/compare${qs ? `?${qs}` : ''}`, { token })
}

/** Module 20: every version this change request has ever had, newest
 * first, each flagged with whether it's the current one and whether an
 * analysis was ever run against it specifically - what the "generate a
 * report for an earlier version" picker renders from. */
export function listReportableVersions(id, token) {
  return apiRequest(`/api/change-requests/${id}/report/versions`, { token })
}

/** Module 11 (made version-aware by Module 20): fetches the PDF report and
 * triggers a browser download. Not built on apiRequest() - that helper
 * only understands JSON bodies, and this response is a binary PDF (or, on
 * failure, a JSON error body - handled the same way apiRequest reports
 * errors, for a consistent message either way).
 *
 * `version` is optional - omit it for "the current version's report" (which
 * now 409s, rather than downloading something misleading, if the CR has
 * been edited since its last analysis - see the ApiError's `.detail` on
 * that response: {message, cr_version, last_analyzed_version,
 * can_reanalyze}); pass a specific version number to explicitly generate a
 * historical report for that version instead. */
export async function downloadReport(id, token, version) {
  const qs = version != null ? `?version=${encodeURIComponent(version)}` : ''
  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/change-requests/${id}/report${qs}`, {
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
        : detail?.message || `Report generation failed with status ${response.status}`
    throw new ApiError(message, response.status, detail)
  }

  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : `CR-${String(id).padStart(4, '0')}-analysis-report.pdf`

  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
