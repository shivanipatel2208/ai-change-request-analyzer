import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  createApprovalRule,
  createUser,
  deleteApprovalRule,
  getSystemSettings,
  listApprovalRules,
  listAuditLog,
  listPermissions,
  listUsers,
  updateApprovalRule,
  updateCrCategories,
  updatePermissions,
  updateUser,
} from '../api/admin'
import '../styles/dashboard.css'
import '../styles/change-request-form.css'
import '../styles/workflow.css'
import '../styles/analysis-dashboard.css'
import '../styles/admin.css'

// Module 21 (Administration & Configuration). Mirrors ROLE_LABELS/etc in
// other pages (module-local label maps rather than a shared import - see
// e.g. MyWorkPage.jsx's own ROLE_LABELS) - here matching
// backend/app/services/workflow_rules.py::USER_ROLE_LABELS exactly.
const ROLE_LABELS = {
  admin: 'Admin',
  requester: 'Requester',
  engineer: 'Engineer',
  reviewer: 'Reviewer',
  security_reviewer: 'Security Reviewer',
  approver: 'Approver',
  product_manager: 'Manager',
}
const ROLE_OPTIONS = Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))

const CAPABILITY_LABELS = {
  cr_create: 'Create Change Requests',
  cr_edit: 'Edit Change Requests',
  status_change: 'Change Status',
  assignment: 'Assign Users',
  approval: 'Approve',
  rejection: 'Reject / Request Changes',
  comments: 'Comment',
  reports: 'Download Reports',
  administration: 'Administration',
}
const CAPABILITY_ORDER = Object.keys(CAPABILITY_LABELS)

const APPROVAL_TYPE_LABELS = {
  technical: 'Technical',
  security: 'Security',
  product: 'Product',
  engineering_manager: 'Engineering Manager',
  director: 'Director',
  qa: 'QA',
  dba: 'DBA',
  release: 'Release',
  general: 'General',
}
const APPROVAL_TYPE_OPTIONS = Object.entries(APPROVAL_TYPE_LABELS).map(([value, label]) => ({ value, label }))

const ADMIN_ACTION_LABELS = {
  user_created: 'User created',
  user_role_changed: 'Role changed',
  user_activated: 'User activated',
  user_deactivated: 'User deactivated',
  permission_changed: 'Permission changed',
  approval_rule_created: 'Approval rule added',
  approval_rule_updated: 'Approval rule updated',
  approval_rule_deleted: 'Approval rule deleted',
  system_setting_changed: 'System setting changed',
}

const TABS = [
  { key: 'users', label: 'Users' },
  { key: 'permissions', label: 'Roles & Permissions' },
  { key: 'approval-rules', label: 'Approval Rules' },
  { key: 'system-settings', label: 'System Settings' },
  { key: 'audit-log', label: 'Audit Log' },
]

function formatDateTime(isoString) {
  if (!isoString) return '—'
  try {
    return new Date(isoString).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return isoString
  }
}

function errorMessage(err, fallback) {
  return err?.message || fallback
}

export default function AdminPage() {
  const { user, token } = useAuth()
  const [activeTab, setActiveTab] = useState('users')

  if (user?.role !== 'admin') {
    return (
      <div className="ad-shell">
        <p className="ad-empty">This section is only available to Admin accounts.</p>
      </div>
    )
  }

  return (
    <div className="ad-shell">
      <div className="ad-header">
        <h1>Administration</h1>
      </div>

      <div className="ad-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`ad-tab${activeTab === tab.key ? ' ad-tab--active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="ad-tab-content">
        {activeTab === 'users' && <UsersTab token={token} currentUser={user} />}
        {activeTab === 'permissions' && <PermissionsTab token={token} />}
        {activeTab === 'approval-rules' && <ApprovalRulesTab token={token} />}
        {activeTab === 'system-settings' && <SystemSettingsTab token={token} />}
        {activeTab === 'audit-log' && <AuditLogTab token={token} />}
      </div>
    </div>
  )
}

// --- Users -------------------------------------------------------------------

function UsersTab({ token, currentUser }) {
  const [users, setUsers] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [rowError, setRowError] = useState({})
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ name: '', email: '', password: '', role: 'engineer' })
  const [createError, setCreateError] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    listUsers(token)
      .then(setUsers)
      .catch((err) => setError(errorMessage(err, 'Could not load users.')))
      .finally(() => setLoading(false))
  }, [token])

  async function handleRoleChange(targetUser, role) {
    setRowError((prev) => ({ ...prev, [targetUser.id]: null }))
    try {
      const updated = await updateUser(token, targetUser.id, { role })
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
    } catch (err) {
      setRowError((prev) => ({ ...prev, [targetUser.id]: errorMessage(err, "Couldn't update this user's role.") }))
    }
  }

  async function handleToggleActive(targetUser) {
    setRowError((prev) => ({ ...prev, [targetUser.id]: null }))
    try {
      const updated = await updateUser(token, targetUser.id, { is_active: !targetUser.is_active })
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
    } catch (err) {
      setRowError((prev) => ({ ...prev, [targetUser.id]: errorMessage(err, "Couldn't update this user's status.") }))
    }
  }

  async function handleCreate(event) {
    event.preventDefault()
    setCreateError(null)
    setSaving(true)
    try {
      const created = await createUser(token, createForm)
      setUsers((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
      setCreateForm({ name: '', email: '', password: '', role: 'engineer' })
      setShowCreate(false)
    } catch (err) {
      setCreateError(errorMessage(err, "Couldn't create this user."))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="ad-empty">Loading users…</p>
  if (error) return <p className="cr-form-error">{error}</p>

  return (
    <div>
      <div className="admin-tab-toolbar">
        <p className="admin-tab-hint">Passwords are never shown or exported - only used to create the account.</p>
        <button type="button" className="cr-btn cr-btn--primary cr-btn--small" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? 'Cancel' : 'Add User'}
        </button>
      </div>

      {showCreate && (
        <form className="cr-section admin-inline-form" onSubmit={handleCreate}>
          {createError && <p className="cr-form-error">{createError}</p>}
          <div className="cr-field-row">
            <div className="cr-field">
              <label htmlFor="admin-new-name">Name</label>
              <input
                id="admin-new-name"
                type="text"
                value={createForm.name}
                onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
            </div>
            <div className="cr-field">
              <label htmlFor="admin-new-email">Email</label>
              <input
                id="admin-new-email"
                type="text"
                value={createForm.email}
                onChange={(e) => setCreateForm((f) => ({ ...f, email: e.target.value }))}
                required
              />
            </div>
          </div>
          <div className="cr-field-row">
            <div className="cr-field">
              <label htmlFor="admin-new-password">Password</label>
              <input
                id="admin-new-password"
                type="password"
                value={createForm.password}
                onChange={(e) => setCreateForm((f) => ({ ...f, password: e.target.value }))}
                required
                minLength={8}
              />
            </div>
            <div className="cr-field">
              <label htmlFor="admin-new-role">Role</label>
              <select
                id="admin-new-role"
                value={createForm.role}
                onChange={(e) => setCreateForm((f) => ({ ...f, role: e.target.value }))}
              >
                {ROLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="cr-form-actions">
            <button type="submit" className="cr-btn cr-btn--primary cr-btn--small" disabled={saving}>
              {saving ? 'Creating…' : 'Create User'}
            </button>
          </div>
        </form>
      )}

      <table className="requests-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.name}</td>
              <td>{u.email}</td>
              <td>
                <select value={u.role} onChange={(e) => handleRoleChange(u, e.target.value)} disabled={u.id === currentUser.id}>
                  {ROLE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <span className={`badge ${u.is_active ? 'badge--green' : 'badge--gray'}`}>
                  {u.is_active ? 'Active' : 'Inactive'}
                </span>
              </td>
              <td>
                <button
                  type="button"
                  className="cr-btn cr-btn--ghost cr-btn--small"
                  onClick={() => handleToggleActive(u)}
                  disabled={u.id === currentUser.id}
                >
                  {u.is_active ? 'Deactivate' : 'Activate'}
                </button>
                {rowError[u.id] && <p className="admin-row-error">{rowError[u.id]}</p>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- Roles & Permissions -------------------------------------------------------

function PermissionsTab({ token }) {
  const [permissions, setPermissions] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [saveMessage, setSaveMessage] = useState(null)

  useEffect(() => {
    listPermissions(token)
      .then(setPermissions)
      .catch((err) => setError(errorMessage(err, 'Could not load permissions.')))
      .finally(() => setLoading(false))
  }, [token])

  if (loading) return <p className="ad-empty">Loading permissions…</p>
  if (error) return <p className="cr-form-error">{error}</p>

  const roles = ROLE_OPTIONS.map((opt) => opt.value).filter((role) => role !== 'admin')
  const key = (role, capability) => `${role}:${capability}`
  const allowedFor = (role, capability) => {
    const pendingKey = key(role, capability)
    if (pendingKey in pending) return pending[pendingKey]
    const row = permissions.find((p) => p.role === role && p.capability === capability)
    return row ? row.allowed : true
  }

  function toggle(role, capability) {
    if (capability === 'administration') return // never editable
    setPending((prev) => ({ ...prev, [key(role, capability)]: !allowedFor(role, capability) }))
    setSaveMessage(null)
  }

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    setSaveMessage(null)
    const changes = Object.entries(pending).map(([k, allowed]) => {
      const [role, capability] = k.split(':')
      return { role, capability, allowed }
    })
    try {
      const updated = await updatePermissions(token, changes)
      setPermissions(updated)
      setPending({})
      setSaveMessage('Saved.')
    } catch (err) {
      setSaveError(errorMessage(err, "Couldn't save permission changes."))
    } finally {
      setSaving(false)
    }
  }

  const hasPending = Object.keys(pending).length > 0

  return (
    <div>
      <p className="admin-tab-hint">
        Admin accounts always have full access, regardless of this table. Administration itself can never be changed
        here - it's always Admin-only, so an admin can never be accidentally locked out.
      </p>

      {saveError && <p className="cr-form-error">{saveError}</p>}

      <div className="admin-matrix-scroll">
        <table className="requests-table admin-matrix">
          <thead>
            <tr>
              <th>Role</th>
              {CAPABILITY_ORDER.map((cap) => (
                <th key={cap}>{CAPABILITY_LABELS[cap]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="admin-matrix-locked-row">
              <td>Admin</td>
              {CAPABILITY_ORDER.map((cap) => (
                <td key={cap}>
                  <input type="checkbox" checked readOnly disabled />
                </td>
              ))}
            </tr>
            {roles.map((role) => (
              <tr key={role}>
                <td>{ROLE_LABELS[role]}</td>
                {CAPABILITY_ORDER.map((cap) => {
                  const locked = cap === 'administration'
                  return (
                    <td key={cap}>
                      <input
                        type="checkbox"
                        checked={locked ? false : allowedFor(role, cap)}
                        disabled={locked}
                        onChange={() => toggle(role, cap)}
                      />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="cr-form-actions">
        {saveMessage && <span className="admin-save-message">{saveMessage}</span>}
        <button type="button" className="cr-btn cr-btn--primary cr-btn--small" onClick={handleSave} disabled={!hasPending || saving}>
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
      </div>
    </div>
  )
}

// --- Approval Rules -------------------------------------------------------------

function ApprovalRulesTab({ token }) {
  const [rules, setRules] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [rowError, setRowError] = useState({})
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ rule_type: 'risk', match_value: '', approval_types: [] })
  const [createError, setCreateError] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    listApprovalRules(token)
      .then(setRules)
      .catch((err) => setError(errorMessage(err, 'Could not load approval rules.')))
      .finally(() => setLoading(false))
  }, [token])

  async function handleToggleEnabled(rule) {
    setRowError((prev) => ({ ...prev, [rule.id]: null }))
    try {
      const updated = await updateApprovalRule(token, rule.id, { enabled: !rule.enabled })
      setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
    } catch (err) {
      setRowError((prev) => ({ ...prev, [rule.id]: errorMessage(err, "Couldn't update this rule.") }))
    }
  }

  async function handleToggleApprovalType(rule, type) {
    const nextTypes = rule.approval_types.includes(type)
      ? rule.approval_types.filter((t) => t !== type)
      : [...rule.approval_types, type]
    if (nextTypes.length === 0) {
      setRowError((prev) => ({ ...prev, [rule.id]: 'At least one required approval type must stay selected.' }))
      return
    }
    setRowError((prev) => ({ ...prev, [rule.id]: null }))
    try {
      const updated = await updateApprovalRule(token, rule.id, { approval_types: nextTypes })
      setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
    } catch (err) {
      setRowError((prev) => ({ ...prev, [rule.id]: errorMessage(err, "Couldn't update this rule.") }))
    }
  }

  async function handleDelete(rule) {
    if (!window.confirm(`Delete this approval rule (${rule.match_value})?`)) return
    setRowError((prev) => ({ ...prev, [rule.id]: null }))
    try {
      await deleteApprovalRule(token, rule.id)
      setRules((prev) => prev.filter((r) => r.id !== rule.id))
    } catch (err) {
      setRowError((prev) => ({ ...prev, [rule.id]: errorMessage(err, "Couldn't delete this rule.") }))
    }
  }

  async function handleCreate(event) {
    event.preventDefault()
    setCreateError(null)
    if (createForm.approval_types.length === 0) {
      setCreateError('Select at least one required approval type.')
      return
    }
    setSaving(true)
    try {
      const created = await createApprovalRule(token, {
        ...createForm,
        match_value: createForm.match_value.trim().toLowerCase(),
      })
      setRules((prev) => [...prev, created])
      setCreateForm({ rule_type: 'risk', match_value: '', approval_types: [] })
      setShowCreate(false)
    } catch (err) {
      setCreateError(errorMessage(err, "Couldn't add this rule."))
    } finally {
      setSaving(false)
    }
  }

  function toggleCreateType(type) {
    setCreateForm((f) => ({
      ...f,
      approval_types: f.approval_types.includes(type) ? f.approval_types.filter((t) => t !== type) : [...f.approval_types, type],
    }))
  }

  if (loading) return <p className="ad-empty">Loading approval rules…</p>
  if (error) return <p className="cr-form-error">{error}</p>

  return (
    <div>
      <p className="admin-tab-hint">
        A risk rule fires when a change request's overall risk lands in that bucket; a category rule fires when its
        keyword appears in the AI's category, target system, or title. Every enabled, matching rule's approval types
        are combined - not a rule engine, just a simple lookup.
      </p>

      <div className="admin-tab-toolbar">
        <span />
        <button type="button" className="cr-btn cr-btn--primary cr-btn--small" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? 'Cancel' : 'Add Rule'}
        </button>
      </div>

      {showCreate && (
        <form className="cr-section admin-inline-form" onSubmit={handleCreate}>
          {createError && <p className="cr-form-error">{createError}</p>}
          <div className="cr-field-row">
            <div className="cr-field">
              <label htmlFor="admin-rule-type">Rule type</label>
              <select
                id="admin-rule-type"
                value={createForm.rule_type}
                onChange={(e) => setCreateForm((f) => ({ ...f, rule_type: e.target.value, match_value: '' }))}
              >
                <option value="risk">Risk level</option>
                <option value="category">Category keyword</option>
              </select>
            </div>
            <div className="cr-field">
              <label htmlFor="admin-rule-match">
                {createForm.rule_type === 'risk' ? 'Risk level' : 'Keyword'}
              </label>
              {createForm.rule_type === 'risk' ? (
                <select
                  id="admin-rule-match"
                  value={createForm.match_value}
                  onChange={(e) => setCreateForm((f) => ({ ...f, match_value: e.target.value }))}
                >
                  <option value="">Select…</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              ) : (
                <input
                  id="admin-rule-match"
                  type="text"
                  placeholder="e.g. checkout"
                  value={createForm.match_value}
                  onChange={(e) => setCreateForm((f) => ({ ...f, match_value: e.target.value }))}
                  required
                />
              )}
            </div>
          </div>
          <div className="cr-field">
            <label>Required approval types</label>
            <div className="admin-chip-row">
              {APPROVAL_TYPE_OPTIONS.map((opt) => (
                <button
                  type="button"
                  key={opt.value}
                  className={`admin-chip${createForm.approval_types.includes(opt.value) ? ' admin-chip--active' : ''}`}
                  onClick={() => toggleCreateType(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <div className="cr-form-actions">
            <button type="submit" className="cr-btn cr-btn--primary cr-btn--small" disabled={saving}>
              {saving ? 'Adding…' : 'Add Rule'}
            </button>
          </div>
        </form>
      )}

      <table className="requests-table">
        <thead>
          <tr>
            <th>Type</th>
            <th>Match</th>
            <th>Required Approvals</th>
            <th>Enabled</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rules.length === 0 && (
            <tr>
              <td colSpan={5}>
                <p className="ad-empty">No approval rules configured - add one above.</p>
              </td>
            </tr>
          )}
          {rules.map((rule) => (
            <tr key={rule.id}>
              <td>{rule.rule_type === 'risk' ? 'Risk level' : 'Category keyword'}</td>
              <td>{rule.match_value}</td>
              <td>
                <div className="admin-chip-row">
                  {APPROVAL_TYPE_OPTIONS.map((opt) => (
                    <button
                      type="button"
                      key={opt.value}
                      className={`admin-chip admin-chip--small${rule.approval_types.includes(opt.value) ? ' admin-chip--active' : ''}`}
                      onClick={() => handleToggleApprovalType(rule, opt.value)}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </td>
              <td>
                <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={() => handleToggleEnabled(rule)}>
                  {rule.enabled ? 'Enabled' : 'Disabled'}
                </button>
              </td>
              <td>
                <button type="button" className="cr-btn cr-btn--ghost cr-btn--small" onClick={() => handleDelete(rule)}>
                  Delete
                </button>
                {rowError[rule.id] && <p className="admin-row-error">{rowError[rule.id]}</p>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- System Settings --------------------------------------------------------------

function SystemSettingsTab({ token }) {
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [newCategory, setNewCategory] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  useEffect(() => {
    getSystemSettings(token)
      .then(setSettings)
      .catch((err) => setError(errorMessage(err, 'Could not load system settings.')))
      .finally(() => setLoading(false))
  }, [token])

  async function saveCategories(categories) {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await updateCrCategories(token, categories)
      setSettings((prev) => ({ ...prev, cr_categories: updated }))
    } catch (err) {
      setSaveError(errorMessage(err, "Couldn't update categories."))
    } finally {
      setSaving(false)
    }
  }

  function handleRemoveCategory(category) {
    saveCategories(settings.cr_categories.filter((c) => c !== category))
  }

  function handleAddCategory(event) {
    event.preventDefault()
    const trimmed = newCategory.trim()
    if (!trimmed || settings.cr_categories.some((c) => c.toLowerCase() === trimmed.toLowerCase())) {
      setNewCategory('')
      return
    }
    saveCategories([...settings.cr_categories, trimmed])
    setNewCategory('')
  }

  if (loading) return <p className="ad-empty">Loading system settings…</p>
  if (error) return <p className="cr-form-error">{error}</p>

  const { ai_provider: aiProvider, repository, knowledge_base: knowledgeBase } = settings

  return (
    <div>
      <div className="cr-section">
        <h3 className="cr-section-title">Change Request Categories</h3>
        <p className="admin-tab-hint">
          The reference list of category names used across the app's grouping and filters. This list is editable
          here; the keyword matching that assigns a specific change request to a category is not (kept simple
          rather than becoming a second rule engine to configure).
        </p>
        {saveError && <p className="cr-form-error">{saveError}</p>}
        <div className="admin-chip-row">
          {settings.cr_categories.map((category) => (
            <span key={category} className="admin-chip admin-chip--removable">
              {category}
              <button type="button" onClick={() => handleRemoveCategory(category)} disabled={saving} aria-label={`Remove ${category}`}>
                ×
              </button>
            </span>
          ))}
        </div>
        <form className="admin-inline-add" onSubmit={handleAddCategory}>
          <input
            type="text"
            placeholder="Add a category…"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            disabled={saving}
          />
          <button type="submit" className="cr-btn cr-btn--secondary cr-btn--small" disabled={saving}>
            Add
          </button>
        </form>
      </div>

      <div className="cr-section">
        <h3 className="cr-section-title">AI Provider</h3>
        <p className="admin-tab-hint">Read-only - change this by editing your backend .env file directly.</p>
        <dl className="admin-info-list">
          <dt>Provider</dt>
          <dd>{aiProvider.provider}</dd>
          <dt>Model</dt>
          <dd>{aiProvider.model}</dd>
          <dt>API key configured</dt>
          <dd>
            <span className={`badge ${aiProvider.api_key_configured ? 'badge--green' : 'badge--red'}`}>
              {aiProvider.api_key_configured ? 'Yes' : 'No'}
            </span>
          </dd>
          <dt>Embeddings supported</dt>
          <dd>{aiProvider.embeddings_supported ? 'Yes' : 'No'}</dd>
        </dl>
      </div>

      <div className="cr-section">
        <h3 className="cr-section-title">Repository</h3>
        <p className="admin-tab-hint">Read-only - change this by editing your backend .env file directly.</p>
        <dl className="admin-info-list">
          <dt>Repository root</dt>
          <dd className="admin-info-path">{repository.repository_root}</dd>
          <dt>Last scan</dt>
          <dd>{repository.last_scan_status || 'Never scanned'}</dd>
          <dt>Last scan file count</dt>
          <dd>{repository.last_scan_file_count ?? '—'}</dd>
          <dt>Last scan at</dt>
          <dd>{formatDateTime(repository.last_scan_at)}</dd>
        </dl>
      </div>

      <div className="cr-section">
        <h3 className="cr-section-title">Knowledge Base</h3>
        <p className="admin-tab-hint">Read-only - change this by editing your backend .env file directly.</p>
        <dl className="admin-info-list">
          <dt>Embedding model</dt>
          <dd>{knowledgeBase.embedding_model}</dd>
          <dt>Embeddings supported</dt>
          <dd>{knowledgeBase.embeddings_supported ? 'Yes' : 'No'}</dd>
          <dt>Documents uploaded</dt>
          <dd>{knowledgeBase.document_count}</dd>
        </dl>
      </div>

      <p className="admin-tab-hint">
        Priority values (Low/Medium/High/Critical) and the workflow status graph aren't configurable here - both are
        used throughout risk scoring, sorting, and the status lifecycle, so changing them safely would take more
        than a settings toggle.
      </p>
    </div>
  )
}

// --- Audit Log ----------------------------------------------------------------

const AUDIT_PAGE_SIZE = 25

function AuditLogTab({ token }) {
  const [data, setData] = useState(null)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    listAuditLog(token, { limit: AUDIT_PAGE_SIZE, offset })
      .then(setData)
      .catch((err) => setError(errorMessage(err, 'Could not load the audit log.')))
      .finally(() => setLoading(false))
  }, [token, offset])

  if (loading && !data) return <p className="ad-empty">Loading audit log…</p>
  if (error) return <p className="cr-form-error">{error}</p>

  const items = data?.items || []
  const total = data?.total || 0

  return (
    <div>
      <p className="admin-tab-hint">
        Every account, role, permission, approval-rule, and system-setting change made through the admin section -
        append-only, never editable here.
      </p>

      <table className="requests-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Actor</th>
            <th>Action</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && (
            <tr>
              <td colSpan={4}>
                <p className="ad-empty">No audit events yet.</p>
              </td>
            </tr>
          )}
          {items.map((item) => (
            <tr key={item.id}>
              <td>{formatDateTime(item.created_at)}</td>
              <td>{item.actor_name || 'System'}</td>
              <td>{ADMIN_ACTION_LABELS[item.action] || item.action}</td>
              <td>{item.detail || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="admin-pagination">
        <button
          type="button"
          className="cr-btn cr-btn--ghost cr-btn--small"
          onClick={() => setOffset((o) => Math.max(0, o - AUDIT_PAGE_SIZE))}
          disabled={offset === 0}
        >
          Previous
        </button>
        <span className="admin-tab-hint">
          {total === 0 ? '0 events' : `${offset + 1}–${Math.min(offset + AUDIT_PAGE_SIZE, total)} of ${total}`}
        </span>
        <button
          type="button"
          className="cr-btn cr-btn--ghost cr-btn--small"
          onClick={() => setOffset((o) => o + AUDIT_PAGE_SIZE)}
          disabled={offset + AUDIT_PAGE_SIZE >= total}
        >
          Next
        </button>
      </div>
    </div>
  )
}
