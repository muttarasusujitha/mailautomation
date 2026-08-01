import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Inbox,
  Loader2,
  Mail,
  MessageSquareText,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  UsersRound,
} from 'lucide-react'
import api from '../utils/api'

const STAGES = [
  ['received', 'Client Request', 'Inbox received'],
  ['extracted', 'Details Filled', 'Domain and fields'],
  ['reply', 'Clahan Reply', 'Reply template'],
  ['autofind', 'Auto Finding', 'Search decision'],
  ['shortlist', 'Top 5 Shortlist', 'Trainer ranking'],
  ['shortlist1', 'Shortlist1', 'Trainer mail flow'],
]

const DETAIL_FIELDS = [
  ['technology_needed', 'Domain / Technology'],
  ['duration_text', 'Training duration'],
  ['training_dates', 'Preferred dates'],
  ['timing', 'Daily timings'],
  ['audience_level', 'Audience level'],
  ['mode', 'Training mode'],
  ['budget_per_day', 'Budget per day'],
  ['participant_count', 'Participants'],
]

function clean(value, fallback = '-') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function fmtDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function pickExtracted(item = {}) {
  return item.extracted || item.client_email_doc?.extracted || {}
}

function pickTechnology(item = {}) {
  const extracted = pickExtracted(item)
  return clean(
    extracted.technology_needed ||
      item.technology_needed ||
      item.domain ||
      item.technology ||
      extracted.technology ||
      extracted.domain,
    'Training'
  )
}

function missingDetails(item = {}) {
  const extracted = pickExtracted(item)
  return Array.isArray(extracted.needs_clarification) ? extracted.needs_clarification.filter(Boolean) : []
}

function hasDomain(item = {}) {
  const extracted = pickExtracted(item)
  return Boolean(extracted.technology_needed || item.technology_needed || item.domain || extracted.technology || extracted.domain)
}

function trainerMailStats(item = {}) {
  const automation = item.mail_automation || item.client_email_doc?.mail_automation || {}
  const trainerMail = automation.trainer_mail || automation
  return {
    sent: Number(trainerMail.sent || automation.sent || 0),
    total: Number(trainerMail.total || automation.total || 0),
    error: trainerMail.error || automation.error || item.trainer_automation_error || '',
  }
}

function clientReplyStats(item = {}) {
  const automation = item.mail_automation || item.client_email_doc?.mail_automation || {}
  const reply = automation.client_reply || {}
  return {
    sent: Boolean(reply.sent || item.reply_sent || item.client_email_doc?.reply_sent || item.reply_status === 'auto_sent'),
    to: reply.to || item.from_email || item.client_email || item.client_email_doc?.from_email || '',
    subject: reply.subject || item.subject || '',
    error: reply.error || item.reply_error || item.auto_send_error || '',
    at: item.reply_sent_at || item.auto_sent_at || item.client_email_doc?.reply_sent_at || item.client_email_doc?.auto_sent_at || '',
  }
}

function shortlistTrainers(item = {}) {
  return item.shortlist?.top_trainers || item.top_trainers || []
}

function stepState({ done = false, active = false, blocked = false } = {}) {
  if (done) return 'done'
  if (blocked) return 'blocked'
  if (active) return 'active'
  return 'waiting'
}

function stepTone(state) {
  if (state === 'done') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (state === 'active') return 'border-blue-200 bg-blue-50 text-blue-800'
  if (state === 'blocked') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-slate-200 bg-slate-50 text-slate-500'
}

function stepIcon(state) {
  if (state === 'done') return <CheckCircle2 className="h-4 w-4" />
  if (state === 'active') return <Loader2 className="h-4 w-4 animate-spin" />
  if (state === 'blocked') return <AlertCircle className="h-4 w-4" />
  return <Clock3 className="h-4 w-4" />
}

function buildClientSteps(item = {}) {
  const missing = missingDetails(item)
  const trainers = shortlistTrainers(item)
  const mailStats = trainerMailStats(item)
  const replyStats = clientReplyStats(item)
  const hasGeneratedReply = Boolean(item.ai_reply || item.draft_reply || item.generated_reply?.body || item.client_email_doc?.ai_reply)
  const requirementDone = Boolean(item.requirement_id)
  const domainDone = hasDomain(item)
  const autoStatus = item.trainer_automation_status || item.client_email_doc?.trainer_automation_status || ''
  const automationTried = Boolean(item.mail_automation?.trainer_mail || item.client_email_doc?.mail_automation?.trainer_mail || autoStatus)
  const mailSent = mailStats.sent > 0
  const hasMailError = Boolean(mailStats.error)

  return [
    {
      key: 'client_received',
      title: 'Client Mail Received',
      status: stepState({ done: true }),
      detail: clean(item.from_email || item.client_email_doc?.from_email, 'Client email captured'),
      meta: fmtDate(item.received_at || item.created_at || item.client_email_doc?.received_at),
    },
    {
      key: 'details_filled',
      title: 'Details Auto-Filled',
      status: stepState({ done: domainDone, blocked: !domainDone }),
      detail: domainDone ? `${pickTechnology(item)}${missing.length ? `, ${missing.length} field(s) still missing` : ', enough to proceed'}` : 'Domain / technology not detected',
      meta: missing.length ? `Missing: ${missing.join(', ')}` : 'Ready for trainer search',
    },
    {
      key: 'reply_prepared',
      title: 'Clahan Reply Prepared',
      status: stepState({ done: hasGeneratedReply || replyStats.sent, active: domainDone && !hasGeneratedReply && !replyStats.sent }),
      detail: hasGeneratedReply || replyStats.sent ? clean(item.reply_template_key || item.client_email_doc?.reply_template_key, 'Reply template selected') : 'Waiting for AI reply template',
      meta: replyStats.subject,
    },
    {
      key: 'client_reply_sent',
      title: 'Client Reply Sent',
      status: stepState({ done: replyStats.sent, active: hasGeneratedReply && !replyStats.sent, blocked: Boolean(replyStats.error) }),
      detail: replyStats.sent ? `Sent to ${clean(replyStats.to, 'client')}` : replyStats.error || 'Waiting to send client acknowledgement',
      meta: fmtDate(replyStats.at),
    },
    {
      key: 'requirement_created',
      title: 'Requirement Created',
      status: stepState({ done: requirementDone, active: replyStats.sent && !requirementDone }),
      detail: requirementDone ? clean(item.requirement_id, 'Requirement ready') : 'Waiting for requirement record',
      meta: requirementDone ? 'Used by Shortlist1' : '',
    },
    {
      key: 'resume_search',
      title: 'Uploaded Resume Search',
      status: stepState({ done: trainers.length > 0, active: requirementDone && !trainers.length && !hasMailError, blocked: hasMailError }),
      detail: trainers.length ? `${trainers.length} trainer(s) ranked from uploaded resumes` : hasMailError || 'Searching uploaded trainer resumes',
      meta: `${mailStats.total || trainers.length || 0} candidate(s) available`,
    },
    {
      key: 'mail1_trainers',
      title: 'Mail1 To Trainers',
      status: stepState({ done: mailSent, active: trainers.length > 0 && !mailSent && !hasMailError, blocked: hasMailError }),
      detail: mailSent ? `${mailStats.sent} trainer mail(s) sent` : hasMailError || 'Waiting to send Mail1',
      meta: mailStats.total ? `${mailStats.sent}/${mailStats.total} sent` : '',
    },
    {
      key: 'shortlist1_handoff',
      title: 'Shortlist1 Takeover',
      status: stepState({ done: mailSent, active: false, blocked: !hasDomain(item) }),
      detail: mailSent
        ? 'Open trainer pipeline in Shortlist1 and continue Mail1 replies from there'
        : trainers.length > 0
        ? 'Shortlist ready. Continue Mail1 from Shortlist1 to send outreach'
        : 'Waiting for top 5 before Shortlist1 takeover',
      meta: autoStatus ? `Status: ${autoStatus}` : 'Mail1 is managed by Shortlist1',
    },
  ]
}

function stageState(item = {}, key) {
  const extracted = pickExtracted(item)
  const missing = missingDetails(item)
  const trainers = shortlistTrainers(item)
  const autoStatus = item.trainer_automation_status || item.client_email_doc?.trainer_automation_status || ''
  const mailStats = trainerMailStats(item)
  const mailSent = mailStats.sent > 0
  const hasReply = Boolean(item.ai_reply || item.draft_reply || item.generated_reply?.body || item.client_email_doc?.ai_reply)

  if (key === 'received') return 'done'
  if (key === 'extracted') return hasDomain(item) ? (missing.length ? 'partial' : 'done') : 'blocked'
  if (key === 'reply') return hasReply || item.reply_sent || item.reply_status === 'auto_sent' ? 'done' : hasDomain(item) ? 'ready' : 'blocked'
  if (key === 'autofind') {
    if (['started', 'no_trainers_emailed', 'failed', 'no_profiles_found'].includes(autoStatus)) return autoStatus === 'failed' ? 'blocked' : 'done'
    if (item.pending_trainer_automation || item.client_authorized_trainer_search || hasDomain(item)) return 'ready'
    return 'blocked'
  }
  if (key === 'shortlist') return trainers.length ? 'done' : hasDomain(item) ? 'ready' : 'blocked'
  if (key === 'shortlist1') return mailSent ? 'done' : trainers.length ? 'waiting' : hasDomain(item) ? 'ready' : 'blocked'
  return 'blocked'
}

function stageTone(state) {
  if (state === 'done') return 'border-emerald-500 bg-emerald-600 text-white'
  if (state === 'partial') return 'border-amber-300 bg-amber-50 text-amber-700'
  if (state === 'ready') return 'border-blue-300 bg-blue-50 text-blue-700'
  return 'border-slate-200 bg-slate-100 text-slate-400'
}

function searchText(item = {}) {
  const extracted = pickExtracted(item)
  return [
    item.email_id,
    item.requirement_id,
    item.subject,
    item.from_email,
    item.from_name,
    item.client_name,
    item.client_email,
    item.status,
    pickTechnology(item),
    extracted.client_name,
    extracted.client_email,
  ].filter(Boolean).join(' ').toLowerCase()
}

function normalizePipelineItem(email = {}, pipelineItems = []) {
  const requirementId = email.requirement_id || ''
  const pipeline = pipelineItems.find(item => item.requirement_id && item.requirement_id === requirementId) || {}
  return {
    ...pipeline,
    ...email,
    client_email_doc: email,
    requirement_id: requirementId || pipeline.requirement_id || '',
    shortlist: pipeline.shortlist || {},
    messages: pipeline.messages || [],
  }
}

function StageRail({ item }) {
  const steps = buildClientSteps(item)
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 shadow-sm">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-bold text-slate-950">Client Pipeline Steps</p>
          <p className="mt-1 text-sm text-slate-500">Track the request from client mail receipt through requirement creation, trainer search, and Shortlist1 takeover. This finishes the shortlist prep, then Shortlist1 handles the rest of Mail1 and trainer outreach.</p>
        </div>
        <span className="inline-flex items-center justify-center rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {steps.filter(step => step.status === 'done').length}/{steps.length} completed
        </span>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        {steps.map((step, index) => {
          const badgeText = step.status === 'done'
            ? 'Done'
            : step.status === 'active'
            ? 'Processing'
            : step.status === 'blocked'
            ? 'Needs attention'
            : 'Waiting'

          return (
            <div key={step.key} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span className={clsx('flex h-9 w-9 items-center justify-center rounded-full border text-sm font-black', stepTone(step.status))}>
                    {stepIcon(step.status)}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold text-slate-950">{`${index + 1}. ${step.title}`}</p>
                    {step.meta ? <p className="mt-1 text-xs text-slate-500">{step.meta}</p> : null}
                  </div>
                </div>
                <span className={clsx(
                  'rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase',
                  step.status === 'done' ? 'bg-emerald-100 text-emerald-700' :
                  step.status === 'active' ? 'bg-blue-100 text-blue-700' :
                  step.status === 'blocked' ? 'bg-amber-100 text-amber-700' :
                  'bg-slate-100 text-slate-500'
                )}>
                  {badgeText}
                </span>
              </div>
              <p className="mt-3 text-sm leading-6 text-slate-600">{step.detail}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DetailGrid({ item }) {
  const extracted = pickExtracted(item)
  const aliases = {
    duration_text: extracted.duration_text || (extracted.duration_days ? `${extracted.duration_days} days` : ''),
    training_dates: extracted.training_dates || extracted.preferred_dates || extracted.timeline_start || '',
    budget_per_day: extracted.budget_per_day || extracted.budget_total || extracted.budget_range || '',
  }
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {DETAIL_FIELDS.map(([key, label]) => {
        const value = key === 'technology_needed' ? pickTechnology(item) : clean(aliases[key] || extracted[key], '')
        const filled = Boolean(value)
        return (
          <div key={key} className={clsx('rounded-lg border p-3', filled ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50')}>
            <p className={clsx('text-[11px] font-bold uppercase tracking-wide', filled ? 'text-emerald-700' : 'text-amber-700')}>{label}</p>
            <p className="mt-1 min-h-[20px] break-words text-sm font-bold text-slate-900">{filled ? value : 'Missing'}</p>
          </div>
        )
      })}
    </div>
  )
}

function RequestCard({ item, active, onClick }) {
  const missing = missingDetails(item)
  const mailStats = trainerMailStats(item)
  const trainers = shortlistTrainers(item)
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'w-full rounded-xl border p-3 text-left transition hover:border-blue-200 hover:bg-white hover:shadow-sm',
        active ? 'border-blue-300 bg-white shadow-md ring-2 ring-blue-500/10' : 'border-slate-200 bg-white/80'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-black text-slate-950">{pickTechnology(item)}</p>
          <p className="mt-1 truncate text-xs text-slate-500">{clean(item.from_name || item.client?.name || item.from_email, 'Client')}</p>
        </div>
        <span className={clsx(
          'shrink-0 rounded-full border px-2 py-1 text-[11px] font-bold',
          trainers.length > 0 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : hasDomain(item) ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-amber-200 bg-amber-50 text-amber-700'
        )}>
          {trainers.length > 0 ? 'Shortlist1 ready' : hasDomain(item) ? 'Ready' : 'Missing'}
        </span>
      </div>
      <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{item.subject || item.body_snippet || item.clean_body || 'Client request'}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-600">
          Missing {missing.length}
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-600">
          Top {trainers.length || 0}
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-600">
          Shortlist1
        </span>
      </div>
    </button>
  )
}

function Conversation({ item }) {
  const messages = item.messages || []
  const initialBody = item.clean_body || item.body || item.body_snippet || ''
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white p-4">
        <div>
          <p className="text-sm font-bold text-slate-950">Client Conversation</p>
          <p className="mt-0.5 text-xs text-slate-500">Inbox request and later client replies stay visible here.</p>
        </div>
        <MessageSquareText className="h-5 w-5 text-slate-400" />
      </div>
      <div className="max-h-[440px] space-y-3 overflow-y-auto p-4">
        {initialBody && (
          <div className="mr-auto max-w-[86%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Original Client Request</p>
            <p className="mt-1 break-words text-sm font-semibold text-slate-900">{item.subject}</p>
            <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-600">{initialBody}</pre>
          </div>
        )}
        {(item.ai_reply || item.draft_reply || item.generated_reply?.body) && (
          <div className="ml-auto max-w-[86%] rounded-2xl rounded-br-sm border border-blue-200 bg-blue-600 p-4 text-white shadow-sm">
            <p className="text-xs font-bold uppercase tracking-wide text-blue-100">Clahan Reply Template</p>
            <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm leading-6 text-blue-50">{item.ai_reply || item.draft_reply || item.generated_reply?.body}</pre>
          </div>
        )}
        {messages.map((message, index) => (
          <div
            key={`${message.email_id || index}-${message.type}`}
            className={clsx(
              'max-w-[86%] rounded-2xl border p-4 shadow-sm',
              message.direction === 'received' ? 'mr-auto rounded-bl-sm border-slate-200 bg-white' : 'ml-auto rounded-br-sm border-blue-200 bg-blue-600 text-white'
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className={clsx('text-xs font-bold uppercase tracking-wide', message.direction === 'received' ? 'text-slate-400' : 'text-blue-100')}>
                {message.label || message.type || 'Message'}
              </p>
              <span className={clsx('text-xs font-semibold', message.direction === 'received' ? 'text-slate-400' : 'text-blue-100')}>{fmtDate(message.at)}</span>
            </div>
            <p className={clsx('mt-1 break-words text-sm font-semibold', message.direction === 'received' ? 'text-slate-900' : 'text-white')}>{message.subject}</p>
            <pre className={clsx('mt-2 whitespace-pre-wrap break-words font-sans text-sm leading-6', message.direction === 'received' ? 'text-slate-600' : 'text-blue-50')}>{message.body || 'No body captured.'}</pre>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ClientPipeline() {
  const navigate = useNavigate()
  const [items, setItems] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [processing, setProcessing] = useState(false)

  const selected = useMemo(
    () => items.find(item => item.email_id === selectedId) || items[0] || null,
    [items, selectedId]
  )

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items
    return items.filter(item => searchText(item).includes(q))
  }, [items, query])

  const stats = useMemo(() => {
    const total = items.length
    const domainReady = items.filter(hasDomain).length
    const autofind = items.filter(item => item.pending_trainer_automation || item.client_authorized_trainer_search || item.trainer_automation_status === 'started').length
    const handoff = items.filter(item => shortlistTrainers(item).length > 0 || item.requirement_id).length
    return { total, domainReady, autofind, handoff }
  }, [items])

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [inboxRes, pipelineRes] = await Promise.all([
        api.get('/inbox', { params: { status: 'all', limit: 200 } }),
        api.get('/client-pipeline', { params: { limit: 200 } }),
      ])
      const pipelineItems = pipelineRes.data?.pipeline || []
      const inboxEmails = inboxRes.data?.emails || []
      const merged = inboxEmails.map(email => normalizePipelineItem(email, pipelineItems))
      setItems(merged)
      if (!merged.some(item => item.email_id === selectedId)) {
        setSelectedId(merged[0]?.email_id || '')
      }
    } catch (e) {
      toast.error(e.message || 'Could not load client pipeline')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(false)
  }, [])

  const syncGmail = async () => {
    setSyncing(true)
    try {
      const res = await api.post('/gmail/sync-now?limit=100')
      toast.success(res.data?.message || 'Gmail sync started')
      window.setTimeout(() => load(true), 6000)
    } catch (e) {
      toast.error(e.message || 'Gmail sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const processPending = async () => {
    setProcessing(true)
    try {
      const res = await api.post('/inbox/process-pending', { limit: 100 })
      toast.success(`Processed ${res.data?.processed || res.data?.processed_count || 0} client mail(s)`)
      await load(true)
    } catch (e) {
      toast.error(e.message || 'Could not process client pipeline')
    } finally {
      setProcessing(false)
    }
  }

  const createRequirement = async () => {
    if (!selected?.email_id) return
    setProcessing(true)
    try {
      const res = await api.post(`/inbox/${selected.email_id}/create-requirement`)
      toast.success(res.data?.requirement_id ? 'Requirement and shortlist created. Continue Mail1 and remaining trainer outreach from Shortlist1.' : 'Client request processed.')
      await load(true)
    } catch (e) {
      toast.error(e.message || 'Could not create requirement')
    } finally {
      setProcessing(false)
    }
  }

  return (
    <div className="min-w-0 space-y-5 overflow-x-hidden animate-fade-in">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-bold uppercase tracking-wide text-blue-700 shadow-sm">
            <Inbox className="h-3.5 w-3.5" /> Inbox Client Pipeline
          </div>
          <h1 className="mt-3 page-title">Client Request Auto-Finding Pipeline</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            One place to verify that every client request is captured, details are filled, missing fields are visible, trainer auto-finding starts, and top 5 shortlist is ready for Shortlist1.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={syncGmail} disabled={syncing} className="btn-secondary text-sm">
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
            Check Inbox
          </button>
          <button onClick={processPending} disabled={processing} className="btn-secondary text-sm">
            {processing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            Process Pending
          </button>
          <button onClick={() => load(true)} className="btn-secondary text-sm">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Client mails</p>
          <p className="mt-1 text-xl font-black text-slate-950">{stats.total}</p>
        </div>
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
          <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">Domain ready</p>
          <p className="mt-1 text-xl font-black text-emerald-900">{stats.domainReady}</p>
        </div>
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Auto finding</p>
          <p className="mt-1 text-xl font-black text-blue-900">{stats.autofind}</p>
        </div>
        <div className="rounded-lg border border-violet-200 bg-violet-50 p-3">
          <p className="text-[11px] font-bold uppercase tracking-wide text-violet-700">Shortlist1 ready</p>
          <p className="mt-1 text-xl font-black text-violet-900">{stats.handoff}</p>
        </div>
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search client, domain, subject..."
              className="h-11 w-full rounded-full border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:bg-white"
            />
          </div>
          <div className="mt-4 flex items-center justify-between">
            <p className="text-sm font-bold text-slate-950">{filteredItems.length} request{filteredItems.length === 1 ? '' : 's'}</p>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
          </div>
          <div className="mt-3 max-h-[72vh] space-y-3 overflow-y-auto pr-1">
            {loading ? (
              Array.from({ length: 5 }).map((_, index) => <div key={index} className="h-32 animate-pulse rounded-lg bg-slate-100" />)
            ) : filteredItems.length ? (
              filteredItems.map(item => (
                <RequestCard
                  key={item.email_id}
                  item={item}
                  active={selected?.email_id === item.email_id}
                  onClick={() => setSelectedId(item.email_id)}
                />
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">
                No client requests found for this search.
              </div>
            )}
          </div>
        </aside>

        <section className="min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm">
          {!selected ? (
            <div className="flex min-h-[620px] items-center justify-center text-sm text-slate-500">
              Select a client request.
            </div>
          ) : (
            <div className="min-w-0 space-y-5 p-5">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">{pickTechnology(selected)}</span>
                    <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">{selected.email_id}</span>
                    {selected.requirement_id && <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700">{selected.requirement_id}</span>}
                  </div>
                  <h2 className="mt-3 break-words text-xl font-bold text-slate-950">{selected.subject || 'Client training request'}</h2>
                  <p className="mt-1 text-sm text-slate-500">{clean(selected.from_name || selected.client?.name, 'Client')} - {clean(selected.from_email || selected.client?.email, 'email missing')}</p>
                </div>
                <button onClick={createRequirement} disabled={processing || !selected.email_id} className="btn-primary text-sm">
                  {processing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Create Top 5
                </button>
                {selected.requirement_id && (
                  <button
                    type="button"
                    onClick={() => navigate(`/shortlist1?requirement_id=${encodeURIComponent(selected.requirement_id)}`)}
                    className="btn-secondary text-sm"
                  >
                    <UsersRound className="h-4 w-4" />
                    Open in Shortlist1
                  </button>
                )}
              </div>

              <StageRail item={selected} />

              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                <div className="space-y-4">
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="mb-3 flex items-center justify-between">
                      <p className="text-sm font-bold text-slate-950">Filled Requirement Details</p>
                      <span className={clsx('rounded-full px-2 py-1 text-xs font-bold', missingDetails(selected).length ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700')}>
                        {missingDetails(selected).length ? `${missingDetails(selected).length} missing` : 'Complete enough'}
                      </span>
                    </div>
                    <DetailGrid item={selected} />
                  </div>

                  <Conversation item={selected} />
                </div>

                <div className="space-y-4">
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-bold text-slate-950">Auto-Finding Decision</p>
                      {hasDomain(selected) ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <AlertCircle className="h-5 w-5 text-amber-600" />}
                    </div>
                    <div className="mt-3 space-y-2 text-sm">
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Domain available</span><strong>{hasDomain(selected) ? 'Yes' : 'No'}</strong></p>
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Pending automation</span><strong>{selected.pending_trainer_automation ? 'Yes' : 'No'}</strong></p>
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Handoff status</span><strong className="capitalize">{clean(selected.trainer_automation_status || selected.client_email_doc?.trainer_automation_status, 'shortlist1')}</strong></p>
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Mail sender</span><strong>Shortlist1</strong></p>
                    </div>
                    {trainerMailStats(selected).error && (
                      <p className="mt-3 rounded-lg bg-red-50 p-2 text-xs font-semibold text-red-700">{trainerMailStats(selected).error}</p>
                    )}
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-bold text-slate-950">Top 5 Shortlist</p>
                      <UsersRound className="h-5 w-5 text-blue-600" />
                    </div>
                    <div className="mt-3 space-y-2">
                      {shortlistTrainers(selected).length ? shortlistTrainers(selected).slice(0, 5).map((trainer, index) => (
                        <div key={trainer.trainer_id || trainer.email || index} className="rounded-lg border border-slate-200 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-bold text-slate-950">{index + 1}. {clean(trainer.name || trainer.trainer_name, 'Trainer')}</p>
                              <p className="mt-1 truncate text-xs text-slate-500">{clean(trainer.email || trainer.trainer_email, 'email missing')}</p>
                            </div>
                            <span className="rounded-full bg-blue-50 px-2 py-1 text-[11px] font-bold text-blue-700">
                              {Math.round(Number(trainer.match_score || 0)) || '-'}
                            </span>
                          </div>
                          <p className="mt-2 text-xs font-semibold capitalize text-slate-500">{clean(trainer.pipeline_status || trainer.status, 'shortlisted')}</p>
                        </div>
                      )) : (
                        <div className="rounded-lg border border-dashed border-slate-200 p-5 text-center text-sm text-slate-500">
                          No shortlist yet. Start auto finding after domain is extracted.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
