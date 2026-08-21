import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { Suspense, lazy, useState, useEffect } from 'react'
import Layout from './components/Layout'
import ChatAssistant from './components/ChatAssistant'
import FloatingIntegrations from './components/FloatingIntegrations'
import ErrorBoundary from './components/ErrorBoundary'
import OfflineBanner from './components/OfflineBanner'

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

const Login = lazyWithRetry(() => import('./pages/Login'))
const Home = lazyWithRetry(() => import('./pages/Home'))
const Contact = lazyWithRetry(() => import('./pages/Contact'))
const Feedback = lazyWithRetry(() => import('./pages/Feedback'))
const Dashboard = lazyWithRetry(() => import('./pages/Dashboard'))
const AdminDashboard = lazyWithRetry(() => import('./pages/AdminDashboard'))
const Trainers = lazyWithRetry(() => import('./pages/Trainers'))
const Requirements = lazyWithRetry(() => import('./pages/Requirements'))
const Emails = lazyWithRetry(() => import('./pages/Emails'))
const ClientRequests = lazyWithRetry(() => import('./pages/ClientRequests'))
const ClientConversations = lazyWithRetry(() => import('./pages/ClientConversations'))
const LinkedInSearch = lazyWithRetry(() => import('./pages/LinkedInSearch'))
const LinkedInPipeline = lazyWithRetry(() => import('./pages/LinkedInPipeline'))
const LinkedInClientPipeline = lazyWithRetry(() => import('./pages/LinkedInClientPipeline'))
const NaukriSearch = lazyWithRetry(() => import('./pages/NaukriSearch'))
const TrainerLocations = lazyWithRetry(() => import('./pages/TrainerLocations'))
const VoiceAIAssistant = lazyWithRetry(() => import('./pages/VoiceAIAssistant'))
const ClientPipeline = lazyWithRetry(() => import('./pages/ClientPipeline'))
const CommercialAnalysis = lazyWithRetry(() => import('./pages/CommercialAnalysis'))
const InterviewSchedules = lazyWithRetry(() => import('./pages/InterviewSchedules'))
const Invoices = lazyWithRetry(() => import('./pages/Invoices'))
const ResumeUpload = lazyWithRetry(() => import('./pages/ResumeUpload'))
const GmailCallback = lazyWithRetry(() => import('./pages/GmailCallback'))
const LinkedInCallback = lazyWithRetry(() => import('./pages/LinkedInCallback'))
const Admin = lazyWithRetry(() => import('./pages/Admin'))
const TocKnowledge = lazyWithRetry(() => import('./pages/TocKnowledge'))
const LabCost = lazyWithRetry(() => import('./pages/LabCost'))
const Shortlist = lazyWithRetry(() => import('./pages/Shortlist'))
const Shortlist1 = lazyWithRetry(() => import('./pages/Shortlist1'))
const Profile = lazyWithRetry(() => import('./pages/Profile'))

function PrivateRoute({ children, isLoggedIn }) {
  return isLoggedIn ? children : <Navigate to="/login" replace />
}

function PageLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm font-semibold text-slate-500">
      Loading...
    </div>
  )
}

function RouteBoundary({ children }) {
  const location = useLocation()
  return <ErrorBoundary resetKey={location.pathname}>{children}</ErrorBoundary>
}

function FloatingBoundary({ children }) {
  const location = useLocation()
  return <ErrorBoundary resetKey={`floating:${location.pathname}`}>{children}</ErrorBoundary>
}

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(() => {
    try {
      if (import.meta.env.DEV) {
        const params = new URLSearchParams(window.location.search)
        if (params.get('dev') === 'true' || params.get('dev_login') === 'true') {
          sessionStorage.setItem('ts_auth', JSON.stringify({ loggedIn: true }))
          return true
        }
      }
      // SEC-009: Use sessionStorage so auth token is not persisted across browser sessions,
      // reducing XSS exposure. Tokens are cleared when the tab/browser is closed.
      const auth = JSON.parse(sessionStorage.getItem('ts_auth') || '{}')
      return !!auth.loggedIn
    } catch { return false }
  })

  useEffect(() => {
    if (!import.meta.env.DEV) return
    try {
      const params = new URLSearchParams(window.location.search)
      if (params.get('dev') === 'true' || params.get('dev_login') === 'true') {
        sessionStorage.setItem('ts_auth', JSON.stringify({ loggedIn: true }))
        setIsLoggedIn(true)
      }
    } catch {
      /* ignore */
    }
  }, [])

  const handleLogin = () => setIsLoggedIn(true)
  const handleLogout = () => {
    sessionStorage.removeItem('ts_auth')
    setIsLoggedIn(false)
  }

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
            isLoggedIn ? <Navigate to="/dashboard" replace /> : <Login onLogin={handleLogin} />
          } />
          <Route path="/home" element={<Home />} />
          <Route path="/" element={<Home />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/feedback" element={<Feedback />} />
          <Route path="/auth/callback" element={<GmailCallback onLogin={handleLogin} />} />
          <Route path="/auth/linkedin/callback" element={<LinkedInCallback />} />
          <Route element={
            <PrivateRoute isLoggedIn={isLoggedIn}>
              <Layout onLogout={handleLogout} />
            </PrivateRoute>
          }>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard"    element={<Dashboard />} />
            <Route path="admin-dashboard" element={<AdminDashboard />} />
            <Route path="trainers"     element={<Trainers />} />
            <Route path="requirements" element={<Requirements />} />
            <Route path="emails"       element={<Emails />} />
            <Route path="inbox"        element={<Navigate to="/client-requests" replace />} />
            <Route path="client-requests" element={<ClientRequests />} />
            <Route path="client-comms" element={<ClientConversations />} />
            <Route path="trainer-comms" element={<ClientConversations />} />
            <Route path="linkedin-search" element={<LinkedInSearch />} />
            <Route path="linkedin-pipeline" element={<LinkedInPipeline />} />
            <Route path="linkedin-client-pipeline" element={<LinkedInClientPipeline />} />
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
            <Route path="commercial-analysis" element={<CommercialAnalysis />} />
            <Route path="interview-scheduled" element={<InterviewSchedules />} />
            <Route path="interview" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="interview-page" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="interview-schedule" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="interview-schedules" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="scheduled-interviews" element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="invoices" element={<Invoices />} />
            <Route path="upload"       element={<Navigate to="/resume-upload" replace />} />
            <Route path="resume-upload" element={<ResumeUpload />} />
            <Route path="admin"        element={<Admin />} />
            <Route path="toc-knowledge" element={<TocKnowledge />} />
            <Route path="lab-cost" element={<LabCost />} />
            <Route path="interviews"   element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="shortlist"    element={<Shortlist />} />
            <Route path="ai-pipeline"  element={<Shortlist1 />} />
            <Route path="shortlist1"   element={<Shortlist1 />} />
            <Route path="profile"      element={<Profile />} />
          </Route>
          <Route path="*" element={<Navigate to={isLoggedIn ? "/dashboard" : "/login"} replace />} />
        </Routes>
      </Suspense>
      </RouteBoundary>

      {/* Chat assistant — visible on all authenticated pages */}
      {isLoggedIn && (
        <FloatingBoundary>
          <FloatingIntegrations />
          <ChatAssistant />
        </FloatingBoundary>
      )}
    </BrowserRouter>
  )
}
