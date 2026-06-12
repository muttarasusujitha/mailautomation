import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { getDashboardStats, clearDatabase } from '../utils/api'
import {
  Users, Mail, TrendingUp,
  RefreshCw, BarChart2, Activity, Trash2, AlertTriangle, Star,
  ArrowUpRight, Database, Send,
  BriefcaseBusiness, Inbox, MessageSquare, Loader2, Settings,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Area, AreaChart, Legend,
} from 'recharts'
import toast from 'react-hot-toast'
import clsx from 'clsx'

function AnimatedNumber({ value, duration = 1100 }) {
  const [display, setDisplay] = useState(0)
  const start = useRef(0)

  useEffect(() => {
    const numeric = Number(value || 0)
    if (numeric === 0) {
      setDisplay(0)
      start.current = 0
      return
    }

    const startTime = Date.now()
    const startVal = start.current
    const tick = () => {
      const elapsed = Date.now() - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(startVal + (numeric - startVal) * eased))
      if (progress < 1) requestAnimationFrame(tick)
      else start.current = numeric
    }
    requestAnimationFrame(tick)
  }, [value, duration])

  return <span>{display.toLocaleString('en-IN')}</span>
}

function normaliseRate(value) {
  const n = Number(value || 0)
  if (n > 0 && n <= 1) return n * 100
  return n
}

function formatPercent(value) {
  const n = Math.max(0, Math.min(100, Number(value || 0)))
  return `${n.toFixed(n % 1 ? 1 : 0)}%`
}

function formatDateTime(value) {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function clientStatusLabel(status = '') {
  const labels = {
    pending_approval: 'Pending Approval',
    auto_sent: 'Auto Sent',
    approved: 'Approved',
    rejected: 'Rejected',
    spam: 'Spam',
  }
  return labels[status] || status || 'New'
}

function clientStatusClass(status = '') {
  if (status === 'pending_approval') return 'badge-amber'
  if (status === 'auto_sent') return 'badge-green'
  if (status === 'approved') return 'badge-blue'
  if (status === 'rejected' || status === 'spam') return 'badge-red'
  return 'badge-slate'
}

function clientRequestTitle(item = {}) {
  const extracted = item.extracted || {}
  const domain = extracted.technology_needed || extracted.domain || extracted.primary_skill || ''
  if (domain) return `Client requesting ${domain} trainer`
  return item.subject || 'New client trainer request'
}

function clientRequestSummary(item = {}) {
  const extracted = item.extracted || {}
  return extracted.email_summary || item.clean_body || item.raw_body || item.subject || ''
}

function TooltipBox({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-4 py-3 text-sm shadow-xl">
      <p className="mb-1 font-semibold text-slate-700">{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-medium">
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  )
}

const dashboardMotionCss = `
  @keyframes dashFloatIn {
    from { opacity: 0; transform: translateY(14px) scale(0.985); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  @keyframes dashSoftGlow {
    0%, 100% { transform: translate3d(-1%, -1%, 0); opacity: 0.7; }
    50% { transform: translate3d(1.5%, 1%, 0); opacity: 1; }
  }
  @keyframes dashSheen {
    0% { transform: translateX(-120%) rotate(9deg); opacity: 0; }
    24% { opacity: 0.42; }
    64% { opacity: 0.18; }
    100% { transform: translateX(130%) rotate(9deg); opacity: 0; }
  }
  @keyframes dashBarGlow {
    0% { transform: translateX(-80%); }
    100% { transform: translateX(240%); }
  }
  .dashboard-shell {
    position: relative;
    isolation: isolate;
  }
  .dashboard-shell::before {
    content: '';
    position: fixed;
    inset: 0;
    z-index: -2;
    pointer-events: none;
    background:
      linear-gradient(112deg, transparent 0 24%, rgba(14,165,233,0.08) 24.2% 24.5%, transparent 25% 100%),
      repeating-linear-gradient(90deg, rgba(14,165,233,0.035) 0 1px, transparent 1px 92px),
      linear-gradient(180deg, rgba(255,255,255,0), rgba(240,249,255,0.42));
    animation: none;
  }
  .dashboard-hero {
    position: relative;
    overflow: hidden;
    border-color: rgba(14,165,233,0.18);
    background:
      linear-gradient(135deg, rgba(255,255,255,0.92), rgba(240,249,255,0.78) 48%, rgba(240,253,244,0.68)),
      linear-gradient(90deg, rgba(14,165,233,0.1), transparent 42%, rgba(16,185,129,0.09));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.92), 0 24px 72px rgba(14,116,144,0.12);
  }
  .dashboard-hero::before {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    background:
      linear-gradient(104deg, transparent 0 38%, rgba(255,255,255,0.62) 44%, rgba(125,211,252,0.18) 49%, transparent 58%),
      repeating-linear-gradient(90deg, rgba(14,165,233,0.08) 0 1px, transparent 1px 64px);
    opacity: 0.76;
  }
  .dashboard-hero::after,
  .dashboard-card-motion::after {
    content: '';
    position: absolute;
    inset: auto 0 0 0;
    height: 2px;
    pointer-events: none;
    background: linear-gradient(90deg, rgba(14,165,233,0.78), rgba(16,185,129,0.52), rgba(245,158,11,0.36));
  }
  .dashboard-card-motion {
    position: relative;
    animation: dashFloatIn 0.58s cubic-bezier(0.22,1,0.36,1) both;
    background:
      linear-gradient(145deg, rgba(255,255,255,0.9), rgba(248,250,252,0.76)),
      linear-gradient(90deg, rgba(14,165,233,0.055), transparent 44%, rgba(16,185,129,0.04));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.92), 0 18px 45px rgba(15,23,42,0.06);
    backdrop-filter: blur(18px);
  }
  .dashboard-card-motion:hover {
    background:
      linear-gradient(145deg, rgba(255,255,255,0.95), rgba(240,249,255,0.82)),
      linear-gradient(90deg, rgba(14,165,233,0.08), transparent 44%, rgba(16,185,129,0.06));
  }
  .ops-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    border-radius: 999px;
    border: 1px solid rgba(14,165,233,0.16);
    background: linear-gradient(135deg, rgba(255,255,255,0.86), rgba(240,249,255,0.72));
    padding: 0.35rem 0.7rem;
    font-size: 0.72rem;
    font-weight: 800;
    color: #0e7490;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.9), 0 8px 20px rgba(15,23,42,0.05);
  }
  .ops-engine-card {
    border: 1px solid rgba(14,165,233,0.16);
    background:
      linear-gradient(145deg, rgba(255,255,255,0.9), rgba(240,249,255,0.72)),
      repeating-linear-gradient(90deg, rgba(14,165,233,0.06) 0 1px, transparent 1px 58px);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.9), 0 18px 45px rgba(15,23,42,0.06);
    backdrop-filter: blur(18px);
  }
  .dashboard-core-panel {
    position: relative;
    overflow: hidden;
    border: 1px solid rgba(14,165,233,0.18);
    background:
      linear-gradient(145deg, rgba(255,255,255,0.86), rgba(240,249,255,0.68)),
      repeating-linear-gradient(90deg, rgba(14,165,233,0.055) 0 1px, transparent 1px 42px);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.92), 0 22px 52px rgba(14,116,144,0.12);
    clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px));
  }
  .dashboard-core-panel::before {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    background:
      linear-gradient(120deg, transparent 0 34%, rgba(255,255,255,0.56) 42%, rgba(125,211,252,0.16) 48%, transparent 58%),
      linear-gradient(90deg, rgba(14,165,233,0.14), transparent 40%, rgba(245,158,11,0.08));
    opacity: 0.72;
  }
  .dashboard-core-row {
    position: relative;
    border: 1px solid rgba(226,232,240,0.9);
    background: rgba(255,255,255,0.58);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.82);
  }
  .dashboard-core-meter {
    position: relative;
    overflow: hidden;
    height: 0.42rem;
    border-radius: 999px;
    background: rgba(226,232,240,0.82);
  }
  .dashboard-core-meter span {
    display: block;
    height: 100%;
    border-radius: inherit;
    box-shadow: 0 0 18px rgba(14,165,233,0.22);
  }
  .dashboard-panel {
    animation: dashFloatIn 0.62s cubic-bezier(0.22,1,0.36,1) both;
  }
  .dashboard-progress {
    position: relative;
    overflow: hidden;
    box-shadow: inset 0 0 0 1px rgba(15,23,42,0.04);
  }
  .dashboard-progress::after {
    content: '';
    position: absolute;
    inset: 0;
    width: 38%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.42), transparent);
    animation: dashBarGlow 2.7s ease-in-out infinite;
  }
`

function Panel({ title, eyebrow, badge, children, className }) {
  return (
    <section className={clsx('card dashboard-panel p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-blue-100 hover:shadow-card-lg', className)}>
      <div className="mb-5 flex items-center justify-between gap-3">
        <div>
          {eyebrow && <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{eyebrow}</p>}
          <h2 className="section-title">{title}</h2>
        </div>
        {badge && <span className="badge-slate">{badge}</span>}
      </div>
      {children}
    </section>
  )
}

function PulseMetric({ label, value, sub, color = 'bg-brand-500' }) {
  const safe = Math.max(0, Math.min(100, Number(value || 0)))
  return (
    <div>
      <div className="mb-2 flex items-end justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-800">{label}</p>
          {sub && <p className="text-xs text-slate-400">{sub}</p>}
        </div>
        <span className="font-display text-lg font-bold text-slate-900">{formatPercent(safe)}</span>
      </div>
      <div className="dashboard-progress h-2.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className={clsx('h-full rounded-full transition-all duration-1000 ease-out', color)}
          style={{ width: `${safe}%` }}
        />
      </div>
    </div>
  )
}

function StatCard({ icon: Icon, label, value, sub, tone, loading, linkTo, delay = 0 }) {
  const navigate = useNavigate()
  const tones = {
    blue: 'bg-blue-50 text-brand-500 border-blue-100',
    purple: 'bg-purple-50 text-purple-500 border-purple-100',
    emerald: 'bg-emerald-50 text-emerald-500 border-emerald-100',
    green: 'bg-green-50 text-green-500 border-green-100',
    orange: 'bg-orange-50 text-orange-500 border-orange-100',
    sky: 'bg-sky-50 text-sky-500 border-sky-100',
    amber: 'bg-amber-50 text-amber-500 border-amber-100',
    red: 'bg-red-50 text-red-500 border-red-100',
  }

  return (
    <button
      type="button"
      onClick={() => linkTo && navigate(linkTo)}
      style={{ animationDelay: `${delay}ms` }}
      className={clsx(
        'group dashboard-card-motion relative flex min-h-[142px] items-start gap-4 overflow-hidden rounded-xl border border-slate-200 p-5 text-left shadow-[0_18px_45px_rgba(15,23,42,0.06)] transition-all duration-300',
        'hover:-translate-y-1 hover:border-slate-300 hover:shadow-[0_22px_55px_rgba(15,23,42,0.09)] focus:outline-none focus:ring-2 focus:ring-slate-500/20',
        linkTo ? 'cursor-pointer' : 'cursor-default'
      )}
    >
      <div className="absolute inset-x-0 top-0 h-1 bg-slate-200 opacity-80 transition-opacity duration-300 group-hover:opacity-100" />
      <div className="absolute -right-8 -top-10 h-24 w-24 rotate-12 rounded-[18px] bg-slate-100/70" />
      <div className="absolute right-3 top-3 flex gap-0.5 opacity-0 transition-opacity duration-300 group-hover:opacity-100">
        {[0, 1, 2].map(i => <span key={i} className="h-1 w-1 rounded-full bg-cyan-400 animate-pulse" style={{ animationDelay: `${i * 130}ms` }} />)}
      </div>
      <div className={clsx('stat-icon border transition-transform duration-300 group-hover:scale-110', tones[tone])}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
        {loading ? (
          <div className="h-8 w-20 animate-pulse rounded-lg bg-slate-100" />
        ) : (
          <p className="font-display text-3xl font-black tracking-tight text-slate-950">
            <AnimatedNumber value={value} />
          </p>
        )}
        {sub && <p className="mt-1 text-xs text-slate-400">{sub}</p>}
        {linkTo && (
          <p className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-brand-500 opacity-0 transition-opacity group-hover:opacity-100">
            View details <ArrowUpRight className="h-3 w-3" />
          </p>
        )}
      </div>
    </button>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [clientInbox, setClientInbox] = useState({ emails: [], stats: {}, whatsapp_logs: [] })
  const [gmailStatus, setGmailStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [syncingInbox, setSyncingInbox] = useState(false)
  const [showClear, setShowClear] = useState(false)
  const [clearing, setClearing] = useState(false)
  const navigate = useNavigate()

  const load = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    try {
      const [statsRes, inboxRes, gmailRes] = await Promise.allSettled([
        getDashboardStats(),
        api.get('/inbox', { params: { limit: 5 } }),
        api.get('/gmail/auth-status'),
      ])

      if (statsRes.status === 'fulfilled') {
        setStats(statsRes.value.data)
      } else {
        toast.error(statsRes.reason?.message || 'Could not load dashboard stats')
      }

      if (inboxRes.status === 'fulfilled') {
        setClientInbox(inboxRes.value.data || { emails: [], stats: {}, whatsapp_logs: [] })
      } else {
        setClientInbox({ emails: [], stats: {}, whatsapp_logs: [] })
      }

      if (gmailRes.status === 'fulfilled') {
        setGmailStatus(gmailRes.value.data)
      } else {
        setGmailStatus({ connected: false })
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleClear = async () => {
    setClearing(true)
    try {
      await clearDatabase()
      toast.success('Database cleared')
      setShowClear(false)
      load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setClearing(false)
    }
  }

  const syncClientInbox = async () => {
    if (syncingInbox) return
    setSyncingInbox(true)
    try {
      const res = await api.post('/gmail/sync-now?limit=50')
      const processed = Number(res.data?.processed_count || 0)
      const skipped = Number(res.data?.skipped || 0)
      if (processed > 0) {
        try {
          const latestRes = await api.get('/inbox', { params: { limit: 1 } })
          const latest = latestRes.data?.emails?.[0]
          if (latest && latest.status !== 'spam') {
            toast.success(clientRequestTitle(latest), { duration: 7000 })
          } else {
            toast.success(`Client inbox checked: ${processed} processed, ${skipped} skipped`)
          }
        } catch {
          toast.success(`Client inbox checked: ${processed} processed, ${skipped} skipped`)
        }
      } else {
        toast.success(`Client inbox checked: ${processed} processed, ${skipped} skipped`)
      }
      await load(true)
    } catch (e) {
      toast.error(e.message || 'Client inbox sync failed')
    } finally {
      setSyncingInbox(false)
    }
  }

  const totalEmails = Number(stats?.total_emails_sent || 0)
  const failedEmails = Number(stats?.total_emails_failed || 0)
  const totalReplies = Number(stats?.total_replies || 0)
  const totalTrainers = Number(stats?.total_trainers || 0)
  const pendingReview = Number(stats?.pending_review || 0)
  const interested = Number(stats?.interested_count || 0)
  const whatsapp = stats?.whatsapp || {}
  const whatsappSent = Number(whatsapp.sent || 0)
  const whatsappFailed = Number(whatsapp.failed || 0)
  const whatsappReplies = Number(whatsapp.replies || 0)
  const clientStats = clientInbox?.stats || {}
  const recentClientEmails = clientInbox?.emails || []
  const latestClientTrainerRequest = recentClientEmails.find(item =>
    item?.status !== 'spam' && (item?.extracted?.is_training_request || item?.requirement_id)
  )
  const clientToday = Number(clientStats.today || 0)
  const clientPending = Number(clientStats.pending_approval || 0)
  const clientAutoSent = Number(clientStats.auto_sent || 0)
  const clientRequirements = Number(clientStats.requirements_created || 0)
  const gmailConnected = !!gmailStatus?.connected
  const gmailUser = gmailStatus?.gmail_user || gmailStatus?.configured_user || ''
  const gmailUserLabel = gmailUser ? ` as ${gmailUser}` : ''
  const replyRate = normaliseRate(stats?.reply_rate || (totalEmails ? (totalReplies / totalEmails) * 100 : 0))
  const interestRate = normaliseRate(stats?.interest_rate || (totalTrainers ? (interested / totalTrainers) * 100 : 0))
  const deliveryRate = totalEmails + failedEmails ? (totalEmails / (totalEmails + failedEmails)) * 100 : 100
  const reviewLoad = totalTrainers ? (pendingReview / totalTrainers) * 100 : 0

  const statusData = stats ? [
    { name: 'Interested', value: stats.interested_count, color: '#10b981' },
    { name: 'Contacted', value: stats.contacted_count, color: '#2563eb' },
    { name: 'Confirmed', value: stats.confirmed_count, color: '#8b5cf6' },
    { name: 'Pending', value: stats.pending_review, color: '#f59e0b' },
    { name: 'Declined', value: stats.declined_count, color: '#ef4444' },
  ].filter(d => Number(d.value || 0) > 0) : []

  const scoreDistData = (stats?.score_distribution || []).map(b => ({
    range: b._id === 'Other' ? 'Other' : `${b._id}-${Number(b._id) + 19}`,
    count: b.count,
  }))

  const activityData = [
    { day: 'Mon', emails: 12, replies: 4 },
    { day: 'Tue', emails: 8, replies: 3 },
    { day: 'Wed', emails: 15, replies: 7 },
    { day: 'Thu', emails: 10, replies: 5 },
    { day: 'Fri', emails: 18, replies: 9 },
    { day: 'Sat', emails: 6, replies: 2 },
    { day: 'Sun', emails: 3, replies: 1 },
  ]

  const statCards = [
    { icon: BriefcaseBusiness, label: 'Client Requests', value: clientToday, sub: 'Received today', tone: 'blue', linkTo: '/client-requests' },
    { icon: Inbox, label: 'Client Pending', value: clientPending, sub: 'Needs approval', tone: 'amber', linkTo: '/client-requests' },
    { icon: Users, label: 'Total Trainers', value: stats?.total_trainers ?? 0, sub: 'In database', tone: 'blue', linkTo: '/trainers' },
    { icon: Mail, label: 'Emails Sent', value: stats?.total_emails_sent ?? 0, sub: 'Outreach emails', tone: 'purple', linkTo: '/emails' },
    { icon: TrendingUp, label: 'Replies', value: stats?.total_replies ?? 0, sub: 'Trainer replies', tone: 'emerald', linkTo: '/emails' },
    { icon: BarChart2, label: 'Requirements', value: stats?.total_requirements ?? 0, sub: 'Active searches', tone: 'orange', linkTo: '/requirements' },
    { icon: Activity, label: 'Confirmed', value: stats?.confirmed_count ?? 0, sub: 'Ready to close', tone: 'sky', linkTo: '/shortlist1' },
    { icon: Send, label: 'WhatsApp Sent', value: whatsappSent, sub: 'Queued/sent/delivered', tone: 'green' },
  ]

  return (
    <div className="dashboard-shell space-y-5 animate-fade-in">
      <style>{dashboardMotionCss}</style>
      <section className="card dashboard-hero overflow-hidden">
        <div className="relative grid gap-4 p-4 lg:grid-cols-[1fr_340px] lg:p-5">
          <div className="min-w-0">
            <div className="mb-1.5 inline-flex items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              Live operational overview
            </div>
            <h1 className="font-display text-2xl font-black tracking-tight text-slate-950 sm:text-3xl">
              Dashboard
            </h1>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
              Track trainer inventory, outreach movement, reply quality, and work that needs recruiter attention.
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {['Trainer intelligence', 'Client inbox', 'Mail automation', 'PO to invoice'].map(item => (
                <span key={item} className="ops-chip">
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-500" />
                  {item}
                </span>
              ))}
            </div>
            <div className="mt-2 grid max-w-3xl gap-2 sm:grid-cols-3">
              {[
                ['AI matching', 'Live', 'bg-blue-50 text-blue-700 border-blue-100'],
                ['Mail automation', gmailConnected ? 'Ready' : 'Setup needed', gmailConnected ? 'bg-emerald-50 text-emerald-700 border-emerald-100' : 'bg-amber-50 text-amber-700 border-amber-100'],
                ['Pipeline sync', refreshing ? 'Refreshing' : 'Normal', refreshing ? 'bg-sky-50 text-sky-700 border-sky-100' : 'bg-slate-50 text-slate-600 border-slate-200'],
              ].map(([label, value, klass], i) => (
                <div
                  key={label}
                  className={clsx('dashboard-card-motion rounded-lg border px-3 py-2 shadow-sm', klass)}
                  style={{ animationDelay: `${120 + i * 80}ms` }}
                >
                  <p className="text-[10px] font-bold uppercase tracking-wide opacity-70">{label}</p>
                  <p className="text-sm font-black">{value}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="dashboard-core-panel relative p-4">
            <div className="relative flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.18em] text-cyan-700">Ops Core</p>
                <p className="mt-1 font-display text-lg font-black text-slate-950">Recruiting Signal</p>
              </div>
              <div className={clsx(
                'rounded-lg border px-2.5 py-1 text-right text-[10px] font-black uppercase tracking-wide',
                gmailConnected ? 'border-emerald-100 bg-emerald-50 text-emerald-700' : 'border-amber-100 bg-amber-50 text-amber-700'
              )}>
                {gmailConnected ? 'Synced' : 'Standby'}
              </div>
            </div>
            <div className="relative mt-4 space-y-2.5">
              {[
                ['Delivery Mesh', deliveryRate, 'bg-gradient-to-r from-cyan-500 to-emerald-400'],
                ['Reply Signal', replyRate, 'bg-gradient-to-r from-sky-500 to-blue-600'],
                ['Review Load', reviewLoad, 'bg-gradient-to-r from-amber-400 to-orange-500'],
              ].map(([label, rawValue, tone]) => {
                const safeValue = Math.max(0, Math.min(100, Number(rawValue || 0)))
                return (
                  <div key={label} className="dashboard-core-row rounded-lg px-3 py-2.5">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <span className="text-xs font-bold text-slate-600">{label}</span>
                      <span className="font-mono text-[11px] font-black text-slate-900">{formatPercent(safeValue)}</span>
                    </div>
                    <div className="dashboard-core-meter">
                      <span className={tone} style={{ width: `${safeValue}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="relative mt-3 grid grid-cols-3 gap-2">
              {[
                ['Profiles', totalTrainers],
                ['Pending', clientPending],
                ['Replies', totalReplies],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-slate-200/80 bg-white/60 px-2 py-2 text-center shadow-sm">
                  <p className="font-mono text-sm font-black text-slate-950">{loading ? '-' : Number(value || 0).toLocaleString('en-IN')}</p>
                  <p className="mt-0.5 truncate text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="relative flex flex-wrap items-center justify-between gap-3 border-t border-cyan-100 bg-white/62 px-4 py-2 backdrop-blur">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <Database className="h-4 w-4 text-slate-400" />
            {loading ? 'Loading dashboard data...' : `${totalTrainers.toLocaleString('en-IN')} trainer profiles synced`}
          </div>
          <div className="flex gap-2">
            <button onClick={() => setShowClear(true)} className="btn-secondary text-sm text-red-500 border-red-100 hover:border-red-300">
              <Trash2 className="h-4 w-4" /> Clear DB
            </button>
            <button onClick={() => load(true)} disabled={refreshing} className="btn-secondary text-sm">
              <RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} /> Refresh
            </button>
          </div>
        </div>
      </section>

      {showClear && (
        <div className="card border-red-100 bg-red-50 p-5 animate-slide-up">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-500" />
            <div className="flex-1">
              <p className="font-semibold text-red-800">Clear entire database?</p>
              <p className="mt-1 text-sm text-red-600">This will delete all trainers, requirements, shortlists and email logs permanently.</p>
              <div className="mt-3 flex gap-3">
                <button onClick={handleClear} disabled={clearing} className="btn-danger text-sm">
                  {clearing ? <><RefreshCw className="h-4 w-4 animate-spin" /> Clearing...</> : 'Yes, clear all'}
                </button>
                <button onClick={() => setShowClear(false)} className="btn-secondary text-sm">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {statCards.map((card, i) => (
          <StatCard key={card.label} {...card} loading={loading} delay={i * 55} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_380px]">
        <Panel
          title="Client Request Flow"
          eyebrow="Client automation"
          badge={gmailConnected ? 'Gmail connected' : 'Gmail not connected'}
        >
          {latestClientTrainerRequest && (
            <button
              type="button"
              onClick={() => navigate('/client-requests')}
              className="mb-4 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-left shadow-sm transition hover:border-brand-200 hover:bg-brand-50"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[11px] font-black uppercase tracking-wide text-brand-600">New client notification</p>
                  <p className="mt-1 truncate text-base font-black text-slate-950">
                    {clientRequestTitle(latestClientTrainerRequest)}
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                    From {latestClientTrainerRequest.from_name || latestClientTrainerRequest.from_email || 'Client'}
                    {latestClientTrainerRequest.received_at ? ` - ${formatDateTime(latestClientTrainerRequest.received_at)}` : ''}
                    {clientRequestSummary(latestClientTrainerRequest) ? ` - ${clientRequestSummary(latestClientTrainerRequest)}` : ''}
                  </p>
                </div>
                <span className={clsx('badge shrink-0 text-[11px]', clientStatusClass(latestClientTrainerRequest.status))}>
                  {clientStatusLabel(latestClientTrainerRequest.status)}
                </span>
              </div>
            </button>
          )}
          <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-bold text-slate-900">Client inbox status</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {gmailConnected
                      ? `Connected${gmailUserLabel}. Use Check Inbox Now to pull latest client requests.`
                      : 'Connect the client Gmail account before testing client request automation.'}
                  </p>
                </div>
                <span className={clsx(
                  'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-bold',
                  gmailConnected
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                    : 'border-red-200 bg-red-50 text-red-700'
                )}>
                  <span className={clsx('h-2 w-2 rounded-full', gmailConnected ? 'bg-emerald-500' : 'bg-red-500')} />
                  {gmailConnected ? 'Ready' : 'Action needed'}
                </span>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  ['Today', clientToday],
                  ['Pending', clientPending],
                  ['Auto Sent', clientAutoSent],
                  ['Requirements', clientRequirements],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg bg-white px-3 py-2">
                    <p className="text-xs font-semibold text-slate-400">{label}</p>
                    <p className="mt-1 text-xl font-bold text-slate-900">
                      {loading ? '-' : Number(value || 0).toLocaleString('en-IN')}
                    </p>
                  </div>
                ))}
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  onClick={syncClientInbox}
                  disabled={!gmailConnected || syncingInbox}
                  className="btn-primary text-sm disabled:opacity-50"
                >
                  {syncingInbox ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Check Inbox Now
                </button>
                <button onClick={() => navigate('/client-requests')} className="btn-secondary text-sm">
                  <BriefcaseBusiness className="h-4 w-4" /> Open Client Requests
                </button>
                <button onClick={() => navigate('/admin')} className="btn-secondary text-sm">
                  <Settings className="h-4 w-4" /> Gmail Settings
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <p className="text-sm font-bold text-slate-900">Latest requests</p>
                <button onClick={() => navigate('/client-requests')} className="text-xs font-bold text-brand-500 hover:text-brand-600">
                  View all
                </button>
              </div>
              {loading ? (
                <div className="space-y-2">
                  {[0, 1, 2].map(i => <div key={i} className="h-14 animate-pulse rounded-lg bg-slate-100" />)}
                </div>
              ) : recentClientEmails.length ? (
                <div className="space-y-2">
                  {recentClientEmails.slice(0, 4).map(item => {
                    return (
                      <button
                        key={item.email_id}
                        onClick={() => navigate('/client-requests')}
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-left shadow-sm transition hover:border-brand-200 hover:bg-brand-50"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <p className="truncate text-sm font-semibold text-slate-800">
                            {clientRequestTitle(item)}
                          </p>
                          <span className={clsx('badge text-[11px]', clientStatusClass(item.status))}>
                            {clientStatusLabel(item.status)}
                          </span>
                        </div>
                        <p className="mt-1 truncate text-xs text-slate-400">
                          {item.from_name || item.from_email || 'Client'} {item.received_at ? `- ${formatDateTime(item.received_at)}` : ''}
                        </p>
                        {clientRequestSummary(item) && (
                          <p className="mt-1 line-clamp-1 text-[11px] text-slate-400">
                            {clientRequestSummary(item)}
                          </p>
                        )}
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="rounded-lg bg-slate-50 px-3 py-6 text-center">
                  <MessageSquare className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                  <p className="text-sm font-medium text-slate-500">No client requests yet</p>
                  <p className="mt-1 text-xs text-slate-400">Connect Gmail and click Check Inbox Now.</p>
                </div>
              )}
            </div>
          </div>
        </Panel>

        <Panel title="Next Best Actions" eyebrow="Shortcuts">
          <div className="space-y-3">
            <p className="px-1 text-[11px] font-bold uppercase tracking-wide text-slate-400">Trainer Pipeline</p>
            <button onClick={() => navigate('/requirements')} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-brand-200 hover:bg-brand-50">
              <span className="flex items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-800">Find matching trainers</span>
                  <span className="text-xs text-slate-400">Open requirements and shortlist suitable profiles</span>
                </span>
                <ArrowUpRight className="h-4 w-4 text-brand-500" />
              </span>
            </button>
            <button onClick={() => navigate('/shortlist1')} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-brand-200 hover:bg-brand-50">
              <span className="flex items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-800">AI pipeline</span>
                  <span className="text-xs text-slate-400">Run AI trainer outreach and pipeline automation</span>
                </span>
                <ArrowUpRight className="h-4 w-4 text-brand-500" />
              </span>
            </button>
            <p className="px-1 pt-2 text-[11px] font-bold uppercase tracking-wide text-slate-400">Client Work</p>
            <button onClick={() => navigate('/client-requests')} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-brand-200 hover:bg-brand-50">
              <span className="flex items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-800">Review client updates</span>
                  <span className="text-xs text-slate-400">Check new requests, slot replies, and scheduling status</span>
                </span>
                <ArrowUpRight className="h-4 w-4 text-brand-500" />
              </span>
            </button>
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_380px]">
        <Panel title="Pipeline Pulse" eyebrow="Health metrics" badge="Current">
          <div className="grid gap-5 sm:grid-cols-2">
            <PulseMetric label="Reply rate" value={replyRate} sub="Replies against outreach" color="bg-emerald-500" />
            <PulseMetric label="Interest rate" value={interestRate} sub="Interested trainers in database" color="bg-brand-500" />
            <PulseMetric label="Delivery health" value={deliveryRate} sub="Sent versus failed emails" color="bg-sky-500" />
            <PulseMetric label="Review load" value={reviewLoad} sub="Pending review share" color="bg-amber-500" />
          </div>
        </Panel>
        <Panel title="Channel Health" eyebrow="Email + WhatsApp">
          <div className="space-y-4">
            <PulseMetric label="Email delivery" value={deliveryRate} sub={`${failedEmails.toLocaleString('en-IN')} failed emails`} color="bg-sky-500" />
            <PulseMetric
              label="WhatsApp health"
              value={whatsappSent + whatsappFailed ? (whatsappSent / (whatsappSent + whatsappFailed)) * 100 : 100}
              sub={`${whatsappReplies.toLocaleString('en-IN')} WhatsApp replies`}
              color="bg-emerald-500"
            />
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Email Activity" badge="Last 7 days" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={activityData}>
              <defs>
                <linearGradient id="emailGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2563eb" stopOpacity={0.18} />
                  <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="replyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.18} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="day" tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <Tooltip content={<TooltipBox />} />
              <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '12px' }} />
              <Area
                type="monotone"
                dataKey="emails"
                stroke="#2563eb"
                strokeWidth={3}
                fill="url(#emailGrad)"
                dot={{ r: 4, fill: '#2563eb' }}
                activeDot={{ r: 6 }}
                name="Emails Sent"
                isAnimationActive
                animationDuration={1000}
              />
              <Area
                type="monotone"
                dataKey="replies"
                stroke="#10b981"
                strokeWidth={3}
                fill="url(#replyGrad)"
                dot={{ r: 4, fill: '#10b981' }}
                activeDot={{ r: 6 }}
                name="Replies"
                isAnimationActive
                animationDuration={1200}
              />
            </AreaChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Trainer Status">
          {statusData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie
                    data={statusData}
                    cx="50%"
                    cy="50%"
                    innerRadius={58}
                    outerRadius={82}
                    dataKey="value"
                    paddingAngle={3}
                    isAnimationActive
                    animationDuration={900}
                  >
                    {statusData.map((entry, _i) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip content={<TooltipBox />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5">
                {statusData.map(d => (
                  <div key={d.name} className="flex items-center justify-between rounded-lg px-2 py-1 text-sm transition hover:bg-slate-50">
                    <span className="flex items-center gap-2 text-slate-600">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color }} />
                      {d.name}
                    </span>
                    <span className="font-bold text-slate-800">{d.value}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="flex h-60 flex-col items-center justify-center text-slate-400">
              <div className="relative mb-3 h-28 w-28">
                <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
                  <circle cx="50" cy="50" r="35" fill="none" stroke="#f1f5f9" strokeWidth="16" />
                  <circle cx="50" cy="50" r="35" fill="none" stroke="#cbd5e1" strokeWidth="16" strokeDasharray="54 180" strokeLinecap="round" />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <Star className="h-6 w-6 text-slate-300" />
                </div>
              </div>
              <p className="text-sm">No trainer status data yet</p>
            </div>
          )}
        </Panel>
      </div>

      {scoreDistData.length > 0 && (
        <Panel title="Match Score Distribution" badge="All shortlisted trainers">
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={scoreDistData}>
              <defs>
                <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2563eb" />
                  <stop offset="100%" stopColor="#93c5fd" />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="range" tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <Tooltip content={<TooltipBox />} />
              <Bar dataKey="count" name="Trainers" fill="url(#barGrad)" radius={[8, 8, 0, 0]} isAnimationActive animationDuration={900} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      )}

      {stats?.recent_emails?.length > 0 && (
        <Panel title="Recent Outreach" badge={`${stats.recent_emails.length} latest`}>
          <div className="space-y-2">
            {stats.recent_emails.map((email, i) => (
              <button
                key={`${email.email_id || email.to_email || i}-${i}`}
                onClick={() => navigate('/emails')}
                style={{ animationDelay: `${i * 45}ms` }}
                className="group/row flex w-full animate-fade-in-up items-center gap-4 rounded-xl border border-transparent px-3 py-2.5 text-left transition-all duration-200 hover:border-brand-100 hover:bg-brand-50"
              >
                <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-brand-50 transition-colors group-hover/row:bg-brand-100">
                  <Mail className="h-4 w-4 text-brand-500" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-800">{email.trainer_name}</p>
                  <p className="truncate text-xs text-slate-400">{email.to_email}</p>
                </div>
                <span className={clsx('badge text-xs',
                  email.status === 'sent' ? 'badge-blue' :
                  email.status === 'failed' ? 'badge-red' : 'badge-slate'
                )}>
                  {email.status}
                </span>
                {email.reply_received && <span className="badge-green text-xs">Replied</span>}
              </button>
            ))}
          </div>
        </Panel>
      )}

      {stats?.recent_whatsapp?.length > 0 && (
        <Panel title="Recent WhatsApp Messages" badge={`${stats.recent_whatsapp.length} latest`}>
          <div className="space-y-2">
            {stats.recent_whatsapp.map((msg, i) => {
              const ctx = msg.context || {}
              return (
                <div
                  key={`${msg.whatsapp_id || msg.twilio_sid || i}-${i}`}
                  style={{ animationDelay: `${i * 45}ms` }}
                  className="flex w-full animate-fade-in-up items-start gap-4 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5"
                >
                  <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-emerald-50">
                    <Send className="h-4 w-4 text-emerald-500" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-slate-800">
                      {ctx.trainer_name || msg.from_number || msg.to_number || 'WhatsApp message'}
                    </p>
                    <p className="truncate text-xs text-slate-400">{msg.event_type} · {ctx.mail_type || msg.direction || 'message'}</p>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
                      <span className="break-all"><strong className="font-semibold text-slate-600">To:</strong> {msg.to_number || 'Not saved'}</span>
                      {msg.from_number && <span className="break-all"><strong className="font-semibold text-slate-600">From:</strong> {msg.from_number}</span>}
                      {msg.provider && <span className="capitalize"><strong className="font-semibold text-slate-600">Provider:</strong> {msg.provider}</span>}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-slate-500">{msg.body}</p>
                    {msg.error_message && <p className="mt-1 text-xs font-semibold text-red-500">{msg.error_message}</p>}
                  </div>
                  <span className={clsx('badge text-xs',
                    ['queued', 'sent', 'delivered', 'read', 'received'].includes(msg.status) ? 'badge-green' :
                    ['failed', 'undelivered', 'skipped'].includes(msg.status) ? 'badge-red' : 'badge-slate'
                  )}>
                    {msg.status}
                  </span>
                </div>
              )
            })}
          </div>
        </Panel>
      )}
    </div>
  )
}
