const STATUS_LABELS = {
  pending_analysis: 'Pending Analysis',
  draft: 'Draft',
  submitted: 'Submitted',
  in_review: 'In Review',
  approved: 'Approved',
  rejected: 'Rejected',
  implemented: 'Implemented',
}

const STATUS_CLASS = {
  pending_analysis: 'badge--indigo',
  draft: 'badge--gray',
  submitted: 'badge--blue',
  in_review: 'badge--purple',
  approved: 'badge--green',
  rejected: 'badge--red',
  implemented: 'badge--teal',
}

const RISK_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
}

const RISK_CLASS = {
  low: 'badge--green',
  medium: 'badge--amber',
  high: 'badge--orange',
  critical: 'badge--red',
}

function formatDate(isoString) {
  try {
    return new Date(isoString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return isoString
  }
}

function TableBody({ items, emptyMessage, onRowClick }) {
  if (items.length === 0) {
    return <p className="chart-empty">{emptyMessage}</p>
  }
  return (
    <div className="table-scroll">
      <table className="requests-table">
        <thead>
          <tr>
            <th>Request ID</th>
            <th>Title</th>
            <th>Category</th>
            <th>Risk</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.id}
              className={onRowClick ? 'cr-list-row' : undefined}
              onClick={onRowClick ? () => onRowClick(item.id) : undefined}
            >
              <td className="requests-table-id">#{item.id}</td>
              <td className="requests-table-title">{item.title}</td>
              <td>{item.category || <span className="table-muted">Not analyzed</span>}</td>
              <td>
                {item.risk ? (
                  <span className={`badge ${RISK_CLASS[item.risk] || 'badge--gray'}`}>
                    {RISK_LABELS[item.risk] || item.risk}
                  </span>
                ) : (
                  <span className="table-muted">—</span>
                )}
              </td>
              <td>
                <span className={`badge ${STATUS_CLASS[item.status] || 'badge--gray'}`}>
                  {STATUS_LABELS[item.status] || item.status}
                </span>
              </td>
              <td className="table-muted">{formatDate(item.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** A simple change-request table: id/title/category/risk/status/created,
 * everything the dashboard summary's own RecentChangeRequestItem rows
 * already carry. Used both for the dashboard's "Recent Change Requests"
 * list (unchanged - no props besides `items` passed there) and, since the
 * shape is identical, inside the dashboard tile popup, rather than building
 * a second near-duplicate table component.
 *
 * `bare` skips the surrounding card and heading entirely - used inside
 * Modal, which already provides its own title/border/background, so
 * nesting a second bordered card inside it would just double the framing. */
export default function RecentRequestsTable({
  items,
  title = 'Recent Change Requests',
  emptyMessage = 'No change requests to show here.',
  onRowClick,
  actions,
  bare = false,
}) {
  if (bare) {
    return <TableBody items={items} emptyMessage={emptyMessage} onRowClick={onRowClick} />
  }

  return (
    <div className="table-card">
      <div className="table-card-header">
        <h2 className="chart-card-title">{title}</h2>
        {actions}
      </div>
      <TableBody items={items} emptyMessage={emptyMessage} onRowClick={onRowClick} />
    </div>
  )
}
