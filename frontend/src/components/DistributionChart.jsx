/** Simple horizontal bar-list chart, used for both the risk overview and the
 * change-category overview. No charting library - just proportional CSS bar
 * widths - so there's no extra npm install for this module. `data` is an
 * ordered array of { label, count, color? }; bars are sized relative to the
 * largest count so differences stay readable even with few data points. */
export default function DistributionChart({ title, data, emptyLabel }) {
  const total = data.reduce((sum, row) => sum + row.count, 0)
  const max = Math.max(1, ...data.map((row) => row.count))

  return (
    <div className="chart-card">
      <h2 className="chart-card-title">{title}</h2>
      {total === 0 ? (
        <p className="chart-empty">{emptyLabel}</p>
      ) : (
        <ul className="bar-list">
          {data.map((row) => (
            <li key={row.label} className="bar-row">
              <span className="bar-row-label">{row.label}</span>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{
                    width: `${Math.round((row.count / max) * 100)}%`,
                    background: row.color || '#4338ca',
                  }}
                />
              </div>
              <span className="bar-row-count">{row.count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
