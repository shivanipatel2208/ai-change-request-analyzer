export default function EmptyState({ onCreateClick }) {
  return (
    <div className="dashboard-empty">
      <div className="dashboard-empty-icon" aria-hidden="true">
        +
      </div>
      <h2 className="dashboard-empty-title">Create your first change request.</h2>
      <p className="dashboard-empty-subtitle">
        Once you submit a change request, its metrics, risk profile, and status will show up here.
      </p>
      <button type="button" className="dashboard-empty-cta" onClick={onCreateClick}>
        + New Change Request
      </button>
    </div>
  )
}
