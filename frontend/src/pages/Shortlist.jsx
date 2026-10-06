import { mail1Template, mail2FollowupTemplate, mail3Template, mail3SlotClarificationTemplate, mail3TooManySlotsTemplate, mail4Template, mail5SelectedTemplate, mail5RejectedTemplate, mailTrainingConfirmedTemplate } from '../utils/workflowTemplates'
import { useState, useEffect, useRef } from 'react'
import { deleteRequirement, generateWorkflowMail, getRequirement, getRequirements, getShortlist, updateRequirement } from '../utils/api'
import api from '../utils/api'
import toast from 'react-hot-toast'
import {
  Users, Mail, Clock, MapPin, Phone,
  ChevronRight, ChevronLeft, Loader2, Send, AlertCircle,
  RefreshCw, Star, MessageSquare, X, Eye,
  Calendar, ClipboardList, Info,
  FileText, CheckCircle2, Bell, PhoneCall, Download, Wand2, Trash2
} from 'lucide-react'
import clsx from 'clsx'
import { isClientHandoffDelivered, pipelineStepComplete } from '../utils/handoffStatus'
import { useLiveShortlist } from '../utils/useLiveShortlist'
import { formatRequirementSchedule } from '../utils/requirementDates'
import ClientHandoffReview from '../components/ClientHandoffReview'
import { linkedinProfileUrl, trainerOwnedDetails } from '../utils/trainerIdentity'

// Some legacy pipeline strings were saved with their UTF-8 bytes decoded as
// Latin-1. Repair them at the UI boundary so no mojibake reaches the screen.
function getLS(k) { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }
function setLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} }
function money(v) {
  const n = Number(v || 0)
  return `INR ${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Pipeline stages Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function channelStatus(label, result, successLabel = 'sent') {
  if (!result) return { label, value: 'Not attempted', tone: 'warn', detail: '' }
  const numberDetail = result.to_number ? `To: ${result.to_number}` : (result.teams_email ? `To: ${result.teams_email}` : '')
  const idDetail = result.twilio_sid || result.aisensy_message_id || result.meta_message_id || result.teams_direct_id || result.email_id || ''
  const detail = [numberDetail, idDetail].filter(Boolean).join(' | ')
  if (result.success === true) return { label, value: result.status || successLabel, tone: 'ok', detail }
  if (result.status === 'not_applicable') return { label, value: 'Not applicable', tone: 'muted', detail: '' }
  if (result.status === 'skipped') return { label, value: 'Skipped', tone: 'warn', detail: [numberDetail, result.error || 'Not configured'].filter(Boolean).join(' | ') }
  return { label, value: 'Failed', tone: 'bad', detail: [numberDetail, result.error || result.status || 'Unknown error'].filter(Boolean).join(' | ') }
}

function showSendStatusToast({ trainerName, result, title = 'Message sent' }) {
  const delivered = isSendMailDelivered(result)
  const email = {
    label: 'Email',
    value: delivered ? 'sent' : 'failed',
    tone: delivered ? 'ok' : 'bad',
    detail: delivered ? (firstSendMailResult(result)?.email_id || result?.email_id || '') : sendMailError(result, 'Unknown error'),
  }
  const channels = [
    email,
    channelStatus('WhatsApp', result?.whatsapp, 'queued'),
    channelStatus('Teams DM', result?.teams_direct, 'sent'),
    channelStatus('Teams Channel', result?.teams, 'sent'),
  ]
  const toneClass = {
    ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    bad: 'bg-red-50 text-red-700 border-red-200',
    warn: 'bg-amber-50 text-amber-700 border-amber-200',
    muted: 'bg-slate-50 text-slate-500 border-slate-200',
  }

  toast.custom((t) => (
    <div className={clsx(
      'w-[360px] max-w-[calc(100vw-32px)] rounded-xl border border-slate-200 bg-white shadow-xl p-4 transition-all',
      t.visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
    )}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-sm font-bold text-slate-900">{title}</p>
          <p className="text-xs text-slate-500 mt-0.5">{trainerName || 'Trainer'}</p>
        </div>
        <button onClick={() => toast.dismiss(t.id)} className="p-1 rounded-lg hover:bg-slate-100 text-slate-400">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="space-y-2">
        {channels.map(item => (
          <div key={item.label} className={clsx('rounded-lg border px-3 py-2', toneClass[item.tone] || toneClass.muted)}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold">{item.label}</span>
              <span className="text-xs font-bold capitalize">{item.value}</span>
            </div>
            {item.detail && <p className="text-[11px] mt-1 break-words opacity-80">{item.detail}</p>}
          </div>
        ))}
      </div>
    </div>
  ), { duration: 10000 })
}

function firstSendMailResult(result = {}) {
  return Array.isArray(result?.results) ? result.results[0] : null
}

function isSendMailDelivered(result = {}) {
  const firstResult = firstSendMailResult(result)
  if (firstResult) return firstResult.status === 'sent'
  if (typeof result?.sent === 'number') return result.sent > 0
  return result?.success === true
}

function sendMailError(result = {}, fallback = 'Email delivery failed') {
  const firstResult = firstSendMailResult(result)
  return firstResult?.error_message || firstResult?.status || result?.error || result?.message || fallback
}

const STAGES = {
  pending:              { label: 'Pending',               color: 'bg-slate-100 text-slate-500',     step: 0 },
  mail1_sent:           { label: '1st Mail Sent Ã°Å¸â€œÂ§',      color: 'bg-blue-100 text-blue-700',       step: 1 },
  waiting_reply1:       { label: 'Waiting for Reply Ã¢ÂÂ³',  color: 'bg-sky-100 text-sky-700',         step: 1 },
  mail1_replied:        { label: 'Mail 1 Replied Ã¢Å“â€¦',     color: 'bg-emerald-100 text-emerald-700', step: 1 },
  details_requested:    { label: 'Details Requested Ã°Å¸â€œâ€¹',  color: 'bg-indigo-100 text-indigo-700',   step: 2 },
  details_received:     { label: 'Details Received Ã¢Å“â€¦',   color: 'bg-emerald-100 text-emerald-700', step: 2 },
  waiting_reply2:       { label: 'Waiting for Reply Ã¢ÂÂ³',  color: 'bg-sky-100 text-sky-700',         step: 2 },
  slot_booked:          { label: 'Slot Booked Ã°Å¸â€œâ€¦',        color: 'bg-amber-100 text-amber-700',     step: 3 },
  interview_scheduled:  { label: 'Interview Scheduled', color: 'bg-purple-100 text-purple-700',  step: 4 },
  selected:             { label: 'Selected Ã¢Å“â€¦',            color: 'bg-emerald-100 text-emerald-700', step: 5 },
  rejected:             { label: 'Not Selected Ã¢ÂÅ’',        color: 'bg-red-100 text-red-600',         step: 5 },
  stopped_selected:     { label: 'Stopped - Role Filled', color: 'bg-slate-100 text-slate-500',     step: 0 },
  toc_requested:        { label: 'ToC Requested Ã°Å¸â€œâ€ž',      color: 'bg-teal-100 text-teal-700',       step: 6 },
  toc_received_pending: { label: 'ToC Received Ã°Å¸â€œâ€ž',       color: 'bg-teal-100 text-teal-700',       step: 6 },
  training_confirmed:   { label: 'Training Confirmed Ã°Å¸Å½â€œ', color: 'bg-green-100 text-green-700',     step: 7 },
  po_requested:         { label: 'PO Requested',           color: 'bg-cyan-100 text-blue-700',       step: 8 },
  client_po_received:   { label: 'Client PO Received',     color: 'bg-cyan-100 text-blue-700',       step: 8 },
  invoice_generated:    { label: 'Invoice Generated',      color: 'bg-emerald-100 text-emerald-700', step: 9 },
  invoice_sent:         { label: 'Invoice Sent',           color: 'bg-green-100 text-green-700',     step: 10 },
}

// Plain labels keep pipeline status easy to scan and avoid legacy emoji bytes.
Object.assign(STAGES, {
  mail1_sent: { ...STAGES.mail1_sent, label: 'Mail 1 Sent' },
  waiting_reply1: { ...STAGES.waiting_reply1, label: 'Waiting for Reply' },
  mail1_replied: { ...STAGES.mail1_replied, label: 'Mail 1 Reply Received' },
  details_requested: { ...STAGES.details_requested, label: 'Details Requested' },
  details_received: { ...STAGES.details_received, label: 'Details Received' },
  waiting_reply2: { ...STAGES.waiting_reply2, label: 'Waiting for Reply' },
  slot_booked: { ...STAGES.slot_booked, label: 'Slots Received' },
  selected: { ...STAGES.selected, label: 'Selected' },
  rejected: { ...STAGES.rejected, label: 'Not Selected' },
  training_confirmed: { ...STAGES.training_confirmed, label: 'Training Confirmed', step: 6 },
  po_requested: { ...STAGES.po_requested, step: 7 },
  client_po_received: { ...STAGES.client_po_received, step: 7 },
  invoice_generated: { ...STAGES.invoice_generated, label: 'Invoice Ready', step: 8 },
  invoice_sent: { ...STAGES.invoice_sent, label: 'Invoice Sent to Client', step: 8 },
  toc_requested: { ...STAGES.toc_requested, label: 'ToC Shared', step: 5 },
  toc_received_pending: { ...STAGES.toc_received_pending, label: 'ToC Received', step: 5 },
})

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Reminder intervals for Mail 1 (in ms) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
const SHORTLIST_REFRESH_INTERVAL_MS = 10000
// The inbox workflow is the one authoritative sender for the client handoff.
// Keeping a second browser-side sender here caused duplicate client emails when
// a trainer reply was processed at the same time as this page refresh.
const AUTO_SEND_CLIENT_SLOTS = false
const THREAD_REFRESH_INTERVAL_MS = 5000
const REPLY_SYNC_THROTTLE_MS = 15000
const truthySetting = value => value === true || ['1', 'true', 'yes', 'on', 'enabled'].includes(String(value ?? '').trim().toLowerCase())
const falseSetting = value => ['0', 'false', 'no', 'off', 'disabled'].includes(String(value ?? '').trim().toLowerCase())
const remindersAllowedFromSettings = (settings = {}) => {
  const pipeline = settings.pipeline || {}
  const schedulerCfg = settings.schedulerCfg || {}
  if (!truthySetting(pipeline.autoRetry)) return false
  if (falseSetting(schedulerCfg.followupEnabled)) return false
  if (falseSetting(schedulerCfg.auto_retry_enabled)) return false
  if (falseSetting(schedulerCfg.autoRetryEnabled)) return false
  return true
}

function requirementFlowType(req = {}) {
  const explicitTarget = String(req.pipeline_target || req.pipeline_page || '').trim().toLowerCase()
  if (explicitTarget === 'shortlist1') return 'confirmed'
  if (explicitTarget === 'shortlist') return 'proposal'
  if (explicitTarget === 'linkedin-pipeline' || explicitTarget === 'linkedin_pipeline') return 'linkedin'

  const raw = String(req.batch_flow || req.batch_type || req.requirement_type || req.training_status || req.source || req.metadata?.source || '').toLowerCase()
  if (raw.includes('linkedin')) return 'linkedin'
  if (raw.includes('proposal')) return 'proposal'
  if (raw.includes('confirmed')) return 'confirmed'

  const text = [
    req.title,
    req.subject,
    req.technology_needed,
    req.domain,
    req.client_requirement_text,
    req.client_request,
    req.original_body,
    req.metadata?.original_body,
    req.metadata?.original_subject,
    req.extracted?.client_request,
  ].filter(Boolean).join(' ').toLowerCase()
  const proposalSignals = [
    'proposal',
    'trainer options',
    'suitable trainer',
    'share profiles',
    'trainer profile',
    'commercials',
    'quotation',
    'quote',
    'upcoming training',
    'upcoming corporate training',
  ]
  const confirmedSignals = [
    'purchase order',
    'po no',
    'program confirmation',
    'confirmed training',
    'training confirmed',
    'we are happy to confirm',
  ]
  if (confirmedSignals.some(signal => text.includes(signal))) return 'confirmed'
  if (proposalSignals.some(signal => text.includes(signal))) return 'proposal'

  const hasValue = value => {
    const clean = String(value || '').trim().toLowerCase()
    return clean && !['to be confirmed', 'tbc', 'tbd', 'na', 'n/a', 'not confirmed', 'not finalized', 'not finalised', 'unknown'].includes(clean)
  }
  const missingCount = [
    req.duration_days || req.duration_hours || req.duration_text || req.duration,
    req.mode,
    req.preferred_dates || req.training_dates || req.timeline_start,
    req.location || req.preferred_location,
  ].filter(value => !hasValue(value)).length
  return missingCount >= 2 ? 'proposal' : 'confirmed'
}

const isProposalRequirement = req => requirementFlowType(req) === 'proposal'
const isLinkedInRequirement = req => requirementFlowType(req) === 'linkedin'

async function getAllRequirementsForFlow() {
  const first = await getRequirements({ page: 1, page_size: 100, pipeline: 'shortlist' })
  const firstData = first.data || {}
  const firstItems = firstData.requirements || firstData.items || []
  const pages = Number(firstData.pages || 1)
  if (pages <= 1) return firstItems
  const rest = await Promise.all(
    Array.from({ length: pages - 1 }, (_, index) => getRequirements({ page: index + 2, page_size: 100, pipeline: 'shortlist' }))
  )
  return rest.reduce((items, res) => {
    const data = res.data || {}
    return items.concat(data.requirements || data.items || [])
  }, firstItems)
}

let shortlistReplyCheckPromise = null
let lastShortlistReplyCheckAt = 0

function syncShortlistRepliesIfDue(force = false) {
  const now = Date.now()
  if (!force && now - lastShortlistReplyCheckAt < REPLY_SYNC_THROTTLE_MS) return Promise.resolve(null)
  if (!shortlistReplyCheckPromise) {
    lastShortlistReplyCheckAt = now
    shortlistReplyCheckPromise = api.post('/emails/check-replies', { since_days: 7, max_messages: 100 })
      .catch(() => null)
      .finally(() => { shortlistReplyCheckPromise = null })
  }
  return shortlistReplyCheckPromise
}

const BACKEND_AUTHORITATIVE_STAGES = new Set([
  'stopped_selected',
  'role_filled',
  'requirement_filled',
  'selected',
  'toc_requested',
  'toc_received_pending',
  'training_confirmed',
  'po_requested',
  'client_po_received',
  'invoice_generated',
  'invoice_sent',
])

function normalizeBackendStage(value = '') {
  const stage = String(value || '').trim().toLowerCase()
  if (stage === 'role_filled' || stage === 'requirement_filled') return 'stopped_selected'
  return BACKEND_AUTHORITATIVE_STAGES.has(stage) ? stage : ''
}

const BACKEND_PIPELINE_STAGE_ALIASES = {
  shortlisted: 'pending',
  new: 'pending',
  mail1: 'waiting_reply1',
  mail1_sent: 'waiting_reply1',
  mail1_reminder: 'waiting_reply1',
  mail1_question_redirect: 'waiting_reply1',
  mail2: 'slot_booked',
  mail2_followup: 'waiting_reply2',
  mail3: 'interview_scheduled',
  mail3_too_many_slots: 'slot_booked',
  mail3_too_few_slots: 'slot_booked',
  mail3_slot_followup: 'slot_booked',
  mail4: 'interview_scheduled',
  mail5_ok: 'selected',
  mail5_no: 'rejected',
  mail6_toc: 'toc_requested',
  mail7_confirm: 'training_confirmed',
}

function normalizePipelineStage(value = '') {
  const stage = String(value || '').trim().toLowerCase()
  if (!stage) return ''
  return BACKEND_PIPELINE_STAGE_ALIASES[stage] || (STAGES[stage] ? stage : normalizeBackendStage(stage))
}

function resolveTrainerStage(trainer, req, state) {
  const authoritative = backendAuthoritativeStage(trainer, req)
  const stateStage = normalizePipelineStage(state?.status)
  if (authoritative) return authoritative

  if (stateStage && stateStage !== 'pending') return stateStage

  const backendStage = normalizePipelineStage(
    trainer?.pipeline_status || trainer?.status || trainer?.last_mail_type || trainer?.last_automation_mail_type
  )
  return backendStage || stateStage || 'pending'
}

function requirementCommercialStage(req) {
  const invoiceStatus = String(req?.invoice_status || '').toLowerCase()
  const clientPoStatus = String(req?.client_po_status || '').toLowerCase()
  const poRequestStatus = String(req?.po_request_status || '').toLowerCase()

  if (invoiceStatus === 'sent' || clientPoStatus === 'invoice_sent') return 'invoice_sent'
  if (invoiceStatus === 'generated' || clientPoStatus === 'invoice_generated') return 'invoice_generated'
  if (clientPoStatus === 'received') return 'client_po_received'
  if (poRequestStatus === 'requested' || req?.po_requested_at) return 'po_requested'
  return ''
}

function backendAuthoritativeStage(trainer, req) {
  const trainerId = String(trainer?.trainer_id || '')
  const selectedId = String(req?.selected_trainer_id || '')
  const commercialStage = requirementCommercialStage(req)
  const requirementStage = normalizeBackendStage(req?.selection_status || req?.status)
  const trainerStage = normalizeBackendStage(trainer?.pipeline_status || trainer?.status)
  const lastMailError = String(trainer?.last_mail_error || '').trim()
  const lastMailType = String(trainer?.last_mail_type || trainer?.last_mail_type_attempted || '').trim().toLowerCase()

  if (
    lastMailError &&
    ['mail1', 'first', 'mail1_reminder'].includes(lastMailType) &&
    ['waiting_reply1', 'mail1_sent'].includes(trainerStage)
  ) {
    return 'pending'
  }

  if (selectedId && trainerId && trainerId !== selectedId) return 'stopped_selected'
  if (selectedId && trainerId === selectedId) {
    if (commercialStage) return commercialStage
    if (['selected', 'toc_requested', 'toc_received_pending', 'training_confirmed', 'po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent'].includes(requirementStage)) {
      return requirementStage
    }
    if (trainerStage && trainerStage !== 'stopped_selected') return trainerStage
    return 'selected'
  }
  return trainerStage
}

function HiringDoneStamp({ requirement, trainerName }) {
  const domain = requirement?.technology_needed || 'This Domain'
  return (
    <div className="pointer-events-none fixed inset-0 z-30 flex items-center justify-center px-6">
      <div className="absolute right-6 top-24 rounded-full border border-emerald-300 bg-emerald-50/95 px-4 py-2 text-sm font-black uppercase tracking-wide text-emerald-800 shadow-lg">
        Domain Closed
      </div>
      <div className="select-none translate-x-10 rounded-2xl border-[5px] border-emerald-600/40 bg-white/55 px-8 py-4 text-center text-emerald-800/35 shadow-[0_0_0_8px_rgba(16,185,129,0.10)] backdrop-blur-[1px] md:translate-x-24 md:px-12 md:py-5">
        <p className="text-4xl font-black uppercase tracking-[0.18em] md:text-6xl">Hiring Done</p>
        <p className="mt-1.5 text-sm font-black uppercase tracking-[0.2em] text-emerald-900/45 md:text-lg">No More Outreach</p>
        <p className="mt-1.5 text-base font-extrabold uppercase tracking-[0.14em] md:text-xl">{domain}</p>
        {trainerName && (
          <p className="mt-1.5 text-xs font-bold uppercase tracking-[0.12em] md:text-sm">
            Selected: {trainerName}
          </p>
        )}
      </div>
    </div>
  )
}

function mail2Template(trainer, req) {
  return mail3Template(trainer, req, '')
}






// AUTO: ToC request sent immediately after selection

// MANUAL: Training confirmation with contact details Ã¢â‚¬â€ sent after ToC is received

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Reply intent detector Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function stripQuotedEmail(text = '') {
  return String(text)
    .split(/\nOn .+wrote:\s*/i)[0]
    .split(/\n-{2,}\s*Original Message\s*-{2,}/i)[0]
    .split('\n')
    .filter(line => !line.trim().startsWith('>'))
    .join('\n')
    .trim()
}

function requestedTrainerDetailItems(req = {}) {
  const source = [
    req.client_request,
    req.requirement_text,
    req.original_email_body,
    req.email_body,
    req.raw_email,
    req.description,
  ].filter(Boolean).join('\n').toLowerCase()
  const domain = req.technology_needed || req.technology || 'training'
  const tocGeneratedByClahan = String(req.toc_action || req.metadata?.toc_action || req.extracted?.toc_action || '').toLowerCase() === 'generate_by_clahan'
  const labManagedByClahan = [
    ...(Array.isArray(req.clahan_managed_details) ? req.clahan_managed_details : []),
    ...(Array.isArray(req.metadata?.clahan_managed_details) ? req.metadata.clahan_managed_details : []),
  ].some(item => String(item).toLowerCase().includes('lab'))
  const items = [
    { key: 'cv', label: 'Updated CV / Trainer Profile', required: true },
    { key: 'linkedin', label: 'LinkedIn Profile', required: true },
    { key: 'experience', label: `${domain} implementation and training experience`, required: true },
    { key: 'certifications', label: 'Relevant certifications', required: /certification|certifications|certificate|certified/.test(source) || !source },
    { key: 'availability', label: 'Availability', required: true },
    { key: 'commercials', label: 'Commercials (per hour/day)', required: /commercial|commercials|per hour|per day|rate|charges|budget|cost/.test(source) || !source },
    { key: 'lab', label: 'Lab support availability and cost, if applicable', required: !labManagedByClahan && /lab support|lab availability|lab cost|labs?\b/.test(source) },
    { key: 'toc', label: 'ToC/course agenda', required: !tocGeneratedByClahan && /\b(toc|table of contents|course agenda|agenda|day[-\s]?wise)\b/.test(source) },
  ]
  if (!source) return trainerOwnedDetails(items)
  return trainerOwnedDetails(items.filter(item => item.required || source.includes(item.key) || source.includes(item.label.toLowerCase().split(' ')[0])))
}

function providedTrainerDetailMap(text = '') {
  const t = stripQuotedEmail(text).toLowerCase()
  return {
    cv: /\b(cv|resume|trainer profile|profile attached|attached profile|attached my profile|updated profile|attachment|attached)\b/i.test(t),
    linkedin: Boolean(linkedinProfileUrl(t)),
    experience: /\b(experience|implementation|hands[-\s]?on|training experience|trained|delivered|worked on|years?|yrs?)\b/i.test(t),
    certifications: /\b(certification|certifications|certified|certificate|not certified|no certification|none)\b/i.test(t),
    availability: /\b(available|availability|slots?|dates?|timings?|schedule|free|can join|can take|from|to|weekdays|weekends|morning|afternoon|evening)\b/i.test(t),
    commercials: /\b(inr|rs\.?|â‚¹|rate|charges?|commercial|commercials|fee|fees|per day|per hour|per session|cost)\b/i.test(t),
    lab: /\b(lab|labs|lab support|setup|environment|sandbox)\b/i.test(t),
  }
}

function missingRequestedTrainerDetails(text = '', req = {}) {
  const provided = providedTrainerDetailMap(text)
  return requestedTrainerDetailItems(req)
    .filter(item => item.required && !provided[item.key])
    .map(item => item.label)
}

function hasRequestedTrainerDetails(text = '', req = {}) {
  const t = stripQuotedEmail(text).toLowerCase()
  if (!t) return false

  return missingRequestedTrainerDetails(t, req).length === 0
}

function hasProperInterviewSlots(text = '') {
  const clean = stripQuotedEmail(text).toLowerCase()
  if (!clean) return false
  const dateHits = [
    /\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b/g,
    /\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b/g,
    /\b(mon|tue|wed|thu|fri|sat|sun)(day)?\b/g,
  ].reduce((sum, rx) => sum + ((clean.match(rx) || []).length), 0)
  const timeHits = [
    /\b\d{1,2}(?::\d{2})?\s*(am|pm)\b/g,
    /\b\d{1,2}(?::\d{2})?\s*[-Ã¢â‚¬â€œ]\s*\d{1,2}(?::\d{2})?\s*(am|pm)\b/g,
  ].reduce((sum, rx) => sum + ((clean.match(rx) || []).length), 0)
  const slotHints = (clean.match(/\b(slot|option|available|availability)\b/g) || []).length
  const hasOneExactSlot = dateHits >= 1 && timeHits >= 1
  const hasThreeSlotOptions = dateHits >= 3 && timeHits >= 3 || dateHits >= 3 && timeHits >= 2 && slotHints >= 1
  return hasOneExactSlot || hasThreeSlotOptions
}

function latestReplyAfter(messages, sentTypes = []) {
  const sent = messages.filter(m => m.direction === 'sent' && sentTypes.includes(m.mail_type))
  if (!sent.length) return null
  const lastSentTime = Math.max(...sent.map(m => new Date(m.sent_at || 0).getTime()))
  return messages
    .filter(m => m.direction === 'received' && new Date(m.sent_at || 0).getTime() > lastSentTime)
    .sort((a, b) => new Date(a.sent_at || 0).getTime() - new Date(b.sent_at || 0).getTime())
    .at(-1) || null
}

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Send Mail Modal Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
async function sendSlotsToClient({ trainer, req, slotText = '', clientEmail = '', clientName = '' }) {
  const res = await api.post('/shortlists/send-client-slots', {
    trainer_id: trainer.trainer_id,
    trainer_name: trainer.name,
    requirement_id: req.requirement_id,
    slot_text: stripQuotedEmail(slotText),
    trainer_details_text: stripQuotedEmail(
      trainer.details_reply_text ||
      trainer.trainer_details_text ||
      trainer.mail1_reply_text ||
      trainer.mail2_reply_text ||
      trainer.reply_text ||
      trainer.last_reply_snippet ||
      ''
    ),
    client_email: clientEmail,
    client_name: clientName,
  })
  return res.data
}

function ClientEmailModal({
  onClose,
  onSubmit,
  loading,
  initialEmail = '',
  initialName = '',
  title = 'Send Slots to Client',
  description = 'Client email is missing for this requirement. Add it once, then the trainer slots will be sent.',
  submitLabel = 'Save & Send',
}) {
  const [clientEmail, setClientEmail] = useState(initialEmail)
  const [clientName, setClientName] = useState(initialName)

  const submit = () => {
    const email = clientEmail.trim()
    if (!email) {
      toast.error('Client email is required')
      return
    }
    onSubmit({ clientEmail: email, clientName: clientName.trim() })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">{title}</h3>
            <p className="mt-1 text-sm text-slate-500">
              {description}
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4">
          <div>
            <label className="label">Client Email</label>
            <input
              className="input"
              type="email"
              placeholder="client@company.com"
              value={clientEmail}
              onChange={e => setClientEmail(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <label className="label">Client Name <span className="font-normal text-slate-400">(optional)</span></label>
            <input
              className="input"
              placeholder="Client name or company"
              value={clientName}
              onChange={e => setClientName(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-6 flex gap-3">
          <button onClick={submit} disabled={loading} className="btn-primary flex-1 justify-center">
            {loading ? <><Loader2 className="h-4 w-4 animate-spin" /> Saving...</> : <><Send className="h-4 w-4" /> {submitLabel}</>}
          </button>
          <button onClick={onClose} disabled={loading} className="btn-secondary">Cancel</button>
        </div>
      </div>
    </div>
  )
}

function MailModal({ trainer, req, mailType, onClose, onSent, generationMode = 'template' }) {
  const [loading, setLoading]           = useState(false)
  const [hasDetails, setHasDetails]     = useState(false)
  const [details, setDetails]           = useState({ domain: req?.technology_needed || '', duration: '', mode: 'Online', participants: '' })
  const [trainerDates, setTrainerDates] = useState('')
  const [interviewLink, setInterviewLink] = useState('')
  const [platform, setPlatform]         = useState('Google Meet')
  const [dateTime, setDateTime]         = useState('')
  const [trainingDate, setTrainingDate] = useState('')
  const [venue, setVenue]               = useState('')
  const [contactName, setContactName]   = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [clientEmail, setClientEmail]   = useState(req?.client_email || '')
  const [clientName, setClientName]     = useState(req?.client_name || req?.client_company || '')
  const [aiMail, setAiMail] = useState(null)
  const [aiGenerating, setAiGenerating] = useState(false)

  const getPreview = () => {
    switch (mailType) {
      case 'mail1':          return mail1Template(trainer, req, hasDetails, details)
      case 'mail2':          return mail2Template(trainer, req)
      case 'mail2_followup': return mail2FollowupTemplate(trainer, req)
      case 'mail3':          return mail4Template(trainer, req, interviewLink, platform, dateTime)
      case 'mail3_too_many_slots': return mail3TooManySlotsTemplate(trainer)
      case 'mail3_too_few_slots':  return mail3SlotClarificationTemplate(trainer)
      case 'mail4':          return mail5SelectedTemplate(trainer, req)
      case 'mail5_ok':       return mail5SelectedTemplate(trainer, req)
      case 'mail5_no':       return mail5RejectedTemplate(trainer, req)
      case 'mail7_confirm':  return mailTrainingConfirmedTemplate(trainer, req, contactName, contactPhone, contactEmail, trainingDate, venue)
      default:               return { subject: '', body: '' }
    }
  }

  const preview = getPreview()

  useEffect(() => {
    if (generationMode !== 'ai') {
      setAiMail(null)
      setAiGenerating(false)
      return undefined
    }
    let cancelled = false
    const fallback = getPreview()
    setAiGenerating(true)
    setAiMail(null)
    generateWorkflowMail({
      requirementId: req.requirement_id,
      trainerId: trainer.trainer_id,
      trainerName: trainer.name,
      mailType,
      subject: fallback.subject,
      body: fallback.body,
    }).then(result => {
      if (!cancelled) setAiMail(result)
    }).catch(error => {
      if (!cancelled) toast.error(error.response?.data?.detail || error.message || 'AI email generation failed')
    }).finally(() => {
      if (!cancelled) setAiGenerating(false)
    })
    return () => { cancelled = true }
  }, [generationMode, mailType, trainer.trainer_id, trainer.name, req.requirement_id, req.batch_flow, req.batch_type, req.pipeline_target, req.pipeline_page, hasDetails, details.domain, details.duration, details.mode, details.participants, trainerDates, interviewLink, platform, dateTime, trainingDate, venue, contactName, contactPhone, contactEmail])

  const TITLES = {
    mail1:         'Ã°Å¸â€œÂ§ Send Shortlist Mail',
    mail2:         'Mail 2 - Slot Booking',
    mail2_followup:'Ã°Å¸â€œâ€¹ Ask Details Again',
    mail3:         'Mail 3 - Interview Link',
    mail3_too_many_slots: 'Ask for 3 Slots',
    mail3_too_few_slots:  'Ask for 3 Complete Slots',
    mail4:         'Mail 4 - Selected',
    mail5_ok:      'Ã°Å¸Å½â€° Send Selection Mail',
    mail5_no:      'Ã¢ÂÅ’ Send Rejection Mail',
    mail7_confirm: 'Ã°Å¸Å½â€œ Send Training Confirmation',
  }

  const NEXT_STAGES = {
    mail1:         'waiting_reply1',
    mail2:         'slot_booked',
    mail2_followup:'waiting_reply2',
    mail3:         'interview_scheduled',
    mail3_too_many_slots: 'slot_booked',
    mail3_too_few_slots:  'slot_booked',
    mail4:         'selected',
    mail5_ok:      'selected',
    mail5_no:      'rejected',
    mail7_confirm: 'training_confirmed',
  }

  const handleSend = async () => {
    if (mailType === 'mail2' && !clientEmail.trim()) {
      toast.error('Client email is required so trainer slots can be sent automatically')
      return
    }
    setLoading(true)
    try {
      if (generationMode === 'ai' && !aiMail) {
        throw new Error('AI email generation failed. Template fallback is disabled while AI mode is on.')
      }
      if (mailType === 'mail3') {
        await api.post('/shortlists/send-interview-link', {
          trainer_id:     trainer.trainer_id,
          trainer_name:   trainer.name,
          to_email:       trainer.email,
          requirement_id: req.requirement_id,
          platform,
          date_time:      dateTime,
          interview_link: interviewLink,
          client_email:   req.client_email,
          client_name:    req.client_name || req.client_company || '',
          mail_type:      'mail3',
        })
      } else {
        const res = await api.post('/shortlists/send-mail', {
          trainer_id:     trainer.trainer_id,
          trainer_name:   trainer.name,
          to_email:       trainer.email,
          requirement_id: req.requirement_id,
          subject:        aiMail?.subject || preview.subject,
          body:           aiMail?.body || preview.body,
          mail_type:      mailType,
          client_email:   mailType === 'mail2' ? clientEmail.trim() : undefined,
          client_name:    mailType === 'mail2' ? clientName.trim() : undefined,
        })
        const firstResult = Array.isArray(res?.data?.results) ? res.data.results[0] : null
        if (res?.data?.success !== true || firstResult?.status !== 'sent') {
          throw new Error(firstResult?.error_message || res?.data?.message || 'Email delivery failed')
        }
      }
      toast.success(mailType === 'mail3' ? 'Interview link sent to trainer and client' : `Ã¢Å“â€¦ Email sent to ${trainer.name}!`)
      let nextStage = NEXT_STAGES[mailType]
      let poExtra = {}
      if (mailType === 'mail7_confirm') {
        try {
          const poRes = await api.post(`/requirements/${req.requirement_id}/request-client-po`, {
            trainer_id: trainer.trainer_id,
            trainer_name: trainer.name,
            client_email: req.client_email,
            client_name: req.client_name || req.client_company || '',
            training_dates: trainingDate || req.training_dates || req.timeline_start || '',
          })
          nextStage = 'po_requested'
          poExtra = {
            clientPoRequestedAt: Date.now(),
            clientPoRequestEmailId: poRes.data?.email_id,
          }
          toast.success(`PO request sent to ${poRes.data?.to_email || req.client_email}`)
        } catch (poError) {
          toast.error(poError.response?.data?.detail || poError.message || 'Training confirmed, but PO request could not be sent')
        }
      }
      onSent(
        nextStage,
        mailType === 'mail7_confirm'
          ? { trainingDate, venue, contactName, contactPhone, contactEmail, ...poExtra }
          : {}
      )
      onClose()
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Send failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-slate-100 sticky top-0 bg-white z-10">
          <div>
            <h3 className="font-bold text-lg text-slate-900">{TITLES[mailType]}</h3>
            <p className="text-sm text-slate-500 mt-0.5">To: <strong>{trainer.name}</strong> Ã‚Â· {trainer.email}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {mailType === 'mail1' && (
            <div className="bg-slate-50 rounded-xl p-4 space-y-3 border border-slate-200">
              <div className="flex items-center gap-3">
                <input type="checkbox" id="hasDetails" checked={hasDetails} onChange={e => setHasDetails(e.target.checked)} className="w-4 h-4" />
                <label htmlFor="hasDetails" className="text-sm font-semibold text-slate-700 cursor-pointer">Client has shared training details</label>
              </div>
              {hasDetails && (
                <div className="grid grid-cols-2 gap-3 pt-2">
                  <div><label className="label">Domain</label><input className="input" value={details.domain} onChange={e => setDetails(d => ({...d, domain: e.target.value}))} /></div>
                  <div><label className="label">Duration</label><input className="input" placeholder="e.g. 3 days / 20 hrs" value={details.duration} onChange={e => setDetails(d => ({...d, duration: e.target.value}))} /></div>
                  <div><label className="label">Mode</label>
                    <select className="input" value={details.mode} onChange={e => setDetails(d => ({...d, mode: e.target.value}))}>
                      <option>Online</option><option>Offline</option><option>Hybrid</option>
                    </select>
                  </div>
                  <div><label className="label">Participants</label><input className="input" placeholder="e.g. 20" value={details.participants} onChange={e => setDetails(d => ({...d, participants: e.target.value}))} /></div>
                </div>
              )}
            </div>
          )}

          {mailType === 'mail2' && (
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="label">Client Email *</label>
                  <input
                    className="input"
                    type="email"
                    placeholder="client@company.com"
                    value={clientEmail}
                    onChange={e => setClientEmail(e.target.value)}
                  />
                </div>
                <div>
                  <label className="label">Client Name / Company</label>
                  <input
                    className="input"
                    placeholder="Client name or company"
                    value={clientName}
                    onChange={e => setClientName(e.target.value)}
                  />
                </div>
              </div>
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700">
                After this trainer replies with slots, Clahan will automatically send those slots to this client.
              </p>
              <label className="label">Trainer's Available Dates (from their reply)</label>
              <textarea className="input resize-none" rows={3}
                placeholder="Ã¢â‚¬Â¢ Monday 10 AM Ã¢â‚¬â€œ 12 PM&#10;Ã¢â‚¬Â¢ Wednesday 2 PM Ã¢â‚¬â€œ 4 PM&#10;Ã¢â‚¬Â¢ Friday anytime"
                value={trainerDates} onChange={e => setTrainerDates(e.target.value)} />
            </div>
          )}

          {mailType === 'mail3' && (
            <div className="bg-slate-50 rounded-xl p-4 space-y-3 border border-slate-200">
              <div className="grid grid-cols-3 gap-2">
                {['Google Meet', 'MS Teams', 'Zoom'].map(p => (
                  <button key={p} type="button" onClick={() => setPlatform(p)}
                    className={clsx('p-2 rounded-xl border-2 text-xs font-semibold transition-all',
                      platform === p ? 'bg-blue-500 text-white border-blue-500' : 'bg-white border-slate-200 text-slate-600 hover:border-blue-300')}>
                    {p === 'Zoom' ? 'Ã°Å¸â€œÂ¹' : p === 'MS Teams' ? 'Ã°Å¸â€™Â¼' : 'Ã°Å¸Å½Â¥'} {p}
                  </button>
                ))}
              </div>
              <div><label className="label">Date & Time</label><input type="datetime-local" className="input" value={dateTime} onChange={e => setDateTime(e.target.value)} /></div>
              <div><label className="label">Meeting Link</label><input className="input" placeholder="https://meet.google.com/..." value={interviewLink} onChange={e => setInterviewLink(e.target.value)} /></div>
            </div>
          )}

          {mailType === 'mail7_confirm' && (
            <div className="bg-slate-50 rounded-xl p-4 space-y-3 border border-slate-200">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide flex items-center gap-1.5">
                <PhoneCall className="w-3.5 h-3.5" /> Contact Person Details
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label">Contact Name</label><input className="input" placeholder="e.g. Rahul Sharma" value={contactName} onChange={e => setContactName(e.target.value)} /></div>
                <div><label className="label">Phone Number</label><input className="input" placeholder="e.g. +91 98765 43210" value={contactPhone} onChange={e => setContactPhone(e.target.value)} /></div>
                <div className="col-span-2"><label className="label">Contact Email</label><input className="input" placeholder="e.g. rahul@company.com" value={contactEmail} onChange={e => setContactEmail(e.target.value)} /></div>
              </div>
              <div className="border-t border-slate-200 pt-3">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Training Schedule</p>
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="label">Training Date</label><input type="date" className="input" value={trainingDate} onChange={e => setTrainingDate(e.target.value)} /></div>
                  <div><label className="label">Venue / Platform</label><input className="input" placeholder="e.g. Client Office, Bengaluru" value={venue} onChange={e => setVenue(e.target.value)} /></div>
                </div>
              </div>
            </div>
          )}

          <div>
            <p className="label mb-1">{generationMode === 'ai' ? 'AI Email Preview' : 'Approved Template Preview'}</p>
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
              {aiGenerating ? <p className="text-sm text-violet-700">Generating AI email...</p> : <>
                <p className="text-xs text-slate-400 mb-1 font-semibold">Subject: <span className="text-slate-700 font-normal">{aiMail?.subject || preview.subject}</span></p>
                <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed mt-2">{aiMail?.body || preview.body}</pre>
              </>}
            </div>
          </div>
        </div>

        <div className="flex gap-3 p-5 border-t border-slate-100 sticky bottom-0 bg-white">
          <button onClick={handleSend} disabled={loading || aiGenerating || (generationMode === 'ai' && !aiMail)}
            className="flex items-center gap-2 justify-center flex-1 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm transition-all disabled:opacity-60">
            {loading ? <><Loader2 className="w-4 h-4 animate-spin" /> Sending...</> : <><Send className="w-4 h-4" /> Send Email</>}
          </button>
          <button onClick={onClose} className="px-4 py-2.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-sm transition-all">
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Thread Modal Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function getTocAccuracy(tocData, form, req) {
  if (!tocData) return null

  const text = [
    tocData.title,
    tocData.subtitle,
    tocData.overview,
    ...(tocData.prerequisites || []),
    ...(tocData.learning_outcomes || []),
    ...(tocData.tools_software || []),
    ...(tocData.days || []).flatMap(day => [
      day.title,
      day.morning_session?.title,
      day.afternoon_session?.title,
      ...(day.morning_session?.topics || []).map(topic => topic.topic),
      ...(day.afternoon_session?.topics || []).map(topic => topic.topic),
    ]),
  ].filter(Boolean).join(' ').toLowerCase()

  const requestedDays = Number(form.duration_days) || 0
  const actualDays = (tocData.days || []).length
  const technology = String(req?.technology_needed || '').toLowerCase().trim()
  const customTopics = String(form.custom_topics || '')
    .split(/[,;\n]/)
    .map(item => item.trim().toLowerCase())
    .filter(item => item.length > 2)

  const checks = [
    {
      label: 'Technology match',
      ok: !technology || text.includes(technology),
      detail: technology ? `Looks for ${req.technology_needed}` : 'No technology provided',
    },
    {
      label: 'Duration match',
      ok: requestedDays > 0 && actualDays === requestedDays,
      detail: `${actualDays || 0} of ${requestedDays || '-'} days generated`,
    },
    {
      label: 'Day-wise structure',
      ok: actualDays > 0 && (tocData.days || []).every(day => day.morning_session && day.afternoon_session),
      detail: 'Morning and afternoon sessions available',
    },
    {
      label: 'Hands-on coverage',
      ok: /\blab|hands-on|exercise|practice|capstone\b/.test(text),
      detail: 'Checks for labs, exercises, or capstone work',
    },
    {
      label: 'Outcomes and prerequisites',
      ok: (tocData.learning_outcomes || []).length >= 3 && (tocData.prerequisites || []).length >= 2,
      detail: 'Client-ready learning outcomes included',
    },
  ]

  if (form.toc_type === 'custom') {
    const matched = customTopics.filter(topic => text.includes(topic))
    checks.push({
      label: 'Custom topic coverage',
      ok: customTopics.length > 0 && matched.length === customTopics.length,
      detail: `${matched.length} of ${customTopics.length} custom topics covered`,
    })
  }

  const score = Math.round((checks.filter(check => check.ok).length / checks.length) * 100)
  return { score, checks }
}

// TOC Generator Modal
function TocModal({ trainer, req, onClose, generationMode = 'template' }) {
  const [form, setForm] = useState({
    duration_days: req?.duration_days || (req?.duration_hours ? Math.max(1, Math.ceil(Number(req.duration_hours) / 8)) : 3),
    training_dates: req?.training_dates || req?.preferred_dates || req?.timeline_start || '',
    timing: req?.timing || req?.schedule || '',
    audience_level: req?.audience_level || req?.level || 'intermediate',
    mode: req?.mode || req?.training_mode || 'Online',
    toc_type: 'standard',
    custom_topics: '',
    client_notes: req?.client_notes || req?.job_description || req?.description || req?.content_scope || '',
    cloud_provider: req?.cloud_provider || '',
    cloud_region: req?.cloud_region || '',
    lab_hours_per_day: req?.lab_hours_per_day || '',
    training_hours_per_day: req?.training_hours_per_day || req?.hours_per_day || '',
    participant_count: req?.participant_count || req?.participants || req?.batch_size || '',
    fx_rate: req?.fx_rate || '',
  })
  const [tocId, setTocId] = useState('')
  const [tocData, setTocData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [costDownloading, setCostDownloading] = useState(false)
  const tocAccuracy = getTocAccuracy(tocData, form, req)

  const update = (key, value) => {
    setForm(prev => ({ ...prev, [key]: value }))
    setTocId('')
    setTocData(null)
  }

  const updateCost = (key, value) => setForm(prev => ({ ...prev, [key]: value }))

  const handleGenerate = async () => {
    if (!form.duration_days || Number(form.duration_days) < 1) return toast.error('Enter a valid duration')
    if (form.toc_type === 'custom' && !form.custom_topics.trim()) return toast.error('Add custom topics for custom TOC mode')

    setLoading(true)
    try {
      const res = await api.post('/toc/generate', {
        requirement_id: req.requirement_id,
        trainer_id: trainer.trainer_id,
        trainer_name: trainer.name,
        trainer_email: trainer.email,
        technology: req.technology_needed,
        duration_days: Number(form.duration_days),
        level: form.audience_level,
        audience_level: form.audience_level,
        mode: form.mode,
        training_dates: form.training_dates,
        timing: form.timing,
        toc_type: form.toc_type,
        custom_topics: form.custom_topics,
        client_notes: form.client_notes,
        generation_mode: generationMode === 'ai' ? 'ai' : 'template',
        hours_per_day: form.training_hours_per_day ? Number(form.training_hours_per_day) : null,
        participant_count: Number(form.participant_count),
      })
      setTocId(res.data.toc_id)
      setTocData(res.data.toc_data)
      if (['requires_review', 'requires_regeneration'].includes(res.data.toc_data?.quality?.status)) toast.error('TOC draft needs review: ' + [...(res.data.toc_data.quality.validation_errors || []), ...(res.data.toc_data.quality.review_warnings || [])].join('; '), { duration: 10000 })
      else if (res.data.toc_data?.generation_warning) toast.error(res.data.toc_data.generation_warning)
      else toast.success('TOC generated successfully')
    } catch (e) {
      const detail = e.response?.data?.detail
      toast.error((typeof detail === 'object' ? detail.message : detail) || e.message || 'TOC generation failed')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async () => {
    if (!tocData) return
    setDownloading(true)
    try {
      const isDraft = ['requires_review', 'requires_regeneration'].includes(tocData.quality?.status)
      const res = await api.post('/documents/excel/toc', { toc: tocData, draft: isDraft }, { responseType: 'blob' })
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${isDraft ? 'DRAFT_' : ''}${(req.technology_needed || 'training').replace(/[^a-z0-9]+/gi, '_')}_ToC.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Excel download failed')
    } finally {
      setDownloading(false)
    }
  }

  const handleLabCostDownload = async () => {
    if (!tocId) return
    if (Number(form.lab_hours_per_day) <= 0 || Number(form.participant_count) <= 0 || Number(form.fx_rate) <= 0) {
      return toast.error('Lab hours, participants, and FX rate must be positive')
    }
    setCostDownloading(true)
    try {
      const res = await api.post('/toc/generate-lab-cost', {
        toc_id: tocId,
        lab_generation_mode: generationMode === 'ai' ? 'ai' : 'template',
        cloud_provider: form.cloud_provider,
        cloud_region: form.cloud_region,
        hours_per_day: Number(form.lab_hours_per_day),
        participant_count: Number(form.participant_count),
        fx_rate: Number(form.fx_rate),
      }, { responseType: 'blob' })
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${(req.technology_needed || 'training').replace(/[^a-z0-9]+/gi, '_')}_${form.cloud_provider}_lab_cost.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Lab cost download failed')
    } finally {
      setCostDownloading(false)
    }
  }

  const renderSession = (session) => (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <p className="text-sm font-bold text-slate-800">{session?.title || 'Session'}</p>
        <span className="text-xs text-slate-400">{session?.time}</span>
      </div>
      <div className="grid grid-cols-[92px_1fr_70px] gap-2 border-b border-slate-100 pb-1 mb-1 text-[10px] font-black uppercase tracking-wide text-slate-400">
        <span>Time</span>
        <span>Topics Covered</span>
        <span className="text-center">Type</span>
      </div>
      <div className="space-y-1.5">
        {(session?.topics || []).map((topic, i) => (
          <div key={i} className="grid grid-cols-[92px_1fr_70px] gap-2 text-xs">
            <span className="text-slate-400">{topic.time}</span>
            <span className="text-slate-700">{topic.topic}</span>
            <span className={clsx(
              'text-center rounded-full px-2 py-0.5 font-semibold',
              topic.type === 'lab' ? 'bg-emerald-50 text-emerald-700' :
              topic.type === 'break' ? 'bg-slate-100 text-slate-500' :
              topic.type === 'qa' ? 'bg-amber-50 text-amber-700' :
              'bg-blue-50 text-blue-700'
            )}>{topic.type}</span>
          </div>
        ))}
      </div>
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <div>
            <h3 className="font-bold text-lg text-slate-900 flex items-center gap-2">
              <FileText className="w-5 h-5 text-teal-600" /> AI Training TOC Generator
            </h3>
            <p className="text-sm text-slate-500 mt-0.5">{trainer.name} Ã‚Â· {req.technology_needed}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 grid grid-cols-1 lg:grid-cols-[330px_1fr] gap-5">
          <div className="space-y-4">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
              <div>
                <label className="label">Duration Days</label>
                <input type="number" min="1" max="100" className="input" value={form.duration_days}
                  onChange={e => update('duration_days', e.target.value)} />
              </div>
              <div>
                <label className="label">Training Dates</label>
                <input className="input" value={form.training_dates}
                  onChange={e => update('training_dates', e.target.value)}
                  placeholder="e.g. 20-22 Jun 2026" />
              </div>
              <div>
                <label className="label">Training hours per day</label>
                <input type="number" min="0.5" max="24" step="0.5" className="input" value={form.training_hours_per_day}
                  onChange={e => update('training_hours_per_day', e.target.value)} placeholder="Confirmed training hours" />
              </div>
              <div>
                <label className="label">Daily Timing / Hours</label>
                <input className="input" value={form.timing}
                  onChange={e => update('timing', e.target.value)}
                  placeholder="e.g. 9:00 AM - 5:00 PM, 7 hours/day" />
              </div>
              <div>
                <label className="label">Audience Level</label>
                <select className="input" value={form.audience_level} onChange={e => update('audience_level', e.target.value)}>
                  <option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
                  <option value="mixed">Basic + Intermediate + Advanced Mix</option>
                </select>
              </div>
              <div>
                <label className="label">Mode</label>
                <select className="input" value={form.mode} onChange={e => update('mode', e.target.value)}>
                  <option>Online</option>
                  <option>Offline</option>
                  <option>Hybrid</option>
                </select>
              </div>
              <div>
                <label className="label">TOC Type</label>
                <div className="grid grid-cols-2 gap-2">
                  {['standard', 'custom'].map(type => (
                    <button key={type} type="button" onClick={() => update('toc_type', type)}
                      className={clsx('rounded-xl border px-3 py-2 text-xs font-bold capitalize',
                        form.toc_type === type ? 'bg-teal-600 text-white border-teal-600' : 'bg-white text-slate-600 border-slate-200')}>
                      {type}
                    </button>
                  ))}
                </div>
              </div>
              {form.toc_type === 'custom' && (
                <div>
                  <label className="label">Custom Topics</label>
                  <textarea rows={5} className="input resize-none" placeholder="Comma-separated topics or free text"
                    value={form.custom_topics} onChange={e => update('custom_topics', e.target.value)} />
                </div>
              )}
              <div>
                <label className="label">Client Content Scope</label>
                <textarea rows={4} className="input resize-none" placeholder="Basic/intermediate/advanced scope, topics, labs, tools, exclusions"
                  value={form.client_notes} onChange={e => update('client_notes', e.target.value)} />
              </div>
              <div className="border-t border-slate-200 pt-3">
                <p className="mb-2 text-xs font-bold uppercase text-slate-500">Lab Cost Assumptions</p>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="label">Cloud</label>
                    <select className="input" value={form.cloud_provider} onChange={e => { updateCost('cloud_provider', e.target.value); updateCost('cloud_region', '') }}>
                      <option value="">Confirm provider</option>
                      <option value="aws">AWS</option>
                      <option value="azure">Azure</option>
                      <option value="gcp">GCP</option>
                    </select>
                  </div>
                  <div>
                    <label className="label">Cloud region</label>
                    <select className="input" value={form.cloud_region} onChange={e => updateCost('cloud_region', e.target.value)}>
                      <option value="">Confirm region</option>
                      {form.cloud_provider === 'aws' && <option value="ap-south-1">Mumbai</option>}
                      {form.cloud_provider === 'azure' && <option value="central-india">Central India</option>}
                      {form.cloud_provider === 'gcp' && <option value="asia-south1">Mumbai</option>}
                    </select>
                    <label className="label">Lab Hrs/Day</label>
                    <input type="number" min="0.5" step="0.5" className="input" value={form.lab_hours_per_day}
                      onChange={e => updateCost('lab_hours_per_day', e.target.value)} />
                  </div>
                  <div>
                    <label className="label">Participants</label>
                    <input type="number" min="1" className="input" value={form.participant_count}
                      onChange={e => updateCost('participant_count', e.target.value)} />
                  </div>
                  <div>
                    <label className="label">USD to INR</label>
                    <input type="number" min="1" step="0.01" className="input" value={form.fx_rate}
                      onChange={e => updateCost('fx_rate', e.target.value)} />
                  </div>
                </div>
              </div>
            </div>

            <button onClick={handleGenerate} disabled={loading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-teal-600 hover:bg-teal-700 text-white font-bold text-sm transition-all disabled:opacity-60">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              {loading ? 'Generating...' : 'Generate Fresh TOC'}
            </button>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 min-h-[520px]">
            {!tocData ? (
              <div className="h-full flex flex-col items-center justify-center text-center text-slate-400">
                <FileText className="w-12 h-12 mb-3 opacity-30" />
                <p className="font-semibold text-slate-500">TOC preview will appear here</p>
                <p className="text-sm mt-1">Fill the parameters and generate a day-by-day curriculum.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {tocAccuracy && (
                  <div className="bg-white rounded-xl border border-emerald-200 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-bold uppercase tracking-wide text-emerald-700">TOC accuracy check</p>
                        <p className="text-sm text-slate-500 mt-1">Review this before downloading or sending to trainer.</p>
                      </div>
                      <div className="text-right">
                        <p className="text-3xl font-black text-emerald-700">{tocAccuracy.score}%</p>
                        <p className="text-xs font-semibold text-slate-400">estimated fit</p>
                      </div>
                    </div>
                    <div className="mt-3 h-2 rounded-full bg-slate-100 overflow-hidden">
                      <div className="h-full rounded-full bg-emerald-500" style={{ width: `${tocAccuracy.score}%` }} />
                    </div>
                    <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                      {tocAccuracy.checks.map(check => (
                        <div key={check.label} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
                          <p className={clsx('text-xs font-bold', check.ok ? 'text-emerald-700' : 'text-amber-700')}>
                            {check.ok ? 'Pass' : 'Review'} - {check.label}
                          </p>
                          <p className="text-xs text-slate-500 mt-0.5">{check.detail}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div className="bg-white rounded-xl border border-slate-200 p-4">
                  <h4 className="font-bold text-xl text-slate-900">{tocData.title}</h4>
                  <p className="text-sm text-slate-500 mt-1">{tocData.subtitle}</p>
                  <p className="text-sm text-slate-700 mt-3 leading-6">{tocData.overview}</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="bg-white rounded-xl border border-slate-200 p-4">
                    <p className="font-bold text-sm text-slate-800 mb-2">Prerequisites</p>
                    <ul className="text-sm text-slate-600 space-y-1 list-disc pl-4">
                      {(tocData.prerequisites || []).map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  </div>
                  <div className="bg-white rounded-xl border border-slate-200 p-4">
                    <p className="font-bold text-sm text-slate-800 mb-2">Learning Outcomes</p>
                    <ul className="text-sm text-slate-600 space-y-1 list-disc pl-4">
                      {(tocData.learning_outcomes || []).map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  </div>
                </div>

                {(tocData.days || []).map(day => (
                  <div key={day.day} className="space-y-3">
                    <h5 className="font-bold text-blue-700 bg-blue-50 border border-blue-100 rounded-xl px-3 py-2">{day.title}</h5>
                    {renderSession(day.morning_session)}
                    {renderSession(day.afternoon_session)}
                  </div>
                ))}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="bg-white rounded-xl border border-slate-200 p-4">
                    <p className="font-bold text-sm text-slate-800 mb-2">Hiring & Test Preparation</p>
                    <ul className="text-sm text-slate-600 space-y-1 list-disc pl-4">
                      {(tocData.hiring_preparation || []).map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  </div>
                  <div className="bg-white rounded-xl border border-slate-200 p-4">
                    <p className="font-bold text-sm text-slate-800 mb-2">Assessment Plan</p>
                    <ul className="text-sm text-slate-600 space-y-1 list-disc pl-4">
                      {(tocData.assessment_plan || []).map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  </div>
                  <div className="bg-white rounded-xl border border-slate-200 p-4">
                    <p className="font-bold text-sm text-slate-800 mb-2">Tools & Software</p>
                    <div className="flex flex-wrap gap-1.5">
                      {(tocData.tools_software || []).map((item, i) => (
                        <span key={i} className="px-2 py-1 rounded-full bg-slate-100 text-slate-600 text-xs font-semibold">{item}</span>
                      ))}
                    </div>
                  </div>
                  <div className="bg-white rounded-xl border border-slate-200 p-4">
                    <p className="font-bold text-sm text-slate-800 mb-2">Certification Guidance</p>
                    <p className="text-sm text-slate-600">{tocData.certification_guidance}</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-3 p-5 border-t border-slate-100 bg-white">
          <button onClick={handleDownload} disabled={!tocId || downloading}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm transition-all disabled:opacity-50">
            {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Download PDF
          </button>
          <button onClick={handleLabCostDownload} disabled={!tocId || costDownloading}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-semibold text-sm transition-all disabled:opacity-50">
            {costDownloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Lab Cost Excel
          </button>
          <button onClick={onClose} className="ml-auto px-4 py-2.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-sm transition-all">
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

const ISSUER_STORAGE_KEY = 'clahan_invoice_issuer'
const DEFAULT_COMPANY_NAME = 'BEULIX SOLUTIONS PRIVATE LIMITED'

function issuerDefaults(req) {
  const saved = getLS(ISSUER_STORAGE_KEY) || {}
  return {
    company_name: saved.company_name || req?.company_name || DEFAULT_COMPANY_NAME,
    company_address: saved.company_address || req?.company_address || '',
    company_email: saved.company_email || req?.company_email || '',
    company_contact: saved.company_contact || req?.company_contact || '',
    company_pan: saved.company_pan || req?.company_pan || '',
    company_gst: saved.company_gst || req?.company_gst || '',
    bank_account_no: saved.bank_account_no || req?.bank_account_no || '',
    bank_ifsc: saved.bank_ifsc || req?.bank_ifsc || '',
    place_of_supply: saved.place_of_supply || req?.place_of_supply || '',
    signatory_name: saved.signatory_name || req?.signatory_name || '',
  }
}

function rememberIssuer(form) {
  setLS(ISSUER_STORAGE_KEY, {
    company_name: form.company_name,
    company_address: form.company_address,
    company_email: form.company_email,
    company_contact: form.company_contact,
    company_pan: form.company_pan,
    company_gst: form.company_gst,
    bank_account_no: form.bank_account_no,
    bank_ifsc: form.bank_ifsc,
    place_of_supply: form.place_of_supply,
    signatory_name: form.signatory_name,
  })
}

function issuerError(form) {
  if (!String(form.company_name || '').trim()) return 'Company legal name is required'
  if (!String(form.company_pan || '').trim()) return 'Company PAN is required'
  if (!String(form.company_gst || '').trim()) return 'Company GSTIN is required'
  if (!String(form.bank_account_no || '').trim()) return 'Bank account number is required'
  if (!String(form.bank_ifsc || '').trim()) return 'Bank IFSC is required'
  return ''
}

function issuerPayload(form) {
  return {
    company_name: String(form.company_name || '').trim(),
    company_address: String(form.company_address || '').trim(),
    company_email: String(form.company_email || '').trim(),
    company_contact: String(form.company_contact || '').trim(),
    company_pan: String(form.company_pan || '').trim(),
    company_gst: String(form.company_gst || '').trim(),
    bank_account_no: String(form.bank_account_no || '').trim(),
    bank_ifsc: String(form.bank_ifsc || '').trim(),
    place_of_supply: String(form.place_of_supply || '').trim(),
    signatory_name: String(form.signatory_name || '').trim(),
    gst_number: String(form.company_gst || '').trim(),
  }
}

function initialPoForm(trainer, req, state) {
  const durationDays = req?.duration_days || (req?.duration_hours ? Math.max(1, Number(req.duration_hours) / 8) : 1)
  return {
    ...issuerDefaults(req),
    client_name: req?.client_company || req?.client_name || '',
    training_dates: state?.trainingDate || req?.training_dates || req?.timeline_start || '',
    duration_days: durationDays,
    mode: req?.mode || 'Online',
    day_rate: trainer?.day_rate || req?.budget_per_day || '',
    total_amount: req?.budget_total || '',
    client_po_number: state?.clientPoNumber || req?.client_po_number || '',
    client_po_date: state?.clientPoDate || req?.client_po_date || '',
    client_billing_address: req?.client_billing_address || '',
    client_gstin: req?.client_gstin || '',
    gst_rate: 18,
    client_po_notes: '',
    payment_terms: 'Payment will be processed within 30 days from successful completion of training and receipt of a valid invoice.',
  }
}

function PurchaseOrderModal({ trainer, req, state, onClose, onStageChange }) {
  const [form, setForm] = useState(() => initialPoForm(trainer, req, state))
  const [po, setPo] = useState(null)
  const [invoice, setInvoice] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [invoiceBusy, setInvoiceBusy] = useState('')

  const update = (key, value) => setForm(prev => ({ ...prev, [key]: value }))
  const durationDays = Number(form.duration_days || 0)
  const dayRate = Number(form.day_rate || 0)
  const overrideTotal = Number(form.total_amount || 0)
  const subtotal = overrideTotal > 0 ? overrideTotal : durationDays * dayRate
  const gstRate = Number(form.gst_rate || 0)
  const gst = subtotal * gstRate / 100
  const grandTotal = subtotal + gst
  const lineRate = dayRate || (durationDays ? subtotal / durationDays : subtotal)

  const payload = () => ({
    trainer_id: trainer.trainer_id,
    requirement_id: req.requirement_id,
    client_name: form.client_name,
    client_email: req.client_email,
    training_dates: form.training_dates,
    duration: String(form.duration_days || ''),
    mode: form.mode,
    day_rate: dayRate,
    total_amount: subtotal,
    gst_rate: gstRate,
    client_po_number: form.client_po_number.trim(),
    client_po_date: form.client_po_date,
    client_billing_address: form.client_billing_address,
    client_gstin: form.client_gstin,
    payment_terms: form.payment_terms,
    notes: form.client_po_notes,
    ...issuerPayload(form),
    items: [{
      description: `${req.technology_needed || 'Training'} Training`,
      hsn_sac: '999293',
      quantity: durationDays || 1,
      rate: lineRate,
      amount: subtotal,
    }],
  })

  const createPo = async () => {
    const missingIssuer = issuerError(form)
    if (missingIssuer) return toast.error(missingIssuer)
    if (!form.client_name.trim()) return toast.error('Client name is required')
    if (!form.training_dates.trim()) return toast.error('Training dates are required')
    if (!Number(form.duration_days || 0)) return toast.error('Duration is required')
    if (subtotal <= 0) return toast.error('Enter day rate or total amount')

    setGenerating(true)
    try {
      const res = await api.post('/purchase-orders/generate', payload())
      const generated = res.data.purchase_order
      setPo(generated)
      rememberIssuer(form)
      toast.success(`PO ${generated.po_number} generated`)
      return generated
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'PO generation failed')
      return null
    } finally {
      setGenerating(false)
    }
  }

  const ensurePo = async () => po || await createPo()

  const ensureInvoice = async () => {
    const missingIssuer = issuerError(form)
    if (missingIssuer) {
      toast.error(missingIssuer)
      return null
    }
    if (!req?.client_email) {
      toast.error('Client email is required before invoice can be sent')
      return null
    }
    if (invoice?.invoice_id) return invoice
    const clientPoNumber = form.client_po_number.trim()
    const current = clientPoNumber ? null : await ensurePo()
    if (!clientPoNumber && !current?.po_id) return null
    const res = clientPoNumber
      ? await api.post(`/requirements/${req.requirement_id}/client-po/generate-invoice`, {
          trainer_id: trainer.trainer_id,
          client_email: req.client_email,
          client_name: req.client_company || req.client_name || form.client_name,
          client_po_number: clientPoNumber,
          client_po_date: form.client_po_date,
          client_billing_address: form.client_billing_address,
          client_gstin: form.client_gstin,
          training_dates: form.training_dates,
          duration_days: durationDays || 1,
          mode: form.mode,
          day_rate: dayRate,
          total_amount: subtotal,
          gst_rate: gstRate,
          payment_terms: form.payment_terms,
          client_po_notes: form.client_po_notes,
          items: payload().items,
          ...issuerPayload(form),
        })
      : await api.post(`/purchase-orders/${current.po_id}/generate-invoice`, {
          gst_rate: gstRate,
          ...issuerPayload(form),
        })
    const generated = res.data.invoice
    setInvoice(generated)
    rememberIssuer(form)
    onStageChange?.('invoice_generated', {
      invoiceGeneratedAt: Date.now(),
      invoiceId: generated.invoice_id,
      invoiceNumber: generated.invoice_number,
    })
    toast.success(`Invoice ${generated.invoice_number} generated`)
    return generated
  }

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const current = await ensurePo()
      if (!current?.po_id) return
      const res = await api.get(`/purchase-orders/${current.po_id}/download`, { responseType: 'blob' })
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${current.po_number}_${trainer.name || 'trainer'}.pdf`.replace(/[^a-z0-9._-]+/gi, '_')
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'PO download failed')
    } finally {
      setDownloading(false)
    }
  }

  const handleGenerateInvoice = async () => {
    setInvoiceBusy('generate')
    try {
      if (form.client_po_number.trim() && subtotal <= 0) return toast.error('Enter the client PO amount before generating invoice')
      await ensureInvoice()
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Invoice generation failed')
    } finally {
      setInvoiceBusy('')
    }
  }

  const handleDownloadInvoice = async () => {
    setInvoiceBusy('download')
    try {
      const current = await ensureInvoice()
      if (!current?.invoice_id) return
      const res = await api.get(`/invoices/${current.invoice_id}/download`, { responseType: 'blob' })
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${current.invoice_number}_${req.client_company || req.client_name || 'client'}.pdf`.replace(/[^a-z0-9._-]+/gi, '_')
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Invoice download failed')
    } finally {
      setInvoiceBusy('')
    }
  }

  const handleSendInvoice = async () => {
    setInvoiceBusy('send')
    try {
      const current = await ensureInvoice()
      if (!current?.invoice_id) return
      const res = await api.post(`/invoices/${current.invoice_id}/send`, {})
      setInvoice(res.data.invoice)
      onStageChange?.('invoice_sent', {
        invoiceSentAt: Date.now(),
        invoiceId: res.data.invoice?.invoice_id || current.invoice_id,
        invoiceNumber: res.data.invoice?.invoice_number || current.invoice_number,
      })
      toast.success(`Invoice sent to ${req.client_email}`)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Invoice send failed')
    } finally {
      setInvoiceBusy('')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <div>
            <h3 className="font-bold text-lg text-slate-900">Generate Purchase Order</h3>
            <p className="text-sm text-slate-500 mt-0.5">{trainer.name} Ã‚Â· {req.technology_needed}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="label">Client Name</label>
              <input className="input" value={form.client_name} onChange={e => update('client_name', e.target.value)} placeholder="Client / company name" />
            </div>
            <div>
              <label className="label">Training Dates</label>
              <input className="input" value={form.training_dates} onChange={e => update('training_dates', e.target.value)} placeholder="e.g. 20-22 May 2026" />
            </div>
            <div>
              <label className="label">Duration Days</label>
              <input type="number" min="0.25" step="0.25" className="input" value={form.duration_days} onChange={e => update('duration_days', e.target.value)} />
            </div>
            <div>
              <label className="label">Mode</label>
              <select className="input" value={form.mode} onChange={e => update('mode', e.target.value)}>
                <option>Online</option>
                <option>Offline</option>
                <option>Hybrid</option>
              </select>
            </div>
            <div>
              <label className="label">Day Rate</label>
              <input type="number" min="0" className="input" value={form.day_rate} onChange={e => update('day_rate', e.target.value)} placeholder="Trainer day rate" />
            </div>
            <div>
              <label className="label">Total Override</label>
              <input type="number" min="0" className="input" value={form.total_amount} onChange={e => update('total_amount', e.target.value)} placeholder="Optional fixed total" />
            </div>
            <div>
              <label className="label">Client PO Number</label>
              <input className="input" value={form.client_po_number} onChange={e => update('client_po_number', e.target.value)} placeholder="PO from client" />
            </div>
            <div>
              <label className="label">Client PO Date</label>
              <input className="input" value={form.client_po_date} onChange={e => update('client_po_date', e.target.value)} placeholder="e.g. 04 Jun 2026" />
            </div>
            <div>
              <label className="label">Client GSTIN</label>
              <input className="input" value={form.client_gstin} onChange={e => update('client_gstin', e.target.value)} placeholder="Client tax ID" />
            </div>
            <div>
              <label className="label">GST Rate %</label>
              <input type="number" min="0" className="input" value={form.gst_rate} onChange={e => update('gst_rate', e.target.value)} />
            </div>
            <div className="md:col-span-2">
              <label className="label">Client Billing Address</label>
              <textarea rows={2} className="input resize-none" value={form.client_billing_address} onChange={e => update('client_billing_address', e.target.value)} placeholder="Billing address from client PO" />
            </div>
            <div className="md:col-span-2 rounded-xl border border-slate-200 bg-slate-50 p-3 grid grid-cols-1 md:grid-cols-2 gap-3">
              <p className="md:col-span-2 text-xs font-bold uppercase tracking-wide text-slate-500">Your company, printed on the invoice</p>
              <div>
                <label className="label">Legal Name</label>
                <input className="input" value={form.company_name} onChange={e => update('company_name', e.target.value)} placeholder="Company legal name" />
              </div>
              <div>
                <label className="label">Signatory</label>
                <input className="input" value={form.signatory_name} onChange={e => update('signatory_name', e.target.value)} placeholder="Authorized signatory" />
              </div>
              <div>
                <label className="label">Company PAN</label>
                <input className="input" value={form.company_pan} onChange={e => update('company_pan', e.target.value)} placeholder="Company PAN" />
              </div>
              <div>
                <label className="label">Company GSTIN</label>
                <input className="input" value={form.company_gst} onChange={e => update('company_gst', e.target.value)} placeholder="Company GSTIN" />
              </div>
              <div>
                <label className="label">Bank Account Number</label>
                <input className="input" value={form.bank_account_no} onChange={e => update('bank_account_no', e.target.value)} placeholder="Account number" />
              </div>
              <div>
                <label className="label">Bank IFSC</label>
                <input className="input" value={form.bank_ifsc} onChange={e => update('bank_ifsc', e.target.value)} placeholder="IFSC code" />
              </div>
              <div>
                <label className="label">Company Email</label>
                <input className="input" value={form.company_email} onChange={e => update('company_email', e.target.value)} placeholder="accounts@company.com" />
              </div>
              <div>
                <label className="label">Company Phone</label>
                <input className="input" value={form.company_contact} onChange={e => update('company_contact', e.target.value)} placeholder="Contact number" />
              </div>
              <div>
                <label className="label">Place of Supply</label>
                <input className="input" value={form.place_of_supply} onChange={e => update('place_of_supply', e.target.value)} placeholder="State" />
              </div>
              <div className="md:col-span-2">
                <label className="label">Company Address</label>
                <textarea rows={2} className="input resize-none" value={form.company_address} onChange={e => update('company_address', e.target.value)} placeholder="Registered address" />
              </div>
            </div>
            <div className="md:col-span-2">
              <label className="label">Payment Terms</label>
              <textarea rows={3} className="input resize-none" value={form.payment_terms} onChange={e => update('payment_terms', e.target.value)} />
            </div>
            <div className="md:col-span-2">
              <label className="label">Client PO Notes</label>
              <textarea rows={2} className="input resize-none" value={form.client_po_notes} onChange={e => update('client_po_notes', e.target.value)} placeholder="Any scope, PO reference, or billing notes from client" />
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div>
                <p className="text-xs text-slate-400 font-semibold uppercase">Subtotal</p>
                <p className="font-bold text-slate-900">{money(subtotal)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-400 font-semibold uppercase">GST {gstRate}%</p>
                <p className="font-bold text-slate-900">{money(gst)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-400 font-semibold uppercase">Grand Total</p>
                <p className="font-bold text-emerald-700">{money(grandTotal)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-400 font-semibold uppercase">PO Status</p>
                <p className="font-bold text-slate-900">{po ? `${po.po_number} Ã‚Â· ${po.status}` : 'Not generated'}</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
            <p className="text-xs text-blue-700 font-semibold uppercase">Client Invoice</p>
            <p className="mt-1 text-sm font-bold text-cyan-900">
              {invoice ? `${invoice.invoice_number} Ã‚Â· ${invoice.status}` : req.client_email ? `Ready for ${req.client_email}` : 'Client email missing'}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 p-5 border-t border-slate-100 bg-white">
          <button onClick={createPo} disabled={generating}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm disabled:opacity-50">
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
            Generate PDF
          </button>
          <button onClick={handleDownload} disabled={generating || downloading}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm disabled:opacity-50">
            {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Download
          </button>
          <button onClick={handleGenerateInvoice} disabled={!!invoiceBusy || generating}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-cyan-700 text-white font-semibold text-sm disabled:opacity-50">
            {invoiceBusy === 'generate' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
            {form.client_po_number.trim() ? 'Generate Invoice From Client PO' : 'Generate Invoice'}
          </button>
          <button onClick={handleDownloadInvoice} disabled={!!invoiceBusy || generating}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-700 hover:bg-slate-800 text-white font-semibold text-sm disabled:opacity-50">
            {invoiceBusy === 'download' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Download Invoice
          </button>
          <button onClick={handleSendInvoice} disabled={!!invoiceBusy || generating || !req.client_email}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-teal-600 hover:bg-teal-700 text-white font-semibold text-sm disabled:opacity-50">
            {invoiceBusy === 'send' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Send Invoice to Client
          </button>
          <button onClick={onClose} className="ml-auto px-4 py-2.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-sm">
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function ThreadModal({ trainer, req, onClose, onThreadUpdate }) {
  const [thread, setThread] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const loadingRef = useRef(false)
  const lastMessageCountRef = useRef(0)

  useEffect(() => {
    let cancelled = false

    const loadThread = async (silent = false) => {
      if (loadingRef.current) return
      loadingRef.current = true
      if (!silent) setLoading(true)
      try {
        const r = await api.get(`/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}&_ts=${Date.now()}`)
        if (cancelled) return
        const all = r.data.messages || []
        const filtered = all.filter(m => {
          const trainerMatch = !m.trainer_id || String(m.trainer_id) === String(trainer.trainer_id)
          const reqMatch = !m.requirement_id || String(m.requirement_id) === String(req.requirement_id)
          return trainerMatch && reqMatch
        })
        filtered.sort((a, b) => new Date(a.sent_at || 0) - new Date(b.sent_at || 0))
        if (silent && lastMessageCountRef.current && filtered.length > lastMessageCountRef.current) {
          toast.success('New conversation reply received')
        }
        lastMessageCountRef.current = filtered.length
        setThread(filtered)
        onThreadUpdate?.(filtered)
      } catch {
        if (!cancelled && !silent) setThread([])
      } finally {
        if (!cancelled) setLoading(false)
        loadingRef.current = false
      }
    }

    const syncLatestReplies = () => {
      setSyncing(true)
      syncShortlistRepliesIfDue().finally(() => {
        if (cancelled) return
        setSyncing(false)
        loadThread(true)
      })
    }

    loadThread()
    syncLatestReplies()
    const threadInterval = setInterval(() => loadThread(true), THREAD_REFRESH_INTERVAL_MS)
    const syncInterval = setInterval(syncLatestReplies, REPLY_SYNC_THROTTLE_MS)
    return () => {
      cancelled = true
      clearInterval(threadInterval)
      clearInterval(syncInterval)
    }
  }, [trainer.trainer_id, req.requirement_id])

  const STAGE_LABELS = {
    mail1:         '1st Contact',
    mail1_reminder:'Follow-up Reminder',
    mail2:         'Slot Booking',
    mail3:         'Interview Link',
    mail4:         'Selected',
    mail5_ok:      'Selection',
    mail5_no:      'Rejection',
    mail6_toc:     'ToC Request (Auto)',
    mail7_confirm: 'Training Confirmation',
    reply:         'Trainer Reply',
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between p-5 border-b border-slate-100 flex-shrink-0">
          <div>
            <h3 className="font-bold text-lg text-slate-900">Ã°Å¸â€™Â¬ Conversation Thread</h3>
            <p className="text-sm text-slate-500">{trainer.name} Ã‚Â· {req.technology_needed}</p>
            {syncing && (
              <p className="mt-1 flex items-center gap-1 text-xs font-semibold text-violet-600">
                <Loader2 className="h-3 w-3 animate-spin" /> Checking latest inbox replies...
              </p>
            )}
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-slate-400">
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> LoadingÃ¢â‚¬Â¦
            </div>
          ) : thread.length === 0 ? (
            <div className="text-center py-10 text-slate-400">
              <MessageSquare className="w-10 h-10 mx-auto mb-2 opacity-30" />
              <p>No messages yet for this trainer</p>
            </div>
          ) : thread.map((msg, i) => {
            const isSent = msg.direction === 'sent'
            const isReminder = msg.mail_type === 'mail1_reminder'
            return (
              <div key={i} className={clsx(
                'rounded-xl p-4 border',
                isReminder ? 'bg-orange-50 border-orange-200 ml-6' :
                isSent     ? 'bg-blue-50 border-blue-100 ml-6'     : 'bg-slate-50 border-slate-200 mr-6'
              )}>
                <div className="flex items-center justify-between mb-1.5 flex-wrap gap-1">
                  <span className={clsx('text-xs font-bold',
                    isReminder ? 'text-orange-600' : isSent ? 'text-blue-600' : 'text-slate-600'
                  )}>
                    {isReminder ? 'Ã°Å¸â€â€ Reminder sent' : isSent ? 'Ã°Å¸â€œÂ¤ You sent' : 'Ã°Å¸â€œÂ¥ Trainer replied'}
                  </span>
                  <div className="flex items-center gap-2">
                    {msg.mail_type && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-white border border-slate-200 text-slate-500">
                        {STAGE_LABELS[msg.mail_type] || msg.mail_type}
                      </span>
                    )}
                    <span className="text-xs text-slate-400">
                      {msg.sent_at ? new Date(msg.sent_at).toLocaleString() : ''}
                    </span>
                  </div>
                </div>
                <p className="text-xs text-slate-500 mb-1.5">
                  <span className="font-semibold">Subject:</span> {msg.subject}
                </p>
                <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">{msg.body}</pre>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Pipeline Step Bar Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function StepBar({ stage, trainer }) {
  const steps = ['Trainer request', 'Trainer reply', 'Client handoff', 'Meet scheduled', 'Client decision', 'Confirmed', 'PO', 'Invoice sent']
  const stepIndex = STAGES[stage]?.step ?? 0
  const isRejected = stage === 'rejected'
  const isDone     = stage === 'invoice_sent'

  return (
    <div className="flex items-center gap-0 mt-2 flex-wrap">
      {steps.map((s, i) => {
        const realStep   = i + 1
        const isActive   = realStep === stepIndex
        const isComplete = pipelineStepComplete(realStep, stepIndex, trainer)
        const isRejStep  = realStep === 5 && isRejected
        const isFinalDone= realStep === 8 && isDone
        return (
          <div key={i} className="flex items-center">
            <div className={clsx(
              'w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold transition-all',
              isComplete             ? 'bg-blue-500 text-white' :
              isRejStep              ? 'bg-red-500 text-white'  :
              isFinalDone            ? 'bg-green-500 text-white':
              isActive && isRejected ? 'bg-red-500 text-white'  :
              isActive               ? 'bg-blue-500 text-white ring-2 ring-blue-200' :
                                       'bg-slate-200 text-slate-400'
            )}>
              <span className="sr-only">
              {isComplete || isFinalDone ? 'Ã¢Å“â€œ' : isRejStep ? 'Ã¢Å“â€¢' : realStep}
              </span>
              {isComplete || isFinalDone ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> : isRejStep ? <X className="h-3.5 w-3.5" aria-hidden="true" /> : realStep}
            </div>
            <div className="hidden sm:block mx-0.5 text-xs text-slate-400 whitespace-nowrap">{s}</div>
            {i < steps.length - 1 && (
              <div className={clsx('w-3 h-0.5 mx-0.5', isComplete ? 'bg-blue-400' : 'bg-slate-200')} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ AUTO PILOT ENGINE Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
//
// Full auto flow:
//   pending trainers Ã¢â€ â€™ Mail 1 is sent to everyone
//   waiting_reply1 Ã¢â€ â€™ reminders at 6h/12h/24h until a Mail 1 reply arrives
//   positive Mail 1 replies are queued in reply order
//   one queued trainer at a time -> Mail 2 slot booking -> manual interview/select rules
//   rejected trainers are skipped and the next queued trainer starts
//   selected trainer stops the requirement queue, then ToC/confirmation rules continue
//
function InterviewRescheduleStatus({ trainer }) {
  const requested = Boolean(trainer?.reschedule_requested) || String(trainer?.pipeline_status || '').toLowerCase() === 'interview_reschedule_requested'
  if (!requested && !trainer?.reschedule_completed_at) return null

  const slotStatus = String(trainer?.slot_status || '').toLowerCase()
  const failed = slotStatus.includes('failed') || slotStatus.includes('missing') || slotStatus.includes('invalid')
  const completed = Boolean(trainer?.reschedule_completed_at)
  const slotsSent = Boolean(trainer?.reschedule_slots_sent_at)
  const requestedBy = String(trainer?.reschedule_requested_by || '').toLowerCase()
  const message = completed
    ? 'Updated interview link sent to both client and trainer.'
    : failed
      ? 'Reschedule needs attention. Check the delivery error before sending again.'
      : slotsSent
        ? 'New trainer slots sent to the client. Waiting for one slot confirmation.'
        : requestedBy === 'trainer'
          ? 'Trainer requested a reschedule. Waiting for the client to share one alternate slot.'
          : 'Client requested a reschedule. Waiting for the trainer to share three alternate slots.'
  const tone = completed ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : failed ? 'border-red-200 bg-red-50 text-red-800' : 'border-amber-200 bg-amber-50 text-amber-900'

  return <div className={clsx('mt-3 rounded-xl border px-3 py-2 text-xs font-semibold', tone)}>
    <span className="font-bold">Interview reschedule: </span>{message}
  </div>
}

function PipelineProgressSummary({ stage, req, trainer }) {
  const postTrainingStages = ['po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent']
  const afterTraining = postTrainingStages.includes(stage)
  const doneStages = {
    mail1: afterTraining || ['mail1_sent', 'waiting_reply1', 'mail1_replied', 'details_requested', 'details_received', 'waiting_reply2', 'slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail2: afterTraining || ['details_requested', 'details_received', 'waiting_reply2', 'slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail3: afterTraining || ['slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail4: afterTraining || ['selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail5: afterTraining || ['selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail6: afterTraining || ['toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail7: afterTraining || stage === 'training_confirmed',
    po: ['po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent'].includes(stage),
    invoice: ['invoice_generated', 'invoice_sent'].includes(stage),
    invoiceSent: stage === 'invoice_sent',
  }
  const clientEmailSaved = Boolean(req?.client_email)
  const slotStatus = String(trainer?.slot_status || '').toLowerCase()
  // Do not infer delivery from local optimistic state. The API must persist
  // the sent flag, email id, and sent_to_client status before showing done.
  const clientSlotsSent = isClientHandoffDelivered(trainer)
  const clientHandoffRetryPending = !clientSlotsSent && (
    slotStatus === 'client_handoff_retry_pending' ||
    slotStatus === 'client_slot_send_failed' ||
    Boolean(trainer?.client_handoff_retry_after)
  )
  const progressPct = stage === 'rejected' ? 100 : stage === 'invoice_sent' ? 100 :
    stage === 'invoice_generated' ? 95 :
    stage === 'training_confirmed' ? 85 :
    ['client_po_received'].includes(stage) ? 80 :
    ['po_requested'].includes(stage) ? 75 :
    ['selected', 'toc_requested', 'toc_received_pending'].includes(stage) ? 75 :
    stage === 'interview_scheduled' ? 65 :
    clientSlotsSent ? 50 :
    clientHandoffRetryPending || stage === 'slot_booked' ? 40 :
    ['mail1_replied', 'details_requested', 'details_received', 'waiting_reply2'].includes(stage) ? 30 :
    ['mail1_sent', 'waiting_reply1'].includes(stage) ? 15 : 0
  const selectionDelivered = ['interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage)
  const progressLabel = stage === 'stopped_selected'
    ? 'Stopped - role filled'
    : stage === 'rejected'
      ? 'Trainer not selected'
      : stage === 'invoice_sent'
        ? 'Workflow complete - invoice sent to client'
        : stage === 'invoice_generated'
          ? 'Invoice ready to send to client'
          : stage === 'training_confirmed'
            ? 'Invoice is next'
          : stage === 'client_po_received'
            ? 'Training confirmation is next'
            : stage === 'po_requested'
              ? 'Waiting for client PO'
              : ['selected', 'toc_requested', 'toc_received_pending'].includes(stage)
                ? 'PO and final confirmation are next'
                : stage === 'interview_scheduled'
                  ? 'Waiting for the client decision'
                  : clientSlotsSent
                    ? 'Waiting for the client to select a slot'
                    : clientHandoffRetryPending
                      ? 'Client handoff is queued for automatic retry'
                      : stage === 'slot_booked'
                      ? 'Client handoff is next'
                      : ['mail1_replied', 'details_requested', 'details_received', 'waiting_reply2'].includes(stage)
                        ? 'Reviewing trainer details and interview slots'
                        : ['mail1_sent', 'waiting_reply1'].includes(stage)
                          ? 'Waiting for trainer reply'
                          : 'Trainer request is next'
  const commercialStatus = doneStages.invoiceSent
    ? 'Invoice sent'
    : doneStages.invoice
      ? 'Invoice generated'
      : doneStages.po
        ? stage === 'po_requested' ? 'PO requested' : 'PO received'
        : 'Not started'
  const items = [
    { label: 'Trainer request', value: doneStages.mail1 ? 'Sent' : 'Not sent', tone: doneStages.mail1 ? 'good' : 'neutral' },
    { label: 'Client handoff', value: clientSlotsSent ? 'Sent to client' : clientHandoffRetryPending ? 'Queued for retry' : stage === 'slot_booked' ? 'Ready to send' : clientEmailSaved ? 'Waiting for trainer reply' : 'Client email missing', tone: clientSlotsSent ? 'good' : clientHandoffRetryPending ? 'warn' : clientEmailSaved ? 'neutral' : 'warn' },
    { label: 'Interview', value: stage === 'interview_scheduled' ? 'Scheduled' : selectionDelivered ? 'Completed' : 'Not scheduled', tone: selectionDelivered ? 'good' : 'warn' },
    { label: 'PO / invoice', value: commercialStatus, tone: doneStages.invoiceSent ? 'good' : doneStages.invoice ? 'warn' : 'neutral' },
    { label: 'Current stage', value: STAGES[stage]?.label || stage || 'Pending', tone: stage === 'rejected' ? 'bad' : 'neutral' },
  ]

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/80 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Pipeline progress</p>
          <p className="text-sm font-semibold text-slate-900">{progressLabel}</p>
        </div>
        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-bold text-slate-600 ring-1 ring-slate-200">{progressPct}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${progressPct}%` }} />
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {items.map(item => (
          <div key={item.label} className="rounded-lg bg-white px-3 py-2 ring-1 ring-slate-200">
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{item.label}</p>
            <p className={clsx(
              'mt-0.5 truncate text-xs font-semibold',
              item.tone === 'good' ? 'text-emerald-700' :
              item.tone === 'warn' ? 'text-amber-700' :
              item.tone === 'bad' ? 'text-red-700' :
                                    'text-slate-700'
            )}>{item.value}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function useAutoPilot({ trainers, req, states, onStatusUpdate, enabled, allowReminders = false }) {
  const runningRef = useRef(false)
  const statesRef  = useRef(states)
  useEffect(() => { statesRef.current = states }, [states])

  useEffect(() => {
    if (!enabled || !trainers.length || !req) return

    const poll = async () => {
      if (runningRef.current) return
      runningRef.current = true

      try {
        const currentStates = statesRef.current
        const nextStates = { ...currentStates }
        const getStage = trainer => resolveTrainerStage(trainer, req, nextStates[trainer.trainer_id])
        const setStage = (trainer, status, extra = {}) => {
          nextStates[trainer.trainer_id] = { ...(nextStates[trainer.trainer_id] || {}), status, ...extra }
          onStatusUpdate(trainer.trainer_id, status, extra)
        }
        // Proposal shortlist automation ends once a trainer is selected.
        for (const trainer of trainers) {
          const st = getStage(trainer)

          if (st === 'selected' || st === 'toc_requested' || st === 'toc_received_pending' || st === 'training_confirmed') {
            runningRef.current = false
            return
          }
        }

        if (trainers.some(t => ['toc_requested', 'toc_received_pending', 'training_confirmed'].includes(getStage(t)))) {
          runningRef.current = false
          return
        }

        // First outreach is now a broadcast: every shortlisted trainer gets Mail 1.
        const pendingTrainers = trainers.filter(t => getStage(t) === 'pending')
        if (pendingTrainers.length) {
          const sentResults = []
          for (const trainer of pendingTrainers) {
            const { subject, body } = mail1Template(trainer, req, false, {})
            const res = await api.post('/shortlists/send-mail', {
              trainer_id:     trainer.trainer_id,
              trainer_name:   trainer.name,
              to_email:       trainer.email,
              requirement_id: req.requirement_id,
              subject, body,
              mail_type: 'mail1',
              idempotency_key: `mail1:${req.requirement_id}:${trainer.trainer_id}`,
            })
            const firstResult = Array.isArray(res?.data?.results) ? res.data.results[0] : null
            const delivered = res?.data?.success === true && firstResult?.status === 'sent'
            sentResults.push({ trainer, result: res.data })
            if (delivered) {
              setStage(trainer, 'waiting_reply1', { mail1SentAt: Date.now(), reminders: 0 })
            } else {
              showSendStatusToast({
                trainerName: trainer.name,
                result: { success: false, error: firstResult?.error_message || res?.data?.message || 'Email delivery failed' },
                title: 'Mail 1 send failed',
              })
            }
          }
          const deliveredCount = sentResults.filter(item => {
            const firstResult = Array.isArray(item.result?.results) ? item.result.results[0] : null
            return item.result?.success === true && firstResult?.status === 'sent'
          }).length
          const failedCount = pendingTrainers.length - deliveredCount
          if (failedCount) {
            toast.error(`Auto: Mail 1 sent to ${deliveredCount}/${pendingTrainers.length}. ${failedCount} failed.`)
          } else {
            toast(`Auto: Mail 1 sent to all ${pendingTrainers.length} shortlisted trainers`, { icon: 'i', duration: 5000 })
          }
          runningRef.current = false
          return
        }

        // Check all Mail 1 recipients for replies and reminders. Positive
        // replies join the queue; Mail 2 is still sent to only one trainer.
        await syncShortlistRepliesIfDue()
        // Mail 1 is the only browser-originated pipeline email. The inbox
        // service owns every reply, one permitted missing-item follow-up, the
        // client handoff, and interview scheduling. Do not run the retired
        // browser-side Mail 2/Mail 3 branches below this point.
        runningRef.current = false
        return
      } catch (e) {
        toast.error(e.message || 'AutoPilot error')
      }

      runningRef.current = false
    }

    poll()
    const interval = setInterval(poll, SHORTLIST_REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [enabled, trainers, req, allowReminders])
}

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Mode Toggle Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function ModeToggle({ autoMode, onChange }) {
  return (
    <div className="flex items-center gap-3 bg-white border border-slate-200 rounded-2xl px-4 py-3 shadow-sm">
      <span className={clsx('text-sm font-semibold transition-colors', !autoMode ? 'text-blue-700' : 'text-slate-400')}>Manual</span>
      <button onClick={() => onChange(!autoMode)}
        className={clsx('relative w-14 h-7 rounded-full transition-all duration-300 focus:outline-none',
          autoMode ? 'bg-gradient-to-r from-violet-500 to-blue-500' : 'bg-slate-200'
        )}>
        <span className={clsx('absolute top-0.5 left-0.5 w-6 h-6 bg-white rounded-full shadow-md transition-all duration-300 flex items-center justify-center',
          autoMode ? 'translate-x-7' : 'translate-x-0'
        )}>
          {autoMode
            ? <svg className="w-3.5 h-3.5 text-violet-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17H3a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2h-2"/></svg>
            : <svg className="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
          }
        </span>
      </button>
      <div className="flex items-center gap-2">
        <span className={clsx('text-sm font-semibold transition-colors', autoMode ? 'text-violet-700' : 'text-slate-400')}>Auto Pilot</span>
        {autoMode && <span className="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full font-semibold animate-pulse">Ã°Å¸Â¤â€“ Active</span>}
      </div>
    </div>
  )
}

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Trainer Card Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function TrainerCard({ trainer, rank, state, req, onStatusUpdate, onRequirementPatch, autoMode, isActive, generationMode }) {
  const stage     = resolveTrainerStage(trainer, req, state)
  const mail1DeliveryFailed = Boolean(
    String(trainer?.last_mail_error || '').trim() &&
    ['mail1', 'first', 'mail1_reminder'].includes(
      String(trainer?.last_mail_type || trainer?.last_mail_type_attempted || '').trim().toLowerCase()
    ) &&
    !trainer?.mail1_sent_at &&
    !trainer?.mail1_email_id
  )
  const stageInfo = mail1DeliveryFailed
    ? { label: 'Mail 1 Failed', color: 'bg-red-100 text-red-700', step: 0 }
    : (STAGES[stage] || STAGES.pending)
  const [mailModal, setMailModal] = useState(null)
  const [showThread, setShowThread] = useState(false)
  const [showTocModal, setShowTocModal] = useState(false)
  const [showPoModal, setShowPoModal] = useState(false)
  const [sendingClientPo, setSendingClientPo] = useState(false)
  const [sendingClientSlots, setSendingClientSlots] = useState(false)
  const [clientEmailRequest, setClientEmailRequest] = useState(null)

  const BTN = 'flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-white transition-all active:scale-95 shadow-sm'

  const handleRequestClientPo = async () => {
    if (sendingClientPo) return
    if (!req?.client_email) {
      toast.error('Client email is required before requesting PO')
      return
    }
    setSendingClientPo(true)
    try {
      const res = await api.post(`/requirements/${req.requirement_id}/request-client-po`, {
        trainer_id: trainer.trainer_id,
        trainer_name: trainer.name,
        client_email: req.client_email,
        client_name: req.client_name || req.client_company || '',
        training_dates: state?.trainingDate || req.training_dates || req.timeline_start || '',
      })
      toast.success(`PO request sent to ${res.data?.to_email || req.client_email}`)
      onStatusUpdate(trainer.trainer_id, 'po_requested', {
        clientPoRequestedAt: Date.now(),
        clientPoRequestEmailId: res.data?.email_id,
      })
    } catch (e) {
      toast.error(e.message || 'Could not request PO from client')
    } finally {
      setSendingClientPo(false)
    }
  }

  const renderActions = () => {
    if (stage === 'slot_booked' || trainer.slot_status === 'pending_approval' || trainer.slot_status === 'client_handoff_retry_pending') {
      return <ClientHandoffReview requirementId={req.requirement_id} trainer={trainer}
        onDelivered={result => onStatusUpdate(trainer.trainer_id, 'slot_booked', {
          clientSlotsSentAt: Date.now(), clientSlotsEmailId: result.email_id,
          clientSlotText: result.slot_text || trainer.slot_reply_text,
        })} />
    }
    // Ã¢â€â‚¬Ã¢â€â‚¬ ToC received Ã¢â‚¬â€ manual confirmation mail Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    if (stage === 'toc_received_pending') {
      return (
        <div className="mt-3">
          <div className="w-full px-3 py-2 bg-teal-50 border border-teal-200 rounded-xl">
            <span className="text-xs text-teal-700 font-semibold">
              A legacy ToC reply is recorded. No separate ToC or training-confirmation email will be sent.
            </span>
          </div>
        </div>
      )
    }

    if (stage === 'training_confirmed') {
      return (
        <div className="flex flex-wrap gap-2 mt-3">
          <div className="w-full px-3 py-2 bg-green-50 border border-green-200 rounded-xl">
            <span className="text-xs text-green-700 font-semibold">
              Ã°Å¸Å½â€œ All done! Training confirmed and contact details shared with trainer.
            </span>
          </div>
          <button onClick={() => setShowPoModal(true)} className={clsx(BTN, 'bg-slate-900 hover:bg-slate-800')}>
            <FileText className="w-3.5 h-3.5" /> Generate PO
          </button>
          <button onClick={handleRequestClientPo} disabled={sendingClientPo || !req.client_email} className={clsx(BTN, 'bg-blue-600 hover:bg-blue-700 disabled:opacity-60')}>
            {sendingClientPo ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            Request PO from Client
          </button>
        </div>
      )
    }

    if (['po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent'].includes(stage)) {
      return (
        <div className="flex flex-wrap gap-2 mt-3">
          <div className="w-full px-3 py-2 bg-blue-50 border border-blue-200 rounded-xl">
            <span className="text-xs text-blue-700 font-semibold">
              Client PO flow active. Generate the invoice after the client PO is received, then send it to the saved client email.
            </span>
          </div>
          <button onClick={handleRequestClientPo} disabled={sendingClientPo || !req.client_email} className={clsx(BTN, 'bg-blue-600 hover:bg-blue-700 disabled:opacity-60')}>
            {sendingClientPo ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            Resend PO Request
          </button>
          <button onClick={() => setShowPoModal(true)} className={clsx(BTN, 'bg-slate-900 hover:bg-slate-800')}>
            <FileText className="w-3.5 h-3.5" /> Generate / Send Invoice
          </button>
        </div>
      )
    }

    // toc_requested Ã¢â‚¬â€ auto is polling, show waiting
    if (stage === 'toc_requested') {
      return (
        <div className="flex items-center gap-2 px-3 py-2 mt-3 bg-teal-50 border border-teal-200 rounded-xl">
          <Loader2 className="w-3.5 h-3.5 text-teal-500 animate-spin flex-shrink-0" />
          <span className="text-xs text-teal-700 font-medium">
            Training documents are being prepared. The next workflow action will appear when the required update is received.
          </span>
          <span className="sr-only">
            Ã¢ÂÂ³ Waiting for trainer to send ToC/Agenda Ã¢â‚¬â€ auto detects reply and notifies you
          </span>
        </div>
      )
    }

    if (stage === 'stopped_selected') {
      return (
        <div className="px-3 py-2 mt-3 bg-slate-50 border border-slate-200 rounded-xl">
          <span className="text-xs text-slate-600 font-medium">
            Role already filled. Auto mails and WhatsApp messages are stopped for this trainer.
          </span>
        </div>
      )
    }

    if (stage === 'rejected') return null

    if (stage === 'selected') {
      return (
        <div className="px-3 py-2 mt-3 bg-emerald-50 border border-emerald-200 rounded-xl">
          <span className="text-xs text-emerald-700 font-semibold">
            Proposal trainer selected. Shortlist automation is complete for this trainer.
          </span>
        </div>
      )
    }

    // Ã¢â€â‚¬Ã¢â€â‚¬ AUTO MODE Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    if (autoMode) {
      if (stage === 'waiting_reply1') {
        return (
          <div className="space-y-2 mt-3">
            <div className="flex items-center gap-2 px-3 py-2 bg-sky-50 border border-sky-200 rounded-xl">
              <Loader2 className="w-3.5 h-3.5 text-sky-500 animate-spin flex-shrink-0" />
              <span className="relative text-xs text-transparent font-medium">
                <span className="absolute inset-0 flex items-center text-sky-700">Mail 1 is sent. The inbox watches for a reply and sends reminders at 6, 12, and 24 hours.</span>
                Ã¢ÂÂ³ Mail 1 sent Ã¢â‚¬â€ checking replies every 10s while reminders run at 6h, 12h, 24h
              </span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-50 border border-orange-100 rounded-xl">
              <Bell className="w-3 h-3 text-orange-400 flex-shrink-0" />
              <span className="text-xs text-orange-600">Auto reminders: <strong>6h Ã‚Â· 12h Ã‚Â· 24h</strong></span>
            </div>
          </div>
        )
      }

      if (stage === 'mail1_replied') {
        return (
          <div className={clsx(
            'flex items-center gap-2 px-3 py-2 mt-3 rounded-xl border',
            isActive ? 'bg-emerald-50 border-emerald-200' : 'bg-slate-50 border-slate-200'
          )}>
            {isActive ? (
              <Loader2 className="w-3.5 h-3.5 text-emerald-500 animate-spin flex-shrink-0" />
            ) : (
              <Clock className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
            )}
            <span className={clsx('text-xs font-medium', isActive ? 'text-emerald-700' : 'text-slate-500')}>
              {isActive
                ? 'Next Mail 1 responder - checking the required details and three interview slots'
                : 'Replied to Mail 1 - queued until the current trainer pipeline finishes'}
            </span>
          </div>
        )
      }

      if (stage === 'waiting_reply2' || stage === 'slot_booked') {
        const slotStatus = String(trainer?.slot_status || '').toLowerCase()
        const clientHandoffSent = isClientHandoffDelivered(trainer)
        const clientHandoffRetryPending = !clientHandoffSent && (
          slotStatus === 'client_handoff_retry_pending' ||
          slotStatus === 'client_slot_send_failed' ||
          Boolean(trainer?.client_handoff_retry_after)
        )
        const msgs = {
          waiting_reply2: 'Waiting for the trainer reply. If a genuinely required detail is missing, the system sends one follow-up only.',
          slot_booked:    clientHandoffSent
            ? 'Trainer details and interview slots were sent to the client. Waiting for the client to select one slot.'
            : clientHandoffRetryPending
              ? 'Trainer shared three valid interview slots. Client handoff is queued for automatic retry.'
              : state?.slotConfirmed
            ? 'Trainer shared three interview slots. Preparing the client handoff.'
            : 'Waiting for three complete dated interview slots from the trainer.',
        }
        return (
          <div className="space-y-2 mt-3">
            <div className="flex items-center gap-2 px-3 py-2 bg-sky-50 border border-sky-200 rounded-xl">
              <Loader2 className="w-3.5 h-3.5 text-sky-500 animate-spin flex-shrink-0" />
              <span className="text-xs text-sky-700 font-medium">{msgs[stage]}</span>
            </div>
          </div>
        )
      }

      if (stage === 'pending') {
        return (
          <div className="px-3 py-2 mt-3 bg-violet-50 border border-violet-200 rounded-xl">
            <span className="relative text-xs text-transparent font-medium">
              <span className="absolute inset-0 flex items-center text-violet-700">Mail 1 will be sent to shortlisted trainers with the requirement, ToC, and slot request.</span>
              Ã°Å¸Â¤â€“ Mail 1 will be sent with the full shortlist batch
            </span>
          </div>
        )
      }

      if (stage === 'interview_scheduled') {
        return (
          <div className="mt-3">
            <div className="w-full px-3 py-2 bg-purple-50 border border-purple-200 rounded-xl">
              <span className="text-xs text-purple-700 font-semibold">
                The meeting invitation was sent by the inbox workflow. The client reply records the decision; after selection, PO and final confirmation continue the workflow.
              </span>
            </div>
          </div>
        )
      }

      return null
    }

    // Ã¢â€â‚¬Ã¢â€â‚¬ MANUAL MODE Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    return (
      <div className="flex flex-wrap gap-2 mt-3">
        {stage === 'pending' && (
          <button onClick={() => setMailModal('mail1')} className={clsx(BTN, 'bg-blue-600 hover:bg-blue-700')}>
            <Mail className="w-3.5 h-3.5" /> Send Shortlist Mail
          </button>
        )}
        {(stage === 'mail1_sent' || stage === 'waiting_reply1' || stage === 'mail1_replied') && (
          <>
            <button onClick={() => setMailModal('mail1')} className={clsx(BTN, 'bg-slate-500 hover:bg-slate-600')}>
              <Mail className="w-3.5 h-3.5" /> Resend Mail
            </button>
          </>
        )}
        {stage === 'waiting_reply2' && (
          <button onClick={() => setMailModal('mail2_followup')} className={clsx(BTN, 'bg-indigo-500 hover:bg-indigo-600')}>
            <ClipboardList className="w-3.5 h-3.5" /> Ask Details Again
          </button>
        )}
        {(stage === 'details_requested' || stage === 'details_received') && (
          <p className="self-center text-xs font-medium text-slate-500">Mail 1 already requests the required details and three dated slots.</p>
        )}
        {stage === 'slot_booked' && (
          <p className="self-center text-xs font-medium text-slate-500">The inbox workflow sends the client handoff only once after all required trainer details are ready.</p>
        )}
        {stage === 'interview_scheduled' && (
          <p className="self-center text-xs font-medium text-slate-500">The inbox workflow records the client decision and continues to PO after selection.</p>
        )}
      </div>
    )
  }

  const handleMailSent = (next, extra = {}) => {
    if (next === 'selected') {
      onRequirementPatch?.({
        selected_trainer_id: trainer.trainer_id,
        selected_trainer_name: trainer.name || trainer.trainer_name || '',
        selection_status: 'selected',
        status: req?.status || 'active',
      })
    }
    if (next === 'po_requested') {
      onRequirementPatch?.({
        po_request_status: 'requested',
        po_requested_at: new Date().toISOString(),
      })
    }
    if (next === 'invoice_generated' || next === 'invoice_sent' || next === 'client_po_received') {
      onRequirementPatch?.({
        invoice_status: next === 'invoice_sent' ? 'sent' : next === 'invoice_generated' ? 'generated' : req?.invoice_status,
        client_po_status: next === 'invoice_sent' ? 'invoice_sent' : next === 'invoice_generated' ? 'invoice_generated' : 'received',
      })
    }
    onStatusUpdate(trainer.trainer_id, next, extra)
    setMailModal(null)
  }


  const handleSendClientSlots = async ({ slotText = '', clientEmail = '', clientName = '' } = {}) => {
    if (sendingClientSlots) return
    setSendingClientSlots(true)
    try {
      let text = slotText || state?.clientSlotText || ''
      if (!text) {
        const res = await api.get(`/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}`)
        const latestSlotReply = latestReplyAfter(res.data.messages || [], ['mail2', 'mail3'])
        text = latestSlotReply?.body || ''
      }

      const sent = await sendSlotsToClient({ trainer, req, slotText: text, clientEmail, clientName })
      if (sent?.pending_approval) {
        setClientEmailRequest(null)
        toast.success('Package ready. Review and approve it in the shortlist.')
        onStatusUpdate(trainer.trainer_id, 'slot_booked', { clientSlotText: text })
        return
      }
      if (!sent?.success || !sent?.email_id) throw new Error(sent?.error || 'Client slot email was not confirmed as delivered')

      setClientEmailRequest(null)
      toast.success(sent?.already_sent ? 'Slots already sent to client' : 'Trainer slots sent to client')
      onStatusUpdate(trainer.trainer_id, stage, {
        clientSlotsSentAt: Date.now(),
        clientSlotsEmailId: sent.email_id || state?.clientSlotsEmailId,
        clientSlotText: stripQuotedEmail(text),
      })
    } catch (e) {
      const message = e.response?.data?.detail || e.message || 'Could not send trainer slots to client'
      if (String(message).toLowerCase().includes('client email not found')) {
        setClientEmailRequest({ slotText: slotText || state?.clientSlotText || '' })
      } else {
        toast.error(message)
      }
    } finally {
      setSendingClientSlots(false)
    }
  }

  const handleThreadUpdate = messages => {
    if (!messages?.length) return
    const current = state?.status || 'pending'
    const update = (next, extra = {}) => {
      if (current !== next || Object.keys(extra).length) onStatusUpdate(trainer.trainer_id, next, extra)
    }

    const latestDetailsReply = latestReplyAfter(messages, ['mail2_followup'])
    if (latestDetailsReply && hasRequestedTrainerDetails(latestDetailsReply.body, req) && ['waiting_reply2', 'details_requested', 'slot_booked'].includes(current)) {
      update('details_received', {
        detailsAcceptedAt: new Date(latestDetailsReply.sent_at || Date.now()).getTime(),
      })
      return
    }

    const latestMail1Reply = latestReplyAfter(messages, ['mail1', 'mail1_reminder'])
    if (latestMail1Reply && ['pending', 'mail1_sent', 'waiting_reply1'].includes(current)) {
      update('mail1_replied', {
        mail1ReplyAt: new Date(latestMail1Reply.sent_at || Date.now()).getTime(),
      })
      return
    }

    const latestSlotReply = latestReplyAfter(messages, ['mail2', 'mail3'])
    if (latestSlotReply && current === 'slot_booked' && !state?.slotConfirmed) {
      const slotText = stripQuotedEmail(latestSlotReply.body)
      if (!hasProperInterviewSlots(slotText)) {
        const replyTime = new Date(latestSlotReply.sent_at || Date.now()).getTime()
        if (replyTime > (state?.slotClarificationAt || 0)) {
          toast('Mail 1 already requested exactly three dated slots. No duplicate slot clarification was sent.', { icon: 'i', duration: 5000 })
        }
        update('slot_booked', { slotClarificationAt: replyTime })
        return
      }
      update('slot_booked', {
        slotReplyAt: new Date(latestSlotReply.sent_at || Date.now()).getTime(),
        slotConfirmed: true,
        clientSlotText: slotText,
      })
      if (AUTO_SEND_CLIENT_SLOTS && !state?.clientSlotsSentAt) {
        handleSendClientSlots({ slotText })
      }
    }
  }

  return (
    <>
      {mailModal && mailModal !== 'mail6_toc' && (
        <MailModal trainer={trainer} req={req} mailType={mailModal}
          onClose={() => setMailModal(null)}
          onSent={handleMailSent} generationMode={generationMode} />
      )}
      {showThread && <ThreadModal trainer={trainer} req={req} onClose={() => setShowThread(false)} onThreadUpdate={handleThreadUpdate} />}
      {showTocModal && <TocModal trainer={trainer} req={req} generationMode={generationMode} onClose={() => setShowTocModal(false)} />}
      {showPoModal && (
        <PurchaseOrderModal
          trainer={trainer}
          req={req}
         
          onClose={() => setShowPoModal(false)}
          onStageChange={(next, extra) => onStatusUpdate(trainer.trainer_id, next, extra)}
        />
      )}
      {clientEmailRequest && (
        <ClientEmailModal
          loading={sendingClientSlots}
          onClose={() => setClientEmailRequest(null)}
          onSubmit={({ clientEmail, clientName }) =>
            handleSendClientSlots({ ...clientEmailRequest, clientEmail, clientName })
          }
        />
      )}

      <div className={clsx('bg-white rounded-2xl border p-4 transition-all hover:shadow-md',
        stage === 'training_confirmed'   ? 'border-green-300 bg-green-50/30'   :
        stage === 'toc_received_pending' ? 'border-teal-300 bg-teal-50/20'     :
        stage === 'toc_requested'        ? 'border-teal-200 bg-teal-50/10'     :
        stage === 'selected'             ? 'border-emerald-300 bg-emerald-50/20':
        stage === 'stopped_selected'     ? 'border-slate-200 bg-slate-50/40' :
        stage === 'rejected'             ? 'border-red-200 bg-red-50/10' :
        isActive && autoMode             ? 'border-violet-300 ring-2 ring-violet-100' :
        'border-slate-200'
      )}>
        <div className="flex items-start gap-3">
          <div className={clsx('w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 font-bold text-sm',
            rank === 1 ? 'bg-amber-100 text-amber-700' :
            rank === 2 ? 'bg-slate-200 text-slate-600' :
            rank === 3 ? 'bg-orange-100 text-orange-600' : 'bg-slate-100 text-slate-500'
          )}>{rank}</div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center flex-wrap gap-2">
              <span className="font-semibold text-slate-900">{trainer.name}</span>
              {trainer.match_score != null && (
                <span className={clsx('px-2 py-0.5 rounded-lg text-xs font-bold',
                  trainer.match_score >= 80 ? 'bg-emerald-100 text-emerald-700' :
                  trainer.match_score >= 60 ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700'
                )}>{trainer.match_score} pts</span>
              )}
              <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold', stageInfo.color)}>
                <span className="font-bold uppercase opacity-70">Trainer Status:</span>
                {stageInfo.label}
              </span>
              {autoMode && isActive && !['selected','rejected','toc_requested','toc_received_pending','training_confirmed','slot_booked','interview_scheduled','po_requested','client_po_received','invoice_generated','invoice_sent'].includes(stage) && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-violet-100 text-violet-700 animate-pulse">
                  <Wand2 className="h-3.5 w-3.5" /> Automation active
                </span>
              )}
            </div>

            <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500">
              {trainer.email    && <span className="flex items-center gap-1"><Mail  className="w-3 h-3" />{trainer.email}</span>}
              {trainer.phone    && <span className="flex items-center gap-1"><Phone className="w-3 h-3" />{trainer.phone}</span>}
              {trainer.location && <span className="flex items-center gap-1"><MapPin className="w-3 h-3" />{trainer.location}</span>}
              {(trainer.experience_raw || trainer.experience_years) && (
                <span className="flex items-center gap-1"><Clock className="w-3 h-3" />
                  {trainer.experience_raw || `${trainer.experience_years} yrs`}
                </span>
              )}
            </div>

            {trainer.skills?.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {trainer.skills.slice(0, 5).map((s, i) => (
                  <span key={i} className="px-2 py-0.5 rounded-full text-xs bg-blue-50 text-blue-700 border border-blue-100">{s}</span>
                ))}
                {trainer.skills.length > 5 && (
                  <span className="px-2 py-0.5 rounded-full text-xs bg-slate-100 text-slate-500">+{trainer.skills.length - 5}</span>
                )}
              </div>
            )}

            <StepBar stage={stage} trainer={trainer} />
            <PipelineProgressSummary stage={stage} req={req} trainer={trainer} />
            <InterviewRescheduleStatus trainer={trainer} />
            {renderActions()}
          </div>

          <button onClick={() => setShowThread(true)}
            className="flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 transition-all">
            <Eye className="w-3.5 h-3.5" /> Thread
          </button>
        </div>
      </div>
    </>
  )
}

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Main Page Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
function hasRequirementWorkflowChanged(current = {}, incoming = {}) {
  return [
    'status', 'batch_flow', 'batch_type', 'requirement_type', 'pipeline_page',
    'selection_status', 'selected_trainer_id', 'selected_trainer_name',
    'client_po_requested', 'client_po_received', 'batch_confirmed', 'invoice_sent',
  ].some(field => current?.[field] !== incoming?.[field])
}

export default function Shortlist() {
  const targetRequirementId = new URLSearchParams(window.location.search).get('requirement_id') || ''
  const [reqs, setReqs]               = useState([])
  const [selectedReq, setSelectedReq] = useState(null)
  const [trainers, setTrainers]       = useState([])
  const [states, setStates]           = useState({})
  const [autoMode, setAutoMode]       = useState(false)
  const [loadingReqs, setLoadingReqs]         = useState(false)
  const [loadingTrainers, setLoadingTrainers] = useState(false)
  const [clientContactOpen, setClientContactOpen] = useState(false)
  const [savingClientContact, setSavingClientContact] = useState(false)
  const [deletingReqId, setDeletingReqId] = useState('')
  const [allowAutoReminders, setAllowAutoReminders] = useState(false)
  const [generationMode, setGenerationMode] = useState('template')

  useEffect(() => {
    setLoadingReqs(true)
    getAllRequirementsForFlow()
      .then(async r => {
        const list = Array.isArray(r) ? r : []
        const proposalReqs = list.filter(isProposalRequirement)
        setReqs(proposalReqs)
        if (targetRequirementId) {
          const match = list.find(req => String(req.requirement_id) === String(targetRequirementId))
          if (match && isProposalRequirement(match)) {
            setSelectedReq(match)
          } else if (match) {
            if (isLinkedInRequirement(match)) {
              toast('This is a LinkedIn requirement. Opening LinkedIn Pipeline.', { icon: 'i' })
              window.location.replace(`/linkedin-pipeline?requirement_id=${encodeURIComponent(match.requirement_id)}&domain=${encodeURIComponent(match.technology_needed || match.domain || '')}`)
            } else {
              toast('This is a confirmed requirement. Opening Confirmed Flow.', { icon: 'i' })
              window.location.replace(`/shortlist1?requirement_id=${encodeURIComponent(match.requirement_id)}`)
            }
          } else {
            const reqRes = await getRequirement(targetRequirementId)
            const requirement = reqRes.data
            if (isProposalRequirement(requirement)) {
              setSelectedReq(requirement)
              setReqs(prev => prev.some(item => item.requirement_id === requirement.requirement_id) ? prev : [requirement, ...prev])
            } else if (isLinkedInRequirement(requirement)) {
              toast('This is a LinkedIn requirement. Opening LinkedIn Pipeline.', { icon: 'i' })
              window.location.replace(`/linkedin-pipeline?requirement_id=${encodeURIComponent(requirement.requirement_id || targetRequirementId)}&domain=${encodeURIComponent(requirement.technology_needed || requirement.domain || '')}`)
            } else {
              toast('This is a confirmed requirement. Opening Confirmed Flow.', { icon: 'i' })
              window.location.replace(`/shortlist1?requirement_id=${encodeURIComponent(requirement.requirement_id || targetRequirementId)}`)
            }
          }
        }
      })
      .catch(() => {})
      .finally(() => setLoadingReqs(false))
  }, [])

  useEffect(() => {
    let cancelled = false
    api.get('/admin/settings')
      .then(res => {
        if (cancelled) return
        const settings = res.data?.settings || res.data || {}
        setAllowAutoReminders(remindersAllowedFromSettings(settings))
      })
      .catch(() => {
        if (!cancelled) setAllowAutoReminders(false)
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    api.get('/requirements/generation-mode')
      .then(res => setGenerationMode(res.data?.generation_mode === 'ai' ? 'ai' : 'template'))
      .catch(() => setGenerationMode('template'))
  }, [])

  useEffect(() => {
    if (!selectedReq) return
    setLoadingTrainers(true)
    setTrainers([])
    getShortlist(selectedReq.requirement_id)
      .then(r => {
        const list = (r.data.top_trainers || r.data.trainers || []).slice(0, 3)
        setTrainers(list)
        const saved = getLS(`sl_v5_${selectedReq.requirement_id}`) || {}
        const merged = { ...saved }
        list.forEach(trainer => {
          const backendStage = backendAuthoritativeStage(trainer, selectedReq)
          if (backendStage) merged[trainer.trainer_id] = { ...(merged[trainer.trainer_id] || {}), status: backendStage }
        })
        setStates(merged)
      })
      .catch(e => {
        if (e.response?.status === 404) {
          setTrainers([])
          setStates({})
          toast.error(e.response?.data?.detail || 'No shortlist found for this requirement yet')
          return
        }
        toast.error(e.response?.data?.detail || e.message || 'Could not load shortlist')
      })
      .finally(() => setLoadingTrainers(false))
  }, [selectedReq])

  useLiveShortlist(selectedReq?.requirement_id, setTrainers, SHORTLIST_REFRESH_INTERVAL_MS)

  const handleStatusUpdate = (trainerId, newStage, extra = {}) => {
    setStates(prev => {
      const next = { ...prev, [trainerId]: { ...(prev[trainerId] || {}), status: newStage, ...extra } }
      if (selectedReq) setLS(`sl_v5_${selectedReq.requirement_id}`, next)
      return next
    })
  }

  const patchSelectedRequirement = patch => {
    if (!selectedReq || !patch) return
    const updated = { ...selectedReq, ...patch }
    setSelectedReq(updated)
    setReqs(prev => prev.map(item => item.requirement_id === updated.requirement_id ? { ...item, ...patch } : item))
  }

  const handleAutoToggle = val => {
    if (val && selectedReq && !selectedReq.client_email) {
      toast.error('Add client email before Auto Pilot so slot replies can go to the client')
      setClientContactOpen(true)
      return
    }
    setAutoMode(val)
    if (val) {
      toast(
        'Auto Pilot ON\n\nMail 1 goes to all shortlisted trainers. Replies are queued, then Mail 2 onward runs one trainer at a time. Selection stops the requirement queue.',
        { duration: 9000, icon: 'i' }
      )
    } else {
      toast('Manual mode', { icon: 'i' })
    }
  }

  const saveClientContact = async ({ clientEmail, clientName }) => {
    if (!selectedReq) return
    setSavingClientContact(true)
    try {
      const res = await updateRequirement(selectedReq.requirement_id, {
        client_email: clientEmail,
        client_name: clientName,
        client_company: clientName,
      })
      const updated = res.data?.requirement || { ...selectedReq, client_email: clientEmail, client_name: clientName, client_company: clientName }
      setSelectedReq(updated)
      setReqs(prev => prev.map(item => item.requirement_id === updated.requirement_id ? updated : item))
      setClientContactOpen(false)
      const sent = res.data?.client_slot_pending?.sent || 0
      toast.success(sent ? `Client email saved. ${sent} pending slot mail sent.` : 'Client email saved')
    } catch (e) {
      toast.error(e.message || 'Could not save client email')
    } finally {
      setSavingClientContact(false)
    }
  }

  const handleDeleteRequirement = async requirement => {
    if (!requirement?.requirement_id || deletingReqId) return
    const label = requirement.technology_needed || requirement.requirement_id
    if (!globalThis.confirm(`Delete "${label}" from Shortlist? This removes its shortlist and pipeline state.`)) return

    setDeletingReqId(requirement.requirement_id)
    try {
      await deleteRequirement(requirement.requirement_id)
      localStorage.removeItem(`sl_v5_${requirement.requirement_id}`)
      setReqs(prev => prev.filter(item => item.requirement_id !== requirement.requirement_id))
      if (selectedReq?.requirement_id === requirement.requirement_id) {
        setSelectedReq(null)
        setTrainers([])
        setStates({})
        setAutoMode(false)
      }
      toast.success(`${label} deleted`)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Could not delete domain')
    } finally {
      setDeletingReqId('')
    }
  }

  const reload = () => {
    if (!selectedReq) return
    setLoadingTrainers(true)
    getShortlist(selectedReq.requirement_id)
      .then(r => {
        const list = (r.data.top_trainers || r.data.trainers || []).slice(0, 3)
        setTrainers(list)
        setStates(prev => {
          const next = { ...prev }
          list.forEach(trainer => {
            const backendStage = backendAuthoritativeStage(trainer, selectedReq)
            if (backendStage) next[trainer.trainer_id] = { ...(next[trainer.trainer_id] || {}), status: backendStage }
          })
          return next
        })
      })
      .catch(() => {})
      .finally(() => setLoadingTrainers(false))
  }

  const syncReplyStates = async () => {
    if (!selectedReq) return
    await syncShortlistRepliesIfDue()

    try {
      const [requirementRes, res] = await Promise.all([
        getRequirement(selectedReq.requirement_id),
        api.get('/emails', {
        params: { requirement_id: selectedReq.requirement_id, page: 1, limit: 200 },
        }),
      ])
      const refreshedRequirement = requirementRes.data || selectedReq
      setSelectedReq(previous => (
        hasRequirementWorkflowChanged(previous, refreshedRequirement) ? refreshedRequirement : previous
      ))
      setReqs(previous => {
        let changed = false
        const next = previous.map(item => {
          if (item.requirement_id !== refreshedRequirement.requirement_id || !hasRequirementWorkflowChanged(item, refreshedRequirement)) return item
          changed = true
          return refreshedRequirement
        })
        return changed ? next : previous
      })
      const replied = (res.data.emails || []).filter(e => e.reply_received && e.trainer_id)
      if (!replied.length) return

      setStates(prev => {
        const next = { ...prev }
        let changed = false

        for (const email of replied) {
          const trainerId = email.trainer_id
          const trainer = trainers.find(item => String(item.trainer_id) === String(trainerId))
          const backendStage = backendAuthoritativeStage(trainer, refreshedRequirement)
          if (backendStage) {
            if (next[trainerId]?.status !== backendStage) {
              next[trainerId] = { ...(next[trainerId] || {}), status: backendStage }
              changed = true
            }
            continue
          }
          const current = next[trainerId]?.status || 'pending'
          if (current === 'stopped_selected') continue
          const replyAt = email.replied_at ? new Date(email.replied_at).getTime() : Date.now()
          const mailType = email.mail_type || ''
          let status = null
          let extra = {}

          if ((mailType === 'mail2_followup' && ['pending', 'details_requested', 'waiting_reply2'].includes(current))) {
            if (!hasRequestedTrainerDetails(email.reply_text || '', selectedReq)) continue
            status = 'details_received'
          } else if ((['mail2', 'mail3'].includes(mailType) && ['pending', 'slot_booked'].includes(current))) {
            status = 'slot_booked'
            extra = { slotReplyAt: replyAt, slotConfirmed: true }
          } else if ((mailType === 'mail6_toc' && ['pending', 'toc_requested'].includes(current))) {
            status = 'toc_received_pending'
          } else if (['pending', 'mail1_sent', 'waiting_reply1'].includes(current)) {
            status = 'mail1_replied'
            extra = { mail1ReplyAt: replyAt }
          } else if (['details_requested', 'waiting_reply2'].includes(current)) {
            status = 'details_received'
          } else if (current === 'slot_booked') {
            status = 'slot_booked'
            extra = { slotReplyAt: replyAt, slotConfirmed: true }
          } else if (current === 'toc_requested') {
            status = 'toc_received_pending'
          }

          if (status && current !== status) {
            next[trainerId] = { ...(next[trainerId] || {}), status, ...extra }
            changed = true
          }
        }

        if (changed) setLS(`sl_v5_${selectedReq.requirement_id}`, next)
        return changed ? next : prev
      })
    } catch {}
  }

  useEffect(() => {
    if (!selectedReq || autoMode) return
    syncReplyStates()
    const interval = setInterval(syncReplyStates, SHORTLIST_REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [selectedReq?.requirement_id, autoMode])

  const activeTrainerId = (() => {
    const active = trainers.find(t =>
      ['waiting_reply2','slot_booked','interview_scheduled','selected','toc_requested','toc_received_pending'].includes(resolveTrainerStage(t, selectedReq, states[t.trainer_id]))
    )
    if (active) return active.trainer_id

    const queued = trainers
      .filter(t => resolveTrainerStage(t, selectedReq, states[t.trainer_id]) === 'mail1_replied')
      .sort((a, b) => {
        const aTime = states[a.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
        const bTime = states[b.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
        return aTime - bTime || trainers.indexOf(a) - trainers.indexOf(b)
      })
    return queued[0]?.trainer_id || null
  })()

  useAutoPilot({
    trainers,
    req: selectedReq,
    states,
    onStatusUpdate: handleStatusUpdate,
    enabled: autoMode && !!selectedReq,
    allowReminders: allowAutoReminders,
  })

  const selectedTrainerForDomain = selectedReq
    ? trainers.find(t => String(t.trainer_id) === String(selectedReq.selected_trainer_id || '')) ||
      trainers.find(t => ['selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(
        resolveTrainerStage(t, selectedReq, states[t.trainer_id])
      ))
    : null
  const hiringDoneForDomain = Boolean(
    selectedReq && (
      selectedReq.selected_trainer_id ||
      ['selected', 'toc_requested', 'training_confirmed'].includes(String(selectedReq.selection_status || '').toLowerCase()) ||
      selectedTrainerForDomain
    )
  )
  const hiringDoneTrainerName = selectedReq?.selected_trainer_name || selectedTrainerForDomain?.name || selectedTrainerForDomain?.trainer_name || ''

  const workflowOverview = [
    { step: '01', label: 'Trainer request', note: 'Mail 1 sends the available requirement details, ToC, availability request, and exactly three dated interview slots.', color: 'bg-blue-600' },
    { step: '02', label: 'Trainer reply review', note: 'The system checks the reply and sends one follow-up only when a genuinely required item is missing.', color: 'bg-violet-600' },
    { step: '03', label: 'Client handoff and Meet', note: 'The client receives the profile/CV, ToC, requested lab cost, availability, and slots. A Meet link is sent only after a slot is chosen.', color: 'bg-emerald-600' },
    { step: '04', label: 'Confirmation, PO, and invoice', note: 'After the client decision, confirm the batch, request the PO, then send the invoice to the saved client email.', color: 'bg-amber-500' },
  ]

  return (
    <div className="space-y-5">
      {hiringDoneForDomain && (
        <HiringDoneStamp requirement={selectedReq} trainerName={hiringDoneTrainerName} />
      )}
      {clientContactOpen && selectedReq && (
        <ClientEmailModal
          loading={savingClientContact}
          initialEmail={selectedReq.client_email || ''}
          initialName={selectedReq.client_name || selectedReq.client_company || ''}
          title="Client Contact"
          description="Save the client email once. When a trainer replies with slots, Clahan will send those slots to this client automatically."
          submitLabel="Save Client"
          onClose={() => setClientContactOpen(false)}
          onSubmit={saveClientContact}
        />
      )}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <Users className="w-6 h-6 text-blue-500" /> Shortlist Proposal Pipeline
        </h1>
        <p className="text-sm text-slate-500 mt-0.5">
          AI wording is controlled from Dashboard. The workflow reviews trainer replies, permits one needed follow-up, completes the client handoff, schedules the Meet, and tracks PO, confirmation, and invoice.
        </p>
      </div>

      <div className="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-800">
        <span className="font-semibold">The shared AI setting changes email wording only; it never changes workflow rules.</span>
        <span className="ml-2 text-violet-700">AI uses current request facts. Approved wording follows the same current workflow.</span>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <ModeToggle autoMode={autoMode} onChange={handleAutoToggle} />
        <div className={clsx('flex items-center gap-2 rounded-2xl border px-4 py-3 text-xs font-bold uppercase tracking-wide', generationMode === 'ai' ? 'border-violet-300 bg-violet-50 text-violet-800' : 'border-slate-300 bg-slate-50 text-slate-700')}>
          {generationMode === 'ai' ? 'AI wording on' : 'Approved wording'}
          <span className="font-medium normal-case tracking-normal text-slate-500">(managed from Dashboard)</span>
        </div>
        <div className={clsx('flex-1 rounded-2xl border px-4 py-3 text-sm transition-all',
          autoMode ? 'bg-violet-50 border-violet-200 text-violet-700' : 'bg-slate-50 border-slate-200 text-slate-600'
        )}>
          {autoMode ? (
            <span>
              <strong>Auto:</strong> Mail 1 and reminders start here. The inbox workflow sends only a needed missing-item follow-up, client handoff, and interview invitation.{' '}
              <strong>Manual:</strong> Review trainer details, the mail thread, and the final selection decision.
            </span>
          ) : (
            <span><strong>Manual:</strong> You control every step for every trainer.</span>
          )}
        </div>
      </div>

      {/* Workflow overview */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5" /> Workflow overview
        </p>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
          {workflowOverview.map(item => (
            <div key={item.step} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center gap-2">
                <span className={clsx('flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold text-white', item.color)}>{item.step}</span>
                <p className="text-sm font-bold text-slate-800">{item.label}</p>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-600">{item.note}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Requirement selector */}
      {!selectedReq ? (
        <div className="bg-white rounded-2xl border border-slate-200 p-4">
          <p className="text-sm font-semibold text-slate-700 mb-3">Select Requirement</p>
          {loadingReqs ? (
            <div className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin" /> Loading...</div>
          ) : reqs.length === 0 ? (
            <div className="flex items-center gap-2 p-3 bg-amber-50 rounded-xl text-sm text-amber-700">
              <AlertCircle className="w-4 h-4" /> No requirements yet. Go to Find Trainers first.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {reqs.map(r => {
                const trainingDateDisplay = formatRequirementSchedule(r)
                return (
                <div key={r.requirement_id}
                  className="flex items-center gap-2 rounded-xl border bg-white border-slate-200 p-2 transition-all hover:border-blue-300 hover:bg-blue-50 group">
                  <button onClick={() => setSelectedReq(r)}
                    className="flex min-w-0 flex-1 flex-col gap-1 rounded-lg p-1 text-left">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                      <Star className="w-4 h-4 text-blue-500" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-sm truncate text-slate-800">{r.technology_needed}</p>
                      <p className="text-xs text-slate-400">{r.requirement_id} Ã‚Â· Top {r.top_n}</p>
                    </div>
                    <ChevronRight className="w-4 h-4 opacity-30 group-hover:opacity-70 flex-shrink-0" />
                  </div>
                  <div className="flex items-center gap-4 pl-10 text-xs">
                    <div className="flex items-center gap-1.5" style={{ color: trainingDateDisplay !== 'TBD' ? '#4b5563' : '#c4b5fd' }}>
                      <Calendar className="w-3.5 h-3.5" style={{ color: trainingDateDisplay !== 'TBD' ? '#b45309' : '#a78bfa', flexShrink: 0 }} />
                      <span className="truncate">{trainingDateDisplay}</span>
                    </div>
                    {r.client_name && (
                      <div className="flex items-center gap-1.5 text-slate-600">
                        <Users className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
                        <span className="truncate">{r.client_name}</span>
                      </div>
                    )}
                  </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteRequirement(r)}
                    disabled={deletingReqId === r.requirement_id}
                    title={`Delete ${r.technology_needed || 'domain'}`}
                    className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-slate-300 transition-all hover:bg-red-50 hover:text-red-600 disabled:opacity-50">
                    {deletingReqId === r.requirement_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  </button>
                </div>
              )
              })}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h2 className="text-lg font-bold text-slate-900">
                Shortlisted for: <span className="text-blue-600">{selectedReq.technology_needed}</span>
              </h2>
              <div className="flex flex-wrap gap-3 mt-2">
                <p className="text-xs text-slate-400">{selectedReq.requirement_id} Ã‚Â· Top {selectedReq.top_n}</p>
                {(() => {
                  const dateDisplay = formatRequirementSchedule(selectedReq)
                  return (
                    <div className="flex items-center gap-1.5 text-xs" style={{ color: dateDisplay !== 'TBD' ? '#b45309' : '#a78bfa' }}>
                      <Calendar className="w-3.5 h-3.5" />
                      <span>{dateDisplay}</span>
                    </div>
                  )
                })()}
                {selectedReq.client_name && (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-600">
                    <Users className="w-3.5 h-3.5" />
                    <span className="font-semibold">{selectedReq.client_name}</span>
                  </div>
                )}
              </div>
              <div className={clsx('mt-1 inline-flex items-center gap-2 rounded-xl border px-2.5 py-1 text-xs font-semibold',
                selectedReq.client_email ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'
              )}>
                <Mail className="h-3.5 w-3.5" />
                <span>{selectedReq.client_email ? `Client: ${selectedReq.client_email}` : 'Client email missing'}</span>
                <button onClick={() => setClientContactOpen(true)} className="ml-1 underline underline-offset-2">
                  {selectedReq.client_email ? 'Edit' : 'Add'}
                </button>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setSelectedReq(null)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold">
                <ChevronLeft className="w-3.5 h-3.5" /> Back
              </button>
              <button onClick={reload} disabled={loadingTrainers}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold">
                <RefreshCw className={clsx('w-3.5 h-3.5', loadingTrainers && 'animate-spin')} /> Refresh
              </button>
            </div>
          </div>

          <div className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-3 text-xs sm:grid-cols-3">
            <div className="rounded-xl bg-blue-50 px-3 py-2 text-blue-700">
              <p className="font-bold">Trainer pipeline</p>
              <p className="mt-0.5 text-blue-600">Mail 1 includes the requirement, ToC, availability, and three slots.</p>
            </div>
            <div className="rounded-xl bg-emerald-50 px-3 py-2 text-emerald-700">
              <p className="font-bold">Client handoff</p>
              <p className="mt-0.5 text-emerald-600">Profile, ToC, lab cost when requested, and trainer slots.</p>
            </div>
            <div className="rounded-xl bg-blue-50 px-3 py-2 text-blue-700">
              <p className="font-bold">Interview result</p>
              <p className="mt-0.5 text-blue-600">After PO and batch confirmation, the invoice is sent to the client.</p>
            </div>
          </div>

          {loadingTrainers ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="bg-white rounded-2xl border p-4 animate-pulse flex gap-3">
                  <div className="w-9 h-9 rounded-xl bg-slate-100 flex-shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-slate-100 rounded w-1/3" />
                    <div className="h-3 bg-slate-100 rounded w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : trainers.length === 0 ? (
            <div className="bg-white rounded-2xl border p-12 text-center">
              <Users className="w-12 h-12 text-slate-200 mx-auto mb-3" />
              <p className="font-medium text-slate-500">No shortlisted trainers</p>
              <p className="text-sm text-slate-400 mt-1">Run "Shortlist Only" in Find Trainers first</p>
            </div>
          ) : (
            <div className="space-y-3">
              {trainers.map((trainer, i) => (
                <TrainerCard
                  key={trainer.trainer_id}
                  trainer={trainer}
                  rank={i + 1}
                  state={states[trainer.trainer_id] || { status: 'pending' }}
                  req={selectedReq}
                  onStatusUpdate={handleStatusUpdate}
                  onRequirementPatch={patchSelectedRequirement}
                  autoMode={autoMode}
                  generationMode={generationMode}
                  isActive={trainer.trainer_id === activeTrainerId}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
