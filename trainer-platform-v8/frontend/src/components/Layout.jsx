import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Users, FileSearch, Mail, Upload, Zap, Search, Settings, Calendar, ListChecks, LogOut, Home, MessageSquare, ChevronDown, Sparkles } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import clsx from 'clsx'

const NAV = [
  { to: '/home',        label: 'Home' },
  { to: '/dashboard',   label: 'Dashboard' },
  { to: '/admin-dashboard', label: 'Admin Dashboard' },
  { to: '/resume-upload', label: 'Upload Resumes' },
  { to: '/requirements', label: 'Find Trainers' },
  { to: '/shortlist',   label: 'Shortlist' },
  { to: '/inbox',       label: 'Client Inbox' },
  { to: '/trainers',    label: 'All Trainers' },
  { to: '/emails',      label: 'Email Logs' },
  { to: '/feedback',    label: 'Feedback' },
  { to: '/contact',     label: 'Contact' },
]

const PAGE_SEARCH_TARGETS = [
  { path: '/home', keywords: ['home', 'main page', 'landing page', 'about', 'about page', 'overview'] },
  { path: '/dashboard', keywords: ['dashboard', 'dash board', 'stats', 'statistics', 'analytics', 'report'] },
  { path: '/admin-dashboard', keywords: ['admin dashboard', 'advanced dashboard', 'analytics dashboard', 'admin analytics', 'analytics report'] },
  { path: '/resume-upload', keywords: ['upload', 'upload resumes', 'resume upload', 'resume', 'resumes', 'pdf', 'docx', 'zip', 'upload resume', 'trainer resume', 'import trainers'] },
  { path: '/requirements', keywords: ['find trainers', 'requirements', 'requirement', 'search requirement', 'new search'] },
  { path: '/shortlist', keywords: ['shortlist', 'short list', 'pipeline', 'selected trainers'] },
  { path: '/inbox', keywords: ['inbox', 'client inbox', 'client email', 'approvals', 'pending approval'] },
  { path: '/trainers', keywords: ['trainers', 'all trainers', 'trainer list', 'trainer database'] },
  { path: '/emails', keywords: ['emails', 'email logs', 'mail logs', 'mail', 'sent mail'] },
  { path: '/interviews', keywords: ['interviews', 'interview', 'schedule', 'meeting'] },
  { path: '/admin', keywords: ['admin', 'settings', 'admin settings', 'smtp', 'configuration'] },
  { path: '/admin?section=whatsapp', keywords: ['whatsapp', 'twilio', 'whatsapp settings', 'whatsapp notifications'] },
  { path: '/admin?section=teams', keywords: ['teams', 'microsoft teams', 'teams webhook', 'teams settings'] },
  { path: '/profile', keywords: ['profile', 'account', 'my profile'] },
  { path: '/feedback', keywords: ['feedback', 'reviews', 'review'] },
  { path: '/contact', keywords: ['contact', 'contact us', 'support', 'help'] },
]

const normalizeSearch = (value) =>
  value.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim()

const findPageRoute = (query) => {
  const normalized = normalizeSearch(query)
  if (!normalized) return null

  const exact = PAGE_SEARCH_TARGETS.find(({ keywords }) =>
    keywords.some(keyword => normalized === keyword)
  )
  if (exact) return exact.path

  const partial = PAGE_SEARCH_TARGETS.find(({ keywords }) =>
    keywords.some(keyword => normalized.includes(keyword))
  )
  return partial?.path || null
}

/* ── Spark animation component ───────────────────────────── */
function SparkEffect({ x, y, duration = 600 }) {
  const sparkElements = Array.from({ length: 6 }, (_, i) => {
    const angle = (i / 6) * Math.PI * 2
    const distance = 40
    const tx = Math.cos(angle) * distance
    const ty = Math.sin(angle) * distance
    return { tx, ty, delay: i * 30 }
  })

  return (
    <>
      {sparkElements.map((spark, i) => (
        <div
          key={i}
          style={{
            position: 'fixed',
            left: x,
            top: y,
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: `linear-gradient(135deg, #60a5fa, #06b6d4)`,
            pointerEvents: 'none',
            zIndex: 9999,
            animation: `spark-burst ${duration}ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards`,
            animationDelay: `${spark.delay}ms`,
            '--tx': `${spark.tx}px`,
            '--ty': `${spark.ty}px`,
          }}
        />
      ))}
      <style>{`
        @keyframes spark-burst {
          0% {
            transform: translate(0, 0) scale(1);
            opacity: 1;
          }
          100% {
            transform: translate(var(--tx), var(--ty)) scale(0);
            opacity: 0;
          }
        }
      `}</style>
    </>
  )
}

export default function Layout({ onLogout }) {
  const [searchQuery, setSearchQuery] = useState('')
  const [profileOpen, setProfileOpen] = useState(false)
  const [pipelineActive, setPipelineActive] = useState(true)
  const [pendingInbox, setPendingInbox] = useState(0)
  const [sparks, setSparks] = useState([])
  const navigate = useNavigate()
  const navRef = useRef(null)

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/api/dashboard/stats')
        setPipelineActive(res.ok)
      } catch { setPipelineActive(false) }
    }
    check()
    const interval = setInterval(check, 30000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const checkInbox = async () => {
      try {
        const res = await fetch('/api/inbox?status=pending_approval&limit=1')
        if (!res.ok) return
        const data = await res.json()
        setPendingInbox(data.stats?.pending_approval || data.total || 0)
      } catch {}
    }
    checkInbox()
    const interval = setInterval(checkInbox, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleSearch = (e) => {
    e.preventDefault()
    const query = searchQuery.trim()
    if (!query) return

    const pageRoute = findPageRoute(query)
    navigate(pageRoute || `/trainers?search=${encodeURIComponent(query)}`)
    setSearchQuery('')
  }

  const createSparkEffect = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const x = rect.left + rect.width / 2
    const y = rect.top + rect.height / 2
    const id = Math.random()
    setSparks(s => [...s, { id, x, y }])
    setTimeout(() => setSparks(s => s.filter(sp => sp.id !== id)), 700)
  }

  const handleNavClick = (e) => {
    createSparkEffect(e)
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-50">
      {/* Top Navigation Bar */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-full px-4 lg:px-8 py-3 flex items-center gap-4">
          {/* Logo with Click Animation */}
          <button
            onClick={(e) => { navigate('/home'); createSparkEffect(e) }}
            className="flex items-center gap-2.5 hover:opacity-80 transition-opacity flex-shrink-0 group"
          >
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-md group-hover:shadow-lg group-hover:scale-110 transition-all duration-300">
              <Zap className="w-5 h-5 text-white" />
            </div>
            <span className="font-bold text-slate-900 text-base hidden sm:block cursor-pointer hover:text-blue-600 transition-colors" style={{ fontFamily:"'Sora',sans-serif" }}>TrainerSync</span>
          </button>

          {/* Navigation Links */}
          <nav ref={navRef} className="hidden lg:flex items-center gap-1 flex-1">
            {NAV.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                onClick={handleNavClick}
                className={({ isActive }) => clsx(
                  'px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 relative group',
                  isActive
                    ? 'text-blue-600 bg-blue-50 border-b-2 border-blue-600'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                )}>
                {label}
                {to === '/inbox' && pendingInbox > 0 && (
                  <span className="ml-2 inline-flex min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                    {pendingInbox > 99 ? '99+' : pendingInbox}
                  </span>
                )}
                {/* Underline animation on hover */}
                <span className="absolute bottom-0 left-0 w-0 h-0.5 bg-gradient-to-r from-blue-400 to-blue-600 group-hover:w-full transition-all duration-300 rounded-full"></span>
              </NavLink>
            ))}
          </nav>

          {/* Expanded Search Bar */}
          <form onSubmit={handleSearch} className="flex items-center flex-1 min-w-[180px] mx-2 lg:mx-4">
            <div className="relative w-full max-w-sm xl:max-w-xl">
              <input
                type="text"
                placeholder="Search pages or trainers..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full px-4 py-2.5 pl-10 rounded-xl bg-slate-100 border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white transition-all duration-300"
              />
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            </div>
          </form>

          {/* Right Section - Status Indicator & Profile */}
          <div className="flex items-center gap-4 ml-auto">
            {/* Status Indicator */}
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-50">
              <div className={clsx('w-2 h-2 rounded-full', pipelineActive ? 'bg-emerald-400 animate-pulse' : 'bg-red-400')} />
              <span className={clsx('text-xs font-medium', pipelineActive ? 'text-emerald-600' : 'text-red-500')}>
                {pipelineActive ? 'Active' : 'Inactive'}
              </span>
            </div>

            {/* User Profile Dropdown - Top Right */}
            <div className="relative">
              <button
                onClick={(e) => { setProfileOpen(!profileOpen); createSparkEffect(e) }}
                className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-100 transition-all group"
              >
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center text-white text-sm font-bold group-hover:scale-110 transition-transform">
                  R
                </div>
                <ChevronDown className={clsx('w-4 h-4 text-slate-600 group-hover:text-slate-900 transition-all duration-300', profileOpen && 'rotate-180')} />
              </button>

              {/* Profile Dropdown Menu */}
              {profileOpen && (
                <div className="absolute right-0 mt-2 w-56 bg-white rounded-lg shadow-xl border border-slate-200 py-2 z-50">
                  <div className="px-4 py-3 border-b border-slate-100">
                    <p className="font-semibold text-slate-900">Recruiter Name</p>
                    <p className="text-xs text-slate-500">recruiter@company.com</p>
                  </div>
                  <button onClick={() => { navigate('/profile'); setProfileOpen(false) }} className="w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2">
                    <Settings className="w-4 h-4" />
                    Settings & Profile
                  </button>
                  <button onClick={() => { navigate('/feedback'); setProfileOpen(false) }} className="w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2">
                    <MessageSquare className="w-4 h-4" />
                    Feedback
                  </button>
                  <div className="border-t border-slate-100 pt-2">
                    {onLogout && (
                      <button
                        onClick={() => { setProfileOpen(false); onLogout() }}
                        className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2 font-medium"
                      >
                        <LogOut className="w-4 h-4" />
                        Logout
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden pt-16">
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>

      {/* Spark effects */}
      {sparks.map(spark => (
        <SparkEffect key={spark.id} x={spark.x} y={spark.y} />
      ))}
    </div>
  )
}
