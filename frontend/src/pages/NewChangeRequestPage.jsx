import { useState } from 'react'
import { analyzeChangeRequest } from '../api/analysis'
import { createChangeRequest } from '../api/changeRequests'
import { useAuth } from '../context/AuthContext'
import '../styles/change-request-form.css'

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

function emptyForm(defaultRequestedBy) {
  return {
    title: '',
    description: '',
    businessObjective: '',
    priority: 'medium',
    requestedBy: defaultRequestedBy || '',
    targetSystem: '',
    desiredDeadline: '',
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

/** The Module 4 workflow: a form that creates a ChangeRequest (status
 * "pending_analysis") and, on success, a confirmation screen with an
 * "Analyze Change" button. Clicking it just explains AI analysis isn't
 * built yet (later module) - it deliberately does nothing else here. */
export default function NewChangeRequestPage({ onNavigate }) {
  const { user, token } = useAuth()
  const [form, setForm] = useState(() => emptyForm(user?.name))
  const [fieldErrors, setFieldErrors] = useState({})
  const [submitError, setSubmitError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [created, setCreated] = useState(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState(null)
  const [analyzeDone, setAnalyzeDone] = useState(false)

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
    if (Object.keys(errors).length > 0) {
      return
    }

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
      }
      const response = await createChangeRequest(payload, token)
      setCreated(response)
    } catch (err) {
      setSubmitError(err.message || 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  function handleCreateAnother() {
    setCreated(null)
    setAnalyzing(false)
    setAnalyzeError(null)
    setAnalyzeDone(false)
    setFieldErrors({})
    setSubmitError(null)
    setForm(emptyForm(user?.name))
  }

  async function handleAnalyze() {
    setAnalyzing(true)
    setAnalyzeError(null)
    try {
      await analyzeChangeRequest(created.id, token)
      setAnalyzeDone(true)
    } catch (err) {
      setAnalyzeError(err.message || 'Analysis failed. Please try again.')
    } finally {
      setAnalyzing(false)
    }
  }

  if (created) {
    return (
      <div className="cr-form-shell">
        <div className="cr-success">
          <div className="cr-success-icon" aria-hidden="true">
            ✓
          </div>
          <h1 className="cr-success-title">Change request created successfully.</h1>
          <p className="cr-success-subtitle">
            <strong>
              #{created.id} — {created.title}
            </strong>{' '}
            has been saved and is now <em>Pending Analysis</em>.
          </p>

          <div className="cr-success-actions">
            {!analyzeDone && (
              <button
                type="button"
                className="cr-btn cr-btn--primary"
                onClick={handleAnalyze}
                disabled={analyzing}
              >
                {analyzing ? 'Analyzing… this can take up to a minute' : 'Analyze Change'}
              </button>
            )}
            {analyzeDone && (
              <button
                type="button"
                className="cr-btn cr-btn--primary"
                onClick={() => onNavigate('change-requests')}
              >
                View Analysis
              </button>
            )}
            <button type="button" className="cr-btn cr-btn--secondary" onClick={handleCreateAnother}>
              Create another request
            </button>
            <button type="button" className="cr-btn cr-btn--ghost" onClick={() => onNavigate('dashboard')}>
              Back to Dashboard
            </button>
          </div>

          {analyzeError && <p className="cr-form-error">{analyzeError}</p>}
          {analyzeDone && (
            <p className="cr-analyze-notice">
              Analysis complete. Open this request from the Change Requests list to see the full results.
            </p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="cr-form-shell">
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        <button type="button" className="breadcrumb-link" onClick={() => onNavigate('dashboard')}>
          Dashboard
        </button>
        <span className="breadcrumb-separator">/</span>
        <span className="breadcrumb-current">New Change Request</span>
      </nav>

      <div className="cr-form-heading">
        <h1>New Change Request</h1>
        <p>Describe the change you need — it&apos;ll be saved as Pending Analysis until it&apos;s reviewed.</p>
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
              placeholder="e.g. Allow OTP login for customers"
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
            <p className="cr-field-example">
              e.g. &quot;Allow customers to log in using OTP sent to their registered mobile number.&quot;
            </p>
            <textarea
              id="cr-description"
              rows={5}
              value={form.description}
              maxLength={DESCRIPTION_MAX}
              onChange={(e) => updateField('description', e.target.value)}
              placeholder="Describe the requested software change in natural language..."
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
              placeholder="Why does this change matter? e.g. Reduce password-reset support tickets."
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
                placeholder="e.g. Jamie Rivera"
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
                placeholder="e.g. POS Backend"
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
              min={todayIso()}
              onChange={(e) => updateField('desiredDeadline', e.target.value)}
              aria-invalid={Boolean(fieldErrors.desiredDeadline)}
            />
            {fieldErrors.desiredDeadline && (
              <span className="cr-field-error">{fieldErrors.desiredDeadline}</span>
            )}
          </div>
        </section>

        <div className="cr-form-actions">
          <button
            type="button"
            className="cr-btn cr-btn--ghost"
            onClick={() => onNavigate('dashboard')}
            disabled={submitting}
          >
            Cancel
          </button>
          <button type="submit" className="cr-btn cr-btn--primary" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create Change Request'}
          </button>
        </div>
      </form>
    </div>
  )
}
