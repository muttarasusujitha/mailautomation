import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  AlertTriangle, BriefcaseBusiness, CalendarCheck, CalendarDays, CheckCircle2, Clock,
  ExternalLink, FileText, IndianRupee, Link2, Loader2, Mail, MapPin, RefreshCw,
  Search, Send, Users, Video, X
} from 'lucide-react'
import api from '../utils/api'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'pending_approval', label: 'Pending' },
  { key: 'auto_sent', label: 'Auto Sent' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'spam', label: 'Spam' },
]

const STATUS_META = {
  pending_approval: { label: 'Pending Approval', tone: 'amber' },
  auto_sent: { label: 'Auto Sent', tone: 'emerald' },
  approved: { label: 'Approved', tone: 'blue' },
  rejected: { label: 'Rejected', tone: 'red' },
  spam: { label: 'Spam', tone: 'slate' },
}

function fmtDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function confidenceTone(score) {
  if (score >= 0.9) return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (score >= 0.7) return 'text-amber-700 bg-amber-50 border-amber-200'
  return 'text-red-700 bg-red-50 border-red-200'
}

function statusClass(tone = 'slate') {
  const tones = {
    amber: 'bg-amber-50 text-amber-700 border-amber-200',
    emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    blue: 'bg-blue-50 text-blue-700 border-blue-200',
    red: 'bg-red-50 text-red-700 border-red-200',
    slate: 'bg-slate-50 text-slate-600 border-slate-200',
  }
  return tones[tone] || tones.slate
}

function updateStatusClass(status = '') {
  if (status === 'confirmed_scheduled') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'trainer_email_failed' || status === 'calendar_failed') return 'border-red-200 bg-red-50 text-red-700'
  if (status === 'needs_manual_review' || status === 'trainer_email_missing') return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function valueOrDash(value) {
  return value === undefined || value === null || value === '' ? '-' : value
}

function Stat({ icon: Icon, label, value, tone = 'blue' }) {
  const tones = {
    blue: 'text-blue-600 bg-blue-50',
    amber: 'text-amber-600 bg-amber-50',
    emerald: 'text-emerald-600 bg-emerald-50',
    slate: 'text-slate-600 bg-slate-100',
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-500">{label}</span>
        <span className={clsx('flex h-9 w-9 items-center justify-center rounded-lg', tones[tone])}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
    </div>
  )
}

function ClientUpdatePanel({ updates = [], loading, onRetry, retryingId = '' }) {
  const latest = updates.slice(0, 5)
  const scheduled = updates.filter(item => item.confirmation_status === 'confirmed_scheduled').length
  const waiting = updates.filter(item => ['sent', 'auto_sent'].includes(item.confirmation_status)).length
  const review = updates.filter(item =>
    ['needs_manual_review', 'calendar_failed', 'trainer_email_failed', 'trainer_email_missing'].includes(item.confirmation_status)
  ).length

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Client Updates</p>
            <h2 className="mt-1 text-lg font-bold text-slate-950">Slot confirmation and Meet scheduling</h2>
            <p className="mt-1 text-sm text-slate-500">
              Track the handoff after trainer slots are shared with each client.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg border border-slate-200 px-3 py-2">
              <p className="text-lg font-bold text-slate-950">{waiting}</p>
              <p className="text-[11px] font-semibold uppercase text-slate-400">Waiting</p>
            </div>
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
              <p className="text-lg font-bold text-emerald-700">{scheduled}</p>
              <p className="text-[11px] font-semibold uppercase text-emerald-600">Scheduled</p>
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
              <p className="text-lg font-bold text-amber-700">{review}</p>
              <p className="text-[11px] font-semibold uppercase text-amber-600">Review</p>
            </div>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 p-4 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading client updates
        </div>
      ) : latest.length === 0 ? (
        <div className="p-4 text-sm text-slate-500">
          No client slot updates yet. Once trainer slots are sent to clients, they will appear here.
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {latest.map(item => {
            const canRetry = ['calendar_failed', 'trainer_email_failed', 'client_email_failed'].includes(item.confirmation_status)
            return (
            <div key={item.email_id} className="grid gap-3 p-4 lg:grid-cols-[1.2fr_1fr_auto] lg:items-center">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-semibold text-slate-950">{item.technology || 'Training'}</p>
                  {item.slot_ref && (
                    <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-bold text-slate-600">{item.slot_ref}</span>
                  )}
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  {item.client_company || item.client_name || item.to_email || 'Client'} {'->'} {item.trainer_name || 'Trainer'}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700">
                  <CalendarCheck className="h-3.5 w-3.5" />
                  {item.confirmed_slot?.date_time_text || item.confirmed_slot?.start_iso || 'Awaiting client time'}
                </span>
                {item.meet_link && (
                  <a
                    href={item.meet_link}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700"
                  >
                    <Video className="h-3.5 w-3.5" /> Meet
                  </a>
                )}
                {item.requirement_id && (
                  <span className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-600">
                    <Link2 className="h-3.5 w-3.5" /> {item.requirement_id}
                  </span>
                )}
                {item.client_email_sent && (
                  <span className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                    <Mail className="h-3.5 w-3.5" /> Client notified
                  </span>
                )}
                {item.trainer_email_sent && (
                  <span className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Trainer notified
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                <span className={clsx('w-fit rounded-lg border px-2.5 py-1 text-xs font-bold capitalize', updateStatusClass(item.confirmation_status))}>
                  {(item.confirmation_status || 'sent').replaceAll('_', ' ')}
                </span>
                {canRetry && (
                  <button
                    onClick={() => onRetry?.(item)}
                    disabled={retryingId === item.email_id}
                    className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {retryingId === item.email_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    Retry
                  </button>
                )}
              </div>
            </div>
          )})}
        </div>
      )}
    </section>
  )
}

function DetailModal({ request, onClose }) {
  const [trainerMails, setTrainerMails] = useState([])
  const [loadingMails, setLoadingMails] = useState(false)

  useEffect(() => {
    let cancelled = false
    const loadTrainerMails = async () => {
      if (!request?.requirement_id) {
        setTrainerMails([])
        return
      }
      setLoadingMails(true)
      try {
        const res = await api.get('/emails', {
          params: { requirement_id: request.requirement_id, limit: 200 },
        })
        if (!cancelled) setTrainerMails(res.data.emails || [])
      } catch {
        if (!cancelled) setTrainerMails([])
      } finally {
        if (!cancelled) setLoadingMails(false)
      }
    }
    loadTrainerMails()
    return () => { cancelled = true }
  }, [request?.requirement_id])

  if (!request) return null
  const extracted = request.extracted || {}
  const reply = request.generated_reply || {}
  const status = STATUS_META[request.status] || { label: request.status || 'Unknown', tone: 'slate' }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900">{extracted.technology_needed || request.subject || 'Client Request'}</h2>
              <span className={clsx('rounded-full border px-2.5 py-1 text-xs font-semibold', statusClass(status.tone))}>
                {status.label}
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-500">{request.from_name || request.from_email} - {request.from_email}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Requirement</p>
              <div className="mt-3 space-y-2 text-sm text-slate-700">
                <p><strong>Technology:</strong> {valueOrDash(extracted.technology_needed)}</p>
                <p><strong>Duration:</strong> {extracted.duration_days ? `${extracted.duration_days} days` : valueOrDash(extracted.duration_hours && `${extracted.duration_hours} hours`)}</p>
                <p><strong>Mode:</strong> {valueOrDash(extracted.mode)}</p>
                <p><strong>Participants:</strong> {valueOrDash(extracted.participant_count)}</p>
                <p><strong>Location:</strong> {valueOrDash(extracted.location)}</p>
                <p><strong>Dates:</strong> {valueOrDash(extracted.preferred_dates || extracted.timeline_start)}</p>
                <p><strong>Budget:</strong> {valueOrDash(extracted.budget_total || extracted.budget_per_day)}</p>
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 md:col-span-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Original Email</p>
              <p className="mt-2 text-sm font-semibold text-slate-900">{request.subject}</p>
              <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-sm leading-6 text-slate-700">
                {request.clean_body || request.raw_body || 'No email body captured.'}
              </pre>
            </div>
          </div>

          <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Generated Reply</p>
            <p className="mt-2 text-sm font-semibold text-slate-900">{reply.subject || 'No reply generated'}</p>
            <pre className="mt-3 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">
              {reply.body || 'No generated reply available.'}
            </pre>
          </div>

          <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Trainer Mails For This Request</p>
                <p className="mt-1 text-sm text-slate-500">
                  {request.requirement_id
                    ? `Requirement ${request.requirement_id}`
                    : 'No requirement has been created from this client email yet.'}
                </p>
              </div>
              {request.requirement_id && (
                <button
                  onClick={() => window.open(`/shortlist1?requirement_id=${encodeURIComponent(request.requirement_id)}`, '_blank')}
                  className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                >
                  Open Shortlist
                </button>
              )}
            </div>

            {!request.requirement_id ? (
              <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm text-slate-500">
                Approve/process this client request first. After a requirement is created and trainer mails are sent, they will show here.
              </div>
            ) : loadingMails ? (
              <div className="mt-4 flex items-center gap-2 rounded-lg bg-slate-50 p-4 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading trainer mails...
              </div>
            ) : trainerMails.length === 0 ? (
              <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm text-slate-500">
                No trainer mails sent yet for this client request.
              </div>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-2">Trainer</th>
                      <th className="px-3 py-2">Mail Type</th>
                      <th className="px-3 py-2">Subject</th>
                      <th className="px-3 py-2">Email</th>
                      <th className="px-3 py-2">WhatsApp</th>
                      <th className="px-3 py-2">Reply</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {trainerMails.map(mail => {
                      const whatsapp = mail.whatsapp_summary || {}
                      return (
                        <tr key={mail.email_id}>
                          <td className="px-3 py-3 align-top">
                            <p className="font-semibold text-slate-900">{mail.trainer_name || '-'}</p>
                            <p className="text-xs text-slate-500">{mail.to_email}</p>
                          </td>
                          <td className="px-3 py-3 align-top">
                            <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
                              {mail.mail_type || '-'}
                            </span>
                          </td>
                          <td className="max-w-xs px-3 py-3 align-top text-slate-700">
                            <p className="line-clamp-2">{mail.subject || '-'}</p>
                            <p className="mt-1 text-xs text-slate-400">{fmtDate(mail.sent_at || mail.created_at)}</p>
                          </td>
                          <td className="px-3 py-3 align-top">
                            <span className={clsx('rounded-full border px-2 py-1 text-xs font-semibold',
                              mail.status === 'sent' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'
                            )}>
                              {mail.status || 'unknown'}
                            </span>
                          </td>
                          <td className="px-3 py-3 align-top">
                            <span className={clsx('rounded-full border px-2 py-1 text-xs font-semibold',
                              whatsapp.success ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'
                            )}>
                              {whatsapp.status || (whatsapp.success ? 'queued' : 'not sent')}
                            </span>
                            {(whatsapp.to_number || whatsapp.from_number) && (
                              <div className="mt-1 max-w-[180px] space-y-0.5 text-xs text-slate-500">
                                {whatsapp.to_number && <p className="break-all">To: {whatsapp.to_number}</p>}
                                {whatsapp.from_number && <p className="break-all">From: {whatsapp.from_number}</p>}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-3 align-top">
                            <span className={clsx('rounded-full border px-2 py-1 text-xs font-semibold',
                              mail.reply_received ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-slate-200 bg-slate-50 text-slate-500'
                            )}>
                              {mail.reply_received ? 'Received' : 'Waiting'}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function ClientRequests() {
  const navigate = useNavigate()
  const [requests, setRequests] = useState([])
  const [clientUpdates, setClientUpdates] = useState([])
  const [stats, setStats] = useState({})
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [retryingUpdateId, setRetryingUpdateId] = useState('')
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null)

  const loadRequests = async () => {
    setLoading(true)
    try {
      const [requestsRes, updatesRes] = await Promise.all([
        api.get('/inbox', {
          params: { status: filter === 'all' ? '' : filter, limit: 200 },
        }),
        api.get('/client-updates', { params: { limit: 25 } }),
      ])
      setRequests(requestsRes.data.emails || [])
      setStats(requestsRes.data.stats || {})
      setClientUpdates(updatesRes.data.updates || [])
    } catch (e) {
      toast.error(e.message || 'Could not load client requests')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRequests()
  }, [filter])

  const syncNow = async () => {
    setSyncing(true)
    try {
      const res = await api.post('/gmail/sync-now?limit=50')
      toast.success(`Inbox checked: ${res.data?.processed_count || 0} new request(s) processed`)
      await loadRequests()
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Inbox sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const retryClientUpdate = async item => {
    if (!item?.email_id || retryingUpdateId) return
    setRetryingUpdateId(item.email_id)
    try {
      const res = await api.post(`/client-updates/${item.email_id}/retry-schedule`)
      if (res.data?.status === 'confirmed_scheduled') {
        toast.success('Calendar created and both client/trainer notifications sent')
      } else {
        toast.error(res.data?.error || `Retry ended with status: ${res.data?.status || 'unknown'}`)
      }
      await loadRequests()
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Calendar retry failed')
    } finally {
      setRetryingUpdateId('')
    }
  }

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return requests
    return requests.filter(item => {
      const extracted = item.extracted || {}
      return [
        item.from_name,
        item.from_email,
        item.subject,
        extracted.client_company,
        extracted.technology_needed,
        extracted.location,
        item.requirement_id,
      ].some(value => String(value || '').toLowerCase().includes(term))
    })
  }, [requests, query])

  const statValues = useMemo(() => {
    const autoSent = Number(stats.auto_sent || 0)
    const pending = Number(stats.pending_approval || 0)
    const created = Number(stats.requirements_created || 0)
    return [
      { icon: Mail, label: 'Today', value: stats.today || 0, tone: 'blue' },
      { icon: AlertTriangle, label: 'Pending', value: pending, tone: 'amber' },
      { icon: Send, label: 'Auto Sent', value: autoSent, tone: 'emerald' },
      { icon: CheckCircle2, label: 'Requirements Created', value: created, tone: 'slate' },
    ]
  }, [stats])

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <BriefcaseBusiness className="h-6 w-6 text-blue-500" /> Client Requests
          </h1>
          <p className="mt-1 text-sm text-slate-500">All training inquiries captured from the client inbox.</p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button onClick={syncNow} disabled={syncing} className="btn-secondary text-sm disabled:opacity-50">
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Check Inbox Now
          </button>
          <button onClick={() => navigate('/inbox')} className="btn-secondary text-sm">
            <FileText className="h-4 w-4" /> Review Drafts
          </button>
          <button onClick={() => navigate('/client-mail-pipeline')} className="btn-secondary text-sm">
            <Send className="h-4 w-4" /> Mail Pipeline
          </button>
          <button onClick={() => navigate('/admin')} className="btn-primary text-sm">
            <ExternalLink className="h-4 w-4" /> Gmail Settings
          </button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {statValues.map(item => <Stat key={item.label} {...item} />)}
      </div>

      <ClientUpdatePanel
        updates={clientUpdates}
        loading={loading}
        onRetry={retryClientUpdate}
        retryingId={retryingUpdateId}
      />

      <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-2">
          {FILTERS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={clsx(
                'rounded-lg px-3 py-2 text-sm font-semibold transition',
                filter === tab.key
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="relative w-full lg:w-80">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search client, tech, location..."
            className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10"
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-slate-400">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading client requests
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-16 text-center text-slate-400">
            <Mail className="mx-auto mb-3 h-10 w-10 opacity-40" />
            <p className="font-medium text-slate-500">No client requests found</p>
            <p className="mt-1 text-sm">Connect the client inbox and click Check Inbox Now.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Client</th>
                  <th className="px-4 py-3">Requirement</th>
                  <th className="px-4 py-3">Details</th>
                  <th className="px-4 py-3">Budget</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {filtered.map(item => {
                  const extracted = item.extracted || {}
                  const status = STATUS_META[item.status] || { label: item.status || 'Unknown', tone: 'slate' }
                  const confidence = Number(item.confidence ?? extracted.confidence ?? 0)
                  return (
                    <tr key={item.email_id} className="hover:bg-slate-50">
                      <td className="px-4 py-4 align-top">
                        <p className="font-semibold text-slate-900">{item.from_name || item.from_email || 'Client'}</p>
                        <p className="mt-1 text-xs text-slate-500">{item.from_email}</p>
                        <p className="mt-1 flex items-center gap-1 text-xs text-slate-400">
                          <Clock className="h-3 w-3" /> {fmtDate(item.received_at)}
                        </p>
                      </td>
                      <td className="px-4 py-4 align-top">
                        <p className="font-semibold text-slate-900">{extracted.technology_needed || 'Technology pending'}</p>
                        <p className="mt-1 line-clamp-2 max-w-xs text-xs text-slate-500">{extracted.email_summary || item.subject}</p>
                        {item.requirement_id && <p className="mt-1 text-xs font-semibold text-blue-600">{item.requirement_id}</p>}
                      </td>
                      <td className="px-4 py-4 align-top">
                        <div className="flex flex-wrap gap-1.5">
                          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2 py-1 text-xs text-slate-600">
                            <CalendarDays className="h-3 w-3" /> {extracted.duration_days ? `${extracted.duration_days} days` : valueOrDash(extracted.preferred_dates || extracted.timeline_start)}
                          </span>
                          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2 py-1 text-xs text-slate-600">
                            <Users className="h-3 w-3" /> {valueOrDash(extracted.participant_count)}
                          </span>
                          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2 py-1 text-xs text-slate-600">
                            <MapPin className="h-3 w-3" /> {valueOrDash(extracted.location || extracted.mode)}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-4 align-top">
                        <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-700">
                          <IndianRupee className="h-3 w-3" />
                          {valueOrDash(extracted.budget_total || extracted.budget_per_day)}
                        </span>
                      </td>
                      <td className="px-4 py-4 align-top">
                        <div className="flex flex-col items-start gap-2">
                          <span className={clsx('rounded-full border px-2 py-1 text-xs font-semibold', statusClass(status.tone))}>
                            {status.label}
                          </span>
                          <span className={clsx('rounded-full border px-2 py-1 text-xs font-semibold', confidenceTone(confidence))}>
                            {Math.round(confidence * 100)}% confidence
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right align-top">
                        <div className="flex justify-end gap-2">
                          <button onClick={() => setSelected(item)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                            View
                          </button>
                          <button onClick={() => navigate('/inbox')} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700">
                            Review
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <DetailModal request={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
