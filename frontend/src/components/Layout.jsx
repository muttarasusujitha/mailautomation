import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  BarChart3, Bell, BookOpen, BriefcaseBusiness, CalendarCheck,
  ChevronDown, ChevronRight, ClipboardCheck, FileSearch, FlaskConical, Home,
  Kanban, LayoutDashboard, Linkedin, ListChecks, LogOut, Mail, MapPin, Menu,
  Mic, Newspaper, PieChart, ReceiptText, ScrollText, Search, Settings, Upload,
  UserCircle, Users, Workflow, X, Zap,
} from 'lucide-react'
import BrandMark from './BrandMark'
import api from '../utils/api'
import PageLoader from './PageLoader'
import ErrorBoundary from './ErrorBoundary'
import FloatingIntegrations from './FloatingIntegrations'
import ChatAssistant from './ChatAssistant'

const NAV_GROUPS = [
  {
    label: 'Trainer Pipeline',
    items: [
      { to: '/dashboard',       label: 'Dashboard',        icon: LayoutDashboard, keywords: ['dashboard','stats','overview'] },
      { to: '/resume-upload',   label: 'Upload Resumes',   icon: Upload,          keywords: ['upload','resume','import'] },
      { to: '/requirements',    label: 'Find Trainers',    icon: FileSearch,      keywords: ['find','requirement','match'] },
      { to: '/shortlist1',      label: 'AI Pipeline',      icon: Zap,             keywords: ['advanced','shortlist1','shortlist','pipeline'] },
      { to: '/shortlist',       label: 'Shortlist',        icon: ListChecks,      keywords: ['shortlist','trainer shortlist'] },
      { to: '/profile-reviews', label: 'Profile Reviews',  icon: ClipboardCheck,  keywords: ['profile review','trainer rating','document review','skill fit'] },
      { to: '/trainers',        label: 'Trainer Database', icon: Users,           keywords: ['trainers','database'] },
    ],
    more: [
      { to: '/voice-ai-assistant', label: 'Voice AI Assistant', icon: Mic,        keywords: ['voice ai','voice assistant','hr assistant','recruiter assistant','voice recruiter'] },
      { to: '/linkedin-search',    label: 'LinkedIn Search',    icon: Linkedin,   keywords: ['linkedin','public search','client post search','trainer profile search'] },
      { to: '/linkedin-pipeline',  label: 'LinkedIn Pipeline',  icon: Workflow,   keywords: ['linkedin pipeline','linkedin automation','linkedin trainers','linkedin outreach'] },
      { to: '/naukri-search',      label: 'Naukri Search',      icon: Newspaper,  keywords: ['naukri','naukri search','naukri public','naukri trainer'] },
      { to: '/trainer-locations',  label: 'Trainer Locations',  icon: MapPin,     keywords: ['trainer location','locations','city','trainer city'] },
    ],
  },
  {
    label: 'Client Work',
    items: [
      { to: '/client-requests',      label: 'Client Requests',  icon: BriefcaseBusiness, keywords: ['client','requests','requirements'] },
      { to: '/interview-scheduled',  label: 'Interviews',       icon: CalendarCheck,     keywords: ['interview','schedule','meeting','meet link'] },
      { to: '/client-mail-pipeline', label: 'Client Pipeline',  icon: Kanban,            keywords: ['client pipeline','client mail pipeline','po','invoice','client po','client mails'] },
      { to: '/invoices',             label: 'Invoices',         icon: ReceiptText,       keywords: ['invoice','manual invoice','generate invoice','billing'] },
      { to: '/purchase-orders',      label: 'Purchase Orders',  icon: ScrollText,        keywords: ['purchase order','purchase orders','generate po','po generator'] },
    ],
    more: [
      { to: '/linkedin-client-pipeline', label: 'LinkedIn Client Pipeline', icon: Linkedin, keywords: ['linkedin client pipeline','client posts','client lead pipeline','mail 1'] },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/admin-dashboard', label: 'Analytics',  icon: BarChart3, keywords: ['admin dashboard','analytics'] },
      { to: '/emails',          label: 'Email Logs', icon: Mail,      keywords: ['email','logs','mail'] },
      { to: '/admin',           label: 'Settings',   icon: Settings,  keywords: ['admin','settings','gmail','whatsapp'] },
    ],
    more: [
      { to: '/toc-knowledge', label: 'ToC Knowledge', icon: BookOpen,      keywords: ['toc','curriculum','knowledge','course agenda'] },
      { to: '/lab-cost',      label: 'Lab Cost',      icon: FlaskConical,  keywords: ['lab cost','lab support','lab setup','cloud lab'] },
      { to: '/commercial',    label: 'Commercial',    icon: PieChart,      keywords: ['commercial','margin','profit','pricing'] },
    ],
  },
]

const ALL_NAV_ITEMS = NAV_GROUPS.flatMap(g => [...g.items, ...(g.more || [])])

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

function routeIsActive(pathname, to) {
  return pathname === to || pathname.startsWith(`${to}/`)
}

function moreGroupsForPath(pathname) {
  return Object.fromEntries(
    NAV_GROUPS
      .filter(group => (group.more || []).some(item => routeIsActive(pathname, item.to)))
      .map(group => [group.label, true])
  )
}

function Sidebar({ pendingInbox, onLogout, onNavigate, connected, pathname }) {
  const [openMore, setOpenMore] = useState(() => moreGroupsForPath(pathname))

  useEffect(() => {
    setOpenMore(prev => {
      const active = moreGroupsForPath(pathname)
      const next = { ...prev, ...active }
      return Object.keys(active).every(key => prev[key]) ? prev : next
    })
  }, [pathname])

  return (
    <aside className="sidebar animate-slide-in">
      {/* Brand header */}
      <div className="sidebar-header">
        <NavLink to="/home" onClick={onNavigate}>
          <BrandMark size="md" />
        </NavLink>

        <div className={clsx(
          'mt-4 flex items-center gap-2 rounded-lg border px-3 py-2',
          connected ? 'border-green-100 bg-green-50' : 'border-amber-100 bg-amber-50'
        )}>
          <span className={clsx('status-dot', connected ? 'green' : 'amber')} />
          <span className={clsx('text-[12px] font-semibold', connected ? 'text-green-700' : 'text-amber-700')}>
            {connected ? 'Gmail connected' : 'Gmail not connected'}
          </span>
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
                {group.more?.length > 0 && (
                  <>
                    <button
                      type="button"
                      onClick={() => setOpenMore(prev => ({ ...prev, [group.label]: !prev[group.label] }))}
                      className="nav-item w-full text-slate-400"
                      aria-expanded={!!openMore[group.label]}
                    >
                      <span className="nav-icon">
                        <ChevronDown className={clsx('h-[15px] w-[15px] transition-transform', openMore[group.label] && 'rotate-180')} />
                      </span>
                      <span className="text-[13px]">{openMore[group.label] ? 'Show less' : `More (${group.more.length})`}</span>
                    </button>
                    {openMore[group.label] && group.more.map(item => (
                      <NavItem key={item.to} item={item} pendingInbox={pendingInbox} onClick={onNavigate} />
                    ))}
                  </>
                )}
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
  const menuRef = useRef(null)
  const drawerRef = useRef(null)
  const contentRef = useRef(null)

  useEffect(() => {
    setMobileOpen(false)
    contentRef.current?.scrollTo({ top: 0, behavior: 'instant' })
  }, [location.pathname])

  useEffect(() => {
    if (!mobileOpen) return
    const drawer = drawerRef.current
    const focusable = () => [...drawer.querySelectorAll('a[href], button, input, select, textarea, [tabindex="0"]')].filter(el => !el.disabled)
    focusable()[0]?.focus()
    const handleKey = event => {
      if (event.key === 'Escape') { event.preventDefault(); setMobileOpen(false) }
      if (event.key !== 'Tab') return
      const items = focusable()
      const first = items[0], last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    const desktop = window.matchMedia('(min-width: 1024px)')
    const onResize = () => { if (desktop.matches) setMobileOpen(false) }
    drawer.addEventListener('keydown', handleKey)
    desktop.addEventListener('change', onResize)
    return () => {
      drawer.removeEventListener('keydown', handleKey)
      desktop.removeEventListener('change', onResize)
      menuRef.current?.focus()
    }
  }, [mobileOpen])

  useEffect(() => {
    let cancelled = false
    let pending = false
    const controller = new AbortController()
    const loadStatus = async () => {
      if (pending || cancelled || document.hidden) return
      pending = true
      try {
        const config = { signal: controller.signal, timeout: 10000, retry: false }
        const [inboxRes, gmailRes] = await Promise.allSettled([
          api.get('/inbox', { ...config, params: { status: 'pending_approval', limit: 1 } }),
          api.get('/gmail/auth-status', config),
        ])
        if (cancelled) return
        if (inboxRes.status === 'fulfilled') {
          const data = inboxRes.value.data
          if (!cancelled) setPendingInbox(data.stats?.pending_approval || data.total || 0)
        }
        if (gmailRes.status === 'fulfilled') {
          const data = gmailRes.value.data
          if (!cancelled) setConnected(!!data.connected)
        }
      } catch { if (!cancelled) setConnected(false) }
      finally { pending = false }
    }
    loadStatus()
    const iv = setInterval(loadStatus, 30000)
    document.addEventListener('visibilitychange', loadStatus)
    return () => { cancelled = true; controller.abort(); clearInterval(iv); document.removeEventListener('visibilitychange', loadStatus) }
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
        <Sidebar pendingInbox={pendingInbox} onLogout={onLogout} onNavigate={() => {}} connected={connected} pathname={location.pathname} />
      </div>

      {/* Mobile sidebar overlay */}
      {mobileOpen && (
        <div ref={drawerRef} id="mobile-navigation" role="dialog" aria-modal="true" aria-label="Navigation" className="fixed inset-0 z-[80] lg:hidden">
          <button
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          />
          <div className="mobile-drawer absolute inset-y-0 left-0 shadow-2xl">
            <Sidebar pendingInbox={pendingInbox} onLogout={onLogout} onNavigate={() => setMobileOpen(false)} connected={connected} pathname={location.pathname} />
          </div>
          <button
            type="button"
            aria-label="Close menu"
            className="absolute right-2 top-3 flex h-11 w-11 items-center justify-center rounded-lg bg-white shadow-md"
            onClick={() => setMobileOpen(false)}
          >
            <X className="h-4 w-4 text-slate-600" />
          </button>
        </div>
      )}

      {/* Main area */}
      <div className="main-area" inert={mobileOpen ? '' : undefined}>
        {/* Header */}
        <header className="app-header">
          {/* Mobile menu toggle */}
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="btn-ghost rounded-lg p-2 lg:hidden"
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
            aria-controls="mobile-navigation"
            ref={menuRef}
          >
            <Menu className="h-5 w-5" />
          </button>

          {/* Breadcrumb + title */}
          <div className="flex min-w-0 flex-1 items-center gap-1 text-[13px] font-semibold text-slate-400">
            <span className="hidden sm:inline">TrainerSync</span>
            <ChevronRight className="hidden h-3 w-3 sm:block" />
            <span className="truncate text-slate-800">{title}</span>
          </div>

          {/* Search */}
          <form onSubmit={submitSearch} className="hidden w-56 shrink-0 md:block xl:w-80">
            <div className="search-bar">
              <Search className="h-4 w-4" />
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search pages, trainers, clients..."
                aria-label="Search pages, trainers and clients"
              />
            </div>
          </form>

          {/* Right actions */}
          <div className="flex items-center gap-2">
            <FloatingIntegrations />
            <ErrorBoundary resetKey={`copilot:${location.pathname}`}>
              <ChatAssistant headerTrigger />
            </ErrorBoundary>
            {/* Gmail status */}
            <NavLink
              to="/admin"
              className={clsx(
                'hidden shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold xl:flex',
                connected
                  ? 'border-green-200 bg-green-50 text-green-700'
                  : 'border-amber-200 bg-amber-50 text-amber-700'
              )}
            >
              <span className={clsx('status-dot', connected ? 'green' : 'amber')} />
              {connected ? 'Gmail ready' : 'Connect Gmail'}
            </NavLink>

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
            <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search..." aria-label="Search pages, trainers and clients" />
          </div>
        </form>

        {/* Page output */}
        <main className="page-content" ref={contentRef}>
          <div className="mx-auto min-w-0 w-full max-w-[1540px]">
            <ErrorBoundary resetKey={location.pathname}>
              <Suspense fallback={<PageLoader />}><Outlet /></Suspense>
            </ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  )
}
