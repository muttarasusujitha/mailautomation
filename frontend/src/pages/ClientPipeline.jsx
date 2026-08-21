import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  AlertCircle,
  ChevronRight,
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
  const isHandoff = trainerMail.handoff === 'shortlist1' || item.trainer_automation_status === 'shortlist1_handoff' || item.client_email_doc?.trainer_automation_status === 'shortlist1_handoff'
  return {
    sent: Number(trainerMail.sent || automation.sent || 0),
    total: Number(trainerMail.total || automation.total || 0),
    error: isHandoff ? '' : trainerMail.error || automation.error || item.trainer_automation_error || '',
    handoff: isHandoff,
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
  const messages = item.messages || []
  const types = new Set(messages.map(message => String(message.type || '').toLowerCase()))
  const trainers = shortlistTrainers(item)
  const trainerStages = trainers.map(trainer => String(trainer.pipeline_status || trainer.status || '').toLowerCase())
  const selectionStatus = String(item.shortlist?.selection_status || item.selection_status || '').toLowerCase()
  const selectedTrainer = item.selected_trainer || {}
  const hasStage = (...stages) => trainerStages.some(stage => stages.includes(stage))
  const detailsSent = types.has('trainer_commercials_to_client') || types.has('commercial_details_notification') || types.has('client_slots')
  const slotsSent = types.has('client_slots') || hasStage('slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed')
  const interviewScheduled = types.has('client_interview_schedule') || hasStage('interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed')
  const selected = Boolean(selectedTrainer.trainer_id || selectedTrainer.name || item.shortlist?.selected_trainer_id) || ['selected', 'confirmed', 'approved'].includes(selectionStatus) || hasStage('selected', 'toc_requested', 'toc_received_pending', 'training_confirmed')
  const tocSent = types.has('client_toc') || hasStage('toc_requested', 'toc_received_pending', 'training_confirmed')
  const confirmed = ['training_confirmed', 'confirmed'].includes(String(item.status || '').toLowerCase()) || hasStage('training_confirmed')
  const latestMessage = (...messageTypes) => [...messages].reverse().find(message => messageTypes.includes(String(message.type || '').toLowerCase())) || null
  const originalMessage = {
    label: 'Client Request',
    direction: 'received',
    subject: item.subject || 'Client training request',
    body: item.clean_body || item.body || item.body_snippet || '',
    at: item.received_at || item.created_at || item.client_email_doc?.received_at,
    from_name: item.from_name || item.client?.name,
    from_email: item.from_email || item.client?.email,
  }

  return [
    {
      key: 'client_request',
      title: 'Client Request',
      status: stepState({ done: true }),
      detail: clean(item.from_email || item.client_email_doc?.from_email, 'Client email captured'),
      meta: fmtDate(item.received_at || item.created_at || item.client_email_doc?.received_at),
      message: originalMessage,
    },
    {
      key: 'trainer_details',
      title: 'Trainer Details',
      status: stepState({ done: detailsSent, active: !detailsSent }),
      detail: detailsSent ? 'Trainer profile and commercials shared with the client' : 'Waiting to share shortlisted trainer details',
      meta: detailsSent ? 'Profile, CV, commercials, and requested attachments' : '',
      message: latestMessage('trainer_commercials_to_client', 'commercial_details_notification', 'client_slots'),
    },
    {
      key: 'slots',
      title: 'Interview Slots',
      status: stepState({ done: slotsSent, active: detailsSent && !slotsSent }),
      detail: slotsSent ? 'Available trainer slots sent to the client' : 'Waiting for trainer slots',
      meta: slotsSent ? 'Client confirms the preferred slot' : '',
      message: latestMessage('client_slots'),
    },
    {
      key: 'interview',
      title: 'Interview',
      status: stepState({ done: interviewScheduled, active: slotsSent && !interviewScheduled }),
      detail: interviewScheduled ? 'Interview date and meeting link sent' : 'Waiting for client slot confirmation',
      meta: interviewScheduled ? 'Client and trainer notified' : '',
      message: latestMessage('client_interview_schedule'),
    },
    {
      key: 'selected',
      title: 'Selected',
      status: stepState({ done: selected, active: interviewScheduled && !selected }),
      detail: selected ? `Trainer selected: ${clean(selectedTrainer.name || item.shortlist?.selected_trainer_name, 'shortlisted trainer')}` : 'Waiting for client selection',
      meta: selected ? 'Proceed with final agenda and confirmation' : '',
      message: latestMessage('client_confirmation'),
    },
    {
      key: 'toc',
      title: 'TOC',
      status: stepState({ done: tocSent, active: selected && !tocSent }),
      detail: tocSent ? 'Approved TOC or course agenda sent to the client' : 'Generate TOC only when the client requests it',
      meta: tocSent ? 'Lab cost remains separate and is sent only when requested' : '',
      message: latestMessage('client_toc', 'client_toc_details_request'),
    },
    {
      key: 'confirmed',
      title: 'Confirmed',
      status: stepState({ done: confirmed, active: tocSent && !confirmed }),
      detail: confirmed ? 'Training confirmed and ready for PO / delivery workflow' : 'Waiting for final client confirmation',
      meta: confirmed ? 'Continue with PO and invoice' : '',
      message: latestMessage('client_confirmation', 'client_po'),
    },
  ]
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

function StageRail({ item, onOpenMessage }) {
  const steps = buildClientSteps(item)
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 shadow-sm">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-bold text-slate-950">Client Pipeline Steps</p>
          <p className="mt-1 text-sm text-slate-500">Track the real client delivery flow from the received request through trainer details, slots, interview, selection, TOC, and confirmation.</p>
        </div>
        <span className="inline-flex items-center justify-center rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {steps.filter(step => step.status === 'done').length}/{steps.length} completed
        </span>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="flex min-w-max items-stretch">
        {steps.map((step, index) => {
          const badgeText = step.status === 'done'
            ? 'Done'
            : step.status === 'active'
            ? 'Processing'
            : step.status === 'blocked'
            ? 'Needs attention'
            : 'Waiting'

          return (
            <div key={step.key} className="flex items-stretch">
              <div
                className={clsx(
                  'w-48 rounded-lg border border-slate-200 bg-white p-3 shadow-sm',
                  'cursor-pointer transition hover:border-blue-300 hover:bg-blue-50/40 hover:shadow-md'
                )}
                role="button"
                tabIndex={0}
                onClick={() => onOpenMessage(step)}
                onKeyDown={event => {
                  if (event.key === 'Enter' || event.key === ' ') onOpenMessage(step)
                }}
                title={`View ${step.title} message`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className={clsx('flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-black', stepTone(step.status))}>
                      {stepIcon(step.status)}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-bold leading-5 text-slate-950">{`${index + 1}. ${step.title}`}</p>
                    </div>
                  </div>
                  <span className={clsx(
                    'rounded-full px-2 py-1 text-[10px] font-semibold uppercase',
                    step.status === 'done' ? 'bg-emerald-100 text-emerald-700' :
                    step.status === 'active' ? 'bg-blue-100 text-blue-700' :
                    step.status === 'blocked' ? 'bg-amber-100 text-amber-700' :
                    'bg-slate-100 text-slate-500'
                  )}>
                    {badgeText}
                  </span>
                </div>
                {step.meta ? <p className="mt-2 min-h-8 text-xs leading-4 text-slate-500">{step.meta}</p> : <div className="min-h-8" />}
                <p className="mt-2 text-xs leading-5 text-slate-600">{step.detail}</p>
                <p className="mt-2 text-xs font-semibold text-blue-700">{step.message ? 'View message' : 'View workflow status'}</p>
              </div>
              {index < steps.length - 1 && (
                <div className="flex w-9 shrink-0 items-center justify-center" aria-hidden="true">
                  <span className={clsx('h-0.5 w-4', step.status === 'done' ? 'bg-emerald-400' : 'bg-slate-300')} />
                  <ChevronRight className={clsx('h-4 w-4 -ml-1', step.status === 'done' ? 'text-emerald-500' : 'text-slate-400')} />
                </div>
              )}
            </div>
          )
        })}
        </div>
      </div>
    </div>
  )
}

function WorkflowMessagePreview({ step, onClose }) {
  const message = step.message
  const body = message?.body || `No email message has been sent for ${step.title} yet. ${step.detail}`
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4" role="dialog" aria-modal="true" aria-label="Client email message">
      <div className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{step.title}</p>
            <h3 className="mt-1 break-words text-lg font-bold text-slate-950">{message?.subject || `${step.title} message`}</h3>
            {message && <p className="mt-2 break-words text-sm text-slate-600">{message.direction === 'received' ? 'From' : 'To'}: {clean(message.from_name || message.to_name, message.direction === 'received' ? 'Client' : 'Client')}</p>}
            <p className="mt-1 text-xs text-slate-500">{message ? fmtDate(message.at) : step.status === 'waiting' ? 'Not sent yet' : 'Message record unavailable'}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Close</button>
        </div>
        <pre className="overflow-y-auto whitespace-pre-wrap break-words p-5 font-sans text-sm leading-7 text-slate-700">{body}</pre>
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
  const trainers = shortlistTrainers(item)
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'w-full rounded-lg border p-3 text-left transition hover:border-blue-200 hover:bg-white hover:shadow-sm',
        active ? 'border-blue-300 bg-white shadow-sm ring-1 ring-blue-200' : 'border-slate-200 bg-white/80'
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
    <div className="rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white p-4">
        <div>
          <p className="text-sm font-bold text-slate-950">Client Conversation</p>
          <p className="mt-0.5 text-xs text-slate-500">Inbox request and later client replies stay visible here.</p>
        </div>
        <MessageSquareText className="h-5 w-5 text-slate-400" />
      </div>
      <div className="max-h-[440px] space-y-3 overflow-y-auto p-4">
        {initialBody && (
          <div className="mr-auto max-w-[86%] rounded-lg rounded-bl-sm border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Original Client Request</p>
            <p className="mt-1 break-words text-sm font-semibold text-slate-900">{item.subject}</p>
            <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-600">{initialBody}</pre>
          </div>
        )}
        {(item.ai_reply || item.draft_reply || item.generated_reply?.body) && (
          <div className="ml-auto max-w-[86%] rounded-lg rounded-br-sm border border-blue-200 bg-blue-600 p-4 text-white shadow-sm">
            <p className="text-xs font-bold uppercase tracking-wide text-blue-100">Clahan Reply Template</p>
            <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm leading-6 text-blue-50">{item.ai_reply || item.draft_reply || item.generated_reply?.body}</pre>
          </div>
        )}
        {messages.map((message, index) => (
          <div
            key={`${message.email_id || index}-${message.type}`}
            className={clsx(
              'max-w-[86%] rounded-lg border p-4 shadow-sm',
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
  const [previewStep, setPreviewStep] = useState(null)

  const selected = useMemo(
    () => items.find(item => item.email_id === selectedId) || null,
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
        setSelectedId('')
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
      const res = await api.post('/emails/check-replies', { max_messages: 100, since_days: 7 })
      toast.success(res.data?.message || 'Reply check started')
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
      toast.success(res.data?.requirement_id ? 'Requirement and shortlist created. Continue trainer outreach from Shortlist1.' : 'Client request processed.')
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

      <div className="min-w-0 space-y-4">
        <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-base font-bold text-slate-950">Select Requirement</p>
              <p className="mt-1 text-sm text-slate-500">Choose a client requirement to view its complete pipeline.</p>
            </div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search client, domain, subject..."
              className="h-11 w-full rounded-full border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:bg-white"
            />
          </div>
          </div>
          <div className="flex items-center justify-between">
            <p className="text-sm font-bold text-slate-950">{filteredItems.length} request{filteredItems.length === 1 ? '' : 's'}</p>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
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
        </section>

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
                {!selected.requirement_id && <button onClick={createRequirement} disabled={processing || !selected.email_id} className="btn-primary text-sm">
                  {processing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Create Requirement
                </button>}
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

              <StageRail item={selected} onOpenMessage={setPreviewStep} />

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
      {previewStep && <WorkflowMessagePreview step={previewStep} onClose={() => setPreviewStep(null)} />}
    </div>
  )
}
