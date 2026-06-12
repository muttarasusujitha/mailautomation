import { useEffect, useMemo, useState } from 'react'
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

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-500">{label}</p>
          <p className="mt-1 text-2xl font-bold text-slate-950">{value}</p>
        </div>
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700">
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

export default function InterviewSchedules() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.get('/interview-schedules', { params: { limit: 200 } })
      setItems(res.data.schedules || [])
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
    if (!term) return items
    return items.filter(item => [
      item.domain,
      item.requirement_id,
      item.client_name,
      item.client_company,
      item.client_email,
      item.trainer_name,
      item.trainer_email,
      item.date_time_text,
      item.meet_link,
    ].some(value => String(value || '').toLowerCase().includes(term)))
  }, [items, query])

  const withLinks = items.filter(item => item.meet_link).length
  const clientSent = items.filter(item => item.client_email_sent).length
  const trainerSent = items.filter(item => item.trainer_email_sent).length

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <CalendarCheck className="h-6 w-6 text-cyan-700" />
            Interview Scheduled
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Clahan internal view for scheduled client and trainer meetings.
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

      <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search domain, client, trainer, email, requirement..."
            className="min-w-0 flex-1 border-0 bg-transparent text-sm outline-none"
          />
        </label>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-5 text-sm font-semibold text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading scheduled interviews
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center">
          <CalendarCheck className="mx-auto h-10 w-10 text-slate-300" />
          <p className="mt-3 font-semibold text-slate-700">No scheduled interviews found</p>
          <p className="mt-1 text-sm text-slate-500">Once client confirms a slot and Meet link is created, it will appear here.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map(item => (
            <article key={`${item.email_id}-${item.calendar_event_id}`} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-lg font-bold text-slate-950">{item.domain || 'Training'}</h2>
                    <span className="rounded-md border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs font-bold text-cyan-700">
                      {statusLabel(item.status)}
                    </span>
                    {item.requirement_id && (
                      <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-bold text-slate-600">
                        {item.requirement_id}
                      </span>
                    )}
                  </div>
                  <div className="mt-3 grid gap-2 lg:grid-cols-2">
                    <ContactLine icon={UserRound} label="Client" value={item.client_name || item.client_company} />
                    <ContactLine icon={Mail} label="Client Mail" value={item.client_email} />
                    <ContactLine icon={Users} label="Trainer" value={item.trainer_name} />
                    <ContactLine icon={Mail} label="Trainer Mail" value={item.trainer_email} />
                  </div>
                </div>

                <div className="flex flex-col gap-2 lg:min-w-80 lg:items-end">
                  <div className="inline-flex w-fit items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-bold text-blue-700">
                    <Clock className="h-4 w-4" />
                    {item.date_time_text || formatDate(item.start_iso)}
                  </div>
                  {item.meet_link ? (
                    <a
                      href={item.meet_link}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex w-fit items-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-bold text-white hover:bg-emerald-700"
                    >
                      <Video className="h-4 w-4" />
                      Open Meeting Link
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  ) : (
                    <span className="inline-flex w-fit items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-bold text-amber-700">
                      <Link2 className="h-4 w-4" />
                      Meeting link pending
                    </span>
                  )}
                </div>
              </div>

              <div className="mt-4 grid gap-2 border-t border-slate-100 pt-3 text-xs font-semibold text-slate-500 md:grid-cols-4">
                <span>Slot Ref: {item.slot_ref || '-'}</span>
                <span>Timezone: {item.timezone || '-'}</span>
                <span>Client Sent: {item.client_email_sent ? 'Yes' : 'No'}</span>
                <span>Trainer Sent: {item.trainer_email_sent ? 'Yes' : 'No'}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
