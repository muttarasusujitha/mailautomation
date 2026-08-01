import { MessageSquare, Phone, Settings, User } from 'lucide-react'
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
    className: 'bg-indigo-600 hover:bg-indigo-500 shadow-indigo-600/35',
    bottom: '16.5rem',
  },
  {
    label: 'WhatsApp',
    title: 'Open WhatsApp',
    externalApp: EXTERNAL_APPS.whatsapp,
    Icon: Phone,
    className: 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-600/35',
    bottom: '13rem',
  },
  {
    label: 'Profile',
    title: 'Open user profile',
    path: '/profile',
    Icon: User,
    className: 'bg-slate-700 hover:bg-slate-600 shadow-slate-700/30',
    bottom: '9.5rem',
  },
  {
    label: 'Admin',
    title: 'Open admin settings',
    path: '/admin',
    Icon: Settings,
    className: 'bg-blue-600 hover:bg-blue-500 shadow-blue-600/35',
    bottom: '6rem',
  },
]

export default function FloatingIntegrations() {
  const navigate = useNavigate()

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
    <>
      {ACTIONS.map((action) => {
        const { label, title, Icon, className, bottom } = action
        return (
        <button
          key={label}
          type="button"
          onClick={() => openAction(action)}
          title={title}
          aria-label={title}
          style={{ bottom }}
          className={`group fixed right-6 z-40 flex h-12 w-12 items-center justify-center rounded-full text-white shadow-xl transition-all duration-300 hover:scale-110 ${className}`}
        >
          <Icon className="h-5 w-5" />
          <span className="pointer-events-none absolute right-14 rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-semibold text-white opacity-0 shadow-lg transition group-hover:opacity-100">
            {label}
          </span>
        </button>
        )
      })}
    </>
  )
}
