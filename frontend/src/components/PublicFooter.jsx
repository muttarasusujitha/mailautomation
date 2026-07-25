import { useNavigate } from 'react-router-dom'
import BrandMark from './BrandMark'

const FOOTER_GROUPS = [
  { title: 'Platform', links: [
    { label: 'Dashboard', path: '/dashboard' },
    { label: 'AI Matching', path: '/requirements' },
    { label: 'Pipeline', path: '/shortlist1' },
    { label: 'Analytics', path: '/admin-dashboard' },
    { label: 'Client Inbox', path: '/client-requests' },
  ] },
  { title: 'Integrations', links: [
    { label: 'Gmail', path: '/admin' },
    { label: 'WhatsApp API', path: '/admin' },
    { label: 'Microsoft Teams', path: '/admin' },
    { label: 'Google Calendar', path: '/admin' },
    { label: 'Gemini AI', path: '/admin' },
  ] },
  { title: 'Company', links: [
    { label: 'About', path: '/home' },
    { label: 'Contact', path: '/contact' },
    { label: 'Privacy Policy', path: '/home' },
    { label: 'Terms', path: '/home' },
    { label: 'Support', path: '/feedback' },
  ] },
]

export default function PublicFooter() {
  const navigate = useNavigate()

  return (
    <footer className="relative z-10 bg-slate-950 px-7 py-11 text-white">
      <div className="mx-auto max-w-6xl">
        <div className="mb-9 grid grid-cols-1 gap-10 md:grid-cols-[1.8fr_1fr_1fr_1fr]">
          <div>
            <BrandMark size="sm" theme="dark" className="mb-3" onClick={() => navigate('/home')} />
            <p className="max-w-60 text-[13px] leading-7 text-slate-500">
              AI-powered trainer matching and operations platform. Match, outreach, track, and confirm - fully automated.
            </p>
          </div>

          {FOOTER_GROUPS.map(group => (
            <div key={group.title}>
              <p className="mb-3.5 text-xs font-bold uppercase tracking-wide text-slate-400">{group.title}</p>
              <ul className="flex list-none flex-col gap-2">
                {group.links.map(link => (
                  <li key={`${group.title}-${link.label}`}>
                    <button
                      type="button"
                      onClick={() => navigate(link.path)}
                      className="text-left text-[13px] text-slate-500 transition hover:text-white"
                    >
                      {link.label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-6">
          <p className="m-0 text-xs text-slate-600">&copy; 2026 TrainerSync - Clahan Technologies. All rights reserved.</p>
          <p className="m-0 text-xs text-slate-700">Match - Outreach - Track - Confirm</p>
        </div>
      </div>
    </footer>
  )
}
