import { useEffect, useState } from 'react'
import { API_BASE_URL } from '../api/client'

/** Small connectivity indicator - carries forward the health-check the
 * project started with, now as a badge instead of the whole page. */
export default function BackendStatusBadge() {
  const [status, setStatus] = useState('checking') // 'checking' | 'ok' | 'error'

  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`status ${res.status}`))))
      .then(() => setStatus('ok'))
      .catch(() => setStatus('error'))
  }, [])

  const label =
    status === 'ok' ? 'Backend connected' : status === 'error' ? 'Backend unreachable' : 'Checking backend…'

  return (
    <span className={`status-badge status-badge--${status}`}>
      <span className="status-dot" />
      {label}
    </span>
  )
}
