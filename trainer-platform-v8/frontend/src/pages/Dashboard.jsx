import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getDashboardStats, clearDatabase } from '../utils/api'
import { Users, Mail, TrendingUp, CheckCircle, XCircle, Clock,
         RefreshCw, BarChart2, Activity, Trash2, AlertTriangle, Star, Zap } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
         PieChart, Pie, Cell, Area, AreaChart, Legend } from 'recharts'
import toast from 'react-hot-toast'
import clsx from 'clsx'

const COLORS = ['#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4']

function AnimatedNumber({ value, duration = 1200 }) {
  const [display, setDisplay] = useState(0)
  const start = useRef(0)
  useEffect(() => {
    if (value === 0) { setDisplay(0); return }
    const startTime = Date.now()
    const startVal  = start.current
    const tick = () => {
      const elapsed = Date.now() - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(startVal + (value - startVal) * eased))
      if (progress < 1) requestAnimationFrame(tick)
      else start.current = value
    }
    requestAnimationFrame(tick)
  }, [value])
  return <span>{display}</span>
}

const Tooltip2 = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-slate-100 shadow-xl rounded-xl px-4 py-3 text-sm">
      <p className="font-semibold text-slate-700 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-medium">{p.name}: {p.value}</p>
      ))}
    </div>
  )
}

const StatCard = ({ icon: Icon, label, value, sub, gradient, loading, suffix = '', onClick, linkTo }) => {
  const navigate = useNavigate()
  const handleClick = () => {
    if (onClick) onClick()
    else if (linkTo) navigate(linkTo)
  }
  return (
    <div
      onClick={handleClick}
      className={clsx(
        "group card p-5 flex items-start gap-4 relative overflow-hidden transition-all duration-300",
        "hover:shadow-card-lg hover:-translate-y-1 hover:border-brand-200",
        (onClick || linkTo) ? "cursor-pointer" : "cursor-default"
      )}>
      <div className={clsx(
        'absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl pointer-events-none',
        'ring-2 ring-inset ring-brand-200'
      )} />
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-all duration-300">
        <div className="flex gap-0.5">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="w-1 h-1 rounded-full bg-brand-400 animate-pulse"
                 style={{ animationDelay: `${i * 150}ms` }} />
          ))}
        </div>
      </div>
      <div className={clsx('stat-icon flex-shrink-0 transition-transform duration-300 group-hover:scale-110', gradient)}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-slate-500 mb-0.5">{label}</p>
        {loading
          ? <div className="h-8 w-20 bg-slate-100 rounded-lg animate-pulse" />
          : <p className="font-display text-2xl font-bold text-slate-900">
              <AnimatedNumber value={typeof value === 'number' ? value : 0} />{suffix}
            </p>
        }
        {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
        {(onClick || linkTo) && (
          <p className="text-xs text-brand-400 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            Click to view →
          </p>
        )}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [stats, setStats]       = useState(null)
  const [loading, setLoading]   = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [showClear, setShowClear]   = useState(false)
  const [clearing, setClearing]     = useState(false)
  const navigate = useNavigate()

  const load = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true); else setLoading(true)
    try {
      const res = await getDashboardStats()
      setStats(res.data)
    } catch (e) { toast.error(e.message) }
    finally { setLoading(false); setRefreshing(false) }
  }

  useEffect(() => { load() }, [])

  const handleClear = async () => {
    setClearing(true)
    try {
      await clearDatabase()
      toast.success('✅ Database cleared!')
      setShowClear(false)
      load()
    } catch (e) { toast.error(e.message) }
    finally { setClearing(false) }
  }

  const statusData = stats ? [
    { name: 'Interested', value: stats.interested_count,  color: '#10b981' },
    { name: 'Contacted',  value: stats.contacted_count,   color: '#2563eb' },
    { name: 'Confirmed',  value: stats.confirmed_count,   color: '#8b5cf6' },
    { name: 'Pending',    value: stats.pending_review,    color: '#f59e0b' },
    { name: 'Declined',   value: stats.declined_count,    color: '#ef4444' },
  ].filter(d => d.value > 0) : []

  const scoreDistData = (stats?.score_distribution || []).map(b => ({
    range: b._id === 'Other' ? 'Other' : `${b._id}-${Number(b._id)+19}`,
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

  const STAT_CARDS = [
    { icon: Users,       label: 'Total Trainers',  value: stats?.total_trainers ?? 0,     sub: 'In database',        gradient: 'bg-blue-50 text-brand-500',    linkTo: '/trainers' },
    { icon: Mail,        label: 'Emails Sent',     value: stats?.total_emails_sent ?? 0,  sub: 'Outreach emails',    gradient: 'bg-purple-50 text-purple-500', linkTo: '/emails' },
    { icon: TrendingUp,  label: 'Replies',         value: stats?.total_replies ?? 0,      sub: 'Trainer replies',    gradient: 'bg-emerald-50 text-emerald-500', linkTo: '/emails' },
    { icon: CheckCircle, label: 'Interested',      value: stats?.interested_count ?? 0,   sub: 'Trainers confirmed', gradient: 'bg-green-50 text-green-500',   linkTo: '/emails' },
    { icon: BarChart2,   label: 'Requirements',    value: stats?.total_requirements ?? 0, sub: 'Active searches',    gradient: 'bg-orange-50 text-orange-500', linkTo: '/requirements' },
    { icon: Activity,    label: 'Total Replies',   value: stats?.total_replies ?? 0,      sub: 'From trainers',      gradient: 'bg-sky-50 text-sky-500',       linkTo: '/emails' },
    { icon: Clock,       label: 'Pending Review',  value: stats?.pending_review ?? 0,     sub: 'Needs attention',    gradient: 'bg-amber-50 text-amber-500' },
    { icon: XCircle,     label: 'Emails Failed',   value: stats?.total_emails_failed ?? 0,sub: 'Need retry',         gradient: 'bg-red-50 text-red-500',       linkTo: '/emails' },
  ]

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header — no subtitle */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Zap className="w-6 h-6 text-brand-500" /> Dashboard
          </h1>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowClear(true)} className="btn-secondary text-sm text-red-500 border-red-100 hover:border-red-300">
            <Trash2 className="w-4 h-4" /> Clear DB
          </button>
          <button onClick={() => load(true)} disabled={refreshing} className="btn-secondary text-sm">
            <RefreshCw className={clsx('w-4 h-4', refreshing && 'animate-spin')} /> Refresh
          </button>
        </div>
      </div>

      {/* Clear DB Confirm */}
      {showClear && (
        <div className="card p-5 border-red-100 bg-red-50 animate-slide-up">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-semibold text-red-800">Clear entire database?</p>
              <p className="text-sm text-red-600 mt-1">This will delete all trainers, requirements, shortlists and email logs permanently.</p>
              <div className="flex gap-3 mt-3">
                <button onClick={handleClear} disabled={clearing} className="btn-danger text-sm">
                  {clearing ? <><RefreshCw className="w-4 h-4 animate-spin" /> Clearing...</> : '🗑️ Yes, Clear All'}
                </button>
                <button onClick={() => setShowClear(false)} className="btn-secondary text-sm">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {STAT_CARDS.map((s, i) => (
          <StatCard key={i} {...s} loading={loading} />
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Activity Chart */}
        <div className="card p-5 lg:col-span-2 group hover:shadow-card-lg transition-all duration-300">
          <div className="flex items-center justify-between mb-5">
            <h2 className="section-title">Email Activity</h2>
            <span className="badge-slate">Last 7 days</span>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={activityData}>
              <defs>
                <linearGradient id="emailGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#2563eb" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="replyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#10b981" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="day" tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <Tooltip content={<Tooltip2 />} />
              <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '12px' }} />
              <Area type="monotone" dataKey="emails" stroke="#2563eb" strokeWidth={2.5}
                    fill="url(#emailGrad)" dot={{ r: 4, fill: '#2563eb' }} name="Emails Sent" />
              <Area type="monotone" dataKey="replies" stroke="#10b981" strokeWidth={2.5}
                    fill="url(#replyGrad)" dot={{ r: 4, fill: '#10b981' }} name="Replies" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Trainer Status Donut */}
        <div className="card p-5 group hover:shadow-card-lg transition-all duration-300">
          <h2 className="section-title mb-4">Trainer Status</h2>
          {statusData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={statusData}
                    cx="50%"
                    cy="50%"
                    innerRadius={55}
                    outerRadius={80}
                    dataKey="value"
                    paddingAngle={3}
                  >
                    {statusData.map((entry, i) => (
                      <Cell key={i} fill={entry.color}
                            style={{ filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))', cursor: 'pointer' }} />
                    ))}
                    {/* Center label */}
                  </Pie>
                  <Tooltip content={<Tooltip2 />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5 mt-1">
                {statusData.map((d, i) => (
                  <div key={i} className="flex items-center justify-between text-sm group/row
                                          hover:bg-slate-50 rounded-lg px-2 py-1 transition-colors cursor-default">
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full transition-transform group-hover/row:scale-125"
                           style={{ background: d.color }} />
                      <span className="text-slate-600">{d.name}</span>
                    </div>
                    <span className="font-bold text-slate-800">{d.value}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="h-52 flex flex-col items-center justify-center text-slate-400">
              {/* Placeholder donut */}
              <div className="relative w-28 h-28 mb-3">
                <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                  <circle cx="50" cy="50" r="35" fill="none" stroke="#f1f5f9" strokeWidth="16" />
                  <circle cx="50" cy="50" r="35" fill="none" stroke="#e2e8f0" strokeWidth="16"
                    strokeDasharray="40 180" strokeLinecap="round" />
                  <circle cx="50" cy="50" r="35" fill="none" stroke="#cbd5e1" strokeWidth="16"
                    strokeDasharray="30 220" strokeDashoffset="-40" strokeLinecap="round" />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <Star className="w-6 h-6 text-slate-300" />
                </div>
              </div>
              <p className="text-sm">No data yet — run a search</p>
            </div>
          )}
        </div>
      </div>

      {/* Score Distribution */}
      {scoreDistData.length > 0 && (
        <div className="card p-5 group hover:shadow-card-lg transition-all duration-300">
          <div className="flex items-center justify-between mb-5">
            <h2 className="section-title">Match Score Distribution</h2>
            <span className="badge-blue">All shortlisted trainers</span>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={scoreDistData}>
              <defs>
                <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="#2563eb" />
                  <stop offset="100%" stopColor="#93c5fd" />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="range" tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <Tooltip content={<Tooltip2 />} />
              <Bar dataKey="count" name="Trainers" fill="url(#barGrad)" radius={[8, 8, 0, 0]}
                   style={{ filter: 'drop-shadow(0 2px 4px rgba(37,99,235,0.2))' }} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent Outreach — clickable to emails page */}
      {stats?.recent_emails?.length > 0 && (
        <div className="card p-5">
          <h2 className="section-title mb-4">Recent Outreach</h2>
          <div className="space-y-2">
            {stats.recent_emails.map((e, i) => (
              <div key={i}
                onClick={() => navigate('/emails')}
                className="group/row flex items-center gap-4 py-2.5 px-3 rounded-xl
                           border border-transparent hover:border-brand-100 hover:bg-brand-50
                           transition-all duration-200 cursor-pointer">
                <div className="w-9 h-9 rounded-full bg-brand-50 flex items-center justify-center flex-shrink-0
                                group-hover/row:bg-brand-100 transition-colors">
                  <Mail className="w-4 h-4 text-brand-500" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-800 truncate">{e.trainer_name}</p>
                  <p className="text-xs text-slate-400 truncate">{e.to_email}</p>
                </div>
                <span className={clsx('badge text-xs',
                  e.status === 'sent'   ? 'badge-blue' :
                  e.status === 'failed' ? 'badge-red'  : 'badge-slate')}>
                  {e.status}
                </span>
                {e.reply_received && <span className="badge-green text-xs">Replied</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
