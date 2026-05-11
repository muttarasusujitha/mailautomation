import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, Users, FileSearch, Mail, Upload, Zap, Menu, X, Settings, Calendar, ListChecks } from 'lucide-react'
import { useState, useEffect } from 'react'
import clsx from 'clsx'

const NAV = [
  { to: '/dashboard',    icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/upload',       icon: Upload,           label: 'Upload Database' },
  { to: '/requirements', icon: FileSearch,       label: 'Find Trainers' },
  { to: '/shortlist',    icon: ListChecks,       label: 'Shortlist' },
  { to: '/trainers',     icon: Users,            label: 'All Trainers' },
  { to: '/emails',       icon: Mail,             label: 'Email Logs' },
  { to: '/interviews',   icon: Calendar,         label: 'Interviews' },
  { to: '/admin',        icon: Settings,         label: 'Admin Settings' },
]

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pipelineActive, setPipelineActive] = useState(true)

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

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {sidebarOpen && (
        <div className="fixed inset-0 z-20 bg-black/20 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}
      <aside className={clsx(
        "fixed inset-y-0 left-0 z-30 w-64 bg-white border-r border-slate-100 flex flex-col transition-transform duration-300 lg:translate-x-0 lg:static lg:z-auto",
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      )}>
        <div className="flex items-center gap-3 px-5 py-5 border-b border-slate-100">
          <div className="w-9 h-9 bg-brand-500 rounded-xl flex items-center justify-center flex-shrink-0">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <div>
            <p className="font-display font-bold text-slate-900 text-base leading-tight">TrainerSync</p>
            <p className="text-xs text-slate-400 font-medium">AI Matching Platform</p>
          </div>
          <button className="ml-auto lg:hidden" onClick={() => setSidebarOpen(false)}>
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider px-3 mb-3">Main Menu</p>
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to} onClick={() => setSidebarOpen(false)}
              className={({ isActive }) => isActive ? 'sidebar-item-active' : 'sidebar-item-inactive'}>
              <Icon className="w-4.5 h-4.5 flex-shrink-0" size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="px-3 py-4 border-t border-slate-100">
          <NavLink to="/admin" onClick={() => setSidebarOpen(false)}
            className={({ isActive }) => clsx('flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all',
              isActive ? 'bg-brand-50 text-brand-600' : 'hover:bg-slate-50 text-slate-600')}>
            <div className="w-8 h-8 rounded-full bg-brand-100 flex items-center justify-center flex-shrink-0">
              <span className="text-brand-600 text-xs font-bold">A</span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-slate-800">Admin</p>
              <p className="text-xs text-slate-400">Recruiter Account</p>
            </div>
            <Settings className="w-4 h-4 text-slate-400 flex-shrink-0" />
          </NavLink>
        </div>
      </aside>
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="bg-white border-b border-slate-100 px-4 lg:px-6 py-3.5 flex items-center gap-4 flex-shrink-0">
          <button className="lg:hidden p-1.5 rounded-lg hover:bg-slate-100" onClick={() => setSidebarOpen(true)}>
            <Menu className="w-5 h-5 text-slate-600" />
          </button>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            <div className={clsx('w-2 h-2 rounded-full', pipelineActive ? 'bg-emerald-400 animate-pulse' : 'bg-red-400')} />
            <span className={clsx('text-xs font-medium hidden sm:block', pipelineActive ? 'text-emerald-600' : 'text-red-500')}>
              {pipelineActive ? 'Active' : 'Not Active'}
            </span>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
