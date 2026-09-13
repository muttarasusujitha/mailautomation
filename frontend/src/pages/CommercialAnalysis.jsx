import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowDownUp, BadgeIndianRupee, CheckCircle2, Search, TrendingUp, Users, X } from 'lucide-react'
import { getCommercialAnalysis, getCommercialAnalyses } from '../utils/api'

const money = value => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pct = value => `${Number(value || 0).toFixed(1)}%`
const clean = value => String(value || '').trim()
const div = (a, b) => Number(b || 0) ? Number(a || 0) / Number(b || 1) : 0
const daysText = value => Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })
const commercialText = option => option?.missing_trainer_commercial ? money(Number(option?.client_revenue || 0) * 0.70) : money(option?.trainer_cost)
const profitText = option => option?.missing_trainer_commercial ? money(Number(option?.client_revenue || 0) * 0.30) : money(option?.clahan_gross_profit)
const marginText = option => option?.missing_trainer_commercial ? '30.0%' : pct(option?.profit_margin_percent)

function parseDatePart(value) {
  const text = clean(value).replace(/,/g, ' ')
  const match = text.match(/\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-zA-Z]+)(?:\s+(\d{4}))?\b/)
  if (!match) return null
  const month = {
    jan: 0, january: 0, feb: 1, february: 1, mar: 2, march: 2, apr: 3, april: 3,
    may: 4, jun: 5, june: 5, jul: 6, july: 6, aug: 7, august: 7, sep: 8,
    sept: 8, september: 8, oct: 9, october: 9, nov: 10, november: 10,
    dec: 11, december: 11,
  }[match[2].toLowerCase()]
  if (month === undefined) return null
  return new Date(Number(match[3] || new Date().getFullYear()), month, Number(match[1]))
}

function dateRangeInfo(value) {
  const text = clean(value)
  if (!text) return null
  const parts = text.split(/\s+(?:to|-|through|till|until)\s+/i)
  if (parts.length < 2) return null
  const start = parseDatePart(parts[0])
  const end = parseDatePart(parts[1])
  if (!start || !end || end < start) return null
  let total = 0
  let saturdays = 0
  let sundays = 0
  const cursor = new Date(start)
  while (cursor <= end) {
    total += 1
    if (cursor.getDay() === 6) saturdays += 1
    if (cursor.getDay() === 0) sundays += 1
    cursor.setDate(cursor.getDate() + 1)
  }
  // Training runs Monday-Saturday; only Sunday is excluded.
  return { total, saturdays, sundays, workingDays: total - sundays }
}

function StatusBadge({ children, tone = 'slate' }) {
  const tones = {
    green: 'border-green-200 bg-green-50 text-green-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-700',
    blue: 'border-blue-200 bg-blue-50 text-blue-700',
    red: 'border-red-200 bg-red-50 text-red-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }
  return <span className={`inline-flex items-center rounded-md border px-2 py-1 text-xs font-bold ${tones[tone]}`}>{children}</span>
}

function requirementTitle(item) {
  const req = item.requirement || {}
  return clean(req.technology_needed || req.domain || req.title || 'Training Requirement')
}

function requirementMetaLine(req = {}, commercial = {}) {
  const dates = clean(req.preferred_dates || req.timeline_start || req.start_date || req.training_dates || req.dates)
  const range = dateRangeInfo(dates)
  const days = range?.total || commercial.duration_days || req.duration_days || req.duration || ''
  const weekendText = range ? `Sat ${range.saturdays}, Sun ${range.sundays}` : ''
  return [
    clean(req.client_name || req.client_company) || 'Client',
    clean(req.mode || req.delivery_mode) || 'Mode pending',
    days ? `${Math.round(Number(days || 0))} days` : 'Days pending',
    dates,
    weekendText,
    clean(req.location || req.preferred_location) || 'Location pending',
  ].filter(Boolean).join(' | ')
}

function needsTrainerCommercial(item) {
  return (item.qtr_trainers || []).some(trainer =>
    (trainer.commercial_options || []).some(option => option.missing_trainer_commercial)
  )
}

function budgetAmount(active) {
  const req = active?.requirement || {}
  return Number(
    active?.negotiation?.current_client_budget ||
    req.client_budget ||
    req.budget ||
    req.approved_client_budget ||
    req.commercial_amount ||
    req.total_amount ||
    req.client_commercial ||
    0
  )
}

function DateBudgetBreakdown({ active }) {
  const req = active?.requirement || {}
  const dates = clean(req.preferred_dates || req.timeline_start || req.start_date || req.training_dates || req.dates)
  const range = dateRangeInfo(dates)
  const budget = budgetAmount(active)
  if (!range || !budget) return null

  const fullPerDay = range.workingDays ? budget / range.workingDays : 0
  const isTotalCommercial = fullPerDay < 10000
  const rows = [
    {
      title: isTotalCommercial ? 'Total Commercial (below ₹10,000/day)' : 'Day-wise Commercial (Sunday excluded)',
      days: range.workingDays,
      revenue: budget,
      perDay: fullPerDay,
      rateLine: `${money(budget)} / ${range.workingDays} training days`,
      note: `Saturday is included; Sunday is excluded. ${isTotalCommercial ? 'Trainer receives one total 70% allocation.' : 'Trainer allocation is shown day-wise.'}`,
    },
  ]

  return (
    <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-bold text-slate-900">Date-wise Budget Calculation</h3>
          <p className="mt-1 text-sm text-slate-500">{dates} | Client budget {money(budget)} | TDS 10% on trainer 70%</p>
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {rows.map(row => {
          const perDay = row.perDay
          const scenarioRevenue = row.revenue
          const clahanPerDay = perDay * 0.30
          const trainerPerDay = perDay * 0.70
          const tdsPerDay = trainerPerDay * 0.10
          const trainerAfterTdsPerDay = trainerPerDay - tdsPerDay
          const clahanTotal = clahanPerDay * row.days
          const trainerTotal = trainerPerDay * row.days
          const tdsTotal = tdsPerDay * row.days
          const trainerAfterTdsTotal = trainerAfterTdsPerDay * row.days
          return (
            <div key={row.title} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <p className="font-bold text-slate-900">{row.title}</p>
              <p className="mt-1 text-xs font-semibold text-slate-500">{row.note}</p>
              <div className="mt-3 space-y-2 text-sm text-slate-700">
                <p>Per-day client rate = {row.rateLine} = <strong>{money(perDay)}</strong></p>
                <p>Client commercial = <strong>{money(scenarioRevenue)}</strong></p>
                <p>Clahan 30% = <strong>{money(clahanTotal)}</strong></p>
                <p>Trainer 70% = <strong>{money(trainerTotal)}</strong>{isTotalCommercial ? ' total' : ` (${money(trainerPerDay)}/day)`}</p>
                <p>TDS = <strong>{money(tdsTotal)}</strong></p>
                <p>Trainer after TDS = <strong>{money(trainerAfterTdsTotal)}</strong></p>
              </div>
              <div className="mt-4 rounded-lg bg-white p-3 text-sm text-slate-700">
                <p>Commercial model: <strong>{isTotalCommercial ? 'Total 70/30 allocation' : 'Day-wise 70/30 allocation'}</strong></p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RequirementCard({ item, selected, onSelect }) {
  const req = item.requirement || {}
  const commercial = item.recommended_commercial || {}
  const trainer = item.recommended_trainer || {}
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-lg border bg-white p-4 text-left shadow-xs transition hover:border-blue-300 hover:shadow-sm ${selected ? 'border-blue-500 ring-2 ring-blue-100' : 'border-slate-200'}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-900">{clean(req.client_name || req.client_company) || 'Client'}</p>
          <p className="mt-1 text-xs font-semibold text-slate-500">{requirementTitle(item)}</p>
        </div>
        <StatusBadge tone={needsTrainerCommercial(item) ? 'amber' : item.negotiation_required ? 'amber' : 'green'}>
          {needsTrainerCommercial(item) ? 'Rate Missing' : item.negotiation_required ? 'Negotiation' : 'Ready'}
        </StatusBadge>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
        <div><p className="text-slate-400">Duration</p><p className="font-bold text-slate-800">{commercial.duration_days || req.duration_days || '-'} days</p></div>
        <div><p className="text-slate-400">Budget</p><p className="font-bold text-slate-800">{money(item.negotiation?.current_client_budget)}</p></div>
        <div><p className="text-slate-400">Model</p><p className="font-bold text-blue-700">{commercial.model || '-'}</p></div>
        <div><p className="text-slate-400">Profit</p><p className="font-bold text-green-700">{money(commercial.clahan_gross_profit)}</p></div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>{item.matching_trainers || 0} matching trainers</span>
        {trainer.trainer_name && <span>Recommended: {trainer.qtr} - {trainer.trainer_name}</span>}
        <span>Margin {pct(commercial.profit_margin_percent)}</span>
      </div>
    </button>
  )
}

function assumedSplit(option) {
  if (!option?.missing_trainer_commercial) return option
  const revenue = Number(option.client_revenue || 0)
  const trainerCost = revenue * 0.70
  const tdsRate = Number(option.tds_rate_percent || 10)
  const tds = trainerCost * (tdsRate / 100)
  return {
    ...option,
    trainer_cost: trainerCost,
    tds_base_amount: trainerCost,
    tds,
    net_amount_after_tds: trainerCost - tds,
    clahan_gross_profit: revenue * 0.30,
    profit_margin_percent: 30,
  }
}

function commercialDateDays(active) {
  const req = active?.requirement || {}
  const dates = clean(req.preferred_dates || req.timeline_start || req.start_date || req.training_dates || req.dates)
  return dateRangeInfo(dates)?.total || 0
}

function CommercialTable({ options = [], active = null }) {
  const actualDays = commercialDateDays(active)
  const calculationLines = option => {
    const calc = assumedSplit(option)
    const days = option.model === 'PER_DAY' ? Number(actualDays || option.duration_days || 0) : Number(option.duration_days || 0)
    const clientRate = div(calc.client_revenue, days)
    const trainerRate = div(calc.trainer_cost, days)
    const clahanCashHeldBeforeTdsDeposit = Number(calc.clahan_gross_profit || 0) + Number(calc.tds || 0)
    if (option.model === 'ONE_TIME_30') {
      return [
        `Client Total = ${money(calc.client_revenue)}`,
        `Clahan 30% = ${money(calc.client_revenue)} x 30% = ${money(calc.clahan_gross_profit)}`,
        `Trainer 70% = ${money(calc.client_revenue)} x 70% = ${money(calc.trainer_cost)}`,
        `TDS Base = Trainer 70% amount = ${money(calc.trainer_cost)}`,
        `TDS = ${money(calc.trainer_cost)} x ${pct(calc.tds_rate_percent)} = ${money(calc.tds)}`,
        `Trainer After TDS = ${money(calc.trainer_cost)} - ${money(calc.tds)} = ${money(calc.net_amount_after_tds)}`,
        `Amount held by Clahan before TDS deposit = Clahan 30% ${money(calc.clahan_gross_profit)} + TDS ${money(calc.tds)} = ${money(clahanCashHeldBeforeTdsDeposit)}`,
        `TDS ${money(calc.tds)} is a statutory deduction to be deposited/handled as per accounting rules; it is shown separately from Clahan profit.`,
        `Clahan Gross Profit = ${money(calc.clahan_gross_profit)}`,
        `Profit Margin = ${money(calc.clahan_gross_profit)} / ${money(calc.client_revenue)} x 100 = ${pct(calc.profit_margin_percent)}`,
      ]
    }
    if (option.model === 'PER_DAY') {
      return [
        `Day-wise Client Rate = ${money(clientRate)}/day`,
        `Total Training Days = ${Math.round(days)} days`,
        `Client Revenue = ${money(clientRate)} x ${Math.round(days)} days = ${money(calc.client_revenue)}`,
        option.missing_trainer_commercial ? `Trainer Day Rate = 70% share = ${money(trainerRate)}/day` : `Trainer Day Rate = ${money(trainerRate)}/day`,
        `Trainer Cost = ${money(trainerRate)} x ${Math.round(days)} days = ${money(calc.trainer_cost)}`,
        `TDS Base = Total trainer cost = ${money(calc.trainer_cost)}`,
        `TDS = ${money(calc.trainer_cost)} x ${pct(calc.tds_rate_percent)} = ${money(calc.tds)}`,
        `Trainer After TDS = ${money(calc.trainer_cost)} - ${money(calc.tds)} = ${money(calc.net_amount_after_tds)}`,
        `Clahan Gross Profit = 30% share = ${money(calc.clahan_gross_profit)}`,
        `Amount held by Clahan before TDS deposit = Profit ${money(calc.clahan_gross_profit)} + TDS ${money(calc.tds)} = ${money(clahanCashHeldBeforeTdsDeposit)}`,
        `Profit Margin = ${money(calc.clahan_gross_profit)} / ${money(calc.client_revenue)} x 100 = ${pct(calc.profit_margin_percent)}`,
      ]
    }
    const label = option.model === 'LUMPSUM' ? 'Lumpsum' : 'Batch'
    if (option.missing_trainer_commercial) {
      return [
        `Client ${label} Amount = ${money(calc.client_revenue)}`,
        `Clahan 30% = ${money(calc.client_revenue)} x 30% = ${money(calc.clahan_gross_profit)}`,
        `Trainer 70% = ${money(calc.client_revenue)} x 70% = ${money(calc.trainer_cost)}`,
        `TDS Base = Trainer 70% amount = ${money(calc.trainer_cost)}`,
        `TDS = ${money(calc.trainer_cost)} x ${pct(calc.tds_rate_percent)} = ${money(calc.tds)}`,
        `Trainer After TDS = ${money(calc.trainer_cost)} - ${money(calc.tds)} = ${money(calc.net_amount_after_tds)}`,
        `Profit Margin = ${money(calc.clahan_gross_profit)} / ${money(calc.client_revenue)} x 100 = ${pct(calc.profit_margin_percent)}`,
      ]
    }
    return [
      `Client ${label} Amount = ${money(calc.client_revenue)}`,
      `Trainer Total Commercial = ${money(calc.trainer_cost)}`,
      `TDS Base = Trainer total commercial = ${money(calc.trainer_cost)}`,
      `TDS = ${money(calc.trainer_cost)} x ${pct(calc.tds_rate_percent)} = ${money(calc.tds)}`,
      `Trainer After TDS = ${money(calc.trainer_cost)} - ${money(calc.tds)} = ${money(calc.net_amount_after_tds)}`,
      `Clahan Gross Profit = ${money(calc.client_revenue)} - ${money(calc.trainer_cost)} - ${money(calc.other_applicable_costs)} = ${money(calc.clahan_gross_profit)}`,
      `Amount held by Clahan before TDS deposit = Profit ${money(calc.clahan_gross_profit)} + TDS ${money(calc.tds)} = ${money(clahanCashHeldBeforeTdsDeposit)}`,
      `TDS ${money(calc.tds)} is shown separately from profit.`,
      `Profit Margin = ${money(calc.clahan_gross_profit)} / ${money(calc.client_revenue)} x 100 = ${pct(calc.profit_margin_percent)}`,
    ]
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-xs font-bold uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">Option</th>
            <th className="px-3 py-2 text-right">Client Revenue</th>
            <th className="px-3 py-2 text-right">Trainer Cost</th>
            <th className="px-3 py-2 text-right">TDS Base</th>
            <th className="px-3 py-2 text-right">TDS</th>
            <th className="px-3 py-2 text-right">After TDS</th>
            <th className="px-3 py-2 text-right">Profit</th>
            <th className="px-3 py-2 text-right">Margin</th>
            <th className="px-3 py-2 text-left">Why / Calculation</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {options.map(option => {
            const calc = assumedSplit(option)
            return (
            <tr key={option.model} className={option.valid ? '' : 'opacity-80'}>
              <td className="px-3 py-2 font-bold text-slate-800">{option.model}</td>
              <td className="px-3 py-2 text-right">{money(calc.client_revenue)}</td>
              <td className="px-3 py-2 text-right">{money(calc.trainer_cost)}</td>
              <td className="px-3 py-2 text-right">{money(calc.tds_base_amount)}</td>
              <td className="px-3 py-2 text-right">{money(calc.tds)}</td>
              <td className="px-3 py-2 text-right">{money(calc.net_amount_after_tds)}</td>
              <td className="px-3 py-2 text-right font-bold text-green-700">{money(calc.clahan_gross_profit)}</td>
              <td className="px-3 py-2 text-right">{pct(calc.profit_margin_percent)}</td>
              <td className="max-w-sm px-3 py-2 text-left text-xs leading-5 text-slate-600">
                <div className="space-y-1">
                  {calculationLines(option).map(line => <p key={line}>{line}</p>)}
                </div>
                <p className="mt-1 font-bold text-blue-700">Client commercial allocation: 30% Clahan, 70% trainer, with TDS calculated on trainer share.</p>
                {!option.within_client_budget && <p className="mt-1 font-bold text-red-700">Above client budget.</p>}
                <p className="mt-1 text-slate-500">{option.reason}</p>
              </td>
            </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function BestOptionSummary({ trainer }) {
  const option = trainer.recommended_option || {}
  if (!option.model) return null
  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <p>Best: <strong>{option.model}</strong></p>
        <p>Revenue: <strong>{money(option.client_revenue)}</strong></p>
        <p>Profit: <strong className="text-green-700">{profitText(option)}</strong></p>
        <p>Margin: <strong>{marginText(option)}</strong></p>
      </div>
      <p className="mt-2 leading-5 text-slate-600">
        {option.model === 'TOTAL_70_30'
          ? `Total 70/30 allocation: Clahan share is ${money(option.clahan_gross_profit)} and trainer share is ${money(option.trainer_cost)}. TDS ${pct(option.tds_rate_percent)} is calculated separately on trainer share.`
          : `Day-wise 70/30 allocation: client revenue ${money(option.client_revenue)}, trainer share ${money(option.trainer_cost)}, and Clahan share ${money(option.clahan_gross_profit)}. TDS ${money(option.tds)} is separate.`}
      </p>
      {option.why_selected && <p className="mt-1 font-semibold text-blue-700">{option.why_selected}</p>}
    </div>
  )
}

function RequirementDetail({ active, onClose }) {
  if (!active) return null
  const activeReq = active.requirement || {}
  const activeTrainer = active.recommended_trainer || {}

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/45 p-3 backdrop-blur-sm sm:p-5">
      <section className="mx-auto flex h-full max-w-7xl flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div>
            <p className="text-xs font-bold uppercase text-slate-400">Clahan Recommendation</p>
            <h2 className="mt-1 text-xl font-bold text-slate-900">{requirementTitle(active)}</h2>
            <p className="mt-1 text-sm text-slate-500">
              {clean(activeReq.client_name || activeReq.client_company) || 'Client'} · {clean(activeReq.mode || activeReq.delivery_mode) || 'Mode pending'} · {clean(activeReq.location || activeReq.preferred_location) || 'Location pending'}
            </p>
            <p className="mt-1 text-sm font-semibold text-slate-700">
              {requirementMetaLine(activeReq, active.recommended_commercial)}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge tone={needsTrainerCommercial(active) ? 'amber' : active.negotiation_required ? 'amber' : 'green'}>
              {needsTrainerCommercial(active) ? 'Confirm Rate' : active.negotiation_required ? 'Negotiate' : 'Proceed'}
            </StatusBadge>
            <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50 hover:text-slate-900" aria-label="Close commercial analysis">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="grid gap-3 md:grid-cols-4">
            <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Trainer</p><p className="font-bold text-slate-900">{activeTrainer.qtr || '-'} {activeTrainer.trainer_name || ''}</p></div>
            <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Commercial</p><p className="font-bold text-blue-700">{active.recommended_commercial?.model || '-'}</p></div>
            <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Profit</p><p className="font-bold text-green-700">{money(active.recommended_commercial?.clahan_gross_profit)}</p></div>
            <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Margin</p><p className="font-bold text-slate-900">{pct(active.recommended_commercial?.profit_margin_percent)}</p></div>
          </div>

          <p className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm leading-6 text-blue-900">{active.explanation}</p>

          <DateBudgetBreakdown active={active} />

          <div className="mt-5">
            <div className="mb-2 flex items-center gap-2"><ArrowDownUp className="h-4 w-4 text-slate-500" /><h3 className="font-bold text-slate-900">Commercial Comparison</h3></div>
            <CommercialTable options={activeTrainer.commercial_options || []} active={active} />
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {(active.qtr_trainers || []).map(trainer => (
              <div key={trainer.qtr} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-bold text-slate-900">{trainer.qtr} - {trainer.trainer_name}</p>
                  {trainer.qtr === activeTrainer.qtr && <CheckCircle2 className="h-4 w-4 text-green-600" />}
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
                  <p>Skill: <strong>{pct(trainer.skill_match)}</strong></p>
                  <p>Exp: <strong>{trainer.experience_years || 0} yrs</strong></p>
                  <p>Rate: <strong>{trainer.trainer_day_rate ? `${money(trainer.trainer_day_rate)}/day` : 'Pending'}</strong></p>
                  <p>Best: <strong>{trainer.recommended_option?.model || '-'}</strong></p>
                </div>
                <BestOptionSummary trainer={trainer} />
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}

export default function CommercialAnalysis() {
  const [items, setItems] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('profit')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getCommercialAnalyses({ limit: 100, status: 'all' })
      .then(res => {
        if (cancelled) return
        const rows = res.data.items || []
        setItems(rows)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    getCommercialAnalysis(selectedId).then(res => { if (!cancelled) setDetail(res.data) })
    return () => { cancelled = true }
  }, [selectedId])

  const rows = useMemo(() => {
    const q = query.toLowerCase()
    return items
      .filter(item => {
        const req = item.requirement || {}
        const haystack = [req.client_name, req.client_company, req.technology_needed, req.domain].join(' ').toLowerCase()
        if (q && !haystack.includes(q)) return false
        if (filter === 'negotiation') return item.negotiation_required
        if (filter === 'short') return Number(item.recommended_commercial?.duration_days || 0) <= 7
        if (filter === 'long') return Number(item.recommended_commercial?.duration_days || 0) > 7
        if (filter === 'confirmed') return item.requirement_confirmed
        return true
      })
      .sort((a, b) => {
        if (sort === 'margin') return (b.recommended_commercial?.profit_margin_percent || 0) - (a.recommended_commercial?.profit_margin_percent || 0)
        if (sort === 'budget') return (b.negotiation?.current_client_budget || 0) - (a.negotiation?.current_client_budget || 0)
        return (b.recommended_commercial?.clahan_gross_profit || 0) - (a.recommended_commercial?.clahan_gross_profit || 0)
      })
  }, [filter, items, query, sort])

  const active = detail || items.find(item => item.requirement?.requirement_id === selectedId)
  const activeReq = active?.requirement || {}
  const activeTrainer = active?.recommended_trainer || {}

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4"><BadgeIndianRupee className="mb-2 h-5 w-5 text-blue-600" /><p className="text-xs text-slate-500">Highest Profit</p><p className="text-xl font-bold text-slate-900">{money(rows[0]?.recommended_commercial?.clahan_gross_profit)}</p></div>
        <div className="rounded-lg border border-slate-200 bg-white p-4"><TrendingUp className="mb-2 h-5 w-5 text-green-600" /><p className="text-xs text-slate-500">Best Margin</p><p className="text-xl font-bold text-slate-900">{pct(Math.max(0, ...rows.map(r => r.recommended_commercial?.profit_margin_percent || 0)))}</p></div>
        <div className="rounded-lg border border-slate-200 bg-white p-4"><Users className="mb-2 h-5 w-5 text-indigo-600" /><p className="text-xs text-slate-500">Requirements</p><p className="text-xl font-bold text-slate-900">{rows.length}</p></div>
        <div className="rounded-lg border border-slate-200 bg-white p-4"><AlertTriangle className="mb-2 h-5 w-5 text-amber-600" /><p className="text-xs text-slate-500">Need Negotiation</p><p className="text-xl font-bold text-slate-900">{rows.filter(r => r.negotiation_required).length}</p></div>
      </div>

      <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-3">
        <div className="search-bar min-w-64 flex-1"><Search className="h-4 w-4" /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search client, company, technology..." /></div>
        <select className="rounded-lg border border-slate-200 px-3 text-sm font-semibold" value={filter} onChange={e => setFilter(e.target.value)}>
          <option value="all">All</option><option value="confirmed">Confirmed</option><option value="short">Short duration</option><option value="long">Long duration</option><option value="negotiation">Negotiation required</option>
        </select>
        <select className="rounded-lg border border-slate-200 px-3 text-sm font-semibold" value={sort} onChange={e => setSort(e.target.value)}>
          <option value="profit">Highest profit</option><option value="margin">Highest margin</option><option value="budget">Client budget</option>
        </select>
      </div>

      <div>
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {loading && <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm font-semibold text-slate-500">Loading commercial analysis...</div>}
          {rows.map(item => (
            <RequirementCard key={item.requirement?.requirement_id} item={item} selected={selectedId === item.requirement?.requirement_id} onSelect={() => setSelectedId(item.requirement?.requirement_id)} />
          ))}
        </div>

        {false && active && (
          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-xs">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-bold uppercase text-slate-400">Clahan Recommendation</p>
                <h2 className="mt-1 text-xl font-bold text-slate-900">{requirementTitle(active)}</h2>
                <p className="mt-1 text-sm text-slate-500">{clean(activeReq.client_name || activeReq.client_company) || 'Client'} · {clean(activeReq.mode || activeReq.delivery_mode) || 'Mode pending'} · {clean(activeReq.location || activeReq.preferred_location) || 'Location pending'}</p>
              </div>
              <StatusBadge tone={needsTrainerCommercial(active) ? 'amber' : active.negotiation_required ? 'amber' : 'green'}>
                {needsTrainerCommercial(active) ? 'Confirm Rate' : active.negotiation_required ? 'Negotiate' : 'Proceed'}
              </StatusBadge>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-4">
              <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Trainer</p><p className="font-bold text-slate-900">{activeTrainer.qtr || '-'} {activeTrainer.trainer_name || ''}</p></div>
              <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Commercial</p><p className="font-bold text-blue-700">{active.recommended_commercial?.model || '-'}</p></div>
              <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Profit</p><p className="font-bold text-green-700">{money(active.recommended_commercial?.clahan_gross_profit)}</p></div>
              <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Margin</p><p className="font-bold text-slate-900">{pct(active.recommended_commercial?.profit_margin_percent)}</p></div>
            </div>

            <p className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm leading-6 text-blue-900">{active.explanation}</p>

            <div className="mt-5">
              <div className="mb-2 flex items-center gap-2"><ArrowDownUp className="h-4 w-4 text-slate-500" /><h3 className="font-bold text-slate-900">Commercial Comparison</h3></div>
              <CommercialTable options={activeTrainer.commercial_options || []} active={active} />
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-2">
              {(active.qtr_trainers || []).map(trainer => (
                <div key={trainer.qtr} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-bold text-slate-900">{trainer.qtr} - {trainer.trainer_name}</p>
                    {trainer.qtr === activeTrainer.qtr && <CheckCircle2 className="h-4 w-4 text-green-600" />}
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
                    <p>Skill: <strong>{pct(trainer.skill_match)}</strong></p>
                    <p>Exp: <strong>{trainer.experience_years || 0} yrs</strong></p>
                    <p>Rate: <strong>{money(trainer.trainer_day_rate)}/day</strong></p>
                    <p>Best: <strong>{trainer.recommended_option?.model || '-'}</strong></p>
                  </div>
                  <BestOptionSummary trainer={trainer} />
                </div>
              ))}
            </div>
          </section>
        )}
        {active && <RequirementDetail active={active} onClose={() => { setSelectedId(''); setDetail(null) }} />}
      </div>
    </div>
  )
}
