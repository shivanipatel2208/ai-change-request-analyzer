import { useState } from 'react'
import './App.css'
import { AuthProvider, useAuth } from './context/AuthContext'
import AuthenticatedHome from './pages/AuthenticatedHome'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'

function AppContent() {
  const { isAuthenticated, initializing } = useAuth()
  const [authView, setAuthView] = useState('login') // 'login' | 'register'

  if (initializing) {
    return (
      <div className="app-loading">
        <p>Loading…</p>
      </div>
    )
  }

  if (isAuthenticated) {
    return <AuthenticatedHome />
  }

  return authView === 'login' ? (
    <LoginPage onSwitchToRegister={() => setAuthView('register')} />
  ) : (
    <RegisterPage onSwitchToLogin={() => setAuthView('login')} />
  )
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}

export default App
