import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  CalendarCheck,
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

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function meetingTime(item = {}) {
  return item.start_iso || item.interview_at || item.sent_at || item.created_at || ''
}

function meetingState(item = {}) {
  const raw = meetingTime(item)
  if (!raw) return 'pending'
  const time = new Date(raw).getTime()
  if (Number.isNaN(time)) return 'pending'
  const diff = time - Date.now()
  if (diff > 5 * 60 * 1000) return 'upcoming'
  if (diff > -90 * 60 * 1000) return 'starting'
  return 'completed'
}

function normalizeSchedule(item = {}) {
  const calendar = item.calendar_event || {}
  const isClientMail = String(item.mail_type || '').startsWith('client_')
  const email = item.trainer_email || item.email || item.to_email || ''
  return {
    ...item,
    domain: item.domain || item.technology || item.technology_needed || item.subject || 'Training',
    client_name: item.client_name || item.client_company || (isClientMail ? 'Client' : ''),
    client_email: item.client_email || (isClientMail ? item.to_email : ''),
    trainer_name: item.trainer_name || item.name || '',
    trainer_email: item.trainer_email || (!isClientMail ? email : ''),
    date_time_text: item.date_time_text || item.interview_date || '',
    meet_link: item.meet_link || item.interview_link || calendar.meet_link || calendar.html_link || '',
    start_iso: item.start_iso || item.interview_at || calendar.start || item.sent_at || item.created_at,
    timezone: item.timezone || calendar.timezone || '',
    calendar_event_id: item.calendar_event_id || calendar.event_id || item.email_id || '',
  }
}

function openMeeting(link) {
  if (!link) {
    toast.error('Meeting link is not available yet')
    return
  }
  window.open(link, '_blank', 'noopener,noreferrer')
}

function ContactLine({ icon: Icon, label, value }) {
  return (
    <div className="flex min-w-0 items-center gap-2 text-sm">
      <Icon className="h-4 w-4 shrink-0 text-slate-400" />
      <span className="shrink-0 font-semibold text-slate-500">{label}</span>
      <span className="min-w-0 truncate text-slate-950">{value || '-'}</span>
    </div>
  )
}

function MeetingRow({ item, active, onClick }) {
  const state = meetingState(item)
  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full rounded-lg border p-3 text-left transition hover:border-blue-200 hover:bg-white',
        active ? 'border-blue-300 bg-blue-50 ring-1 ring-blue-100' : 'border-slate-200 bg-white'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-950">{item.trainer_name || item.trainer_email || 'Selected trainer'}</p>
          <p className="mt-1 truncate text-xs font-semibold text-slate-500">{item.domain}</p>
        </div>
        <span className={clsx(
          'rounded-lg px-2 py-1 text-xs font-bold capitalize',
          state === 'starting' ? 'bg-emerald-50 text-emerald-700' :
            state === 'upcoming' ? 'bg-blue-50 text-blue-700' :
              state === 'completed' ? 'bg-slate-100 text-slate-500' :
                'bg-amber-50 text-amber-700'
        )}>
          {state}
        </span>
      </div>
      <p className="mt-3 truncate text-xs font-semibold text-slate-600">{item.date_time_text || formatDate(item.start_iso)}</p>
      <p className="mt-1 truncate text-xs text-slate-400">{item.client_name || item.client_email || 'Client'}</p>
    </button>
  )
}

export default function InterviewSchedules() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('upcoming')
  const [selectedKey, setSelectedKey] = useState('')
  const [notified, setNotified] = useState({})

  const load = async () => {
    setLoading(true)
    try {
      let lastError
      for (const [index, endpoint] of SCHEDULE_ENDPOINTS.entries()) {
        try {
          const res = await api.get(endpoint, { params: { limit: 200 } })
          const schedules = (res.data.schedules || []).map(normalizeSchedule)
          if (schedules.length || index === SCHEDULE_ENDPOINTS.length - 1) {
            setItems(schedules)
            setSelectedKey(prev => prev || `${schedules[0]?.email_id || ''}-${schedules[0]?.calendar_event_id || ''}`)
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

  useEffect(() => { load() }, [])

  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {})
    }
  }, [])

  useEffect(() => {
    const timer = setInterval(() => {
      const nextNotified = { ...notified }
      items.forEach(item => {
        const raw = meetingTime(item)
        const time = new Date(raw).getTime()
        if (!raw || Number.isNaN(time)) return
        const key = `${item.email_id || ''}-${item.calendar_event_id || ''}-${raw}`
        const diff = time - Date.now()
        if (diff > 0 && diff <= 5 * 60 * 1000 && !nextNotified[key]) {
          nextNotified[key] = true
          const title = 'Meeting starts in 5 minutes'
          const body = `${item.trainer_name || 'Trainer'} with ${item.client_name || item.client_email || 'client'}`
          toast.success(`${title}: ${body}`, { duration: 10000 })
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(title, { body })
          }
        }
      })
      setNotified(nextNotified)
    }, 30000)
    return () => clearInterval(timer)
  }, [items, notified])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter(item => {
      if (filter !== 'all' && meetingState(item) !== filter) return false
      if (!term) return true
      return [
        item.domain,
        item.requirement_id,
        item.client_name,
        item.client_email,
        item.trainer_name,
        item.trainer_email,
        item.date_time_text,
      ].some(value => String(value || '').toLowerCase().includes(term))
    })
  }, [items, query, filter])

  const selected = useMemo(
    () => filtered.find(item => `${item.email_id || ''}-${item.calendar_event_id || ''}` === selectedKey) || filtered[0] || null,
    [filtered, selectedKey]
  )

  const counts = {
    all: items.length,
    upcoming: items.filter(item => meetingState(item) === 'upcoming').length,
    starting: items.filter(item => meetingState(item) === 'starting').length,
    completed: items.filter(item => meetingState(item) === 'completed').length,
  }

  return (
    <div className="min-w-0 space-y-5 overflow-x-hidden animate-fade-in">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-bold uppercase tracking-wide text-blue-700 shadow-sm">
            <CalendarCheck className="h-3.5 w-3.5" /> Interview Meetings
          </div>
          <h1 className="mt-3 page-title">Interview Meeting Board</h1>
          <p className="mt-1 text-sm text-slate-500">Selected trainers, client/trainer emails, meeting date, and host join controls.</p>
        </div>
        <button onClick={load} disabled={loading} className="btn-secondary w-fit text-sm">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        {[
          ['All', counts.all, 'all'],
          ['Upcoming', counts.upcoming, 'upcoming'],
          ['Starting Now', counts.starting, 'starting'],
          ['Completed', counts.completed, 'completed'],
        ].map(([label, count, key]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={clsx('rounded-lg border p-4 text-left shadow-sm transition', filter === key ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50')}
          >
            <p className="text-sm font-semibold text-slate-500">{label}</p>
            <p className="mt-1 text-2xl font-bold text-slate-950">{count}</p>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-5 text-sm font-semibold text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading scheduled interviews
        </div>
      ) : (
        <div className="grid min-w-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="min-w-0 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search trainer, client, domain..."
                className="h-11 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </div>
            <p className="mt-4 text-sm font-bold text-slate-950">{filtered.length} selected interview{filtered.length === 1 ? '' : 's'}</p>
            <div className="mt-3 max-h-[72vh] space-y-3 overflow-y-auto pr-1 [scrollbar-gutter:stable]">
              {filtered.length ? filtered.map(item => {
                const key = `${item.email_id || ''}-${item.calendar_event_id || ''}`
                return (
                  <MeetingRow
                    key={key}
                    item={item}
                    active={selected && key === `${selected.email_id || ''}-${selected.calendar_event_id || ''}`}
                    onClick={() => setSelectedKey(key)}
                  />
                )
              }) : (
                <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">
                  No interviews found.
                </div>
              )}
            </div>
          </aside>

          <section className="min-w-0 rounded-lg border border-slate-200 bg-white shadow-sm">
            {!selected ? (
              <div className="flex min-h-[520px] items-center justify-center text-sm text-slate-500">
                Select an interview.
              </div>
            ) : (
              <div className="min-w-0 p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">{selected.domain}</span>
                      {selected.requirement_id && <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">{selected.requirement_id}</span>}
                      <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-bold capitalize text-emerald-700">{meetingState(selected)}</span>
                    </div>
                    <h2 className="mt-3 text-2xl font-bold text-slate-950">{selected.trainer_name || selected.trainer_email || 'Selected Trainer'}</h2>
                    <p className="mt-1 text-sm text-slate-500">{selected.client_name || selected.client_email || 'Client'}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => openMeeting(selected.meet_link)} disabled={!selected.meet_link} className="btn-primary text-sm disabled:opacity-50">
                      <Video className="h-4 w-4" />
                      Start Meeting
                      <ExternalLink className="h-4 w-4" />
                    </button>
                    <button onClick={() => openMeeting(selected.meet_link)} disabled={!selected.meet_link} className="btn-secondary text-sm disabled:opacity-50">
                      <Users className="h-4 w-4" />
                      Host / Admit People
                    </button>
                  </div>
                </div>

                <div className="mt-5 grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
                  <div className="space-y-4">
                    <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Interview Date & Time</p>
                        <Clock className="h-4 w-4 text-blue-600" />
                      </div>
                      <p className="mt-3 text-lg font-black text-blue-950">{selected.date_time_text || formatDate(selected.start_iso)}</p>
                      <p className="mt-1 text-xs font-semibold text-blue-700">{selected.timezone || 'Timezone not captured'}</p>
                    </div>

                    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                      <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Client & Trainer</p>
                      <div className="mt-3 space-y-2">
                        <ContactLine icon={UserRound} label="Client" value={selected.client_name || selected.client_company} />
                        <ContactLine icon={Mail} label="Client Mail" value={selected.client_email} />
                        <ContactLine icon={Users} label="Trainer" value={selected.trainer_name} />
                        <ContactLine icon={Mail} label="Trainer Mail" value={selected.trainer_email} />
                      </div>
                    </div>
                  </div>

                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-bold text-slate-950">Google Meet</p>
                        <p className="mt-0.5 text-xs text-slate-500">Open as host, then admit client and trainer from the Google Meet waiting room.</p>
                      </div>
                      <Video className="h-5 w-5 text-slate-400" />
                    </div>
                    {selected.meet_link ? (
                      <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-800">
                        <p className="mb-2">Meeting link ready</p>
                        <a className="break-all underline" href={selected.meet_link} target="_blank" rel="noreferrer">{selected.meet_link}</a>
                      </div>
                    ) : (
                      <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-800">
                        <Link2 className="mr-1 inline h-4 w-4" />
                        Meeting link is pending.
                      </div>
                    )}
                    <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
                      <p className="font-bold text-slate-950">Reminder</p>
                      <p className="mt-1">This page shows a browser/toast notification 5 minutes before the interview starts.</p>
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
