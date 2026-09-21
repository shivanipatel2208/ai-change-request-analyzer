// Talk to the backend directly on :8000 (override with VITE_API_BASE_URL).
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export class ApiError extends Error {
  // `detail` (Module 20) carries the backend's raw `detail` value whenever
  // it's more than a plain string - e.g. the version-mismatch report error,
  // which is a {message, cr_version, last_analyzed_version, can_reanalyze}
  // object - so a caller that needs those specific fields doesn't have to
  // re-parse `message` back out of a sentence. Most callers still just
  // read `.message` and never look at `.detail` at all.
  constructor(message, status, detail) {
    super(typeof message === 'string' ? message : 'Request failed.')
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Thin fetch wrapper: JSON in, JSON out, attaches the bearer token when given, and
 * turns a non-2xx response into a thrown ApiError with the backend's error message. */
export async function apiRequest(path, { method = 'GET', body, token } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError('Could not reach the backend. Is it running?', 0)
  }

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await response.json() : null

  if (!response.ok) {
    const detail = data?.detail
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join(' ')
      : typeof detail === 'string'
        ? detail
        : detail?.message || `Request failed with status ${response.status}`
    throw new ApiError(message, response.status, detail)
  }

  return data
}
