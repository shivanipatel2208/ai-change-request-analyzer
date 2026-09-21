import '../styles/dashboard.css'

/** Placeholder for nav items outside this module's scope (Change Requests,
 * New Analysis, Knowledge Base, Repository, Reports, Settings). Keeps the
 * full navigation feeling real instead of dead links, without building any
 * of those pages out yet - they're later modules. */
export default function ComingSoonPage({ label }) {
  return (
    <div className="dashboard-shell">
      <div className="dashboard-empty">
        <h2 className="dashboard-empty-title">{label}</h2>
        <p className="dashboard-empty-subtitle">This part of the app is built in a later module.</p>
      </div>
    </div>
  )
}
