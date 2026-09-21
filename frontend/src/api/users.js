import { apiRequest } from './client'

// Module 12 Phase 3: a simple user directory for the assignment picker.
export function listUsers(token) {
  return apiRequest('/api/users', { token })
}
