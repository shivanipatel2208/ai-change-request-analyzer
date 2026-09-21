import { apiRequest } from './client'

// Module 15 (Repository Intelligence): scanning "the repository" itself
// (not scoped to any one change request - see
// backend/app/models/repository_scan.py's docstring) via
// backend/app/api/repository.py, and matching one change request's
// current analysis against whatever the most recent scan indexed via the
// repository-findings routes in backend/app/api/change_requests.py.
// Mirrors the shape of every other endpoint module here - thin
// apiRequest wrappers, no extra logic.

/** Scans the app's configured repository root and records a new
 * RepositoryScan - never touches or deletes any prior scan. */
export function triggerRepositoryScan(token) {
  return apiRequest('/api/repository/scan', { method: 'POST', token })
}

/** The most recent repository scan, with its full indexed-file list.
 * 404s (as an ApiError with status 404) if no scan has ever been run -
 * callers that treat "no scan yet" as a normal, not-yet-happened state
 * should catch that rather than surface it as a page-level error. */
export function getLatestRepositoryScan(token) {
  return apiRequest('/api/repository/latest', { token })
}

/** Matches this change request's current analysis against the most recent
 * repository scan and persists the result - "which source files may
 * actually be affected by this change request?" Re-running this replaces
 * this exact (change request, analysis, scan) triple's prior findings
 * rather than piling up duplicates. */
export function triggerRepositoryMatch(id, token) {
  return apiRequest(`/api/change-requests/${id}/repository-findings`, { method: 'POST', token })
}

/** Whatever repository findings already exist for this change request's
 * current analysis - empty (never 404) if a match hasn't been run yet.
 * Each finding reports is_outdated/outdated_reasons: whether the change
 * request has since been edited, a newer analysis has run, or a newer
 * repository scan is available. */
export function getRepositoryFindings(id, token) {
  return apiRequest(`/api/change-requests/${id}/repository-findings`, { token })
}
