import { apiRequest } from './client'

export function registerRequest(name, email, password, confirmPassword) {
  return apiRequest('/auth/register', {
    method: 'POST',
    body: { name, email, password, confirm_password: confirmPassword },
  })
}

export function loginRequest(email, password, rememberMe) {
  return apiRequest('/auth/login', {
    method: 'POST',
    body: { email, password, remember_me: rememberMe },
  })
}

export function getCurrentUser(token) {
  return apiRequest('/auth/me', { token })
}

export function logoutRequest(token) {
  return apiRequest('/auth/logout', { method: 'POST', token })
}
