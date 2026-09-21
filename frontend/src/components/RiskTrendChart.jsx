/** Module 19 Phase 6 (Engineering Change Analytics): a monthly risk-mix
 * trend, hand-rolled the same way DistributionChart.jsx is - proportional
 * CSS bar widths, no charting library. Each row is one calendar month; the
 * single bar is split into 4 stacked segments (low/medium/high/critical)
 * sized relative to that month's own total, so the chart reads as "what
 * fraction of that month's analyzed change requests fell into each risk
 * bucket" rather than raw counts across very different totals. */
const SEGMENTS = [
  { key: 'low', label: 'Low', color: '#12b76a' },
  { key: 'medium', label: 'Medium', color: '#f79009' },
  { key: 'high', label: 'High', color: '#f04438' },
  { key: 'critical', label: 'Critical', color: '#b42318' },
]

export default function RiskTrendChart({ data, emptyLabel }) {
  return (
    <div className="chart-card">
      <h2 className="chart-card-title">Risk Distribution Over Time</h2>
      {!data || data.length === 0 ? (
        <p className="chart-empty">{emptyLabel}</p>
      ) : (
        <>
          <ul className="trend-list">
            {data.map((point) => {
              const total = SEGMENTS.reduce((sum, seg) => sum + (point[seg.key] || 0), 0)
              return (
                <li key={point.period} className="trend-row">
                  <span className="trend-row-label">{point.period}</span>
                  <div className="trend-bar-track">
                    {total === 0 ? null : (
                      SEGMENTS.map((seg) => {
                        const count = point[seg.key] || 0
                        if (count === 0) return null
                        return (
                          <div
                            key={seg.key}
                            className="trend-bar-segment"
                            style={{ width: `${(count / total) * 100}%`, background: seg.color }}
                            title={`${seg.label}: ${count}`}
                          />
                        )
                      })
                    )}
                  </div>
                  <span className="trend-row-count">{total}</span>
                </li>
              )
            })}
          </ul>
          <div className="trend-legend">
            {SEGMENTS.map((seg) => (
              <span key={seg.key} className="trend-legend-item">
                <span className="trend-legend-swatch" style={{ background: seg.color }} />
                {seg.label}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
