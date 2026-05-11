import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Trainers from './pages/Trainers'
import Requirements from './pages/Requirements'
import Emails from './pages/Emails'
import Upload from './pages/Upload'
import Admin from './pages/Admin'
import Interviews from './pages/Interviews'
import Shortlist from './pages/Shortlist'

export default function App() {
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
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="trainers" element={<Trainers />} />
          <Route path="requirements" element={<Requirements />} />
          <Route path="emails" element={<Emails />} />
          <Route path="upload" element={<Upload />} />
          <Route path="admin" element={<Admin />} />
          <Route path="interviews" element={<Interviews />} />
          <Route path="shortlist"  element={<Shortlist />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
