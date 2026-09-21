import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  analyzeChangeRequest,
  answerClarificationQuestion,
  compareAnalyses,
  downloadReport,
  getAnalysis,
  getAnalysisHistory,
  listReportableVersions,
  reviewRequirement,
  updateImplementationTask,
  updateSecurityFindingStatus,
  updateTestCase,
} from '../api/analysis'
// Module 15 (Repository Intelligence).
import {
  getLatestRepositoryScan,
  getRepositoryFindings,
  triggerRepositoryMatch,
  triggerRepositoryScan,
} from '../api/repository'
// Module 14 Phase 1: reuses the exact same recommended-approvals endpoint
// ChangeRequestDetail.jsx already calls - this page just also displays it,
// rather than standing up a second "what approvals does this need" system.
import { getRecommendedApprovals } from '../api/approvals'
import { getChangeRequest } from '../api/changeRequests'
import DistributionChart from '../components/DistributionChart'
import ImpactGraph from '../components/ImpactGraph'
import { useAuth } from '../context/AuthContext'
import '../styles/dashboard.css'
import '../styles/change-request-form.css'
import '../styles/change-requests-list.css'
import '../styles/analysis-dashboard.css'
// Module 13 Phase 3/4/5: reuses the same outdated-banner / compare-table
// styles Module 12's CR-version-compare feature already defined, rather
// than re-declaring near-identical CSS a second time.
import '../styles/workflow.css'

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'requirements', label: 'Requirements' },
  { key: 'impact', label: 'Impact' },
  { key: 'repository', label: 'Repository' },
  { key: 'dependencies', label: 'Dependencies' },
  { key: 'risks', label: 'Risks' },
  { key: 'security', label: 'Security' },
  { key: 'effort', label: 'Complexity & Effort' },
  { key: 'missing', label: 'Missing Information' },
  { key: 'tests', label: 'Test Cases' },
  { key: 'plan', label: 'Implementation Plan' },
  { key: 'traceability', label: 'Traceability' },
  { key: 'history', label: 'History' },
]

const PRIORITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }
const PRIORITY_CLASS = {
  low: 'badge--green',
  medium: 'badge--amber',
  high: 'badge--orange',
  critical: 'badge--red',
}
const LEVEL_CLASS = {
  low: 'badge--green',
  medium: 'badge--amber',
  high: 'badge--orange',
  critical: 'badge--red',
  very_high: 'badge--red',
}
const PRIORITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 }

// Module 9: the risk-analysis engine's 8 categories (analysis_engine.py's
// CLASSIFICATION/RISK_CATEGORIES list) in a fixed display order, each with
// its own chart color. Any risk stored under a category outside this list
// (the app's older TECHNICAL/BUSINESS values, kept for backward
// compatibility) still counts - it's just grouped into "Other" rather than
// silently dropped.
const RISK_CATEGORY_ORDER = [
  'security',
  'data',
  'performance',
  'availability',
  'integration',
  'regression',
  'compliance',
  'operational',
]
const RISK_CATEGORY_COLORS = {
  security: '#b42318',
  data: '#175cd3',
  performance: '#7839ee',
  availability: '#0e7090',
  integration: '#dc6803',
  regression: '#c11574',
  compliance: '#3538cd',
  operational: '#667085',
  other: '#98a2b3',
}

const RECOMMENDATION_META = {
  approve: { emoji: '🟢', label: 'APPROVE', tone: 'success' },
  approve_with_conditions: { emoji: '🟡', label: 'APPROVE WITH CONDITIONS', tone: 'warning' },
  requires_clarification: { emoji: '🔴', label: 'REQUIRES CLARIFICATION', tone: 'danger' },
  needs_more_info: { emoji: '🟡', label: 'NEEDS MORE INFO', tone: 'warning' },
  reject: { emoji: '🔴', label: 'REJECT', tone: 'danger' },
}

// Module 13 Phase 1: Known/Inferred/Unknown - a separate "what kind of
// statement is this" tag from the AI, distinct from its numeric confidence
// (see backend/app/models/enums.py::Certainty and
// backend/app/schemas/ai_analysis.py's _normalize_certainty for why
// "unknown" here is a real, meaningful value rather than a placeholder).
const CERTAINTY_LABELS = { known: 'Known', inferred: 'Inferred', unknown: 'Unknown' }
const CERTAINTY_CLASS = { known: 'badge--green', inferred: 'badge--indigo', unknown: 'badge--gray' }

// Module 14 Phase 3: a coarse Low/Medium/High confidence in the
// Complexity level / Effort estimate specifically - distinct from
// CertaintyBadge above (which tags individual requirements/risks/
// components) and from the overall "AI Confidence" summary card (which is
// the classification's own confidence_score). Colors run the OPPOSITE
// direction from LEVEL_CLASS on purpose: a *high* confidence is reassuring
// (green), not alarming, unlike a *high* impact/risk level.
const CONFIDENCE_LEVEL_LABELS = { low: 'Low', medium: 'Medium', high: 'High' }
const CONFIDENCE_LEVEL_CLASS = { low: 'badge--amber', medium: 'badge--blue', high: 'badge--green' }

// Module 15 (Repository Intelligence): the ONLY three labels a repository
// finding can ever carry (backend/app/models/enums.py::FileMatchLabel) -
// there is no "definitely affected" value anywhere in this app on purpose,
// computed server-side from a numeric confidence score, never trusted
// from the AI's own wording. Colors run the same direction as LEVEL_CLASS
// (more confident a file is affected = more attention-grabbing), not the
// "green is good" direction ConfidenceLevelBadge uses - a confident file
// match is something to go look at, not reassuring news.
const MATCH_LABEL_LABELS = {
  likely_affected: 'Likely Affected',
  potentially_affected: 'Potentially Affected',
  possibly_related: 'Possibly Related',
}
const MATCH_LABEL_CLASS = {
  likely_affected: 'badge--orange',
  potentially_affected: 'badge--amber',
  possibly_related: 'badge--gray',
}

// Module 14 Phase 4: the 7 fixed lenses every analysis assesses impact
// through (backend/app/models/enums.py::ImpactCategory), in a fixed
// display order - distinct from RISK_CATEGORY_ORDER above (a Risk is a
// specific thing that could go wrong; an impact assessment describes the
// change's general effect through this lens regardless of whether
// anything goes wrong).
const IMPACT_CATEGORY_ORDER = ['business', 'technical', 'customer', 'operational', 'security', 'data', 'performance']
const IMPACT_CATEGORY_LABELS = {
  business: 'Business',
  technical: 'Technical',
  customer: 'Customer',
  operational: 'Operational',
  security: 'Security',
  data: 'Data',
  performance: 'Performance',
}

function ImpactAssessmentBadges({ item }) {
  if (!item) return null
  return (
    <div className="ad-impact-card-badges">
      <span className={`badge ${LEVEL_CLASS[item.impact_level] || 'badge--gray'}`}>
        {titleCase(item.impact_level)} impact
      </span>
      <CertaintyBadge certainty={item.certainty} />
    </div>
  )
}

function ImpactAssessmentCard({ category, item }) {
  return (
    <div className="cr-detail-section ad-impact-card">
      <h3 className="ad-impact-card-title">{IMPACT_CATEGORY_LABELS[category] || titleCase(category)}</h3>
      {item ? (
        <>
          <ImpactAssessmentBadges item={item} />
          <p className="cr-detail-text ad-mt">{item.description}</p>
          <ConfidenceBar value={item.confidence} />
          <RelatedFilesLine files={item.related_files} />
        </>
      ) : (
        <p className="ad-empty">Insufficient information.</p>
      )}
    </div>
  )
}

// Module 14 Phase 4: the full 7-category grid - used on the Impact tab.
// The Overview tab's Business/Technical Impact sections pull the matching
// two items out of the same `analysis.impact_assessments` list directly,
// rather than duplicating this component, since they show extra context
// (business requirements, affected components) alongside the AI finding.
function ImpactAnalysisSection({ analysis }) {
  const byCategory = {}
  analysis.impact_assessments.forEach((item) => {
    if (!byCategory[item.category]) byCategory[item.category] = item
  })
  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Impact Analysis</h2>
      {analysis.impact_assessments.length === 0 ? (
        <p className="ad-empty">
          No structured impact assessment is available for this analysis yet - re-analyze this change request to
          generate one.
        </p>
      ) : (
        <div className="ad-impact-grid">
          {IMPACT_CATEGORY_ORDER.map((category) => (
            <ImpactAssessmentCard key={category} category={category} item={byCategory[category]} />
          ))}
        </div>
      )}
    </section>
  )
}

// Module 14 Phase 5: the 9 fixed lenses a Security finding is classified
// under (backend/app/models/enums.py::SecurityCategory), fixed display
// order.
const SECURITY_CATEGORY_ORDER = [
  'authentication',
  'authorization',
  'data_protection',
  'secrets',
  'api_security',
  'rate_limiting',
  'privacy',
  'audit_logging',
  'compliance',
]
const SECURITY_CATEGORY_LABELS = {
  authentication: 'Authentication',
  authorization: 'Authorization',
  data_protection: 'Data Protection',
  secrets: 'Secrets',
  api_security: 'API Security',
  rate_limiting: 'Rate Limiting',
  privacy: 'Privacy',
  audit_logging: 'Audit Logging',
  compliance: 'Compliance',
}
// Only OPEN/NOT_APPLICABLE ever come from the AI itself - ACKNOWLEDGED/
// RESOLVED are set by a human reviewer instead (Module 14 Phase 6, see
// SecurityFindingStatusControl below).
const SECURITY_STATUS_OPTIONS = [
  { value: 'open', label: 'Open' },
  { value: 'not_applicable', label: 'Not Applicable' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
]
const SECURITY_STATUS_LABELS = {
  open: 'Open',
  not_applicable: 'Not Applicable',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
}
const SECURITY_STATUS_CLASS = {
  open: 'badge--orange',
  not_applicable: 'badge--gray',
  acknowledged: 'badge--blue',
  resolved: 'badge--green',
}

function SecurityStatusBadge({ status }) {
  if (!status) return null
  return (
    <span className={`badge ad-inline-badge ${SECURITY_STATUS_CLASS[status] || 'badge--gray'}`}>
      {SECURITY_STATUS_LABELS[status] || titleCase(status)}
    </span>
  )
}

/** Module 14 Phase 6: lets an authorized human move this finding's Status
 * forward (or back, to reopen/correct one) - the AI itself can only ever
 * leave a finding Open or Not Applicable (see
 * SecurityFindingItem.normalize_status on the backend). Same "backend is
 * the real permission boundary, this control just shows the resulting
 * 403 inline" approach as RequirementReviewControl above. */
function SecurityFindingStatusControl({ finding, changeRequestId, token, onReviewed }) {
  const [editing, setEditing] = useState(false)
  const [choice, setChoice] = useState(finding.status)
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    updateSecurityFindingStatus(changeRequestId, finding.id, { status: choice, comment: comment || null }, token)
      .then(() => {
        setEditing(false)
        setComment('')
        return onReviewed()
      })
      .catch((err) => setError(err.message || 'Could not update this finding.'))
      .finally(() => setSubmitting(false))
  }

  if (!editing) {
    return (
      <button type="button" className="cr-btn cr-btn--ghost cr-btn--small ad-mt" onClick={() => setEditing(true)}>
        Update status
      </button>
    )
  }

  return (
    <form className="respond-form ad-mt" onSubmit={handleSubmit}>
      {error && <p className="cr-form-error">{error}</p>}
      <div className="status-form-row">
        <select
          className="cr-filter-select"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          aria-label="Finding status"
        >
          {SECURITY_STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <button type="submit" className="cr-btn cr-btn--primary cr-btn--small" disabled={submitting}>
          {submitting ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          className="cr-btn cr-btn--ghost cr-btn--small"
          onClick={() => {
            setEditing(false)
            setError(null)
          }}
        >
          Cancel
        </button>
      </div>
      <div className="cr-field">
        <label htmlFor={`sec-comment-${finding.id}`}>
          Comment <span className="cr-optional-tag">optional</span>
        </label>
        <textarea
          id={`sec-comment-${finding.id}`}
          rows={2}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
    </form>
  )
}

function SecurityFindingCard({ category, item, changeRequestId, token, onReviewed }) {
  return (
    <div className="cr-detail-section ad-impact-card">
      <h3 className="ad-impact-card-title">{SECURITY_CATEGORY_LABELS[category] || titleCase(category)}</h3>
      {item ? (
        <>
          <div className="ad-impact-card-badges">
            <span className={`badge ${LEVEL_CLASS[item.severity] || 'badge--gray'}`}>
              {titleCase(item.severity)} severity
            </span>
            <SecurityStatusBadge status={item.status} />
          </div>
          <p className="cr-detail-text ad-mt">{item.finding}</p>
          {item.evidence && <p className="cr-analysis-list-mitigation">Evidence: {item.evidence}</p>}
          {item.recommendation && (
            <p className="cr-analysis-list-mitigation">Recommendation: {item.recommendation}</p>
          )}
          <SecurityFindingStatusControl
            finding={item}
            changeRequestId={changeRequestId}
            token={token}
            onReviewed={onReviewed}
          />
        </>
      ) : (
        <p className="ad-empty">Insufficient information.</p>
      )}
    </div>
  )
}

// Module 14 Phase 5: the full 9-category grid, replacing the old flat
// concerns/summary blob as the Security tab's primary content. Kept
// separate from ImpactAnalysisSection above (different category set,
// different card fields) even though the card shell/CSS is shared.
function SecurityFindingsSection({ analysis, changeRequestId, token, onReviewed }) {
  const byCategory = {}
  analysis.security_findings.forEach((item) => {
    if (!byCategory[item.category]) byCategory[item.category] = item
  })
  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Security Findings</h2>
      <div className="ad-impact-grid">
        {SECURITY_CATEGORY_ORDER.map((category) => (
          <SecurityFindingCard
            key={category}
            category={category}
            item={byCategory[category]}
            changeRequestId={changeRequestId}
            token={token}
            onReviewed={onReviewed}
          />
        ))}
      </div>
    </section>
  )
}

function ConfidenceLevelBadge({ level }) {
  if (!level) return null
  return (
    <span className={`badge ad-inline-badge ${CONFIDENCE_LEVEL_CLASS[level] || 'badge--gray'}`}>
      {CONFIDENCE_LEVEL_LABELS[level] || titleCase(level)} confidence
    </span>
  )
}

function CertaintyBadge({ certainty }) {
  if (!certainty) return null
  return (
    <span className={`badge ad-inline-badge ${CERTAINTY_CLASS[certainty] || 'badge--gray'}`}>
      {CERTAINTY_LABELS[certainty] || certainty}
    </span>
  )
}

// Same small formatter ChangeRequestDetail.jsx / NotificationsPage.jsx
// already each define locally - not worth sharing across three files for
// one date-formatting one-liner.
function formatDate(isoString) {
  if (!isoString) return '—'
  try {
    return new Date(isoString).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return isoString
  }
}

function titleCase(value) {
  if (!value) return value
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function riskTone(scoreOutOf10) {
  if (scoreOutOf10 >= 7.5) return '#b42318'
  if (scoreOutOf10 >= 5) return '#c4320a'
  if (scoreOutOf10 >= 2.5) return '#b54708'
  return '#067647'
}

/** Splits the analysis engine's "Backend: X, Frontend: Y, Testing: Z,
 * Total: W" string back into its four parts for the summary card / Effort
 * tab. Falls back to nulls (rendered as "Insufficient information.") if the
 * text doesn't match - display-only, never blocks anything. */
function parseEffortEstimate(text) {
  if (!text) return null
  const labels = ['Backend', 'Frontend', 'Testing', 'Total']
  const result = {}
  labels.forEach((label, i) => {
    const rest = labels.slice(i + 1)
    const pattern = rest.length
      ? new RegExp(`${label}:\\s*(.*?)(?:,\\s*(?:${rest.join('|')}):|$)`, 'i')
      : new RegExp(`${label}:\\s*(.*)$`, 'i')
    const match = text.match(pattern)
    result[label.toLowerCase()] = match ? match[1].replace(/,\s*$/, '').trim() : null
  })
  return result
}

function Gauge({ pct, color, children }) {
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <div className="ad-gauge" style={{ '--gauge-pct': `${clamped}%`, '--gauge-color': color }}>
      <div className="ad-gauge-inner">{children}</div>
    </div>
  )
}

function EmptyTab({ text }) {
  return (
    <section className="cr-detail-section">
      <p className="ad-empty">{text}</p>
    </section>
  )
}

// Module 15 Phase 5/6 (Repository Intelligence - Integration): the
// file_path of any of this change request's own repository findings that
// share enough wording with this specific item to plausibly be "the
// file(s) behind this" - computed fresh by the backend
// (app/services/repository_linkage.py), never a second, duplicate impact
// system. Renders nothing when empty - the common case for an analysis
// that predates any repository scan, or an item nothing in the repository
// overlaps with.
function RelatedFilesLine({ files }) {
  if (!files || files.length === 0) return null
  return (
    <p className="cr-analysis-list-mitigation">
      Related file{files.length > 1 ? 's' : ''}: {files.join(', ')}
    </p>
  )
}

// Module 17 Phase 4 (Test Cases & Implementation Plan 2.0 - Traceability):
// the "REQ-<id>"/"RISK-<id>" references app/services/traceability_linkage.py
// computes for a test case/task - same "renders nothing when empty" rule
// as RelatedFilesLine above, for the same reason (a fresh analysis with no
// requirements/risks yet, or an item nothing overlaps with, is an honest
// "nothing found," not a gap to flag).
function ReferencesLine({ label, refs }) {
  if (!refs || refs.length === 0) return null
  return (
    <p className="cr-analysis-list-mitigation">
      {label}: {refs.join(', ')}
    </p>
  )
}

function ConfidenceBar({ value }) {
  return (
    <div className="ad-confidence-row">
      <div className="bar-track ad-confidence-track">
        <div className="bar-fill" style={{ width: `${Math.round(value)}%`, background: '#4338ca' }} />
      </div>
      <span className="ad-confidence-value">{Math.round(value)}% confidence</span>
    </div>
  )
}

function OverviewTab({ analysis, recommendedApprovals }) {
  const recMeta = analysis.recommendation ? RECOMMENDATION_META[analysis.recommendation] : null
  const affectedNames = analysis.affected_components.map(
    (c) => `${c.component_name} (${titleCase(c.component_type)})`
  )
  // Module 14 Phase 4: Business/Technical Impact now come straight from the
  // same impact_assessments the Impact tab's structured cards use, instead
  // of being assembled here out of unrelated fields (business-type
  // Requirements, complexity_reasoning) - one source of truth per finding,
  // per the architecture lock. `undefined` (pre-Phase-4 analyses that
  // haven't been regenerated yet) falls through to the same "Insufficient
  // information." empty state as before.
  const businessImpact = analysis.impact_assessments.find((i) => i.category === 'business')
  const technicalImpact = analysis.impact_assessments.find((i) => i.category === 'technical')

  return (
    <>
      <section className="cr-detail-section">
        <h2 className="cr-section-title">AI Summary</h2>
        <p className="cr-detail-text">{analysis.summary}</p>
      </section>

      <section className="cr-detail-section">
        <h2 className="cr-section-title">Classification</h2>
        <dl className="cr-detail-grid">
          <dt>Category</dt>
          <dd>{analysis.category}</dd>
          <dt>Confidence</dt>
          <dd>{Math.round(analysis.confidence_score)}%</dd>
        </dl>
        {analysis.classification_reason && <p className="cr-detail-text ad-mt">{analysis.classification_reason}</p>}
      </section>

      <section className="cr-detail-section">
        <h2 className="cr-section-title">Business Impact</h2>
        {businessImpact ? (
          <>
            <ImpactAssessmentBadges item={businessImpact} />
            <p className="cr-detail-text ad-mt">{businessImpact.description}</p>
          </>
        ) : (
          <p className="ad-empty">Insufficient information.</p>
        )}
      </section>

      <section className="cr-detail-section">
        <h2 className="cr-section-title">Technical Impact</h2>
        {technicalImpact ? (
          <>
            <ImpactAssessmentBadges item={technicalImpact} />
            <p className="cr-detail-text ad-mt">{technicalImpact.description}</p>
            {affectedNames.length > 0 && (
              <p className="cr-detail-text ad-mt">
                <strong>Affects:</strong> {affectedNames.join(', ')}
              </p>
            )}
          </>
        ) : (
          <p className="ad-empty">Insufficient information.</p>
        )}
      </section>

      <section className="cr-detail-section">
        <h2 className="cr-section-title">Recommendation</h2>
        {recMeta ? (
          <p className="ad-recommendation-inline">
            <span aria-hidden="true">{recMeta.emoji}</span> <strong>{recMeta.label}</strong>
          </p>
        ) : (
          <p className="ad-empty">No recommendation given.</p>
        )}
        {analysis.recommendation_reasoning && <p className="cr-detail-text">{analysis.recommendation_reasoning}</p>}
        {analysis.workflow_recommendation && (
          <p className="cr-detail-text ad-mt approvals-recommendation">{analysis.workflow_recommendation}</p>
        )}
        {/* Module 14 Phase 1: the same AI-derived recommended-approval-types
            list already used to build ChangeRequestDetail.jsx's Approvals
            section (GET .../approvals/recommended) - reused here as read-
            only badges. This never creates an Approval row itself; tagging
            an actual approver still only happens on the change request's
            detail page, per the architecture lock (one approval system). */}
        {recommendedApprovals.length > 0 && (
          <div className="ad-mt ad-recommended-approvals">
            <span className="cr-detail-text-label">Recommended:</span>
            {recommendedApprovals.map((r) => (
              <span key={r.approval_type} className="badge badge--indigo ad-inline-badge">
                ✓ {r.label}
              </span>
            ))}
            {/* Module 22: recommended_approvals.is_outdated - the change
                request has been edited since the analysis these
                recommendations were computed from, the same staleness
                signal the outdated-banner elsewhere on this page already
                warns about, just applied here since this section has no
                banner of its own to attach it to. */}
            {recommendedApprovals[0]?.is_outdated && (
              <span className="badge badge--amber ad-inline-badge" title="The change request has been edited since this analysis ran.">
                May be outdated
              </span>
            )}
          </div>
        )}
      </section>

      <KnowledgeEvidenceSection evidence={analysis.knowledge_evidence} />
    </>
  )
}

// Module 16 Phase 4/5 (Project Knowledge Base & RAG): the project
// documentation this specific analysis run actually grounded itself in -
// read straight off analysis.knowledge_evidence (already present on the
// AnalysisRead response, no separate fetch needed). Renders nothing when
// empty, which is the common case for any analysis that predates this
// module, or one where nothing in the knowledge base was genuinely
// relevant (min_score filtering - see knowledge_embeddings.py). Each
// row's own is_outdated (set by the API layer from the same
// is_outdated computation as the analysis itself - see
// api/change_requests.py) is the ONLY staleness axis evidence has: it
// was always generated fresh as part of one analysis run, so "outdated"
// here means only "the change request has been edited since," never a
// second, independent staleness check.
function KnowledgeEvidenceSection({ evidence }) {
  if (!evidence || evidence.length === 0) return null
  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Evidence Used</h2>
      <p className="cr-detail-text ig-intro">
        Excerpts from your team&apos;s own knowledge base that this analysis was grounded in - cited exactly as
        given to the AI, never asserted with more certainty than the similarity score below supports.
      </p>
      <ul className="cr-analysis-list ad-mt">
        {evidence.map((item) => (
          <li key={item.id} className="cr-analysis-list-item">
            {item.is_outdated && <span className="badge badge--amber">Outdated</span>}
            <div>
              <p className="cr-analysis-list-tag">
                {item.document_title}
                {item.section_label ? ` · ${item.section_label}` : ''}
              </p>
              <ConfidenceBar value={item.similarity_score * 100} />
              <p className="cr-analysis-list-text ad-mt">{item.content_snippet}</p>
              {item.is_outdated && (
                <p className="cr-analysis-list-mitigation">
                  This analysis (and the evidence it used) predates a later edit to the change request - re-analyze
                  for up-to-date grounding.
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

// Module 14 Phase 6: a human reviewer's verdict on a Requirement -
// entirely separate from CertaintyBadge above (the AI's own Known/
// Inferred/Unknown label, never touched by reviewing).
const REVIEW_STATUS_LABELS = { confirmed: 'Confirmed', needs_clarification: 'Needs Clarification' }
const REVIEW_STATUS_CLASS = { confirmed: 'badge--green', needs_clarification: 'badge--amber' }

function ReviewStatusBadge({ status }) {
  if (!status) return null
  return (
    <span className={`badge ad-inline-badge ${REVIEW_STATUS_CLASS[status] || 'badge--gray'}`}>
      {REVIEW_STATUS_LABELS[status] || titleCase(status)}
    </span>
  )
}

/** Module 14 Phase 6: lets an authorized human mark this requirement
 * Confirmed or Needs Clarification. The real permission boundary is the
 * backend (workflow_rules.can_review_analysis_findings) - this control is
 * shown to every viewer, and an unauthorized attempt simply surfaces the
 * backend's 403 message inline below, rather than duplicating the CR's
 * assignment-role logic on this page too. */
function RequirementReviewControl({ requirement, changeRequestId, token, onReviewed }) {
  const [editing, setEditing] = useState(false)
  const [choice, setChoice] = useState(requirement.review_status || 'confirmed')
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    reviewRequirement(changeRequestId, requirement.id, { review_status: choice, comment: comment || null }, token)
      .then(() => {
        setEditing(false)
        setComment('')
        return onReviewed()
      })
      .catch((err) => setError(err.message || 'Could not save this review.'))
      .finally(() => setSubmitting(false))
  }

  return (
    <div className="ad-mt">
      <ReviewStatusBadge status={requirement.review_status} />
      {!editing ? (
        <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={() => setEditing(true)}>
          {requirement.review_status ? 'Change review' : 'Review'}
        </button>
      ) : (
        <form className="respond-form" onSubmit={handleSubmit}>
          {error && <p className="cr-form-error">{error}</p>}
          <div className="status-form-row">
            <select
              className="cr-filter-select"
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              aria-label="Review verdict"
            >
              <option value="confirmed">Confirmed</option>
              <option value="needs_clarification">Needs Clarification</option>
            </select>
            <button type="submit" className="cr-btn cr-btn--primary cr-btn--small" disabled={submitting}>
              {submitting ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              className="cr-btn cr-btn--ghost cr-btn--small"
              onClick={() => {
                setEditing(false)
                setError(null)
              }}
            >
              Cancel
            </button>
          </div>
          {choice === 'needs_clarification' && (
            <div className="cr-field">
              <label htmlFor={`review-comment-${requirement.id}`}>
                Comment <span className="cr-optional-tag">required for this response</span>
              </label>
              <textarea
                id={`review-comment-${requirement.id}`}
                rows={2}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </div>
          )}
        </form>
      )}
    </div>
  )
}

function RequirementsTab({ analysis, changeRequestId, token, onReviewed }) {
  const items = [...analysis.requirements].sort(
    (a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9)
  )
  if (items.length === 0) return <EmptyTab text="No requirements were extracted for this change." />
  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Extracted Requirements</h2>
      <ul className="cr-analysis-list">
        {items.map((r) => (
          <li key={r.id} className="cr-analysis-list-item">
            <span className={`badge ${PRIORITY_CLASS[r.priority] || 'badge--gray'}`}>
              {PRIORITY_LABELS[r.priority] || r.priority}
            </span>
            <div>
              <p className="cr-analysis-list-tag">
                {titleCase(r.requirement_type)} <CertaintyBadge certainty={r.certainty} />
              </p>
              <p className="cr-analysis-list-text">{r.description}</p>
              {typeof r.confidence === 'number' && <ConfidenceBar value={r.confidence} />}
              {r.evidence && <p className="cr-analysis-list-mitigation">Evidence: {r.evidence}</p>}
              <RequirementReviewControl
                requirement={r}
                changeRequestId={changeRequestId}
                token={token}
                onReviewed={onReviewed}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ImpactTab({ analysis, changeRequest, crCode }) {
  const items = analysis.affected_components
  return (
    <>
      <ImpactAnalysisSection analysis={analysis} />

      <section className="cr-detail-section">
        <h2 className="cr-section-title">Impact &amp; Dependency Graph</h2>
        <p className="cr-detail-text ig-intro">
          Every affected component and dependency the AI identified for this change, branching from the change
          request itself. The analysis doesn&apos;t specify how these items relate to each other, so - rather than
          guessing at connections that were never asserted - each one is shown as directly tied to the change,
          grouped by category. Click any node for its full detail.
        </p>
        <ImpactGraph
          changeRequest={changeRequest}
          crCode={crCode}
          components={analysis.affected_components}
          dependencies={analysis.dependencies}
        />
      </section>

      {items.length === 0 ? (
        <EmptyTab text="No affected components were identified." />
      ) : (
        <section className="cr-detail-section">
          <h2 className="cr-section-title">Affected Components</h2>
          <ul className="cr-analysis-list">
            {items.map((c) => (
              <li key={c.id} className="cr-analysis-list-item">
                <span className={`badge ${LEVEL_CLASS[c.impact_level] || 'badge--gray'}`}>
                  {titleCase(c.impact_level)} impact
                </span>
                <CertaintyBadge certainty={c.certainty} />
                <div>
                  <p className="cr-analysis-list-tag">
                    {c.component_name} · {titleCase(c.component_type)}
                  </p>
                  <p className="cr-analysis-list-text">{c.reason}</p>
                  <ConfidenceBar value={c.confidence} />
                  {/* Module 14 Phase 2 */}
                  {c.evidence && <p className="cr-analysis-list-mitigation">Evidence: {c.evidence}</p>}
                  <RelatedFilesLine files={c.related_files} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

// Module 14 Phase 2: how directly this change actually relies on a
// dependency - distinct from its impact-level badge (how much *this
// change* would be affected). "Potential" is deliberately the AI's way of
// flagging "plausible but not confidently established" rather than
// asserting a dependency it isn't sure about - see the "do not invent
// dependencies" prompt rule in analysis_engine.py.
const RELATIONSHIP_LABELS = { direct: 'Direct', indirect: 'Indirect', potential: 'Potential' }
const RELATIONSHIP_CLASS = { direct: 'badge--blue', indirect: 'badge--purple', potential: 'badge--gray' }

function DependenciesTab({ analysis }) {
  const items = analysis.dependencies
  if (items.length === 0) return <EmptyTab text="No dependencies were identified." />
  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Dependencies</h2>
      <ul className="cr-analysis-list">
        {items.map((d) => (
          <li key={d.id} className="cr-analysis-list-item">
            <span className={`badge ${LEVEL_CLASS[d.impact_level] || 'badge--gray'}`}>
              {titleCase(d.impact_level)} impact
            </span>
            {d.relationship_type && (
              <span className={`badge ${RELATIONSHIP_CLASS[d.relationship_type] || 'badge--gray'}`}>
                {RELATIONSHIP_LABELS[d.relationship_type] || titleCase(d.relationship_type)}
              </span>
            )}
            {d.risk_severity && (
              <span className={`badge ${LEVEL_CLASS[d.risk_severity] || 'badge--gray'}`}>
                {titleCase(d.risk_severity)} risk
              </span>
            )}
            <div>
              <p className="cr-analysis-list-tag">
                {d.dependency_name} · {titleCase(d.dependency_type)}
              </p>
              <p className="cr-analysis-list-text">{d.reason}</p>
              <RelatedFilesLine files={d.related_files} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Module 9: the 0-10 overall risk score, shown again (bigger, with
 * context) inside the Risks tab itself rather than only in the top summary
 * card - reuses the same Gauge/riskTone the summary card uses so the
 * number is always consistent. */
function OverallRiskCard({ analysis, items }) {
  const scoreOutOf10 = analysis.risk_score / 10
  const severityCounts = { critical: 0, high: 0, medium: 0, low: 0 }
  items.forEach((r) => {
    if (severityCounts[r.severity] !== undefined) severityCounts[r.severity] += 1
  })
  const highest = ['critical', 'high', 'medium', 'low'].find((level) => severityCounts[level] > 0)

  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Overall Risk Score</h2>
      <div className="rk-overall">
        <Gauge pct={scoreOutOf10 * 10} color={riskTone(scoreOutOf10)}>
          <span className="ad-gauge-value">{scoreOutOf10.toFixed(1)}</span>
        </Gauge>
        <div className="rk-overall-text">
          <p className="ad-summary-text">{scoreOutOf10.toFixed(1)} out of 10</p>
          <p className="cr-detail-text">
            {items.length === 0
              ? 'No individual risks were identified for this change.'
              : `${items.length} risk${items.length === 1 ? '' : 's'} identified${
                  highest ? ` · highest severity: ${titleCase(highest)}` : ''
                }.`}
          </p>
        </div>
      </div>
    </section>
  )
}

/** One risk, laid out as a small card - severity/category header, then
 * probability + score as mini bars, then the two narrative fields the spec
 * asks for explicitly: Explanation and Mitigation. "Explanation" here is
 * the AI's own description/explanation text (analysis_engine.py already
 * combines the two before storage) - nothing added beyond what it wrote. */
function RiskCard({ risk }) {
  return (
    <div className="rk-card">
      <div className="rk-card-header">
        <span className={`badge ${LEVEL_CLASS[risk.severity] || 'badge--gray'}`}>{titleCase(risk.severity)}</span>
        <span className="rk-card-category">{titleCase(risk.category)}</span>
        <CertaintyBadge certainty={risk.certainty} />
      </div>

      <div className="rk-card-metrics">
        <div className="rk-metric">
          <span className="rk-metric-label">Probability</span>
          <div className="rk-metric-row">
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${Math.round(risk.probability * 100)}%`, background: '#4338ca' }}
              />
            </div>
            <span className="rk-metric-value">{Math.round(risk.probability * 100)}%</span>
          </div>
        </div>
        <div className="rk-metric">
          <span className="rk-metric-label">Score</span>
          <div className="rk-metric-row">
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${Math.round(risk.score)}%`, background: riskTone(risk.score / 10) }}
              />
            </div>
            <span className="rk-metric-value">{Math.round(risk.score)}/100</span>
          </div>
        </div>
      </div>

      <p className="rk-card-label">Explanation</p>
      <p className="cr-detail-text">{risk.description || 'Insufficient information.'}</p>

      <p className="rk-card-label">Mitigation</p>
      <p className="cr-detail-text">{risk.mitigation || 'Insufficient information.'}</p>

      {typeof risk.confidence === 'number' && (
        <>
          <p className="rk-card-label">AI Confidence in This Assessment</p>
          <p className="cr-detail-text">{Math.round(risk.confidence)}%</p>
        </>
      )}
      <RelatedFilesLine files={risk.related_files} />
    </div>
  )
}

function RisksTab({ analysis }) {
  const items = analysis.risks

  if (items.length === 0) {
    return (
      <>
        <OverallRiskCard analysis={analysis} items={items} />
        <EmptyTab text="No risks were identified for this change." />
      </>
    )
  }

  const severityCounts = { critical: 0, high: 0, medium: 0, low: 0 }
  items.forEach((r) => {
    if (severityCounts[r.severity] !== undefined) severityCounts[r.severity] += 1
  })
  const severityChartData = [
    { label: 'Critical', count: severityCounts.critical, color: '#b42318' },
    { label: 'High', count: severityCounts.high, color: '#c4320a' },
    { label: 'Medium', count: severityCounts.medium, color: '#b54708' },
    { label: 'Low', count: severityCounts.low, color: '#067647' },
  ]

  const categoryCounts = {}
  let otherCount = 0
  items.forEach((r) => {
    if (RISK_CATEGORY_ORDER.includes(r.category)) {
      categoryCounts[r.category] = (categoryCounts[r.category] || 0) + 1
    } else {
      otherCount += 1
    }
  })
  const categoryChartData = RISK_CATEGORY_ORDER.map((cat) => ({
    label: titleCase(cat),
    count: categoryCounts[cat] || 0,
    color: RISK_CATEGORY_COLORS[cat],
  }))
  if (otherCount > 0) {
    categoryChartData.push({ label: 'Other', count: otherCount, color: RISK_CATEGORY_COLORS.other })
  }

  const sorted = [...items].sort((a, b) => (PRIORITY_ORDER[a.severity] ?? 9) - (PRIORITY_ORDER[b.severity] ?? 9))

  return (
    <>
      <OverallRiskCard analysis={analysis} items={items} />
      <DistributionChart title="Risk Severity Breakdown" data={severityChartData} emptyLabel="No risks." />
      <DistributionChart title="Risk Category Breakdown" data={categoryChartData} emptyLabel="No risks." />
      <section className="cr-detail-section">
        <h2 className="cr-section-title">Risk Details</h2>
        <div className="rk-list">
          {sorted.map((r) => (
            <RiskCard key={r.id} risk={r} />
          ))}
        </div>
      </section>
    </>
  )
}

/** Module 9's security checklist - built only from the concerns and
 * mitigations already shown above (each tagged so it's clear which is
 * which), turned into checkable review items. Purely a local, in-page
 * interaction (nothing persisted) - it doesn't add any fact that wasn't
 * already displayed in the sections above it. */
function SecurityChecklist({ concerns, mitigations }) {
  const items = useMemo(
    () => [
      ...concerns.map((text, i) => ({ id: `concern-${i}`, tag: 'Concern', text })),
      ...mitigations.map((text, i) => ({ id: `mitigation-${i}`, tag: 'Mitigation', text })),
    ],
    [concerns, mitigations]
  )
  const [checked, setChecked] = useState({})

  if (items.length === 0) return null

  const doneCount = items.filter((item) => checked[item.id]).length

  function toggle(id) {
    setChecked((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Security Checklist</h2>
      <p className="cr-detail-text ig-intro">
        Built from the concerns and mitigations above - check items off as you review them for this change.
      </p>
      <div className="sec-checklist-progress">
        <div className="bar-track">
          <div
            className="bar-fill"
            style={{ width: `${items.length ? Math.round((doneCount / items.length) * 100) : 0}%`, background: '#067647' }}
          />
        </div>
        <span className="sec-checklist-progress-text">
          {doneCount}/{items.length} reviewed
        </span>
      </div>
      <ul className="sec-checklist">
        {items.map((item) => (
          <li key={item.id} className="sec-checklist-item">
            <label>
              <input type="checkbox" checked={Boolean(checked[item.id])} onChange={() => toggle(item.id)} />
              <span className={`sec-checklist-tag sec-checklist-tag--${item.tag.toLowerCase()}`}>{item.tag}</span>
              <span className={`sec-checklist-text${checked[item.id] ? ' sec-checklist-text--done' : ''}`}>
                {item.text}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  )
}

function SecurityTab({ analysis, changeRequestId, token, onReviewed }) {
  let security = null
  try {
    security = analysis.security_analysis ? JSON.parse(analysis.security_analysis) : null
  } catch {
    security = null
  }
  const concerns = security?.concerns || []
  const summary = security?.summary
  const securityRisks = analysis.risks.filter((r) => r.category === 'security')
  const mitigations = securityRisks.map((r) => r.mitigation).filter(Boolean)
  // Module 14 Phase 5: once an analysis has real structured findings, they
  // fully replace the old flat concerns/mitigations/checklist rendering
  // below - showing both would be two different views of "what's wrong,
  // security-wise" built at different times or by different logic, which
  // is exactly the duplicate-system the architecture lock rules out. Only
  // an analysis that predates Phase 5 (no security_findings rows at all)
  // still gets the old rendering.
  const hasStructuredFindings = analysis.security_findings.length > 0

  const hasAnything = hasStructuredFindings || Boolean(summary) || concerns.length > 0 || securityRisks.length > 0
  if (!hasAnything) {
    return <EmptyTab text="No security concerns were identified." />
  }

  // Security Risk Level is derived only from security-category risk items
  // (real AI-assigned severity/score) - never estimated from the concern
  // count, which would mean inventing a rating the AI never gave.
  const worstSeverity =
    securityRisks.length > 0
      ? securityRisks.reduce(
          (worst, r) => ((PRIORITY_ORDER[r.severity] ?? 9) < (PRIORITY_ORDER[worst] ?? 9) ? r.severity : worst),
          securityRisks[0].severity
        )
      : null
  const worstScore = securityRisks.length > 0 ? Math.max(...securityRisks.map((r) => r.score)) : null

  return (
    <>
      <section className="cr-detail-section">
        <h2 className="cr-section-title">Security Risk Level</h2>
        {worstSeverity ? (
          <div className="sec-level-row">
            <span className={`badge sec-level-badge ${LEVEL_CLASS[worstSeverity] || 'badge--gray'}`}>
              {titleCase(worstSeverity)}
            </span>
            <span className="cr-detail-text">
              Based on {securityRisks.length} security-related risk{securityRisks.length === 1 ? '' : 's'} identified
              {worstScore != null ? ` · highest score ${Math.round(worstScore)}/100` : ''}.
            </span>
          </div>
        ) : (
          <p className="ad-empty">
            The AI didn&apos;t score a specific security risk level for this change
            {concerns.length > 0 ? ' - see the concerns below.' : '.'}
          </p>
        )}
      </section>

      {summary && (
        <section className="cr-detail-section">
          <h2 className="cr-section-title">Summary</h2>
          <p className="cr-detail-text">{summary}</p>
        </section>
      )}

      {hasStructuredFindings ? (
        <SecurityFindingsSection
          analysis={analysis}
          changeRequestId={changeRequestId}
          token={token}
          onReviewed={onReviewed}
        />
      ) : (
        <>
          <section className="cr-detail-section">
            <h2 className="cr-section-title">Potential Concerns</h2>
            {concerns.length > 0 ? (
              <ul className="cr-plain-list">
                {concerns.map((concern, index) => (
                  <li key={index}>{concern}</li>
                ))}
              </ul>
            ) : (
              <p className="ad-empty ad-mt">No specific concerns flagged.</p>
            )}
          </section>

          <section className="cr-detail-section">
            <h2 className="cr-section-title">Recommended Mitigations</h2>
            {mitigations.length > 0 ? (
              <ul className="cr-plain-list">
                {mitigations.map((mitigation, index) => (
                  <li key={index}>{mitigation}</li>
                ))}
              </ul>
            ) : (
              <p className="ad-empty ad-mt">No specific mitigations beyond the concerns above were provided.</p>
            )}
          </section>

          <SecurityChecklist concerns={concerns} mitigations={mitigations} />
        </>
      )}
    </>
  )
}

/** Module 14 Phase 3: Complexity and Effort share one tab (and one section
 * here) because the spec pairs them - both are estimates, both get a
 * Low/Medium/High confidence instead of a fake-precise number, and both
 * are explained in plain language rather than left as a bare badge. */
function ComplexityCard({ analysis }) {
  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Complexity</h2>
      <div className="ad-complexity-row">
        <span className={`badge ad-summary-badge ${LEVEL_CLASS[analysis.complexity] || 'badge--gray'}`}>
          {titleCase(analysis.complexity)}
        </span>
        {analysis.complexity_confidence && <ConfidenceLevelBadge level={analysis.complexity_confidence} />}
      </div>
      <p className="cr-detail-text ad-mt">{analysis.complexity_reasoning || 'Insufficient information.'}</p>
    </section>
  )
}

function EffortTab({ analysis, effort }) {
  return (
    <>
      <ComplexityCard analysis={analysis} />
      {!analysis.effort_estimate ? (
        <EmptyTab text="No effort estimate available." />
      ) : (
        <section className="cr-detail-section">
          <h2 className="cr-section-title">
            Estimated Effort {analysis.effort_confidence && <ConfidenceLevelBadge level={analysis.effort_confidence} />}
          </h2>
          <p className="ad-effort-note">
            Ranges, not fake precision - the AI's honest estimate from the request text alone.
          </p>
          <div className="ad-effort-grid">
            {[
              { label: 'Backend', value: effort?.backend },
              { label: 'Frontend', value: effort?.frontend },
              { label: 'Testing', value: effort?.testing },
              { label: 'Total', value: effort?.total },
            ].map((row) => (
              <div key={row.label} className="ad-effort-row">
                <span className="ad-effort-label">{row.label}</span>
                <span className="ad-effort-value">{row.value || 'Insufficient information.'}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  )
}

/** Answers one clarification question in place - the missing information
 * the AI itself asked for, typed in by whoever actually has it (often the
 * requester, not necessarily whoever's reviewing the analysis - so this is
 * open to anyone who can comment, same as ClarificationAnswerControl's own
 * backend gate). Submitting always marks the question Resolved; it can be
 * opened again afterward to correct the answer, which is why an already-
 * answered question still shows this control rather than locking it away. */
function ClarificationAnswerControl({ question, changeRequestId, token, onAnswered }) {
  const [editing, setEditing] = useState(false)
  const [answer, setAnswer] = useState(question.answer_text || '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    answerClarificationQuestion(changeRequestId, question.id, answer, token)
      .then(() => {
        setEditing(false)
        return onAnswered()
      })
      .catch((err) => setError(err.message || 'Could not save this answer.'))
      .finally(() => setSubmitting(false))
  }

  if (!editing) {
    return (
      <div className="ad-mt">
        {question.resolved && question.answer_text && (
          <p className="cr-question-answer">
            <span className="cr-question-answer-label">Answer:</span> {question.answer_text}
          </p>
        )}
        <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={() => setEditing(true)}>
          {question.resolved ? 'Edit answer' : 'Provide this information'}
        </button>
      </div>
    )
  }

  return (
    <form className="respond-form ad-mt" onSubmit={handleSubmit}>
      {error && <p className="cr-form-error">{error}</p>}
      <div className="cr-field">
        <label htmlFor={`clarification-answer-${question.id}`}>Your answer</label>
        <textarea
          id={`clarification-answer-${question.id}`}
          rows={3}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Type the missing information here…"
        />
      </div>
      <div className="status-form-row">
        <button type="submit" className="cr-btn cr-btn--primary cr-btn--small" disabled={submitting || !answer.trim()}>
          {submitting ? 'Saving…' : 'Save answer'}
        </button>
        <button
          type="button"
          className="cr-btn cr-btn--ghost cr-btn--small"
          onClick={() => {
            setEditing(false)
            setAnswer(question.answer_text || '')
            setError(null)
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

function MissingInfoTab({ analysis, changeRequestId, token, onAnswered }) {
  const items = analysis.clarification_questions
  const unresolved = items.filter((q) => !q.resolved)
  const sorted = [...items].sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9))

  if (items.length === 0) {
    return (
      <div className="ad-missing-banner ad-missing-banner--clear">
        <span className="ad-missing-count">0</span>
        <span>No clarification items - nothing blocking this change.</span>
      </div>
    )
  }

  return (
    <>
      <div className={`ad-missing-banner ${unresolved.length > 0 ? 'ad-missing-banner--alert' : 'ad-missing-banner--clear'}`}>
        <span className="ad-missing-count">{unresolved.length}</span>
        <span>{unresolved.length === 1 ? 'clarification item required.' : 'clarification items required.'}</span>
      </div>
      <section className="cr-detail-section">
        <ul className="cr-question-list">
          {sorted.map((q) => (
            <li key={q.id} className="cr-question-item">
              <span className={`badge ${q.resolved ? 'badge--green' : 'badge--amber'}`}>
                {q.resolved ? 'Resolved' : 'Open'}
              </span>
              <div>
                <p className="cr-question-text">
                  <span className={`badge ad-inline-badge ${PRIORITY_CLASS[q.priority] || 'badge--gray'}`}>
                    {PRIORITY_LABELS[q.priority] || q.priority}
                  </span>
                  {q.question}
                </p>
                <p className="cr-question-reason">{q.reason}</p>
                <ClarificationAnswerControl
                  question={q}
                  changeRequestId={changeRequestId}
                  token={token}
                  onAnswered={onAnswered}
                />
              </div>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}

// Module 10: the AI Analysis Engine's real TestType vocabulary
// (analysis_engine.py's TEST_TYPES / app.models.enums.TestType) - note this
// doesn't literally match every label in the Module 10 spec's example list
// ("Functional", "Negative"); those aren't values the engine can produce.
// Rather than inventing new categories the AI was never asked to classify
// against, the filter below is built from whatever types are actually
// present in this analysis's real test cases.
const TEST_TYPE_LABELS = {
  unit: 'Unit',
  integration: 'Integration',
  e2e: 'End-to-End',
  regression: 'Regression',
  performance: 'Performance',
  security: 'Security',
  manual: 'Manual',
  // Module 17 Phase 1/2 (Test Cases & Implementation Plan 2.0)
  negative: 'Negative',
  boundary: 'Boundary',
  api: 'API',
  ui: 'UI',
  data_validation: 'Data Validation',
}

// Module 17 Phase 3 - Module 12's own per-CR role vocabulary (see
// AssignmentRole in the backend), reused here purely to label a
// *suggestion* (see ImplementationPlanTab's own "Suggested Owner" field) -
// never an actual assignment control.
const ASSIGNMENT_ROLE_LABELS = {
  requester: 'Requester',
  owner: 'Owner',
  technical_lead: 'Technical Lead',
  reviewer: 'Reviewer',
  approver: 'Approver',
  security_reviewer: 'Security Reviewer',
  qa_owner: 'QA Owner',
  implementation_owner: 'Implementation Owner',
}

/** Module 17 Phase 6 (human editing): lets an authorized human correct one
 * AI-generated test case in place. Same pattern as RequirementReviewControl
 * above - shown to every viewer, the real permission boundary is the
 * backend (workflow_rules.can_review_analysis_findings), so an
 * unauthorized attempt just surfaces the backend's 403 message inline
 * rather than duplicating that logic here. Never touches this row's own
 * requirement/risk/related-file references - those stay computed fresh by
 * the backend on the next load, from whatever the edited wording now is. */
function TestCaseEditControl({ testCase, changeRequestId, token, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(testCase.title)
  const [description, setDescription] = useState(testCase.description)
  const [testType, setTestType] = useState(testCase.test_type)
  const [priority, setPriority] = useState(testCase.priority)
  const [preconditions, setPreconditions] = useState(testCase.preconditions || '')
  const [steps, setSteps] = useState((testCase.steps || []).join('\n'))
  const [expectedResult, setExpectedResult] = useState(testCase.expected_result)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  function startEditing() {
    setTitle(testCase.title)
    setDescription(testCase.description)
    setTestType(testCase.test_type)
    setPriority(testCase.priority)
    setPreconditions(testCase.preconditions || '')
    setSteps((testCase.steps || []).join('\n'))
    setExpectedResult(testCase.expected_result)
    setReason('')
    setError(null)
    setEditing(true)
  }

  function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    updateTestCase(
      changeRequestId,
      testCase.id,
      {
        title,
        description,
        test_type: testType,
        priority,
        preconditions: preconditions || null,
        steps: steps
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
        expected_result: expectedResult,
        reason: reason || null,
      },
      token
    )
      .then(() => {
        setEditing(false)
        return onSaved()
      })
      .catch((err) => setError(err.message || 'Could not save this test case.'))
      .finally(() => setSubmitting(false))
  }

  if (!editing) {
    return (
      <div className="ad-mt">
        {testCase.edited_by && <span className="badge ad-inline-badge badge--blue">Edited</span>}
        <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={startEditing}>
          Edit
        </button>
      </div>
    )
  }

  return (
    <form className="respond-form ad-mt" onSubmit={handleSubmit}>
      {error && <p className="cr-form-error">{error}</p>}
      <div className="cr-field">
        <label htmlFor={`tc-title-${testCase.id}`}>Title</label>
        <input
          id={`tc-title-${testCase.id}`}
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div className="cr-field">
        <label htmlFor={`tc-description-${testCase.id}`}>Description</label>
        <textarea
          id={`tc-description-${testCase.id}`}
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="status-form-row">
        <select
          className="cr-filter-select"
          value={testType}
          onChange={(e) => setTestType(e.target.value)}
          aria-label="Test type"
        >
          {Object.entries(TEST_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select
          className="cr-filter-select"
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
          aria-label="Priority"
        >
          {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="cr-field">
        <label htmlFor={`tc-preconditions-${testCase.id}`}>
          Preconditions <span className="cr-optional-tag">optional</span>
        </label>
        <textarea
          id={`tc-preconditions-${testCase.id}`}
          rows={2}
          value={preconditions}
          onChange={(e) => setPreconditions(e.target.value)}
        />
      </div>
      <div className="cr-field">
        <label htmlFor={`tc-steps-${testCase.id}`}>
          Steps <span className="cr-optional-tag">one per line</span>
        </label>
        <textarea id={`tc-steps-${testCase.id}`} rows={3} value={steps} onChange={(e) => setSteps(e.target.value)} />
      </div>
      <div className="cr-field">
        <label htmlFor={`tc-expected-${testCase.id}`}>Expected Result</label>
        <textarea
          id={`tc-expected-${testCase.id}`}
          rows={2}
          value={expectedResult}
          onChange={(e) => setExpectedResult(e.target.value)}
        />
      </div>
      <div className="cr-field">
        <label htmlFor={`tc-reason-${testCase.id}`}>
          Reason for this edit <span className="cr-optional-tag">optional</span>
        </label>
        <textarea id={`tc-reason-${testCase.id}`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="status-form-row">
        <button type="submit" className="cr-btn cr-btn--primary cr-btn--small" disabled={submitting}>
          {submitting ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          className="cr-btn cr-btn--ghost cr-btn--small"
          onClick={() => {
            setEditing(false)
            setError(null)
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

function TestCasesTab({ analysis, changeRequestId, token, onRegenerate, regenerating, onSaved }) {
  const items = analysis.test_cases
  const [typeFilter, setTypeFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')

  if (items.length === 0) return <EmptyTab text="No test cases were suggested." />

  const availableTypes = [...new Set(items.map((t) => t.test_type))].sort()
  const availablePriorities = [...new Set(items.map((t) => t.priority))].sort(
    (a, b) => (PRIORITY_ORDER[a] ?? 9) - (PRIORITY_ORDER[b] ?? 9)
  )
  const filtered = items.filter(
    (t) => (!typeFilter || t.test_type === typeFilter) && (!priorityFilter || t.priority === priorityFilter)
  )

  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Suggested Test Cases</h2>

      {/* Module 17 Phase 5 - every test case shares its parent analysis's
          own is_outdated exactly (see TestCaseRead's own docstring), so
          this reuses that same flag rather than computing a second,
          independent staleness check - mirrors the Repository tab's own
          outdated-banner pattern, just scoped to this one tab. Reuses the
          existing full re-analysis action (no separate "regenerate just
          the tests" AI capability - see AnalysisDashboardPage's own
          handleRegenerate). */}
      {analysis.is_outdated && (
        <div className="outdated-banner">
          <span className="outdated-banner-text">
            <span className="outdated-banner-icon" aria-hidden="true">
              ⚠
            </span>
            <span>
              <strong>These test cases may be outdated.</strong> The change request has been edited since this
              analysis ran - regenerate to get test cases based on the current version.
            </span>
          </span>
          <button
            type="button"
            className="cr-btn cr-btn--primary cr-btn--small"
            onClick={onRegenerate}
            disabled={regenerating}
          >
            {regenerating ? 'Regenerating…' : 'Regenerate Test Cases'}
          </button>
        </div>
      )}

      <div className="tc-filters">
        <select
          className="cr-filter-select"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          aria-label="Filter by type"
        >
          <option value="">All types</option>
          {availableTypes.map((type) => (
            <option key={type} value={type}>
              {TEST_TYPE_LABELS[type] || titleCase(type)}
            </option>
          ))}
        </select>
        <select
          className="cr-filter-select"
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value)}
          aria-label="Filter by priority"
        >
          <option value="">All priorities</option>
          {availablePriorities.map((p) => (
            <option key={p} value={p}>
              {PRIORITY_LABELS[p] || p}
            </option>
          ))}
        </select>
        <span className="tc-filter-count">
          {filtered.length} of {items.length} shown
        </span>
      </div>

      {filtered.length === 0 ? (
        <p className="ad-empty">No test cases match these filters.</p>
      ) : (
        <ul className="cr-analysis-list">
          {filtered.map((t) => (
            <li key={t.id} className="cr-analysis-list-item">
              <span className={`badge ${PRIORITY_CLASS[t.priority] || 'badge--gray'}`}>
                {PRIORITY_LABELS[t.priority] || t.priority}
              </span>
              <div>
                <p className="cr-analysis-list-tag">
                  {t.test_id} · {t.title} · {TEST_TYPE_LABELS[t.test_type] || titleCase(t.test_type)}
                </p>
                <p className="cr-analysis-list-text">{t.description}</p>
                <p className="cr-analysis-list-mitigation">Expected: {t.expected_result}</p>
                {t.preconditions && <p className="cr-analysis-list-mitigation">Preconditions: {t.preconditions}</p>}
                {t.steps && t.steps.length > 0 && (
                  <ol className="tc-steps">
                    {t.steps.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ol>
                )}
                <ReferencesLine label="Traces to requirement(s)" refs={t.requirement_references} />
                <ReferencesLine label="Traces to risk(s)" refs={t.risk_references} />
                <RelatedFilesLine files={t.related_files} />
                <TestCaseEditControl testCase={t} changeRequestId={changeRequestId} token={token} onSaved={onSaved} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Module 17 Phase 6 (human editing): same pattern as TestCaseEditControl
 * above, applied to one ImplementationTask instead - see that control's
 * own docstring. */
function ImplementationTaskEditControl({ task, changeRequestId, token, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [taskName, setTaskName] = useState(task.task)
  const [description, setDescription] = useState(task.description)
  const [component, setComponent] = useState(task.component)
  const [priority, setPriority] = useState(task.priority)
  const [estimatedEffort, setEstimatedEffort] = useState(task.estimated_effort)
  const [dependencies, setDependencies] = useState(task.dependencies || '')
  const [ownerSuggestion, setOwnerSuggestion] = useState(task.owner_suggestion || '')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  function startEditing() {
    setTaskName(task.task)
    setDescription(task.description)
    setComponent(task.component)
    setPriority(task.priority)
    setEstimatedEffort(task.estimated_effort)
    setDependencies(task.dependencies || '')
    setOwnerSuggestion(task.owner_suggestion || '')
    setReason('')
    setError(null)
    setEditing(true)
  }

  function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    updateImplementationTask(
      changeRequestId,
      task.id,
      {
        task: taskName,
        description,
        component,
        priority,
        estimated_effort: estimatedEffort,
        dependencies: dependencies || null,
        owner_suggestion: ownerSuggestion || null,
        reason: reason || null,
      },
      token
    )
      .then(() => {
        setEditing(false)
        return onSaved()
      })
      .catch((err) => setError(err.message || 'Could not save this task.'))
      .finally(() => setSubmitting(false))
  }

  if (!editing) {
    return (
      <div className="ad-mt">
        {task.edited_by && <span className="badge ad-inline-badge badge--blue">Edited</span>}
        <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={startEditing}>
          Edit
        </button>
      </div>
    )
  }

  return (
    <form className="respond-form ad-mt" onSubmit={handleSubmit}>
      {error && <p className="cr-form-error">{error}</p>}
      <div className="cr-field">
        <label htmlFor={`ip-task-${task.id}`}>Task</label>
        <input
          id={`ip-task-${task.id}`}
          type="text"
          value={taskName}
          onChange={(e) => setTaskName(e.target.value)}
        />
      </div>
      <div className="cr-field">
        <label htmlFor={`ip-description-${task.id}`}>Description</label>
        <textarea
          id={`ip-description-${task.id}`}
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="status-form-row">
        <input
          type="text"
          className="cr-filter-select"
          value={component}
          onChange={(e) => setComponent(e.target.value)}
          aria-label="Component"
        />
        <select
          className="cr-filter-select"
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
          aria-label="Priority"
        >
          {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="status-form-row">
        <input
          type="text"
          className="cr-filter-select"
          value={estimatedEffort}
          onChange={(e) => setEstimatedEffort(e.target.value)}
          aria-label="Estimated effort"
        />
        <select
          className="cr-filter-select"
          value={ownerSuggestion}
          onChange={(e) => setOwnerSuggestion(e.target.value)}
          aria-label="Suggested owner"
        >
          <option value="">No suggestion</option>
          {Object.entries(ASSIGNMENT_ROLE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="cr-field">
        <label htmlFor={`ip-dependencies-${task.id}`}>
          Depends on <span className="cr-optional-tag">optional</span>
        </label>
        <input
          id={`ip-dependencies-${task.id}`}
          type="text"
          value={dependencies}
          onChange={(e) => setDependencies(e.target.value)}
        />
      </div>
      <div className="cr-field">
        <label htmlFor={`ip-reason-${task.id}`}>
          Reason for this edit <span className="cr-optional-tag">optional</span>
        </label>
        <textarea id={`ip-reason-${task.id}`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="status-form-row">
        <button type="submit" className="cr-btn cr-btn--primary cr-btn--small" disabled={submitting}>
          {submitting ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          className="cr-btn cr-btn--ghost cr-btn--small"
          onClick={() => {
            setEditing(false)
            setError(null)
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

/** Module 10: implementation plan shown as an ordered, numbered timeline -
 * the order is simply the order the AI returned implementation_plan in
 * (already the order it persisted in), not a computed schedule. */
function ImplementationPlanTab({ analysis, changeRequestId, token, onRegenerate, regenerating, onSaved }) {
  const items = analysis.implementation_tasks
  if (items.length === 0) return <EmptyTab text="No implementation plan was suggested." />
  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Implementation Plan</h2>
      <p className="cr-detail-text ig-intro">Shown in the order the AI suggested.</p>

      {/* Module 17 Phase 5 - see TestCasesTab's own identical banner for
          why this reuses analysis.is_outdated and the existing full
          re-analysis action rather than a separate computation/capability. */}
      {analysis.is_outdated && (
        <div className="outdated-banner">
          <span className="outdated-banner-text">
            <span className="outdated-banner-icon" aria-hidden="true">
              ⚠
            </span>
            <span>
              <strong>This implementation plan may be outdated.</strong> The change request has been edited since
              this analysis ran - regenerate to get a plan based on the current version.
            </span>
          </span>
          <button
            type="button"
            className="cr-btn cr-btn--primary cr-btn--small"
            onClick={onRegenerate}
            disabled={regenerating}
          >
            {regenerating ? 'Regenerating…' : 'Regenerate Implementation Plan'}
          </button>
        </div>
      )}

      <ol className="ip-timeline">
        {items.map((t, index) => (
          <li key={t.id} className="ip-step">
            <div className="ip-step-marker">
              <span className="ip-step-number">{index + 1}</span>
              {index < items.length - 1 && <span className="ip-step-line" aria-hidden="true" />}
            </div>
            <div className="ip-step-card">
              <div className="ip-step-header">
                <span className={`badge ${PRIORITY_CLASS[t.priority] || 'badge--gray'}`}>
                  {PRIORITY_LABELS[t.priority] || t.priority}
                </span>
                <span className="ip-step-task">{t.task}</span>
              </div>
              <p className="cr-detail-text">{t.description}</p>
              <dl className="ip-step-meta">
                <dt>Component</dt>
                <dd>{t.component}</dd>
                <dt>Estimated Effort</dt>
                <dd>{t.estimated_effort}</dd>
                {t.owner_suggestion && (
                  <>
                    <dt>Suggested Owner</dt>
                    <dd>{ASSIGNMENT_ROLE_LABELS[t.owner_suggestion] || titleCase(t.owner_suggestion)}</dd>
                  </>
                )}
              </dl>
              {t.dependencies && <p className="cr-analysis-list-mitigation">Depends on: {t.dependencies}</p>}
              <ReferencesLine label="Traces to requirement(s)" refs={t.requirement_references} />
              <RelatedFilesLine files={t.related_files} />
              <ImplementationTaskEditControl task={t} changeRequestId={changeRequestId} token={token} onSaved={onSaved} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

/** Module 17 Phase 4 (Test Cases & Implementation Plan 2.0 -
 * Traceability): Requirement -> Implementation Task -> Test Case, grouped
 * by requirement. The links themselves are computed server-side
 * (app/services/traceability_linkage.py) by keyword overlap - never
 * AI-generated, so a requirement with nothing listed under it just means
 * no task/test case's wording overlapped enough to link automatically,
 * not a real gap in coverage. Anything that didn't link to any
 * requirement is listed separately at the end, so nothing the AI produced
 * silently disappears from this view. */
function TraceabilityTab({ analysis }) {
  const requirements = analysis.requirements
  const risks = analysis.risks
  const testCases = analysis.test_cases
  const tasks = analysis.implementation_tasks

  if (requirements.length === 0 && risks.length === 0) {
    return (
      <EmptyTab text="No requirements or risks were extracted for this change, so there's nothing yet to trace implementation tasks or test cases back to." />
    )
  }

  const rows = requirements.map((r) => {
    const ref = `REQ-${r.id}`
    return {
      ref,
      requirement: r,
      tasks: tasks.filter((t) => t.requirement_references.includes(ref)),
      testCases: testCases.filter((t) => t.requirement_references.includes(ref)),
    }
  })

  const untracedTasks = tasks.filter((t) => t.requirement_references.length === 0)
  const untracedTestCases = testCases.filter((t) => t.requirement_references.length === 0)

  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Traceability</h2>
      <p className="cr-detail-text ig-intro">
        Requirement &rarr; Implementation Task &rarr; Test Case, computed by matching each task&apos;s/test
        case&apos;s own wording against this analysis&apos;s own requirements - never AI-generated, so an ID here
        never points at something that doesn&apos;t actually exist.
      </p>
      {rows.length === 0 ? (
        <p className="ad-empty">No requirements were extracted for this change.</p>
      ) : (
        <ul className="tl-list">
          {rows.map(({ ref, requirement, tasks: linkedTasks, testCases: linkedTestCases }) => (
            <li key={ref} className="tl-row">
              <div className="tl-requirement">
                <span className={`badge ${PRIORITY_CLASS[requirement.priority] || 'badge--gray'}`}>{ref}</span>
                <p className="cr-analysis-list-text">{requirement.description}</p>
              </div>
              <div className="tl-linked">
                <div className="tl-column">
                  <h4 className="tl-column-title">Implementation Tasks</h4>
                  {linkedTasks.length === 0 ? (
                    <p className="ad-empty">None linked.</p>
                  ) : (
                    <ul className="tl-column-list">
                      {linkedTasks.map((t) => (
                        <li key={t.id}>{t.task}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="tl-column">
                  <h4 className="tl-column-title">Test Cases</h4>
                  {linkedTestCases.length === 0 ? (
                    <p className="ad-empty">None linked.</p>
                  ) : (
                    <ul className="tl-column-list">
                      {linkedTestCases.map((t) => (
                        <li key={t.id}>
                          {t.test_id} &middot; {t.title}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {(untracedTasks.length > 0 || untracedTestCases.length > 0) && (
        <div className="tl-untraced">
          <h3 className="tl-untraced-title">Not linked to a specific requirement</h3>
          <p className="cr-detail-text ig-intro">
            Still part of the plan - their own wording just didn&apos;t overlap enough with any single requirement
            above to link automatically.
          </p>
          {untracedTasks.length > 0 && (
            <p className="cr-analysis-list-mitigation">
              Implementation tasks: {untracedTasks.map((t) => t.task).join(', ')}
            </p>
          )}
          {untracedTestCases.length > 0 && (
            <p className="cr-analysis-list-mitigation">
              Test cases: {untracedTestCases.map((t) => `${t.test_id} (${t.title})`).join(', ')}
            </p>
          )}
        </div>
      )}
    </section>
  )
}

/** Module 13 Phase 2/5: every analysis ever run for this change request,
 * newest first, with a "View changes vs. previous" action per row that
 * fetches a computed (not AI-written) diff against whichever analysis ran
 * immediately before it - mirrors the CR-version "Compare Versions" UI
 * Module 12 already built (same compare-table styling), just for
 * analysis-to-analysis instead of version-to-version.
 *
 * Deliberately tracks TWO different numbers per row, never conflating
 * them: "Analysis #N" is just this row's position in this list (oldest
 * run is #1, and a plain re-analyze with no content edit always adds a
 * new #N here) - it has nothing to do with the CR's own version number,
 * which only Module 12's edit-triggered versioning ever changes. "CR vX"
 * is that real content version this particular run analyzed. Two runs
 * can and often will share the same CR version (re-analyzing without
 * editing in between) - that's correct, not a bug, and is exactly why
 * these can't be the same number. */
function AnalysisHistoryTab({ history, currentAnalysisId, compareToId, compareResult, compareLoading, onToggleCompare }) {
  if (!history || history.length === 0) {
    return <EmptyTab text="No analysis history available." />
  }

  return (
    <section className="cr-detail-section">
      <h2 className="cr-section-title">Analysis History</h2>
      <p className="cr-detail-text ig-intro">
        Every AI analysis run for this change request, newest first - re-analyzing always adds a new entry here, even
        without editing the change request itself. &quot;View changes&quot; computes a diff against the analysis run
        immediately before it - no extra AI call, and it&apos;s never wrong about the numbers.
      </p>
      <ul className="versions-list">
        {history.map((a, index) => {
          const isOldest = index === history.length - 1
          const runNumber = history.length - index
          const recMeta = a.recommendation ? RECOMMENDATION_META[a.recommendation] : null
          const isOpen = compareToId === a.id

          return (
            <li key={a.id}>
              <div className="version-row">
                <div className="version-row-main">
                  <span className="version-row-number">
                    Analysis #{runNumber} <span className="version-row-cr-version">(CR v{a.change_request_version ?? '—'})</span>
                    {a.id === currentAnalysisId ? ' (current)' : ''}
                  </span>
                  <span className="version-row-summary">
                    {titleCase(a.category)} · {titleCase(a.complexity)} complexity · risk{' '}
                    {Math.round(a.risk_score)}/100
                    {recMeta ? ` · ${recMeta.label}` : ''}
                  </span>
                  <span className="version-row-meta">{formatDate(a.created_at)}</span>
                </div>
                {!isOldest && (
                  <button
                    type="button"
                    className="cr-btn cr-btn--secondary cr-btn--small"
                    onClick={() => onToggleCompare(a.id)}
                  >
                    {isOpen ? 'Hide changes' : 'View changes vs. previous'}
                  </button>
                )}
              </div>

              {isOpen && (
                <div className="cr-detail-section" style={{ marginTop: '0.5rem' }}>
                  {compareLoading && <p className="cr-list-status-text">Comparing…</p>}
                  {compareResult?.error && (
                    <p className="cr-list-status-text cr-list-status-text--error">{compareResult.error}</p>
                  )}
                  {compareResult?.fields && (
                    <>
                      {compareResult.is_significant_change && (
                        <div className="ad-missing-banner ad-missing-banner--alert">
                          <span className="ad-missing-count">!</span>
                          <span>
                            Significant change detected: {compareResult.significant_change_reasons.join(' ')}
                          </span>
                        </div>
                      )}
                      <table className="compare-table">
                        <thead>
                          <tr>
                            <th>Field</th>
                            <th>Previous</th>
                            <th>This Version</th>
                          </tr>
                        </thead>
                        <tbody>
                          {compareResult.fields
                            .filter((f) => f.status !== 'unchanged')
                            .map((f) => (
                              <tr key={f.field} className={`compare-row--${f.status}`}>
                                <td>{f.label}</td>
                                <td className="compare-old">{f.old_value ?? '—'}</td>
                                <td className="compare-new">{f.new_value ?? '—'}</td>
                              </tr>
                            ))}
                          {compareResult.fields.every((f) => f.status === 'unchanged') && (
                            <tr>
                              <td colSpan={3} className="compare-row--unchanged">
                                No field differences between these two analyses.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>

                      {(compareResult.requirements_added.length > 0 ||
                        compareResult.requirements_removed.length > 0) && (
                        <div className="ad-mt">
                          <p className="rk-card-label">Requirements</p>
                          {compareResult.requirements_added.map((r) => (
                            <p key={`req-add-${r}`} className="cr-analysis-list-text diff-added">
                              + {r}
                            </p>
                          ))}
                          {compareResult.requirements_removed.map((r) => (
                            <p key={`req-rem-${r}`} className="cr-analysis-list-text diff-removed">
                              − {r}
                            </p>
                          ))}
                        </div>
                      )}

                      {(compareResult.affected_components_added.length > 0 ||
                        compareResult.affected_components_removed.length > 0) && (
                        <div className="ad-mt">
                          <p className="rk-card-label">Affected Components</p>
                          {compareResult.affected_components_added.map((c) => (
                            <p key={`comp-add-${c}`} className="cr-analysis-list-text diff-added">
                              + {c}
                            </p>
                          ))}
                          {compareResult.affected_components_removed.map((c) => (
                            <p key={`comp-rem-${c}`} className="cr-analysis-list-text diff-removed">
                              − {c}
                            </p>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/** Module 15 (Repository Intelligence): this module's own headline
 * question - "which source files may actually be affected by this change
 * request?" - answered as its own tab rather than folded into the Impact
 * tab, since a repository finding is a different KIND of thing (evidence
 * about the actual codebase) from an AI-inferred affected component. Every
 * row here already passed the backend's hallucination guard (a file the
 * AI named that wasn't in the matcher's own candidate shortlist is never
 * persisted at all - app/services/repository_matcher.py) and its
 * match_label is always one of exactly three hedged values, computed
 * server-side from a numeric confidence score - never trusted from the
 * AI's own wording (see MATCH_LABEL_LABELS above). Version-aware like
 * everything else this module touches: `is_outdated`/`outdated_reasons`
 * are computed fresh by the backend every time this loads (Module 15
 * Phase 4), never stored - the same rule the analysis's own outdated
 * banner already follows. */
function RepositoryTab({ findings, scan, onRescan, rescanning, rescanError }) {
  const anyOutdated = findings.some((f) => f.is_outdated)
  const sorted = [...findings].sort((a, b) => b.confidence - a.confidence)

  return (
    <>
      <section className="cr-detail-section">
        <div className="ad-header--row">
          <div>
            <h2 className="cr-section-title">Repository / Affected Files</h2>
            <p className="cr-detail-text ig-intro">
              Source files from the project&apos;s own repository that may actually be affected by this change,
              matched against this analysis - never asserted with more certainty than the evidence supports (see
              each row&apos;s label and evidence below).
            </p>
            {scan && (
              <p className="cr-detail-text ad-mt">
                Last scan: {scan.file_count} file{scan.file_count === 1 ? '' : 's'} indexed
                {scan.skipped_count > 0 ? `, ${scan.skipped_count} skipped` : ''} on {formatDate(scan.started_at)}.
              </p>
            )}
          </div>
          <button
            type="button"
            className="cr-btn cr-btn--secondary cr-btn--small"
            onClick={onRescan}
            disabled={rescanning}
          >
            {rescanning ? 'Re-scanning…' : 'Re-scan Repository'}
          </button>
        </div>
        {rescanError && <p className="cr-form-error ad-header-error">{rescanError}</p>}
      </section>

      {anyOutdated && (
        <div className="outdated-banner">
          <span className="outdated-banner-text">
            <span className="outdated-banner-icon" aria-hidden="true">
              ⚠
            </span>
            <span>
              <strong>Some repository findings below may be outdated.</strong> The change request has been edited,
              a newer AI analysis has run, or a newer repository scan is available since these were generated - see
              each row for which.
            </span>
          </span>
          <button
            type="button"
            className="cr-btn cr-btn--primary cr-btn--small"
            onClick={onRescan}
            disabled={rescanning}
          >
            {rescanning ? 'Re-scanning…' : 'Re-scan Repository'}
          </button>
        </div>
      )}

      {sorted.length === 0 ? (
        <EmptyTab
          text={
            scan
              ? 'No files in the scanned repository were found to plausibly relate to this change request yet - ' +
                'click "Re-scan Repository" above to try again after the code has changed, or after re-analyzing.'
              : 'The repository hasn’t been scanned yet - click "Re-scan Repository" above to index it and ' +
                'match it against this change request.'
          }
        />
      ) : (
        <section className="cr-detail-section">
          <ul className="cr-analysis-list">
            {sorted.map((f) => (
              <li key={f.id} className="cr-analysis-list-item">
                <span className={`badge ${MATCH_LABEL_CLASS[f.match_label] || 'badge--gray'}`}>
                  {MATCH_LABEL_LABELS[f.match_label] || titleCase(f.match_label)}
                </span>
                <span className={`badge ${LEVEL_CLASS[f.impact_level] || 'badge--gray'}`}>
                  {titleCase(f.impact_level)} impact
                </span>
                {f.is_outdated && <span className="badge badge--amber">Outdated</span>}
                <div>
                  <p className="cr-analysis-list-tag">
                    {f.file_path}
                    {f.language ? ` · ${titleCase(f.language)}` : ''}
                  </p>
                  <p className="cr-analysis-list-text">{f.reason}</p>
                  <ConfidenceBar value={f.confidence} />
                  <p className="cr-analysis-list-mitigation">Evidence: {f.evidence}</p>
                  {f.is_outdated && f.outdated_reasons.length > 0 && (
                    <p className="cr-analysis-list-mitigation">Why outdated: {f.outdated_reasons.join(' ')}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

/** Module 7: the dedicated AI Analysis Dashboard - header, five summary
 * cards, and a 10-tab breakdown of the latest analysis for one change
 * request. Pure read view of GET /api/change-requests/{id} (title) and
 * GET /api/change-requests/{id}/analysis (everything else, Module 6) - no
 * AI calls happen here, and every number/label on the page traces back to
 * a real stored field (nothing invented for the demo). */
export default function AnalysisDashboardPage({ id, onBackToDetail, onBackToList }) {
  const { token } = useAuth()
  const [changeRequest, setChangeRequest] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')
  // Spec: clicking the "CR v1"/"Analysis v1" badges at the top of the page
  // should jump straight to the version/analysis history below, rather
  // than making the visitor go hunt for the History tab themselves.
  const tabContentRef = useRef(null)
  const goToHistoryTab = useCallback(() => {
    setActiveTab('history')
    tabContentRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])
  const [regenerating, setRegenerating] = useState(false)
  const [regenerateError, setRegenerateError] = useState(null)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState(null)
  // Module 20 (Version-Aware Reports): the structured 409 the report
  // endpoint now returns when the current version hasn't been analyzed
  // (rather than silently building a misleading report) - null whenever
  // the last download attempt didn't hit that specific case. The full
  // version list backs the "generate a report for an earlier version"
  // picker.
  const [reportMismatch, setReportMismatch] = useState(null)
  const [reportableVersions, setReportableVersions] = useState([])
  const [selectedReportVersion, setSelectedReportVersion] = useState('')
  // Module 13 Phase 2/5: analysis history + compare.
  const [analysisHistory, setAnalysisHistory] = useState([])
  const [compareToId, setCompareToId] = useState(null)
  const [compareResult, setCompareResult] = useState(null)
  const [compareLoading, setCompareLoading] = useState(false)
  // Module 14 Phase 1: the same AI-derived recommended-approval-types list
  // ChangeRequestDetail.jsx's Approvals section already fetches - shown
  // here too so "what does this need to move forward" is visible without
  // leaving the Analysis Dashboard.
  const [recommendedApprovals, setRecommendedApprovals] = useState([])
  // Module 15 (Repository Intelligence).
  const [repositoryFindings, setRepositoryFindings] = useState([])
  const [repositoryScan, setRepositoryScan] = useState(null)
  const [rescanning, setRescanning] = useState(false)
  const [rescanError, setRescanError] = useState(null)

  const loadAll = useCallback(() => {
    return Promise.all([
      getChangeRequest(id, token),
      getAnalysis(id, token),
      getAnalysisHistory(id, token),
      getRecommendedApprovals(id, token),
      getRepositoryFindings(id, token),
      // 404s (as an ApiError) if no repository scan has ever been run at
      // all - a normal, not-yet-happened state for a fresh install, not a
      // page-level error, so it's swallowed to null right here rather than
      // failing the whole Promise.all.
      getLatestRepositoryScan(token).catch(() => null),
      // Module 20: powers the "generate a report for an earlier version"
      // picker below - never fails the whole page load if it errors (a
      // report picker that's temporarily unavailable shouldn't block
      // seeing the analysis itself).
      listReportableVersions(id, token).catch(() => []),
    ]).then(([cr, an, hist, recommended, findings, scan, versions]) => {
      setChangeRequest(cr)
      setAnalysis(an)
      setAnalysisHistory(hist)
      setRecommendedApprovals(recommended)
      setReportableVersions(versions)
      setRepositoryFindings(findings)
      setRepositoryScan(scan)
    })
  }, [id, token])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setActiveTab('overview')
    setCompareToId(null)
    setCompareResult(null)

    loadAll()
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load this analysis.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, token])

  /** Module 10: "Regenerate Analysis" - the architecture already supports
   * re-running the AI on this change request (Module 6's POST .../analyze,
   * already used by the "Re-analyze" button on the change request's detail
   * page). This just exposes the same action from the dashboard itself, so
   * a fresh run's results (new test cases, new implementation plan, etc.)
   * show up here without navigating away first. */
  function handleRegenerate() {
    setRegenerating(true)
    setRegenerateError(null)
    setCompareToId(null)
    setCompareResult(null)
    // A fresh analysis run means whatever "current version has not been
    // analyzed" warning was showing (Module 20) is about to be stale
    // either way - cleared here rather than left displayed against an
    // analysis that no longer reflects the CR's real state.
    setReportMismatch(null)
    setDownloadError(null)
    analyzeChangeRequest(id, token)
      .then(() => loadAll())
      .catch((err) => setRegenerateError(err.message || 'Regenerating the analysis failed. Please try again.'))
      .finally(() => setRegenerating(false))
  }

  /** Module 15 (Repository Intelligence): "Re-scan Repository" - scans the
   * configured repository fresh, then re-runs the CR→file match against
   * this analysis, then reloads everything so the Repository tab (and any
   * related_files line elsewhere on this page) reflects the new scan.
   * Two backend calls in sequence rather than one combined endpoint - the
   * backend deliberately keeps "scan the repo" and "match this CR against
   * the latest scan" as two separate, independently-triggerable actions
   * (Phase 1 and Phase 3), and this button is just the one place the
   * frontend chains them together for convenience. */
  function handleRescanRepository() {
    setRescanning(true)
    setRescanError(null)
    triggerRepositoryScan(token)
      .then(() => triggerRepositoryMatch(id, token))
      .then(() => loadAll())
      .catch((err) => setRescanError(err.message || 'Re-scanning the repository failed. Please try again.'))
      .finally(() => setRescanning(false))
  }

  /** Module 13 Phase 2/5: fetch the computed diff between analysis `id`
   * (the "to" side) and whichever analysis ran immediately before it - the
   * History tab's "View changes vs. previous" button. */
  function handleToggleAnalysisCompare(analysisId) {
    if (compareToId === analysisId) {
      setCompareToId(null)
      setCompareResult(null)
      return
    }
    setCompareToId(analysisId)
    setCompareResult(null)
    setCompareLoading(true)
    compareAnalyses(id, { to: analysisId }, token)
      .then(setCompareResult)
      .catch((err) => setCompareResult({ error: err.message || 'Could not compare these analyses.' }))
      .finally(() => setCompareLoading(false))
  }

  /** Module 11 (version-aware since Module 20): "Download Report" - builds
   * the PDF entirely from already-persisted data (no re-running the AI).
   * With no `version`, this is "the current report" - which now comes
   * back as a structured 409 (spec section 3's "current CR version has
   * not been analyzed" case) instead of a misleading current-looking
   * report, whenever the CR has been edited since its last analysis;
   * passing an explicit `version` (from the mismatch banner's "view that
   * version instead" button, or from the version picker below) always
   * generates a clearly-labeled historical report for that version. */
  function handleDownloadReport(version) {
    setDownloading(true)
    setDownloadError(null)
    setReportMismatch(null)
    downloadReport(id, token, version)
      .then(() => {
        // Refresh the version picker's has_analysis flags - best-effort,
        // never treated as the download itself having failed.
        listReportableVersions(id, token)
          .then(setReportableVersions)
          .catch(() => {})
      })
      .catch((err) => {
        if (err.status === 409 && err.detail && typeof err.detail === 'object') {
          setReportMismatch(err.detail)
        } else {
          setDownloadError(err.message || 'Generating the report failed. Please try again.')
        }
      })
      .finally(() => setDownloading(false))
  }

  const crCode = `CR-${String(id).padStart(4, '0')}`

  const breadcrumb = (current) => (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <button type="button" className="breadcrumb-link" onClick={onBackToList}>
        Change Requests
      </button>
      <span className="breadcrumb-separator">/</span>
      <button type="button" className="breadcrumb-link" onClick={onBackToDetail}>
        {crCode}
      </button>
      <span className="breadcrumb-separator">/</span>
      <span className="breadcrumb-current">{current}</span>
    </nav>
  )

  if (loading) {
    return (
      <div className="ad-shell">
        <p className="cr-list-status-text">Loading analysis…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="ad-shell">
        {breadcrumb('AI Analysis')}
        <p className="cr-list-status-text cr-list-status-text--error">{error}</p>
      </div>
    )
  }

  const riskOutOf10 = analysis.risk_score / 10
  const recMeta = analysis.recommendation ? RECOMMENDATION_META[analysis.recommendation] : null
  const effort = parseEffortEstimate(analysis.effort_estimate)
  const unresolvedQuestions = analysis.clarification_questions.filter((q) => !q.resolved)

  return (
    <div className="ad-shell">
      {breadcrumb('AI Analysis')}

      <div className="ad-header ad-header--row">
        <div>
          <span className="ad-header-code">{crCode}</span>
          <h1>{changeRequest.title}</h1>
          {/* Module 14 Phase 1: makes version-awareness visible, not just
              structurally true - the CR's current version and the version
              this specific analysis ran against, side by side, plus the
              CR's real workflow status. is_outdated below already covers
              *whether* these two numbers disagree; this is just always
              showing the numbers themselves. */}
          <div className="ad-header-meta">
            <button
              type="button"
              className="badge version-badge version-badge--clickable"
              onClick={goToHistoryTab}
              title="View every analysis run for this change request"
            >
              CR v{changeRequest.current_version || 1}
            </button>
            <button
              type="button"
              className="badge version-badge version-badge--clickable"
              onClick={goToHistoryTab}
              title="View every analysis run for this change request"
            >
              Analysis v{analysis.change_request_version ?? '—'}
            </button>
            <span className="badge badge--gray">{changeRequest.status_label || titleCase(changeRequest.status)}</span>
          </div>
        </div>
        <div className="ad-header-actions">
          <div className="ad-header-buttons">
            <button
              type="button"
              className="cr-btn cr-btn--secondary"
              onClick={handleRegenerate}
              disabled={regenerating}
            >
              {regenerating ? 'Regenerating… this can take up to a minute' : 'Regenerate Analysis'}
            </button>
            <button
              type="button"
              className="cr-btn cr-btn--primary"
              onClick={() => handleDownloadReport()}
              disabled={downloading}
            >
              {downloading ? 'Generating report…' : 'Download Report'}
            </button>
          </div>
          {regenerateError && <p className="cr-form-error ad-header-error">{regenerateError}</p>}
          {downloadError && <p className="cr-form-error ad-header-error">{downloadError}</p>}

          {/* Module 20 spec section 3: never show a misleading "current"
              report - if the current version hasn't been analyzed, show
              the warning plus both ways forward (re-analyze, or fall back
              to the last version that WAS analyzed) instead of a PDF. */}
          {reportMismatch && (
            <div className="outdated-banner ad-report-mismatch">
              <span className="outdated-banner-text">
                <span className="outdated-banner-icon" aria-hidden="true">
                  ⚠
                </span>
                <span>
                  <strong>Current CR version has not been analyzed.</strong> Version{' '}
                  {reportMismatch.cr_version} of this change request has no analysis of its own yet, so a
                  "current" report can't be generated without mixing data from two different versions.
                </span>
              </span>
              <div className="ad-report-mismatch-actions">
                <button
                  type="button"
                  className="cr-btn cr-btn--primary cr-btn--small"
                  onClick={handleRegenerate}
                  disabled={regenerating}
                >
                  {regenerating ? 'Regenerating…' : 'Re-analyze'}
                </button>
                {reportMismatch.last_analyzed_version != null && (
                  <button
                    type="button"
                    className="cr-btn cr-btn--secondary cr-btn--small"
                    onClick={() => handleDownloadReport(reportMismatch.last_analyzed_version)}
                    disabled={downloading}
                  >
                    View Version {reportMismatch.last_analyzed_version} Report Instead
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Module 20 spec section 7: an authorized user (anyone who can
              already view this change request) can pull a report for any
              specific past version on purpose, regardless of whether the
              current version is up to date. Only worth showing once
              there's more than one version to choose from. */}
          {reportableVersions.length > 1 && (
            <div className="ad-report-version-picker">
              <label htmlFor="report-version-select">Report for a specific version</label>
              <select
                id="report-version-select"
                value={selectedReportVersion}
                onChange={(event) => setSelectedReportVersion(event.target.value)}
              >
                <option value="">Current (Version {changeRequest.current_version || 1})</option>
                {reportableVersions.map((v) => (
                  <option key={v.version_number} value={v.version_number}>
                    Version {v.version_number}
                    {v.is_current ? ' (current)' : ''} — {v.has_analysis ? 'analyzed' : 'not analyzed'}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="cr-btn cr-btn--secondary cr-btn--small"
                onClick={() =>
                  handleDownloadReport(selectedReportVersion ? Number(selectedReportVersion) : undefined)
                }
                disabled={downloading}
              >
                {downloading ? 'Generating…' : 'Generate Report'}
              </button>
            </div>
          )}
        </div>
      </div>

      {analysis.is_outdated && (
        <div className="outdated-banner">
          <span className="outdated-banner-text">
            <span className="outdated-banner-icon" aria-hidden="true">
              ⚠
            </span>
            <span>
              <strong>This analysis is outdated.</strong> The change request has been edited since this analysis
              ran - regenerate it to see results that reflect the current version.
            </span>
          </span>
          <button
            type="button"
            className="cr-btn cr-btn--primary cr-btn--small"
            onClick={handleRegenerate}
            disabled={regenerating}
          >
            {regenerating ? 'Regenerating…' : 'Regenerate Analysis'}
          </button>
        </div>
      )}

      <div className="ad-summary-grid">
        <div className="ad-summary-card">
          <span className="ad-summary-label">Risk Score</span>
          <div className="ad-summary-body">
            <Gauge pct={riskOutOf10 * 10} color={riskTone(riskOutOf10)}>
              <span className="ad-gauge-value">{riskOutOf10.toFixed(1)}</span>
            </Gauge>
            <span className="ad-summary-sub">out of 10</span>
          </div>
        </div>

        <div className="ad-summary-card">
          <span className="ad-summary-label">Complexity</span>
          <div className="ad-summary-body ad-summary-body--center">
            <div className="ad-summary-stack">
              <span className={`badge ad-summary-badge ${LEVEL_CLASS[analysis.complexity] || 'badge--gray'}`}>
                {titleCase(analysis.complexity)}
              </span>
              {analysis.complexity_confidence && (
                <ConfidenceLevelBadge level={analysis.complexity_confidence} />
              )}
            </div>
          </div>
        </div>

        <div className="ad-summary-card">
          <span className="ad-summary-label">Estimated Effort</span>
          <div className="ad-summary-body ad-summary-body--center">
            <div className="ad-summary-stack">
              <span className="ad-summary-text">{effort?.total || 'Insufficient information.'}</span>
              {analysis.effort_confidence && <ConfidenceLevelBadge level={analysis.effort_confidence} />}
            </div>
          </div>
        </div>

        <div className="ad-summary-card">
          <span className="ad-summary-label">AI Confidence</span>
          <div className="ad-summary-body">
            <Gauge pct={analysis.confidence_score} color="#4338ca">
              <span className="ad-gauge-value">{Math.round(analysis.confidence_score)}%</span>
            </Gauge>
          </div>
        </div>

        <div className={`ad-summary-card ad-recommendation-card ad-recommendation-card--${recMeta?.tone || 'neutral'}`}>
          <span className="ad-summary-label">Recommendation</span>
          <div className="ad-summary-body ad-summary-body--center">
            {recMeta ? (
              <span className="ad-recommendation-value">
                <span aria-hidden="true">{recMeta.emoji}</span> {recMeta.label}
              </span>
            ) : (
              <span className="ad-summary-text">—</span>
            )}
          </div>
        </div>
      </div>

      <div className="ad-tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            className={`ad-tab${activeTab === tab.key ? ' ad-tab--active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
            {tab.key === 'missing' && unresolvedQuestions.length > 0 && (
              <span className="ad-tab-count">{unresolvedQuestions.length}</span>
            )}
          </button>
        ))}
      </div>

      <div className="ad-tab-content" ref={tabContentRef}>
        {activeTab === 'overview' && (
          <OverviewTab analysis={analysis} recommendedApprovals={recommendedApprovals} />
        )}
        {activeTab === 'requirements' && (
          <RequirementsTab analysis={analysis} changeRequestId={id} token={token} onReviewed={loadAll} />
        )}
        {activeTab === 'impact' && (
          <ImpactTab analysis={analysis} changeRequest={changeRequest} crCode={crCode} />
        )}
        {activeTab === 'repository' && (
          <RepositoryTab
            findings={repositoryFindings}
            scan={repositoryScan}
            onRescan={handleRescanRepository}
            rescanning={rescanning}
            rescanError={rescanError}
          />
        )}
        {activeTab === 'dependencies' && <DependenciesTab analysis={analysis} />}
        {activeTab === 'risks' && <RisksTab analysis={analysis} />}
        {activeTab === 'security' && (
          <SecurityTab analysis={analysis} changeRequestId={id} token={token} onReviewed={loadAll} />
        )}
        {activeTab === 'effort' && <EffortTab analysis={analysis} effort={effort} />}
        {activeTab === 'missing' && (
          <MissingInfoTab analysis={analysis} changeRequestId={id} token={token} onAnswered={loadAll} />
        )}
        {activeTab === 'tests' && (
          <TestCasesTab
            analysis={analysis}
            changeRequestId={id}
            token={token}
            onRegenerate={handleRegenerate}
            regenerating={regenerating}
            onSaved={loadAll}
          />
        )}
        {activeTab === 'plan' && (
          <ImplementationPlanTab
            analysis={analysis}
            changeRequestId={id}
            token={token}
            onRegenerate={handleRegenerate}
            regenerating={regenerating}
            onSaved={loadAll}
          />
        )}
        {activeTab === 'traceability' && <TraceabilityTab analysis={analysis} />}
        {activeTab === 'history' && (
          <AnalysisHistoryTab
            history={analysisHistory}
            currentAnalysisId={analysis.id}
            compareToId={compareToId}
            compareResult={compareResult}
            compareLoading={compareLoading}
            onToggleCompare={handleToggleAnalysisCompare}
          />
        )}
      </div>
    </div>
  )
}
