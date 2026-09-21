import { apiRequest } from './client'

// Module 21 (Administration & Configuration) - see backend/app/api/admin.py.
// Every one of these requires an Admin account server-side; the frontend
// also only ever shows the Admin page to an admin (see AppHeader's
// NAV_ITEMS filtering and AdminPage's own access check) - this file makes
// no access decisions of its own.

// --- Users -----------------------------------------------------------------

export function listUsers(token) {
  return apiRequest('/api/admin/users', { token })
}

export function createUser(token, { name, email, password, role }) {
  return apiRequest('/api/admin/users', { method: 'POST', token, body: { name, email, password, role } })
}

export function updateUser(token, userId, changes) {
  return apiRequest(`/api/admin/users/${userId}`, { method: 'PATCH', token, body: changes })
}

// --- System-level audit log --------------------------------------------------

export function listAuditLog(token, { limit = 50, offset = 0 } = {}) {
  return apiRequest(`/api/admin/audit-log?limit=${limit}&offset=${offset}`, { token })
}

// --- Permissions matrix ------------------------------------------------------

export function listPermissions(token) {
  return apiRequest('/api/admin/permissions', { token })
}

export function updatePermissions(token, permissions) {
  return apiRequest('/api/admin/permissions', { method: 'PUT', token, body: { permissions } })
}

// --- Approval rules ----------------------------------------------------------

export function listApprovalRules(token) {
  return apiRequest('/api/admin/approval-rules', { token })
}

export function createApprovalRule(token, rule) {
  return apiRequest('/api/admin/approval-rules', { method: 'POST', token, body: rule })
}

export function updateApprovalRule(token, ruleId, changes) {
  return apiRequest(`/api/admin/approval-rules/${ruleId}`, { method: 'PATCH', token, body: changes })
}

export function deleteApprovalRule(token, ruleId) {
  return apiRequest(`/api/admin/approval-rules/${ruleId}`, { method: 'DELETE', token })
}

// --- System settings ---------------------------------------------------------

export function getSystemSettings(token) {
  return apiRequest('/api/admin/system-settings', { token })
}

export function updateCrCategories(token, categories) {
  return apiRequest('/api/admin/system-settings/cr-categories', { method: 'PUT', token, body: { categories } })
}
