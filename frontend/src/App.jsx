import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { Suspense, lazy, useState, useEffect } from 'react'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import OfflineBanner from './components/OfflineBanner'
import PageLoader from './components/PageLoader'
import { getSession, logoutSession } from './utils/api'

function isChunkLoadError(error) {
  const text = `${error?.name || ''} ${error?.message || ''}`.toLowerCase()
  return text.includes('failed to fetch dynamically imported module') ||
    text.includes('loading chunk') ||
    text.includes('importing a module script failed')
}

function lazyWithRetry(importer) {
  return lazy(async () => {
    const retryKey = `ts_chunk_retry:${importer.toString().slice(0, 120)}`
    try {
      const module = await importer()
      sessionStorage.removeItem(retryKey)
      return module
    } catch (error) {
      if (isChunkLoadError(error) && !sessionStorage.getItem(retryKey)) {
        sessionStorage.setItem(retryKey, '1')
        window.location.reload()
        return new Promise(() => {})
      }
      throw error
    }
  })
}

const ResetPassword = lazyWithRetry(() => import('./pages/ResetPassword'))
const Login = lazyWithRetry(() => import('./pages/Login'))
const LoginChoice = lazyWithRetry(() => import('./pages/LoginChoice'))
const Home = lazyWithRetry(() => import('./pages/Home'))
const Contact = lazyWithRetry(() => import('./pages/Contact'))
const Feedback = lazyWithRetry(() => import('./pages/Feedback'))
const Dashboard = lazyWithRetry(() => import('./pages/Dashboard'))
const AdminDashboard = lazyWithRetry(() => import('./pages/AdminDashboard'))
const Trainers = lazyWithRetry(() => import('./pages/Trainers'))
const Requirements = lazyWithRetry(() => import('./pages/Requirements'))
const Emails = lazyWithRetry(() => import('./pages/Emails'))
const Inbox = lazyWithRetry(() => import('./pages/Inbox'))
const ClientRequests = lazyWithRetry(() => import('./pages/ClientRequests'))
const LinkedInSearch = lazyWithRetry(() => import('./pages/LinkedInSearch'))
const LinkedInPipeline = lazyWithRetry(() => import('./pages/LinkedInPipeline'))
const NaukriSearch = lazyWithRetry(() => import('./pages/NaukriSearch'))
const TrainerLocations = lazyWithRetry(() => import('./pages/TrainerLocations'))
const VoiceAIAssistant = lazyWithRetry(() => import('./pages/VoiceAIAssistant'))
const ClientPipeline = lazyWithRetry(() => import('./pages/ClientPipeline'))
const InterviewSchedules = lazyWithRetry(() => import('./pages/InterviewSchedules'))
const Invoices = lazyWithRetry(() => import('./pages/Invoices'))
const PurchaseOrders = lazyWithRetry(() => import('./pages/PurchaseOrders'))
const FinanceApprovals = lazyWithRetry(() => import('./pages/FinanceApprovals'))
const ResumeUpload = lazyWithRetry(() => import('./pages/ResumeUpload'))
const GmailCallback = lazyWithRetry(() => import('./pages/GmailCallback'))
const LinkedInCallback = lazyWithRetry(() => import('./pages/LinkedInCallback'))
const Admin = lazyWithRetry(() => import('./pages/Admin'))
const TocKnowledge = lazyWithRetry(() => import('./pages/TocKnowledge'))
const LabCost = lazyWithRetry(() => import('./pages/LabCost'))
const CommercialAnalysis = lazyWithRetry(() => import('./pages/CommercialAnalysis'))
const Shortlist = lazyWithRetry(() => import('./pages/Shortlist'))
const Shortlist1 = lazyWithRetry(() => import('./pages/Shortlist1'))
const Profile = lazyWithRetry(() => import('./pages/Profile'))
const ProfileReviews = lazyWithRetry(() => import('./pages/ProfileReviews'))
const TrainerPortal = lazyWithRetry(() => import('./pages/TrainerPortal'))
const TrainerApplications = lazyWithRetry(() => import('./pages/TrainerApplications'))
const PartnerOpportunities = lazyWithRetry(() => import('./pages/PartnerOpportunities'))
const ClientPortal = lazyWithRetry(() => import('./pages/ClientPortal'))

function PrivateRoute({ children, isLoggedIn, user, trainerOnly = false, clientOnly = false, adminOnly = false }) {
  if (!isLoggedIn) return <Navigate to="/login" replace />
  if (trainerOnly) return user?.role === 'trainer' ? children : <Navigate to="/dashboard" replace />
  if (clientOnly) return user?.role === 'client' ? children : <Navigate to="/dashboard" replace />
  if (!['admin', 'trainer', 'client'].includes(user?.role)) return <Navigate to="/login" replace />
  if (user?.role === 'trainer') return <Navigate to="/trainer-portal" replace />
  if (user?.role === 'client') return <Navigate to="/client-portal" replace />
  if (adminOnly && user?.role !== 'admin') return <Navigate to="/dashboard" replace />
  return children
}

function RouteBoundary({ children }) {
  const location = useLocation()
  return <ErrorBoundary resetKey={location.pathname}>{children}</ErrorBoundary>
}

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [user, setUser] = useState(null)
  const [authReady, setAuthReady] = useState(false)
  useEffect(() => {
    let active = true
    const expired = () => { setIsLoggedIn(false); setUser(null) }
    window.addEventListener('auth-expired', expired)
    getSession().then(account => { if (active) { setUser(account); setIsLoggedIn(true) } })
      .catch(() => { if (active) setIsLoggedIn(false) })
      .finally(() => { if (active) setAuthReady(true) })
    return () => { active = false; window.removeEventListener('auth-expired', expired) }
  }, [])
  const handleLogin = async () => {
    const account = await getSession()
    setUser(account)
    setIsLoggedIn(true)
    return account
  }
  const handleLogout = async () => {
    try { await logoutSession() } catch { /* expired sessions already require login */ }
    setIsLoggedIn(false)
    setUser(null)
  }
  if (!authReady) return <PageLoader />

  return (
    <BrowserRouter>
      <OfflineBanner />
      <Toaster
        position="top-right"
        toastOptions={{
          style: { borderRadius: '12px', fontFamily: "'Inter', sans-serif", fontSize: '14px' },
          success: { iconTheme: { primary: '#2563eb', secondary: '#fff' } },
        }}
      />
      <RouteBoundary>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/login" element={
            isLoggedIn ? <Navigate to={user?.role === 'trainer' ? '/trainer-portal' : user?.role === 'client' ? '/client-portal' : '/dashboard'} replace /> : <LoginChoice />
          } />
          <Route path="/admin-login" element={isLoggedIn ? <Navigate to={user?.role === 'trainer' ? '/trainer-portal' : user?.role === 'client' ? '/client-portal' : '/dashboard'} replace /> : <Login key="admin-login-page" onLogin={handleLogin} initialRole="admin" allowSignup={false} />} />
          <Route path="/trainer-login" element={isLoggedIn ? <Navigate to={user?.role === 'trainer' ? '/trainer-portal' : user?.role === 'client' ? '/client-portal' : '/dashboard'} replace /> : <Login key="trainer-login" onLogin={handleLogin} initialRole="trainer" />} />
          <Route path="/client-login" element={isLoggedIn ? <Navigate to={user?.role === 'client' ? '/client-portal' : user?.role === 'trainer' ? '/trainer-portal' : '/dashboard'} replace /> : <Login key="client-login" onLogin={handleLogin} initialRole="client" />} />
          <Route path="/trainer-portal" element={
            <PrivateRoute isLoggedIn={isLoggedIn} user={user} trainerOnly>
              <TrainerPortal user={user} onLogout={handleLogout} />
            </PrivateRoute>
          } />
          <Route path="/client-portal" element={<PrivateRoute isLoggedIn={isLoggedIn} user={user} clientOnly><ClientPortal user={user} onLogout={handleLogout} /></PrivateRoute>} />
          <Route path="/reset-password" element={user?.role === 'trainer' ? <Navigate to="/trainer-portal" replace /> : user?.role === 'client' ? <Navigate to="/client-portal" replace /> : <ResetPassword />} />
          <Route path="/home" element={<Home user={user} onLogout={isLoggedIn ? handleLogout : undefined} />} />
          <Route path="/" element={<Home user={user} onLogout={isLoggedIn ? handleLogout : undefined} />} />
          <Route path="/contact" element={user?.role === 'trainer' ? <Navigate to="/trainer-portal" replace /> : user?.role === 'client' ? <Navigate to="/client-portal" replace /> : <Contact />} />
          <Route path="/feedback" element={user?.role === 'trainer' ? <Navigate to="/trainer-portal" replace /> : user?.role === 'client' ? <Navigate to="/client-portal" replace /> : <Feedback />} />
          <Route path="/auth/callback" element={user?.role === 'trainer' ? <Navigate to="/trainer-portal" replace /> : user?.role === 'client' ? <Navigate to="/client-portal" replace /> : <GmailCallback onLogin={handleLogin} />} />
          <Route path="/auth/linkedin/callback" element={user?.role === 'trainer' ? <Navigate to="/trainer-portal" replace /> : user?.role === 'client' ? <Navigate to="/client-portal" replace /> : <LinkedInCallback onLogin={handleLogin} />} />
          <Route element={
            <PrivateRoute isLoggedIn={isLoggedIn} user={user}>
              <Layout isAdmin={user?.role === 'admin'} onLogout={handleLogout} />
            </PrivateRoute>
          }>
            <Route path="dashboard"    element={<Dashboard />} />
            <Route path="admin-dashboard" element={<AdminDashboard />} />
            <Route path="trainers"     element={<Trainers />} />
            <Route path="trainer-applications" element={<TrainerApplications />} />
            <Route path="partner-opportunities" element={<PartnerOpportunities />} />
            <Route path="requirements" element={<Requirements />} />
            <Route path="emails"       element={<Emails />} />
            <Route path="inbox"        element={<Inbox />} />
            <Route path="client-requests" element={<ClientRequests />} />
            <Route path="trainer-comms" element={<Navigate to="/dashboard" replace />} />
            <Route path="client-comms" element={<Navigate to="/dashboard" replace />} />
            <Route path="linkedin-search" element={<LinkedInSearch />} />
            <Route path="linkedin-pipeline" element={<LinkedInPipeline />} />
            <Route path="naukri-search" element={<NaukriSearch />} />
            <Route path="trainer-locations" element={<TrainerLocations />} />
            <Route path="trainer-locations/*" element={<TrainerLocations />} />
            <Route path="trainer-location" element={<TrainerLocations />} />
            <Route path="trainer-location/*" element={<TrainerLocations />} />
            <Route path="trainer-location-page" element={<TrainerLocations />} />
            <Route path="locations" element={<Navigate to="/trainer-locations" replace />} />
            <Route path="voice-ai-assistant" element={<VoiceAIAssistant />} />
            <Route path="client-pipeline" element={<ClientPipeline />} />
            <Route path="client-mail-pipeline" element={<ClientPipeline />} />
            <Route path="interview-scheduled" element={<InterviewSchedules />} />
            <Route path="interview" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="interview-page" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="interview-schedule" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="interview-schedules" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="scheduled-interviews" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="invoices" element={<Invoices />} />
            <Route path="purchase-orders" element={<PurchaseOrders />} />
            <Route path="finance-approvals" element={<FinanceApprovals />} />
            <Route path="upload"       element={<Navigate to="/resume-upload" replace />} />
            <Route path="resume-upload" element={<ResumeUpload />} />
            <Route path="admin"        element={<PrivateRoute isLoggedIn={isLoggedIn} user={user} adminOnly><Admin /></PrivateRoute>} />
            <Route path="toc-knowledge" element={<TocKnowledge />} />
            <Route path="lab-cost" element={<LabCost />} />
            <Route path="commercial" element={<PrivateRoute isLoggedIn={isLoggedIn} user={user} adminOnly><CommercialAnalysis /></PrivateRoute>} />
            <Route path="interviews"   element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="shortlist"    element={<Shortlist />} />
            <Route path="ai-pipeline"  element={<Shortlist1 />} />
            <Route path="shortlist1"   element={<Shortlist1 />} />
            <Route path="profile"      element={<Profile />} />
            <Route path="profile-reviews" element={<ProfileReviews />} />
          </Route>
          <Route path="*" element={<Navigate to={isLoggedIn ? (user?.role === 'trainer' ? "/trainer-portal" : user?.role === 'client' ? "/client-portal" : "/dashboard") : "/login"} replace />} />
        </Routes>
      </Suspense>
      </RouteBoundary>

    </BrowserRouter>
  )
}
