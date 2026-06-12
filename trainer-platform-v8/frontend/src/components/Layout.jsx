import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  BarChart3,
  Bell,
  BookOpen,
  BriefcaseBusiness,
  CalendarCheck,
  CheckCircle2,
  ChevronRight,
  FileSearch,
  Globe2,
  Home,
  LayoutDashboard,
  LogOut,
  Mail,
  Menu,
  MessageSquare,
  ReceiptText,
  Search,
  Settings,
  Upload,
  UserCircle,
  Users,
  Zap,
} from 'lucide-react'
import BrandMark from './BrandMark'
import ThemeToggle from './ThemeToggle'

const NAV_GROUPS = [
  {
    label: 'Trainer Pipeline',
    items: [
      { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, keywords: ['dashboard', 'stats', 'overview'] },
      { to: '/resume-upload', label: 'Upload Resumes', icon: Upload, keywords: ['upload', 'resume', 'import'] },
      { to: '/requirements', label: 'Find Trainers', icon: FileSearch, keywords: ['find', 'requirement', 'match'] },
      { to: '/shortlist1', label: 'AI Pipeline', icon: Zap, keywords: ['advanced', 'shortlist1', 'shortlist', 'pipeline'] },
      { to: '/shortlist', label: 'Shortlist', icon: Users, keywords: ['shortlist', 'trainer shortlist'] },
      { to: '/linkedin-search', label: 'LinkedIn Search', icon: Globe2, keywords: ['linkedin', 'public search', 'client post search', 'trainer profile search'] },
      { to: '/naukri-search', label: 'Naukri Search', icon: BriefcaseBusiness, keywords: ['naukri', 'naukri search', 'naukri public', 'naukri trainer'] },
      { to: '/linkedin-shortlist', label: 'LinkedIn Shortlist', icon: CheckCircle2, keywords: ['linkedin shortlist', 'shortlisted linkedin', 'trainer lead shortlist', 'client post shortlist'] },
      { to: '/trainers', label: 'Trainer Database', icon: Users, keywords: ['trainers', 'database'] },
    ],
  },
  {
    label: 'Client Work',
    items: [
      { to: '/client-requests', label: 'Client Requests', icon: BriefcaseBusiness, keywords: ['client', 'requests', 'requirements'] },
      { to: '/client-leads', label: 'Client Leads', icon: Search, keywords: ['client leads', 'lead finder', 'linkedin leads', 'trainer requirement leads'] },
      { to: '/linkedin-search', label: 'LinkedIn Search', icon: Globe2, keywords: ['linkedin', 'public search', 'client post search', 'trainer profile search'] },
      { to: '/naukri-search', label: 'Naukri Search', icon: BriefcaseBusiness, keywords: ['naukri', 'naukri search', 'naukri public', 'naukri trainer'] },
      { to: '/linkedin-shortlist', label: 'LinkedIn Shortlist', icon: CheckCircle2, keywords: ['linkedin shortlist', 'shortlisted linkedin', 'trainer lead shortlist', 'client post shortlist'] },
      { to: '/interview-scheduled', label: 'Interview Scheduled', icon: CalendarCheck, keywords: ['interview', 'schedule', 'meeting', 'meet link'] },
      { to: '/client-mail-pipeline', label: 'Client Mail Pipeline', icon: ReceiptText, keywords: ['client pipeline', 'client mail pipeline', 'po', 'invoice', 'client po', 'client mails'] },
      { to: '/invoices', label: 'Invoices', icon: ReceiptText, keywords: ['invoice', 'manual invoice', 'generate invoice', 'billing'] },
      { to: '/client-conversations', label: 'Client Threads', icon: MessageSquare, keywords: ['client threads', 'client conversations', 'conversation', 'thread'] },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/admin-dashboard', label: 'Admin Analytics', icon: BarChart3, keywords: ['admin dashboard', 'analytics'] },
      { to: '/emails', label: 'Email Logs', icon: Mail, keywords: ['email', 'logs', 'mail'] },
      { to: '/toc-knowledge', label: 'ToC Knowledge', icon: BookOpen, keywords: ['toc', 'curriculum', 'knowledge', 'course agenda'] },
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
        'nav-holo-link group relative flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold transition',
        isActive
          ? 'nav-holo-link-active bg-white text-slate-950 shadow-[0_14px_32px_rgba(14,116,144,0.16)] ring-1 ring-cyan-100'
          : 'text-slate-600 hover:bg-white/75 hover:text-slate-950'
      )}
    >
      {({ isActive }) => (
        <>
          {isActive && <span className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-cyan-400" />}
          <span className={clsx(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition',
            isActive ? 'border-cyan-100 bg-cyan-600 text-white' : 'border-slate-200 bg-white/70 text-slate-500 group-hover:border-cyan-200 group-hover:text-cyan-700'
          )}>
            <Icon className="h-4 w-4" />
          </span>
          <span className="min-w-0 flex-1 truncate">{item.label}</span>
          {item.to === '/client-requests' && pendingInbox > 0 && (
            <span className="rounded-full bg-rose-500 px-1.5 py-0.5 text-[10px] font-bold text-white shadow-sm">
              {pendingInbox > 99 ? '99+' : pendingInbox}
            </span>
          )}
        </>
      )}
    </NavLink>
  )
}

function Sidebar({ pendingInbox, onLogout, onNavigate }) {
  return (
    <aside className="premium-rail relative flex h-full w-72 flex-col overflow-hidden text-slate-800">
      <div className="absolute inset-y-0 right-0 w-px bg-slate-200" />
      <div className="relative border-b border-slate-200 px-5 py-4">
        <NavLink to="/home" onClick={onNavigate}>
          <BrandMark />
        </NavLink>
        <div className="mt-4 inline-flex items-center gap-2 rounded-lg border border-cyan-200 bg-white/70 px-3 py-1 text-[11px] font-bold uppercase tracking-wide text-cyan-700 shadow-sm chrome-button">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_14px_rgba(52,211,153,0.8)]" />
          Operations Hub
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
          <div className="nano-tile rounded-lg border border-cyan-100 px-3 py-2">
            <p className="font-bold text-slate-950">AI</p>
            <p className="mt-0.5 text-slate-500">Pipeline</p>
          </div>
          <div className="nano-tile rounded-lg border border-emerald-100 px-3 py-2">
            <p className="font-bold text-slate-950">PO</p>
            <p className="mt-0.5 text-slate-500">Billing</p>
          </div>
        </div>
      </div>

      <div className="relative flex-1 overflow-y-auto px-3 py-4">
        <NavLink
          to="/home"
          onClick={onNavigate}
          className={({ isActive }) => clsx(
            'nav-holo-link mb-4 flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold transition',
            isActive ? 'nav-holo-link-active bg-white text-slate-950 shadow-sm ring-1 ring-cyan-100' : 'text-slate-600 hover:bg-white/75 hover:text-slate-950'
          )}
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-cyan-100 bg-white/70 text-cyan-700">
            <Home className="h-4 w-4" />
          </span>
          Home
        </NavLink>

        <div className="space-y-5">
          {NAV_GROUPS.map(group => (
            <div key={group.label}>
              <p className="mb-2 px-3 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">{group.label}</p>
              <div className="space-y-1">
                {group.items.map(item => (
                  <SidebarLink key={item.to} item={item} pendingInbox={pendingInbox} onNavigate={onNavigate} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="relative border-t border-slate-200 p-3">
        <NavLink
          to="/profile"
          onClick={onNavigate}
          className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 transition hover:bg-white/75 hover:text-slate-950"
        >
          <UserCircle className="h-4 w-4" />
          Recruiter Profile
        </NavLink>
        {onLogout && (
          <button
            type="button"
            onClick={onLogout}
            className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-50 hover:text-rose-700"
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
    <div className="workspace-grid flex h-screen overflow-hidden">
      <div className="hidden p-3 pr-0 lg:flex">
        <Sidebar pendingInbox={pendingInbox} onLogout={onLogout} onNavigate={() => {}} />
      </div>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm" onClick={closeMobile} aria-label="Close navigation" />
          <div className="absolute inset-y-0 left-0 w-72 p-3 shadow-xl">
            <Sidebar pendingInbox={pendingInbox} onLogout={onLogout} onNavigate={closeMobile} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="command-header border-b border-slate-200/80 bg-white/80 shadow-sm shadow-slate-200/50 backdrop-blur-xl">
          <div className="flex min-h-[72px] items-center gap-3 px-4 lg:px-6">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="chrome-button rounded-lg border border-slate-200 bg-white p-2 text-slate-600 shadow-sm hover:bg-slate-50 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="h-5 w-5" />
            </button>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1 text-xs font-semibold text-slate-400">
                Command Center <ChevronRight className="h-3 w-3" /> {title}
              </div>
              <h1 className="truncate font-display text-xl font-bold tracking-tight text-slate-950">{title}</h1>
            </div>

            <form onSubmit={submitSearch} className="hidden w-full max-w-md flex-none md:block">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={query}
                  onChange={event => setQuery(event.target.value)}
                  placeholder="Search pages, clients, trainers..."
                  className="h-11 w-full rounded-lg border border-slate-200/90 bg-slate-50/80 pl-9 pr-4 text-sm shadow-inner outline-none transition focus:border-slate-900 focus:bg-white focus:ring-4 focus:ring-slate-900/10"
                />
              </div>
            </form>

            <div className="flex flex-1 items-center justify-end gap-3">
              <div className="automation-spine">
                <span className="automation-node">R</span>
                <span className="h-px w-5 bg-cyan-200" />
                <span className="automation-node">T</span>
                <span className="h-px w-5 bg-emerald-200" />
                <span className="automation-node">PO</span>
                <span className="h-px w-5 bg-sky-200" />
                <span className="automation-node">I</span>
              </div>
              <div className="hidden items-center gap-2 xl:flex">
                <span className="command-chip">
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-500" />
                  TOC Agent
                </span>
                <span className="command-chip">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Invoice Auto
                </span>
              </div>
              <div className="hidden sm:block">
                <ThemeToggle />
              </div>
              <button
                type="button"
                onClick={() => navigate('/inbox')}
                className="chrome-button relative rounded-lg border border-slate-200 bg-white/90 p-2 text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:bg-white"
                aria-label="Client inbox"
              >
                <Bell className="h-5 w-5" />
                {pendingInbox > 0 && <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full bg-red-500 ring-2 ring-white" />}
              </button>

              <div className="chrome-button hidden items-center gap-2 rounded-lg border border-slate-200/90 bg-white px-3 py-2 text-xs font-bold text-slate-600 shadow-sm sm:flex">
                <span className={clsx('h-2 w-2 rounded-full shadow-sm', connected ? 'bg-emerald-500' : 'bg-amber-500')} />
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
                  className="h-11 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-4 text-sm outline-none transition focus:border-slate-900 focus:bg-white focus:ring-4 focus:ring-slate-900/10"
                />
              </div>
            </form>
        </header>

        <main className="command-main relative min-w-0 flex-1 overflow-y-auto">
          <div className="relative mx-auto w-full max-w-[1540px] px-4 py-6 lg:px-7 lg:py-7">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
