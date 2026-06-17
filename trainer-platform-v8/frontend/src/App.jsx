import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { Suspense, lazy, useState } from 'react'
import Layout from './components/Layout'
import ChatAssistant from './components/ChatAssistant'
import FloatingIntegrations from './components/FloatingIntegrations'
import ThemeToggle from './components/ThemeToggle'

const Login = lazy(() => import('./pages/Login'))
const Home = lazy(() => import('./pages/Home'))
const Contact = lazy(() => import('./pages/Contact'))
const Feedback = lazy(() => import('./pages/Feedback'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'))
const Trainers = lazy(() => import('./pages/Trainers'))
const Requirements = lazy(() => import('./pages/Requirements'))
const Emails = lazy(() => import('./pages/Emails'))
const ClientRequests = lazy(() => import('./pages/ClientRequests'))
const ClientLeads = lazy(() => import('./pages/ClientLeads'))
const LinkedInSearch = lazy(() => import('./pages/LinkedInSearch'))
const LinkedInShortlist = lazy(() => import('./pages/LinkedInShortlist'))
const NaukriSearch = lazy(() => import('./pages/NaukriSearch'))
const ClientConversations = lazy(() => import('./pages/ClientConversations'))
const ClientPipeline = lazy(() => import('./pages/ClientPipeline'))
const InterviewSchedules = lazy(() => import('./pages/InterviewSchedules'))
const Invoices = lazy(() => import('./pages/Invoices'))
const ResumeUpload = lazy(() => import('./pages/ResumeUpload'))
const GmailCallback = lazy(() => import('./pages/GmailCallback'))
const Admin = lazy(() => import('./pages/Admin'))
const TocKnowledge = lazy(() => import('./pages/TocKnowledge'))
const Shortlist = lazy(() => import('./pages/Shortlist'))
const Shortlist1 = lazy(() => import('./pages/Shortlist1'))
const Profile = lazy(() => import('./pages/Profile'))

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

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(() => {
    try {
      const auth = JSON.parse(localStorage.getItem('ts_auth') || '{}')
      return !!auth.loggedIn
    } catch { return false }
  })

  const handleLogin = () => setIsLoggedIn(true)
  const handleLogout = () => {
    localStorage.removeItem('ts_auth')
    setIsLoggedIn(false)
  }

  return (
    <BrowserRouter>
      <Toaster
        position="top-right"
        toastOptions={{
          style: { borderRadius: '12px', fontFamily: "'Inter', sans-serif", fontSize: '14px' },
          success: { iconTheme: { primary: '#2563eb', secondary: '#fff' } },
        }}
      />
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/login" element={
            isLoggedIn ? <Navigate to="/dashboard" replace /> : <Login onLogin={handleLogin} />
          } />
          <Route path="/home" element={<Home />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/feedback" element={<Feedback />} />
          <Route path="/auth/callback" element={<GmailCallback />} />
          <Route path="/" element={
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
            <Route path="client-leads" element={<ClientLeads />} />
            <Route path="linkedin-search" element={<LinkedInSearch />} />
            <Route path="linkedin-shortlist" element={<LinkedInShortlist />} />
            <Route path="naukri-search" element={<NaukriSearch />} />
            <Route path="client-pipeline" element={<ClientPipeline />} />
            <Route path="client-mail-pipeline" element={<ClientPipeline />} />
            <Route path="client-conversations" element={<ClientConversations />} />
            <Route path="interview-scheduled" element={<InterviewSchedules />} />
            <Route path="invoices" element={<Invoices />} />
            <Route path="upload"       element={<Navigate to="/resume-upload" replace />} />
            <Route path="resume-upload" element={<ResumeUpload />} />
            <Route path="admin"        element={<Admin />} />
            <Route path="toc-knowledge" element={<TocKnowledge />} />
            <Route path="interviews"   element={<Navigate to="/interview-scheduled" replace />} />
            <Route path="shortlist"    element={<Shortlist />} />
            <Route path="shortlist1"   element={<Shortlist1 />} />
            <Route path="profile"      element={<Profile />} />
          </Route>
          <Route path="*" element={<Navigate to={isLoggedIn ? "/dashboard" : "/login"} replace />} />
        </Routes>
      </Suspense>

      {/* Chat assistant — visible on all authenticated pages */}
      {isLoggedIn && (
        <>
          <ThemeToggle floating />
          <FloatingIntegrations />
          <ChatAssistant />
        </>
      )}
    </BrowserRouter>
  )
}
