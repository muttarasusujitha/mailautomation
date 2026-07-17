import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  CalendarCheck,
  CheckCircle2,
  Clock,
  ExternalLink,
  Link2,
  Loader2,
  Mail,
  RefreshCw,
  Search,
  UserRound,
  Users,
  Video,
} from 'lucide-react'
import api from '../utils/api'

const SCHEDULE_ENDPOINTS = [
  '/interview-schedules',
  '/interview-reminders/interview-schedules',
]

const PIPELINE_STAGES = [
  ['scheduled', 'Scheduled', 'Interview captured'],
  ['client_email_sent', 'Client Mail', 'Client notified'],
  ['trainer_email_sent', 'Trainer Mail', 'Trainer notified'],
  ['meet_link', 'Meet Link', 'Join link ready'],
  ['upcoming', 'Date State', 'Upcoming or done'],
]

function formatDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return String(value)
  }
}

function statusLabel(value = '') {
  return String(value || 'scheduled').replaceAll('_', ' ')
}

function dateState(item = {}) {
  const raw = item.start_iso || item.interview_at || item.sent_at || item.created_at
  if (!raw) return 'pending'
  const time = new Date(raw).getTime()
  if (Number.isNaN(time)) return 'pending'
  return time >= Date.now() ? 'upcoming' : 'completed'
}

function stageStates(item = {}) {
  return {
    scheduled: item.interview_scheduled || item.date_time_text || item.start_iso ? 'done' : 'pending',
    client_email_sent: item.client_email_sent ? 'done' : 'pending',
    trainer_email_sent: item.trainer_email_sent ? 'done' : 'pending',
    meet_link: item.meet_link ? 'done' : 'pending',
    upcoming: dateState(item) === 'completed' ? 'done' : dateState(item) === 'upcoming' ? 'ready' : 'pending',
  }
}

function progressCount(item = {}) {
  return Object.values(stageStates(item)).filter(value => value === 'done').length
}

function progressPercent(item = {}) {
  return Math.round((progressCount(item) / PIPELINE_STAGES.length) * 100)
}

function currentStageLabel(item = {}) {
  const states = stageStates(item)
  const pending = PIPELINE_STAGES.find(([key]) => states[key] !== 'done')
  return pending ? pending[1] : 'Completed'
}

function normalizeSchedule(item = {}) {
  const calendar = item.calendar_event || {}
  const isClientMail = String(item.mail_type || '').startsWith('client_')
  const email = item.trainer_email || item.email || item.to_email || ''
  const clientEmail = item.client_email || (isClientMail ? item.to_email : '')
  const trainerEmail = item.trainer_email || (!isClientMail ? email : '')

  return {
    ...item,
    domain: item.domain || item.technology || item.technology_needed || item.subject || 'Training',
    client_name: item.client_name || item.client_company || (isClientMail ? 'Client' : ''),
    client_email: clientEmail,
    trainer_name: item.trainer_name || item.name || '',
    trainer_email: trainerEmail,
    date_time_text: item.date_time_text || item.interview_date || '',
    meet_link: item.meet_link || item.interview_link || calendar.meet_link || calendar.html_link || '',
    start_iso: item.start_iso || item.interview_at || calendar.start || item.sent_at || item.created_at,
    timezone: item.timezone || calendar.timezone || '',
    slot_ref: item.slot_ref || item.client_slot_email_id || item.email_id || '',
    calendar_event_id: item.calendar_event_id || calendar.event_id || item.email_id || '',
    client_email_sent: Boolean(item.client_email_sent || isClientMail),
    trainer_email_sent: Boolean(item.trainer_email_sent || item.mail_type === 'mail4'),
  }
}

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-500">{label}</p>
          <p className="mt-1 text-2xl font-bold text-slate-950">{value}</p>
        </div>
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
          <Icon className="h-5 w-5" />
        </span>
      </div>
    </div>
  )
}

function ContactLine({ icon: Icon, label, value }) {
  return (
    <div className="flex min-w-0 items-center gap-2 text-sm">
      <Icon className="h-4 w-4 shrink-0 text-slate-400" />
      <span className="shrink-0 font-semibold text-slate-500">{label}</span>
      <span className="min-w-0 truncate text-slate-900">{value || '-'}</span>
    </div>
  )
}

function SummaryTile({ label, value, sub, tone = 'slate' }) {
  const tones = {
    blue: 'border-blue-200 bg-blue-50 text-blue-700',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }
  return (
    <div className={clsx('rounded-lg border p-3', tones[tone] || tones.slate)}>
      <p className="text-[11px] font-bold uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-1 truncate text-lg font-black">{value}</p>
      {sub && <p className="mt-0.5 truncate text-xs opacity-70">{sub}</p>}
    </div>
  )
}

function StageRail({ item }) {
  const states = stageStates(item)
  return (
    <div className="overflow-x-auto pb-2 [scrollbar-gutter:stable]">
      <div className="flex min-w-max items-start gap-0">
        {PIPELINE_STAGES.map(([key, title, sub], index) => {
          const state = states[key] || 'pending'
          const done = state === 'done'
          const ready = state === 'ready'
          return (
            <div key={key} className="flex items-start">
              <div className="flex w-[112px] flex-col items-center text-center">
                <span className={clsx(
                  'flex h-7 w-7 items-center justify-center rounded-full border text-xs font-black shadow-sm',
                  done ? 'border-blue-500 bg-blue-600 text-white' :
                    ready ? 'border-emerald-300 bg-emerald-50 text-emerald-700' :
                      'border-amber-300 bg-amber-50 text-amber-700'
                )}>
                  {done ? <CheckCircle2 className="h-4 w-4" /> : index + 1}
                </span>
                <p className={clsx('mt-1.5 text-[11px] font-black', done ? 'text-blue-700' : ready ? 'text-emerald-700' : 'text-slate-600')}>
                  {title}
                </p>
                <p className="mt-0.5 max-w-[98px] text-[10px] leading-3 text-slate-400">{sub}</p>
              </div>
              {index < PIPELINE_STAGES.length - 1 && (
                <div className={clsx('mt-3 h-0.5 w-10 rounded-full', done ? 'bg-blue-500' : 'bg-slate-200')} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ScheduleListItem({ item, active, onClick }) {
  const percent = progressPercent(item)
  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full rounded-xl border p-3 text-left transition hover:border-blue-200 hover:bg-white hover:shadow-sm',
        active ? 'border-blue-300 bg-white shadow-md ring-2 ring-blue-500/10' : 'border-slate-200 bg-white/80'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-950">{item.domain}</p>
          <p className="mt-1 truncate text-xs text-slate-500">{item.client_name || item.client_email || 'Client pending'}</p>
        </div>
        <span className={clsx(
          'shrink-0 rounded-full border px-2 py-1 text-xs font-bold',
          percent >= 80 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : percent >= 50 ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-amber-200 bg-amber-50 text-amber-700'
        )}>
          {percent}%
        </span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-blue-600" style={{ width: `${percent}%` }} />
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="truncate text-xs font-bold text-slate-600">{currentStageLabel(item)}</p>
        <span className="shrink-0 text-xs font-bold text-slate-400">{formatDate(item.start_iso)}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {item.requirement_id && (
          <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-[11px] font-bold text-blue-700">
            {item.requirement_id}
          </span>
        )}
        {item.meet_link && (
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-bold text-emerald-700">
            Link ready
          </span>
        )}
      </div>
      <p className="mt-3 truncate text-xs font-semibold text-slate-500">
        Trainer: {item.trainer_name || item.trainer_email || '-'}
      </p>
    </button>
  )
}

export default function InterviewSchedules() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [selectedKey, setSelectedKey] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      let lastError
      for (const [index, endpoint] of SCHEDULE_ENDPOINTS.entries()) {
        try {
          const res = await api.get(endpoint, { params: { limit: 200 } })
          const schedules = res.data.schedules || []
          if (schedules.length || index === SCHEDULE_ENDPOINTS.length - 1) {
            const normalized = schedules.map(normalizeSchedule)
            setItems(normalized)
            setSelectedKey(prev => prev || `${normalized[0]?.email_id || ''}-${normalized[0]?.calendar_event_id || ''}`)
            return
          }
        } catch (err) {
          lastError = err
        }
      }
      throw lastError
    } catch (err) {
      toast.error(err.message || 'Could not load interview schedules')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter(item => {
      if (filter === 'upcoming' && dateState(item) !== 'upcoming') return false
      if (filter === 'completed' && dateState(item) !== 'completed') return false
      if (filter === 'missing-link' && item.meet_link) return false
      if (!term) return true
      return [
      item.domain,
      item.requirement_id,
      item.client_name,
      item.client_company,
      item.client_email,
      item.trainer_name,
      item.trainer_email,
      item.date_time_text,
      item.meet_link,
      ].some(value => String(value || '').toLowerCase().includes(term))
    })
  }, [items, query, filter])

  const selected = useMemo(
    () => filtered.find(item => `${item.email_id || ''}-${item.calendar_event_id || ''}` === selectedKey) || filtered[0] || null,
    [filtered, selectedKey]
  )

  const withLinks = items.filter(item => item.meet_link).length
  const clientSent = items.filter(item => item.client_email_sent).length
  const trainerSent = items.filter(item => item.trainer_email_sent).length
  const upcomingCount = items.filter(item => dateState(item) === 'upcoming').length

  const filters = [
    ['all', 'All', items.length],
    ['upcoming', 'Upcoming', upcomingCount],
    ['completed', 'Completed', items.filter(item => dateState(item) === 'completed').length],
    ['missing-link', 'Missing Link', items.filter(item => !item.meet_link).length],
  ]

  return (
    <div className="min-w-0 space-y-5 overflow-x-hidden animate-fade-in">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-bold uppercase tracking-wide text-blue-700 shadow-sm">
            <CalendarCheck className="h-3.5 w-3.5" /> Interview Pipeline
          </div>
          <h1 className="mt-3 page-title">Interview Schedule Board</h1>
          <p className="mt-1 text-sm text-slate-500">
            Client and trainer interview flow with meeting links, mail state, and schedule readiness in one board.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="btn-secondary w-fit text-sm"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <Stat icon={CalendarCheck} label="Scheduled Meetings" value={items.length} />
        <Stat icon={Video} label="Meeting Links" value={withLinks} />
        <Stat icon={Mail} label="Client Mails Sent" value={clientSent} />
        <Stat icon={Users} label="Trainer Mails Sent" value={trainerSent} />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="flex items-center gap-2 overflow-x-auto pb-1 [scrollbar-gutter:stable]">
          {filters.map(([key, label, count]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={clsx(
                'shrink-0 rounded-xl border px-3 py-2 text-sm font-bold',
                filter === key ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
              )}
            >
              {label} <span className="ml-1 opacity-75">{count}</span>
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-5 text-sm font-semibold text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading scheduled interviews
        </div>
      ) : (
        <div className="grid min-w-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search client, trainer, domain..."
                className="h-11 w-full rounded-full border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </div>
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm font-bold text-slate-950">{filtered.length} interview{filtered.length === 1 ? '' : 's'}</p>
            </div>
            <div className="mt-3 max-h-[72vh] space-y-3 overflow-y-auto pr-1 [scrollbar-gutter:stable]">
              {filtered.length ? filtered.map(item => {
                const key = `${item.email_id || ''}-${item.calendar_event_id || ''}`
                return (
                  <ScheduleListItem
                    key={key}
                    item={item}
                    active={selected && key === `${selected.email_id || ''}-${selected.calendar_event_id || ''}`}
                    onClick={() => setSelectedKey(key)}
                  />
                )
              }) : (
                <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">
                  No scheduled interviews found for this filter.
                </div>
              )}
            </div>
          </aside>

          <section className="min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm">
            {!selected ? (
              <div className="flex min-h-[620px] items-center justify-center text-sm text-slate-500">
                Select an interview schedule.
              </div>
            ) : (
              <div className="flex min-h-[720px] min-w-0 flex-col">
                <header className="border-b border-slate-200 p-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">{selected.domain}</span>
                        {selected.requirement_id && <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">{selected.requirement_id}</span>}
                        <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-bold capitalize text-emerald-700">{statusLabel(selected.status)}</span>
                      </div>
                      <h2 className="mt-3 text-xl font-bold text-slate-950">{selected.client_name || selected.client_email || 'Client Meeting'}</h2>
                      <p className="mt-1 text-sm text-slate-500">{selected.trainer_name || selected.trainer_email || 'Trainer details pending'}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {selected.meet_link ? (
                        <a href={selected.meet_link} target="_blank" rel="noreferrer" className="btn-primary text-sm">
                          <Video className="h-4 w-4" />
                          Open Meeting
                          <ExternalLink className="h-4 w-4" />
                        </a>
                      ) : (
                        <span className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-bold text-amber-700">
                          <Link2 className="h-4 w-4" /> Meeting link pending
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="mt-5 grid gap-3 md:grid-cols-4">
                    <SummaryTile label="Readiness" value={`${progressPercent(selected)}%`} sub={currentStageLabel(selected)} tone="blue" />
                    <SummaryTile label="Date State" value={dateState(selected)} sub={selected.date_time_text || formatDate(selected.start_iso)} tone={dateState(selected) === 'upcoming' ? 'emerald' : 'slate'} />
                    <SummaryTile label="Client Mail" value={selected.client_email_sent ? 'Sent' : 'Pending'} sub={selected.client_email || 'client email'} tone={selected.client_email_sent ? 'emerald' : 'amber'} />
                    <SummaryTile label="Trainer Mail" value={selected.trainer_email_sent ? 'Sent' : 'Pending'} sub={selected.trainer_email || 'trainer email'} tone={selected.trainer_email_sent ? 'emerald' : 'amber'} />
                  </div>
                  <div className="mt-5">
                    <StageRail item={selected} />
                  </div>
                </header>

                <div className="grid min-w-0 flex-1 gap-5 p-5 2xl:grid-cols-[360px_minmax(0,1fr)]">
                  <aside className="min-w-0 space-y-4">
                    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Interview Slot</p>
                        <Clock className="h-4 w-4 text-blue-600" />
                      </div>
                      <p className="mt-3 text-lg font-black text-blue-950">{selected.date_time_text || formatDate(selected.start_iso)}</p>
                      <p className="mt-1 text-xs font-semibold text-blue-700">{selected.timezone || 'Timezone not captured'}</p>
                    </div>

                    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                      <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Contacts</p>
                      <div className="mt-3 space-y-2">
                        <ContactLine icon={UserRound} label="Client" value={selected.client_name || selected.client_company} />
                        <ContactLine icon={Mail} label="Client Mail" value={selected.client_email} />
                        <ContactLine icon={Users} label="Trainer" value={selected.trainer_name} />
                        <ContactLine icon={Mail} label="Trainer Mail" value={selected.trainer_email} />
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                      <p className="text-xs font-bold uppercase tracking-wide text-slate-400">References</p>
                      <div className="mt-3 space-y-2 text-sm">
                        <p className="flex justify-between gap-3"><span className="text-slate-500">Slot Ref</span><strong className="break-words text-right text-slate-900">{selected.slot_ref || '-'}</strong></p>
                        <p className="flex justify-between gap-3"><span className="text-slate-500">Calendar</span><strong className="break-words text-right text-slate-900">{selected.calendar_event_id || '-'}</strong></p>
                        <p className="flex justify-between gap-3"><span className="text-slate-500">Email ID</span><strong className="break-words text-right text-slate-900">{selected.email_id || '-'}</strong></p>
                      </div>
                    </div>
                  </aside>

                  <div className="min-w-0 rounded-xl border border-slate-200 bg-slate-50">
                    <div className="flex items-center justify-between border-b border-slate-200 p-4">
                      <div>
                        <p className="text-sm font-bold text-slate-950">Interview Communication Snapshot</p>
                        <p className="mt-0.5 text-xs text-slate-500">Mail status, meeting link, and schedule metadata for this interview.</p>
                      </div>
                      <CalendarCheck className="h-5 w-5 text-slate-400" />
                    </div>
                    <div className="space-y-3 p-4">
                      <div className="rounded-lg border border-white bg-white p-4 shadow-sm">
                        <p className="text-sm font-bold text-slate-950">{selected.subject || 'Interview schedule'}</p>
                        <pre className="mt-2 max-w-full whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-600 [overflow-wrap:anywhere]">{selected.body || 'No mail body captured.'}</pre>
                      </div>
                      {selected.meet_link && (
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-800">
                          Meeting link ready: <a className="break-all underline" href={selected.meet_link} target="_blank" rel="noreferrer">{selected.meet_link}</a>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
