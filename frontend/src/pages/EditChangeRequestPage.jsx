import { useEffect, useState } from 'react'
import { getChangeRequest, updateChangeRequest } from '../api/changeRequests'
import { useAuth } from '../context/AuthContext'
import '../styles/change-request-form.css'
import '../styles/workflow.css'

const PRIORITY_OPTIONS = [
  { value: 'low', label: 'Low', color: '#12b76a' },
  { value: 'medium', label: 'Medium', color: '#f79009' },
  { value: 'high', label: 'High', color: '#f04438' },
  { value: 'critical', label: 'Critical', color: '#b42318' },
]

const TARGET_SYSTEM_SUGGESTIONS = [
  'POS Backend',
  'POS Frontend',
  'Mobile App',
  'Admin Panel',
  'Payment Gateway',
  'Inventory System',
  'Reporting Dashboard',
  'API Gateway',
  'Database',
  'Infrastructure',
]

const DESCRIPTION_MIN = 20
const DESCRIPTION_MAX = 4000
const TITLE_MAX = 255

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function formFromDetail(detail) {
  return {
    title: detail.title || '',
    description: detail.description || '',
    businessObjective: detail.business_objective || '',
    priority: detail.priority || 'medium',
    requestedBy: detail.requested_by || '',
    targetSystem: detail.target_system || '',
    desiredDeadline: detail.desired_deadline || '',
    businessImpact: detail.business_impact || '',
    technicalImpact: detail.technical_impact || '',
    customerImpact: detail.customer_impact || '',
    environment: detail.environment || '',
    dependenciesNote: detail.dependencies_note || '',
    complianceRequirements: detail.compliance_requirements || '',
    tags: (detail.tags || []).join(', '),
  }
}

function validate(form) {
  const errors = {}
  const title = form.title.trim()
  const description = form.description.trim()
  const requestedBy = form.requestedBy.trim()
  const targetSystem = form.targetSystem.trim()

  if (!title) errors.title = 'Title is required.'
  else if (title.length < 5) errors.title = 'Title must be at least 5 characters.'
  else if (title.length > TITLE_MAX) errors.title = `Title must be ${TITLE_MAX} characters or fewer.`

  if (!description) errors.description = 'Description is required.'
  else if (description.length < DESCRIPTION_MIN)
    errors.description = `Add a bit more detail - at least ${DESCRIPTION_MIN} characters.`
  else if (description.length > DESCRIPTION_MAX)
    errors.description = `Description must be ${DESCRIPTION_MAX} characters or fewer.`

  if (!requestedBy) errors.requestedBy = 'Requested By is required.'
  if (!targetSystem) errors.targetSystem = 'Target System is required.'

  if (form.desiredDeadline && form.desiredDeadline < todayIso()) {
    errors.desiredDeadline = "Deadline can't be in the past."
  }

  return errors
}

function parseTags(raw) {
  const values = raw
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean)
  return values.length > 0 ? values : null
}

/** Module 12 Phase 2: the Edit form. Prefills from GET .../{id}, submits a
 * full PUT (the backend only ever records fields that actually changed -
 * see app/services/versioning.py - so sending back untouched values is a
 * harmless no-op), then shows the field-by-field "here's what changed"
 * confirmation the spec asks for before returning to the detail view. */
export default function EditChangeRequestPage({ id, onCancel, onSaved }) {
  const { token } = useAuth()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [form, setForm] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [submitError, setSubmitError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null) // the PUT response, once saved

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    getChangeRequest(id, token)
      .then((detail) => {
        if (!cancelled) setForm(formFromDetail(detail))
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.message || 'Could not load this change request.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, token])

  function updateField(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }))
    if (fieldErrors[field]) {
      setFieldErrors((prev) => {
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    const errors = validate(form)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      const payload = {
        title: form.title.trim(),
        description: form.description.trim(),
        business_objective: form.businessObjective.trim() || null,
        priority: form.priority,
        requested_by: form.requestedBy.trim(),
        target_system: form.targetSystem.trim(),
        desired_deadline: form.desiredDeadline || null,
        business_impact: form.businessImpact.trim() || null,
        technical_impact: form.technicalImpact.trim() || null,
        customer_impact: form.customerImpact.trim() || null,
        environment: form.environment.trim() || null,
        dependencies_note: form.dependenciesNote.trim() || null,
        compliance_requirements: form.complianceRequirements.trim() || null,
        tags: parseTags(form.tags),
      }
      const response = await updateChangeRequest(id, payload, token)
      setResult(response)
    } catch (err) {
      setSubmitError(err.message || 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="cr-form-shell">
        <p className="cr-list-status-text">Loading change request…</p>
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="cr-form-shell">
        <p className="cr-list-status-text cr-list-status-text--error">{loadError}</p>
        <button type="button" className="cr-btn cr-btn--ghost" onClick={onCancel}>
          ← Back
        </button>
      </div>
    )
  }

  if (result) {
    const changed = result.changes.length > 0
    return (
      <div className="cr-form-shell">
        <div className="cr-success">
          <div className="cr-success-icon" aria-hidden="true">
            ✓
          </div>
          <h1 className="cr-success-title">{changed ? "Here's what changed" : 'No changes made'}</h1>
          {changed ? (
            <>
              <p className="cr-success-subtitle">
                Saved as <strong>Version {result.new_version}</strong>. The AI analysis (if any) is now marked
                outdated until this request is re-analyzed.
              </p>
              <ul className="edit-confirm-list">
                {result.changes.map((change) => (
                  <li key={change.field} className="edit-confirm-item">
                    <span className="edit-confirm-field">{change.label}</span>
                    <span className="edit-confirm-values">
                      {change.status === 'added' && (
                        <span className="to-value">{change.new_value}</span>
                      )}
                      {change.status === 'removed' && (
                        <span className="from-value">{change.old_value}</span>
                      )}
                      {change.status === 'changed' && (
                        <>
                          <span className="from-value">{change.old_value}</span>
                          {' → '}
                          <span className="to-value">{change.new_value}</span>
                        </>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="no-changes-note">The values you submitted matched what was already saved.</p>
          )}

          <div className="cr-success-actions">
            <button type="button" className="cr-btn cr-btn--primary" onClick={() => onSaved?.(id)}>
              Back to Change Request
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="cr-form-shell">
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        <button type="button" className="breadcrumb-link" onClick={onCancel}>
          #{id}
        </button>
        <span className="breadcrumb-separator">/</span>
        <span className="breadcrumb-current">Edit</span>
      </nav>

      <div className="cr-form-heading">
        <h1>Edit Change Request</h1>
        <p>Changes are versioned and recorded on the activity history - nothing is overwritten silently.</p>
      </div>

      <form className="cr-form" onSubmit={handleSubmit} noValidate>
        {submitError && <p className="cr-form-error">{submitError}</p>}

        <section className="cr-section">
          <h2 className="cr-section-title">Request Details</h2>

          <div className="cr-field">
            <label htmlFor="cr-title">Title</label>
            <input
              id="cr-title"
              type="text"
              value={form.title}
              maxLength={TITLE_MAX}
              onChange={(e) => updateField('title', e.target.value)}
              aria-invalid={Boolean(fieldErrors.title)}
            />
            <div className="cr-field-footer">
              {fieldErrors.title ? (
                <span className="cr-field-error">{fieldErrors.title}</span>
              ) : (
                <span className="cr-field-hint">A short, specific summary.</span>
              )}
              <span className="cr-char-count">
                {form.title.length}/{TITLE_MAX}
              </span>
            </div>
          </div>

          <div className="cr-field">
            <label htmlFor="cr-description">Description</label>
            <textarea
              id="cr-description"
              rows={5}
              value={form.description}
              maxLength={DESCRIPTION_MAX}
              onChange={(e) => updateField('description', e.target.value)}
              aria-invalid={Boolean(fieldErrors.description)}
            />
            <div className="cr-field-footer">
              {fieldErrors.description ? (
                <span className="cr-field-error">{fieldErrors.description}</span>
              ) : (
                <span className="cr-field-hint">Minimum {DESCRIPTION_MIN} characters.</span>
              )}
              <span className="cr-char-count">
                {form.description.length}/{DESCRIPTION_MAX}
              </span>
            </div>
          </div>

          <div className="cr-field">
            <label htmlFor="cr-objective">
              Business Objective <span className="cr-optional-tag">optional</span>
            </label>
            <textarea
              id="cr-objective"
              rows={2}
              value={form.businessObjective}
              onChange={(e) => updateField('businessObjective', e.target.value)}
            />
          </div>
        </section>

        <section className="cr-section">
          <h2 className="cr-section-title">Classification &amp; Ownership</h2>

          <div className="cr-field">
            <label>Priority</label>
            <div className="cr-priority-group" role="radiogroup" aria-label="Priority">
              {PRIORITY_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={form.priority === option.value}
                  className={`cr-priority-btn${
                    form.priority === option.value ? ' cr-priority-btn--active' : ''
                  }`}
                  style={form.priority === option.value ? { '--priority-color': option.color } : undefined}
                  onClick={() => updateField('priority', option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="cr-field-row">
            <div className="cr-field">
              <label htmlFor="cr-requested-by">Requested By</label>
              <input
                id="cr-requested-by"
                type="text"
                value={form.requestedBy}
                maxLength={255}
                onChange={(e) => updateField('requestedBy', e.target.value)}
                aria-invalid={Boolean(fieldErrors.requestedBy)}
              />
              {fieldErrors.requestedBy && <span className="cr-field-error">{fieldErrors.requestedBy}</span>}
            </div>

            <div className="cr-field">
              <label htmlFor="cr-target-system">Target System</label>
              <input
                id="cr-target-system"
                type="text"
                list="cr-target-system-options"
                value={form.targetSystem}
                maxLength={255}
                onChange={(e) => updateField('targetSystem', e.target.value)}
                aria-invalid={Boolean(fieldErrors.targetSystem)}
              />
              <datalist id="cr-target-system-options">
                {TARGET_SYSTEM_SUGGESTIONS.map((suggestion) => (
                  <option key={suggestion} value={suggestion} />
                ))}
              </datalist>
              {fieldErrors.targetSystem && (
                <span className="cr-field-error">{fieldErrors.targetSystem}</span>
              )}
            </div>
          </div>

          <div className="cr-field">
            <label htmlFor="cr-deadline">
              Desired Deadline <span className="cr-optional-tag">optional</span>
            </label>
            <input
              id="cr-deadline"
              type="date"
              value={form.desiredDeadline}
              onChange={(e) => updateField('desiredDeadline', e.target.value)}
              aria-invalid={Boolean(fieldErrors.desiredDeadline)}
            />
            {fieldErrors.desiredDeadline && (
              <span className="cr-field-error">{fieldErrors.desiredDeadline}</span>
            )}
          </div>
        </section>

        <section className="cr-section">
          <h2 className="cr-section-title">Additional Details</h2>

          <div className="cr-field-row">
            <div className="cr-field">
              <label htmlFor="cr-business-impact">
                Business Impact <span className="cr-optional-tag">optional</span>
              </label>
              <textarea
                id="cr-business-impact"
                rows={2}
                value={form.businessImpact}
                onChange={(e) => updateField('businessImpact', e.target.value)}
              />
            </div>
            <div className="cr-field">
              <label htmlFor="cr-technical-impact">
                Technical Impact <span className="cr-optional-tag">optional</span>
              </label>
              <textarea
                id="cr-technical-impact"
                rows={2}
                value={form.technicalImpact}
                onChange={(e) => updateField('technicalImpact', e.target.value)}
              />
            </div>
          </div>

          <div className="cr-field-row">
            <div className="cr-field">
              <label htmlFor="cr-customer-impact">
                Customer Impact <span className="cr-optional-tag">optional</span>
              </label>
              <textarea
                id="cr-customer-impact"
                rows={2}
                value={form.customerImpact}
                onChange={(e) => updateField('customerImpact', e.target.value)}
              />
            </div>
            <div className="cr-field">
              <label htmlFor="cr-environment">
                Environment <span className="cr-optional-tag">optional</span>
              </label>
              <input
                id="cr-environment"
                type="text"
                value={form.environment}
                placeholder="e.g. Production"
                onChange={(e) => updateField('environment', e.target.value)}
              />
            </div>
          </div>

          <div className="cr-field">
            <label htmlFor="cr-dependencies">
              Dependencies <span className="cr-optional-tag">optional</span>
            </label>
            <textarea
              id="cr-dependencies"
              rows={2}
              value={form.dependenciesNote}
              onChange={(e) => updateField('dependenciesNote', e.target.value)}
            />
          </div>

          <div className="cr-field">
            <label htmlFor="cr-compliance">
              Compliance Requirements <span className="cr-optional-tag">optional</span>
            </label>
            <textarea
              id="cr-compliance"
              rows={2}
              value={form.complianceRequirements}
              onChange={(e) => updateField('complianceRequirements', e.target.value)}
            />
          </div>

          <div className="cr-field">
            <label htmlFor="cr-tags">
              Tags <span className="cr-optional-tag">optional, comma-separated</span>
            </label>
            <input
              id="cr-tags"
              type="text"
              value={form.tags}
              placeholder="e.g. mobile, auth, otp"
              onChange={(e) => updateField('tags', e.target.value)}
            />
          </div>
        </section>

        <div className="cr-form-actions">
          <button
            type="button"
            className="cr-btn cr-btn--ghost"
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </button>
          <button type="submit" className="cr-btn cr-btn--primary" disabled={submitting}>
            {submitting ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </form>
    </div>
  )
}
