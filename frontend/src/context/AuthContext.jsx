import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getCurrentUser, loginRequest, logoutRequest, registerRequest } from '../api/auth'

const AuthContext = createContext(null)

const STORAGE_KEY = 'acra_auth' // AI Change Request Analyzer

function loadStoredToken() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw)?.access_token ?? null : null
  } catch {
    // localStorage unavailable (private browsing, disabled, etc.) - just start logged out.
    return null
  }
}

function saveStoredToken(accessToken) {
  try {
    if (accessToken) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ access_token: accessToken }))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // Nothing we can do - auth just won't persist across page reloads.
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [initializing, setInitializing] = useState(true)

  // On first load, if a token was saved from a previous session, verify it's
  // still valid (not expired) before trusting it.
  useEffect(() => {
    const storedToken = loadStoredToken()
    if (!storedToken) {
      setInitializing(false)
      return
    }
    getCurrentUser(storedToken)
      .then((freshUser) => {
        setToken(storedToken)
        setUser(freshUser)
      })
      .catch(() => {
        saveStoredToken(null)
      })
      .finally(() => setInitializing(false))
  }, [])

  const applyAuthResponse = useCallback((data) => {
    saveStoredToken(data.access_token)
    setToken(data.access_token)
    setUser(data.user)
  }, [])

  const login = useCallback(
    async (email, password, rememberMe) => {
      const data = await loginRequest(email, password, rememberMe)
      applyAuthResponse(data)
    },
    [applyAuthResponse]
  )

  const register = useCallback(
    async (name, email, password, confirmPassword) => {
      const data = await registerRequest(name, email, password, confirmPassword)
      applyAuthResponse(data)
    },
    [applyAuthResponse]
  )

  const logout = useCallback(async () => {
    if (token) {
      try {
        await logoutRequest(token)
      } catch {
        // Best-effort - clear local state regardless of whether the backend call succeeds.
      }
    }
    saveStoredToken(null)
    setToken(null)
    setUser(null)
  }, [token])

  const value = useMemo(
    () => ({ user, token, initializing, isAuthenticated: Boolean(user), login, register, logout }),
    [user, token, initializing, login, register, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}
