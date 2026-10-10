import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { getDashboardStats, getDashboardAnalytics, clearDatabase } from '../utils/api'
import {
  Users, Mail, TrendingUp, RefreshCw, BarChart2, Activity,
  Trash2, AlertTriangle, Star, ArrowUpRight, Database, Send,
  BriefcaseBusiness, Inbox, MessageSquare, Loader2, Settings, Sparkles, Search,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Area, AreaChart, Legend,
} from 'recharts'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { normalizeGmailStatus } from '../utils/gmailOAuth'

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
function formatPercent(v) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  const n = Math.max(0, Math.min(100, Number(v)))
  return `${n.toFixed(n % 1 ? 1 : 0)}%`
}
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
      {/* BUG-011: use stable key from data (name+color) instead of array index */}
      {payload.map((p) => (
        <p key={`${p.name}-${p.color}`} style={{ color: p.color }} className="font-medium">{p.name}: {p.value}</p>
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
      <div className="min-w-0 flex-1">
        <div className="mb-3 flex items-start justify-between gap-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
          <div className={clsx('stat-icon border', t.bg, t.border)}>
            <Icon className={clsx('h-5 w-5', t.icon)} />
          </div>
        </div>
        {loading
          ? <div className="skeleton h-9 w-24 mb-1" />
          : <p className="text-3xl font-extrabold text-slate-900 tracking-tight" style={{ fontFamily: "'Plus Jakarta Sans',sans-serif" }}>
              <AnimatedNumber value={value} />
            </p>
        }
        {sub && <p className="mt-2 min-h-[18px] truncate text-xs font-medium text-slate-500">{sub}</p>}
        {linkTo && (
          <p className="mt-3 flex items-center gap-1 text-xs font-semibold text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity">
            View details <ArrowUpRight className="h-3 w-3" />
          </p>
        )}
      </div>
    </button>
  )
}

/* ─── Progress metric ──────────────────────────────────────── */
function PulseMetric({ label, value, sub, color = 'bg-blue-500' }) {
  const hasValue = value != null && Number.isFinite(Number(value))
  const safe = hasValue ? Math.max(0, Math.min(100, Number(value))) : 0
  return (
    <div>
      <div className="flex items-end justify-between gap-3 mb-2">
        <div>
          <p className="text-sm font-semibold text-slate-800">{label}</p>
          {sub && <p className="text-xs text-slate-400">{sub}</p>}
        </div>
        <span className="text-lg font-bold text-slate-900" style={{ fontFamily: "'Plus Jakarta Sans',sans-serif" }}>
          {hasValue ? formatPercent(safe) : 'No data'}
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
  const [dashboardAnalytics, setDashboardAnalytics] = useState(null)
  const [statsUnavailable, setStatsUnavailable] = useState(false)
  const [clientInbox, setClientInbox] = useState({ emails: [], stats: {}, whatsapp_logs: [] })
  const [gmailStatus, setGmailStatus] = useState(null)
  const [loading, setLoading]       = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [syncingInbox, setSyncingInbox] = useState(false)
  const [generationMode, setGenerationMode] = useState('template')
  const [savingGenerationMode, setSavingGenerationMode] = useState(false)
  const [showClear, setShowClear]   = useState(false)
  const [clearing, setClearing]     = useState(false)
  const [fetchingLinkedIn, setFetchingLinkedIn] = useState(false)
  const [linkedinMessage, setLinkedinMessage] = useState('')
  const navigate = useNavigate()

  const load = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true); else setLoading(true)
    try {
      // BUG-009: Promise.allSettled already handles rejections per-request;
      // each settled result is checked individually so no rejection goes unhandled.
      const [statsRes, inboxRes, gmailRes, analyticsRes, generationModeRes] = await Promise.allSettled([
        getDashboardStats(),
        api.get('/inbox', { params: { limit: 5, include_stats: false, include_total: false } }),
        api.get('/gmail/auth-status'),
        getDashboardAnalytics({ preset: 'week' }),
        api.get('/requirements/generation-mode'),
      ])
      if (statsRes.status === 'fulfilled') {
        setStats(statsRes.value.data)
        setStatsUnavailable(false)
      } else {
        setStatsUnavailable(true)
        toast.error(statsRes.reason?.message || 'Could not load stats')
      }
      setClientInbox(
        inboxRes.status === 'fulfilled'
          ? inboxRes.value.data || { emails: [], stats: {}, whatsapp_logs: [] }
          : { emails: [], stats: {}, whatsapp_logs: [] }
      )
      if (inboxRes.status === 'rejected') {
        toast.error(inboxRes.reason?.message || 'Could not load inbox')
      }
      setGmailStatus(
        gmailRes.status === 'fulfilled' ? normalizeGmailStatus(gmailRes.value.data) : normalizeGmailStatus({ connected: false })
      )
      setDashboardAnalytics(analyticsRes.status === 'fulfilled' ? analyticsRes.value.data : null)
      if (generationModeRes.status === 'fulfilled') {
        setGenerationMode(generationModeRes.value.data?.generation_mode === 'ai' ? 'ai' : 'template')
      }
    } catch (err) {
      toast.error(err?.message || 'Failed to load dashboard data')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  // BUG-008: empty dependency array [] is intentional — load once on mount only
  useEffect(() => { load() }, [])

  const updateGenerationMode = async mode => {
    if (savingGenerationMode) return
    setSavingGenerationMode(true)
    try {
      const res = await api.put('/requirements/generation-mode', { generation_mode: mode })
      const savedMode = res.data?.generation_mode === 'ai' ? 'ai' : 'template'
      setGenerationMode(savedMode)
      toast.success(savedMode === 'ai' ? 'Agentic AI enabled for the entire application' : 'Approved templates enabled for the entire application')
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Could not update AI generation mode')
    } finally {
      setSavingGenerationMode(false)
    }
  }

  const handleClear = async () => {
    setClearing(true)
    try { await clearDatabase(); toast.success('Database cleared'); setShowClear(false); load() }
    catch (e) { toast.error(e.message) }
    finally { setClearing(false) }
  }

  const fetchLinkedIn = async () => {
    if (fetchingLinkedIn) return
    setFetchingLinkedIn(true)
    setLinkedinMessage('Fetching Python client requirements and trainer profiles…')
    try {
      const body = { domains: ['Python'], search_provider: 'public', save: true, max_results: 20, max_queries: 2 }
      const [clientRes, trainerRes] = await Promise.all([
        api.post('/linkedin-leads/search', { ...body, mode: 'client' }),
        api.post('/linkedin-leads/search', { ...body, mode: 'trainer' }),
      ])
      const clientSaved = Number(clientRes.data?.saved_count || 0)
      const trainerSaved = Number(trainerRes.data?.saved_count || 0)
      const clientFound = Number(clientRes.data?.found || 0)
      const trainerFound = Number(trainerRes.data?.found || 0)
      const error = clientRes.data?.search_error || trainerRes.data?.search_error || ''
      const reason = clientRes.data?.domain_outcomes?.[0]?.reason || trainerRes.data?.domain_outcomes?.[0]?.reason || ''
      const message = error
        ? error
        : `Saved ${clientSaved} client requirement${clientSaved === 1 ? '' : 's'} and ${trainerSaved} trainer${trainerSaved === 1 ? '' : 's'}. Found ${clientFound} client posts and ${trainerFound} trainer profiles.${reason ? ` ${reason}` : ''}`
      setLinkedinMessage(message)
      if (clientSaved || trainerSaved) toast.success(message)
      else toast.error(message)
      await load(true)
    } catch (error) {
      const message = error?.response?.data?.detail || error.message || 'LinkedIn fetch failed'
      setLinkedinMessage(message)
      toast.error(message)
    } finally {
      setFetchingLinkedIn(false)
    }
  }

  const syncClientInbox = async () => {
    if (syncingInbox) return
    setSyncingInbox(true)
    try {
      const res = await api.post('/gmail/sync-now?limit=50&process=false')
      if (res.data?.queued) {
        toast.success('Inbox fetch started for review. No client replies will be sent.')
        window.setTimeout(() => load(true), 10000)
        return
      }
      const processed = Number(res.data?.processed_count || 0)
      toast.success(`Inbox checked: ${processed} message(s) fetched for review`)
      await load(true)
    } catch (e) { toast.error(e.message || 'Inbox sync failed') }
    finally { setSyncingInbox(false) }
  }

  // ── Derived values ──────────────────────────────────────────
  const totalEmails    = Number(stats?.total_emails_sent ?? stats?.emails?.total_sent ?? 0)
  const failedEmails   = Number(stats?.total_emails_failed ?? stats?.emails?.failed ?? 0)
  const totalReplies   = Number(stats?.total_replies ?? stats?.emails?.total_replies ?? 0)
  const totalTrainers  = Number(stats?.trainers?.total ?? stats?.total_trainers ?? 0)
  const pendingReview  = Number(stats?.pending_review ?? stats?.trainers?.pending_review ?? 0)
  const interested     = Number(stats?.interested_count ?? stats?.interested ?? 0)
  const whatsapp       = stats?.whatsapp || {}
  const whatsappSent   = Number(whatsapp.total_sent ?? whatsapp.sent ?? 0)
  const whatsappFailed = Number(whatsapp.failed || 0)
  const whatsappSkipped = Number(whatsapp.skipped || 0)
  const whatsappAttempted = Number(whatsapp.total_attempted ?? whatsapp.total ?? whatsappSent + whatsappFailed + whatsappSkipped)
  const whatsappReplies = Number(whatsapp.replies || 0)
  const clientStats    = clientInbox?.stats || {}
  const recentClientEmails    = clientInbox?.emails || []
  const latestClientTrainerRequest = recentClientEmails.find(item =>
    item?.status !== 'spam' && (item?.extracted?.is_training_request || item?.requirement_id)
  )
  const clientRequests = stats?.client_requests || {}
  const clientTotal    = Number(clientRequests.total ?? clientStats.total ?? 0)
  const clientToday    = Number(clientRequests.today ?? clientStats.today ?? 0)
  const clientPending  = Number(clientRequests.pending_approval ?? clientStats.pending_approval ?? 0)
  const linkedinClientTotal = Number(clientRequests.linkedin_total || 0)
  const linkedinClients = clientRequests.recent_linkedin || []
  const confirmedTrainers = Number(stats?.trainers?.confirmed || 0)
  const linkedinTrainerTotal = Number(stats?.trainers?.leads || 0)
  const linkedinTrainers = stats?.trainers?.recent_linkedin || []
  const gmailConnected = !!gmailStatus?.connected
  const gmailUser      = gmailStatus?.gmail_user || gmailStatus?.configured_user || gmailStatus?.email || ''
  const replyRate      = totalEmails ? normaliseRate(stats?.reply_rate ?? (totalReplies / totalEmails) * 100) : null
  const interestRate   = totalTrainers ? normaliseRate(stats?.interest_rate ?? (interested / totalTrainers) * 100) : null
  const emailAttempts  = totalEmails + failedEmails
  const deliveryRate   = emailAttempts ? (totalEmails / emailAttempts) * 100 : null
  const reviewLoad     = totalTrainers ? (pendingReview / totalTrainers) * 100 : null
  const scoreInputs    = [deliveryRate, replyRate, interestRate, reviewLoad == null ? null : Math.max(0, 100 - reviewLoad)].filter(Number.isFinite)
  const automationScore = scoreInputs.length ? Math.round(scoreInputs.reduce((sum, value) => sum + value, 0) / scoreInputs.length) : null

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

  const sentByDate = new Map((dashboardAnalytics?.emails_over_time || []).map(row => [row.date, Number(row.emails_sent || 0)]))
  const repliesByDate = new Map((dashboardAnalytics?.email_replies_over_time || []).map(row => [row.date, Number(row.replies || 0)]))
  const monday = new Date()
  monday.setHours(0, 0, 0, 0)
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7))
  const activityData = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(monday)
    date.setDate(monday.getDate() + index)
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    return {
      day: date.toLocaleDateString(undefined, { weekday: 'short' }),
      emails: sentByDate.get(key) || 0,
      replies: repliesByDate.get(key) || 0,
    }
  })

  const statCards = [
    { icon: BriefcaseBusiness, label: 'Client Requests', value: clientTotal, sub: linkedinClientTotal ? `${clientToday} today · ${linkedinClientTotal} from LinkedIn` : `${clientToday} received today`, tone: 'blue', linkTo: '/client-requests' },
    { icon: Inbox,             label: 'Client Pending',  value: clientPending, sub: 'Needs approval', tone: 'amber',  linkTo: '/client-requests' },
    { icon: Users,             label: 'Total Trainers',  value: totalTrainers, sub: `${confirmedTrainers} confirmed · ${linkedinTrainerTotal} LinkedIn`, tone: 'blue', linkTo: '/trainers' },
    { icon: Mail,              label: 'Emails Sent',     value: totalEmails, sub: 'Outreach emails', tone: 'purple', linkTo: '/emails' },
    { icon: TrendingUp,        label: 'Replies',         value: totalReplies, sub: 'Trainer replies', tone: 'emerald', linkTo: '/emails' },
    { icon: BarChart2,         label: 'Requirements',    value: stats?.total_requirements ?? stats?.requirements?.total ?? 0, sub: 'Active searches', tone: 'orange', linkTo: '/requirements' },
    { icon: Activity,          label: 'Confirmed',       value: stats?.confirmed_count ?? stats?.shortlists?.trainers_selected ?? 0, sub: 'Ready to close', tone: 'sky', linkTo: '/shortlist1' },
    { icon: Send,              label: 'WhatsApp Activity', value: whatsappAttempted, sub: `${whatsappSent} sent, ${whatsappFailed} failed, ${whatsappSkipped} skipped`, tone: whatsappFailed ? 'red' : 'green' },
  ]


  return (
    <div className="dashboard-shell space-y-6 animate-fade-in">

      {/* ── Hero strip ─────────────────────────────────────── */}
      <div className="dashboard-hero overflow-hidden">
        <div className="p-5 md:p-7">
          <div className="grid gap-6 lg:grid-cols-[1fr_280px] lg:items-start">
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-3">
                <span className="h-2 w-2 rounded-full bg-blue-600 shadow-[0_0_16px_rgba(37,99,235,.45)] animate-pulse-soft" />
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">Live command view</span>
              </div>
              <h1 className="text-4xl font-extrabold tracking-normal text-slate-950 md:text-5xl">Dashboard</h1>
              <p className="mt-3 max-w-3xl text-sm font-medium leading-6 text-slate-600 md:text-base">Track trainer inventory, outreach movement, reply quality, and recruiter action in one clean view.</p>
              <div className="flex flex-wrap gap-2.5 mt-5">
                {['Trainer intelligence','Client inbox','Mail automation','PO to invoice'].map(item => (
                  <span key={item} className="dashboard-hero-chip px-3 py-1.5 text-xs font-bold">{item}</span>
                ))}
              </div>
            </div>

            {/* Ops signals */}
            <div className="grid gap-2.5">
              {[
                ['AI matching', 'Live', 'badge-blue'],
                ['Mail automation', gmailConnected ? 'Ready' : 'Setup needed', gmailConnected ? 'badge-green' : 'badge-amber'],
                ['Pipeline sync', refreshing ? 'Refreshing…' : 'Normal', refreshing ? 'badge-blue' : 'badge-slate'],
              ].map(([label, val, cls]) => (
                <div key={label} className="dashboard-signal px-4 py-3 flex items-center justify-between gap-4">
                  <span className="text-xs font-bold text-blue-700 uppercase tracking-wide">{label}</span>
                  <span className={clsx('badge text-[11px]', cls)}>{val}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Action bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white/80 px-5 py-4 md:px-7">
          <div className="dashboard-hero-chip flex items-center gap-2 px-3 py-2 text-xs font-bold">
            <Database className="h-4 w-4 text-blue-600" />
            {loading
              ? 'Loading…'
              : statsUnavailable
                ? 'Trainer data temporarily unavailable'
                : `${totalTrainers.toLocaleString('en-IN')} trainer profiles synced`}
          </div>
          <div className="flex gap-2">
            <button onClick={() => setShowClear(true)} className="inline-flex items-center gap-2 rounded-md border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-600 transition hover:bg-red-50">
              <Trash2 className="h-4 w-4" /> Clear DB
            </button>
            <button onClick={() => load(true)} disabled={refreshing} className="dashboard-hero-action inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold text-blue-700 transition disabled:opacity-60">
              <RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} /> Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Shared AI generation setting */}
      <section className={clsx('flex flex-wrap items-center justify-between gap-4 rounded-2xl border px-5 py-4', generationMode === 'ai' ? 'border-violet-200 bg-violet-50' : 'border-slate-200 bg-white')}>
        <div className="flex items-start gap-3">
          <span className={clsx('mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl', generationMode === 'ai' ? 'bg-violet-100 text-violet-700' : 'bg-slate-100 text-slate-500')}>
            <Sparkles className="h-4 w-4" />
          </span>
          <div>
            <p className="font-bold text-slate-900">Agentic AI for the entire application</p>
            <p className="mt-1 text-sm text-slate-600">When this is on, the model writes the same one reply the templates use. Annapurna U covers ToC, lab cost, and a mail that asks for both. Murali Mohan M covers invoice and purchase order. Approved packages stay exactly as reviewed.</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className={clsx('text-xs font-bold uppercase tracking-wide', generationMode === 'ai' ? 'text-violet-800' : 'text-slate-600')}>
            {generationMode === 'ai' ? 'AI is on' : 'Approved templates'}
          </span>
          <button
            type="button"
            role="switch"
            aria-label="Agentic AI for the entire application"
            aria-checked={generationMode === 'ai'}
            onClick={() => updateGenerationMode(generationMode === 'ai' ? 'template' : 'ai')}
            disabled={savingGenerationMode}
            className={clsx('relative h-7 w-14 rounded-full transition-colors disabled:opacity-50', generationMode === 'ai' ? 'bg-violet-600' : 'bg-slate-400')}
          >
            <span className={clsx('absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform', generationMode === 'ai' ? 'translate-x-8' : 'translate-x-1')} />
          </button>
        </div>
      </section>

      <div className="grid gap-3 md:grid-cols-4">
        {[
          ['Automation score', formatPercent(automationScore), automationScore == null ? 'No data' : automationScore >= 80 ? 'Strong' : automationScore >= 55 ? 'Watch' : 'Needs action', automationScore == null ? 'badge-slate' : automationScore >= 80 ? 'badge-green' : automationScore >= 55 ? 'badge-amber' : 'badge-red'],
          ['Client queue', clientPending.toLocaleString('en-IN'), clientPending ? 'Pending review' : 'Clear', clientPending ? 'badge-amber' : 'badge-green'],
          ['Reply engine', formatPercent(replyRate), `${totalReplies.toLocaleString('en-IN')} replies`, 'badge-blue'],
          ['Delivery', formatPercent(deliveryRate), deliveryRate == null ? 'No activity' : failedEmails ? `${failedEmails} failed` : 'Clean', deliveryRate == null ? 'badge-slate' : failedEmails ? 'badge-red' : 'badge-green'],
        ].map(([label, value, status, badge]) => (
          <div key={label} className="dashboard-mini-card flex items-center justify-between gap-3 p-3">
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{label}</p>
              <p className="mt-1 truncate text-xl font-extrabold text-slate-900" style={{ fontFamily: "'Plus Jakarta Sans',sans-serif" }}>{value}</p>
            </div>
            <span className={clsx('badge text-[11px]', badge)}>{status}</span>
          </div>
        ))}
      </div>

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

      <section className="rounded-2xl border border-slate-200 bg-white p-4 md:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-900">LinkedIn collection</p>
            <p className="mt-1 text-xs text-slate-500">
              {linkedinMessage || 'Fetch client requirement posts and trainer profiles. Saved leads stay on this dashboard.'}
            </p>
          </div>
          <button type="button" onClick={fetchLinkedIn} disabled={fetchingLinkedIn} className="btn-primary text-sm disabled:opacity-50">
            {fetchingLinkedIn ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Fetch LinkedIn
          </button>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-800">Client requirements</p>
              <button type="button" onClick={() => navigate('/linkedin-client-pipeline')} className="text-xs font-bold text-blue-600">View all</button>
            </div>
            {loading ? (
              <div className="skeleton h-16 w-full" />
            ) : linkedinClients.length ? (
              <div className="space-y-2">
                {linkedinClients.slice(0, 4).map(item => (
                  <button key={item.lead_id || item.source_url} type="button" onClick={() => navigate('/linkedin-client-pipeline')} className="dashboard-list-row w-full px-3 py-2.5 text-left">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-semibold text-slate-800">{item.domain ? `${item.domain} requirement` : item.company_name || 'Client requirement'}</p>
                      <span className="badge badge-blue text-[11px]">{item.status || 'new'}</span>
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-400">
                      {item.contact_name || item.company_name || 'LinkedIn post'}
                      {item.created_at ? ` · ${formatDateTime(item.created_at)}` : ''}
                    </p>
                    {item.summary && <p className="mt-1 line-clamp-2 text-xs text-slate-500">{item.summary}</p>}
                  </button>
                ))}
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">No LinkedIn client requirements yet.</p>
            )}
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-800">Trainers</p>
              <button type="button" onClick={() => navigate('/linkedin-pipeline')} className="text-xs font-bold text-blue-600">View all</button>
            </div>
            {loading ? (
              <div className="skeleton h-16 w-full" />
            ) : linkedinTrainers.length ? (
              <div className="space-y-2">
                {linkedinTrainers.slice(0, 4).map(item => (
                  <button key={item.lead_id || item.source_url} type="button" onClick={() => navigate('/linkedin-pipeline')} className="dashboard-list-row w-full px-3 py-2.5 text-left">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-semibold text-slate-800">{item.name || item.trainer_name || 'Trainer profile'}</p>
                      <span className="badge badge-slate text-[11px]">{item.domain || 'LinkedIn'}</span>
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-400">
                      {item.headline || item.summary || 'Trainer lead'}
                      {item.created_at ? ` · ${formatDateTime(item.created_at)}` : ''}
                    </p>
                  </button>
                ))}
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">No LinkedIn trainers yet.</p>
            )}
          </div>
        </div>
      </section>

      {/* ── Client flow + shortcuts ─────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_340px]">
        <Panel title="Client Request Flow" eyebrow="Client automation"
          badge={gmailConnected ? 'Gmail connected' : 'Gmail not connected'}>

          {latestClientTrainerRequest && (
            <button type="button" onClick={() => navigate('/client-requests')}
              className="dashboard-list-row mb-4 w-full px-4 py-3 text-left">
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

          <div className="dashboard-mini-card p-4 mb-4">
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

          <div className="dashboard-mini-card p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="font-semibold text-slate-900 text-sm">Latest requests</p>
              <button onClick={() => navigate('/client-requests')} className="text-xs font-bold text-blue-600 hover:text-blue-800">View all</button>
            </div>
            {loading ? (
              <div className="space-y-2">{['sk-0','sk-1','sk-2'].map(k => <div key={k} className="skeleton h-14 w-full" />)}</div>
            ) : recentClientEmails.length ? (
              <div className="space-y-2">
                {recentClientEmails.slice(0, 4).map(item => (
                  <button key={item.email_id} onClick={() => navigate('/client-requests')}
                    className="dashboard-list-row w-full px-3 py-2.5 text-left">
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
                className="dashboard-action-card w-full px-4 py-3 text-left">
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
              className="dashboard-action-card w-full px-4 py-3 text-left">
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
              value={whatsappSent + whatsappFailed ? (whatsappSent / (whatsappSent + whatsappFailed)) * 100 : null}
              sub={whatsappSent + whatsappFailed ? `${whatsappFailed} failed, ${whatsappSkipped} skipped, ${whatsappReplies} replies` : 'No delivery attempts yet'} color="bg-emerald-500" />
          </div>
        </Panel>
      </div>

      {/* ── Charts row ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Email Activity" badge="This week" className="lg:col-span-2">
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
            {stats.recent_emails.map((email) => (
              <button key={email.email_id || email.to_email} onClick={() => navigate('/emails')}
                className="dashboard-list-row group/row flex w-full items-center gap-4 px-3 py-2.5 text-left">
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
            {stats.recent_whatsapp.map((msg) => {
              const ctx = msg.context || {}
              return (
                <div key={msg.whatsapp_id || msg.to_number} className="dashboard-list-row flex items-start gap-4 px-3 py-3">
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
