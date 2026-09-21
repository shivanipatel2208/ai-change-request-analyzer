import './auth-layout.css'

export default function AuthLayout({ children }) {
  return (
    <div className="auth-shell">
      <div className="auth-brand-panel">
        <div className="auth-brand-content">
          <div className="auth-logo">
            <span className="auth-logo-mark">AI</span>
            <span className="auth-logo-word">Change Request Analyzer</span>
          </div>
          <p className="auth-tagline">Turn ambiguous change requests into engineering decisions.</p>
        </div>
      </div>
      <div className="auth-form-panel">
        <div className="auth-form-card">{children}</div>
      </div>
    </div>
  )
}
