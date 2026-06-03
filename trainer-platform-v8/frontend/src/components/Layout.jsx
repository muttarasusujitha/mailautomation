import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  BarChart3,
  Bell,
  BriefcaseBusiness,
  ChevronRight,
  FileSearch,
  Home,
  LayoutDashboard,
  LogOut,
  Mail,
  Menu,
  MessageSquare,
  Search,
  Settings,
  Upload,
  UserCircle,
  Users,
  Zap,
} from 'lucide-react'
import BrandMark from './BrandMark'

const NAV_GROUPS = [
  {
    label: 'Trainer Pipeline',
    items: [
      { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, keywords: ['dashboard', 'stats', 'overview'] },
      { to: '/resume-upload', label: 'Upload Resumes', icon: Upload, keywords: ['upload', 'resume', 'import'] },
      { to: '/requirements', label: 'Find Trainers', icon: FileSearch, keywords: ['find', 'requirement', 'match'] },
      { to: '/shortlist1', label: 'AI Pipeline', icon: Zap, keywords: ['advanced', 'shortlist1', 'shortlist', 'pipeline'] },
      { to: '/shortlist', label: 'Shortlist', icon: Users, keywords: ['shortlist', 'trainer shortlist'] },
      { to: '/trainers', label: 'Trainer Database', icon: Users, keywords: ['trainers', 'database'] },
    ],
  },
  {
    label: 'Client Work',
    items: [
      { to: '/client-requests', label: 'Client Requests', icon: BriefcaseBusiness, keywords: ['client', 'requests', 'requirements'] },
      { to: '/client-conversations', label: 'Client Threads', icon: MessageSquare, keywords: ['client threads', 'client conversations', 'conversation', 'thread'] },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/admin-dashboard', label: 'Admin Analytics', icon: BarChart3, keywords: ['admin dashboard', 'analytics'] },
      { to: '/emails', label: 'Email Logs', icon: Mail, keywords: ['email', 'logs', 'mail'] },
      { to: '/admin', label: 'Settings', icon: Settings, keywords: ['admin', 'settings', 'gmail', 'whatsapp'] },
    ],
  },
]

const ALL_NAV_ITEMS = NAV_GROUPS.flatMap(group => group.items)

function normalise(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim()
}

function routeForQuery(query) {
  const q = normalise(query)
  if (!q) return null
  return ALL_NAV_ITEMS.find(item =>
    item.keywords.some(keyword => q === normalise(keyword) || q.includes(normalise(keyword)))
  )?.to || null
}

function pageTitle(pathname) {
  if (pathname === '/dashboard') return 'Dashboard'
  const item = ALL_NAV_ITEMS.find(entry => pathname === entry.to || pathname.startsWith(`${entry.to}/`))
  return item?.label || 'TrainerSync'
}

function SidebarLink({ item, pendingInbox, onNavigate }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      onClick={onNavigate}
      className={({ isActive }) => clsx(
        'group flex min-h-10 items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold transition',
        isActive
          ? 'bg-blue-50 text-blue-700 ring-1 ring-blue-100'
          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {item.to === '/client-requests' && pendingInbox > 0 && (
        <span className="rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
          {pendingInbox > 99 ? '99+' : pendingInbox}
        </span>
      )}
    </NavLink>
  )
}

function Sidebar({ pendingInbox, onLogout, onNavigate }) {
  return (
    <aside className="flex h-full w-72 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-5 py-4">
        <NavLink to="/home" onClick={onNavigate}>
          <BrandMark />
        </NavLink>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-4">
        <NavLink
          to="/home"
          onClick={onNavigate}
          className="mb-4 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-900"
        >
          <Home className="h-4 w-4" /> Home
        </NavLink>

        <div className="space-y-5">
          {NAV_GROUPS.map(group => (
            <div key={group.label}>
              <p className="mb-2 px-3 text-[11px] font-bold uppercase tracking-wide text-slate-400">{group.label}</p>
              <div className="space-y-1">
                {group.items.map(item => (
                  <SidebarLink key={item.to} item={item} pendingInbox={pendingInbox} onNavigate={onNavigate} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="border-t border-slate-200 p-3">
        <NavLink
          to="/profile"
          onClick={onNavigate}
          className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        >
          <UserCircle className="h-4 w-4" />
          Recruiter Profile
        </NavLink>
        {onLogout && (
          <button
            type="button"
            onClick={onLogout}
            className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold text-red-600 hover:bg-red-50"
          >
            <LogOut className="h-4 w-4" />
            Logout
          </button>
        )}
      </div>
    </aside>
  )
}

export default function Layout({ onLogout }) {
  const [query, setQuery] = useState('')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [pendingInbox, setPendingInbox] = useState(0)
  const [connected, setConnected] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const title = useMemo(() => pageTitle(location.pathname), [location.pathname])

  useEffect(() => {
    let cancelled = false
    const loadStatus = async () => {
      try {
        const [inboxRes, gmailRes] = await Promise.allSettled([
          fetch('/api/inbox?status=pending_approval&limit=1'),
          fetch('/api/gmail/auth-status'),
        ])
        if (cancelled) return
        if (inboxRes.status === 'fulfilled' && inboxRes.value.ok) {
          const data = await inboxRes.value.json()
          if (!cancelled) setPendingInbox(data.stats?.pending_approval || data.total || 0)
        }
        if (gmailRes.status === 'fulfilled' && gmailRes.value.ok) {
          const data = await gmailRes.value.json()
          if (!cancelled) setConnected(!!data.connected)
        }
      } catch {
        if (!cancelled) setConnected(false)
      }
    }
    loadStatus()
    const interval = setInterval(loadStatus, 30000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const submitSearch = (event) => {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) return
    navigate(routeForQuery(trimmed) || `/trainers?search=${encodeURIComponent(trimmed)}`)
    setQuery('')
    setMobileOpen(false)
  }

  const closeMobile = () => setMobileOpen(false)

  return (
    <div className="flex h-screen overflow-hidden bg-slate-100">
      <div className="hidden lg:block">
        <Sidebar pendingInbox={pendingInbox} onLogout={onLogout} onNavigate={() => {}} />
      </div>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button className="absolute inset-0 bg-slate-950/40" onClick={closeMobile} aria-label="Close navigation" />
          <div className="absolute inset-y-0 left-0 w-72 shadow-xl">
            <Sidebar pendingInbox={pendingInbox} onLogout={onLogout} onNavigate={closeMobile} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-slate-200 bg-white">
          <div className="flex min-h-16 items-center gap-3 px-4 lg:px-6">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="h-5 w-5" />
            </button>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1 text-xs font-medium text-slate-400">
                Workspace <ChevronRight className="h-3 w-3" /> {title}
              </div>
              <h1 className="truncate text-lg font-bold text-slate-950">{title}</h1>
            </div>

            <form onSubmit={submitSearch} className="hidden w-full max-w-md flex-none md:block">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={query}
                  onChange={event => setQuery(event.target.value)}
                  placeholder="Search pages, clients, trainers..."
                  className="h-10 w-full rounded-full border border-slate-200 bg-slate-50 pl-9 pr-4 text-sm outline-none focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-500/10"
                />
              </div>
            </form>

            <div className="flex flex-1 items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => navigate('/inbox')}
                className="relative rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50"
                aria-label="Client inbox"
              >
                <Bell className="h-5 w-5" />
                {pendingInbox > 0 && <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full bg-red-500 ring-2 ring-white" />}
              </button>

              <div className="hidden items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600 sm:flex">
                <span className={clsx('h-2 w-2 rounded-full', connected ? 'bg-emerald-500' : 'bg-amber-500')} />
                {connected ? 'Gmail Ready' : 'Connect Gmail'}
              </div>
            </div>
          </div>

          <form onSubmit={submitSearch} className="border-t border-slate-100 px-4 py-3 md:hidden">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={event => setQuery(event.target.value)}
                placeholder="Search..."
                className="h-10 w-full rounded-full border border-slate-200 bg-slate-50 pl-9 pr-4 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </div>
          </form>
        </header>

        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1500px] px-4 py-5 lg:px-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
