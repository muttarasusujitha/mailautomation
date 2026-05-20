import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { useState, useEffect } from 'react'
import Layout from './components/Layout'
import ChatAssistant from './components/ChatAssistant'
import FloatingIntegrations from './components/FloatingIntegrations'
import Login from './pages/Login'
import Home from './pages/Home'
import Contact from './pages/Contact'
import Feedback from './pages/Feedback'
import Dashboard from './pages/Dashboard'
import AdminDashboard from './pages/AdminDashboard'
import Trainers from './pages/Trainers'
import Requirements from './pages/Requirements'
import Emails from './pages/Emails'
import Inbox from './pages/Inbox'
import ClientRequests from './pages/ClientRequests'
import ResumeUpload from './pages/ResumeUpload'
import GmailCallback from './pages/GmailCallback'
import Admin from './pages/Admin'
import Interviews from './pages/Interviews'
import Shortlist from './pages/Shortlist'
import Shortlist1 from './pages/Shortlist1'
import Profile from './pages/Profile'

function PrivateRoute({ children, isLoggedIn }) {
  return isLoggedIn ? children : <Navigate to="/login" replace />
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
          style: { borderRadius: '12px', fontFamily: "'DM Sans', sans-serif", fontSize: '14px' },
          success: { iconTheme: { primary: '#2563eb', secondary: '#fff' } },
        }}
      />
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
          <Route path="inbox"        element={<Inbox />} />
          <Route path="client-requests" element={<ClientRequests />} />
          <Route path="upload"       element={<Navigate to="/resume-upload" replace />} />
          <Route path="resume-upload" element={<ResumeUpload />} />
          <Route path="admin"        element={<Admin />} />
          <Route path="interviews"   element={<Interviews />} />
          <Route path="shortlist"    element={<Shortlist />} />
          <Route path="shortlist1"   element={<Shortlist1 />} />
          <Route path="profile"      element={<Profile />} />
        </Route>
        <Route path="*" element={<Navigate to={isLoggedIn ? "/dashboard" : "/login"} replace />} />
      </Routes>

      {/* Chat assistant — visible on all authenticated pages */}
      {isLoggedIn && (
        <>
          <FloatingIntegrations />
          <ChatAssistant />
        </>
      )}
    </BrowserRouter>
  )
}
