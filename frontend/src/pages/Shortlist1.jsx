import { useState, useEffect, useRef } from 'react'
import api, { deleteRequirement, getRequirement, getRequirements, getShortlist, updateRequirement } from '../utils/api'
import toast from 'react-hot-toast'
import {
  Users, Mail, Clock, MapPin, Phone,
  ChevronRight, ChevronLeft, Loader2, Send, AlertCircle,
  RefreshCw, Star, MessageSquare, X, Eye,
  Calendar, PartyPopper, ThumbsDown, ClipboardList, Info,
  FileText, CheckCircle2, Bell, PhoneCall, Download, Wand2,
  Sparkles, Bot, Trash2
} from 'lucide-react'
import clsx from 'clsx'
import { formatRequirementSchedule } from '../utils/requirementDates'

// â”€â”€â”€ Gemini AI Helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function generateAIReply({ trainerName, domain, stage, trainerReply, previousMails, fallback }) {
  const templateGuide = `
Template 1 - Trainer Requirement:
Subject: Training Requirement - {Domain}
Body shares the client requirement and asks only for missing/client-requested trainer details such as profile/CV, LinkedIn, availability, commercials, lab support, certifications, or ToC. Do not ask generic interest or experience questions.

Template 1 Reminder:
Subject: [Reminder {Number}] Training Requirement - {Domain}
Body gently follows up because no reply was received.

Template 2 - Client Handoff:
Subject: Trainer Details - {Domain}
Body sends the client exactly what they asked for, such as trainer profile/CV, LinkedIn, commercials, ToC/lab details, and trainer available dates when available.

Template 3 - Interview Slot / Result:
Subject: Interview Slot Booking - {Domain}
Body coordinates discussion/interview slots with date, time, timezone, and meeting link. After client feedback, send selected or rejection update to the trainer.
`

  const prompt = `Generate the next email for the trainer pipeline.

Use the mail template rules below as the source of truth, but write the email naturally and professionally.

Trainer name: ${trainerName}
Domain: ${domain}
Current stage/mail type: ${stage}

Latest trainer reply:
${trainerReply || 'No trainer reply yet.'}

Recent thread:
${(previousMails || []).slice(-4).map(m => `${m.direction === 'sent' ? 'We sent' : 'Trainer replied'}: ${m.subject || ''}\n${(m.body || '').slice(0, 500)}`).join('\n\n') || 'No previous thread context.'}

Template/rules:
${templateGuide}

Strict output rules:
- Address trainer by name: Dear ${trainerName || 'Trainer'},
- Do not use Dear Sir/Madam.
- End with exactly:
Regards,
Clahan Technologies
sujithaofficial585@gmail.com
- Generate only subject and body.
- Format exactly:
SUBJECT: <subject>
BODY:
<body>`

  const response = await api.post('/assistant/chat', {
    system: 'You generate concise professional trainer outreach emails for Clahan Technologies / TrainerSync.',
    messages: [{ role: 'user', content: prompt }],
    feature: 'shortlist_email_generation',
    metadata: { trainerName, domain, stage },
  })
  const text = response.data?.reply || ''
  const subjectMatch = /SUBJECT:\s*(.+)/i.exec(text)
  const bodyMatch = /BODY:\s*([\s\S]+)/i.exec(text)
  return {
    subject: subjectMatch?.[1]?.trim() || fallback?.subject || '',
    body: bodyMatch?.[1]?.trim() || text.trim() || fallback?.body || '',
  }

}

// â”€â”€â”€ localStorage helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function getLS(k) { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }
function setLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} }
function money(v) {
  const n = Number(v || 0)
  return `INR ${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function compactMoney(v) {
  const n = parseMoneyAmount(v)
  if (!n) return ''
  return `INR ${n.toLocaleString('en-IN')}`
}

function extractAvailabilityLines(text = '') {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
  const slotPattern = /\b(slot|available|availability|interview|discussion|am|pm|ist|gmt|utc|monday|tuesday|wednesday|thursday|friday|saturday|sunday|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}[/-]\d{1,2}|\d{1,2}\s+[a-z]{3,})\b/i
  return lines.filter(line => slotPattern.test(line)).slice(0, 6)
}

function cleanTrainerReplyForClient(text = '') {
  return String(text || '')
    .replace(/(?:â‚¹|rs\.?|inr)\s*[\d,]+(?:\.\d+)?/gi, '[Commercial shared separately below]')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .slice(0, 12)
    .join('\n')
}

function trainerClientSummaryForHandoff(text = '') {
  const clean = stripQuotedEmail(String(text || ''))
  const linkedin = (clean.match(/https?:\/\/[^\s<>)]+linkedin\.com[^\s<>)]+/i) || [])[0]
  const lines = ['- Trainer profile/CV: attached/shared for review']
  if (linkedin) lines.push(`- LinkedIn profile: ${linkedin.replace(/[.,;:]$/, '')}`)
  return lines.join('\n')
}

function poDurationText(req = {}) {
  return (
    req.duration_text ||
    req.training_duration ||
    req.duration ||
    (req.duration_hours ? `${req.duration_hours} hours` : '') ||
    (req.duration_days ? `${req.duration_days} days` : '')
  )
}

function requirementFlowType(req = {}) {
  const raw = String(req.batch_flow || req.batch_type || req.requirement_type || req.training_status || '').toLowerCase()
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

const isConfirmedRequirement = req => requirementFlowType(req) === 'confirmed'

async function getAllRequirementsForFlow() {
  const first = await getRequirements({ page: 1, page_size: 100 })
  const firstData = first.data || {}
  const firstItems = firstData.requirements || firstData.items || []
  const pages = Number(firstData.pages || 1)
  if (pages <= 1) return firstItems
  const rest = await Promise.all(
    Array.from({ length: pages - 1 }, (_, index) => getRequirements({ page: index + 2, page_size: 100 }))
  )
  return rest.reduce((items, res) => {
    const data = res.data || {}
    return items.concat(data.requirements || data.items || [])
  }, firstItems)
}

function poCommercialText(req = {}, trainer = {}) {
  const value =
    req.client_budget_per_day ||
    req.budget_per_day ||
    req.budget_total ||
    req.budget ||
    trainer.client_budget_amount ||
    trainer.trainer_target_rate ||
    trainer.day_rate
  const amount = compactMoney(value)
  return amount ? `${amount} per day/session` : ''
}

function channelStatus(label, result, successLabel = 'sent') {
  if (!result) return { label, value: 'Not returned', tone: 'warn', detail: '' }
  const numberDetail = result.to_number ? `To: ${result.to_number}` : (result.teams_email ? `To: ${result.teams_email}` : '')
  const idDetail = result.twilio_sid || result.aisensy_message_id || result.meta_message_id || result.teams_direct_id || result.email_id || ''
  const detail = [numberDetail, idDetail].filter(Boolean).join(' | ')
  if (result.success === true) return { label, value: result.status || successLabel, tone: 'ok', detail }
  if (result.status === 'not_applicable') return { label, value: 'Not applicable', tone: 'muted', detail: '' }
  if (result.status === 'skipped') return { label, value: 'Skipped', tone: 'warn', detail: [numberDetail, result.error || 'Not configured'].filter(Boolean).join(' | ') }
  return { label, value: 'Failed', tone: 'bad', detail: [numberDetail, result.error || result.status || 'Unknown error'].filter(Boolean).join(' | ') }
}

function showSendStatusToast({ trainerName, result, title = 'Message sent' }) {
  const email = {
    label: 'Email',
    value: result?.success ? 'sent' : 'failed',
    tone: result?.success ? 'ok' : 'bad',
    detail: result?.success ? (result?.email_id || '') : (result?.error || 'Unknown error'),
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

function showBulkSendStatusToast({ title = 'Bulk messages sent', results = [] }) {
  const countOk = (items, pick) => items.filter(item => pick(item)?.success === true).length
  const emailOk = results.filter(item => isSendMailDelivered(item.result)).length
  const whatsappOk = countOk(results, item => item.result?.whatsapp)
  const teamsDirectOk = countOk(results, item => item.result?.teams_direct)
  const teamsOk = countOk(results, item => item.result?.teams)
  const rows = [
    { label: 'Trainers', value: results.length, tone: 'muted' },
    { label: 'Email sent', value: `${emailOk}/${results.length}`, tone: emailOk === results.length ? 'ok' : 'warn' },
    { label: 'WhatsApp queued', value: `${whatsappOk}/${results.length}`, tone: whatsappOk === results.length ? 'ok' : 'warn' },
    { label: 'Teams DM sent', value: `${teamsDirectOk}/${results.length}`, tone: teamsDirectOk ? 'ok' : 'muted' },
    { label: 'Teams channel', value: `${teamsOk}/${results.length}`, tone: teamsOk ? 'ok' : 'muted' },
  ]
  const toneClass = {
    ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    warn: 'bg-amber-50 text-amber-700 border-amber-200',
    muted: 'bg-slate-50 text-slate-600 border-slate-200',
  }

  toast.custom((t) => (
    <div className={clsx(
      'w-[360px] max-w-[calc(100vw-32px)] rounded-xl border border-slate-200 bg-white shadow-xl p-4 transition-all',
      t.visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
    )}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-sm font-bold text-slate-900">{title}</p>
          <p className="text-xs text-slate-500 mt-0.5">Email and WhatsApp status summary</p>
        </div>
        <button onClick={() => toast.dismiss(t.id)} className="p-1 rounded-lg hover:bg-slate-100 text-slate-400">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {rows.map(item => (
          <div key={item.label} className={clsx('rounded-lg border px-3 py-2', toneClass[item.tone] || toneClass.muted)}>
            <p className="text-[11px] font-semibold">{item.label}</p>
            <p className="text-sm font-bold mt-0.5">{item.value}</p>
          </div>
        ))}
      </div>
    </div>
  ), { duration: 10000 })
}

// â”€â”€â”€ Pipeline stages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

function assertSendMailDelivered(result = {}, fallback = 'Email delivery failed') {
  if (!isSendMailDelivered(result)) {
    throw new Error(sendMailError(result, fallback))
  }
  return result
}

const STAGES = {
  pending:              { label: 'Pending',               color: 'bg-slate-100 text-slate-500',     step: 0 },
  mail1_sent:           { label: '1st Mail Sent ðŸ“§',      color: 'bg-blue-100 text-blue-700',       step: 1 },
  waiting_reply1:       { label: 'Waiting for Reply â³',  color: 'bg-sky-100 text-sky-700',         step: 1 },
  mail1_replied:        { label: 'Mail 1 Replied âœ…',     color: 'bg-emerald-100 text-emerald-700', step: 1 },
  details_requested:    { label: 'Details Requested ðŸ“‹',  color: 'bg-indigo-100 text-indigo-700',   step: 2 },
  details_received:     { label: 'Details Received âœ…',   color: 'bg-emerald-100 text-emerald-700', step: 2 },
  waiting_reply2:       { label: 'Waiting for Reply â³',  color: 'bg-sky-100 text-sky-700',         step: 2 },
  slot_booked:          { label: 'Slot Booked ðŸ“…',        color: 'bg-amber-100 text-amber-700',     step: 3 },
  interview_scheduled:  { label: 'Interview Scheduled ðŸ—“ï¸',color: 'bg-purple-100 text-purple-700',  step: 4 },
  selected:             { label: 'Selected âœ…',            color: 'bg-emerald-100 text-emerald-700', step: 5 },
  rejected:             { label: 'Not Selected âŒ',        color: 'bg-red-100 text-red-600',         step: 5 },
  stopped_selected:     { label: 'Stopped - Role Filled', color: 'bg-slate-100 text-slate-500',     step: 0 },
  toc_requested:        { label: 'ToC Requested ðŸ“„',      color: 'bg-teal-100 text-teal-700',       step: 6 },
  toc_received_pending: { label: 'ToC Received ðŸ“„',       color: 'bg-teal-100 text-teal-700',       step: 6 },
  training_confirmed:   { label: 'Training Confirmed ðŸŽ“', color: 'bg-green-100 text-green-700',     step: 7 },
  po_requested:         { label: 'PO Requested',           color: 'bg-cyan-100 text-blue-700',       step: 8 },
  client_po_received:   { label: 'Client PO Received',     color: 'bg-cyan-100 text-blue-700',       step: 8 },
  invoice_generated:    { label: 'Invoice Generated',      color: 'bg-emerald-100 text-emerald-700', step: 9 },
  invoice_sent:         { label: 'Invoice Sent',           color: 'bg-green-100 text-green-700',     step: 10 },
}

// â”€â”€â”€ Reminder intervals for Mail 1 (in ms) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const REMINDER_INTERVALS = [
  { hours: 6,  label: '6h follow-up'  },
  { hours: 12, label: '12h follow-up' },
  { hours: 24, label: '24h follow-up' },
]

const SHORTLIST_REFRESH_INTERVAL_MS = 10000
const AUTO_SEND_CLIENT_SLOTS = true
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
const PIPELINE_MAIL_OPTIONS = [
  { value: 'mail1', label: 'Template 1 - Trainer Requirement' },
  { value: 'trainer_commercials_to_client', label: 'Template 2 - Client Handoff + Availability' },
  { value: 'mail3', label: 'Template 3 - Interview Slot / Result' },
]
let inboxSyncPromise = null
let lastInboxSyncAt = 0
const sentGuard = new Set()

function syncInboxReplies(force = false) {
  const now = Date.now()
  if (!force && now - lastInboxSyncAt < REPLY_SYNC_THROTTLE_MS) return Promise.resolve(null)
  if (!inboxSyncPromise) {
    lastInboxSyncAt = now
    inboxSyncPromise = api.post('/emails/check-replies', { since_days: 7, max_messages: 100 })
      .catch(() => null)
      .finally(() => { inboxSyncPromise = null })
  }
  return inboxSyncPromise
}

function shouldSendOnce(key) {
  if (sentGuard.has(key)) return false
  sentGuard.add(key)
  return true
}

const ACTIVE_PIPELINE_STAGES = new Set([
  'waiting_reply2',
  'details_received',
  'slot_booked',
  'interview_scheduled',
  'selected',
  'toc_requested',
  'toc_received_pending',
])

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
  mail2: 'waiting_reply2',
  mail2_followup: 'waiting_reply2',
  mail3: 'slot_booked',
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

const PIPELINE_STAGE_RANK = {
  pending: 0,
  waiting_reply1: 1,
  mail1_sent: 1,
  mail1_replied: 2,
  details_requested: 3,
  waiting_reply2: 3,
  details_received: 4,
  slot_booked: 5,
  interview_scheduled: 6,
  selected: 7,
  toc_requested: 8,
  toc_received_pending: 9,
  training_confirmed: 10,
  po_requested: 11,
  client_po_received: 12,
  invoice_generated: 13,
  invoice_sent: 14,
  rejected: 99,
  stopped_selected: 99,
}

function isBackendAheadOfLocal(backendStage, stateStage) {
  if (!backendStage || !stateStage || stateStage === 'pending') return false
  const backendRank = PIPELINE_STAGE_RANK[backendStage] ?? -1
  const stateRank = PIPELINE_STAGE_RANK[stateStage] ?? -1
  return backendRank > stateRank
}

function resolveTrainerStage(trainer, req, state) {
  const authoritative = backendAuthoritativeStage(trainer, req)
  const stateStage = normalizePipelineStage(state?.status)
  const backendStage = normalizePipelineStage(
    trainer?.pipeline_status || trainer?.status || trainer?.last_mail_type || trainer?.last_automation_mail_type
  )
  if (
    authoritative &&
    stateStage &&
    stateStage !== 'pending' &&
    ['waiting_reply1', 'mail1_sent', 'waiting_reply2'].includes(authoritative) &&
    !['waiting_reply1', 'mail1_sent', 'waiting_reply2'].includes(stateStage)
  ) {
    return stateStage
  }
  if (authoritative) return authoritative

  if (isBackendAheadOfLocal(backendStage, stateStage)) return backendStage

  if (stateStage && stateStage !== 'pending') return stateStage

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

  if (selectedId && trainerId && trainerId !== selectedId) return 'stopped_selected'
  if (selectedId && trainerId === selectedId) {
    if (commercialStage) return commercialStage
    if (trainerStage && trainerStage !== 'stopped_selected') return trainerStage
    if (['selected', 'toc_requested', 'toc_received_pending', 'training_confirmed', 'po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent'].includes(requirementStage)) {
      return requirementStage
    }
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

function greeting(trainer) {
  const name = (trainer?.name || trainer?.trainer_name || '').trim()
  return `Dear ${name || 'Trainer'},`
}

function cleanDetailValue(value) {
  return value == null ? '' : String(value).trim()
}

const MIN_TRAINER_DAY_RATE_VISIBLE = 10000
const SHORT_DURATION_DAYS = 7
const SHORT_DURATION_TRAINER_SHARE = 0.78
const DEFAULT_TRAINER_SHARE = 0.70

function durationDaysFromRequirement(req = {}) {
  const explicit = Number(req.duration_days || req.commercial_working_days || 0)
  if (Number.isFinite(explicit) && explicit > 0) return explicit
  const text = String(req.duration_text || req.duration || '')
  const match = /(\d+(?:\.\d+)?)\s*(?:working\s*)?days?/i.exec(text)
  return match ? Number(match[1]) : 0
}

function trainerShareForDays(days) {
  return days && days <= SHORT_DURATION_DAYS ? SHORT_DURATION_TRAINER_SHARE : DEFAULT_TRAINER_SHARE
}

function roundCommercialAmount(amount) {
  const numeric = Number(amount || 0)
  if (!Number.isFinite(numeric) || numeric <= 0) return 0
  return Math.ceil(numeric / 1000) * 1000
}

function trainerBudgetFromClientAmount(amount, unit = 'day', days = 0) {
  const numeric = parseMoneyAmount(amount)
  if (!numeric || numeric <= 0) return null
  const share = trainerShareForDays(days)
  if (unit === 'total' && days > 0) {
    const trainerPerDay = (numeric / days) * share
    const trainerTotal = numeric * share
    return {
      amount: trainerPerDay < MIN_TRAINER_DAY_RATE_VISIBLE ? Math.round(trainerTotal) : roundCommercialAmount(trainerPerDay),
      unit: trainerPerDay < MIN_TRAINER_DAY_RATE_VISIBLE ? 'total' : 'day',
      clientAmount: numeric,
      marginPercent: Math.round((1 - share) * 100),
    }
  }
  const trainerAmount = numeric * share
  if (trainerAmount <= 0) return null
  return { amount: roundCommercialAmount(trainerAmount), unit, clientAmount: numeric, marginPercent: Math.round((1 - share) * 100) }
}

function trainerVisibleBudgetInfo(req = {}) {
  const days = durationDaysFromRequirement(req)
  const total = trainerBudgetFromClientAmount(req.budget_total || req.total_budget || req.budget || req.commercials?.total_amount, 'total', days)
  if (total) return total
  const explicit = parseMoneyAmount(req.trainer_visible_budget_per_session || req.trainer_requested_budget_per_session)
  if (explicit > 0) return { amount: roundCommercialAmount(explicit), unit: 'day' }
  const hourly = trainerBudgetFromClientAmount(req.budget_per_hour || req.hourly_rate || req.client_budget_per_hour, 'hour', days)
  if (hourly) return hourly
  const day = trainerBudgetFromClientAmount(req.budget_per_day || req.day_rate || req.client_budget_per_day, 'day', days)
  if (day) return day
  return null
}

function mail1RequirementDetails(req = {}, details = {}) {
  const duration = cleanDetailValue(
    details.duration ||
    req.duration_text ||
    (req.duration_days ? `${req.duration_days} day(s)` : '') ||
    (req.duration_hours ? `${req.duration_hours} hour(s)` : '')
  )
  const timing = cleanDetailValue(
    req.training_dates ||
    req.preferred_dates ||
    req.dates ||
    req.date_time_text ||
    req.timing ||
    req.schedule ||
    req.training_timing ||
    [req.timeline_start, req.timeline_end].filter(Boolean).join(' to ')
  )
  const mode = cleanDetailValue(details.mode || req.mode || req.training_mode || req.delivery_mode)
  const participants = cleanDetailValue(details.participants || req.participant_count || req.participants)
  const trainerBudget = trainerVisibleBudgetInfo(req)
  const commercial = cleanDetailValue(trainerBudget?.amount || '')
  return {
    duration,
    timing,
    mode,
    participants,
    commercial: commercial ? (/^\d+(\.\d+)?$/.test(commercial) ? `INR ${Number(commercial).toLocaleString('en-IN')} ${trainerBudget?.unit === 'total' ? 'total trainer commercial' : 'per day/session'}, inclusive of TDS` : commercial) : '',
  }
}

function mail1MissingClientDetails(detailMap) {
  return [
    !detailMap.duration ? 'duration' : '',
    !detailMap.timing ? 'timing/schedule' : '',
    !detailMap.mode ? 'training mode' : '',
    !detailMap.commercial ? 'commercials/budget' : '',
  ].filter(Boolean)
}

// â”€â”€â”€ Email template builders â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function requestedTrainerDetailItems(req = {}) {
  const source = String([
    req.requested_details,
    req.required_trainer_details,
    req.client_requested_details,
    req.requirement_text,
    req.email_body,
    req.body,
  ].filter(Boolean).join(' ')).toLowerCase()
  const items = []
  const add = (key, label) => {
    if (!items.some(item => item.key === key)) items.push({ key, label })
  }

  add('profile', 'Trainer profile')
  add('cv', 'Updated CV/resume')
  add('linkedin', 'LinkedIn profile')
  if (/\b(commercial|budget|rate|charges?|fee|fees|cost|per day|per session)\b/.test(source) || !source) {
    add('commercial', 'Commercial expectation per day/session')
  }
  if (/\b(certification|certifications|certificate|certified)\b/.test(source)) add('certification', 'Relevant certifications')
  if (/\b(toc|table of contents|course agenda|agenda|day[-\s]?wise)\b/.test(source)) add('toc', 'ToC/course agenda')
  if (/\b(lab|hands[-\s]?on|environment|setup)\b/.test(source)) add('lab', 'Lab/support details')
  return items
}

function trainerReplyDetailPresence(text = '') {
  const clean = stripQuotedEmail(text)
  const t = clean.toLowerCase()
  const hasAttachment = /\b(attached|attachment|enclosed|please find|pfa|shared)\b/.test(t)
  return {
    profile: /\b(profile|trainer profile|brief profile)\b/.test(t) || hasAttachment,
    cv: /\b(cv|resume|curriculum vitae)\b/.test(t) || hasAttachment,
    linkedin: /linkedin\.com|linkedin profile|linkedin\b/.test(t),
    commercial: /\b(inr|rs\.?|\u20b9|rate|charges?|commercial|fee|fees|per day|per session|cost)\b/i.test(t),
    certification: /\b(certification|certifications|certificate|certified|not certified|no certification|none)\b/i.test(t),
    toc: /\b(toc|table of contents|course agenda|agenda|day[-\s]?wise|module|topics covered)\b/i.test(t),
    lab: /\b(lab|hands[-\s]?on|environment|setup|software|tools|prerequisite)\b/i.test(t),
    availability: hasProperInterviewSlots(clean) || /\b(available|availability|slot|slots|interview|discussion)\b/i.test(t),
  }
}

function missingTrainerDetailItems(text = '', req = {}) {
  const presence = trainerReplyDetailPresence(text)
  return requestedTrainerDetailItems(req).filter(item => !presence[item.key])
}

function hasCompleteRequestedTrainerDetails(text = '', req = {}) {
  const clean = stripQuotedEmail(text)
  if (!clean) return false
  if (acceptsSameCommercial(clean)) return true
  const required = requestedTrainerDetailItems(req)
  const missing = missingTrainerDetailItems(clean, req)
  const presentCount = required.length - missing.length
  if (!missing.length) return true
  return presentCount >= Math.max(3, required.length - 1) && trainerReplyDetailPresence(clean).commercial
}

function hasRequestedTrainerDetails(text = '', req = {}) {
  return hasCompleteRequestedTrainerDetails(text, req)
}

function mail1Template(trainer, req, hasDetails, details, isReminder = false, reminderNum = 0) {
  const domain = details?.domain || req.technology_needed
  const detailMap = mail1RequirementDetails(req, details)
  const missingDetails = mail1MissingClientDetails(detailMap)
  const hello = greeting(trainer)
  const reminderPrefix = isReminder
    ? `${hello}\n\nThis is a gentle follow-up (Reminder ${reminderNum}) to our earlier email regarding the ${domain} training requirement.\n\nWe haven't received your response yet. Kindly let us know your interest and availability at the earliest.\n\n---\n\n`
    : ''
  let body = `${reminderPrefix}${hello}\n\nWe have received a training requirement for ${domain} and are looking for a trainer with relevant experience.\n\nTraining Details:\n\nDomain/Technology: ${domain}`
  if (detailMap.duration) body += `\nDuration: ${detailMap.duration}`
  if (detailMap.timing) body += `\nTiming/Schedule: ${detailMap.timing}`
  if (detailMap.mode) body += `\nMode: ${detailMap.mode}`
  if (detailMap.participants) body += `\nParticipants: ${detailMap.participants}`
  if (detailMap.commercial) body += `\nCommercials/Budget: ${detailMap.commercial}`
  if (missingDetails.length) {
    body += `\n\nThe client has not provided the ${missingDetails.join(', ')} yet. We will share those details later once we receive them.`
  }
  const requestedItems = requestedTrainerDetailItems(req).map(item => `* ${item.label}`).join('\n')
  body += `\n\nPlease let us know if you are interested and available for this requirement. Kindly share the details below:\n\n${requestedItems}\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  const subject = isReminder
    ? `[Reminder ${reminderNum}] Training Requirement â€“ ${domain}`
    : `Training Requirement â€“ ${domain}`
  return { subject, body }
}

function isMail1OffStageQuestion(text = '') {
  const clean = stripQuotedEmail(text).toLowerCase()
  if (!clean) return false
  const asksQuestion = clean.includes('?') || /\b(what|when|where|how|which|share|provide|confirm|details?)\b/.test(clean)
  const offStageTopic = /\b(duration|hours?|days?|timings?|schedule|participants?|client|company|rate|commercial|budget|google\s*meet|meet\s*link|meeting\s*link|zoom|teams|location|mode|agenda|toc)\b/.test(clean)
  return asksQuestion && offStageTopic
}

function isDeliveryBounce(text = '') {
  const clean = stripQuotedEmail(text).toLowerCase()
  return /\b(address not found|message blocked|wasn'?t delivered|delivery incomplete|mail delivery subsystem|undeliverable)\b/.test(clean)
}

function mail2Template(trainer, req, trainerReply = '') {
  const missingItems = missingTrainerDetailItems(trainerReply, req)
  const items = (missingItems.length ? missingItems : requestedTrainerDetailItems(req))
    .map(item => `* ${item.label}`)
    .join('\n')
  return {
    subject: `Training Requirement – ${req.technology_needed} | Additional Details Required`,
    body: `${greeting(trainer)}\n\nThank you for your response.\n\nTo proceed further, kindly share the below missing details:\n\n${items}\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}

function mail2FollowupTemplate(trainer, req, trainerReply = '') {
  const missingItems = missingTrainerDetailItems(trainerReply, req)
  const items = (missingItems.length ? missingItems : requestedTrainerDetailItems(req))
    .map(item => `* ${item.label}`)
    .join('\n')
  return {
    subject: `Re: Training Requirement – ${req.technology_needed} | Details Required`,
    body: `${greeting(trainer)}\n\nThank you for confirming your interest.\n\nTo proceed further, kindly share the below pending details:\n\n${items}\n\nOnce we receive these details, we can move ahead with the next step.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}
function trainerCommercialNegotiationTemplate(trainer, req, quote, target) {
  const domain = req?.technology_needed || 'the training requirement'
  const unitText = target.unit === 'hour' ? 'per hour' : 'per day'
  const clientBudget = target.clientBudget || clientBudgetInfo(req)
  const clientBudgetLine = clientBudget?.amount
    ? `The client has confirmed a budget of INR ${clientBudget.amount.toLocaleString('en-IN')} ${unitText}. `
    : ''
  return {
    subject: `Re: Training Requirement - ${domain} | Commercial Discussion`,
    body: `${greeting(trainer)}\n\nThank you for sharing your details and commercials for the ${domain} requirement.\n\n${clientBudgetLine}To align with this budget, kindly confirm if you can proceed at INR ${target.amount.toLocaleString('en-IN')} ${unitText}.\n\nPlease let us know if this revised commercial is workable.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}

function mail3Template(trainer, req, trainerDates) {
  const formattedDates = trainerDates
    ? trainerDates.split('\n').map(date => date.trim()).filter(Boolean).map(date => `• ${date}`).join('\n')
    : '• Monday, Jan 15, 2024 - 10:00 AM IST\n• Tuesday, Jan 16, 2024 - 2:00 PM IST\n• Wednesday, Jan 17, 2024 - 4:00 PM IST'

  return {
    subject: `Interview Slot Booking - ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nPlease share three convenient interview/discussion slots with date, time, and time zone so we can coordinate with the client.\n\nPreferred format:\n${formattedDates}\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}
function mail3SlotClarificationTemplate(trainer) {
  return {
    subject: 'Interview Slot Details Required',
    body: `Hi ${trainer?.name || 'Trainer'},\n\nThank you for sharing the slot. Could you please provide the exact interview date and time, including whether it is AM or PM?\n\nAlso, please share 3 available slots with the corresponding dates so that we can schedule the interview accordingly.\n\nThanks.`
  }
}

function mail3TooManySlotsTemplate(trainer) {
  return {
    subject: 'Re: Interview Slot Booking',
    body: `Hi ${trainer?.name || 'Trainer'},\n\nThank you for your availability. For our scheduling process, we typically work with 3 slots as it helps us coordinate efficiently.\n\nCould you please share your top 3 preferred slots with dates and times?\n\nThank you.`
  }
}

function mail4Template(trainer, req, interviewLink, platform, dateTime) {
  return {
    subject: `Interview Schedule Confirmation â€“ ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nYour interview has been scheduled. Please find the details below:\n\nDate & Time: ${dateTime || '[Date & Time]'}\nPlatform: ${platform || 'Google Meet'}\nMeeting Link: ${interviewLink || '[Google Meet Link]'}\n\nPlease join on time. Let us know if you need any assistance.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}

function mail5SelectedTemplate(trainer, req) {
  return {
    subject: `Congratulations! You have been Selected â€“ ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nCongratulations. The client has selected your profile for this assignment.\n\nWe will share the next steps and coordination details shortly.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}

function mail5RejectedTemplate(trainer, req) {
  return {
    subject: `Update on Training Requirement â€“ ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nThank you for your time and interest in the ${req.technology_needed} training requirement.\n\nAfter careful consideration, we regret to inform you that we have decided to proceed with another trainer at this time.\n\nWe will keep your profile on record and reach out for future opportunities.\n\nThank you once again for your cooperation.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}

// AUTO: ToC request sent immediately after selection
function mailTocAutoTemplate(trainer, req) {
  return {
    subject: `Action Required: ToC / Course Agenda â€“ ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nCongratulations again on being selected for the ${req.technology_needed} training!\n\nTo initiate the onboarding process, kindly share the following at the earliest:\n\n* Detailed Table of Contents (ToC) / Course Agenda\n* Day-wise session breakdown\n* Tools, software, or prerequisites required by participants\n* Estimated preparation time needed\n\nPlease revert at the earliest so we can coordinate with the client on schedule.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}

// MANUAL: Training confirmation with contact details â€” sent after ToC is received
function mailTrainingConfirmedTemplate(trainer, req, contactName, contactPhone, contactEmail, trainingDate, venue) {
  return {
    subject: `Training Schedule Confirmed â€“ ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nWe are pleased to confirm your engagement for the ${req.technology_needed} training. Please find the final details below:\n\nTraining Date: ${trainingDate || '[Training Date]'}\nVenue / Platform: ${venue || '[Venue / Platform]'}\n\nAction Items Before Training:\n* Ensure all materials and slides are ready\n* Share soft copies of training content with us 2 days prior\n* Confirm your availability 24 hours before the training\n\nFor any questions or additional information, please contact:\n\nðŸ‘¤ ${contactName || '[Contact Name]'}\nðŸ“ž ${contactPhone || '[Phone Number]'}\nðŸ“§ ${contactEmail || '[Email]'}\n\nWe look forward to a successful training session!\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`
  }
}

// â”€â”€â”€ Reply intent detector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function detectIntent(text = '') {
  const t = text.toLowerCase()
  const negPhrases = [
    'not interested', 'not available', 'not able', 'not in a position',
    'i am not', "i'm not", 'i will not', "i won't", 'i wont',
    'cannot', "can't", 'cant', 'unable to', 'no thanks', 'no thank you',
    'decline', 'declining', 'unfortunately i', 'regret to inform',
    'not suitable', 'not convenient', 'pass on this', 'withdraw',
    'not interested in', 'do not wish', 'sorry, i cannot', 'sorry i cannot',
    'not possible', 'not workable', 'not okay', 'not ok',
    'cannot increase', "can't increase", 'cant increase',
    'budget cannot', 'budget is fixed', 'commercials are fixed',
  ]
  for (const phrase of negPhrases) if (t.includes(phrase)) return 'negative'
  const detailSignals = [
    'total years of experience', 'years of experience', 'number of trainings',
    'relevant certifications', 'preferred training mode', 'expected commercial',
    'charges per day', 'charges per session', 'per session', 'per day',
    'current location', 'please find my details', 'find below', 'details below',
    'sharing my details', 'as requested', 'available for both',
    'full-day or half-day', 'full day or half day', 'online / offline', 'online/offline',
  ]
  for (const s of detailSignals) if (t.includes(s)) return 'positive'
  const tocSignals = [
    'table of contents', 'toc', 'course agenda', 'day-wise', 'day wise',
    'session plan', 'training plan', 'module', 'topics covered', 'please find attached',
    'find the toc', 'find the agenda', 'sharing the agenda', 'attached herewith',
  ]
  for (const s of tocSignals) if (t.includes(s)) return 'toc_received'
  const posPhrases = [
    'i am interested', "i'm interested", 'i am available', "i'm available",
    'happy to', 'glad to', 'looking forward', 'sounds good',
    'absolutely', 'definitely', 'please share', 'will do',
    'let us proceed', 'i can ', 'yes,', 'sure,', 'ok', 'okay',
    'confirm', 'proceed', 'accept', 'agree',
    'thank you for your response', 'thank you for reaching',
    'please find', 'i would be', 'i am open',
  ]
  for (const phrase of posPhrases) if (t.includes(phrase)) return 'positive'
  if (t.trim().length > 80) return 'positive'
  return 'neutral'
}

function stripQuotedEmail(text = '') {
  return String(text)
    .split(/\nOn .+wrote:\s*/i)[0]
    .split(/\n-{2,}\s*Original Message\s*-{2,}/i)[0]
    .split('\n')
    .filter(line => !line.trim().startsWith('>'))
    .join('\n')
    .trim()
}

function messageTime(message = {}) {
  return new Date(
    message.sent_at ||
    message.received_at ||
    message.created_at ||
    message.updated_at ||
    0
  ).getTime()
}

const TRAINING_COUNT_WORDS = new Set(['training', 'trainings', 'session', 'sessions', 'batch', 'batches', 'conducted'])

function normalizeDetailToken(token = '') {
  return String(token)
    .replaceAll(':', '')
    .replaceAll('-', '')
    .replaceAll(',', '')
    .replaceAll('.', '')
    .replaceAll('+', '')
    .trim()
}

function isNumericDetailToken(token = '') {
  const cleaned = normalizeDetailToken(token)
  return [...cleaned].some(ch => ch >= '0' && ch <= '9') && Number.isFinite(Number(cleaned))
}

function hasTrainingCount(text = '') {
  const tokens = String(text)
    .replaceAll('\r', ' ')
    .replaceAll('\n', ' ')
    .replaceAll('\t', ' ')
    .split(' ')
    .filter(Boolean)
    .slice(0, 500)

  return tokens.some((token, index) => {
    const current = normalizeDetailToken(token)
    const nearby = tokens.slice(index + 1, index + 4)
    return (
      (TRAINING_COUNT_WORDS.has(current) && nearby.some(isNumericDetailToken)) ||
      (isNumericDetailToken(current) && nearby.some(next => TRAINING_COUNT_WORDS.has(normalizeDetailToken(next))))
    )
  })
}

function hasLegacyRequestedTrainerDetails(text = '') {
  const t = stripQuotedEmail(text).toLowerCase()
  if (!t) return false
  return false
}

function parseMoneyAmount(value) {
  if (value === null || value === undefined || value === '') return 0
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  const match = /\d+(?:\.\d+)?/.exec(String(value).replace(/,/g, ''))
  return match ? Number(match[0]) : 0
}

function extractCommercialQuote(text = '') {
  const clean = stripQuotedEmail(text)
  const compact = clean.replace(/,/g, '')
  const patterns = [
    /(?:inr|rs\.?|â‚¹)\s*(\d+(?:\.\d+)?)\s*(?:\/|\s*per\s*)\s*(hour|hr|day|session)/i,
    /(\d+(?:\.\d+)?)\s*(?:inr|rs\.?|â‚¹)\s*(?:\/|\s*per\s*)\s*(hour|hr|day|session)/i,
    /(?:charges?|commercials?|rate|fees?|cost)\D{0,25}(\d+(?:\.\d+)?)\D{0,15}(hour|hr|day|session)/i,
    /(\d+(?:\.\d+)?)\D{0,15}(?:per|\/)\s*(hour|hr|day|session)/i,
    /(?:charges?|commercials?|commercial|rate|fees?|cost|budget)\D{0,40}(\d+(?:\.\d+)?)/i,
    /(\d+(?:\.\d+)?)\D{0,40}(?:charges?|commercials?|commercial|rate|fees?|cost|budget)/i,
  ]
  for (const rx of patterns) {
    const match = rx.exec(compact)
    if (!match) continue
    const amount = Number(match[1])
    const unitRaw = String(match[2] || '').toLowerCase()
    const unit = unitRaw.includes('hour') || unitRaw === 'hr' ? 'hour' : 'day'
    if (Number.isFinite(amount) && amount > 0) return { amount, unit }
  }
  return null
}

function acceptsSameCommercial(text = '') {
  const clean = stripQuotedEmail(text).toLowerCase()
  return /\b(same|client|your|given|shared|mentioned|above)\b.{0,40}\b(commercial|budget|rate|amount|charges?)\b.{0,40}\b(ok|okay|fine|accepted|agree|workable|proceed)\b/.test(clean) ||
    /\b(ok|okay|fine|accepted|agree|workable|proceed)\b.{0,40}\b(same|client|your|given|shared|mentioned|above)\b.{0,40}\b(commercial|budget|rate|amount|charges?)\b/.test(clean)
}

function clientBudgetInfo(req = {}) {
  const hourly = parseMoneyAmount(req.budget_per_hour || req.hourly_rate || req.client_budget_per_hour)
  if (hourly > 0) return { amount: hourly, unit: 'hour' }
  const day = parseMoneyAmount(req.budget_per_day || req.day_rate || req.client_budget_per_day)
  if (day > 0) return { amount: day, unit: 'day' }
  const total = parseMoneyAmount(req.budget_total || req.total_budget || req.commercials?.total_amount)
  const days = parseMoneyAmount(req.duration_days || req.duration)
  if (total > 0 && days > 0) return { amount: Math.round(total / days), unit: 'day' }
  return null
}

function trainerRateFromClientBudget(amount) {
  return Math.max(0, Math.floor((Number(amount) || 0) * 0.70))
}

function clientRateFromTrainerRate(amount) {
  const value = Number(amount) || 0
  return value > 0 ? Math.ceil(value / 0.70) : 0
}

function negotiationTarget(clientBudget) {
  if (!clientBudget?.amount) return null
  const raw = trainerRateFromClientBudget(clientBudget.amount)
  const roundTo = clientBudget.unit === 'hour' ? 100 : 500
  return {
    unit: clientBudget.unit,
    amount: Math.max(roundTo, Math.floor(raw / roundTo) * roundTo),
  }
}

function clientBudgetIncreaseTarget(clientBudget) {
  if (!clientBudget?.amount) return null
  const requested = clientRateFromTrainerRate(clientBudget.amount)
  const increment = Math.max(0, requested - clientBudget.amount)
  return {
    unit: clientBudget.unit,
    increment,
    amount: requested,
  }
}

function needsCommercialNegotiation(replyText, req) {
  const quote = extractCommercialQuote(replyText)
  const clientBudget = clientBudgetInfo(req)
  if (!quote || !clientBudget || quote.unit !== clientBudget.unit) return null
  if (quote.amount <= clientBudget.amount) return null
  const target = negotiationTarget(clientBudget)
  if (!target || target.amount >= quote.amount) return null
  return { quote, clientBudget, target }
}

async function requestClientBudgetIncrease({ trainer, req, clientBudget, requestedBudget = 0 }) {
  const target = requestedBudget > 0
    ? {
        unit: clientBudget.unit,
        increment: Math.max(0, requestedBudget - clientBudget.amount),
        amount: requestedBudget,
      }
    : clientBudgetIncreaseTarget(clientBudget)
  if (!target) return { success: false, error: 'Client budget is missing' }
  const res = await api.post(`/requirements/${req.requirement_id}/request-client-budget-increase`, {
    trainer_id: trainer.trainer_id,
    trainer_name: trainer.name,
    client_email: req.client_email,
    client_name: req.client_name || req.client_company || '',
    current_budget: clientBudget.amount,
    requested_budget: target.amount,
    increment: target.increment,
    unit: target.unit,
  })
  return res.data
}

function extractCommercialCounterOffer(replyText = '', clientBudget = null) {
  const clean = stripQuotedEmail(replyText).toLowerCase().replace(/,/g, '')
  if (!clean) return null
  if (clientBudget?.amount) {
    const trainerTarget = trainerRateFromClientBudget(clientBudget.amount)
    const extraPatterns = [
      /(?:extra|more|additional|increase)\D{0,30}(?:inr|rs\.?|â‚¹)?\s*(\d+(?:\.\d+)?)\s*(k)?\b/i,
      /(?:inr|rs\.?|â‚¹)?\s*(\d+(?:\.\d+)?)\s*(k)?\b\D{0,20}(?:extra|more|additional)/i,
    ]
    for (const rx of extraPatterns) {
      const match = clean.match(rx)
      if (!match) continue
      const extra = Number(match[1]) * (match[2] ? 1000 : 1)
      if (Number.isFinite(extra) && extra > 0) return { amount: trainerTarget + extra, unit: clientBudget.unit }
    }
  }
  const quote = extractCommercialQuote(replyText)
  if (quote) return quote
  const kMatch = clean.match(/\b(\d+(?:\.\d+)?)\s*k\b/i)
  if (kMatch) {
    const amount = Number(kMatch[1]) * 1000
    if (Number.isFinite(amount) && amount > 0) return { amount, unit: clientBudget?.unit || 'day' }
  }
  return null
}

function isCommercialAcceptedAfterNegotiation(replyText, req) {
  const clientBudget = clientBudgetInfo(req)
  const quote = extractCommercialCounterOffer(replyText, clientBudget)
  if (!quote && detectIntent(replyText) === 'positive') return true
  if (!quote || !clientBudget || quote.unit !== clientBudget.unit) return false
  return clientRateFromTrainerRate(quote.amount) <= clientBudget.amount
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
    /\b\d{1,2}(?::\d{2})?\s*[-â€“]\s*\d{1,2}(?::\d{2})?\s*(am|pm)\b/g,
  ].reduce((sum, rx) => sum + ((clean.match(rx) || []).length), 0)
  const slotHints = (clean.match(/\b(slot|option|available|availability)\b/g) || []).length
  const hasOneExactSlot = dateHits >= 1 && timeHits >= 1
  const hasThreeSlotOptions = dateHits >= 3 && timeHits >= 3 || dateHits >= 3 && timeHits >= 2 && slotHints >= 1
  return hasOneExactSlot || hasThreeSlotOptions
}

function countSlotsInReply(text = '') {
  const clean = stripQuotedEmail(text).toLowerCase()
  if (!clean) return 0
  
  // Count date occurrences (each date might represent a slot)
  const dates = [
    /\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b/g,
    /\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b/g,
    /\b(mon|tue|wed|thu|fri|sat|sun)(day)?\b/g,
  ].reduce((sum, rx) => sum + ((clean.match(rx) || []).length), 0)
  
  // Count bullet points or "slot" mentions
  const bulletSlots = (clean.match(/[â€¢\-*]\s*\d{1,2}|slot\s*\d{1,2}/g) || []).length
  
  return Math.max(dates, bulletSlots)
}

function hasTooManySlots(text = '') {
  return countSlotsInReply(text) > 3
}

function hasTooFewSlots(text = '') {
  const slotCount = countSlotsInReply(text)
  return slotCount > 0 && slotCount < 3
}

async function sendSlotClarificationMail({ trainer, req }) {
  const { subject, body } = mail3SlotClarificationTemplate(trainer)
  const res = await api.post('/shortlists/send-mail', {
    trainer_id: trainer.trainer_id,
    trainer_name: trainer.name,
    to_email: trainer.email,
    requirement_id: req.requirement_id,
    subject,
    body,
    mail_type: 'mail3_slot_followup',
  })
  return res.data
}

function latestReplyAfter(messages, sentTypes = []) {
  const sent = messages.filter(m => m.direction === 'sent' && sentTypes.includes(m.mail_type))
  if (!sent.length) return null
  const lastSentTime = Math.max(...sent.map(messageTime))
  return [...messages]
    .sort((a, b) => messageTime(a) - messageTime(b))
    .findLast(m => m.direction === 'received' && messageTime(m) > lastSentTime) || null
}

function latestTrainerDetailsReply(messages = [], req = {}) {
  return (
    latestReplyAfter(messages, ['mail2', 'mail2_followup', 'commercial_negotiation', 'trainer_rate_discussion']) ||
    latestReplyAfter(messages, ['mail1', 'mail1_reminder']) ||
    [...messages]
      .sort((a, b) => messageTime(a) - messageTime(b))
      .findLast(m => m.direction === 'received' && hasRequestedTrainerDetails(m.body || '', req)) ||
    null
  )
}

async function sendSlotsToClient({ trainer, req, slotText = '', trainerDetailsText = '', force = false, clientEmail = '', clientName = '' }) {
  const res = await api.post('/shortlists/send-client-slots', {
    trainer_id: trainer.trainer_id,
    trainer_name: trainer.name,
    requirement_id: req.requirement_id,
    slot_text: stripQuotedEmail(slotText),
    trainer_details_text: stripQuotedEmail(trainerDetailsText),
    force,
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
  title = 'Client Contact',
  description = 'Save the client email once. When a trainer replies with slots, Clahan will send those slots to this client automatically.',
  submitLabel = 'Save Client',
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
            <p className="mt-1 text-sm text-slate-500">{description}</p>
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

function inferPipelineStateFromThread(messages = []) {
  if (!messages.length) return null

  const sorted = [...messages].sort((a, b) => messageTime(a) - messageTime(b))
  const sentTypes = new Set(sorted.filter(m => m.direction === 'sent').map(m => m.mail_type))
  const ts = msg => messageTime(msg) || Date.now()

  if (sentTypes.has('mail5_no')) return { status: 'rejected' }
  if (sentTypes.has('mail7_confirm')) return { status: 'training_confirmed' }

  if (sentTypes.has('mail6_toc')) {
    const tocReply = latestReplyAfter(sorted, ['mail6_toc'])
    if (tocReply) {
      return { status: 'toc_received_pending', tocReplyAt: ts(tocReply) }
    }
    return { status: 'toc_requested' }
  }

  if (sentTypes.has('mail5_ok')) return { status: 'selected' }
  if (sentTypes.has('mail4')) return { status: 'interview_scheduled' }

  if (sentTypes.has('mail3')) {
    const slotReply = latestReplyAfter(sorted, ['mail3'])
    return slotReply
      ? hasProperInterviewSlots(slotReply.body)
        ? { status: 'slot_booked', slotReplyAt: ts(slotReply), slotConfirmed: true }
        : { status: 'slot_booked', slotClarificationAt: ts(slotReply) }
      : { status: 'slot_booked' }
  }

  if (sentTypes.has('commercial_negotiation')) {
    const negotiationReply = latestReplyAfter(sorted, ['commercial_negotiation'])
    if (!negotiationReply) return { status: 'waiting_reply2' }
  }

  if (sentTypes.has('client_budget_revision_request')) {
    const clientBudgetReply = latestReplyAfter(sorted, ['client_budget_revision_request'])
    if (!clientBudgetReply) return { status: 'waiting_reply2' }
    const budgetIntent = detectIntent(clientBudgetReply.body)
    if (budgetIntent === 'negative') return { status: 'rejected' }
    if (budgetIntent === 'positive') return { status: 'details_received', clientBudgetRevisionAcceptedAt: ts(clientBudgetReply) }
    return { status: 'waiting_reply2' }
  }

  if (sentTypes.has('mail2') || sentTypes.has('mail2_followup')) {
    const detailsReply = latestReplyAfter(sorted, ['mail2', 'mail2_followup'])
    if (detailsReply && hasRequestedTrainerDetails(detailsReply.body, req)) {
      return { status: 'details_received', detailsAcceptedAt: ts(detailsReply) }
    }
    const anyCompleteDetailsReply = sorted.find(m => m.direction === 'received' && hasRequestedTrainerDetails(m.body, req))
    if (anyCompleteDetailsReply) {
      return { status: 'details_received', detailsAcceptedAt: ts(anyCompleteDetailsReply) }
    }
    if (detailsReply && detectIntent(detailsReply.body) === 'negative') {
      return { status: 'rejected' }
    }
    return { status: 'waiting_reply2' }
  }

  if (sentTypes.has('mail1') || sentTypes.has('mail1_reminder')) {
    const mail1Reply = latestReplyAfter(sorted, ['mail1', 'mail1_reminder'])
    if (mail1Reply && detectIntent(mail1Reply.body) === 'negative') {
      return { status: 'rejected' }
    }
    if (mail1Reply) {
      if (hasRequestedTrainerDetails(mail1Reply.body, req)) {
        return { status: 'details_received', mail1ReplyAt: ts(mail1Reply), detailsAcceptedAt: ts(mail1Reply) }
      }
      return { status: 'mail1_replied', mail1ReplyAt: ts(mail1Reply) }
    }
    return { status: 'waiting_reply1' }
  }

  return null
}

function inferPipelineStateFromEmailLogs(logs = []) {
  if (!logs.length) return null

  const messages = []
  for (const log of logs) {
    messages.push({
      direction: 'sent',
      mail_type: log.mail_type,
      sent_at: log.sent_at || log.created_at,
      body: log.body || '',
    })
    if (log.reply_received && log.reply_text) {
      messages.push({
        direction: 'received',
        mail_type: 'reply',
        sent_at: log.replied_at || log.created_at,
        body: log.reply_text,
      })
    }
  }

  return inferPipelineStateFromThread(messages)
}

// â”€â”€â”€ Send Mail Modal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function MailModal({ trainer, req, mailType, onClose, onSent, threadMessages }) {
  const [loading, setLoading]           = useState(false)
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
  // â”€â”€ AI state â”€â”€
  const [aiGenerating, setAiGenerating] = useState(false)
  const [aiSubject, setAiSubject]       = useState('')
  const [aiBody, setAiBody]             = useState('')
  const [aiUsed, setAiUsed]             = useState(false)

  const getTemplatePreview = () => {
    const latestReply = threadMessages?.findLast(m => m.direction === 'received')?.body || ''
    
    switch (mailType) {
      case 'mail1':          return mail1Template(trainer, req, false, {})
      case 'mail2':          return mail2Template(trainer, req)
      case 'mail2_followup': return mail2FollowupTemplate(trainer, req)
      case 'mail3':          
        // Check if trainer provided wrong number of slots
        if (latestReply) {
          if (hasTooManySlots(latestReply)) {
            return mail3TooManySlotsTemplate(trainer)
          }
          if (hasTooFewSlots(latestReply)) {
            return mail3SlotClarificationTemplate(trainer)
          }
        }
        return mail3Template(trainer, req, trainerDates)
      case 'mail3_too_many_slots': return mail3TooManySlotsTemplate(trainer)
      case 'mail3_too_few_slots':  return mail3SlotClarificationTemplate(trainer)
      case 'mail4':          return mail4Template(trainer, req, interviewLink, platform, dateTime)
      case 'mail5_ok':       return mail5SelectedTemplate(trainer, req)
      case 'mail5_no':       return mail5RejectedTemplate(trainer, req)
      case 'mail7_confirm':  return mailTrainingConfirmedTemplate(trainer, req, contactName, contactPhone, contactEmail, trainingDate, venue)
      default:               return { subject: '', body: '' }
    }
  }

  const getPreview = () => {
    if (aiUsed && aiSubject && aiBody) return { subject: aiSubject, body: aiBody }
    return getTemplatePreview()
  }

  const preview = getPreview()

  const handleAIGenerate = async () => {
    setAiGenerating(true)
    try {
      const latestReply = threadMessages?.findLast(m => m.direction === 'received')
      const result = await generateAIReply({
        trainerName:   trainer.name,
        domain:        req.technology_needed,
        stage:         mailType,
        trainerReply:  latestReply?.body || '',
        previousMails: threadMessages || [],
        fallback:      getTemplatePreview(),
      })
      setAiSubject(result.subject)
      setAiBody(result.body)
      setAiUsed(true)
      toast.success('âœ¨ AI email generated!')
    } catch (e) {
      toast.error('AI generation failed: ' + (e.message || 'Unknown error'))
    } finally {
      setAiGenerating(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    const latestReply = threadMessages?.findLast(m => m.direction === 'received')
    setAiGenerating(true)
    setAiUsed(false)
    Promise.resolve(generateAIReply({
      trainerName:   trainer.name,
      domain:        req.technology_needed,
      stage:         mailType,
      trainerReply:  latestReply?.body || '',
      previousMails: threadMessages || [],
      fallback:      getTemplatePreview(),
    })).then(result => {
      if (cancelled) return
      setAiSubject(result.subject)
      setAiBody(result.body)
      setAiUsed(true)
    }).catch(() => {
      if (!cancelled) toast.error('AI email generation failed')
    }).finally(() => {
      if (!cancelled) setAiGenerating(false)
    })
    return () => { cancelled = true }
  }, [
    mailType,
    trainer.trainer_id,
    req.requirement_id,
    trainerDates,
    interviewLink,
    platform,
    dateTime,
    trainingDate,
    venue,
    contactName,
    contactPhone,
    contactEmail,
  ])

  const TITLES = {
    mail1:         'ðŸ“§ Send Shortlist Mail',
    mail2:         'ðŸ“‹ Request Trainer Details',
    mail2_followup:'ðŸ“‹ Ask Details Again',
    mail3:         'ðŸ“… Book Interview Slot',
    mail4:         'ðŸ—“ï¸ Send Interview Schedule',
    mail5_ok:      'ðŸŽ‰ Send Selection Mail',
    mail5_no:      'âŒ Send Rejection Mail',
    mail7_confirm: 'ðŸŽ“ Send Training Confirmation',
  }

  const NEXT_STAGES = {
    mail1:         'waiting_reply1',
    mail2:         'waiting_reply2',
    mail2_followup:'waiting_reply2',
    mail3:         'slot_booked',
    mail4:         'interview_scheduled',
    mail5_ok:      'selected',
    mail5_no:      'rejected',
    mail7_confirm: 'training_confirmed',
  }

  const handleSend = async () => {
    if (mailType === 'mail3' && !clientEmail.trim()) {
      toast.error('Client email is required so trainer slots can be sent automatically')
      return
    }
    setLoading(true)
    try {
      const finalSubject = aiUsed ? aiSubject : preview.subject
      const finalBody    = aiUsed ? aiBody    : preview.body
      let res
      if (mailType === 'mail4') {
        res = await api.post('/shortlists/send-interview-link', {
          trainer_id:     trainer.trainer_id,
          trainer_name:   trainer.name,
          to_email:       trainer.email,
          requirement_id: req.requirement_id,
          platform,
          date_time:      dateTime,
          interview_link: interviewLink,
          client_email:   req.client_email,
          client_name:    req.client_name || req.client_company || '',
        })
      } else {
        res = await api.post('/shortlists/send-mail', {
          trainer_id:     trainer.trainer_id,
          trainer_name:   trainer.name,
          to_email:       trainer.email,
          requirement_id: req.requirement_id,
          subject:        finalSubject,
          body:           finalBody,
          mail_type:      mailType,
          client_email:   mailType === 'mail3' ? clientEmail.trim() : undefined,
          client_name:    mailType === 'mail3' ? clientName.trim() : undefined,
        })
      }
      const result = res?.data || {}
      if (mailType !== 'mail4') {
        assertSendMailDelivered(result)
      }
      showSendStatusToast({ trainerName: trainer.name, result, title: 'Pipeline mail sent' })
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
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-slate-100 sticky top-0 bg-white z-10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-violet-100 text-violet-700 flex items-center justify-center">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-lg text-slate-900">{TITLES[mailType]}</h3>
              <p className="text-sm text-slate-500 mt-0.5">AI-generated mail for <strong>{trainer.name}</strong> Â· {trainer.email}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
            <div className="flex items-center gap-3">
              <Sparkles className="w-5 h-5 text-violet-600 flex-shrink-0" />
              <div>
                <p className="text-sm font-bold text-violet-900">TrainerSync AI writes this mail from your 3-template pipeline rules.</p>
                <p className="text-xs text-violet-700 mt-0.5">It uses trainer name, domain, stage, latest reply, and thread context. The message is not manually edited.</p>
              </div>
            </div>
          </div>

          {mailType === 'mail3' && (
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
                placeholder="â€¢ Monday 10 AM â€“ 12 PM&#10;â€¢ Wednesday 2 PM â€“ 4 PM&#10;â€¢ Friday anytime"
                value={trainerDates} onChange={e => setTrainerDates(e.target.value)} />
            </div>
          )}

          {mailType === 'mail4' && (
            <div className="bg-slate-50 rounded-xl p-4 space-y-3 border border-slate-200">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Interview details for AI mail</p>
              <div className="grid grid-cols-3 gap-2">
                {['Google Meet', 'MS Teams', 'Zoom'].map(p => (
                  <button key={p} type="button" onClick={() => setPlatform(p)}
                    className={clsx('p-2 rounded-xl border-2 text-xs font-semibold transition-all',
                      platform === p ? 'bg-blue-500 text-white border-blue-500' : 'bg-white border-slate-200 text-slate-600 hover:border-blue-300')}>
                    {p === 'Zoom' ? 'ðŸ“¹' : p === 'MS Teams' ? 'ðŸ’¼' : 'ðŸŽ¥'} {p}
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

          {/* â”€â”€ AI Generate Button â”€â”€ */}
          <div className="hidden">
            <Bot className="w-5 h-5 text-violet-500 flex-shrink-0" />
            <div className="flex-1">
              <p className="text-xs font-semibold text-violet-700">Rule-Based AI Email</p>
              <p className="text-xs text-violet-500">Generated automatically from pipeline rules and trainer context</p>
            </div>
            <button
              onClick={handleAIGenerate}
              disabled={aiGenerating}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-xs font-semibold transition-all disabled:opacity-60 flex-shrink-0"
            >
              {aiGenerating
                ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Generating...</>
                : <><Sparkles className="w-3.5 h-3.5" /> Regenerate</>
              }
            </button>
          </div>

          {/* AI email preview */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="label">AI Generated Email</p>
              {aiUsed && (
                <span className="flex items-center gap-1 text-xs text-violet-600 font-semibold">
                  <Sparkles className="w-3 h-3" /> Auto Generated
                </span>
              )}
            </div>

            {aiGenerating ? (
              <div className="flex items-center justify-center gap-2 rounded-xl border border-violet-200 bg-violet-50 p-6 text-sm font-semibold text-violet-700">
                <Loader2 className="h-4 w-4 animate-spin" /> Generating email from AI rules...
              </div>
            ) : aiUsed ? (
              <div className="space-y-2">
                <div>
                  <label className="label text-xs">Subject</label>
                  <input
                    className="input text-sm bg-white"
                    value={aiSubject}
                    onChange={e => setAiSubject(e.target.value)}
                    readOnly
                  />
                </div>
                <div>
                  <label className="label text-xs">Body</label>
                  <textarea
                    className="input resize-none text-sm font-sans leading-relaxed bg-white"
                    rows={12}
                    value={aiBody}
                    onChange={e => setAiBody(e.target.value)}
                    readOnly
                  />
                </div>
                <p className="text-xs text-slate-400 flex items-center gap-1">
                  <Info className="w-3 h-3" /> Generated automatically from your 3-template mail rules
                </p>
              </div>
            ) : (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700">
                AI email is not ready yet. Please wait a moment.
              </div>
            )}
          </div>
        </div>

        <div className="flex gap-3 p-5 border-t border-slate-100 sticky bottom-0 bg-white">
          <button onClick={handleSend} disabled={loading || aiGenerating || !aiUsed}
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

// â”€â”€â”€ Thread Modal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
function TocModal({ trainer, req, onClose }) {
  const [form, setForm] = useState({
    duration_days: req?.duration_days || (req?.duration_hours ? Math.max(1, Math.ceil(Number(req.duration_hours) / 8)) : 3),
    training_dates: req?.training_dates || req?.preferred_dates || req?.timeline_start || '',
    timing: req?.timing || req?.schedule || '',
    audience_level: req?.audience_level || req?.level || 'intermediate',
    mode: req?.mode || req?.training_mode || 'Online',
    toc_type: 'standard',
    custom_topics: '',
    client_notes: req?.client_notes || req?.job_description || req?.description || req?.content_scope || '',
  })
  const [tocId, setTocId] = useState('')
  const [tocData, setTocData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [sending, setSending] = useState(false)
  const tocAccuracy = getTocAccuracy(tocData, form, req)

  const update = (key, value) => {
    setForm(prev => ({ ...prev, [key]: value }))
    setTocId('')
    setTocData(null)
  }

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
        audience_level: form.audience_level,
        mode: form.mode,
        training_dates: form.training_dates,
        timing: form.timing,
        toc_type: form.toc_type,
        custom_topics: form.custom_topics,
        client_notes: form.client_notes,
      })
      setTocId(res.data.toc_id)
      setTocData(res.data.toc_data)
      toast.success('TOC generated successfully')
    } catch (e) {
      const detail = e.response?.data?.detail
      toast.error((typeof detail === 'object' ? detail.message : detail) || e.message || 'TOC generation failed')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async () => {
    if (!tocId) return
    setDownloading(true)
    try {
      const res = await api.post('/toc/generate-pdf', { toc_id: tocId }, { responseType: 'blob' })
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${(req.technology_needed || 'training').replace(/[^a-z0-9]+/gi, '_')}_${tocId}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'PDF download failed')
    } finally {
      setDownloading(false)
    }
  }

  const handleSend = async () => {
    if (!tocId) return
    setSending(true)
    try {
      await api.post('/toc/send-email', { toc_id: tocId })
      toast.success(`TOC sent to ${trainer.name}`)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'TOC email failed')
    } finally {
      setSending(false)
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
            <p className="text-sm text-slate-500 mt-0.5">{trainer.name} Â· {req.technology_needed}</p>
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
          <button onClick={handleSend} disabled={!tocId || sending}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm transition-all disabled:opacity-50">
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Send to Trainer
          </button>
          <button onClick={onClose} className="ml-auto px-4 py-2.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-sm transition-all">
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function initialPoForm(trainer, req, state) {
  const durationDays = req?.duration_days || (req?.duration_hours ? Math.max(1, Number(req.duration_hours) / 8) : 1)
  return {
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
  const gst = subtotal * 0.18
  const grandTotal = subtotal + gst

  const payload = () => ({
    trainer_id: trainer.trainer_id,
    requirement_id: req.requirement_id,
    client_name: form.client_name,
    client_email: req.client_email,
    training_dates: form.training_dates,
    duration_days: Number(form.duration_days || 1),
    mode: form.mode,
    day_rate: Number(form.day_rate || 0),
    total_amount: Number(form.total_amount || 0),
    payment_terms: form.payment_terms,
  })

  const createPo = async () => {
    if (!form.client_name.trim()) return toast.error('Client name is required')
    if (!form.training_dates.trim()) return toast.error('Training dates are required')
    if (!Number(form.duration_days || 0)) return toast.error('Duration is required')
    if (subtotal <= 0) return toast.error('Enter day rate or total amount')

    setGenerating(true)
    try {
      const res = await api.post('/purchase-orders/generate', payload())
      const generated = res.data.purchase_order
      setPo(generated)
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
          duration_days: Number(form.duration_days || 1),
          mode: form.mode,
          day_rate: Number(form.day_rate || 0),
          total_amount: Number(form.total_amount || subtotal),
          gst_rate: Number(form.gst_rate || 18),
          payment_terms: form.payment_terms,
          client_po_notes: form.client_po_notes,
        })
      : await api.post(`/purchase-orders/${current.po_id}/generate-invoice`, {
          client_email: req.client_email,
          client_name: req.client_company || req.client_name || form.client_name,
        })
    const generated = res.data.invoice
    setInvoice(generated)
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
            <p className="text-sm text-slate-500 mt-0.5">{trainer.name} Â· {req.technology_needed}</p>
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
                <p className="text-xs text-slate-400 font-semibold uppercase">GST 18%</p>
                <p className="font-bold text-slate-900">{money(gst)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-400 font-semibold uppercase">Grand Total</p>
                <p className="font-bold text-emerald-700">{money(grandTotal)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-400 font-semibold uppercase">PO Status</p>
                <p className="font-bold text-slate-900">{po ? `${po.po_number} Â· ${po.status}` : 'Not generated'}</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
            <p className="text-xs text-blue-700 font-semibold uppercase">Client Invoice</p>
            <p className="mt-1 text-sm font-bold text-cyan-900">
              {invoice ? `${invoice.invoice_number} Â· ${invoice.status}` : req.client_email ? `Ready for ${req.client_email}` : 'Client email missing'}
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
        filtered.sort((a, b) => messageTime(a) - messageTime(b))
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
      syncInboxReplies().finally(() => {
        if (cancelled) return
        setSyncing(false)
        loadThread(true)
      })
    }

    loadThread()
    syncLatestReplies()
    const interval = setInterval(() => loadThread(true), THREAD_REFRESH_INTERVAL_MS)
    const syncInterval = setInterval(syncLatestReplies, REPLY_SYNC_THROTTLE_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
      clearInterval(syncInterval)
    }
  }, [trainer.trainer_id, req.requirement_id])

  const STAGE_LABELS = {
    mail1:         '1st Contact',
    mail1_reminder:'Follow-up Reminder',
    mail2:         'Details Request',
    mail3:         'Slot Booking',
    mail4:         'Interview Schedule',
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
            <h3 className="font-bold text-lg text-slate-900">ðŸ’¬ Conversation Thread</h3>
            <p className="text-sm text-slate-500">{trainer.name} Â· {req.technology_needed}</p>
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
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loadingâ€¦
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
                    {isReminder ? 'ðŸ”” Reminder sent' : isSent ? 'ðŸ“¤ You sent' : 'ðŸ“¥ Trainer replied'}
                  </span>
                  <div className="flex items-center gap-2">
                    {msg.mail_type && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-white border border-slate-200 text-slate-500">
                        {STAGE_LABELS[msg.mail_type] || msg.mail_type}
                      </span>
                    )}
                    <span className="text-xs text-slate-400">
                      {(msg.sent_at || msg.received_at || msg.created_at) ? new Date(msg.sent_at || msg.received_at || msg.created_at).toLocaleString() : ''}
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

// â”€â”€â”€ Pipeline Step Bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function StepBar({ stage }) {
  const steps = ['Mail 1', 'Details', 'Slot', 'Interview', 'Selected', 'ToC', 'Confirmed']
  const stepIndex = STAGES[stage]?.step ?? 0
  const isRejected = stage === 'rejected'
  const isDone     = ['training_confirmed', 'po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent'].includes(stage)

  return (
    <div className="mt-4 grid grid-cols-7 gap-1.5 rounded-xl border border-slate-200 bg-slate-50 p-2">
      {steps.map((s, i) => {
        const realStep   = i + 1
        const isActive   = realStep === stepIndex
        const isComplete = realStep < stepIndex
        const isRejStep  = realStep === 5 && isRejected
        const isFinalDone= realStep === 7 && isDone
        return (
          <div key={i} className={clsx(
            'min-w-0 rounded-lg px-1.5 py-1.5 text-center transition-all',
            isComplete || isFinalDone ? 'bg-white shadow-sm ring-1 ring-blue-100' :
            isActive ? 'bg-white shadow-sm ring-1 ring-slate-200' :
            'bg-transparent'
          )}>
            <div className={clsx(
              'mx-auto flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold transition-all',
              isComplete             ? 'bg-blue-500 text-white' :
              isRejStep              ? 'bg-red-500 text-white'  :
              isFinalDone            ? 'bg-green-500 text-white':
              isActive && isRejected ? 'bg-red-500 text-white'  :
              isActive               ? 'bg-blue-500 text-white ring-2 ring-blue-200' :
                                       'bg-slate-200 text-slate-400'
            )}>
              {isComplete || isFinalDone ? 'âœ“' : isRejStep ? 'âœ•' : realStep}
            </div>
            <div className={clsx(
              'mt-1 truncate text-[10px] font-semibold',
              isActive || isComplete || isFinalDone ? 'text-slate-700' : 'text-slate-400'
            )}>{s}</div>
          </div>
        )
      })}
    </div>
  )
}

// â”€â”€â”€ AUTO PILOT ENGINE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
//
// Full auto flow:
//   pending trainers â†’ Mail 1 is sent to everyone
//   waiting_reply1 â†’ reminders at 6h/12h/24h until a Mail 1 reply arrives
//   positive Mail 1 replies are queued in reply order
//   one queued trainer at a time â†’ Mail 2 â†’ Mail 3 â†’ manual interview/select rules
//   rejected trainers are skipped and the next queued trainer starts
//   selected trainer stops the requirement queue, then ToC/confirmation rules continue
//
function PipelineProgressSummary({ stage, state, req }) {
  const postTrainingStages = ['po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent']
  const afterTraining = postTrainingStages.includes(stage)
  const doneStages = {
    mail1: afterTraining || ['mail1_sent', 'waiting_reply1', 'mail1_replied', 'details_requested', 'details_received', 'waiting_reply2', 'slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail2: afterTraining || ['details_requested', 'details_received', 'waiting_reply2', 'slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail3: afterTraining || ['slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail4: afterTraining || ['interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail5: afterTraining || ['selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail6: afterTraining || ['toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    mail7: afterTraining || stage === 'training_confirmed',
    po: ['po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent'].includes(stage),
    invoice: ['invoice_generated', 'invoice_sent'].includes(stage),
    invoiceSent: stage === 'invoice_sent',
  }

  const clientEmailSaved = Boolean(req?.client_email)
  const clientSlotsSent = Boolean(state?.clientSlotsSentAt)
  const templateDone = [
    doneStages.mail1,
    doneStages.mail2 || clientSlotsSent || ['details_received', 'slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
    doneStages.mail3 || ['slot_booked', 'interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(stage),
  ].filter(Boolean).length
  const progressPct = Math.round((templateDone / 3) * 100)
  const progressLabel = stage === 'stopped_selected'
    ? 'Stopped - role filled'
    : templateDone === 3
      ? 'Trainer flow complete'
      : `Template ${Math.min(templateDone + 1, 3)} is next`
  const commercialStatus = doneStages.invoiceSent
    ? 'Invoice sent'
    : doneStages.invoice
      ? 'Invoice generated'
      : doneStages.po
        ? stage === 'po_requested' ? 'PO requested' : 'PO received'
        : 'Not started'
  const items = [
    { label: 'Templates', value: `${templateDone}/3 complete`, tone: templateDone === 3 ? 'good' : 'neutral' },
    { label: 'Client slots', value: clientSlotsSent ? 'Sent to client' : clientEmailSaved ? 'Client saved' : 'Email missing', tone: clientSlotsSent ? 'good' : clientEmailSaved ? 'neutral' : 'warn' },
    { label: 'Commercial', value: commercialStatus, tone: doneStages.invoiceSent ? 'good' : doneStages.invoice ? 'warn' : 'neutral' },
    { label: 'Current stage', value: STAGES[stage]?.label || stage || 'Pending', tone: stage === 'rejected' ? 'bad' : 'neutral' },
  ]

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-bold uppercase text-slate-400">Pipeline progress</p>
          <p className="text-sm font-bold text-slate-900">{progressLabel}</p>
        </div>
        <span className="rounded-full bg-slate-900 px-2.5 py-1 text-xs font-bold text-white">{progressPct}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={clsx(
          'h-full rounded-full transition-all',
          stage === 'rejected' ? 'bg-red-500' : progressPct === 100 ? 'bg-emerald-500' : 'bg-blue-500'
        )} style={{ width: `${progressPct}%` }} />
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {items.map(item => (
          <div key={item.label} className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-100">
            <p className="text-[10px] font-bold uppercase text-slate-400">{item.label}</p>
            <p className={clsx(
              'mt-0.5 truncate text-xs font-bold',
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
        const sendMail3SlotBooking = async (trainer, extraStage = {}) => {
          const { subject, body } = mail3Template(trainer, req, '')
          const mail3Res = await api.post('/shortlists/send-mail', {
            trainer_id: trainer.trainer_id,
            trainer_name: trainer.name,
            to_email: trainer.email,
            requirement_id: req.requirement_id,
            subject,
            body,
            mail_type: 'mail3',
            client_email: req.client_email,
            client_name: req.client_name || req.client_company,
          })
          showSendStatusToast({ trainerName: trainer.name, result: mail3Res.data, title: 'Slot booking sent' })
          if (!isSendMailDelivered(mail3Res?.data)) {
            toast.error(sendMailError(mail3Res?.data, 'Failed to send Mail 3 slot booking'))
            return false
          }

          setStage(trainer, 'slot_booked', {
            mail3SentAt: Date.now(),
            ...extraStage,
          })
          return true
        }
        const sendClientCommercialsFromReply = async (trainer, reply, reason = 'details') => {
          if (!req.client_email) {
            toast.error('Client email is missing. Cannot send trainer commercials to client.')
            return false
          }

          const replyContent = reply?.body || reply?.reply_text || reply?.content || ''
          const trainerOffer = trainerVisibleBudgetInfo(req)
          const quote = extractCommercialQuote(replyContent) ||
            (acceptsSameCommercial(replyContent) && trainerOffer?.amount ? { amount: trainerOffer.amount, unit: trainerOffer.unit } : null)
          if (!quote?.amount) {
            toast.error(`No commercial amount or same-commercial acceptance found in ${trainer.name}'s reply.`)
            return false
          }

          const acceptedClientCommercial = trainerOffer?.amount &&
            trainerOffer.unit === quote.unit &&
            quote.amount <= trainerOffer.amount
          const clientAmount = clientRateFromTrainerRate(quote.amount)
          const unitText = quote.unit === 'hour' ? 'per hour' : quote.unit === 'session' ? 'per session' : 'per day'
          const guardKey = `${req.requirement_id}:${trainer.trainer_id}:client_commercials:${reason}:${acceptedClientCommercial ? 'accepted' : clientAmount}:${messageTime(reply)}`
          if (!shouldSendOnce(guardKey)) return true

          try {
            const notificationRes = await api.post('/shortlists/send-mail', {
              trainer_id: trainer.trainer_id,
              trainer_name: trainer.name,
              to_email: req.client_email,
              requirement_id: req.requirement_id,
              subject: `Shortlisted Profile Details Received - ${req.technology_needed}`,
              body: `Hi ${req.client_name || 'Team'},\n\nGood news. The shortlisted trainer has shared the required details for the ${req.technology_needed} requirement.\n\nWe are sharing the commercials for your review in the next email.\n\nRegards,\nClahan Technologies`,
              mail_type: 'commercial_details_notification',
            })
            showSendStatusToast({ trainerName: trainer.name, result: notificationRes.data, title: 'Client notification sent' })
          } catch {
            // Non-blocking: send the actual commercial mail even if this heads-up fails.
          }

          if (acceptedClientCommercial) {
            const acceptedRes = await api.post('/shortlists/send-mail', {
              trainer_id: trainer.trainer_id,
              trainer_name: trainer.name,
              to_email: req.client_email,
              requirement_id: req.requirement_id,
              subject: `Trainer Accepted Your Commercial - ${req.technology_needed} | ${trainer.name}`,
              body: `Hi ${req.client_name || 'Team'},\n\nThe shortlisted trainer is okay to proceed with your commercial for the ${req.technology_needed} requirement.\n\nAccepted Commercial:\n- INR ${trainerOffer.amount.toLocaleString('en-IN')} ${unitText}\n\nWe will proceed with interview slot coordination next.\n\nRegards,\nClahan Technologies`,
              mail_type: 'client_budget_acknowledgment',
            })
            showSendStatusToast({ trainerName: trainer.name, result: acceptedRes.data, title: 'Client commercial acceptance sent' })
            if (!isSendMailDelivered(acceptedRes?.data)) {
              toast.error(sendMailError(acceptedRes?.data, 'Failed to notify client about accepted commercial'))
              return false
            }

            const mail3Sent = await sendMail3SlotBooking(trainer, {
              detailsAcceptedAt: messageTime(reply) || Date.now(),
              clientCommercialsSentAt: Date.now(),
              commercialAcceptedByTrainerAt: Date.now(),
              commercial_status: 'accepted_by_trainer',
            })
            if (!mail3Sent) return false
            toast(`Auto: ${trainer.name} accepted the client commercial. Mail 3 slot booking sent.`, { icon: 'INR', duration: 5000 })
            return true
          }

          const commercialRes = await api.post('/shortlists/send-mail', {
            trainer_id: trainer.trainer_id,
            trainer_name: trainer.name,
            to_email: req.client_email,
            requirement_id: req.requirement_id,
            subject: `Shortlisted Trainer Commercials for Approval - ${req.technology_needed}`,
            body: `Hi ${req.client_name || 'Team'},\n\nThe shortlisted trainer has shared the required details and commercials for the ${req.technology_needed} requirement.\n\nCommercial Rate for Client Review:\n- INR ${clientAmount.toLocaleString('en-IN')} ${unitText}\n\nPlease review and confirm if this rate is acceptable. Once approved, we will proceed with interview slot coordination.\n\nRegards,\nClahan Technologies`,
            mail_type: 'trainer_commercials_to_client',
          })
          showSendStatusToast({ trainerName: trainer.name, result: commercialRes.data, title: 'Client commercials sent' })
          if (!isSendMailDelivered(commercialRes?.data)) {
            toast.error(sendMailError(commercialRes?.data, 'Failed to send commercials to client'))
            return false
          }

          setStage(trainer, 'details_received', {
            detailsAcceptedAt: messageTime(reply) || Date.now(),
            clientCommercialsSentAt: Date.now(),
            commercial_status: 'sent_to_client',
          })
          toast(`Auto: commercials sent to ${req.client_name || 'client'} for approval.`, { icon: 'INR', duration: 5000 })
          return true
        }
        const getThread = async trainer => {
          const res = await api.get(
            `/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}`
          )
          return (res.data.messages || [])
            .map(m => ({
              ...m,
              direction: m.direction === 'outbound' ? 'sent' : m.direction === 'inbound' ? 'received' : m.direction,
            }))
            .filter(m =>
              (!m.trainer_id     || String(m.trainer_id)     === String(trainer.trainer_id)) &&
              (!m.requirement_id || String(m.requirement_id) === String(req.requirement_id))
            )
        }

        // Selected means the requirement is fulfilled. Keep only the selected
        // trainer's post-selection ToC/confirmation workflow alive.
        for (const trainer of trainers) {
          const st = getStage(trainer)

          if (st === 'selected') {
            const { subject, body } = mailTocAutoTemplate(trainer, req)
            const res = await api.post('/shortlists/send-mail', {
              trainer_id:     trainer.trainer_id,
              trainer_name:   trainer.name,
              to_email:       trainer.email,
              requirement_id: req.requirement_id,
              subject, body,
              mail_type: 'mail6_toc',
            })
            showSendStatusToast({ trainerName: trainer.name, result: res.data, title: 'ToC request sent' })
            toast(`Auto: ToC request sent to ${trainer.name}`, { icon: 'i', duration: 4000 })
            onStatusUpdate(trainer.trainer_id, 'toc_requested')
            runningRef.current = false
            return
          }

          if (st === 'toc_requested') {
            const { subject, body } = mailTrainingConfirmedTemplate(
              trainer,
              req,
              req.client_name || req.client_company || '',
              req.client_phone || '',
              req.client_email || '',
              req.training_dates || req.timeline_start || '',
              req.mode || ''
            )
            const confirmRes = await api.post('/shortlists/send-mail', {
              trainer_id: trainer.trainer_id,
              trainer_name: trainer.name,
              to_email: trainer.email,
              requirement_id: req.requirement_id,
              subject,
              body,
              mail_type: 'mail7_confirm',
            })
            showSendStatusToast({ trainerName: trainer.name, result: confirmRes.data, title: 'Training confirmation sent' })
            let poExtra = {}
            if (req.client_email) {
              try {
                const poRes = await api.post(`/requirements/${req.requirement_id}/request-client-po`, {
                  trainer_id: trainer.trainer_id,
                  trainer_name: trainer.name,
                  client_email: req.client_email,
                  client_name: req.client_name || req.client_company || '',
                  training_dates: req.training_dates || req.timeline_start || '',
                })
                poExtra = {
                  clientPoRequestedAt: Date.now(),
                  clientPoRequestEmailId: poRes.data?.email_id,
                }
                toast.success(`PO request sent to ${poRes.data?.to_email || req.client_email}`)
              } catch (e) {
                toast.error(e.response?.data?.detail || e.message || 'PO request failed')
              }
            }
            onStatusUpdate(trainer.trainer_id, 'training_confirmed', poExtra)
            toast(`Auto: Training confirmed for ${trainer.name}`, { icon: 'i', duration: 5000 })
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
            })
            const delivered = isSendMailDelivered(res?.data)
            sentResults.push({ trainer, result: res.data })
            if (delivered) {
              setStage(trainer, 'waiting_reply1', { mail1SentAt: Date.now(), reminders: 0 })

            } else {
              showSendStatusToast({
                trainerName: trainer.name,
                result: { success: false, error: sendMailError(res?.data) },
                title: 'Mail 1 send failed',
              })
            }
          }
          showBulkSendStatusToast({ title: 'Mail 1 batch sent', results: sentResults })
          const deliveredCount = sentResults.filter(item => {
            return isSendMailDelivered(item.result)
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
        // replies move to Mail 2 for every shortlisted trainer who responded.
        await syncInboxReplies()
        for (const trainer of trainers) {
          if (getStage(trainer) !== 'waiting_reply1') continue

          const messages = await getThread(trainer)
          const mail1Messages = messages.filter(m =>
            m.direction === 'sent' &&
            (m.mail_type === 'mail1' || m.mail_type === 'mail1_reminder')
          )
          if (!mail1Messages.length) continue

          const firstSentTime = Math.min(...mail1Messages.map(messageTime))
          const lastSentTime = Math.max(...mail1Messages.map(messageTime))
          const repliesAfterMail1 = messages
            .filter(m => m.direction === 'received' && messageTime(m) > firstSentTime && !isDeliveryBounce(m.body || ''))
            .sort((a, b) => messageTime(a) - messageTime(b))

          if (repliesAfterMail1.length) {
            const latest = repliesAfterMail1[repliesAfterMail1.length - 1]
            const firstReply = repliesAfterMail1[0]
            const intent = detectIntent(latest.body)
            const rank = trainers.indexOf(trainer) + 1
            const replyAt = messageTime(firstReply) || Date.now()

            if (intent === 'negative') {
              toast(`Auto: ${trainer.name} (Rank ${rank}) declined`, { icon: 'i', duration: 5000 })
              setStage(trainer, 'rejected')
            } else {
              toast(`Auto: ${trainer.name} replied to Template 1 - queued for details`, { icon: 'mail', duration: 4000 })
              setStage(trainer, 'mail1_replied', {
                mail1ReplyAt: replyAt,
                mail1QuestionReply: isMail1OffStageQuestion(latest.body),
              })
            }
            continue
          }

          if (!allowReminders) continue

          const remindersSent = mail1Messages.filter(m => m.mail_type === 'mail1_reminder').length
          const hoursSinceLastSent = (Date.now() - lastSentTime) / (1000 * 60 * 60)
          for (let i = remindersSent; i < REMINDER_INTERVALS.length; i++) {
            const { hours, label } = REMINDER_INTERVALS[i]
            if (hoursSinceLastSent >= hours) {
              const { subject, body } = mail1Template(trainer, req, false, {}, true, i + 1)
              const res = await api.post('/shortlists/send-mail', {
                trainer_id:     trainer.trainer_id,
                trainer_name:   trainer.name,
                to_email:       trainer.email,
                requirement_id: req.requirement_id,
                subject, body,
                mail_type: 'mail1_reminder',
              })
              showSendStatusToast({ trainerName: trainer.name, result: res.data, title: 'Reminder sent' })
              const rank = trainers.indexOf(trainer) + 1
              toast(`Auto: ${label} sent to ${trainer.name} (Rank ${rank})`, { icon: 'i', duration: 4000 })
              break
            }
          }
        }

        // Mail 2 is also sent batch-style, like Mail 1. Later slot/interview
        // stages stay controlled so only one trainer is selected for the role.
        const mail2Responders = trainers
          .filter(t => getStage(t) === 'mail1_replied')
          .sort((a, b) => {
            const aTime = nextStates[a.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
            const bTime = nextStates[b.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
            return aTime - bTime || trainers.indexOf(a) - trainers.indexOf(b)
          })

        if (mail2Responders.length) {
          const sentResults = []
          for (const trainer of mail2Responders) {
            const messages = await getThread(trainer)
            const mail2AlreadySent = messages.some(m =>
              m.direction === 'sent' &&
              (m.mail_type === 'mail2' || m.mail_type === 'mail2_followup')
            )
            if (mail2AlreadySent) {
              setStage(trainer, 'waiting_reply2')
              continue
            }
            const mail1Reply = latestReplyAfter(messages, ['mail1', 'mail1_reminder'])
            if (mail1Reply && hasRequestedTrainerDetails(mail1Reply.body, req)) {
              setStage(trainer, 'details_received', {
                mail1ReplyAt: messageTime(mail1Reply) || Date.now(),
                detailsAcceptedAt: messageTime(mail1Reply) || Date.now(),
              })
              continue
            }

            const { subject, body } = mail2Template(trainer, req, mail1Reply?.body || '')
            const res = await api.post('/shortlists/send-mail', {
              trainer_id:     trainer.trainer_id,
              trainer_name:   trainer.name,
              to_email:       trainer.email,
              requirement_id: req.requirement_id,
              subject, body,
              mail_type: 'mail2',
            })
            sentResults.push({ trainer, result: res.data })
            setStage(trainer, 'waiting_reply2')
          }

          if (sentResults.length) {
            showBulkSendStatusToast({ title: 'Mail 2 batch sent', results: sentResults })
            toast(`Auto: Mail 2 sent to ${sentResults.length} shortlisted trainer${sentResults.length === 1 ? '' : 's'} who replied to Mail 1`, { icon: 'i', duration: 5000 })
            runningRef.current = false
            return
          }
        }

        // If one trainer is already past Mail 2, keep that trainer's pipeline
        // exclusive until manual selection/rejection completes.
        const activeTrainer = trainers.find(t =>
      ACTIVE_PIPELINE_STAGES.has(getStage(t))
        )
        const activeStage = activeTrainer ? getStage(activeTrainer) : null

        if (['interview_scheduled', 'selected', 'toc_requested', 'toc_received_pending'].includes(activeStage)) {
          runningRef.current = false
          return
        }

        if (activeStage === 'details_received') {
          const messages = await getThread(activeTrainer)
          const latestDetailsReply = latestReplyAfter(messages, ['mail2', 'mail2_followup', 'commercial_negotiation', 'trainer_rate_discussion'])
          const alreadySentClientCommercials = messages.some(m =>
            m.direction === 'sent' &&
            ['trainer_commercials_to_client', 'commercial_details_notification'].includes(m.mail_type)
          ) || Boolean(nextStates[activeTrainer.trainer_id]?.clientCommercialsSentAt)
          const clientAcceptedCommercial = messages.some(m =>
            m.direction === 'sent' &&
            m.mail_type === 'client_budget_acknowledgment'
          ) || nextStates[activeTrainer.trainer_id]?.commercial_status === 'accepted_by_trainer'
          const mail3AlreadySent = messages.some(m => m.direction === 'sent' && m.mail_type === 'mail3')
          if (!mail3AlreadySent) {
            const mail3Sent = await sendMail3SlotBooking(activeTrainer, {
              detailsAcceptedAt: messageTime(latestDetailsReply) || nextStates[activeTrainer.trainer_id]?.detailsAcceptedAt || Date.now(),
              clientCommercialsSentAt: nextStates[activeTrainer.trainer_id]?.clientCommercialsSentAt || Date.now(),
              commercialAcceptedByTrainerAt: nextStates[activeTrainer.trainer_id]?.commercialAcceptedByTrainerAt || Date.now(),
              commercial_status: 'accepted_by_trainer',
            })
            if (mail3Sent) {
              toast(`Auto: ${activeTrainer.name} shared requested details. Mail 3 slot booking sent.`, { icon: 'INR', duration: 5000 })
            }
          } else if (!alreadySentClientCommercials && latestDetailsReply) {
            await sendClientCommercialsFromReply(activeTrainer, latestDetailsReply, 'details_received')
          } else if (alreadySentClientCommercials && !mail3AlreadySent) {
            toast(`Commercials were sent to ${req.client_name || 'client'}. Waiting for client approval before Mail 3.`, { icon: 'INR', duration: 4000 })
          } else if (alreadySentClientCommercials) {
            toast(`Commercials were sent to ${req.client_name || 'client'} and Mail 3 is already sent.`, { icon: 'INR', duration: 4000 })
          }
          runningRef.current = false
          return
        }

        if (activeStage === 'slot_booked') {
          const messages = await getThread(activeTrainer)
          const latestDetailsReply = latestReplyAfter(messages, ['mail2', 'mail2_followup'])
          if (latestDetailsReply && hasRequestedTrainerDetails(latestDetailsReply.body, req) && !nextStates[activeTrainer.trainer_id]?.detailsAcceptedAt) {
            const negotiation = needsCommercialNegotiation(latestDetailsReply.body, req)
            const negotiationAlreadySent = messages.some(m => m.direction === 'sent' && m.mail_type === 'commercial_negotiation')
            if (negotiation && !negotiationAlreadySent) {
              const { subject, body } = trainerCommercialNegotiationTemplate(activeTrainer, req, negotiation.quote, negotiation.target)
              const res = await api.post('/shortlists/send-mail', {
                trainer_id:     activeTrainer.trainer_id,
                trainer_name:   activeTrainer.name,
                to_email:       activeTrainer.email,
                requirement_id: req.requirement_id,
                subject, body,
                mail_type: 'commercial_negotiation',
              })
              showSendStatusToast({ trainerName: activeTrainer.name, result: res.data, title: 'Commercial negotiation sent' })
              toast(`Auto: commercial negotiation sent to ${activeTrainer.name}`, { icon: 'i', duration: 5000 })
              setStage(activeTrainer, 'waiting_reply2', { commercialNegotiationAt: Date.now() })
              runningRef.current = false
              return
            }
            setStage(activeTrainer, 'details_received', {
              detailsAcceptedAt: messageTime(latestDetailsReply) || Date.now(),
            })
            toast(`Auto: ${activeTrainer.name} shared the requested details - ready for Slot Booking`, { icon: 'i', duration: 5000 })
            runningRef.current = false
            return
          }

          const mail2Messages = messages.filter(m =>
            m.direction === 'sent' &&
            (m.mail_type === 'mail2' || m.mail_type === 'mail2_followup')
          )
          const mail3Messages = messages.filter(m => m.direction === 'sent' && m.mail_type === 'mail3')
          if (!mail3Messages.length) { runningRef.current = false; return }

          if (mail2Messages.length && !nextStates[activeTrainer.trainer_id]?.slotConfirmed) {
            const lastMail2Time = Math.max(...mail2Messages.map(messageTime))
            const firstMail3Time = Math.min(...mail3Messages.map(messageTime))
            const mail2Replies = messages
              .filter(m =>
                m.direction === 'received' &&
                messageTime(m) > lastMail2Time &&
                messageTime(m) < firstMail3Time
              )
              .sort((a, b) => messageTime(a) - messageTime(b))

            if (mail2Replies.length && !mail2Replies.some(m => hasRequestedTrainerDetails(m.body, req))) {
              const latestMail2Reply = mail2Replies[mail2Replies.length - 1]
              const replyTime = messageTime(latestMail2Reply) || Date.now()
              const handledAt = nextStates[activeTrainer.trainer_id]?.detailsFollowupAt || 0
              const guardKey = `${req.requirement_id}:${activeTrainer.trainer_id}:mail2_followup:${replyTime}:${stripQuotedEmail(latestMail2Reply.body).slice(0, 80)}`
              if (replyTime > handledAt && shouldSendOnce(guardKey)) {
                const { subject, body } = mail2FollowupTemplate(activeTrainer, req, latestMail2Reply?.body || '')
                const res = await api.post('/shortlists/send-mail', {
                  trainer_id:     activeTrainer.trainer_id,
                  trainer_name:   activeTrainer.name,
                  to_email:       activeTrainer.email,
                  requirement_id: req.requirement_id,
                  subject, body,
                  mail_type: 'mail2_followup',
                })
                showSendStatusToast({ trainerName: activeTrainer.name, result: res.data, title: 'Details follow-up sent' })
                toast(`Auto: ${activeTrainer.name} reached Slot Booking without details - asked for details again`, { icon: 'i', duration: 7000 })
              }
              setStage(activeTrainer, 'waiting_reply2', { detailsFollowupAt: replyTime })
              runningRef.current = false
              return
            }
          }

          const lastMail3Time = Math.max(...mail3Messages.map(messageTime))
          const handledAt = nextStates[activeTrainer.trainer_id]?.slotReplyAt || 0
          const newReplies = messages
            .filter(m =>
              m.direction === 'received' &&
              messageTime(m) > lastMail3Time &&
              messageTime(m) > handledAt
            )
            .sort((a, b) => messageTime(a) - messageTime(b))

          if (!newReplies.length) {
            runningRef.current = false
            return
          }

          const latest = newReplies[newReplies.length - 1]
          const replyTime = messageTime(latest) || Date.now()
          const intent = detectIntent(latest.body)
          const rank = trainers.indexOf(activeTrainer) + 1

          if (intent === 'negative') {
            toast(`Auto: ${activeTrainer.name} (Rank ${rank}) is unavailable/declined after slot mail - moving to next Mail 1 responder`, { icon: 'i', duration: 6000 })
            setStage(activeTrainer, 'rejected')
            runningRef.current = false
            return
          }

          if (!hasProperInterviewSlots(latest.body)) {
            const handledAt = nextStates[activeTrainer.trainer_id]?.slotClarificationAt || 0
            const guardKey = `${req.requirement_id}:${activeTrainer.trainer_id}:mail3_slot_followup:${replyTime}:${stripQuotedEmail(latest.body).slice(0, 80)}`
            if (replyTime > handledAt && shouldSendOnce(guardKey)) {
              const res = await sendSlotClarificationMail({ trainer: activeTrainer, req })
              showSendStatusToast({ trainerName: activeTrainer.name, result: res, title: 'Slot clarification sent' })
              toast(`Auto: ${activeTrainer.name} did not share a clear dated AM/PM slot, so clarification mail was sent.`, { icon: 'i', duration: 6000 })
            }
            setStage(activeTrainer, 'slot_booked', { slotClarificationAt: replyTime })
            runningRef.current = false
            return
          }

          const slotText = stripQuotedEmail(latest.body)
          const detailsReplyForClient = latestTrainerDetailsReply(messages, req)
          const trainerDetailsText = stripQuotedEmail(detailsReplyForClient?.body || '')
          const extra = { slotReplyAt: replyTime, slotConfirmed: true, clientSlotText: slotText }
          if (AUTO_SEND_CLIENT_SLOTS && !nextStates[activeTrainer.trainer_id]?.clientSlotsSentAt) {
            try {
              const sent = await sendSlotsToClient({ trainer: activeTrainer, req, slotText, trainerDetailsText, force: false })
              if (sent?.success) {
                extra.clientSlotsSentAt = Date.now()
                extra.clientSlotsEmailId = sent.email_id
                toast('Auto: trainer slots sent to client for confirmation', { icon: 'i', duration: 5000 })
              } else {
                toast.error(sent?.error || 'Could not send trainer slots to client')
              }
            } catch (e) {
              toast.error(e.response?.data?.detail || e.message || 'Could not send trainer slots to client')
            }
          }
          toast(`Auto: ${activeTrainer.name} shared proper slots. Client confirmation step is updated.`, { icon: 'i', duration: 5000 })
          setStage(activeTrainer, 'slot_booked', extra)

          if (intent === '__legacy_positive__') {
            toast(`Auto: ${activeTrainer.name} confirmed slot availability. Interview link mail is ready for AI generation.`, { icon: 'i', duration: 5000 })
            const slotText = stripQuotedEmail(latest.body)
            const detailsReplyForClient = latestTrainerDetailsReply(messages, req)
            const trainerDetailsText = stripQuotedEmail(detailsReplyForClient?.body || '')
            const extra = { slotReplyAt: replyTime, slotConfirmed: true, clientSlotText: slotText }
            if (AUTO_SEND_CLIENT_SLOTS && !nextStates[activeTrainer.trainer_id]?.clientSlotsSentAt) {
              try {
                const sent = await sendSlotsToClient({ trainer: activeTrainer, req, slotText, trainerDetailsText, force: false })
                if (sent?.success) {
                  extra.clientSlotsSentAt = Date.now()
                  extra.clientSlotsEmailId = sent.email_id
                  toast('Auto: trainer slots sent to client for confirmation', { icon: 'i', duration: 5000 })
                } else {
                  toast.error(sent?.error || 'Could not send trainer slots to client')
                }
              } catch (e) {
                toast.error(e.response?.data?.detail || e.message || 'Could not send trainer slots to client')
              }
            }
            setStage(activeTrainer, 'slot_booked', extra)
          }

          runningRef.current = false
          return
        }

        if (activeStage === 'waiting_reply2') {
          const messages = await getThread(activeTrainer)
          const sentMails = messages.filter(m => m.direction === 'sent')
          if (!sentMails.length) { runningRef.current = false; return }
          const lastSentTime = Math.max(...sentMails.map(messageTime))
          const newReplies = messages.filter(m =>
            m.direction === 'received' &&
            messageTime(m) > lastSentTime
          )
          if (!newReplies.length) { runningRef.current = false; return }

          const latest = newReplies[newReplies.length - 1]
          const intent = detectIntent(latest.body)
          const replyTime = messageTime(latest) || Date.now()
          const handledAt = nextStates[activeTrainer.trainer_id]?.detailsFollowupAt || 0
          const rank   = trainers.indexOf(activeTrainer) + 1
          const lastSentMail = sentMails
            .slice()
            .sort((a, b) => messageTime(b) - messageTime(a))[0]
          const isNegotiationReply = lastSentMail?.mail_type === 'commercial_negotiation'
          const isClientBudgetRevisionReply = lastSentMail?.mail_type === 'client_budget_revision_request'
          const acceptedNegotiatedCommercial = isNegotiationReply && isCommercialAcceptedAfterNegotiation(latest.body, req)
          const acceptedClientBudgetRevision = isClientBudgetRevisionReply && intent === 'positive'

          if (isNegotiationReply && !acceptedNegotiatedCommercial) {
            const clientBudget = clientBudgetInfo(req)
            const revisedQuote = extractCommercialCounterOffer(latest.body, clientBudget)
            if (intent === 'negative' && !revisedQuote) {
              toast(`Auto: ${activeTrainer.name} did not accept the commercial. Moving to another trainer.`, { duration: 6000 })
              setStage(activeTrainer, 'rejected', {
                commercialRejectedAt: replyTime,
                commercialRejectedBy: 'trainer',
              })
              runningRef.current = false
              return
            }
            const requestedRateForQuote = revisedQuote ? clientRateFromTrainerRate(revisedQuote.amount) : 0
            const stillAboveClientBudget = revisedQuote && clientBudget && revisedQuote.unit === clientBudget.unit && requestedRateForQuote > clientBudget.amount
            if (stillAboveClientBudget) {
              if (!clientBudget) {
                toast.error('Client budget is missing. Cannot request a revised commercial from client.')
                runningRef.current = false
                return
              }
              try {
                const requestedBudget = requestedRateForQuote
                const clientRes = await requestClientBudgetIncrease({ trainer: activeTrainer, req, clientBudget, requestedBudget })
                const requestedBudgetDisplay = Number(clientRes?.requested_budget || requestedBudget || 0)
                const unit = clientRes?.unit || clientBudget.unit || 'day'
                toast.success(
                  clientRes?.skipped
                    ? 'Client budget revision request already sent'
                    : `Client budget revision requested: INR ${requestedBudgetDisplay.toLocaleString('en-IN')} per ${unit}`,
                  { duration: 6000 }
                )
                setStage(activeTrainer, 'waiting_reply2', {
                  clientBudgetRevisionRequestedAt: Date.now(),
                  clientBudgetRevisionEmailId: clientRes?.email_id,
                })
              } catch (e) {
                toast.error(e.response?.data?.detail || e.message || 'Could not request budget revision from client')
              }
              runningRef.current = false
              return
            }
          }

          if (isClientBudgetRevisionReply) {
            if (intent === 'negative') {
              toast(`Auto: client did not approve the budget revision for ${activeTrainer.name}. Moving to the next available trainer.`, { duration: 6000 })
              setStage(activeTrainer, 'rejected', {
                commercialRejectedAt: replyTime,
                commercialRejectedBy: 'client',
              })
              runningRef.current = false
              return
            }
            if (!acceptedClientBudgetRevision) {
              toast('Client budget revision reply needs manual review before moving ahead.', { duration: 6000 })
              setStage(activeTrainer, 'waiting_reply2', { clientBudgetRevisionReviewAt: replyTime })
              runningRef.current = false
              return
            }
          }

          if (!isNegotiationReply && !isClientBudgetRevisionReply && intent === 'negative') {
            toast(`Auto: ${activeTrainer.name} (Rank ${rank}) declined - moving to next Mail 1 responder`, { icon: 'i', duration: 5000 })
            setStage(activeTrainer, 'rejected')
            runningRef.current = false
            return
          }

          if (acceptedNegotiatedCommercial) {
            await sendClientCommercialsFromReply(activeTrainer, latest, 'accepted_negotiation')
            runningRef.current = false
            return
          } else if (acceptedClientBudgetRevision) {
            toast(`Auto: client approved revised commercials for ${activeTrainer.name}. Slot booking is now ready.`, { icon: 'INR', duration: 5000 })
            setStage(activeTrainer, 'details_received', { clientBudgetRevisionAcceptedAt: replyTime })
            runningRef.current = false
            return
          } else if (!hasRequestedTrainerDetails(latest.body, req)) {
            const guardKey = `${req.requirement_id}:${activeTrainer.trainer_id}:mail2_followup:${replyTime}:${stripQuotedEmail(latest.body).slice(0, 80)}`
            if (replyTime > handledAt && shouldSendOnce(guardKey)) {
              const { subject, body } = mail2FollowupTemplate(activeTrainer, req, latest?.body || '')
              const res = await api.post('/shortlists/send-mail', {
                trainer_id:     activeTrainer.trainer_id,
                trainer_name:   activeTrainer.name,
                to_email:       activeTrainer.email,
                requirement_id: req.requirement_id,
                subject, body,
                mail_type: 'mail2_followup',
              })
              showSendStatusToast({ trainerName: activeTrainer.name, result: res.data, title: 'Details follow-up sent' })
              toast(`Auto: ${activeTrainer.name} replied without the requested details - details request sent again`, { icon: 'i', duration: 6000 })
              setStage(activeTrainer, 'waiting_reply2', { detailsFollowupAt: replyTime })
            }
            runningRef.current = false
            return
          }

          const negotiation = needsCommercialNegotiation(latest.body, req)
          const negotiationAlreadySent = messages.some(m => m.direction === 'sent' && m.mail_type === 'commercial_negotiation')
          if (negotiation && !negotiationAlreadySent) {
            const { subject, body } = trainerCommercialNegotiationTemplate(activeTrainer, req, negotiation.quote, negotiation.target)
            const res = await api.post('/shortlists/send-mail', {
              trainer_id:     activeTrainer.trainer_id,
              trainer_name:   activeTrainer.name,
              to_email:       activeTrainer.email,
              requirement_id: req.requirement_id,
              subject, body,
              mail_type: 'commercial_negotiation',
            })
            showSendStatusToast({ trainerName: activeTrainer.name, result: res.data, title: 'Commercial negotiation sent' })
            toast(`Auto: commercial negotiation sent to ${activeTrainer.name}`, { icon: 'i', duration: 5000 })
            setStage(activeTrainer, 'waiting_reply2', { commercialNegotiationAt: Date.now() })
            runningRef.current = false
            return
          }

          await sendClientCommercialsFromReply(activeTrainer, latest, 'mail2_details')
          runningRef.current = false
          return

        }

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

// â”€â”€â”€ Trainer Card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function TrainerCard({ trainer, rank, state, req, onStatusUpdate, onRequirementPatch, autoMode, isActive }) {
  const stage     = resolveTrainerStage(trainer, req, state)
  const stageInfo = STAGES[stage] || STAGES.pending
  const [mailModal, setMailModal] = useState(null)
  const [manualMailType, setManualMailType] = useState('mail1')
  const [showThread, setShowThread] = useState(false)
  const [showTocModal, setShowTocModal] = useState(false)
  const [showPoModal, setShowPoModal] = useState(false)
  const [sendingToc, setSendingToc] = useState(false)
  const [sendingClientPo, setSendingClientPo] = useState(false)
  const [sendingClientSlots, setSendingClientSlots] = useState(false)
  const [sendingCommercials, setSendingCommercials] = useState(false)
  const [sendingNegotiation, setSendingNegotiation] = useState(false)
  const [showNegotiationModal, setShowNegotiationModal] = useState(false)
  const [showTemplates, setShowTemplates] = useState(false)
  const [clientBudget, setClientBudget] = useState('')
  const [clientEmailRequest, setClientEmailRequest] = useState(null)
  const [threadMessages, setThreadMessages] = useState([])
  const [profileEnhancement, setProfileEnhancement] = useState(null)
  const [showProfileEnhancement, setShowProfileEnhancement] = useState(false)
  const [profileEnhancementBusy, setProfileEnhancementBusy] = useState(false)
  const [approvedProfileSuggestions, setApprovedProfileSuggestions] = useState([])
  const [editedProfileBullets, setEditedProfileBullets] = useState({})
  const [trainerConfirmations, setTrainerConfirmations] = useState({})
  const [trainerConfirmationReference, setTrainerConfirmationReference] = useState('')

  const BTN = 'flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-white transition-all active:scale-95 shadow-sm'

  const analyzeProfileAgainstRequirement = async () => {
    setProfileEnhancementBusy(true)
    try {
      const res = await api.post('/profile-enhancements/analyze', {
        requirement_id: req.requirement_id,
        trainer_id: trainer.trainer_id,
      })
      const enhancement = res.data.enhancement
      setProfileEnhancement(enhancement)
      setApprovedProfileSuggestions(
        (enhancement?.analysis?.suggestions || [])
          .filter(item => !item.requires_trainer_confirmation && item.suggested_bullet)
          .map(item => item.id)
      )
      setEditedProfileBullets(Object.fromEntries(
        (enhancement?.analysis?.suggestions || []).map(item => [item.id, item.suggested_bullet || ''])
      ))
      setShowProfileEnhancement(true)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Could not analyze trainer profile')
    } finally {
      setProfileEnhancementBusy(false)
    }
  }

  const approveProfileEnhancement = async () => {
    setProfileEnhancementBusy(true)
    try {
      const res = await api.post(
        `/profile-enhancements/${req.requirement_id}/${trainer.trainer_id}/approve`,
        {
          approved_suggestion_ids: approvedProfileSuggestions,
          edited_bullets: editedProfileBullets,
          confirmed_by: 'shortlist_review',
        }
      )
      setProfileEnhancement(res.data.enhancement)
      setShowProfileEnhancement(false)
      toast.success(`${res.data.approved_count || 0} verified profile addition(s) approved`)
      onStatusUpdate(trainer.trainer_id, stage, {
        profile_enhancement_status: 'approved',
        approved_profile_bullets: res.data.enhancement?.approved_bullets || [],
      })
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Could not approve profile enhancement')
    } finally {
      setProfileEnhancementBusy(false)
    }
  }

  const recordTrainerProfileConfirmation = async () => {
    if (!trainerConfirmationReference.trim()) {
      toast.error('Enter the trainer name or email confirmation reference')
      return
    }
    setProfileEnhancementBusy(true)
    try {
      const res = await api.post(
        `/profile-enhancements/${req.requirement_id}/${trainer.trainer_id}/confirm`,
        {
          confirmed_bullets: trainerConfirmations,
          confirmed_by: trainerConfirmationReference.trim(),
          confirmation_source: 'trainer_email_or_call',
        }
      )
      const enhancement = res.data.enhancement
      setProfileEnhancement(enhancement)
      setEditedProfileBullets(current => ({
        ...current,
        ...Object.fromEntries((enhancement.analysis?.suggestions || []).map(item => [item.id, item.suggested_bullet || ''])),
      }))
      setApprovedProfileSuggestions(current => [
        ...new Set([...current, ...(enhancement.analysis?.suggestions || [])
          .filter(item => !item.requires_trainer_confirmation && item.suggested_bullet)
          .map(item => item.id)]),
      ])
      toast.success(`${res.data.confirmed_count} trainer confirmation(s) recorded`)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Could not record trainer confirmation')
    } finally {
      setProfileEnhancementBusy(false)
    }
  }

  const getThread = async trainer => {
    const res = await api.get(
      `/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}`
    )
    return (res.data.messages || [])
      .map(m => ({
        ...m,
        direction: m.direction === 'outbound' ? 'sent' : m.direction === 'inbound' ? 'received' : m.direction,
      }))
      .filter(m =>
        (!m.trainer_id     || String(m.trainer_id)     === String(trainer.trainer_id)) &&
        (!m.requirement_id || String(m.requirement_id) === String(req.requirement_id))
      )
  }

  const sendNegotiationEmail = async () => {
    if (!clientBudget || isNaN(clientBudget)) {
      toast.error('âŒ Please enter a valid client budget amount')
      return
    }

    setSendingNegotiation(true)
    try {
      const budgetAmount = parseInt(clientBudget)
      const trainerOffer = trainerRateFromClientBudget(budgetAmount)

      if (trainerOffer <= 0) {
        toast.error('Client budget must be valid for trainer offer')
        setSendingNegotiation(false)
        return
      }

      const { subject, body } = trainerCommercialNegotiationTemplate(trainer, req, 0, {
        amount: trainerOffer,
        unit: 'day',
        clientBudget: { amount: budgetAmount, unit: 'day' },
      })

      const negotiationRes = await api.post('/shortlists/send-mail', {
        trainer_id: trainer.trainer_id,
        trainer_name: trainer.name,
        to_email: trainer.email,
        requirement_id: req.requirement_id,
        subject: subject,
        body: body,
        mail_type: 'commercial_negotiation',
      })

      if (isSendMailDelivered(negotiationRes?.data)) {
        // Also send confirmation email to client
        try {
          const clientRes = await api.post('/shortlists/send-mail', {
            trainer_id: trainer.trainer_id,
            trainer_name: trainer.name,
            to_email: req.client_email,
            requirement_id: req.requirement_id,
            subject: `Trainer Found â€“ Rate Negotiation in Progress | ${req.technology_needed}`,
            body: `Hi ${req.client_name || 'Team'},\n\nGood news. We have reviewed a suitable shortlisted trainer profile for your ${req.technology_needed} requirement.\n\nWe are currently aligning the commercial rates based on your budget of â‚¹${budgetAmount.toLocaleString('en-IN')}/day.\n\nWe will update you within 24 hours with the confirmation.\n\nThank you for your patience.\n\nRegards,\nClahan Technologies`,
            mail_type: 'trainer_negotiation_client_update',
          })
          
          if (isSendMailDelivered(clientRes?.data)) {
            toast.success(`ðŸ“§ Trainer negotiation sent âœ…\nðŸ“§ Client update sent âœ…`)
            setShowNegotiationModal(false)
            setClientBudget('')
          } else {
            toast.success(`ðŸ“§ Trainer negotiation sent âœ…\nâš ï¸ Failed to send client update`)
            setShowNegotiationModal(false)
            setClientBudget('')
          }
        } catch {
          toast.success(`ðŸ“§ Trainer negotiation sent âœ…\nâš ï¸ Could not send client update`)
          setShowNegotiationModal(false)
          setClientBudget('')
        }
      } else {
        toast.error(negotiationRes?.data?.error || 'Failed to send negotiation email')
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Error sending negotiation email')
    } finally {
      setSendingNegotiation(false)
    }
  }

  const sendManualPipelineTemplate = async () => {
    if (manualMailType === 'mail6_toc') {
      handleTocRequest()
      return
    }
    
    if (manualMailType === 'trainer_acknowledgment') {
      toast('Trainer thank-you mail is skipped. Send Mail 3 slot booking or ask only missing details.', { duration: 5000 })
      return
    }
    if (manualMailType === 'client_budget_reply') {
      // Simulate client replying with their budget
      const clientBudget = prompt('Enter client budget per day (e.g., 40000)')
      if (!clientBudget) return
      
      try {
        const budgetAmount = parseInt(clientBudget.replace(/[â‚¹,]/g, ''))
        if (isNaN(budgetAmount) || budgetAmount <= 0) {
          toast.error('âŒ Invalid budget amount')
          return
        }
        
        // Get trainer rate (assuming trainer.rate or trainer.amount exists)
        const trainerRate = trainer.rate || trainer.amount || 0
        const budgetGap = trainerRate - budgetAmount
        
        // Send email as if client is replying with budget
        const clientReplyRes = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: req.client_email,
          requirement_id: req.requirement_id,
          subject: `RE: Shortlisted Trainer Commercials for Approval â€“ ${req.technology_needed}`,
          body: `Hi Team,\n\nThank you for sharing the commercial rates. Our budget for this ${req.technology_needed} requirement is â‚¹${budgetAmount.toLocaleString('en-IN')} per day.\n\nPlease confirm if the trainer can work within this budget.\n\nRegards,\n${req.client_name || 'Client Team'}`,
          mail_type: 'client_budget_reply',
          direction: 'received', // Mark as incoming
        })
        
        if (isSendMailDelivered(clientReplyRes?.data)) {
          // Check if there's a budget gap
          if (budgetGap <= 0) {
            // NO GAP - Client budget is equal or higher than trainer rate
            // Send Mail 3 (Slot Booking) directly to trainer
            toast.success(`âœ… Client budget reply sent (â‚¹${budgetAmount.toLocaleString('en-IN')}/day) - No gap detected`)
            toast.success(`ðŸŽ¯ Client budget matches trainer rate! Sending slot booking directly...`)
            
            const { subject, body } = mail3Template(trainer, req, '')
            const mail3Res = await api.post('/shortlists/send-mail', {
              trainer_id: trainer.trainer_id,
              trainer_name: trainer.name,
              to_email: trainer.email,
              requirement_id: req.requirement_id,
              subject,
              body,
              mail_type: 'mail3',
            })
            
            if (isSendMailDelivered(mail3Res?.data)) {
              toast.success(`ðŸ“… Mail 3 (Slot Booking) sent to trainer`)
            }
          } else {
            // GAP EXISTS - Continue with negotiation flow
            toast.success(`âœ… Client budget reply sent (â‚¹${budgetAmount.toLocaleString('en-IN')}/day)`)
            toast.info(`âš–ï¸ Rate gap detected: â‚¹${budgetGap.toLocaleString('en-IN')} - Continue to negotiation`)
          }
        } else {
          toast.error(clientReplyRes?.data?.error || 'Failed to send client budget reply')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending client budget reply')
      }
      return
    }
    
    if (manualMailType === 'client_budget_acknowledgment') {
      // Send acknowledgment to client after they reply with budget
      const clientBudget = prompt('Enter the client budget they mentioned (e.g., 40000)')
      if (!clientBudget) return
      
      try {
        const budgetAmount = parseInt(clientBudget.replace(/[â‚¹,]/g, ''))
        if (isNaN(budgetAmount) || budgetAmount <= 0) {
          toast.error('âŒ Invalid budget amount')
          return
        }
        
        const ackRes = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: req.client_email,
          requirement_id: req.requirement_id,
          subject: `RE: Budget Confirmation â€“ ${req.technology_needed} | Negotiation in Progress`,
          body: `Hi ${req.client_name || 'Team'},\n\nThank you for confirming your budget of â‚¹${budgetAmount.toLocaleString('en-IN')} per day for the ${req.technology_needed} requirement.\n\nWe have received your budget constraint and are aligning the shortlisted profile with your budget. If the commercial can be aligned, we will proceed immediately.\n\nIf not, we will identify an alternative trainer according to your requirements and share the details shortly.\n\nWe will update you within 24 hours with the outcome.\n\nThank you for your patience.\n\nRegards,\nClahan Technologies`,
          mail_type: 'client_budget_acknowledgment',
        })
        
        if (isSendMailDelivered(ackRes?.data)) {
          toast.success(`âœ… Budget acknowledgment sent to ${req.client_name || 'client'}`)
        } else {
          toast.error(ackRes?.data?.error || 'Failed to send budget acknowledgment')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending budget acknowledgment')
      }
      return
    }
    
    if (manualMailType === 'rate_gap_resolution') {
      // Send rate gap resolution options to client
      const trainerRate = prompt('Enter trainer rate (e.g., 50000)')
      if (!trainerRate) return
      
      const clientBudget = prompt('Enter client budget (e.g., 45000)')
      if (!clientBudget) return
      
      try {
        const trainerAmount = parseInt(trainerRate.replace(/[â‚¹,]/g, ''))
        const clientAmount = parseInt(clientBudget.replace(/[â‚¹,]/g, ''))
        
        if (isNaN(trainerAmount) || isNaN(clientAmount) || trainerAmount <= 0 || clientAmount <= 0) {
          toast.error('âŒ Invalid amounts')
          return
        }
        
        const gap = trainerAmount - clientAmount
        
        if (gap <= 0) {
          toast.error('âŒ Trainer rate should be higher than client budget for this email')
          return
        }
        
        const gapRes = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: req.client_email,
          requirement_id: req.requirement_id,
          subject: `Training Rate Discussion â€“ ${req.technology_needed}`,
          body: `Dear ${req.client_name || 'Team'},\n\nThank you for confirming your budget for the ${req.technology_needed} requirement. We truly appreciate your quick response.\n\nWe have reviewed a suitable shortlisted trainer profile and are sharing the commercial options for your review.\n\n**Commercial Details:**\nQuoted Rate: â‚¹${trainerAmount.toLocaleString('en-IN')} per day\nYour Budgeted Amount: â‚¹${clientAmount.toLocaleString('en-IN')} per day\nRate Difference: â‚¹${gap.toLocaleString('en-IN')} per day\n\n**We would like to present two options for your consideration:**\n\n**Option 1: Proceed with the shortlisted trainer**\nThis profile is aligned with the requirement based on the available skill match and delivery fit.\n\n**Option 2: Identify an Alternative Trainer**\nWe can search for another qualified trainer who aligns with your budget of â‚¹${clientAmount.toLocaleString('en-IN')} per day while meeting your specific requirements.\n\nKindly let us know your preference at your earliest convenience.\n\nRegards,\nClahan Technologies`,
          mail_type: 'rate_gap_resolution',
        })
        
        if (isSendMailDelivered(gapRes?.data)) {
          toast.success(`âœ… Rate gap email sent (Gap: â‚¹${gap.toLocaleString('en-IN')}/day)`)
          toast.info(`ðŸ“‹ Waiting for client to choose Option 1 or Option 2...`)
        } else {
          toast.error(gapRes?.data?.error || 'Failed to send rate gap resolution email')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending rate gap resolution email')
      }
      return
    }
    
    if (manualMailType === 'client_rate_gap_option1') {
      // Client chose Option 1: Proceed with trainer at higher rate
      // Send TOC details request to client
      try {
        const tocRes = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: req.client_email,
          requirement_id: req.requirement_id,
          subject: `Training Preparation â€“ ${req.technology_needed} | Please Confirm Session Details`,
          body: `Dear ${req.client_name || 'Team'},\n\nThank you for confirming your preference to proceed with the shortlisted trainer for your ${req.technology_needed} requirement.\n\nTo move ahead smoothly, kindly share any final session details or training agenda/ToC requirements you would like us to align before the next coordination step.\n\nRegards,\nClahan Technologies`,
          mail_type: 'client_toc_details_request',
        })
        
        if (isSendMailDelivered(tocRes?.data)) {
          toast.success(`âœ… Client confirmed Option 1 (Proceed)`)
          toast.success(`ðŸ“‹ TOC details request sent to ${req.client_name || 'client'}`)
        } else {
          toast.error(tocRes?.data?.error || 'Failed to send TOC details request')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending TOC details request')
      }
      return
    }
    
    if (manualMailType === 'client_rate_gap_option2') {
      // Client chose Option 2: Find alternative trainer within budget
      // Send acknowledgment and inform about next steps
      try {
        const option2Res = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: req.client_email,
          requirement_id: req.requirement_id,
          subject: `Training Engagement â€“ Exploring Alternative Options | ${req.technology_needed}`,
          body: `Dear ${req.client_name || 'Team'},\n\nThank you for your response regarding the shortlisted profile for your ${req.technology_needed} requirement.\n\nWe respect your decision to explore alternative trainers within your budget of â‚¹${parseInt(prompt('Enter client budget (e.g., 40000)') || 0).toLocaleString('en-IN')} per day.\n\nWe will identify another suitable profile aligned with your requirement and share the best-fit option for your review.\n\nRegards,\nClahan Technologies`,
          mail_type: 'client_rate_gap_option2',
        })
        
        if (isSendMailDelivered(option2Res?.data)) {
          toast.success(`âœ… Client confirmed Option 2 (Find Alternative)`)
          toast.success(`ðŸ”„ Alternative trainer search initiated`)
        } else {
          toast.error(option2Res?.data?.error || 'Failed to send option 2 acknowledgment')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending option 2 email')
      }
      return
    }
    
    if (manualMailType === 'trainer_rate_discussion') {
      // Send rate discussion message to trainer
      const trainerRate = prompt('Enter trainer rate (e.g., 50000)')
      if (!trainerRate) return
      
      const clientBudget = prompt('Enter client budget (e.g., 45000)')
      if (!clientBudget) return
      
      try {
        const trainerAmount = parseInt(trainerRate.replace(/[â‚¹,]/g, ''))
        const clientAmount = parseInt(clientBudget.replace(/[â‚¹,]/g, ''))
        
        if (isNaN(trainerAmount) || isNaN(clientAmount) || trainerAmount <= 0 || clientAmount <= 0) {
          toast.error('âŒ Invalid amounts')
          return
        }
        
        const targetAmount = trainerRateFromClientBudget(clientAmount)
        const gap = trainerAmount - targetAmount
        
        if (targetAmount <= 0) {
          toast.error('Client budget must be valid for trainer offer')
          return
        }

        if (gap <= 0) {
          toast.error('âŒ Trainer rate is already within the revised trainer offer')
          return
        }
        
        const trainerRes = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: trainer.email,
          requirement_id: req.requirement_id,
          subject: `Training Engagement Update â€“ ${req.technology_needed} | Rate Discussion`,
          body: `Dear ${trainer.name || 'Trainer'},\n\nThank you for sharing your details and commercials for the ${req.technology_needed} requirement.\n\nThe client has confirmed a budget of INR ${clientAmount.toLocaleString('en-IN')} per day. To align with this budget, kindly confirm if you can proceed at INR ${targetAmount.toLocaleString('en-IN')} per day.\n\nPlease let us know if this revised commercial is workable.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`,
          mail_type: 'trainer_rate_discussion',
        })
        
        if (isSendMailDelivered(trainerRes?.data)) {
          toast.success(`âœ… Rate discussion email sent to ${trainer.name}`)
        } else {
          toast.error(trainerRes?.data?.error || 'Failed to send trainer rate discussion email')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending trainer rate discussion email')
      }
      return
    }
    
    if (manualMailType === 'trainer_rate_accepted') {
      // Client accepted the rate - send confirmation to trainer and proceed with slots
      try {
        const acceptRes = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: trainer.email,
          requirement_id: req.requirement_id,
          subject: `Engagement Confirmed â€“ ${req.technology_needed} | Proceeding with Training`,
          body: `Dear ${trainer.name || 'Trainer'},\n\nCongratulations. The client has selected your profile for this assignment.\n\nWe will share the next steps and coordination details shortly.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`,
          mail_type: 'trainer_rate_accepted',
        })
        
        if (isSendMailDelivered(acceptRes?.data)) {
          toast.success(`âœ… Rate accepted confirmation sent to ${trainer.name}`)
          
          // Now send slot booking mail (mail3)
          try {
            const { subject: mail3Subject, body: mail3Body } = mail3Template(trainer, req, '')
            const mail3Res = await api.post('/shortlists/send-mail', {
              trainer_id: trainer.trainer_id,
              trainer_name: trainer.name,
              to_email: trainer.email,
              requirement_id: req.requirement_id,
              subject: mail3Subject,
              body: mail3Body,
              mail_type: 'mail3',
              client_email: req.client_email,
              client_name: req.client_name || req.client_company,
            })
            if (isSendMailDelivered(mail3Res?.data)) {
              toast.success(`ðŸ“… Slot booking mail sent to ${trainer.name}`)
            }
          } catch (e) {
            console.error('Slot booking error:', e)
          }
        } else {
          toast.error(acceptRes?.data?.error || 'Failed to send rate accepted confirmation')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending rate accepted email')
      }
      return
    }
    
    if (manualMailType === 'trainer_rate_rejected') {
      // Client rejected the rate - send rejection email to trainer
      const trainerRate = prompt('Enter trainer rate (e.g., 45000)')
      if (!trainerRate) return
      
      const clientBudget = prompt('Enter client budget (e.g., 40000)')
      if (!clientBudget) return
      
      try {
        const trainerAmount = parseInt(trainerRate.replace(/[â‚¹,]/g, ''))
        const clientAmount = parseInt(clientBudget.replace(/[â‚¹,]/g, ''))
        
        if (isNaN(trainerAmount) || isNaN(clientAmount) || trainerAmount <= 0 || clientAmount <= 0) {
          toast.error('âŒ Invalid amounts')
          return
        }
        
        const gap = trainerAmount - clientAmount
        
        const rejectRes = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: trainer.email,
          requirement_id: req.requirement_id,
          subject: `Update on ${req.technology_needed} Engagement â€“ Client Decision`,
          body: `Dear ${trainer.name || 'Trainer'},\n\nThank you for your time and interest in the ${req.technology_needed} requirement.\n\nAt this stage, the client has decided to proceed with another option.\n\nWe appreciate your cooperation and will reach out for future suitable requirements.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`,
          mail_type: 'trainer_rate_rejected',
        })
        
        if (isSendMailDelivered(rejectRes?.data)) {
          toast.success(`âœ… Rate rejection email sent to ${trainer.name}`)
        } else {
          toast.error(rejectRes?.data?.error || 'Failed to send rate rejection email')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending rate rejection email')
      }
      return
    }
    
    if (manualMailType === 'client_toc_details_request') {
      // Check if client sent TOC details or not
      const clientSentDetails = confirm('Did client send TOC details?\n\nOK = Yes, details received â†’ Send TOC to trainer\nCancel = No, not received â†’ Send reminder to client')
      
      if (clientSentDetails) {
        // CLIENT SENT DETAILS â†’ Prepare TOC and send to trainer
        try {
          const tocRes = await api.post('/shortlists/send-mail', {
            trainer_id: trainer.trainer_id,
            trainer_name: trainer.name,
            to_email: trainer.email,
            requirement_id: req.requirement_id,
            subject: `Terms of Collaboration (ToC) â€“ ${req.technology_needed} Training | ${req.client_name || 'Client'}`,
            body: `Dear ${trainer.name},\n\nPlease find the ToC / Course Agenda details for the ${req.technology_needed} requirement below.\n\nTraining Details:\nTechnology: ${req.technology_needed}\nTraining Rate: â‚¹${parseInt(prompt('Enter trainer rate (e.g., 45000)') || 0).toLocaleString('en-IN')} per day\n\nClient Session Details:\n${prompt('Paste client-provided session details (days, time, format, participants):') || 'Details to be confirmed'}\n\nPlease review and let us know if any clarification is required.\n\nRegards,\nClahan Technologies\nsujithaofficial585@gmail.com`,
            mail_type: 'mail6_toc',
          })
          
          if (isSendMailDelivered(tocRes?.data)) {
            toast.success(`âœ… TOC document prepared and sent to ${trainer.name}`)
            toast.success(`ðŸ“„ Client details have been shared with trainer`)
          } else {
            toast.error(tocRes?.data?.error || 'Failed to send TOC to trainer')
          }
        } catch (e) {
          toast.error(e.response?.data?.detail || e.message || 'Error sending TOC to trainer')
        }
      } else {
        // CLIENT DIDN'T SEND DETAILS â†’ Send reminder to client
        try {
          const reminderRes = await api.post('/shortlists/send-mail', {
            trainer_id: trainer.trainer_id,
            trainer_name: trainer.name,
            to_email: req.client_email,
            requirement_id: req.requirement_id,
            subject: `Follow-up: Training Session Details Required â€“ ${req.technology_needed}`,
            body: `Dear ${req.client_name || 'Team'},\n\nWe hope you are doing well.\n\nWe are following up on the final training session details for your ${req.technology_needed} requirement.\n\nKindly share any pending session details, participant information, or agenda/ToC expectations so we can proceed without delay.\n\nRegards,\nClahan Technologies`,
            mail_type: 'client_toc_details_followup',
          })
          
          if (isSendMailDelivered(reminderRes?.data)) {
            toast.success(`ðŸ”” Reminder sent to ${req.client_name || 'client'}`)
            toast.info(`ðŸ“‹ Waiting for client to provide TOC details`)
          } else {
            toast.error(reminderRes?.data?.error || 'Failed to send reminder')
          }
        } catch (e) {
          toast.error(e.response?.data?.detail || e.message || 'Error sending reminder')
        }
      }
      return
    }
    
    if (manualMailType === 'trainer_commercials_to_client') {
      // Send trainer commercials to client
      setSendingCommercials(true)
      try {
        const messages = await getThread(trainer)
        
        // Try to find mail2 reply first, then any received email that's not mail1/mail3
        let mail2Reply = messages.find(m => m.direction === 'received' && (m.mail_type === 'mail2' || m.mail_type === 'mail2_followup'))
        
        if (!mail2Reply) {
          // Fallback: look for any recent received email that might be trainer's response
          mail2Reply = messages.filter(m => 
            m.direction === 'received' && 
            m.mail_type !== 'mail1' && 
            m.mail_type !== 'mail3'
          ).sort((a, b) => messageTime(b) - messageTime(a))[0]
        }
        
        if (!mail2Reply) {
          toast.error('âŒ No trainer reply found. Trainer must respond to the details request first.')
          setSendingCommercials(false)
          return
        }
        
        const replyContent = mail2Reply.body || mail2Reply.reply_text || mail2Reply.content || ''
        const commercialMatches = replyContent.match(/â‚¹[\d,]+|inr\s*[\d,]+/gi) || []
        
        if (commercialMatches.length === 0) {
          toast.error('âŒ No charges/commercials found in trainer reply. Ask trainer to mention their rates.')
          setSendingCommercials(false)
          return
        }
        
        // Build client rates with Clahan markup
        const clientRates = commercialMatches.map(c => {
          const amount = parseInt(c.replace(/[â‚¹,inr\s]/gi, ''))
          return `â‚¹${clientRateFromTrainerRate(amount).toLocaleString('en-IN')}`
        })
        
        // Only show final client rates - don't mention trainer's original charges or Clahan markup
        const commercialDetails = clientRates.map(c => `- ${c}`).join('\n')
        const trainerDetails = trainerClientSummaryForHandoff(replyContent)
        const availabilityLines = extractAvailabilityLines(replyContent)
        const availabilityText = availabilityLines.length
          ? availabilityLines.map(line => `- ${line}`).join('\n')
          : '- Trainer availability will be confirmed based on your preferred discussion slot.'
        
        const commercialRes = await api.post('/shortlists/send-mail', {
          trainer_id: trainer.trainer_id,
          trainer_name: trainer.name,
          to_email: req.client_email,
          requirement_id: req.requirement_id,
          subject: `Shortlisted Trainer Details - ${req.technology_needed}`,
          body: `Dear ${req.client_name || 'Team'},\n\nThe shortlisted trainer has shared the requested details for the ${req.technology_needed} requirement. Please find the summary below for your review.\n\nTrainer: ${trainer.name || trainer.trainer_name || 'Shortlisted trainer'}\n\nTrainer Details:\n${trainerDetails || 'Profile/details shared by trainer are available for review.'}\n\nClient Commercials:\n${commercialDetails}\n\nTrainer Available Dates/Slots:\n${availabilityText}\n\nKindly confirm the preferred interview/discussion slot, and we will share the meeting link with both sides.\n\nRegards,\nClahan Technologies`,
          mail_type: 'trainer_commercials_to_client',
        })
        
        if (isSendMailDelivered(commercialRes?.data)) {
          toast.success(`Client handoff sent to ${req.client_name || 'client'}`)
          onStatusUpdate(trainer.trainer_id, 'details_received', { clientCommercialsSentAt: Date.now() })
          setSendingCommercials(false)
          return

        } else {
          toast.error(commercialRes?.data?.error || 'Failed to send commercials')
        }
      } catch (e) {
        toast.error(e.response?.data?.detail || e.message || 'Error sending commercials')
      } finally {
        setSendingCommercials(false)
      }
      return
    }
    
    setMailModal(manualMailType)
  }

  const renderManualPipelineSelector = () => (
    <div className="mt-3 flex flex-col gap-2 rounded-xl border border-slate-200 bg-slate-50 p-2">
      <button
        type="button"
        onClick={() => setShowTemplates(prev => !prev)}
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-bold text-slate-600 transition-all hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
      >
        <Send className="h-3.5 w-3.5" />
        {showTemplates ? 'Hide templates' : 'More templates'}
      </button>
      <button
        type="button"
        onClick={() => setShowNegotiationModal(true)}
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 text-xs font-bold text-amber-700 transition-all hover:border-amber-300 hover:bg-amber-100"
      >
        ðŸ’° Negotiate Rate
      </button>
      {showTemplates && (
        <div className="mt-2 flex flex-col gap-2 rounded-lg border border-blue-100 bg-white p-3 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Manual mail templates</p>
            <p className="mt-0.5 text-xs text-blue-600">Use only when you need to override the automation.</p>
          </div>
          <select
            value={manualMailType}
            onChange={e => setManualMailType(e.target.value)}
            className="h-9 rounded-lg border border-blue-200 bg-white px-2 text-xs font-semibold text-slate-700 outline-none focus:border-blue-400"
          >
            {PIPELINE_MAIL_OPTIONS.map(item => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={sendManualPipelineTemplate}
            disabled={(manualMailType === 'mail6_toc' && sendingToc) || (manualMailType === 'trainer_commercials_to_client' && sendingCommercials)}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-3 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {(manualMailType === 'mail6_toc' && sendingToc) || (manualMailType === 'trainer_commercials_to_client' && sendingCommercials) ? 
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 
              <Send className="h-3.5 w-3.5" />}
            Send
          </button>
        </div>
      )}
    </div>
  )

  const handleRequestClientPo = async () => {
    if (sendingClientPo) return
    if (!req?.client_email) {
      toast.error('Client email is required before requesting PO')
      return
    }
    setSendingClientPo(true)
    try {
      const subject = 'Request for Purchase Order'
      const duration = poDurationText(req) || 'To be confirmed'
      const trainingDates = state?.trainingDate || req.training_dates || req.timeline_start || ''
      const dayRate = poCommercialText(req, trainer) || 'To be confirmed'
      const trainingDateLine = trainingDates ? `- **Training Dates:** ${trainingDates}\n` : ''
      const modeText = [req.mode || req.delivery_mode || '', req.location || ''].filter(Boolean).join(' / ')
      const modeLine = modeText ? `- **Mode/Location:** ${modeText}\n` : ''
      const participantText = req.participant_count || req.participants || ''
      const participantLine = participantText ? `- **Participants:** ${participantText}\n` : ''
      const body = `Dear ${req.client_name || 'Client'},\n\nThank you for confirming the **${req.technology_needed || 'DevOps'}** training requirement.\n\nWe have identified a suitable trainer for this engagement.\n\n**Training Details:**\n\n- **Domain:** ${req.technology_needed || 'DevOps'}\n- **Duration:** ${duration}\n${trainingDateLine}${modeLine}${participantLine}- **Commercials:** ${dayRate}\n\nKindly share the Purchase Order (PO) at your earliest convenience so that we can proceed with trainer confirmation and the remaining training arrangements.\n\nPlease let us know if you require any additional information.\n\nRegards,\nClahan Technologies`

      const res = await api.post(`/requirements/${req.requirement_id}/request-client-po`, {
        trainer_id: trainer.trainer_id,
        trainer_name: trainer.name,
        client_email: req.client_email,
        client_name: req.client_name || req.client_company || '',
        training_dates: trainingDates,
        subject,
        body,
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

  const renderPostSelectionTools = ({ note = '', waiting = false, includeConfirm = false } = {}) => (
    <div className="flex flex-wrap gap-2 mt-3">
      {note && (
        <div className="w-full flex items-center gap-2 px-3 py-2 bg-teal-50 border border-teal-200 rounded-xl">
          {waiting && <Loader2 className="w-3.5 h-3.5 text-teal-500 animate-spin flex-shrink-0" />}
          <span className="text-xs text-teal-700 font-semibold">{note}</span>
        </div>
      )}
      <button onClick={() => setShowTocModal(true)} className={clsx(BTN, 'bg-emerald-600 hover:bg-emerald-700')}>
        <FileText className="w-3.5 h-3.5" /> Generate TOC
      </button>
      <button onClick={() => setShowPoModal(true)} className={clsx(BTN, 'bg-slate-900 hover:bg-slate-800')}>
        <FileText className="w-3.5 h-3.5" /> Generate PO
      </button>
      <button onClick={handleRequestClientPo} disabled={sendingClientPo || !req.client_email} className={clsx(BTN, 'bg-blue-600 hover:bg-blue-700 disabled:opacity-60')}>
        {sendingClientPo ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
        {stage === 'po_requested' ? 'Resend PO Request' : 'Request PO from Client'}
      </button>
      <button onClick={handleTocRequest} disabled={sendingToc} className={clsx(BTN, 'bg-teal-600 hover:bg-teal-700 disabled:opacity-60')}>
        {sendingToc ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
        {sendingToc ? 'Sending...' : stage === 'toc_requested' ? 'Resend ToC / Agenda' : 'Request ToC / Agenda'}
      </button>
    </div>
  )

  const renderActions = () => {
    // â”€â”€ ToC received â€” manual confirmation mail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if (stage === 'toc_received_pending') {
      return renderPostSelectionTools({
        note: 'ToC received from trainer. You can generate TOC/PO from here.',
      })
    }

    if (stage === 'training_confirmed') {
      return renderPostSelectionTools({
        note: 'Training confirmed and contact details shared with trainer.',
      })
    }

    if (['po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent'].includes(stage)) {
      return renderPostSelectionTools({
        note: 'Client PO flow active. Generate the invoice after the client PO is received, then send it to the saved client email.',
      })
    }

    if (stage === 'toc_requested') {
      return renderPostSelectionTools({
        note: 'Waiting for trainer to send ToC/Agenda. You can still generate TOC, generate PO, or resend the request.',
        waiting: true,
      })
    }

    if (stage === 'selected') {
      return renderPostSelectionTools()
    }

    if (stage === 'training_confirmed') {
      return (
        <div className="flex flex-wrap gap-2 mt-3">
          <div className="w-full px-3 py-2 bg-green-50 border border-green-200 rounded-xl">
            <span className="text-xs text-green-700 font-semibold">
              ðŸŽ“ All done! Training confirmed and contact details shared with trainer.
            </span>
          </div>
          <button onClick={() => setShowPoModal(true)} className={clsx(BTN, 'bg-slate-900 hover:bg-slate-800')}>
            <FileText className="w-3.5 h-3.5" /> Generate PO
          </button>
        </div>
      )
    }

    // toc_requested â€” auto is polling, show waiting
    if (stage === 'toc_requested') {
      return (
        <div className="flex items-center gap-2 px-3 py-2 mt-3 bg-teal-50 border border-teal-200 rounded-xl">
          <Loader2 className="w-3.5 h-3.5 text-teal-500 animate-spin flex-shrink-0" />
          <span className="text-xs text-teal-700 font-medium">
            â³ Waiting for trainer to send ToC/Agenda â€” auto detects reply and notifies you
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
        <div className="flex flex-wrap gap-2 mt-3">
          <button onClick={() => setShowTocModal(true)} className={clsx(BTN, 'bg-emerald-600 hover:bg-emerald-700')}>
            <FileText className="w-3.5 h-3.5" /> Generate TOC ðŸ“‹
          </button>
          <button onClick={() => setShowPoModal(true)} className={clsx(BTN, 'bg-slate-900 hover:bg-slate-800')}>
            <FileText className="w-3.5 h-3.5" /> Generate PO
          </button>
          <button onClick={handleTocRequest} disabled={sendingToc} className={clsx(BTN, 'bg-teal-600 hover:bg-teal-700 disabled:opacity-60')}>
            {sendingToc ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            {sendingToc ? 'Sending...' : 'Request ToC / Agenda'}
          </button>
        </div>
      )
    }

    // â”€â”€ AUTO MODE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if (autoMode) {
      if (stage === 'waiting_reply1') {
        return (
          <div className="space-y-2 mt-3">
            <div className="flex items-center gap-2 px-3 py-2 bg-sky-50 border border-sky-200 rounded-xl">
              <Loader2 className="w-3.5 h-3.5 text-sky-500 animate-spin flex-shrink-0" />
              <span className="text-xs text-sky-700 font-medium">
                â³ Mail 1 sent â€” checking replies every 10s while reminders run at 6h, 12h, 24h
              </span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-50 border border-orange-100 rounded-xl">
              <Bell className="w-3 h-3 text-orange-400 flex-shrink-0" />
              <span className="text-xs text-orange-600">Auto reminders: <strong>6h Â· 12h Â· 24h</strong></span>
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
                ? 'Next Mail 1 responder â€” sending Request Details shortly'
                : 'Replied to Mail 1 â€” queued until the current trainer pipeline finishes'}
            </span>
          </div>
        )
      }

      if (stage === 'waiting_reply2' || stage === 'slot_booked') {
        const msgs = {
          waiting_reply2: 'â³ Waiting for complete Mail 2 details â€” incomplete replies get a details request again',
          slot_booked:    state?.slotConfirmed
            ? 'âœ… Trainer confirmed slot availability â€” send the Interview Link'
            : 'â³ Waiting for reply to Mail 3 â€” negative replies auto-reject and move to the next queued trainer',
        }
        return (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2 px-3 py-2 bg-sky-50 border border-sky-200 rounded-xl">
              <Loader2 className="w-3.5 h-3.5 text-sky-500 animate-spin flex-shrink-0" />
              <span className="text-xs text-sky-700 font-medium">{msgs[stage]}</span>
            </div>
            {stage === 'slot_booked' && state?.slotConfirmed && (
              <button
                onClick={() => handleSendClientSlots({ force: true })}
                disabled={sendingClientSlots}
                className={clsx(BTN, 'bg-amber-600 hover:bg-amber-700 disabled:opacity-60')}
              >
                {sendingClientSlots ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                {state?.clientSlotsSentAt ? 'Resend Slots to Client' : 'Send Slots to Client'}
              </button>
            )}
          </div>
        )
      }

      if (stage === 'pending') {
        return (
          <div className="px-3 py-2 mt-3 bg-violet-50 border border-violet-200 rounded-xl">
            <span className="text-xs text-violet-700 font-medium">
              ðŸ¤– Mail 1 will be sent with the full shortlist batch
            </span>
          </div>
        )
      }

      if (stage === 'interview_scheduled') {
        return (
          <div className="mt-3 space-y-2">
            <div className="w-full px-3 py-2 bg-purple-50 border border-purple-200 rounded-xl">
              <span className="text-xs text-purple-700 font-semibold">
                Interview/discussion is scheduled. After client feedback, send the trainer selected or rejection update.
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => setMailModal('mail5_ok')} className={clsx(BTN, 'bg-emerald-600 hover:bg-emerald-700')}>
                <PartyPopper className="w-3.5 h-3.5" /> Trainer Selected
              </button>
              <button onClick={() => setMailModal('mail5_no')} className={clsx(BTN, 'bg-red-500 hover:bg-red-600')}>
                <ThumbsDown className="w-3.5 h-3.5" /> Trainer Rejected
              </button>
            </div>
          </div>
        )
      }

      return null
    }

    // â”€â”€ MANUAL MODE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    return (
      <div className="flex flex-wrap gap-2 mt-3">
        {stage === 'pending' && (
          <button onClick={() => setMailModal('mail1')} className={clsx(BTN, 'bg-blue-600 hover:bg-blue-700')}>
            <Mail className="w-3.5 h-3.5" /> Trainer Requirement
          </button>
        )}
        {(stage === 'mail1_sent' || stage === 'waiting_reply1' || stage === 'mail1_replied') && (
          <>
            <button onClick={() => setMailModal('mail1')} className={clsx(BTN, 'bg-slate-500 hover:bg-slate-600')}>
              <Mail className="w-3.5 h-3.5" /> Trainer Requirement
            </button>
          </>
        )}
        {(stage === 'details_requested' || stage === 'details_received') && (
          <button onClick={() => setMailModal('mail3')} className={clsx(BTN, 'bg-amber-500 hover:bg-amber-600')}>
            <Calendar className="w-3.5 h-3.5" /> Interview Slot / Result
          </button>
        )}
        {stage === 'slot_booked' && (
          <>
            {state?.slotConfirmed && (
              <>
                <button
                  onClick={() => handleSendClientSlots({ force: true })}
                  disabled={sendingClientSlots}
                  className={clsx(BTN, 'bg-amber-600 hover:bg-amber-700 disabled:opacity-60')}
                >
                  {sendingClientSlots ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                  {state?.clientSlotsSentAt ? 'Resend Slots to Client' : 'Send Slots to Client'}
                </button>
                <button onClick={() => setMailModal('mail4')} className={clsx(BTN, 'bg-purple-600 hover:bg-purple-700')}>
                  <Calendar className="w-3.5 h-3.5" /> Send Interview Link
                </button>
              </>
            )}
          </>
        )}
        {stage === 'interview_scheduled' && (
          <>
            <button onClick={() => setMailModal('mail4')} className={clsx(BTN, 'bg-purple-600 hover:bg-purple-700')}>
              <Calendar className="w-3.5 h-3.5" /> Resend Interview Link
            </button>
            <button onClick={() => setMailModal('mail5_ok')} className={clsx(BTN, 'bg-emerald-600 hover:bg-emerald-700')}>
              <PartyPopper className="w-3.5 h-3.5" /> Trainer Selected
            </button>
            <button onClick={() => setMailModal('mail5_no')} className={clsx(BTN, 'bg-red-500 hover:bg-red-600')}>
              <ThumbsDown className="w-3.5 h-3.5" /> Trainer Rejected
            </button>
          </>
        )}
        {stage === 'selected' && (
          <button onClick={handleTocRequest} disabled={sendingToc} className={clsx(BTN, 'bg-teal-600 hover:bg-teal-700 disabled:opacity-60')}>
            {sendingToc ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileText className="w-3.5 h-3.5" />}
            {sendingToc ? 'Sending...' : 'Request ToC / Agenda'}
          </button>
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

  const handleTocRequest = async () => {
    if (sendingToc) return

    setSendingToc(true)
    try {
      const { subject, body } = mailTocAutoTemplate(trainer, req)
      const res = await api.post('/shortlists/send-mail', {
        trainer_id: trainer.trainer_id,
        trainer_name: trainer.name,
        to_email: trainer.email,
        requirement_id: req.requirement_id,
        subject,
        body,
        mail_type: 'mail6_toc',
      })

      assertSendMailDelivered(res.data, 'ToC request failed')

      showSendStatusToast({ trainerName: trainer.name, result: res.data, title: 'ToC request sent' })
      toast.success('ToC request sent!')
      handleMailSent('toc_requested')
    } catch (e) {
      toast.error(e.message || 'ToC request failed')
    } finally {
      setSendingToc(false)
    }
  }

  const handleSendClientSlots = async ({ slotText = '', trainerDetailsText: providedTrainerDetailsText = '', force = true, clientEmail = '', clientName = '' } = {}) => {
    if (sendingClientSlots) return
    setSendingClientSlots(true)
    try {
      let text = slotText || state?.clientSlotText || ''
      let trainerDetailsText = providedTrainerDetailsText || state?.trainerDetailsText || ''
      if (!text) {
        const res = await api.get(`/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}`)
        const messages = res.data.messages || []
        const latestSlotReply = latestReplyAfter(messages, ['mail3'])
        const detailsReply = latestTrainerDetailsReply(messages, req)
        text = latestSlotReply?.body || ''
        trainerDetailsText = detailsReply?.body || trainerDetailsText
      }

      const sent = await sendSlotsToClient({ trainer, req, slotText: text, trainerDetailsText, force, clientEmail, clientName })
      if (sent?.success === false) throw new Error(sent.error || 'Client slot email failed')

      setClientEmailRequest(null)
      toast.success(sent?.already_sent ? 'Slots already sent to client' : 'Trainer slots sent to client')
      onStatusUpdate(trainer.trainer_id, stage, {
        clientSlotsSentAt: Date.now(),
        clientSlotsEmailId: sent.email_id || state?.clientSlotsEmailId,
        clientSlotText: stripQuotedEmail(text),
        trainerDetailsText: stripQuotedEmail(trainerDetailsText),
      })
    } catch (e) {
      const message = e.response?.data?.detail || e.message || 'Could not send trainer slots to client'
      if (String(message).toLowerCase().includes('client email not found')) {
        setClientEmailRequest({ slotText: slotText || state?.clientSlotText || '', force })
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

    const inferred = inferPipelineStateFromThread(messages)
    if (inferred?.status) {
      const { status, ...extra } = inferred
      if (status === 'slot_booked' && extra.slotConfirmed) {
        const latestSlotReply = latestReplyAfter(messages, ['mail3'])
        const detailsReply = latestTrainerDetailsReply(messages, req)
        const slotText = stripQuotedEmail(latestSlotReply?.body || '')
        if (slotText) extra.clientSlotText = slotText
        if (detailsReply?.body) extra.trainerDetailsText = stripQuotedEmail(detailsReply.body)
        if (AUTO_SEND_CLIENT_SLOTS && slotText && !state?.clientSlotsSentAt) {
          handleSendClientSlots({ slotText, trainerDetailsText: extra.trainerDetailsText || '', force: false })
        }
      }
      update(status, extra)
      return
    }

    const latestDetailsReply = latestReplyAfter(messages, ['mail2', 'mail2_followup'])
    if (latestDetailsReply && hasRequestedTrainerDetails(latestDetailsReply.body, req) && ['waiting_reply2', 'details_requested', 'slot_booked'].includes(current)) {
      update('details_received', {
        detailsAcceptedAt: messageTime(latestDetailsReply) || Date.now(),
      })
      return
    }

    const latestMail1Reply = latestReplyAfter(messages, ['mail1', 'mail1_reminder'])
    if (latestMail1Reply && ['pending', 'mail1_sent', 'waiting_reply1'].includes(current)) {
      update('mail1_replied', {
        mail1ReplyAt: messageTime(latestMail1Reply) || Date.now(),
      })
      return
    }

    const latestSlotReply = latestReplyAfter(messages, ['mail3'])
    if (latestSlotReply && current === 'slot_booked' && !state?.slotConfirmed) {
      const slotText = stripQuotedEmail(latestSlotReply.body)
      if (!hasProperInterviewSlots(slotText)) {
        const replyTime = messageTime(latestSlotReply) || Date.now()
        if (replyTime > (state?.slotClarificationAt || 0)) {
          sendSlotClarificationMail({ trainer, req })
            .then(res => showSendStatusToast({ trainerName: trainer.name, result: res, title: 'Slot clarification sent' }))
            .catch(e => toast.error(e.response?.data?.detail || e.message || 'Slot clarification failed'))
        }
        update('slot_booked', { slotClarificationAt: replyTime })
        return
      }
      update('slot_booked', {
        slotReplyAt: messageTime(latestSlotReply) || Date.now(),
        slotConfirmed: true,
        clientSlotText: slotText,
        trainerDetailsText: stripQuotedEmail(latestTrainerDetailsReply(messages, req)?.body || ''),
      })
      if (AUTO_SEND_CLIENT_SLOTS && !state?.clientSlotsSentAt) {
        handleSendClientSlots({ slotText, trainerDetailsText: stripQuotedEmail(latestTrainerDetailsReply(messages, req)?.body || ''), force: false })
      }
    }
  }

  return (
    <>
      {mailModal && mailModal !== 'mail6_toc' && (
        <MailModal trainer={trainer} req={req} mailType={mailModal}
          onClose={() => setMailModal(null)}
          onSent={handleMailSent}
          threadMessages={threadMessages} />
      )}
      {showThread && <ThreadModal trainer={trainer} req={req} onClose={() => setShowThread(false)} onThreadUpdate={(msgs) => { handleThreadUpdate(msgs); setThreadMessages(msgs) }} />}
      {showTocModal && <TocModal trainer={trainer} req={req} onClose={() => setShowTocModal(false)} />}
      {showPoModal && (
        <PurchaseOrderModal
          trainer={trainer}
          req={req}
          state={state}
          onClose={() => setShowPoModal(false)}
          onStageChange={(next, extra) => onStatusUpdate(trainer.trainer_id, next, extra)}
        />
      )}
      {showNegotiationModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="rounded-xl bg-white p-6 shadow-xl max-w-sm w-full mx-4">
            <h2 className="text-lg font-bold text-slate-900 mb-4">ðŸ’° Negotiate Trainer Rate</h2>
            <p className="text-sm text-slate-600 mb-4">
              Enter the client's maximum budget per day. We'll offer the trainer â‚¹5,000 less (Clahan margin).
            </p>
            <div className="mb-4">
              <label className="block text-xs font-semibold text-slate-700 mb-2">
                Client Budget (â‚¹/day)
              </label>
              <input
                type="number"
                placeholder="e.g., 40000"
                value={clientBudget}
                onChange={e => setClientBudget(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:border-amber-500 focus:outline-none text-sm"
              />
            </div>
            {clientBudget && !isNaN(clientBudget) && (
              <div className="mb-4 p-3 bg-amber-50 rounded-lg">
                <p className="text-xs font-semibold text-amber-900">
                  Trainer Offer: â‚¹{trainerRateFromClientBudget(parseInt(clientBudget)).toLocaleString('en-IN')}/day
                </p>
                <p className="text-xs text-amber-800 mt-1">
                  (Client budget: â‚¹{parseInt(clientBudget).toLocaleString('en-IN')}/day)
                </p>
              </div>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => {
                  setShowNegotiationModal(false)
                  setClientBudget('')
                }}
                className="px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-100 rounded-lg transition-all"
              >
                Cancel
              </button>
              <button
                onClick={sendNegotiationEmail}
                disabled={sendingNegotiation || !clientBudget}
                className="px-4 py-2 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 disabled:opacity-60 rounded-lg transition-all inline-flex items-center gap-2"
              >
                {sendingNegotiation ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'ðŸ“§'}
                Send Negotiation
              </button>
            </div>
          </div>
        </div>
      )}
      {clientEmailRequest && (
        <ClientEmailModal
          loading={sendingClientSlots}
          title="Send Slots to Client"
          description="Client email is missing for this requirement. Add it once, then the trainer slots will be sent."
          submitLabel="Save & Send"
          onClose={() => setClientEmailRequest(null)}
          onSubmit={({ clientEmail, clientName }) =>
            handleSendClientSlots({ ...clientEmailRequest, clientEmail, clientName })
          }
        />
      )}
      {showProfileEnhancement && profileEnhancement && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-slate-900">Requirement-Aligned Profile Review</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Original profile is preserved. Approve only additions supported by resume evidence.
                </p>
              </div>
              <button onClick={() => setShowProfileEnhancement(false)} className="text-sm font-semibold text-slate-500">Close</button>
            </div>
            <div className="mt-5 space-y-3">
              {(profileEnhancement.analysis?.suggestions || []).map(item => {
                const selectable = !item.requires_trainer_confirmation && !!item.suggested_bullet
                const checked = approvedProfileSuggestions.includes(item.id)
                return (
                  <label key={item.id} className={clsx(
                    'block rounded-xl border p-4',
                    selectable ? 'border-slate-200 bg-white' : 'border-amber-200 bg-amber-50'
                  )}>
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={!selectable}
                        onChange={e => setApprovedProfileSuggestions(current =>
                          e.target.checked ? [...current, item.id] : current.filter(id => id !== item.id)
                        )}
                        className="mt-1"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-bold text-slate-900">{item.skill}</span>
                          <span className={clsx(
                            'rounded-full px-2 py-0.5 text-xs font-bold',
                            item.evidence_status === 'confirmed' ? 'bg-emerald-100 text-emerald-700' :
                            item.evidence_status === 'related' ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700'
                          )}>{item.evidence_status}</span>
                        </div>
                        <p className="mt-2 text-xs text-slate-500"><strong>Original evidence:</strong> {item.resume_evidence}</p>
                        <p className="mt-1 text-xs text-slate-500"><strong>Source:</strong> {item.source_section || 'Original profile'} · <strong>Strength:</strong> {(item.match_strength || item.evidence_status).replaceAll('_', ' ')}</p>
                        {item.experience_depth && <p className="mt-1 text-xs text-slate-500"><strong>Depth:</strong> {item.experience_depth}</p>}
                        {selectable && (
                          <div className="mt-3 grid gap-1">
                            <span className="text-xs font-semibold text-slate-600">Client-specific suggested sentence</span>
                            <textarea
                              value={editedProfileBullets[item.id] ?? item.suggested_bullet ?? ''}
                              onChange={e => setEditedProfileBullets(current => ({ ...current, [item.id]: e.target.value }))}
                              rows={2}
                              className="w-full rounded-lg border border-slate-200 p-2 text-sm text-slate-800"
                            />
                          </div>
                        )}
                        {item.requires_trainer_confirmation && (
                          <div className="mt-3">
                            <p className="text-xs font-semibold text-amber-700">Trainer confirmation required before this can be added.</p>
                            <textarea
                              value={trainerConfirmations[item.id] || ''}
                              onChange={e => setTrainerConfirmations(current => ({ ...current, [item.id]: e.target.value }))}
                              placeholder={`Paste ${trainer.name || 'the trainer'}'s exact confirmation for ${item.skill}`}
                              rows={2}
                              className="mt-2 w-full rounded-lg border border-amber-300 bg-white p-2 text-sm"
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  </label>
                )
              })}
            </div>
            {(profileEnhancement.analysis?.suggestions || []).some(item => item.requires_trainer_confirmation) && (
              <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4">
                <p className="text-sm font-bold text-amber-900">Record trainer-provided evidence</p>
                <p className="mt-1 text-xs text-amber-700">Paste only what the trainer confirmed by email or call. This action is saved in the audit history.</p>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input
                    value={trainerConfirmationReference}
                    onChange={e => setTrainerConfirmationReference(e.target.value)}
                    placeholder="Trainer name or confirmation email reference"
                    className="min-w-0 flex-1 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm"
                  />
                  <button
                    onClick={recordTrainerProfileConfirmation}
                    disabled={profileEnhancementBusy || !Object.values(trainerConfirmations).some(value => value.trim())}
                    className="btn-secondary text-sm disabled:opacity-50"
                  >Record Confirmation</button>
                </div>
              </div>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <button onClick={() => setShowProfileEnhancement(false)} className="btn-secondary text-sm">Cancel</button>
              <button
                onClick={approveProfileEnhancement}
                disabled={profileEnhancementBusy || !approvedProfileSuggestions.length}
                className="btn-primary text-sm disabled:opacity-50"
              >
                {profileEnhancementBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                Approve Verified Additions
              </button>
            </div>
          </div>
        </div>
      )}

      <div className={clsx('bg-white rounded-2xl border p-4 transition-all hover:-translate-y-0.5 hover:shadow-lg',
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
          <div className={clsx('flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl text-sm font-black shadow-sm',
            rank === 1 ? 'bg-amber-100 text-amber-700' :
            rank === 2 ? 'bg-slate-200 text-slate-600' :
            rank === 3 ? 'bg-orange-100 text-orange-600' : 'bg-slate-100 text-slate-500'
          )}>{rank}</div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center flex-wrap gap-2">
              <div>
                <span className="text-base font-bold text-slate-950">{trainer.name}</span>
                {trainer.title && <div className="text-xs text-slate-500 mt-0.5">{trainer.title}</div>}
              </div>
              {trainer.match_score != null && (
                <span className={clsx('px-2 py-0.5 rounded-lg text-xs font-bold',
                  trainer.match_score >= 80 ? 'bg-emerald-100 text-emerald-700' :
                  trainer.match_score >= 60 ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700'
                )}>{trainer.match_score} pts</span>
              )}
              <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold', stageInfo.color)}>
                {stageInfo.label}
              </span>
              {autoMode && isActive && !['selected','rejected','toc_requested','toc_received_pending','training_confirmed','slot_booked','interview_scheduled','po_requested','client_po_received','invoice_generated','invoice_sent'].includes(stage) && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-violet-100 text-violet-700 animate-pulse">
                  ðŸ¤– Auto Active
                </span>
              )}
            </div>

            <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
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
                  <span key={i} className="rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700">{s}</span>
                ))}
                {trainer.skills.length > 5 && (
                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500">+{trainer.skills.length - 5}</span>
                )}
              </div>
            )}
            {(trainer.resume || trainer.combined_text || trainer.raw_text || trainer.summary || trainer.bio || trainer.trainer_details_received) && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  onClick={analyzeProfileAgainstRequirement}
                  disabled={profileEnhancementBusy}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-violet-200 bg-violet-50 px-3 py-2 text-xs font-bold text-violet-700 hover:bg-violet-100 disabled:opacity-50"
                >
                  {profileEnhancementBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bot className="h-3.5 w-3.5" />}
                  Align Profile to Client Requirement
                </button>
                {trainer.profile_enhancement_status === 'approved' && (
                  <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-bold text-emerald-700">Verified enhancement approved</span>
                )}
              </div>
            )}

            <StepBar stage={stage} />
            <PipelineProgressSummary stage={stage} state={state} req={req} />
            {renderActions()}
            {renderManualPipelineSelector()}
          </div>

          <button onClick={() => setShowThread(true)}
            className="flex h-9 flex-shrink-0 items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 text-xs font-bold text-slate-700 transition-all hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700">
            <Eye className="w-3.5 h-3.5" /> Thread
          </button>
        </div>
      </div>
    </>
  )
}

// â”€â”€â”€ Main Page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
export default function Shortlist1() {
  const rawReqParam = new URLSearchParams(globalThis.location.search).get('requirement_id') || ''
  // If the query param contains surrounding text (copied content), extract canonical REQ-XXXX token
  const reqMatch = (rawReqParam || '').match(/(REQ-[A-Z0-9]+)/i)
  const targetRequirementId = reqMatch ? reqMatch[1] : rawReqParam.trim()
  const [reqs, setReqs]               = useState([])
  const [selectedReq, setSelectedReq] = useState(null)
  const [trainers, setTrainers]       = useState([])
  const [states, setStates]           = useState({})
  const [loadingReqs, setLoadingReqs]         = useState(false)
  const [loadingTrainers, setLoadingTrainers] = useState(false)
  const [clientContactOpen, setClientContactOpen] = useState(false)
  const [savingClientContact, setSavingClientContact] = useState(false)
  const [deletingReqId, setDeletingReqId] = useState('')
  const [missingRequirement, setMissingRequirement] = useState(false)
  const [autoMode, setAutoMode] = useState(true)
  const [allowAutoReminders, setAllowAutoReminders] = useState(false)

  useEffect(() => {
    const loadRequirements = async () => {
      setLoadingReqs(true)
      try {
        const list = await getAllRequirementsForFlow()
        const confirmedReqs = list.filter(isConfirmedRequirement)
        setReqs(confirmedReqs)

        if (targetRequirementId) {
          const match = list.find(req => String(req.requirement_id) === String(targetRequirementId))
          if (match && isConfirmedRequirement(match)) {
            setSelectedReq(match)
            setMissingRequirement(false)
          } else if (match) {
            toast('This is a proposal requirement. Opening Proposal Flow.', { icon: 'i' })
            globalThis.location.replace(`/shortlist?requirement_id=${encodeURIComponent(match.requirement_id)}`)
          } else {
            try {
              const reqRes = await getRequirement(targetRequirementId)
              const requirement = reqRes.data
              if (!isConfirmedRequirement(requirement)) {
                toast('This is a proposal requirement. Opening Proposal Flow.', { icon: 'i' })
                globalThis.location.replace(`/shortlist?requirement_id=${encodeURIComponent(requirement.requirement_id || targetRequirementId)}`)
                return
              }
              setSelectedReq(requirement)
              setReqs(prev => prev.some(item => item.requirement_id === requirement.requirement_id) ? prev : [requirement, ...prev])
              setMissingRequirement(false)
            } catch (err) {
              if (err.response?.status === 404) {
                try {
                  const shortlistRes = await getShortlist(targetRequirementId)
                  const shortlist = shortlistRes.data || {}
                  const trainers = shortlist.top_trainers || shortlist.trainers || []
                  const requirement = {
                    requirement_id: targetRequirementId,
                    technology_needed: shortlist.technology_needed || '',
                    top_n: trainers.length || 0,
                    client_email: '',
                  }
                  setSelectedReq(requirement)
                  setReqs(prev => prev.some(item => item.requirement_id === requirement.requirement_id) ? prev : [requirement, ...prev])
                  setMissingRequirement(false)
                } catch {
                  setMissingRequirement(true)
                }
              } else {
                setMissingRequirement(true)
              }
            }
          }
        } else {
          setMissingRequirement(false)
        }
      } catch {
      } finally {
        setLoadingReqs(false)
      }
    }

    loadRequirements()
  }, [targetRequirementId])

  useEffect(() => {
    let cancelled = false
    api.get('/admin/settings')
      .then(res => {
        if (cancelled) return
        const settings = res.data?.settings || res.data || {}
        setAutoMode(settings.pipeline?.autoSend === undefined ? true : truthySetting(settings.pipeline?.autoSend))
        setAllowAutoReminders(remindersAllowedFromSettings(settings))
      })
      .catch(() => {
        if (!cancelled) {
          setAutoMode(true)
          setAllowAutoReminders(false)
        }
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!selectedReq) return
    setLoadingTrainers(true)
    setTrainers([])
    getShortlist(selectedReq.requirement_id)
      .then(r => {
        const list = r.data.top_trainers || r.data.trainers || []
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
    if (!globalThis.confirm(`Delete "${label}" from AI Pipeline? This removes its shortlist and pipeline state.`)) return

    setDeletingReqId(requirement.requirement_id)
    try {
      await deleteRequirement(requirement.requirement_id)
      localStorage.removeItem(`sl_v5_${requirement.requirement_id}`)
      setReqs(prev => prev.filter(item => item.requirement_id !== requirement.requirement_id))
      if (selectedReq?.requirement_id === requirement.requirement_id) {
        setSelectedReq(null)
        setTrainers([])
        setStates({})
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
        const list = r.data.top_trainers || r.data.trainers || []
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
  }

  const syncReplyStates = async () => {
    if (!selectedReq || !trainers.length) return
    await syncInboxReplies()

    try {
      const res = await api.get('/emails', {
        params: { requirement_id: selectedReq.requirement_id, page: 1, limit: 1000, _ts: Date.now() },
      })
      const logsByTrainer = {}
      for (const email of (res.data.emails || [])) {
        if (!email.trainer_id) continue
        const key = String(email.trainer_id)
        logsByTrainer[key] = logsByTrainer[key] || []
        logsByTrainer[key].push(email)
      }
      const threadResults = trainers.map(trainer => ({
        trainerId: trainer.trainer_id,
        inferred: backendAuthoritativeStage(trainer, selectedReq)
          ? { status: backendAuthoritativeStage(trainer, selectedReq) }
          : inferPipelineStateFromEmailLogs(logsByTrainer[String(trainer.trainer_id)] || []),
      }))

      setStates(prev => {
        const next = { ...prev }
        let changed = false

        for (const result of threadResults) {
          if (!result?.inferred?.status) continue
          const trainerId = result.trainerId
          const current = next[trainerId]?.status || 'pending'
          const { status, ...extra } = result.inferred

          if (current !== status || Object.keys(extra).some(k => next[trainerId]?.[k] !== extra[k])) {
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
    if (!selectedReq) return
    syncReplyStates()
    const interval = setInterval(syncReplyStates, SHORTLIST_REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [selectedReq?.requirement_id, trainers.length])

  const activeTrainerId = (() => {
    const active = trainers.find(t =>
      ACTIVE_PIPELINE_STAGES.has(resolveTrainerStage(t, selectedReq, states[t.trainer_id]))
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

  const pipelineStats = {
    total: trainers.length,
    waiting: trainers.filter(t => ['waiting_reply1', 'waiting_reply2', 'toc_requested'].includes(resolveTrainerStage(t, selectedReq, states[t.trainer_id]))).length,
    replied: trainers.filter(t => ['mail1_replied', 'details_received', 'slot_booked', 'interview_scheduled', 'selected', 'toc_received_pending', 'training_confirmed'].includes(resolveTrainerStage(t, selectedReq, states[t.trainer_id]))).length,
    completed: trainers.filter(t => ['training_confirmed', 'rejected'].includes(resolveTrainerStage(t, selectedReq, states[t.trainer_id]))).length,
  }

  const aiFlowSteps = [
    { step: '01', label: 'Trainer requirement', note: 'Share client details and ask only missing/requested trainer details', color: 'bg-blue-600' },
    { step: '02', label: 'Client handoff', note: 'Send requested trainer details with available interview dates/slots', color: 'bg-emerald-600' },
    { step: '03', label: 'Interview result', note: 'Confirm slot/link with both sides, then send trainer selected or rejection mail after client feedback', color: 'bg-amber-500' },
  ]

  useAutoPilot({
    trainers,
    req: selectedReq,
    states,
    onStatusUpdate: handleStatusUpdate,
    enabled: autoMode && !!selectedReq && !!selectedReq.client_email,
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
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-5 p-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
              <Bot className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Shortlist AI Pipeline</h1>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
                AI uses 3 core templates: trainer requirement, client handoff, and discussion/interview slots. After client feedback, the trainer gets the selected or rejection update.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              ['Trainers', pipelineStats.total],
              ['Waiting', pipelineStats.waiting],
              ['Replied', pipelineStats.replied],
              ['Done', pipelineStats.completed],
            ].map(([label, value]) => (
              <div key={label} className="min-w-[88px] rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <p className="text-xs font-semibold text-slate-400">{label}</p>
                <p className="text-lg font-bold text-slate-900">{value}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="border-t border-slate-100 bg-violet-50 px-5 py-3">
          <div className="flex flex-wrap items-center gap-2 text-sm text-violet-800">
            <Sparkles className="h-4 w-4" />
            <span className="font-semibold">AI mode is always active.</span>
            <span className="text-violet-700">No manual message writing, no template editing, no manual/auto switch.</span>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5" /> AI Mail Flow
        </p>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          {aiFlowSteps.map(s => (
            <div key={s.step} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center gap-2">
                <span className={clsx('flex h-7 w-7 items-center justify-center rounded-lg text-xs font-bold text-white', s.color)}>{s.step}</span>
                <span className="text-sm font-bold text-slate-800">{s.label}</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-500">{s.note}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Requirement selector */}
      {!selectedReq ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-sm font-semibold text-slate-700 mb-3">Select Requirement</p>
          {loadingReqs ? (
            <div className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin" /> Loading...</div>
          ) : missingRequirement ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <p className="font-semibold">Requirement not found</p>
              <p className="mt-2 text-sm text-slate-600">The requested requirement ID was not found. Please check the URL or select a different request.</p>
            </div>
          ) : reqs.length === 0 ? (
            <div className="flex items-center gap-2 p-3 bg-amber-50 rounded-xl text-sm text-amber-700">
              <AlertCircle className="w-4 h-4" /> No requirements yet. Go to Find Trainers first.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {reqs.map(r => (
                <div key={r.requirement_id}
                  className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 transition-all hover:border-blue-300 hover:bg-blue-50 group">
                  <button onClick={() => setSelectedReq(r)}
                    className="flex min-w-0 flex-1 items-center gap-3 rounded-lg p-1 text-left">
                  <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                    <Star className="w-4 h-4 text-blue-500" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-sm truncate text-slate-800">{r.technology_needed}</p>
                    <p className={clsx('mt-1 flex items-center gap-1 text-xs', r.client_email ? 'text-emerald-600' : 'text-amber-600')}>
                      <Mail className="h-3 w-3" />
                      {r.client_email ? 'Client email saved' : 'Client email missing'}
                    </p>
                    {r.client_name && <p className="text-xs text-slate-600">Client: {r.client_name}</p>}
                    {(() => {
                      const schedule = formatRequirementSchedule(r)
                      const tone = schedule === 'TBD' ? 'text-slate-400' : 'text-amber-600'
                      return <p className={clsx('text-xs', tone)}>Schedule: {schedule}</p>
                    })()}
                    <p className="text-xs text-slate-400">{r.requirement_id} - Top {r.top_n}</p>
                  </div>
                  <ChevronRight className="w-4 h-4 opacity-30 group-hover:opacity-70 flex-shrink-0" />
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
              ))}
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
              <div className={clsx('mt-1 inline-flex items-center gap-2 rounded-xl border px-2.5 py-1 text-xs font-semibold',
                selectedReq.client_email ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'
              )}>
                <Mail className="h-3.5 w-3.5" />
                <span>{selectedReq.client_email ? `Client: ${selectedReq.client_email}` : 'Client email missing'}</span>
                <button onClick={() => setClientContactOpen(true)} className="ml-1 underline underline-offset-2">
                  {selectedReq.client_email ? 'Edit' : 'Add'}
                </button>
              </div>
              <p className="text-xs text-slate-400">{selectedReq.requirement_id} - Top {selectedReq.top_n}</p>
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

          <div className="grid gap-2 rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-sm sm:grid-cols-3">
            <div className="rounded-lg bg-blue-50 px-3 py-2 text-blue-700">
              <p className="font-bold">Trainer pipeline</p>
              <p className="mt-0.5 text-blue-600">3 templates from requirement to interview</p>
            </div>
            <div className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-700">
              <p className="font-bold">Client handoff</p>
              <p className="mt-0.5 text-emerald-600">Requested trainer details and available dates</p>
            </div>
            <div className="rounded-lg bg-blue-50 px-3 py-2 text-blue-700">
              <p className="font-bold">Interview result</p>
              <p className="mt-0.5 text-blue-600">Slot link, selected or rejection update</p>
            </div>
          </div>

          {!selectedReq.client_email && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-amber-700">
                <AlertCircle className="h-4 w-4" />
                Add client email to start AI pipeline and auto-send trainer slots to the client.
              </div>
              <button onClick={() => setClientContactOpen(true)} className="btn-secondary bg-white">
                Add Client
              </button>
            </div>
          )}

          {loadingTrainers ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }, (_, i) => (
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
              <p className="text-sm text-slate-400 mt-1">No matching trainers were found for this requirement yet</p>
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

