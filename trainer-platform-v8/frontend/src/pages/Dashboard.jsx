import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { getDashboardStats, clearDatabase } from '../utils/api'
import {
  Users, Mail, TrendingUp, RefreshCw, BarChart2, Activity,
  Trash2, AlertTriangle, Star, ArrowUpRight, Database, Send,
  BriefcaseBusiness, Inbox, MessageSquare, Loader2, Settings,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Area, AreaChart, Legend,
} from 'recharts'
import toast from 'react-hot-toast'
import clsx from 'clsx'

/* ─── Helpers ──────────────────────────────────────────────── */
function AnimatedNumber({ value, duration = 1100 }) {
  const [display, setDisplay] = useState(0)
  const start = useRef(0)
  useEffect(() => {
    const numeric = Number(value || 0)
    if (numeric === 0) { setDisplay(0); start.current = 0; return }
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

function normaliseRate(v) { const n = Number(v || 0); return n > 0 && n <= 1 ? n * 100 : n }
function formatPercent(v) { const n = Math.max(0, Math.min(100, Number(v || 0))); return `${n.toFixed(n % 1 ? 1 : 0)}%` }
function formatDateTime(v) { if (!v) return ''; try { return new Date(v).toLocaleString() } catch { return String(v) } }

function clientStatusLabel(s = '') {
  return { pending_approval: 'Pending', auto_sent: 'Auto Sent', approved: 'Approved', rejected: 'Rejected', spam: 'Spam' }[s] || s || 'New'
}
function clientStatusClass(s = '') {
  if (s === 'pending_approval') return 'badge-amber'
  if (s === 'auto_sent') return 'badge-green'
  if (s === 'approved') return 'badge-blue'
  if (s === 'rejected' || s === 'spam') return 'badge-red'
  return 'badge-slate'
}
function clientRequestTitle(item = {}) {
  const e = item.extracted || {}
  const domain = e.technology_needed || e.domain || e.primary_skill || ''
  return domain ? `Client requesting ${domain} trainer` : item.subject || 'New client trainer request'
}
/* ─── Tooltip ──────────────────────────────────────────────── */
function TooltipBox({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-4 py-3 text-sm shadow-xl">
      <p className="mb-1 font-semibold text-slate-700">{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-medium">{p.name}: {p.value}</p>
      ))}
    </div>
  )
}

/* ─── Stat Card ────────────────────────────────────────────── */
const TONE_MAP = {
  blue:    { bg: 'bg-blue-50',    icon: 'text-blue-600',    border: 'border-blue-100' },
  purple:  { bg: 'bg-purple-50',  icon: 'text-purple-600',  border: 'border-purple-100' },
  emerald: { bg: 'bg-emerald-50', icon: 'text-emerald-600', border: 'border-emerald-100' },
  green:   { bg: 'bg-green-50',   icon: 'text-green-600',   border: 'border-green-100' },
  orange:  { bg: 'bg-orange-50',  icon: 'text-orange-500',  border: 'border-orange-100' },
  sky:     { bg: 'bg-sky-50',     icon: 'text-sky-600',     border: 'border-sky-100' },
  amber:   { bg: 'bg-amber-50',   icon: 'text-amber-600',   border: 'border-amber-100' },
  red:     { bg: 'bg-red-50',     icon: 'text-red-500',     border: 'border-red-100' },
}

function StatCard({ icon: Icon, label, value, sub, tone = 'blue', loading, linkTo, delay = 0 }) {
  const navigate = useNavigate()
  const t = TONE_MAP[tone] || TONE_MAP.blue
  return (
    <button
      type="button"
      onClick={() => linkTo && navigate(linkTo)}
      style={{ animationDelay: `${delay}ms` }}
      className={clsx(
        'stat-card group text-left animate-slide-up',
        linkTo ? 'cursor-pointer' : 'cursor-default'
      )}
    >
      <div className={clsx('stat-icon border', t.bg, t.border)}>
        <Icon className={clsx('h-5 w-5', t.icon)} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1">{label}</p>
        {loading
          ? <div className="skeleton h-8 w-20 mb-1" />
          : <p className="text-3xl font-extrabold text-slate-900 tracking-tight" style={{ fontFamily: "'Plus Jakarta Sans',sans-serif" }}>
              <AnimatedNumber value={value} />
            </p>
        }
        {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
        {linkTo && (
          <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity">
            View details <ArrowUpRight className="h-3 w-3" />
          </p>
        )}
      </div>
    </button>
  )
}

/* ─── Progress metric ──────────────────────────────────────── */
function PulseMetric({ label, value, sub, color = 'bg-blue-500' }) {
  const safe = Math.max(0, Math.min(100, Number(value || 0)))
  return (
    <div>
      <div className="flex items-end justify-between gap-3 mb-2">
        <div>
          <p className="text-sm font-semibold text-slate-800">{label}</p>
          {sub && <p className="text-xs text-slate-400">{sub}</p>}
        </div>
        <span className="text-lg font-bold text-slate-900" style={{ fontFamily: "'Plus Jakarta Sans',sans-serif" }}>
          {formatPercent(safe)}
        </span>
      </div>
      <div className="progress-bar">
        <div className={clsx('progress-fill', color)} style={{ width: `${safe}%`, background: undefined }} />
      </div>
    </div>
  )
}

/* ─── Panel ────────────────────────────────────────────────── */
function Panel({ title, eyebrow, badge, children, className }) {
  return (
    <section className={clsx('panel animate-fade-in', className)}>
      <div className="panel-header">
        <div>
          {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
          <h2 className="section-title">{title}</h2>
        </div>
        {badge && <span className="badge-slate">{badge}</span>}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  )
}


/* ─── Main Dashboard ───────────────────────────────────────── */
export default function Dashboard() {
  const [stats, setStats]           = useState(null)
  const [clientInbox, setClientInbox] = useState({ emails: [], stats: {}, whatsapp_logs: [] })
  const [gmailStatus, setGmailStatus] = useState(null)
  const [loading, setLoading]       = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [syncingInbox, setSyncingInbox] = useState(false)
  const [showClear, setShowClear]   = useState(false)
  const [clearing, setClearing]     = useState(false)
  const navigate = useNavigate()

  const load = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true); else setLoading(true)
    try {
      const [statsRes, inboxRes, gmailRes] = await Promise.allSettled([
        getDashboardStats(),
        api.get('/inbox', { params: { limit: 5 } }),
        api.get('/gmail/auth-status'),
      ])
      if (statsRes.status === 'fulfilled') setStats(statsRes.value.data)
      else toast.error(statsRes.reason?.message || 'Could not load stats')
      setClientInbox(inboxRes.status === 'fulfilled' ? inboxRes.value.data || { emails: [], stats: {}, whatsapp_logs: [] } : { emails: [], stats: {}, whatsapp_logs: [] })
      setGmailStatus(gmailRes.status === 'fulfilled' ? gmailRes.value.data : { connected: false })
    } finally { setLoading(false); setRefreshing(false) }
  }
  useEffect(() => { load() }, [])

  const handleClear = async () => {
    setClearing(true)
    try { await clearDatabase(); toast.success('Database cleared'); setShowClear(false); load() }
    catch (e) { toast.error(e.message) }
    finally { setClearing(false) }
  }

  const syncClientInbox = async () => {
    if (syncingInbox) return
    setSyncingInbox(true)
    try {
      const res = await api.post('/gmail/sync-now?limit=50')
      const processed = Number(res.data?.processed_count || 0)
      const skipped   = Number(res.data?.skipped || 0)
      toast.success(`Inbox checked: ${processed} processed, ${skipped} skipped`)
      await load(true)
    } catch (e) { toast.error(e.message || 'Inbox sync failed') }
    finally { setSyncingInbox(false) }
  }

  // ── Derived values ──────────────────────────────────────────
  const totalEmails    = Number(stats?.total_emails_sent || 0)
  const failedEmails   = Number(stats?.total_emails_failed || 0)
  const totalReplies   = Number(stats?.total_replies || 0)
  const totalTrainers  = Number(stats?.total_trainers || 0)
  const pendingReview  = Number(stats?.pending_review || 0)
  const interested     = Number(stats?.interested_count || 0)
  const whatsapp       = stats?.whatsapp || {}
  const whatsappSent   = Number(whatsapp.sent || 0)
  const whatsappFailed = Number(whatsapp.failed || 0)
  const whatsappReplies = Number(whatsapp.replies || 0)
  const clientStats    = clientInbox?.stats || {}
  const recentClientEmails    = clientInbox?.emails || []
  const latestClientTrainerRequest = recentClientEmails.find(item =>
    item?.status !== 'spam' && (item?.extracted?.is_training_request || item?.requirement_id)
  )
  const clientToday    = Number(clientStats.today || 0)
  const clientPending  = Number(clientStats.pending_approval || 0)
  const gmailConnected = !!gmailStatus?.connected
  const gmailUser      = gmailStatus?.gmail_user || gmailStatus?.configured_user || ''
  const replyRate      = normaliseRate(stats?.reply_rate || (totalEmails ? (totalReplies / totalEmails) * 100 : 0))
  const interestRate   = normaliseRate(stats?.interest_rate || (totalTrainers ? (interested / totalTrainers) * 100 : 0))
  const deliveryRate   = totalEmails + failedEmails ? (totalEmails / (totalEmails + failedEmails)) * 100 : 100
  const reviewLoad     = totalTrainers ? (pendingReview / totalTrainers) * 100 : 0

  const statusData = stats ? [
    { name: 'Interested', value: stats.interested_count, color: '#10b981' },
    { name: 'Contacted',  value: stats.contacted_count,  color: '#2563eb' },
    { name: 'Confirmed',  value: stats.confirmed_count,  color: '#8b5cf6' },
    { name: 'Pending',    value: stats.pending_review,   color: '#f59e0b' },
    { name: 'Declined',   value: stats.declined_count,   color: '#ef4444' },
  ].filter(d => Number(d.value || 0) > 0) : []

  const scoreDistData = (stats?.score_distribution || []).map(b => ({
    range: b._id === 'Other' ? 'Other' : `${b._id}-${Number(b._id) + 19}`,
    count: b.count,
  }))

  const activityData = [
    { day: 'Mon', emails: 12, replies: 4 },
    { day: 'Tue', emails: 8,  replies: 3 },
    { day: 'Wed', emails: 15, replies: 7 },
    { day: 'Thu', emails: 10, replies: 5 },
    { day: 'Fri', emails: 18, replies: 9 },
    { day: 'Sat', emails: 6,  replies: 2 },
    { day: 'Sun', emails: 3,  replies: 1 },
  ]

  const statCards = [
    { icon: BriefcaseBusiness, label: 'Client Requests', value: clientToday, sub: 'Received today',   tone: 'blue',   linkTo: '/client-requests' },
    { icon: Inbox,             label: 'Client Pending',  value: clientPending, sub: 'Needs approval', tone: 'amber',  linkTo: '/client-requests' },
    { icon: Users,             label: 'Total Trainers',  value: stats?.total_trainers ?? 0, sub: 'In database', tone: 'blue', linkTo: '/trainers' },
    { icon: Mail,              label: 'Emails Sent',     value: stats?.total_emails_sent ?? 0, sub: 'Outreach emails', tone: 'purple', linkTo: '/emails' },
    { icon: TrendingUp,        label: 'Replies',         value: stats?.total_replies ?? 0, sub: 'Trainer replies', tone: 'emerald', linkTo: '/emails' },
    { icon: BarChart2,         label: 'Requirements',    value: stats?.total_requirements ?? 0, sub: 'Active searches', tone: 'orange', linkTo: '/requirements' },
    { icon: Activity,          label: 'Confirmed',       value: stats?.confirmed_count ?? 0, sub: 'Ready to close', tone: 'sky', linkTo: '/shortlist1' },
    { icon: Send,              label: 'WhatsApp Sent',   value: whatsappSent, sub: 'Queued/sent/delivered', tone: 'green' },
  ]


  return (
    <div className="space-y-6 animate-fade-in">

      {/* ── Hero strip ─────────────────────────────────────── */}
      <div className="panel overflow-hidden">
        <div className="p-5 border-b border-slate-100" style={{ background: 'linear-gradient(135deg,#f0f7ff 0%,#ffffff 60%)' }}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="status-dot green animate-pulse-soft" />
                <span className="text-xs font-semibold text-emerald-700">Live operational overview</span>
              </div>
              <h1 className="page-title">Dashboard</h1>
              <p className="page-sub max-w-xl">Track trainer inventory, outreach movement, reply quality, and work that needs recruiter attention.</p>
              <div className="flex flex-wrap gap-2 mt-3">
                {['Trainer intelligence','Client inbox','Mail automation','PO to invoice'].map(item => (
                  <span key={item} className="chip chip-blue text-xs">{item}</span>
                ))}
              </div>
            </div>

            {/* Ops signals */}
            <div className="flex flex-col gap-2 min-w-[200px]">
              {[
                ['AI matching', 'Live', 'badge-blue'],
                ['Mail automation', gmailConnected ? 'Ready' : 'Setup needed', gmailConnected ? 'badge-green' : 'badge-amber'],
                ['Pipeline sync', refreshing ? 'Refreshing…' : 'Normal', refreshing ? 'badge-blue' : 'badge-slate'],
              ].map(([label, val, cls]) => (
                <div key={label} className={clsx('rounded-lg border px-3 py-2 flex items-center justify-between gap-4', cls.replace('badge-','border-').replace('blue','blue-100').replace('green','green-100').replace('amber','amber-100').replace('slate','slate-200'))}>
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{label}</span>
                  <span className={clsx('badge text-[11px]', cls)}>{val}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Action bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 bg-slate-50 border-t border-slate-100">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Database className="h-4 w-4 text-slate-400" />
            {loading ? 'Loading…' : `${totalTrainers.toLocaleString('en-IN')} trainer profiles synced`}
          </div>
          <div className="flex gap-2">
            <button onClick={() => setShowClear(true)} className="btn-secondary text-sm text-red-500 border-red-100 hover:border-red-200">
              <Trash2 className="h-4 w-4" /> Clear DB
            </button>
            <button onClick={() => load(true)} disabled={refreshing} className="btn-secondary text-sm">
              <RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} /> Refresh
            </button>
          </div>
        </div>
      </div>

      {/* ── Clear DB warning ───────────────────────────────── */}
      {showClear && (
        <div className="panel border-red-200 bg-red-50 animate-slide-up">
          <div className="panel-body flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-red-500 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="font-semibold text-red-800">Clear entire database?</p>
              <p className="text-sm text-red-600 mt-1">This will permanently delete all trainers, requirements, shortlists and email logs.</p>
              <div className="flex gap-3 mt-3">
                <button onClick={handleClear} disabled={clearing} className="btn-danger text-sm">
                  {clearing ? <><RefreshCw className="h-4 w-4 animate-spin" />Clearing…</> : 'Yes, clear all'}
                </button>
                <button onClick={() => setShowClear(false)} className="btn-secondary text-sm">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Stat cards ─────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {statCards.map((card, i) => (
          <StatCard key={card.label} {...card} loading={loading} delay={i * 50} />
        ))}
      </div>

      {/* ── Client flow + shortcuts ─────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_340px]">
        <Panel title="Client Request Flow" eyebrow="Client automation"
          badge={gmailConnected ? 'Gmail connected' : 'Gmail not connected'}>

          {latestClientTrainerRequest && (
            <button type="button" onClick={() => navigate('/client-requests')}
              className="mb-4 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-left transition hover:border-blue-200 hover:bg-blue-50">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="eyebrow mb-1">New client notification</p>
                  <p className="font-bold text-slate-900 truncate">{clientRequestTitle(latestClientTrainerRequest)}</p>
                  <p className="text-xs text-slate-400 mt-1 line-clamp-1">
                    From {latestClientTrainerRequest.from_name || latestClientTrainerRequest.from_email || 'Client'}
                    {latestClientTrainerRequest.received_at ? ` · ${formatDateTime(latestClientTrainerRequest.received_at)}` : ''}
                  </p>
                </div>
                <span className={clsx('badge text-[11px]', clientStatusClass(latestClientTrainerRequest.status))}>
                  {clientStatusLabel(latestClientTrainerRequest.status)}
                </span>
              </div>
            </button>
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-4 mb-4">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
              <div>
                <p className="font-semibold text-slate-900 text-sm">Client inbox status</p>
                <p className="text-xs text-slate-500 mt-1">
                  {gmailConnected ? `Connected${gmailUser ? ` as ${gmailUser}` : ''}. Click Check Inbox Now to pull latest requests.` : 'Connect the client Gmail account first.'}
                </p>
              </div>
              <span className={clsx('badge', gmailConnected ? 'badge-green' : 'badge-red')}>
                <span className={clsx('status-dot', gmailConnected ? 'green' : 'red')} />
                {gmailConnected ? 'Ready' : 'Action needed'}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={syncClientInbox} disabled={!gmailConnected || syncingInbox} className="btn-primary text-sm disabled:opacity-50">
                {syncingInbox ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Check Inbox Now
              </button>
              <button onClick={() => navigate('/client-requests')} className="btn-secondary text-sm">
                <BriefcaseBusiness className="h-4 w-4" /> Client Requests
              </button>
              <button onClick={() => navigate('/admin')} className="btn-secondary text-sm">
                <Settings className="h-4 w-4" /> Gmail Settings
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="font-semibold text-slate-900 text-sm">Latest requests</p>
              <button onClick={() => navigate('/client-requests')} className="text-xs font-bold text-blue-600 hover:text-blue-800">View all</button>
            </div>
            {loading ? (
              <div className="space-y-2">{[0,1,2].map(i => <div key={i} className="skeleton h-14 w-full" />)}</div>
            ) : recentClientEmails.length ? (
              <div className="space-y-2">
                {recentClientEmails.slice(0, 4).map(item => (
                  <button key={item.email_id} onClick={() => navigate('/client-requests')}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left transition hover:border-blue-200 hover:bg-blue-50">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-semibold text-slate-800">{clientRequestTitle(item)}</p>
                      <span className={clsx('badge text-[11px]', clientStatusClass(item.status))}>{clientStatusLabel(item.status)}</span>
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-400">
                      {item.from_name || item.from_email || 'Client'}
                      {item.received_at ? ` · ${formatDateTime(item.received_at)}` : ''}
                    </p>
                  </button>
                ))}
              </div>
            ) : (
              <div className="empty-state py-8">
                <div className="empty-state-icon"><MessageSquare className="h-5 w-5" /></div>
                <p className="text-sm font-medium text-slate-500">No client requests yet</p>
                <p className="text-xs text-slate-400">Connect Gmail and click Check Inbox Now.</p>
              </div>
            )}
          </div>
        </Panel>

        {/* Quick actions */}
        <Panel title="Next Best Actions" eyebrow="Shortcuts">
          <div className="space-y-3">
            <p className="eyebrow">Trainer Pipeline</p>
            {[
              { label: 'Find matching trainers', sub: 'Open requirements and shortlist suitable profiles', to: '/requirements' },
              { label: 'AI pipeline', sub: 'Run AI trainer outreach and pipeline automation', to: '/shortlist1' },
            ].map(a => (
              <button key={a.to} onClick={() => navigate(a.to)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-blue-200 hover:bg-blue-50">
                <span className="flex items-center justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-slate-800">{a.label}</span>
                    <span className="text-xs text-slate-400">{a.sub}</span>
                  </span>
                  <ArrowUpRight className="h-4 w-4 text-blue-500 flex-shrink-0" />
                </span>
              </button>
            ))}
            <p className="eyebrow pt-2">Client Work</p>
            <button onClick={() => navigate('/client-requests')}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-blue-200 hover:bg-blue-50">
              <span className="flex items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-800">Review client updates</span>
                  <span className="text-xs text-slate-400">Check new requests, slot replies, scheduling status</span>
                </span>
                <ArrowUpRight className="h-4 w-4 text-blue-500 flex-shrink-0" />
              </span>
            </button>
          </div>
        </Panel>
      </div>

      {/* ── Metrics row ────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Pipeline Pulse" eyebrow="Health metrics" badge="Current">
          <div className="grid gap-5 sm:grid-cols-2">
            <PulseMetric label="Reply rate" value={replyRate} sub="Replies against outreach" />
            <PulseMetric label="Interest rate" value={interestRate} sub="Interested trainers" color="bg-purple-500" />
            <PulseMetric label="Delivery health" value={deliveryRate} sub={`${failedEmails} failed emails`} color="bg-sky-500" />
            <PulseMetric label="Review load" value={reviewLoad} sub="Pending review share" color="bg-amber-500" />
          </div>
        </Panel>
        <Panel title="Channel Health" eyebrow="Email + WhatsApp">
          <div className="space-y-5">
            <PulseMetric label="Email delivery" value={deliveryRate} sub={`${failedEmails.toLocaleString('en-IN')} failed emails`} />
            <PulseMetric label="WhatsApp health"
              value={whatsappSent + whatsappFailed ? (whatsappSent / (whatsappSent + whatsappFailed)) * 100 : 100}
              sub={`${whatsappReplies} WhatsApp replies`} color="bg-emerald-500" />
          </div>
        </Panel>
      </div>

      {/* ── Charts row ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Email Activity" badge="Last 7 days" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={activityData}>
              <defs>
                <linearGradient id="emailGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2563eb" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="replyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="day" tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <Tooltip content={<TooltipBox />} />
              <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '12px' }} />
              <Area type="monotone" dataKey="emails" stroke="#2563eb" strokeWidth={2.5} fill="url(#emailGrad)" dot={{ r: 3, fill: '#2563eb' }} name="Emails Sent" />
              <Area type="monotone" dataKey="replies" stroke="#10b981" strokeWidth={2.5} fill="url(#replyGrad)" dot={{ r: 3, fill: '#10b981' }} name="Replies" />
            </AreaChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Trainer Status">
          {statusData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={statusData} cx="50%" cy="50%" innerRadius={55} outerRadius={78} dataKey="value" paddingAngle={3}>
                    {statusData.map(entry => <Cell key={entry.name} fill={entry.color} />)}
                  </Pie>
                  <Tooltip content={<TooltipBox />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5 mt-2">
                {statusData.map(d => (
                  <div key={d.name} className="flex items-center justify-between rounded-lg px-2 py-1 text-sm hover:bg-slate-50 transition">
                    <span className="flex items-center gap-2 text-slate-600">
                      <span className="h-2.5 w-2.5 rounded-full flex-shrink-0" style={{ background: d.color }} />
                      {d.name}
                    </span>
                    <span className="font-bold text-slate-800">{d.value}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state h-60">
              <div className="empty-state-icon"><Star className="h-5 w-5" /></div>
              <p className="text-sm text-slate-500">No status data yet</p>
            </div>
          )}
        </Panel>
      </div>

      {/* ── Score distribution ──────────────────────────────── */}
      {scoreDistData.length > 0 && (
        <Panel title="Match Score Distribution" badge="All shortlisted trainers">
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={scoreDistData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="range" tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <Tooltip content={<TooltipBox />} />
              <Bar dataKey="count" name="Trainers" fill="#2563eb" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      )}

      {/* ── Recent outreach ─────────────────────────────────── */}
      {stats?.recent_emails?.length > 0 && (
        <Panel title="Recent Outreach" badge={`${stats.recent_emails.length} latest`}>
          <div className="space-y-1">
            {stats.recent_emails.map((email, i) => (
              <button key={`${email.email_id || i}`} onClick={() => navigate('/emails')}
                className="group/row flex w-full items-center gap-4 rounded-xl px-3 py-2.5 text-left transition hover:bg-blue-50">
                <div className="avatar avatar-sm bg-blue-50 text-blue-600 flex-shrink-0">
                  <Mail className="h-3.5 w-3.5" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-800">{email.trainer_name}</p>
                  <p className="truncate text-xs text-slate-400">{email.to_email}</p>
                </div>
                <span className={clsx('badge text-[11px]', email.status === 'sent' ? 'badge-blue' : email.status === 'failed' ? 'badge-red' : 'badge-slate')}>
                  {email.status}
                </span>
                {email.reply_received && <span className="badge-green text-[11px]">Replied</span>}
              </button>
            ))}
          </div>
        </Panel>
      )}

      {/* ── Recent WhatsApp ─────────────────────────────────── */}
      {stats?.recent_whatsapp?.length > 0 && (
        <Panel title="Recent WhatsApp Messages" badge={`${stats.recent_whatsapp.length} latest`}>
          <div className="space-y-2">
            {stats.recent_whatsapp.map((msg, i) => {
              const ctx = msg.context || {}
              return (
                <div key={`${msg.whatsapp_id || i}`} className="flex items-start gap-4 rounded-xl border border-slate-100 bg-slate-50 px-3 py-3">
                  <div className="avatar avatar-sm bg-emerald-50 text-emerald-600 flex-shrink-0">
                    <Send className="h-3.5 w-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-slate-800">{ctx.trainer_name || msg.to_number || 'WhatsApp'}</p>
                    <p className="truncate text-xs text-slate-400">{msg.event_type} · {ctx.mail_type || msg.direction || 'message'}</p>
                    {msg.body && <p className="mt-1 line-clamp-1 text-xs text-slate-500">{msg.body}</p>}
                    {msg.error_message && <p className="mt-1 text-xs font-semibold text-red-500">{msg.error_message}</p>}
                  </div>
                  <span className={clsx('badge text-[11px]',
                    ['queued','sent','delivered','read','received'].includes(msg.status) ? 'badge-green' :
                    ['failed','undelivered','skipped'].includes(msg.status) ? 'badge-red' : 'badge-slate'
                  )}>{msg.status}</span>
                </div>
              )
            })}
          </div>
        </Panel>
      )}
    </div>
  )
}
