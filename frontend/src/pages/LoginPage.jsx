import { useState } from 'react'
import AuthLayout from '../components/AuthLayout'
import { ApiError } from '../api/client'
import { useAuth } from '../context/AuthContext'

export default function LoginPage({ onSwitchToRegister }) {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email, password, rememberMe)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout>
      <h1 className="auth-title">Welcome back</h1>
      <p className="auth-subtitle">Sign in to continue to your workspace.</p>

      <form className="auth-form" onSubmit={handleSubmit}>
        <label className="auth-field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            placeholder="you@company.com"
          />
        </label>

        <label className="auth-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            placeholder="••••••••"
          />
        </label>

        <div className="auth-row">
          <label className="auth-checkbox">
            <input type="checkbox" checked={rememberMe} onChange={(e) => setRememberMe(e.target.checked)} />
            <span>Remember me</span>
          </label>
          {/* Module 23: removed a disabled "Forgot password? (Coming soon)"
              control that lived here - a dead, always-disabled link isn't
              worth showing on the very first screen of a demo. */}
        </div>

        {error && <p className="auth-error">{error}</p>}

        <button type="submit" className="auth-submit" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      <p className="auth-switch">
        Don&apos;t have an account?{' '}
        <button type="button" className="auth-link-button" onClick={onSwitchToRegister}>
          Create one
        </button>
      </p>
    </AuthLayout>
  )
}
