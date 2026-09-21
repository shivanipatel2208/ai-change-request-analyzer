import { useState } from 'react'
import AppHeader, { NAV_ITEMS } from '../components/AppHeader'
import { useAuth } from '../context/AuthContext'
import '../styles/home.css'
import AdminPage from './AdminPage'
import AnalyticsPage from './AnalyticsPage'
import ChangeRequestsPage from './ChangeRequestsPage'
import DashboardPage from './DashboardPage'
import KnowledgeBasePage from './KnowledgeBasePage'
import MyWorkPage from './MyWorkPage'
import NewChangeRequestPage from './NewChangeRequestPage'
import NotificationsPage from './NotificationsPage'
import ReportsPage from './ReportsPage'
import ComingSoonPage from './ComingSoonPage'

/** Shell for everything behind login: the header/nav lives here once, and
 * `activeView` (plain local state - no router in this project) decides
 * which page renders below it. Dashboard (Module 3), New Change Request
 * (Module 4), Change Requests (Module 5), Notifications (Module 12
 * Phase 5), My Work (Module 18 Phase 4), and Analytics (Module 19
 * Phase 6) are the real pages built so far; every other nav item still
 * shows a "coming later" placeholder.
 *
 * `jumpToCrId` lets Notifications/My Work/the header's own notification
 * bell (Module 18 Phase 6) hand off "open change request #N" to Change
 * Requests without a router - clicking a notification or a My Work row
 * sets it and switches the view; ChangeRequestsPage consumes it via its
 * `jumpToId` prop and reports back through `onJumpHandled` so it's only
 * used once. */
export default function AuthenticatedHome() {
  const { user, logout } = useAuth()
  const [activeView, setActiveView] = useState('dashboard')
  const [jumpToCrId, setJumpToCrId] = useState(null)

  const activeLabel = NAV_ITEMS.find((item) => item.key === activeView)?.label || activeView

  function openChangeRequest(id) {
    setJumpToCrId(id)
    setActiveView('change-requests')
  }

  let page
  if (activeView === 'dashboard') {
    page = <DashboardPage onNavigate={setActiveView} onOpenChangeRequest={openChangeRequest} />
  } else if (activeView === 'new-analysis') {
    page = <NewChangeRequestPage onNavigate={setActiveView} />
  } else if (activeView === 'change-requests') {
    page = (
      <ChangeRequestsPage
        onNavigate={setActiveView}
        jumpToId={jumpToCrId}
        onJumpHandled={() => setJumpToCrId(null)}
      />
    )
  } else if (activeView === 'my-work') {
    page = <MyWorkPage onOpenChangeRequest={openChangeRequest} />
  } else if (activeView === 'analytics') {
    page = <AnalyticsPage />
  } else if (activeView === 'notifications') {
    page = <NotificationsPage onOpenChangeRequest={openChangeRequest} />
  } else if (activeView === 'reports') {
    page = <ReportsPage onOpenChangeRequest={openChangeRequest} onNavigate={setActiveView} />
  } else if (activeView === 'knowledge-base') {
    page = <KnowledgeBasePage />
  } else if (activeView === 'settings') {
    // Module 21: AdminPage does its own admin-only gate (and AppHeader
    // already hides this nav item for non-admins), so nothing extra is
    // needed here.
    page = <AdminPage />
  } else {
    page = <ComingSoonPage label={activeLabel} />
  }

  return (
    <div className="app-shell">
      <AppHeader
        activeView={activeView}
        onNavigate={setActiveView}
        onOpenChangeRequest={openChangeRequest}
        user={user}
        onLogout={logout}
      />
      <main className="app-main">{page}</main>
    </div>
  )
}
