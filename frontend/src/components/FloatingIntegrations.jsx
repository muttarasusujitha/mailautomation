import { useEffect, useRef } from 'react'
import { MessageSquare, Phone, Settings, User, Zap } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

const EXTERNAL_APPS = {
  teams: {
    appUrl: 'msteams://teams.microsoft.com/',
    fallbackUrl: 'https://teams.microsoft.com/v2/',
  },
  whatsapp: {
    appUrl: 'whatsapp://send',
    fallbackUrl: 'https://web.whatsapp.com/',
  },
}

const ACTIONS = [
  {
    label: 'Teams',
    title: 'Open Microsoft Teams',
    externalApp: EXTERNAL_APPS.teams,
    Icon: MessageSquare,
    className: 'text-indigo-700 hover:bg-indigo-50',
  },
  {
    label: 'WhatsApp',
    title: 'Open WhatsApp',
    externalApp: EXTERNAL_APPS.whatsapp,
    Icon: Phone,
    className: 'text-emerald-700 hover:bg-emerald-50',
  },
  {
    label: 'Profile',
    title: 'Open user profile',
    path: '/profile',
    Icon: User,
    className: 'text-slate-700 hover:bg-slate-100',
  },
  {
    label: 'Admin',
    title: 'Open admin settings',
    path: '/admin',
    Icon: Settings,
    className: 'text-blue-700 hover:bg-blue-50',
  },
]

export default function FloatingIntegrations() {
  const navigate = useNavigate()
  const menuRef = useRef(null)

  useEffect(() => {
    const dismiss = event => {
      if (event.type === 'pointerdown' && menuRef.current?.contains(event.target)) return
      if (event.type === 'keydown' && event.key !== 'Escape') return
      menuRef.current?.removeAttribute('open')
      if (event.type === 'keydown') menuRef.current?.querySelector('summary')?.focus()
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', dismiss)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', dismiss)
    }
  }, [])

  const openAction = (action) => {
    if (action.externalApp) {
      window.location.href = action.externalApp.appUrl
      window.setTimeout(() => {
        if (document.visibilityState === 'visible') {
          window.open(action.externalApp.fallbackUrl, '_blank', 'noopener,noreferrer')
        }
      }, 700)
      return
    }
    navigate(action.path)
  }

  return (
    <details ref={menuRef} className="quick-links relative shrink-0">
      <summary
        aria-label="Open quick links"
        title="Open quick links"
        className="quick-links-trigger flex min-h-10 cursor-pointer list-none items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 [&::-webkit-details-marker]:hidden"
      >
        <Zap className="h-4 w-4 text-blue-600" />
        <span className="hidden xl:inline">Quick links</span>
      </summary>
      <div className="quick-links-menu absolute right-0 top-full z-[90] mt-2 w-56 overflow-hidden rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl shadow-slate-900/10">
        <p className="px-3 pb-1.5 pt-2 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">Shortcuts</p>
        {ACTIONS.map(action => {
          const { label, title, Icon, className } = action
          return (
            <button
              key={label}
              type="button"
              aria-label={title}
              onClick={event => {
                event.currentTarget.closest('details')?.removeAttribute('open')
                openAction(action)
              }}
              title={title}
              className={`flex min-h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-semibold transition ${className}`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          )
        })}
      </div>
    </details>
  )
}
