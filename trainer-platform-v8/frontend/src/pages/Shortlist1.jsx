import { useState, useEffect, useRef } from 'react'
import api, { deleteRequirement, getRequirements, getShortlist, updateRequirement } from '../utils/api'
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

// ─── Gemini AI Helper ─────────────────────────────────────────────────────────
async function generateAIReply({ trainerName, domain, stage, trainerReply, previousMails, fallback }) {
  const templateGuide = `
Mail 1 First Contact:
Subject: Training Requirement - {Domain}
Body asks if trainer is interested/available and requests updated trainer profile with relevant experience.

Mail 1 Reminder:
Subject: [Reminder {Number}] Training Requirement - {Domain}
Body gently follows up because no reply was received.

Mail 2 Details Request:
Subject: Training Requirement - {Domain} | Additional Details Required
Body asks for total experience, trainings conducted, certifications, preferred mode, full-day/half-day availability, charges, location, and date availability.

Mail 2 Follow-Up:
Subject: Re: Training Requirement - {Domain} | Details Required
Body asks again for the above details if the reply was incomplete.

Mail 3 Slot Booking:
Subject: Interview Slot Booking - {Domain}
Body asks trainer to confirm one interview slot.

Mail 4 Interview Schedule:
Subject: Interview Schedule Confirmation - {Domain}
Body shares date/time, platform, and meeting link.

Mail 5A Selection:
Subject: Congratulations! You have been Selected - {Domain}
Body confirms selection and asks for ToC/course agenda and prerequisites.

Mail 5B Rejection:
Subject: Update on Training Requirement - {Domain}
Body politely says another trainer was selected and profile will be kept for future.

Mail 6 ToC Request:
Subject: Action Required: ToC / Course Agenda - {Domain}
Body asks for detailed ToC, day-wise breakdown, tools/prerequisites, and prep needs.

Mail 7 Training Confirmation:
Subject: Training Schedule Confirmed - {Domain}
Body confirms final date, venue/platform, action items, and contact details.
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
TrainerSync Team
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
  const subjectMatch = text.match(/SUBJECT:\s*(.+)/i)
  const bodyMatch = text.match(/BODY:\s*([\s\S]+)/i)
  return {
    subject: subjectMatch?.[1]?.trim() || fallback?.subject || '',
    body: bodyMatch?.[1]?.trim() || text.trim() || fallback?.body || '',
  }

}

// ─── localStorage helpers ─────────────────────────────────────────────────────
function getLS(k) { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }
function setLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} }
function money(v) {
  const n = Number(v || 0)
  return `INR ${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
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
  const emailOk = results.filter(item => item.result?.success).length
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

// ─── Pipeline stages ──────────────────────────────────────────────────────────
const STAGES = {
  pending:              { label: 'Pending',               color: 'bg-slate-100 text-slate-500',     step: 0 },
  mail1_sent:           { label: '1st Mail Sent 📧',      color: 'bg-blue-100 text-blue-700',       step: 1 },
  waiting_reply1:       { label: 'Waiting for Reply ⏳',  color: 'bg-sky-100 text-sky-700',         step: 1 },
  mail1_replied:        { label: 'Mail 1 Replied ✅',     color: 'bg-emerald-100 text-emerald-700', step: 1 },
  details_requested:    { label: 'Details Requested 📋',  color: 'bg-indigo-100 text-indigo-700',   step: 2 },
  details_received:     { label: 'Details Received ✅',   color: 'bg-emerald-100 text-emerald-700', step: 2 },
  waiting_reply2:       { label: 'Waiting for Reply ⏳',  color: 'bg-sky-100 text-sky-700',         step: 2 },
  slot_booked:          { label: 'Slot Booked 📅',        color: 'bg-amber-100 text-amber-700',     step: 3 },
  interview_scheduled:  { label: 'Interview Scheduled 🗓️',color: 'bg-purple-100 text-purple-700',  step: 4 },
  selected:             { label: 'Selected ✅',            color: 'bg-emerald-100 text-emerald-700', step: 5 },
  rejected:             { label: 'Not Selected ❌',        color: 'bg-red-100 text-red-600',         step: 5 },
  stopped_selected:     { label: 'Stopped - Role Filled', color: 'bg-slate-100 text-slate-500',     step: 0 },
  toc_requested:        { label: 'ToC Requested 📄',      color: 'bg-teal-100 text-teal-700',       step: 6 },
  toc_received_pending: { label: 'ToC Received 📄',       color: 'bg-teal-100 text-teal-700',       step: 6 },
  training_confirmed:   { label: 'Training Confirmed 🎓', color: 'bg-green-100 text-green-700',     step: 7 },
  po_requested:         { label: 'PO Requested',           color: 'bg-cyan-100 text-cyan-700',       step: 8 },
  client_po_received:   { label: 'Client PO Received',     color: 'bg-cyan-100 text-cyan-700',       step: 8 },
  invoice_generated:    { label: 'Invoice Generated',      color: 'bg-emerald-100 text-emerald-700', step: 9 },
  invoice_sent:         { label: 'Invoice Sent',           color: 'bg-green-100 text-green-700',     step: 10 },
}

// ─── Reminder intervals for Mail 1 (in ms) ───────────────────────────────────
const REMINDER_INTERVALS = [
  { hours: 6,  label: '6h follow-up'  },
  { hours: 12, label: '12h follow-up' },
  { hours: 24, label: '24h follow-up' },
]

const SHORTLIST_REFRESH_INTERVAL_MS = 10000
const AUTO_SEND_CLIENT_SLOTS = true
const THREAD_REFRESH_INTERVAL_MS = 5000
const REPLY_SYNC_THROTTLE_MS = 15000
const PIPELINE_MAIL_OPTIONS = [
  { value: 'mail1', label: 'Mail 1 - First Contact' },
  { value: 'mail2', label: 'Mail 2 - Details Request' },
  { value: 'mail2_followup', label: 'Mail 2 Follow-up' },
  { value: 'mail3', label: 'Mail 3 - Slot Booking' },
  { value: 'mail4', label: 'Mail 4 - Interview Schedule' },
  { value: 'mail5_ok', label: 'Mail 5 - Selection' },
  { value: 'mail5_no', label: 'Mail 5 - Rejection' },
  { value: 'mail6_toc', label: 'Mail 6 - ToC Request' },
  { value: 'mail7_confirm', label: 'Mail 7 - Training Confirmation' },
]
let inboxSyncPromise = null
let lastInboxSyncAt = 0
const sentGuard = new Set()

function syncInboxReplies(force = false) {
  const now = Date.now()
  if (!force && now - lastInboxSyncAt < REPLY_SYNC_THROTTLE_MS) return Promise.resolve(null)
  if (!inboxSyncPromise) {
    lastInboxSyncAt = now
    inboxSyncPromise = api.post('/emails/check-replies')
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

function backendStoppedStage(trainer) {
  return ['stopped_selected', 'role_filled', 'requirement_filled'].includes(trainer?.pipeline_status || trainer?.status)
    ? 'stopped_selected'
    : ''
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

// ─── Email template builders ──────────────────────────────────────────────────
function mail1Template(trainer, req, hasDetails, details, isReminder = false, reminderNum = 0) {
  const domain = details?.domain || req.technology_needed
  const hello = greeting(trainer)
  const reminderPrefix = isReminder
    ? `${hello}\n\nThis is a gentle follow-up (Reminder ${reminderNum}) to our earlier email regarding the ${domain} training requirement.\n\nWe haven't received your response yet. Kindly let us know your interest and availability at the earliest.\n\n---\n\n`
    : ''
  let body = `${reminderPrefix}${hello}\n\nWe have received a training requirement for ${domain} and are looking for a trainer with relevant experience.\n\nTraining Details:\n\nDomain/Technology: ${domain}`
  if (hasDetails) {
    if (details.duration)     body += `\nDuration: ${details.duration}`
    if (details.mode)         body += `\nMode: ${details.mode}`
    if (details.participants) body += `\nParticipants: ${details.participants}`
  }
  if (!details?.duration || !details?.participants) {
    body += `\n\nAt this stage, we are checking your interest and availability first. Once you confirm, we will share the confirmed duration, schedule, participants, and other requirement details as they are finalized.`
  }
  body += `\n\nPlease let us know if you are interested and available for this requirement. Kindly share your updated trainer profile along with relevant experience.\n\nRegards,\nTrainerSync Team`
  const subject = isReminder
    ? `[Reminder ${reminderNum}] Training Requirement – ${domain}`
    : `Training Requirement – ${domain}`
  return { subject, body }
}

function isMail1OffStageQuestion(text = '') {
  const clean = stripQuotedEmail(text).toLowerCase()
  if (!clean) return false
  const asksQuestion = clean.includes('?') || /\b(what|when|where|how|which|share|provide|confirm|details?)\b/.test(clean)
  const offStageTopic = /\b(duration|hours?|days?|timings?|schedule|participants?|client|company|rate|commercial|budget|google\s*meet|meet\s*link|meeting\s*link|zoom|teams|location|mode|agenda|toc)\b/.test(clean)
  return asksQuestion && offStageTopic
}

function mail1QuestionRedirectTemplate(trainer, req) {
  const domain = req?.technology_needed || 'the training requirement'
  return {
    subject: `Re: Training Requirement - ${domain}`,
    body: `${greeting(trainer)}\n\nThank you for your question.\n\nAt this stage, we are first checking your interest and availability for the ${domain} requirement. Confirmed duration, schedule, participant count, client details, and Google Meet / meeting link details will be shared in the next step once your profile is shortlisted and the client confirms the discussion.\n\nFor now, could you please confirm if you are interested and available for this requirement? If yes, kindly share your updated trainer profile and relevant experience.\n\nRegards,\nTrainerSync Team`,
  }
}

function mail2Template(trainer, req) {
  return {
    subject: `Training Requirement – ${req.technology_needed} | Additional Details Required`,
    body: `${greeting(trainer)}\n\nThank you for your response.\n\nTo proceed further, kindly share the below details:\n\n* Total years of experience\n* Number of trainings conducted previously\n* Relevant certifications\n* Preferred training mode (Online / Offline)\n* Availability for Full-Day or Half-Day sessions\n* Expected commercial charges per day/session\n* Current location\n* Availability for the mentioned dates\n\nRegards,\nTrainerSync Team`
  }
}

function mail2FollowupTemplate(trainer, req) {
  return {
    subject: `Re: Training Requirement – ${req.technology_needed} | Details Required`,
    body: `${greeting(trainer)}\n\nThank you for confirming your interest.\n\nTo proceed further, kindly share the above requested details:\n\n* Total years of experience\n* Number of trainings conducted previously\n* Relevant certifications\n* Preferred training mode (Online / Offline)\n* Availability for Full-Day or Half-Day sessions\n* Expected commercial charges per day/session\n* Current location\n* Availability for the mentioned dates\n\nOnce we receive these details, we can move ahead with the next step.\n\nRegards,\nTrainerSync Team`
  }
}

function trainerCommercialNegotiationTemplate(trainer, req, quote, target) {
  const domain = req?.technology_needed || 'the training requirement'
  const unitText = target.unit === 'hour' ? 'per hour' : 'per day'
  return {
    subject: `Re: Training Requirement - ${domain} | Commercial Discussion`,
    body: `${greeting(trainer)}\n\nThank you for sharing your details and commercials for the ${domain} requirement.\n\nWe have reviewed the overall scope, expected engagement, and internal commercial feasibility for this requirement. To move ahead smoothly, we request you to kindly consider revising your commercials to around INR ${target.amount.toLocaleString('en-IN')} ${unitText}.\n\nThis will help us align the engagement commercially and proceed with the next discussion steps. Please confirm if this revised commercial is workable from your side.\n\nRegards,\nTrainerSync Team`
  }
}

function mail3Template(trainer, req, trainerDates) {
  return {
    subject: `Interview Slot Booking - ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nThank you for sharing your details.\n\nWe would like to book an interview slot with you. Based on your availability, please confirm one of the following slots:\n\n${trainerDates || '• [Slot 1]\n• [Slot 2]\n• [Slot 3]'}\n\nKindly confirm your preferred slot at the earliest.\n\nRegards,\nTrainerSync Team`
  }
}

function mail3SlotClarificationTemplate(trainer) {
  return {
    subject: 'Interview Slot Details Required',
    body: `Hi ${trainer?.name || 'Trainer'},\n\nThank you for sharing the slot. Could you please provide the exact interview date and time, including whether it is AM or PM?\n\nAlso, please share 3 available slots with the corresponding dates so that we can schedule the interview accordingly.\n\nThanks.`
  }
}

function mail4Template(trainer, req, interviewLink, platform, dateTime) {
  return {
    subject: `Interview Schedule Confirmation – ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nYour interview has been scheduled. Please find the details below:\n\nDate & Time: ${dateTime || '[Date & Time]'}\nPlatform: ${platform || 'Zoom'}\nMeeting Link: ${interviewLink || '[Meeting Link]'}\n\nPlease join on time. Let us know if you need any assistance.\n\nRegards,\nTrainerSync Team`
  }
}

function mail5SelectedTemplate(trainer, req) {
  return {
    subject: `Congratulations! You have been Selected – ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nCongratulations! We are pleased to inform you that you have been selected for the ${req.technology_needed} training requirement.\n\nTo proceed further, kindly share the following:\n\n* Table of Contents (ToC) / Course Agenda for the training\n* Any prerequisite materials or tools required\n\nWe look forward to working with you!\n\nRegards,\nTrainerSync Team`
  }
}

function mail5RejectedTemplate(trainer, req) {
  return {
    subject: `Update on Training Requirement – ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nThank you for your time and interest in the ${req.technology_needed} training requirement.\n\nAfter careful consideration, we regret to inform you that we have decided to proceed with another trainer at this time.\n\nWe will keep your profile on record and reach out for future opportunities.\n\nThank you once again for your cooperation.\n\nRegards,\nTrainerSync Team`
  }
}

// AUTO: ToC request sent immediately after selection
function mailTocAutoTemplate(trainer, req) {
  return {
    subject: `Action Required: ToC / Course Agenda – ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nCongratulations again on being selected for the ${req.technology_needed} training!\n\nTo initiate the onboarding process, kindly share the following at the earliest:\n\n* Detailed Table of Contents (ToC) / Course Agenda\n* Day-wise session breakdown\n* Tools, software, or prerequisites required by participants\n* Estimated preparation time needed\n\nPlease revert at the earliest so we can coordinate with the client on schedule.\n\nRegards,\nTrainerSync Team`
  }
}

// MANUAL: Training confirmation with contact details — sent after ToC is received
function mailTrainingConfirmedTemplate(trainer, req, contactName, contactPhone, contactEmail, trainingDate, venue) {
  return {
    subject: `Training Schedule Confirmed – ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nWe are pleased to confirm your engagement for the ${req.technology_needed} training. Please find the final details below:\n\nTraining Date: ${trainingDate || '[Training Date]'}\nVenue / Platform: ${venue || '[Venue / Platform]'}\n\nAction Items Before Training:\n* Ensure all materials and slides are ready\n* Share soft copies of training content with us 2 days prior\n* Confirm your availability 24 hours before the training\n\nFor any questions or additional information, please contact:\n\n👤 ${contactName || '[Contact Name]'}\n📞 ${contactPhone || '[Phone Number]'}\n📧 ${contactEmail || '[Email]'}\n\nWe look forward to a successful training session!\n\nRegards,\nTrainerSync Team`
  }
}

// ─── Reply intent detector ────────────────────────────────────────────────────
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

function hasRequestedTrainerDetails(text = '') {
  const t = stripQuotedEmail(text).toLowerCase()
  if (!t) return false

  const fieldSignals = [
    'total years of experience',
    'number of trainings conducted',
    'relevant certifications',
    'preferred training mode',
    'availability for full-day',
    'availability for half-day',
    'expected commercial charges',
    'current location',
    'availability for the mentioned dates',
  ]
  const fieldHits = fieldSignals.filter(s => t.includes(s)).length
  if (fieldHits >= 4) return true

  const checks = [
    /\b\d{1,2}\+?\s*(years|yrs|year|yr)\b/.test(t) || /\bexperience\s*[:-]/.test(t) || t.includes('years of experience'),
    hasTrainingCount(t) || t.includes('trainings conducted'),
    /certification|certified|certificate|certifications|not certified|no certification|none/i.test(t),
    /\b(online|offline|hybrid|classroom|remote)\b/.test(t),
    /\b(full[-\s]?day|half[-\s]?day|full day|half day)\b/.test(t),
    /\b(inr|rs\.?|₹|rate|charges?|commercial|fee|fees|per day|per session|cost)\b/i.test(t),
    /\b(location|based in|current city|city)\b/i.test(t) || /\b(bengaluru|bangalore|chennai|hyderabad|pune|mumbai|delhi|gurgaon|noida|kolkata|india)\b/i.test(t),
    /\b(available|availability|dates?|from|to|weekdays|weekends|morning|afternoon|evening)\b/i.test(t),
  ]

  return checks.filter(Boolean).length >= 3
}

function parseMoneyAmount(value) {
  if (value === null || value === undefined || value === '') return 0
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  const match = String(value).replace(/,/g, '').match(/\d+(?:\.\d+)?/)
  return match ? Number(match[0]) : 0
}

function extractCommercialQuote(text = '') {
  const clean = stripQuotedEmail(text)
  const compact = clean.replace(/,/g, '')
  const patterns = [
    /(?:inr|rs\.?|₹)\s*(\d+(?:\.\d+)?)\s*(?:\/|\s*per\s*)\s*(hour|hr|day|session)/i,
    /(\d+(?:\.\d+)?)\s*(?:inr|rs\.?|₹)\s*(?:\/|\s*per\s*)\s*(hour|hr|day|session)/i,
    /(?:charges?|commercials?|rate|fees?|cost)\D{0,25}(\d+(?:\.\d+)?)\D{0,15}(hour|hr|day|session)/i,
    /(\d+(?:\.\d+)?)\D{0,15}(?:per|\/)\s*(hour|hr|day|session)/i,
  ]
  for (const rx of patterns) {
    const match = compact.match(rx)
    if (!match) continue
    const amount = Number(match[1])
    const unitRaw = String(match[2] || '').toLowerCase()
    const unit = unitRaw.includes('hour') || unitRaw === 'hr' ? 'hour' : 'day'
    if (Number.isFinite(amount) && amount > 0) return { amount, unit }
  }
  return null
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

function negotiationTarget(clientBudget) {
  if (!clientBudget?.amount) return null
  const raw = clientBudget.amount * 0.8
  const roundTo = clientBudget.unit === 'hour' ? 100 : 500
  return {
    unit: clientBudget.unit,
    amount: Math.max(roundTo, Math.floor(raw / roundTo) * roundTo),
  }
}

function clientBudgetIncreaseTarget(clientBudget) {
  if (!clientBudget?.amount) return null
  const increment = clientBudget.unit === 'hour' ? 500 : 5000
  return {
    unit: clientBudget.unit,
    increment,
    amount: clientBudget.amount + increment,
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
    const increment = clientBudget.unit === 'hour' ? 500 : 5000
    const trainerTarget = Math.max(0, clientBudget.amount - increment)
    const extraPatterns = [
      /(?:extra|more|additional|increase)\D{0,30}(?:inr|rs\.?|₹)?\s*(\d+(?:\.\d+)?)\s*(k)?\b/i,
      /(?:inr|rs\.?|₹)?\s*(\d+(?:\.\d+)?)\s*(k)?\b\D{0,20}(?:extra|more|additional)/i,
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
  if (!quote || !clientBudget || quote.unit !== clientBudget.unit) return false
  const increment = clientBudget.unit === 'hour' ? 500 : 5000
  return quote.amount + increment <= clientBudget.amount
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
    /\b\d{1,2}(?::\d{2})?\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(am|pm)\b/g,
  ].reduce((sum, rx) => sum + ((clean.match(rx) || []).length), 0)
  const slotHints = (clean.match(/\b(slot|option|available|availability)\b/g) || []).length
  const hasOneExactSlot = dateHits >= 1 && timeHits >= 1
  const hasThreeSlotOptions = dateHits >= 3 && timeHits >= 3 || dateHits >= 3 && timeHits >= 2 && slotHints >= 1
  return hasOneExactSlot || hasThreeSlotOptions
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
  const lastSentTime = Math.max(...sent.map(m => new Date(m.sent_at || 0).getTime()))
  return [...messages]
    .sort((a, b) => new Date(a.sent_at || 0).getTime() - new Date(b.sent_at || 0).getTime())
    .findLast(m => m.direction === 'received' && new Date(m.sent_at || 0).getTime() > lastSentTime) || null
}

async function sendSlotsToClient({ trainer, req, slotText = '', force = false, clientEmail = '', clientName = '' }) {
  const res = await api.post('/shortlists/send-client-slots', {
    trainer_id: trainer.trainer_id,
    trainer_name: trainer.name,
    requirement_id: req.requirement_id,
    slot_text: stripQuotedEmail(slotText),
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

  const sorted = [...messages].sort((a, b) => new Date(a.sent_at || 0).getTime() - new Date(b.sent_at || 0).getTime())
  const sentTypes = new Set(sorted.filter(m => m.direction === 'sent').map(m => m.mail_type))
  const ts = msg => new Date(msg?.sent_at || Date.now()).getTime()

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
    if (detailsReply && detectIntent(detailsReply.body) === 'negative') {
      return { status: 'rejected' }
    }
    if (detailsReply && hasRequestedTrainerDetails(detailsReply.body)) {
      return { status: 'details_received', detailsAcceptedAt: ts(detailsReply) }
    }
    return { status: 'waiting_reply2' }
  }

  if (sentTypes.has('mail1') || sentTypes.has('mail1_reminder')) {
    const mail1Reply = latestReplyAfter(sorted, ['mail1', 'mail1_reminder'])
    if (mail1Reply && detectIntent(mail1Reply.body) === 'negative') {
      return { status: 'rejected' }
    }
    if (mail1Reply) {
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

// ─── Send Mail Modal ──────────────────────────────────────────────────────────
function MailModal({ trainer, req, mailType, onClose, onSent, threadMessages }) {
  const [loading, setLoading]           = useState(false)
  const [trainerDates, setTrainerDates] = useState('')
  const [interviewLink, setInterviewLink] = useState('')
  const [platform, setPlatform]         = useState('Zoom')
  const [dateTime, setDateTime]         = useState('')
  const [trainingDate, setTrainingDate] = useState('')
  const [venue, setVenue]               = useState('')
  const [contactName, setContactName]   = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [clientEmail, setClientEmail]   = useState(req?.client_email || '')
  const [clientName, setClientName]     = useState(req?.client_name || req?.client_company || '')
  // ── AI state ──
  const [aiGenerating, setAiGenerating] = useState(false)
  const [aiSubject, setAiSubject]       = useState('')
  const [aiBody, setAiBody]             = useState('')
  const [aiUsed, setAiUsed]             = useState(false)

  const getTemplatePreview = () => {
    switch (mailType) {
      case 'mail1':          return mail1Template(trainer, req, false, {})
      case 'mail2':          return mail2Template(trainer, req)
      case 'mail2_followup': return mail2FollowupTemplate(trainer, req)
      case 'mail3':          return mail3Template(trainer, req, trainerDates)
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
      toast.success('✨ AI email generated!')
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
    mail1:         '📧 Send Shortlist Mail',
    mail2:         '📋 Request Trainer Details',
    mail2_followup:'📋 Ask Details Again',
    mail3:         '📅 Book Interview Slot',
    mail4:         '🗓️ Send Interview Schedule',
    mail5_ok:      '🎉 Send Selection Mail',
    mail5_no:      '❌ Send Rejection Mail',
    mail7_confirm: '🎓 Send Training Confirmation',
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
              <p className="text-sm text-slate-500 mt-0.5">AI-generated mail for <strong>{trainer.name}</strong> · {trainer.email}</p>
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
                <p className="text-sm font-bold text-violet-900">TrainerSync AI writes this mail from your 7-stage pipeline rules.</p>
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
                placeholder="• Monday 10 AM – 12 PM&#10;• Wednesday 2 PM – 4 PM&#10;• Friday anytime"
                value={trainerDates} onChange={e => setTrainerDates(e.target.value)} />
            </div>
          )}

          {mailType === 'mail4' && (
            <div className="bg-slate-50 rounded-xl p-4 space-y-3 border border-slate-200">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Interview details for AI mail</p>
              <div className="grid grid-cols-3 gap-2">
                {['Zoom', 'MS Teams', 'Google Meet'].map(p => (
                  <button key={p} type="button" onClick={() => setPlatform(p)}
                    className={clsx('p-2 rounded-xl border-2 text-xs font-semibold transition-all',
                      platform === p ? 'bg-blue-500 text-white border-blue-500' : 'bg-white border-slate-200 text-slate-600 hover:border-blue-300')}>
                    {p === 'Zoom' ? '📹' : p === 'MS Teams' ? '💼' : '🎥'} {p}
                  </button>
                ))}
              </div>
              <div><label className="label">Date & Time</label><input type="datetime-local" className="input" value={dateTime} onChange={e => setDateTime(e.target.value)} /></div>
              <div><label className="label">Meeting Link</label><input className="input" placeholder="https://zoom.us/j/..." value={interviewLink} onChange={e => setInterviewLink(e.target.value)} /></div>
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

          {/* ── AI Generate Button ── */}
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
                  <Info className="w-3 h-3" /> Generated automatically from your 7-stage mail rules
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

// ─── Thread Modal ─────────────────────────────────────────────────────────────
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
            <p className="text-sm text-slate-500 mt-0.5">{trainer.name} · {req.technology_needed}</p>
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
  const [sending, setSending] = useState(false)
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

  const handleSend = async () => {
    setSending(true)
    try {
      const current = await ensurePo()
      if (!current?.po_id) return
      const res = await api.post(`/purchase-orders/${current.po_id}/send`, {})
      setPo(res.data.purchase_order)
      toast.success(`PO sent to ${trainer.name}`)
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'PO send failed')
    } finally {
      setSending(false)
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
            <p className="text-sm text-slate-500 mt-0.5">{trainer.name} · {req.technology_needed}</p>
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
                <p className="font-bold text-slate-900">{po ? `${po.po_number} · ${po.status}` : 'Not generated'}</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4">
            <p className="text-xs text-cyan-700 font-semibold uppercase">Client Invoice</p>
            <p className="mt-1 text-sm font-bold text-cyan-900">
              {invoice ? `${invoice.invoice_number} · ${invoice.status}` : req.client_email ? `Ready for ${req.client_email}` : 'Client email missing'}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 p-5 border-t border-slate-100 bg-white">
          <button onClick={createPo} disabled={generating}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm disabled:opacity-50">
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
            Generate PDF
          </button>
          <button onClick={handleDownload} disabled={generating || downloading || sending}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm disabled:opacity-50">
            {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Download
          </button>
          <button onClick={handleSend} disabled={generating || downloading || sending}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm disabled:opacity-50">
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Send Email + WhatsApp
          </button>
          <button onClick={handleGenerateInvoice} disabled={!!invoiceBusy || generating || sending}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-700 text-white font-semibold text-sm disabled:opacity-50">
            {invoiceBusy === 'generate' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
            {form.client_po_number.trim() ? 'Generate Invoice From Client PO' : 'Generate Invoice'}
          </button>
          <button onClick={handleDownloadInvoice} disabled={!!invoiceBusy || generating || sending}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-700 hover:bg-slate-800 text-white font-semibold text-sm disabled:opacity-50">
            {invoiceBusy === 'download' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Download Invoice
          </button>
          <button onClick={handleSendInvoice} disabled={!!invoiceBusy || generating || sending || !req.client_email}
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
            <h3 className="font-bold text-lg text-slate-900">💬 Conversation Thread</h3>
            <p className="text-sm text-slate-500">{trainer.name} · {req.technology_needed}</p>
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
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading…
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
                    {isReminder ? '🔔 Reminder sent' : isSent ? '📤 You sent' : '📥 Trainer replied'}
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

// ─── Pipeline Step Bar ────────────────────────────────────────────────────────
function StepBar({ stage }) {
  const steps = ['Mail 1', 'Details', 'Slot', 'Interview', 'Selected', 'ToC', 'Confirmed']
  const stepIndex = STAGES[stage]?.step ?? 0
  const isRejected = stage === 'rejected'
  const isDone     = ['training_confirmed', 'po_requested', 'client_po_received', 'invoice_generated', 'invoice_sent'].includes(stage)

  return (
    <div className="flex items-center gap-0 mt-2 flex-wrap">
      {steps.map((s, i) => {
        const realStep   = i + 1
        const isActive   = realStep === stepIndex
        const isComplete = realStep < stepIndex
        const isRejStep  = realStep === 5 && isRejected
        const isFinalDone= realStep === 7 && isDone
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
              {isComplete || isFinalDone ? '✓' : isRejStep ? '✕' : realStep}
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

// ─── AUTO PILOT ENGINE ────────────────────────────────────────────────────────
//
// Full auto flow:
//   pending trainers → Mail 1 is sent to everyone
//   waiting_reply1 → reminders at 6h/12h/24h until a Mail 1 reply arrives
//   positive Mail 1 replies are queued in reply order
//   one queued trainer at a time → Mail 2 → Mail 3 → manual interview/select rules
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
  const mailDone = ['mail1', 'mail2', 'mail3', 'mail4', 'mail5', 'mail6', 'mail7'].filter(key => doneStages[key]).length
  const progressPct = Math.round((mailDone / 7) * 100)
  const progressLabel = stage === 'stopped_selected'
    ? 'Stopped - role filled'
    : mailDone === 7
      ? 'Trainer flow complete'
      : `Mail ${Math.min(mailDone + 1, 7)} is next`
  const commercialStatus = doneStages.invoiceSent
    ? 'Invoice sent'
    : doneStages.invoice
      ? 'Invoice generated'
      : doneStages.po
        ? stage === 'po_requested' ? 'PO requested' : 'PO received'
        : 'Not started'
  const items = [
    { label: 'Trainer mails', value: `${mailDone}/7 complete`, tone: mailDone === 7 ? 'good' : 'neutral' },
    { label: 'Client slots', value: clientSlotsSent ? 'Sent to client' : clientEmailSaved ? 'Client saved' : 'Email missing', tone: clientSlotsSent ? 'good' : clientEmailSaved ? 'neutral' : 'warn' },
    { label: 'Commercial', value: commercialStatus, tone: doneStages.invoiceSent ? 'good' : doneStages.invoice ? 'warn' : 'neutral' },
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
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
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

function useAutoPilot({ trainers, req, states, onStatusUpdate, enabled }) {
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
        const getStage = trainer => backendAuthoritativeStage(trainer, req) || nextStates[trainer.trainer_id]?.status || 'pending'
        const setStage = (trainer, status, extra = {}) => {
          nextStates[trainer.trainer_id] = { ...(nextStates[trainer.trainer_id] || {}), status, ...extra }
          onStatusUpdate(trainer.trainer_id, status, extra)
        }
        const getThread = async trainer => {
          const res = await api.get(
            `/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}`
          )
          return (res.data.messages || []).filter(m =>
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
            toast(`🤖 Auto: ToC request sent to ${trainer.name} 📄`, { icon: '🤖', duration: 4000 })
            onStatusUpdate(trainer.trainer_id, 'toc_requested')
            runningRef.current = false
            return
          }

          if (st === 'toc_requested') {
            await syncInboxReplies()
            const messages = await getThread(trainer)
            const sentMails = messages.filter(m => m.direction === 'sent')
            if (!sentMails.length) continue
            const lastSentTime = Math.max(...sentMails.map(m => new Date(m.sent_at || 0).getTime()))
            const newReplies = messages.filter(m =>
              m.direction === 'received' &&
              new Date(m.sent_at || 0).getTime() > lastSentTime
            )
            if (!newReplies.length) continue
            const latest = newReplies[newReplies.length - 1]
            const intent = detectIntent(latest.body)
            if (intent === 'toc_received' || intent === 'positive') {
              toast(
                `Auto: ${trainer.name} sent the ToC/Agenda. Training Confirmation is ready for AI generation.`,
                { icon: '📄', duration: 6000 }
              )
              onStatusUpdate(trainer.trainer_id, 'toc_received_pending')
              runningRef.current = false
              return
            }
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
            sentResults.push({ trainer, result: res.data })
            setStage(trainer, 'waiting_reply1', { mail1SentAt: Date.now(), reminders: 0 })
          }
          showBulkSendStatusToast({ title: 'Mail 1 batch sent', results: sentResults })
          toast(`🤖 Auto: Mail 1 sent to all ${pendingTrainers.length} shortlisted trainers`, { icon: '📧', duration: 5000 })
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

          const firstSentTime = Math.min(...mail1Messages.map(m => new Date(m.sent_at || 0).getTime()))
          const lastSentTime = Math.max(...mail1Messages.map(m => new Date(m.sent_at || 0).getTime()))
          const repliesAfterMail1 = messages
            .filter(m => m.direction === 'received' && new Date(m.sent_at || 0).getTime() > firstSentTime)
            .sort((a, b) => new Date(a.sent_at || 0).getTime() - new Date(b.sent_at || 0).getTime())

          if (repliesAfterMail1.length) {
            const latest = repliesAfterMail1[repliesAfterMail1.length - 1]
            const firstReply = repliesAfterMail1[0]
            const intent = detectIntent(latest.body)
            const rank = trainers.indexOf(trainer) + 1
            const replyAt = new Date(firstReply.sent_at || Date.now()).getTime()

            if (intent === 'negative') {
              toast(`🤖 Auto: ${trainer.name} (Rank ${rank}) declined ❌`, { icon: '⏭️', duration: 5000 })
              setStage(trainer, 'rejected')
            } else if (intent === 'positive' || intent === 'toc_received') {
              toast(`🤖 Auto: ${trainer.name} replied to Mail 1 ✅ — queued for details`, { icon: '📬', duration: 4000 })
              setStage(trainer, 'mail1_replied', { mail1ReplyAt: replyAt })
            } else if (isMail1OffStageQuestion(latest.body)) {
              const latestReplyAt = new Date(latest.sent_at || Date.now()).getTime()
              const handledAt = nextStates[trainer.trainer_id]?.mail1QuestionRedirectAt || 0
              const guardKey = `${req.requirement_id}:${trainer.trainer_id}:mail1_question_redirect:${latestReplyAt}:${stripQuotedEmail(latest.body).slice(0, 80)}`
              if (latestReplyAt > handledAt && shouldSendOnce(guardKey)) {
                const { subject, body } = mail1QuestionRedirectTemplate(trainer, req)
                const res = await api.post('/shortlists/send-mail', {
                  trainer_id:     trainer.trainer_id,
                  trainer_name:   trainer.name,
                  to_email:       trainer.email,
                  requirement_id: req.requirement_id,
                  subject,
                  body,
                  mail_type: 'mail1_question_redirect',
                })
                showSendStatusToast({ trainerName: trainer.name, result: res.data, title: 'Interest clarification sent' })
                toast(`Auto: ${trainer.name} asked for later-stage details. Interest clarification sent.`, { icon: 'i', duration: 5000 })
              }
              setStage(trainer, 'waiting_reply1', { mail1QuestionRedirectAt: latestReplyAt })
            }
            continue
          }

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
              toast(`🤖 Auto: ${label} sent to ${trainer.name} (Rank ${rank}) 🔔`, { icon: '⏰', duration: 4000 })
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

            const { subject, body } = mail2Template(trainer, req)
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
            toast(`Auto: Mail 2 sent to ${sentResults.length} shortlisted trainer${sentResults.length === 1 ? '' : 's'} who replied to Mail 1`, { icon: '📋', duration: 5000 })
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
          const mail3AlreadySent = messages.some(m => m.direction === 'sent' && m.mail_type === 'mail3')
          if (!mail3AlreadySent) {
            const { subject, body } = mail3Template(activeTrainer, req, '')
            const res = await api.post('/shortlists/send-mail', {
              trainer_id:     activeTrainer.trainer_id,
              trainer_name:   activeTrainer.name,
              to_email:       activeTrainer.email,
              requirement_id: req.requirement_id,
              subject, body,
              mail_type: 'mail3',
              client_email: req.client_email,
              client_name: req.client_name || req.client_company,
            })
            showSendStatusToast({ trainerName: activeTrainer.name, result: res.data, title: 'Slot booking sent' })
            toast(`Auto: Slot Booking mail sent to ${activeTrainer.name}. Next trainer will wait until this pipeline finishes.`, { icon: '📅', duration: 5000 })
          }
          setStage(activeTrainer, 'slot_booked')
          runningRef.current = false
          return
        }

        if (activeStage === 'slot_booked') {
          const messages = await getThread(activeTrainer)
          const latestDetailsReply = latestReplyAfter(messages, ['mail2', 'mail2_followup'])
          if (latestDetailsReply && hasRequestedTrainerDetails(latestDetailsReply.body) && !nextStates[activeTrainer.trainer_id]?.detailsAcceptedAt) {
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
              toast(`Auto: commercial negotiation sent to ${activeTrainer.name}`, { icon: '₹', duration: 5000 })
              setStage(activeTrainer, 'waiting_reply2', { commercialNegotiationAt: Date.now() })
              runningRef.current = false
              return
            }
            setStage(activeTrainer, 'details_received', {
              detailsAcceptedAt: new Date(latestDetailsReply.sent_at || Date.now()).getTime(),
            })
            toast(`🤖 Auto: ${activeTrainer.name} shared the requested details — ready for Slot Booking`, { icon: '✅', duration: 5000 })
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
            const lastMail2Time = Math.max(...mail2Messages.map(m => new Date(m.sent_at || 0).getTime()))
            const firstMail3Time = Math.min(...mail3Messages.map(m => new Date(m.sent_at || 0).getTime()))
            const mail2Replies = messages
              .filter(m =>
                m.direction === 'received' &&
                new Date(m.sent_at || 0).getTime() > lastMail2Time &&
                new Date(m.sent_at || 0).getTime() < firstMail3Time
              )
              .sort((a, b) => new Date(a.sent_at || 0).getTime() - new Date(b.sent_at || 0).getTime())

            if (mail2Replies.length && !mail2Replies.some(m => hasRequestedTrainerDetails(m.body))) {
              const latestMail2Reply = mail2Replies[mail2Replies.length - 1]
              const replyTime = new Date(latestMail2Reply.sent_at || Date.now()).getTime()
              const handledAt = nextStates[activeTrainer.trainer_id]?.detailsFollowupAt || 0
              const guardKey = `${req.requirement_id}:${activeTrainer.trainer_id}:mail2_followup:${replyTime}:${stripQuotedEmail(latestMail2Reply.body).slice(0, 80)}`
              if (replyTime > handledAt && shouldSendOnce(guardKey)) {
                const { subject, body } = mail2FollowupTemplate(activeTrainer, req)
                const res = await api.post('/shortlists/send-mail', {
                  trainer_id:     activeTrainer.trainer_id,
                  trainer_name:   activeTrainer.name,
                  to_email:       activeTrainer.email,
                  requirement_id: req.requirement_id,
                  subject, body,
                  mail_type: 'mail2_followup',
                })
                showSendStatusToast({ trainerName: activeTrainer.name, result: res.data, title: 'Details follow-up sent' })
                toast(`🤖 Auto: ${activeTrainer.name} reached Slot Booking without details — moved back and asked for details again`, { icon: '📋', duration: 7000 })
              }
              setStage(activeTrainer, 'waiting_reply2', { detailsFollowupAt: replyTime })
              runningRef.current = false
              return
            }
          }

          const lastMail3Time = Math.max(...mail3Messages.map(m => new Date(m.sent_at || 0).getTime()))
          const handledAt = nextStates[activeTrainer.trainer_id]?.slotReplyAt || 0
          const newReplies = messages
            .filter(m =>
              m.direction === 'received' &&
              new Date(m.sent_at || 0).getTime() > lastMail3Time &&
              new Date(m.sent_at || 0).getTime() > handledAt
            )
            .sort((a, b) => new Date(a.sent_at || 0).getTime() - new Date(b.sent_at || 0).getTime())

          if (!newReplies.length) {
            runningRef.current = false
            return
          }

          const latest = newReplies[newReplies.length - 1]
          const replyTime = new Date(latest.sent_at || Date.now()).getTime()
          const intent = detectIntent(latest.body)
          const rank = trainers.indexOf(activeTrainer) + 1

          if (intent === 'negative') {
            toast(`🤖 Auto: ${activeTrainer.name} (Rank ${rank}) is unavailable/declined after slot mail — moving to next Mail 1 responder`, { icon: '⏭️', duration: 6000 })
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
              toast(`Auto: ${activeTrainer.name} did not share a clear dated AM/PM slot, so clarification mail was sent.`, { icon: '📅', duration: 6000 })
            }
            setStage(activeTrainer, 'slot_booked', { slotClarificationAt: replyTime })
            runningRef.current = false
            return
          }

          const slotText = stripQuotedEmail(latest.body)
          const extra = { slotReplyAt: replyTime, slotConfirmed: true, clientSlotText: slotText }
          if (AUTO_SEND_CLIENT_SLOTS && !nextStates[activeTrainer.trainer_id]?.clientSlotsSentAt) {
            try {
              const sent = await sendSlotsToClient({ trainer: activeTrainer, req, slotText, force: false })
              if (sent?.success) {
                extra.clientSlotsSentAt = Date.now()
                extra.clientSlotsEmailId = sent.email_id
                toast('Auto: trainer slots sent to client for confirmation', { icon: '📨', duration: 5000 })
              } else {
                toast.error(sent?.error || 'Could not send trainer slots to client')
              }
            } catch (e) {
              toast.error(e.response?.data?.detail || e.message || 'Could not send trainer slots to client')
            }
          }
          toast(`Auto: ${activeTrainer.name} shared proper slots. Client confirmation step is updated.`, { icon: '📅', duration: 5000 })
          setStage(activeTrainer, 'slot_booked', extra)

          if (intent === '__legacy_positive__') {
            toast(`Auto: ${activeTrainer.name} confirmed slot availability. Interview link mail is ready for AI generation.`, { icon: '📅', duration: 5000 })
            const slotText = stripQuotedEmail(latest.body)
            const extra = { slotReplyAt: replyTime, slotConfirmed: true, clientSlotText: slotText }
            if (AUTO_SEND_CLIENT_SLOTS && !nextStates[activeTrainer.trainer_id]?.clientSlotsSentAt) {
              try {
                const sent = await sendSlotsToClient({ trainer: activeTrainer, req, slotText, force: false })
                if (sent?.success) {
                  extra.clientSlotsSentAt = Date.now()
                  extra.clientSlotsEmailId = sent.email_id
                  toast('Auto: trainer slots sent to client for confirmation', { icon: '📨', duration: 5000 })
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
          const lastSentTime = Math.max(...sentMails.map(m => new Date(m.sent_at || 0).getTime()))
          const newReplies = messages.filter(m =>
            m.direction === 'received' &&
            new Date(m.sent_at || 0).getTime() > lastSentTime
          )
          if (!newReplies.length) { runningRef.current = false; return }

          const latest = newReplies[newReplies.length - 1]
          const intent = detectIntent(latest.body)
          const replyTime = new Date(latest.sent_at || Date.now()).getTime()
          const handledAt = nextStates[activeTrainer.trainer_id]?.detailsFollowupAt || 0
          const rank   = trainers.indexOf(activeTrainer) + 1
          const lastSentMail = sentMails
            .slice()
            .sort((a, b) => new Date(b.sent_at || 0).getTime() - new Date(a.sent_at || 0).getTime())[0]
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
            const quoteMarkup = clientBudget?.unit === 'hour' ? 500 : 5000
            const stillAboveClientBudget = revisedQuote && clientBudget && revisedQuote.unit === clientBudget.unit && revisedQuote.amount + quoteMarkup > clientBudget.amount
            if (stillAboveClientBudget) {
              if (!clientBudget) {
                toast.error('Client budget is missing. Cannot request a revised commercial from client.')
                runningRef.current = false
                return
              }
              try {
                const increment = clientBudget.unit === 'hour' ? 500 : 5000
                const requestedBudget = revisedQuote.amount + increment
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
            toast(`🤖 Auto: ${activeTrainer.name} (Rank ${rank}) declined ❌ — moving to next Mail 1 responder`, { icon: '⏭️', duration: 5000 })
            setStage(activeTrainer, 'rejected')
            runningRef.current = false
            return
          }

          if (acceptedNegotiatedCommercial) {
            toast(`Auto: ${activeTrainer.name} accepted revised commercials. Moving to slot booking.`, { icon: 'INR', duration: 5000 })
          } else if (acceptedClientBudgetRevision) {
            toast(`Auto: client approved revised commercials for ${activeTrainer.name}. Moving to slot booking.`, { icon: 'INR', duration: 5000 })
          } else if (!hasRequestedTrainerDetails(latest.body)) {
            const guardKey = `${req.requirement_id}:${activeTrainer.trainer_id}:mail2_followup:${replyTime}:${stripQuotedEmail(latest.body).slice(0, 80)}`
            if (replyTime > handledAt && shouldSendOnce(guardKey)) {
              const { subject, body } = mail2FollowupTemplate(activeTrainer, req)
              const res = await api.post('/shortlists/send-mail', {
                trainer_id:     activeTrainer.trainer_id,
                trainer_name:   activeTrainer.name,
                to_email:       activeTrainer.email,
                requirement_id: req.requirement_id,
                subject, body,
                mail_type: 'mail2_followup',
              })
              showSendStatusToast({ trainerName: activeTrainer.name, result: res.data, title: 'Details follow-up sent' })
              toast(`🤖 Auto: ${activeTrainer.name} replied without the requested details — details request sent again`, { icon: '📋', duration: 6000 })
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
            toast(`Auto: commercial negotiation sent to ${activeTrainer.name}`, { icon: '₹', duration: 5000 })
            setStage(activeTrainer, 'waiting_reply2', { commercialNegotiationAt: Date.now() })
            runningRef.current = false
            return
          }

          const { subject, body } = mail3Template(activeTrainer, req, '')
          const res = await api.post('/shortlists/send-mail', {
            trainer_id:     activeTrainer.trainer_id,
            trainer_name:   activeTrainer.name,
            to_email:       activeTrainer.email,
            requirement_id: req.requirement_id,
            subject, body,
            mail_type: 'mail3',
            client_email: req.client_email,
            client_name: req.client_name || req.client_company,
          })
          showSendStatusToast({ trainerName: activeTrainer.name, result: res.data, title: 'Slot booking sent' })
          toast(`🤖 Auto: Slot Booking mail sent to ${activeTrainer.name}`, { icon: '📅', duration: 5000 })
          setStage(activeTrainer, 'slot_booked')
          runningRef.current = false
          return
        }

        // No trainer is currently past Mail 1. Start Mail 2 for the first
        // positive Mail 1 responder, ordered by reply time.
        const nextResponder = trainers
          .filter(t => false && getStage(t) === 'mail1_replied')
          .sort((a, b) => {
            const aTime = nextStates[a.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
            const bTime = nextStates[b.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
            return aTime - bTime || trainers.indexOf(a) - trainers.indexOf(b)
          })[0]

        if (nextResponder) {
          const { subject, body } = mail2Template(nextResponder, req)
          const res = await api.post('/shortlists/send-mail', {
            trainer_id:     nextResponder.trainer_id,
            trainer_name:   nextResponder.name,
            to_email:       nextResponder.email,
            requirement_id: req.requirement_id,
            subject, body,
            mail_type: 'mail2',
          })
          showSendStatusToast({ trainerName: nextResponder.name, result: res.data, title: 'Details request sent' })
          toast(`🤖 Auto: sent Details Request (Mail 2) to ${nextResponder.name}`, { icon: '📋', duration: 4000 })
          setStage(nextResponder, 'waiting_reply2')
        }

      } catch (e) {
        toast.error(e.message || 'AutoPilot error')
      }

      runningRef.current = false
    }

    poll()
    const interval = setInterval(poll, SHORTLIST_REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [enabled, trainers, req])
}

// ─── Trainer Card ─────────────────────────────────────────────────────────────
function TrainerCard({ trainer, rank, state, req, onStatusUpdate, onRequirementPatch, autoMode, isActive }) {
  const stage     = backendAuthoritativeStage(trainer, req) || state?.status || 'pending'
  const stageInfo = STAGES[stage] || STAGES.pending
  const [mailModal, setMailModal] = useState(null)
  const [manualMailType, setManualMailType] = useState('mail1')
  const [showThread, setShowThread] = useState(false)
  const [showTocModal, setShowTocModal] = useState(false)
  const [showPoModal, setShowPoModal] = useState(false)
  const [sendingToc, setSendingToc] = useState(false)
  const [sendingClientPo, setSendingClientPo] = useState(false)
  const [sendingClientSlots, setSendingClientSlots] = useState(false)
  const [clientEmailRequest, setClientEmailRequest] = useState(null)
  const [threadMessages, setThreadMessages] = useState([])
  const [showTemplates, setShowTemplates] = useState(false)

  const BTN = 'flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-white transition-all active:scale-95 shadow-sm'

  const sendManualPipelineTemplate = () => {
    if (manualMailType === 'mail6_toc') {
      handleTocRequest()
      return
    }
    setMailModal(manualMailType)
  }

  const renderManualPipelineSelector = () => (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setShowTemplates(prev => !prev)}
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-bold text-slate-600 transition-all hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
      >
        <Send className="h-3.5 w-3.5" />
        {showTemplates ? 'Hide templates' : 'More templates'}
      </button>
      {showTemplates && (
        <div className="mt-2 flex flex-col gap-2 rounded-xl border border-blue-100 bg-blue-50/60 p-3 sm:flex-row sm:items-center">
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
            disabled={manualMailType === 'mail6_toc' && sendingToc}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-3 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {manualMailType === 'mail6_toc' && sendingToc ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
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
      {includeConfirm && (
        <button onClick={() => setMailModal('mail7_confirm')} className={clsx(BTN, 'bg-green-600 hover:bg-green-700')}>
          <CheckCircle2 className="w-3.5 h-3.5" /> Send Training Confirmation
        </button>
      )}
    </div>
  )

  const renderActions = () => {
    // ── ToC received — manual confirmation mail ──────────────────────────────
    if (stage === 'toc_received_pending') {
      return renderPostSelectionTools({
        note: 'ToC received from trainer. You can generate TOC/PO or send the final training confirmation.',
        includeConfirm: true,
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
              🎓 All done! Training confirmed and contact details shared with trainer.
            </span>
          </div>
          <button onClick={() => setShowPoModal(true)} className={clsx(BTN, 'bg-slate-900 hover:bg-slate-800')}>
            <FileText className="w-3.5 h-3.5" /> Generate PO
          </button>
        </div>
      )
    }

    // toc_requested — auto is polling, show waiting
    if (stage === 'toc_requested') {
      return (
        <div className="flex items-center gap-2 px-3 py-2 mt-3 bg-teal-50 border border-teal-200 rounded-xl">
          <Loader2 className="w-3.5 h-3.5 text-teal-500 animate-spin flex-shrink-0" />
          <span className="text-xs text-teal-700 font-medium">
            ⏳ Waiting for trainer to send ToC/Agenda — auto detects reply and notifies you
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
            <FileText className="w-3.5 h-3.5" /> Generate TOC 📋
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

    // ── AUTO MODE ───────────────────────────────────────────────────────────
    if (autoMode) {
      if (stage === 'waiting_reply1') {
        return (
          <div className="space-y-2 mt-3">
            <div className="flex items-center gap-2 px-3 py-2 bg-sky-50 border border-sky-200 rounded-xl">
              <Loader2 className="w-3.5 h-3.5 text-sky-500 animate-spin flex-shrink-0" />
              <span className="text-xs text-sky-700 font-medium">
                ⏳ Mail 1 sent — checking replies every 10s while reminders run at 6h, 12h, 24h
              </span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-50 border border-orange-100 rounded-xl">
              <Bell className="w-3 h-3 text-orange-400 flex-shrink-0" />
              <span className="text-xs text-orange-600">Auto reminders: <strong>6h · 12h · 24h</strong></span>
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
                ? 'Next Mail 1 responder — sending Request Details shortly'
                : 'Replied to Mail 1 — queued until the current trainer pipeline finishes'}
            </span>
          </div>
        )
      }

      if (stage === 'waiting_reply2' || stage === 'slot_booked') {
        const msgs = {
          waiting_reply2: '⏳ Waiting for complete Mail 2 details — incomplete replies get a details request again',
          slot_booked:    state?.slotConfirmed
            ? '✅ Trainer confirmed slot availability — send the Interview Link'
            : '⏳ Waiting for reply to Mail 3 — negative replies auto-reject and move to the next queued trainer',
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
              🤖 Mail 1 will be sent with the full shortlist batch
            </span>
          </div>
        )
      }

      if (stage === 'interview_scheduled') {
        return (
          <div className="flex flex-wrap gap-2 mt-3">
            <div className="w-full px-3 py-2 bg-purple-50 border border-purple-200 rounded-xl">
              <span className="text-xs text-purple-700 font-semibold">
                Interview decision ready. AI will generate the next mail for selection or rejection.
              </span>
            </div>
            <button onClick={() => setMailModal('mail5_ok')} className={clsx(BTN, 'bg-emerald-600 hover:bg-emerald-700')}>
              <PartyPopper className="w-3.5 h-3.5" /> Send Selection Mail
            </button>
            <button onClick={() => setMailModal('mail5_no')} className={clsx(BTN, 'bg-red-500 hover:bg-red-600')}>
              <ThumbsDown className="w-3.5 h-3.5" /> Send Rejection Mail
            </button>
          </div>
        )
      }

      return null
    }

    // ── MANUAL MODE ─────────────────────────────────────────────────────────
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
            <button onClick={() => setMailModal('mail2')} className={clsx(BTN, 'bg-indigo-600 hover:bg-indigo-700')}>
              <ClipboardList className="w-3.5 h-3.5" /> Request Details
            </button>
          </>
        )}
        {stage === 'waiting_reply2' && (
          <button onClick={() => setMailModal('mail2_followup')} className={clsx(BTN, 'bg-indigo-500 hover:bg-indigo-600')}>
            <ClipboardList className="w-3.5 h-3.5" /> Ask Details Again
          </button>
        )}
        {(stage === 'details_requested' || stage === 'details_received') && (
          <button onClick={() => setMailModal('mail3')} className={clsx(BTN, 'bg-amber-500 hover:bg-amber-600')}>
            <Calendar className="w-3.5 h-3.5" /> Book Interview Slot
          </button>
        )}
        {stage === 'slot_booked' && (
          <>
            {state?.slotConfirmed && (
              <button
                onClick={() => handleSendClientSlots({ force: true })}
                disabled={sendingClientSlots}
                className={clsx(BTN, 'bg-amber-600 hover:bg-amber-700 disabled:opacity-60')}
              >
                {sendingClientSlots ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                {state?.clientSlotsSentAt ? 'Resend Slots to Client' : 'Send Slots to Client'}
              </button>
            )}
            <button onClick={() => setMailModal('mail4')} className={clsx(BTN, 'bg-purple-600 hover:bg-purple-700')}>
              <Calendar className="w-3.5 h-3.5" /> Send Interview Link
            </button>
          </>
        )}
        {stage === 'interview_scheduled' && (
          <>
            <button onClick={() => setMailModal('mail5_ok')} className={clsx(BTN, 'bg-emerald-600 hover:bg-emerald-700')}>
              <PartyPopper className="w-3.5 h-3.5" /> Send Selection Mail
            </button>
            <button onClick={() => setMailModal('mail5_no')} className={clsx(BTN, 'bg-red-500 hover:bg-red-600')}>
              <ThumbsDown className="w-3.5 h-3.5" /> Send Rejection Mail
            </button>
          </>
        )}
        {stage === 'selected' && (
          <button onClick={handleTocRequest} disabled={sendingToc} className={clsx(BTN, 'bg-teal-600 hover:bg-teal-700 disabled:opacity-60')}>
            {sendingToc ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileText className="w-3.5 h-3.5" />}
            {sendingToc ? 'Sending...' : 'Request ToC / Agenda'}
          </button>
        )}
        {stage === 'toc_requested' && (
          <button onClick={() => setMailModal('mail7_confirm')} className={clsx(BTN, 'bg-green-600 hover:bg-green-700')}>
            <CheckCircle2 className="w-3.5 h-3.5" /> Send Training Confirmation
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

      if (res.data?.success === false) {
        throw new Error(res.data?.error || 'ToC request failed')
      }

      showSendStatusToast({ trainerName: trainer.name, result: res.data, title: 'ToC request sent' })
      toast.success('ToC request sent!')
      handleMailSent('toc_requested')
    } catch (e) {
      toast.error(e.message || 'ToC request failed')
    } finally {
      setSendingToc(false)
    }
  }

  const handleSendClientSlots = async ({ slotText = '', force = true, clientEmail = '', clientName = '' } = {}) => {
    if (sendingClientSlots) return
    setSendingClientSlots(true)
    try {
      let text = slotText || state?.clientSlotText || ''
      if (!text) {
        const res = await api.get(`/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}`)
        const latestSlotReply = latestReplyAfter(res.data.messages || [], ['mail3'])
        text = latestSlotReply?.body || ''
      }

      const sent = await sendSlotsToClient({ trainer, req, slotText: text, force, clientEmail, clientName })
      if (sent?.success === false) throw new Error(sent.error || 'Client slot email failed')

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
        const slotText = stripQuotedEmail(latestSlotReply?.body || '')
        if (slotText) extra.clientSlotText = slotText
        if (AUTO_SEND_CLIENT_SLOTS && slotText && !state?.clientSlotsSentAt) {
          handleSendClientSlots({ slotText, force: false })
        }
      }
      update(status, extra)
      return
    }

    const latestDetailsReply = latestReplyAfter(messages, ['mail2', 'mail2_followup'])
    if (latestDetailsReply && hasRequestedTrainerDetails(latestDetailsReply.body) && ['waiting_reply2', 'details_requested', 'slot_booked'].includes(current)) {
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

    const latestSlotReply = latestReplyAfter(messages, ['mail3'])
    if (latestSlotReply && current === 'slot_booked' && !state?.slotConfirmed) {
      const slotText = stripQuotedEmail(latestSlotReply.body)
      if (!hasProperInterviewSlots(slotText)) {
        const replyTime = new Date(latestSlotReply.sent_at || Date.now()).getTime()
        if (replyTime > (state?.slotClarificationAt || 0)) {
          sendSlotClarificationMail({ trainer, req })
            .then(res => showSendStatusToast({ trainerName: trainer.name, result: res, title: 'Slot clarification sent' }))
            .catch(e => toast.error(e.response?.data?.detail || e.message || 'Slot clarification failed'))
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
        handleSendClientSlots({ slotText, force: false })
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
              <span className={clsx('px-2 py-0.5 rounded-full text-xs font-semibold', stageInfo.color)}>{stageInfo.label}</span>
              {autoMode && isActive && !['selected','rejected','toc_requested','toc_received_pending','training_confirmed','slot_booked','interview_scheduled','po_requested','client_po_received','invoice_generated','invoice_sent'].includes(stage) && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-violet-100 text-violet-700 animate-pulse">
                  🤖 Auto Active
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

            <StepBar stage={stage} />
            <PipelineProgressSummary stage={stage} state={state} req={req} />
            {renderActions()}
            {renderManualPipelineSelector()}
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

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function Shortlist1() {
  const targetRequirementId = new URLSearchParams(globalThis.location.search).get('requirement_id') || ''
  const [reqs, setReqs]               = useState([])
  const [selectedReq, setSelectedReq] = useState(null)
  const [trainers, setTrainers]       = useState([])
  const [states, setStates]           = useState({})
  const autoMode = true
  const [loadingReqs, setLoadingReqs]         = useState(false)
  const [loadingTrainers, setLoadingTrainers] = useState(false)
  const [clientContactOpen, setClientContactOpen] = useState(false)
  const [savingClientContact, setSavingClientContact] = useState(false)
  const [deletingReqId, setDeletingReqId] = useState('')

  useEffect(() => {
    setLoadingReqs(true)
    getRequirements()
      .then(r => {
        const list = r.data.requirements || []
        setReqs(list)
        if (targetRequirementId) {
          const match = list.find(req => String(req.requirement_id) === String(targetRequirementId))
          if (match) setSelectedReq(match)
        }
      })
      .catch(() => {})
      .finally(() => setLoadingReqs(false))
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
      .catch(() => toast.error('Could not load shortlist'))
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
      .catch(() => {})
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
      ACTIVE_PIPELINE_STAGES.has(backendAuthoritativeStage(t, selectedReq) || states[t.trainer_id]?.status)
    )
    if (active) return active.trainer_id

    const queued = trainers
      .filter(t => (backendAuthoritativeStage(t, selectedReq) || states[t.trainer_id]?.status) === 'mail1_replied')
      .sort((a, b) => {
        const aTime = states[a.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
        const bTime = states[b.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
        return aTime - bTime || trainers.indexOf(a) - trainers.indexOf(b)
      })
    return queued[0]?.trainer_id || null
  })()

  const pipelineStats = {
    total: trainers.length,
    waiting: trainers.filter(t => ['waiting_reply1', 'waiting_reply2', 'toc_requested'].includes(backendAuthoritativeStage(t, selectedReq) || states[t.trainer_id]?.status)).length,
    replied: trainers.filter(t => ['mail1_replied', 'details_received', 'slot_booked', 'interview_scheduled', 'selected', 'toc_received_pending', 'training_confirmed'].includes(backendAuthoritativeStage(t, selectedReq) || states[t.trainer_id]?.status)).length,
    completed: trainers.filter(t => ['training_confirmed', 'rejected'].includes(backendAuthoritativeStage(t, selectedReq) || states[t.trainer_id]?.status)).length,
  }

  const aiFlowSteps = [
    { step: '01', label: 'First contact', note: 'AI sends Mail 1 to shortlisted trainers', color: 'bg-blue-600' },
    { step: '02', label: 'Reply check', note: 'Replies sync every 10 seconds', color: 'bg-sky-600' },
    { step: '03', label: 'Details request', note: 'Incomplete replies get a smart follow-up', color: 'bg-indigo-600' },
    { step: '04', label: 'Slot booking', note: 'AI asks for interview availability', color: 'bg-amber-500' },
    { step: '05', label: 'Selection', note: 'Selection or rejection mail is generated', color: 'bg-emerald-600' },
    { step: '06', label: 'ToC request', note: 'Selected trainer gets course agenda request', color: 'bg-teal-600' },
    { step: '07', label: 'Confirmation', note: 'Final schedule mail is generated', color: 'bg-green-600' },
  ]

  useAutoPilot({
    trainers,
    req: selectedReq,
    states,
    onStatusUpdate: handleStatusUpdate,
    enabled: autoMode && !!selectedReq && !!selectedReq.client_email,
  })

  const selectedTrainerForDomain = selectedReq
    ? trainers.find(t => String(t.trainer_id) === String(selectedReq.selected_trainer_id || '')) ||
      trainers.find(t => ['selected', 'toc_requested', 'toc_received_pending', 'training_confirmed'].includes(
        backendAuthoritativeStage(t, selectedReq) || states[t.trainer_id]?.status || t.pipeline_status || t.status
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
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="flex flex-col gap-5 p-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
              <Bot className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Shortlist1 AI Pipeline</h1>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
                AI generates every trainer mail from your 7-stage rules. Replies are checked every 10 seconds and trainer cards move through the pipeline automatically.
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
              <div key={label} className="min-w-[88px] rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
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

      <div className="bg-white rounded-2xl border border-slate-200 p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5" /> AI Mail Flow
        </p>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-7">
          {aiFlowSteps.map(s => (
            <div key={s.step} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
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
              {reqs.map(r => (
                <div key={r.requirement_id}
                  className="flex items-center gap-2 rounded-xl border bg-white border-slate-200 p-2 transition-all hover:border-blue-300 hover:bg-blue-50 group">
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
                    <p className="text-xs text-slate-400">{r.requirement_id} · Top {r.top_n}</p>
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
              <p className="text-xs text-slate-400">{selectedReq.requirement_id} · Top {selectedReq.top_n}</p>
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
              <p className="mt-0.5 text-blue-600">7 mails from outreach to confirmation</p>
            </div>
            <div className="rounded-xl bg-emerald-50 px-3 py-2 text-emerald-700">
              <p className="font-bold">Client handoff</p>
              <p className="mt-0.5 text-emerald-600">Slots, interview, selection, ToC</p>
            </div>
            <div className="rounded-xl bg-cyan-50 px-3 py-2 text-cyan-700">
              <p className="font-bold">Commercial closure</p>
              <p className="mt-0.5 text-cyan-600">PO request, invoice generation, invoice sent</p>
            </div>
          </div>

          {!selectedReq.client_email && (
            <div className="flex items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
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
