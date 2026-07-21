import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  BarChart3, Bell, BookOpen, BriefcaseBusiness, CalendarCheck,
  CheckCircle2, ChevronRight, FileSearch, Globe2, Home,
  LayoutDashboard, LogOut, Mail, Menu,
  ReceiptText, Search, Settings, Upload, UserCircle, Users, Zap, X,
} from 'lucide-react'
import BrandMark from './BrandMark'

const NAV_GROUPS = [
  {
    label: 'Trainer Pipeline',
    items: [
      { to: '/dashboard',         label: 'Dashboard',          icon: LayoutDashboard, keywords: ['dashboard','stats','overview'] },
      { to: '/resume-upload',     label: 'Upload Resumes',     icon: Upload,          keywords: ['upload','resume','import'] },
      { to: '/requirements',      label: 'Find Trainers',      icon: FileSearch,      keywords: ['find','requirement','match'] },
      { to: '/shortlist1',        label: 'AI Pipeline',        icon: Zap,             keywords: ['advanced','shortlist1','shortlist','pipeline'] },
      { to: '/shortlist',         label: 'Shortlist',          icon: Users,           keywords: ['shortlist','trainer shortlist'] },
      { to: '/linkedin-search',   label: 'LinkedIn Search',    icon: Globe2,          keywords: ['linkedin','public search','client post search','trainer profile search'] },
      { to: '/naukri-search',     label: 'Naukri Search',      icon: BriefcaseBusiness, keywords: ['naukri','naukri search','naukri public','naukri trainer'] },
      { to: '/linkedin-shortlist',label: 'LinkedIn Shortlist', icon: CheckCircle2,    keywords: ['linkedin shortlist','shortlisted linkedin','trainer lead shortlist','client post shortlist'] },
      { to: '/trainers',          label: 'Trainer Database',   icon: Users,           keywords: ['trainers','database'] },
    ],
  },
  {
    label: 'Client Work',
    items: [
      { to: '/client-requests',      label: 'Client Requests',    icon: BriefcaseBusiness, keywords: ['client','requests','requirements'] },
      { to: '/client-leads',         label: 'Client Leads',       icon: Search,            keywords: ['client leads','lead finder','linkedin leads'] },
      { to: '/interview-scheduled',  label: 'Interviews',         icon: CalendarCheck,     keywords: ['interview','schedule','meeting','meet link'] },
      { to: '/client-mail-pipeline', label: 'Client Pipeline',    icon: ReceiptText,       keywords: ['client pipeline','client mail pipeline','po','invoice','client po','client mails'] },
      { to: '/invoices',             label: 'Invoices',           icon: ReceiptText,       keywords: ['invoice','manual invoice','generate invoice','billing'] },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/admin-dashboard', label: 'Analytics',     icon: BarChart3,  keywords: ['admin dashboard','analytics'] },
      { to: '/emails',          label: 'Email Logs',    icon: Mail,       keywords: ['email','logs','mail'] },
      { to: '/toc-knowledge',   label: 'ToC Knowledge', icon: BookOpen,   keywords: ['toc','curriculum','knowledge','course agenda'] },
      { to: '/admin',           label: 'Settings',      icon: Settings,   keywords: ['admin','settings','gmail','whatsapp'] },
    ],
  },
]

const ALL_NAV_ITEMS = NAV_GROUPS.flatMap(g => g.items)

function norm(v) {
  return String(v || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim()
}
function routeForQuery(q) {
  const n = norm(q)
  if (!n) return null
  return ALL_NAV_ITEMS.find(item =>
    item.keywords.some(k => n === norm(k) || n.includes(norm(k)))
  )?.to || null
}
function pageTitle(pathname) {
  if (pathname === '/dashboard') return 'Dashboard'
  const item = ALL_NAV_ITEMS.find(e => pathname === e.to || pathname.startsWith(`${e.to}/`))
  return item?.label || 'TrainerSync'
}


function NavItem({ item, pendingInbox, onClick }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      onClick={onClick}
      className={({ isActive }) =>
        clsx('nav-item group', isActive && 'active')
      }
    >
      <span className="nav-icon">
        <Icon className="h-[15px] w-[15px]" />
      </span>
      <span className="min-w-0 flex-1 truncate text-[13.5px]">{item.label}</span>
      {item.to === '/client-requests' && pendingInbox > 0 && (
        <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">
          {pendingInbox > 99 ? '99+' : pendingInbox}
        </span>
      )}
    </NavLink>
  )
}

function Sidebar({ pendingInbox, onLogout, onNavigate }) {
  return (
    <aside className="sidebar animate-slide-in">
      {/* Brand header */}
      <div className="sidebar-header">
        <NavLink to="/home" onClick={onNavigate}>
          <BrandMark size="md" />
        </NavLink>

        {/* Status pill */}
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2">
          <span className="status-dot green animate-pulse-soft" />
          <span className="text-[12px] font-semibold text-blue-700">Operations Hub · Live</span>
        </div>
      </div>

      {/* Navigation */}
      <div className="sidebar-body">
        {/* Home */}
        <NavLink
          to="/home"
          onClick={onNavigate}
          className={({ isActive }) => clsx('nav-item mb-2', isActive && 'active')}
        >
          <span className="nav-icon"><Home className="h-[15px] w-[15px]" /></span>
          <span className="text-[13.5px]">Home</span>
        </NavLink>

        <div className="space-y-5">
          {NAV_GROUPS.map(group => (
            <div key={group.label}>
              <p className="sidebar-group-label">{group.label}</p>
              <div className="space-y-0.5">
                {group.items.map(item => (
                  <NavItem key={item.to} item={item} pendingInbox={pendingInbox} onClick={onNavigate} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="sidebar-footer">
        <NavLink
          to="/profile"
          onClick={onNavigate}
          className="nav-item"
        >
          <UserCircle className="h-4 w-4 flex-shrink-0 text-slate-400" />
          <span className="text-[13.5px]">Recruiter Profile</span>
        </NavLink>
        {onLogout && (
          <button
            type="button"
            onClick={onLogout}
            className="nav-item mt-0.5 w-full text-red-500 hover:bg-red-50 hover:text-red-600"
          >
            <LogOut className="h-4 w-4 flex-shrink-0" />
            <span className="text-[13.5px]">Logout</span>
          </button>
        )}
      </div>
    </aside>
  )
}


export default function Layout({ onLogout }) {
  const [query, setQuery]         = useState('')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [pendingInbox, setPendingInbox] = useState(0)
  const [connected, setConnected]  = useState(false)
  const navigate  = useNavigate()
  const location  = useLocation()
  const title     = useMemo(() => pageTitle(location.pathname), [location.pathname])

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
      } catch { if (!cancelled) setConnected(false) }
    }
    loadStatus()
    const iv = setInterval(loadStatus, 30000)
    return () => { cancelled = true; clearInterval(iv) }
  }, [])

  const submitSearch = e => {
    e.preventDefault()
    const t = query.trim()
    if (!t) return
    navigate(routeForQuery(t) || `/trainers?search=${encodeURIComponent(t)}`)
    setQuery('')
    setMobileOpen(false)
  }

  return (
    <div className="app-shell">
      {/* Desktop sidebar */}
      <div className="hidden lg:block">
        <Sidebar pendingInbox={pendingInbox} onLogout={onLogout} onNavigate={() => {}} />
      </div>

      {/* Mobile sidebar overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          />
          <div className="absolute inset-y-0 left-0 w-[272px] shadow-2xl">
            <Sidebar pendingInbox={pendingInbox} onLogout={onLogout} onNavigate={() => setMobileOpen(false)} />
          </div>
          <button
            className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-lg bg-white shadow-md"
            onClick={() => setMobileOpen(false)}
          >
            <X className="h-4 w-4 text-slate-600" />
          </button>
        </div>
      )}

      {/* Main area */}
      <div className="main-area">
        {/* Header */}
        <header className="app-header">
          {/* Mobile menu toggle */}
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="btn-ghost rounded-lg p-2 lg:hidden"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>

          {/* Breadcrumb + title */}
          <div className="min-w-0 flex-1">
            <div className="hidden items-center gap-1 text-[11px] font-semibold text-slate-400 sm:flex">
              <span>TrainerSync</span>
              <ChevronRight className="h-3 w-3" />
              <span className="text-slate-600">{title}</span>
            </div>
            <h1 className="truncate text-[17px] font-bold tracking-tight text-slate-900 sm:text-lg">
              {title}
            </h1>
          </div>

          {/* Search */}
          <form onSubmit={submitSearch} className="hidden w-72 md:block lg:w-80">
            <div className="search-bar">
              <Search className="h-4 w-4" />
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search pages, trainers, clients..."
              />
            </div>
          </form>

          {/* Right actions */}
          <div className="flex items-center gap-2">
            {/* Gmail status */}
            <div className={clsx(
              'hidden items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold sm:flex',
              connected
                ? 'border-green-200 bg-green-50 text-green-700'
                : 'border-amber-200 bg-amber-50 text-amber-700'
            )}>
              <span className={clsx('status-dot', connected ? 'green' : 'amber')} />
              {connected ? 'Gmail Ready' : 'Connect Gmail'}
            </div>

            {/* Notifications */}
            <button
              type="button"
              onClick={() => navigate('/inbox')}
              className="relative rounded-lg border border-slate-200 bg-white p-2 text-slate-500 shadow-xs transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-600"
              aria-label="Client inbox"
            >
              <Bell className="h-4 w-4" />
              {pendingInbox > 0 && (
                <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white ring-2 ring-white">
                  {pendingInbox > 9 ? '9+' : pendingInbox}
                </span>
              )}
            </button>
          </div>
        </header>

        {/* Mobile search */}
        <form onSubmit={submitSearch} className="border-b border-slate-100 bg-white px-4 py-2 md:hidden">
          <div className="search-bar">
            <Search className="h-4 w-4" />
            <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search..." />
          </div>
        </form>

        {/* Page output */}
        <main className="page-content">
          <div className="mx-auto w-full max-w-[1540px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
