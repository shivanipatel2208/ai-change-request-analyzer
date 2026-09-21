/** One metrics card on the dashboard. `tone` only changes the accent color
 * of the value - kept subtle on purpose (this is an internal engineering
 * tool, not a marketing page).
 *
 * `onClick` is optional: cards used purely for display (e.g. the Reports
 * page's own MetricCard-based stats, which have nothing sensible to drill
 * into) render exactly as before. Passing it turns the whole card into a
 * button that shows which change requests were actually counted for it -
 * `active` just highlights whichever card's drill-down is currently open. */
export default function MetricCard({ label, value, tone = 'default', onClick, active = false }) {
  const className = `metric-card${onClick ? ' metric-card--clickable' : ''}${active ? ' metric-card--active' : ''}`

  if (!onClick) {
    return (
      <div className={className}>
        <span className="metric-card-label">{label}</span>
        <span className={`metric-card-value metric-card-value--${tone}`}>{value}</span>
      </div>
    )
  }

  return (
    <button type="button" className={className} onClick={onClick} aria-pressed={active}>
      <span className="metric-card-label">{label}</span>
      <span className={`metric-card-value metric-card-value--${tone}`}>{value}</span>
    </button>
  )
}
