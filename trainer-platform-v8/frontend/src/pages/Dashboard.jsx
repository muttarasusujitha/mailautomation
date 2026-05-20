import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { getDashboardStats, clearDatabase } from '../utils/api'
import {
  Users, Mail, TrendingUp, CheckCircle, XCircle, Clock,
  RefreshCw, BarChart2, Activity, Trash2, AlertTriangle, Star, Zap,
  ArrowUpRight, Database, Send, FileSearch, UploadCloud, ShieldCheck,
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

function QuickAction({ icon: Icon, label, to, tone = 'brand' }) {
  const navigate = useNavigate()
  const tones = {
    brand: 'border-brand-100 bg-brand-50 text-brand-700 hover:bg-brand-100/70 hover:border-brand-200',
    emerald: 'border-emerald-100 bg-emerald-50 text-emerald-700 hover:bg-emerald-100/70 hover:border-emerald-200',
    amber: 'border-amber-100 bg-amber-50 text-amber-700 hover:bg-amber-100/70 hover:border-amber-200',
    slate: 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100 hover:border-slate-300',
  }

  return (
    <button
      onClick={() => navigate(to)}
      className={clsx(
        'group flex min-h-[46px] items-center justify-between gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm',
        tones[tone]
      )}
    >
      <span className="flex items-center gap-2 text-sm font-semibold">
        <Icon className="h-4 w-4" /> {label}
      </span>
      <ArrowUpRight className="h-4 w-4 opacity-45 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:opacity-100" />
    </button>
  )
}

function Panel({ title, eyebrow, badge, children, className }) {
  return (
    <section className={clsx('card p-5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-card-lg', className)}>
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
      <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
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
        'group card relative flex min-h-[132px] items-start gap-4 overflow-hidden p-5 text-left transition-all duration-300 animate-fade-in-up',
        'hover:-translate-y-1 hover:border-brand-200 hover:shadow-card-lg focus:outline-none focus:ring-2 focus:ring-brand-500/20',
        linkTo ? 'cursor-pointer' : 'cursor-default'
      )}
    >
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-500 via-emerald-400 to-amber-400 opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
      <div className="absolute right-3 top-3 flex gap-0.5 opacity-0 transition-opacity duration-300 group-hover:opacity-100">
        {[0, 1, 2].map(i => (
          <span key={i} className="h-1 w-1 rounded-full bg-brand-400 animate-pulse" style={{ animationDelay: `${i * 130}ms` }} />
        ))}
      </div>
      <div className={clsx('stat-icon border transition-transform duration-300 group-hover:scale-110', tones[tone])}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
        {loading ? (
          <div className="h-8 w-20 animate-pulse rounded-lg bg-slate-100" />
        ) : (
          <p className="font-display text-2xl font-bold text-slate-900">
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
      toast.success(`Client inbox checked: ${processed} processed, ${skipped} skipped`)
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
  const clientToday = Number(clientStats.today || 0)
  const clientPending = Number(clientStats.pending_approval || 0)
  const clientAutoSent = Number(clientStats.auto_sent || 0)
  const clientRequirements = Number(clientStats.requirements_created || 0)
  const gmailConnected = !!gmailStatus?.connected
  const gmailUser = gmailStatus?.gmail_user || gmailStatus?.configured_user || ''
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
    { icon: ShieldCheck, label: 'Client Auto Sent', value: clientAutoSent, sub: 'Replies sent by AI rules', tone: 'emerald', linkTo: '/client-requests' },
    { icon: CheckCircle, label: 'Client Requirements', value: clientRequirements, sub: 'Created from inbox', tone: 'green', linkTo: '/client-requests' },
    { icon: Users, label: 'Total Trainers', value: stats?.total_trainers ?? 0, sub: 'In database', tone: 'blue', linkTo: '/trainers' },
    { icon: Mail, label: 'Emails Sent', value: stats?.total_emails_sent ?? 0, sub: 'Outreach emails', tone: 'purple', linkTo: '/emails' },
    { icon: TrendingUp, label: 'Replies', value: stats?.total_replies ?? 0, sub: 'Trainer replies', tone: 'emerald', linkTo: '/emails' },
    { icon: CheckCircle, label: 'Interested', value: stats?.interested_count ?? 0, sub: 'Trainer interest', tone: 'green', linkTo: '/emails' },
    { icon: BarChart2, label: 'Requirements', value: stats?.total_requirements ?? 0, sub: 'Active searches', tone: 'orange', linkTo: '/requirements' },
    { icon: Activity, label: 'Confirmed', value: stats?.confirmed_count ?? 0, sub: 'Ready to close', tone: 'sky', linkTo: '/shortlist' },
    { icon: Clock, label: 'Pending Review', value: stats?.pending_review ?? 0, sub: 'Needs attention', tone: 'amber', linkTo: '/trainers' },
    { icon: XCircle, label: 'Emails Failed', value: stats?.total_emails_failed ?? 0, sub: 'Need retry', tone: 'red', linkTo: '/emails' },
    { icon: Send, label: 'WhatsApp Sent', value: whatsappSent, sub: 'Queued/sent/delivered', tone: 'green' },
    { icon: TrendingUp, label: 'WhatsApp Replies', value: whatsappReplies, sub: 'Inbound messages', tone: 'emerald' },
    { icon: XCircle, label: 'WhatsApp Failed', value: whatsappFailed, sub: 'Failed/skipped', tone: 'red' },
  ]

  return (
    <div className="space-y-5 animate-fade-in">
      <section className="card overflow-hidden">
        <div className="grid gap-5 p-5 lg:grid-cols-[1fr_360px] lg:items-center">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              Live operational overview
            </div>
            <h1 className="page-title flex items-center gap-2">
              <Zap className="h-6 w-6 text-brand-500" /> Dashboard
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
              Track trainer inventory, outreach movement, reply quality, and work that needs recruiter attention.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <QuickAction icon={BarChart2} label="Admin Dashboard" to="/admin-dashboard" tone="brand" />
            <QuickAction icon={MessageSquare} label="Feedback" to="/feedback" tone="emerald" />
            <QuickAction icon={Mail} label="Contact" to="/contact" tone="amber" />
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/70 px-5 py-3">
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
          <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-bold text-slate-900">Client inbox status</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {gmailConnected
                      ? `Connected${gmailUser ? ` as ${gmailUser}` : ''}. Use Check Inbox Now to pull latest client requests.`
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
                    const extracted = item.extracted || {}
                    return (
                      <button
                        key={item.email_id}
                        onClick={() => navigate('/client-requests')}
                        className="w-full rounded-lg border border-slate-100 px-3 py-2 text-left transition hover:border-brand-100 hover:bg-brand-50"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <p className="truncate text-sm font-semibold text-slate-800">
                            {extracted.technology_needed || item.subject || 'Client request'}
                          </p>
                          <span className={clsx('badge text-[11px]', clientStatusClass(item.status))}>
                            {clientStatusLabel(item.status)}
                          </span>
                        </div>
                        <p className="mt-1 truncate text-xs text-slate-400">
                          {item.from_name || item.from_email || 'Client'} {item.received_at ? `- ${formatDateTime(item.received_at)}` : ''}
                        </p>
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
            <button onClick={() => navigate('/admin-dashboard')} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-brand-200 hover:bg-brand-50">
              <span className="flex items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-800">Admin Dashboard</span>
                  <span className="text-xs text-slate-400">Open analytics and admin insights</span>
                </span>
                <ArrowUpRight className="h-4 w-4 text-brand-500" />
              </span>
            </button>
            <button onClick={() => navigate('/feedback')} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-brand-200 hover:bg-brand-50">
              <span className="flex items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-800">Feedback</span>
                  <span className="text-xs text-slate-400">View recruiter reviews and feedback</span>
                </span>
                <ArrowUpRight className="h-4 w-4 text-brand-500" />
              </span>
            </button>
            <button onClick={() => navigate('/contact')} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-brand-200 hover:bg-brand-50">
              <span className="flex items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-800">Contact</span>
                  <span className="text-xs text-slate-400">Open support and contact details</span>
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
                    {statusData.map((entry, i) => (
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
