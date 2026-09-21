import { useEffect } from 'react'
import '../styles/modal.css'

/** A minimal, reusable popup dialog - the first one in this app, added for
 * the dashboard's clickable tiles (spec: "instead I want a popup"). Click
 * on the dimmed backdrop, the × button, or press Escape to close; clicking
 * anywhere inside the dialog itself never closes it. `actions`, if given,
 * renders in a footer strip below the body (e.g. pagination controls). */
export default function Modal({ title, onClose, children, actions }) {
  useEffect(() => {
    function handleKeyDown(event) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {actions && <div className="modal-footer">{actions}</div>}
      </div>
    </div>
  )
}
