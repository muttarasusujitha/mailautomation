import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowDownUp,
  BarChart3,
  Bot,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Cloud,
  Download,
  GitBranch,
  IndianRupee,
  Loader2,
  MessageCircle,
  PieChart as PieChartIcon,
  RefreshCw,
  ReceiptText,
  Target,
  TrendingUp,
  Workflow,
  Zap,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Funnel,
  FunnelChart,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { getDashboardAnalytics } from '../utils/api'

const COLORS = ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#14b8a6', '#f97316']

const PRESETS = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'This Week' },
  { key: 'month', label: 'This Month' },
  { key: 'custom', label: 'Custom Range' },
]

const inputDate = (date) => {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const todayInput = () => inputDate(new Date())

const monthStartInput = () => {
  const now = new Date()
  return inputDate(new Date(now.getFullYear(), now.getMonth(), 1))
}

const number = (value) => Number(value || 0).toLocaleString('en-IN')

const currency = (value, code = 'INR') =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: code,
    maximumFractionDigits: 0,
  }).format(Number(value || 0))

const expenseCurrency = (value, code = 'INR') =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: code,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value || 0))

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-slate-100 bg-white px-3 py-2 text-sm shadow-xl">
      {label && <p className="mb-1 font-semibold text-slate-700">{label}</p>}
      {payload.map((item, index) => (
        <p key={index} className="font-medium" style={{ color: item.color || item.payload?.fill }}>
          {item.name}: {item.value}
        </p>
      ))}
    </div>
  )
}

function Panel({ title, subtitle, icon: Icon, children, className }) {
  return (
    <section className={clsx('rounded-2xl border border-slate-200 bg-white p-5 shadow-sm', className)}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            {Icon && (
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                <Icon className="h-4 w-4" />
              </span>
            )}
            <h2 className="text-base font-bold text-slate-900">{title}</h2>
          </div>
          {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

function MetricCard({ icon: Icon, label, value, sub, tone = 'blue', onClick }) {
  const tones = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-emerald-50 text-emerald-600',
    amber: 'bg-amber-50 text-amber-600',
    purple: 'bg-violet-50 text-violet-600',
    cyan: 'bg-cyan-50 text-cyan-600',
    red: 'bg-red-50 text-red-600',
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:-translate-y-1 hover:shadow-lg',
        onClick ? 'cursor-pointer' : 'cursor-default'
      )}
    >
      <div className="flex items-start gap-3">
        <div className={clsx('flex h-10 w-10 items-center justify-center rounded-xl', tones[tone])}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{value}</p>
          {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
        </div>
      </div>
    </button>
  )
}

function EmptyChart({ label = 'No data for this range' }) {
  return (
    <div className="flex h-[260px] items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-sm font-medium text-slate-400">
      {label}
    </div>
  )
}

const EXPENSE_ICON = {
  whatsapp: MessageCircle,
  teams: Workflow,
  gemini: Bot,
  client_storage: Cloud,
}

const EXPENSE_TONE = {
  whatsapp: 'border-emerald-100 bg-emerald-50 text-emerald-700',
  teams: 'border-blue-100 bg-blue-50 text-blue-700',
  gemini: 'border-violet-100 bg-violet-50 text-violet-700',
  client_storage: 'border-cyan-100 bg-cyan-50 text-cyan-700',
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [filter, setFilter] = useState({
    preset: 'month',
    start_date: monthStartInput(),
    end_date: todayInput(),
  })

  const params = useMemo(() => {
    if (filter.preset !== 'custom') return { preset: filter.preset }
    return {
      preset: 'custom',
      start_date: filter.start_date,
      end_date: filter.end_date,
    }
  }, [filter])

  const load = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    try {
      const res = await getDashboardAnalytics(params)
      setData(res.data)
    } catch (err) {
      toast.error(err.message || 'Could not load dashboard analytics')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    load(false)
  }, [params])

  const setPreset = (preset) => {
    setFilter(prev => ({ ...prev, preset }))
  }

  const exportPdf = () => {
    setTimeout(() => window.print(), 50)
  }

  const cards = data?.status_cards || {}
  const weekly = data?.requirements_weekly || []
  const funnel = data?.pipeline_funnel || []
  const categories = data?.category_breakdown || []
  const trend = data?.reply_rate_trend || []
  const whatsapp = data?.whatsapp || {}
  const poMonth = data?.po_month || {}
  const expenses = data?.expenses || {}
  const expenseItems = expenses.items || []
  const expenseWeekly = expenses.weekly || []
  const expenseCurrencyCode = expenses.currency || 'INR'

  return (
    <div className="space-y-5" id="dashboard-report">
      <style>{`
        @media print {
          body * { visibility: hidden; }
          #dashboard-report, #dashboard-report * { visibility: visible; }
          #dashboard-report { position: absolute; inset: 0; padding: 0; background: white; }
          .no-print { display: none !important; }
          .print-break { break-inside: avoid; page-break-inside: avoid; }
        }
      `}</style>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Zap className="h-6 w-6 text-blue-600" />
            Analytics Dashboard
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Requirement movement, trainer responses, WhatsApp delivery, and purchase order value.
          </p>
        </div>

        <div className="no-print flex flex-wrap gap-2">
          <button onClick={() => load(true)} disabled={refreshing} className="btn-secondary text-sm">
            <RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} />
            Refresh
          </button>
          <button onClick={exportPdf} className="btn-primary text-sm">
            <Download className="h-4 w-4" />
            Export PDF
          </button>
        </div>
      </div>

      <div className="no-print rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <CalendarDays className="h-4 w-4 text-blue-600" />
            Date Range
          </div>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map(item => (
              <button
                key={item.key}
                type="button"
                onClick={() => setPreset(item.key)}
                className={clsx(
                  'rounded-lg px-3 py-2 text-xs font-semibold transition',
                  filter.preset === item.key
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          {filter.preset === 'custom' && (
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <input
                type="date"
                value={filter.start_date}
                onChange={e => setFilter(prev => ({ ...prev, start_date: e.target.value }))}
                className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
              />
              <span className="text-xs text-slate-400">to</span>
              <input
                type="date"
                value={filter.end_date}
                onChange={e => setFilter(prev => ({ ...prev, end_date: e.target.value }))}
                className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
              />
            </div>
          )}
        </div>
      </div>

      {loading ? (
        <div className="flex min-h-[420px] items-center justify-center rounded-2xl border border-slate-200 bg-white">
          <div className="flex items-center gap-3 text-sm font-semibold text-slate-500">
            <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
            Loading analytics...
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-6">
            <MetricCard
              icon={Target}
              label="Total Open"
              value={number(cards.total_open)}
              sub="Requirements still active"
              tone="blue"
              onClick={() => navigate('/requirements')}
            />
            <MetricCard
              icon={CheckCircle2}
              label="Total Closed"
              value={number(cards.total_closed)}
              sub="Closed or PO generated"
              tone="green"
              onClick={() => navigate('/requirements')}
            />
            <MetricCard
              icon={Workflow}
              label="In Pipeline"
              value={number(cards.total_in_pipeline)}
              sub="Shortlist or outreach started"
              tone="purple"
              onClick={() => navigate('/shortlist')}
            />
            <MetricCard
              icon={Clock3}
              label="Avg Days to Close"
              value={`${Number(cards.average_days_to_close || 0).toFixed(1)}`}
              sub="Based on generated POs"
              tone="amber"
            />
            <MetricCard
              icon={IndianRupee}
              label="PO Value This Month"
              value={currency(poMonth.value, poMonth.currency || 'INR')}
              sub={`${number(poMonth.count)} purchase orders`}
              tone="cyan"
            />
            <MetricCard
              icon={MessageCircle}
              label="WhatsApp Delivery"
              value={`${whatsapp.delivery_rate || 0}%`}
              sub={`${number(whatsapp.delivered)} delivered of ${number(whatsapp.total)}`}
              tone="green"
              onClick={() => navigate('/admin?section=whatsapp')}
            />
          </div>

          <Panel
            title="Expense Monitor"
            subtitle="Estimated cost by selected range. Update provider rates in admin settings/costCfg when your billing rates change."
            icon={ReceiptText}
            className="print-break"
          >
            <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Total estimated expense</p>
                <p className="mt-2 text-3xl font-bold text-slate-900">
                  {expenseCurrency(expenses.total, expenseCurrencyCode)}
                </p>
                <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-lg bg-white px-2 py-2">
                    <p className="text-[11px] font-semibold text-slate-400">Communication</p>
                    <p className="text-sm font-bold text-slate-800">{expenseCurrency(expenses.communication_total, expenseCurrencyCode)}</p>
                  </div>
                  <div className="rounded-lg bg-white px-2 py-2">
                    <p className="text-[11px] font-semibold text-slate-400">Gemini AI</p>
                    <p className="text-sm font-bold text-slate-800">{expenseCurrency(expenses.ai_total, expenseCurrencyCode)}</p>
                  </div>
                  <div className="rounded-lg bg-white px-2 py-2">
                    <p className="text-[11px] font-semibold text-slate-400">Storage</p>
                    <p className="text-sm font-bold text-slate-800">{expenseCurrency(expenses.storage_total, expenseCurrencyCode)}</p>
                  </div>
                </div>
                <p className="mt-3 text-xs leading-5 text-slate-500">
                  These values are estimates from application logs. Twilio, Gemini, Microsoft, and cloud invoices remain the final billing source.
                </p>
              </div>

              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {expenseItems.map(item => {
                  const Icon = EXPENSE_ICON[item.key] || IndianRupee
                  return (
                    <div key={item.key} className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="flex items-center justify-between gap-3">
                        <span className={clsx('flex h-9 w-9 items-center justify-center rounded-lg border', EXPENSE_TONE[item.key] || 'border-slate-200 bg-slate-50 text-slate-600')}>
                          <Icon className="h-4 w-4" />
                        </span>
                        <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-500">
                          {number(item.count)} {item.unit}
                        </span>
                      </div>
                      <p className="mt-3 text-sm font-bold text-slate-800">{item.label}</p>
                      <p className="mt-1 text-2xl font-bold text-slate-900">{expenseCurrency(item.cost, expenseCurrencyCode)}</p>
                      <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-500">{item.note}</p>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="mt-5">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-bold text-slate-900">Weekly expense trend</p>
                  <p className="text-xs text-slate-500">Changes automatically for Today, Week, Month, and Custom ranges.</p>
                </div>
                {expenses.estimated && (
                  <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-bold text-amber-700">
                    Estimated
                  </span>
                )}
              </div>
              {expenseWeekly.length ? (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={expenseWeekly}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="week" tick={{ fontSize: 12, fill: '#64748b' }} />
                    <YAxis tick={{ fontSize: 12, fill: '#64748b' }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Legend />
                    <Bar dataKey="whatsapp" name="WhatsApp" stackId="cost" fill="#10b981" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="teams" name="Teams" stackId="cost" fill="#2563eb" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="gemini" name="Gemini" stackId="cost" fill="#8b5cf6" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="storage" name="Client Inbox Storage" stackId="cost" fill="#06b6d4" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart label="No expense usage for this range" />
              )}
            </div>
          </Panel>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Panel
              title="Requirements Opened vs Closed"
              subtitle="Weekly movement for the selected date range"
              icon={BarChart3}
              className="print-break xl:col-span-2"
            >
              {weekly.length ? (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={weekly}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="week" tick={{ fontSize: 12, fill: '#64748b' }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: '#64748b' }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Legend />
                    <Bar dataKey="opened" name="Opened" fill="#2563eb" radius={[6, 6, 0, 0]} />
                    <Bar dataKey="closed" name="Closed" fill="#10b981" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart />
              )}
            </Panel>

            <Panel
              title="Pipeline Funnel"
              subtitle="Requirements by current pipeline stage"
              icon={GitBranch}
              className="print-break"
            >
              {funnel.some(item => item.value > 0) ? (
                <ResponsiveContainer width="100%" height={300}>
                  <FunnelChart>
                    <Tooltip content={<ChartTooltip />} />
                    <Funnel dataKey="value" data={funnel} isAnimationActive>
                      <LabelList position="right" fill="#334155" stroke="none" dataKey="stage" />
                      {funnel.map((entry, index) => (
                        <Cell key={entry.stage} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Funnel>
                  </FunnelChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart />
              )}
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Panel
              title="Category Breakdown"
              subtitle="Requirement technology categories"
              icon={PieChartIcon}
              className="print-break"
            >
              {categories.length ? (
                <>
                  <ResponsiveContainer width="100%" height={260}>
                    <PieChart>
                      <Pie
                        data={categories}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={58}
                        outerRadius={92}
                        paddingAngle={3}
                      >
                        {categories.map((entry, index) => (
                          <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip content={<ChartTooltip />} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="space-y-2">
                    {categories.map((item, index) => (
                      <div key={item.name} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">
                        <span className="flex items-center gap-2 text-slate-700">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ background: COLORS[index % COLORS.length] }} />
                          {item.name}
                        </span>
                        <span className="font-bold text-slate-900">{item.value}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <EmptyChart />
              )}
            </Panel>

            <Panel
              title="Reply Rate Trend"
              subtitle="Last 4 weeks of outreach replies"
              icon={TrendingUp}
              className="print-break xl:col-span-2"
            >
              {trend.length ? (
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="week" tick={{ fontSize: 12, fill: '#64748b' }} />
                    <YAxis unit="%" tick={{ fontSize: 12, fill: '#64748b' }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Legend />
                    <Line
                      type="monotone"
                      dataKey="reply_rate"
                      name="Reply Rate"
                      stroke="#10b981"
                      strokeWidth={3}
                      dot={{ r: 4, fill: '#10b981' }}
                    />
                    <Line
                      type="monotone"
                      dataKey="sent"
                      name="Emails Sent"
                      stroke="#2563eb"
                      strokeWidth={2}
                      dot={{ r: 3, fill: '#2563eb' }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart />
              )}
            </Panel>
          </div>

          <Panel
            title="WhatsApp Delivery Detail"
            subtitle="Delivery health for outbound WhatsApp notifications in the selected range"
            icon={ArrowDownUp}
            className="print-break"
          >
            <div className="grid gap-4 md:grid-cols-4">
              {[
                ['Total Messages', whatsapp.total, 'blue'],
                ['Sent / Queued', whatsapp.sent, 'purple'],
                ['Delivered', whatsapp.delivered, 'green'],
                ['Failed', whatsapp.failed, 'red'],
              ].map(([label, value, tone]) => (
                <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
                  <p className={clsx(
                    'mt-1 text-2xl font-bold',
                    tone === 'green' && 'text-emerald-600',
                    tone === 'red' && 'text-red-600',
                    tone === 'purple' && 'text-violet-600',
                    tone === 'blue' && 'text-blue-600'
                  )}>
                    {number(value)}
                  </p>
                </div>
              ))}
            </div>
            <div className="mt-4 h-3 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-emerald-500 transition-all"
                style={{ width: `${Math.min(100, Number(whatsapp.delivery_rate || 0))}%` }}
              />
            </div>
          </Panel>
        </>
      )}
    </div>
  )
}
