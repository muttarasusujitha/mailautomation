import { useState, useEffect, useRef } from 'react'
import { deleteRequirement, getRequirements, getShortlist, updateRequirement } from '../utils/api'
import api from '../utils/api'
import toast from 'react-hot-toast'
import {
  Users, Mail, Clock, MapPin, Phone,
  ChevronRight, ChevronLeft, Loader2, Send, AlertCircle,
  RefreshCw, Star, MessageSquare, X, Eye,
  Calendar, PartyPopper, ThumbsDown, ClipboardList, Info,
  FileText, CheckCircle2, Bell, PhoneCall, Download, Wand2, Trash2
} from 'lucide-react'
import clsx from 'clsx'

// ─── localStorage helpers ─────────────────────────────────────────────────────
function getLS(k) { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }
function setLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} }
function money(v) {
  const n = Number(v || 0)
  return `INR ${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

// ─── Date Parser ──────────────────────────────────────────────────────────────
function parseTrainingDate(dateStr) {
  if (!dateStr) return null
  const str = String(dateStr).trim()
  if (!str || str === 'null' || str === '') return null
  try {
    const d = new Date(str)
    if (!isNaN(d) && d.getFullYear() > 2000 && d.getFullYear() < 2100) {
      return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
    }
  } catch (e) {}
  const dayNames = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
  for (let i = 0; i < dayNames.length; i++) {
    if (str.toLowerCase().includes(`next ${dayNames[i]}`) || str.toLowerCase().includes(`this ${dayNames[i]}`)) {
      const today = new Date()
      const currentDay = today.getDay()
      let daysAhead = i - currentDay
      if (daysAhead <= 0) daysAhead += 7
      const result = new Date(today)
      result.setDate(result.getDate() + daysAhead)
      return result.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
    }
  }
  const dateMatch = str.match(/(\d{1,2})(st|nd|rd|th)?\s+([a-zA-Z]+)\s*(\d{4})?/)
  if (dateMatch) {
    const day = dateMatch[1]
    const month = dateMatch[3]
    const year = dateMatch[4] || new Date().getFullYear()
    try {
      const d = new Date(`${month} ${day}, ${year}`)
      if (!isNaN(d)) return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
    } catch (e) {}
  }
  const slashMatch = str.match(/(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})/)
  if (slashMatch) {
    try {
      const d = new Date(slashMatch[3], slashMatch[2] - 1, slashMatch[1])
      if (!isNaN(d)) return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
    } catch (e) {}
  }
  const weekMatch = str.match(/(\d+)(?:st|nd|rd|th)?\s+(?:week|Week)\s+(?:of\s+)?([a-zA-Z]+)\s*(\d{4})?/i)
  if (weekMatch) {
    const weekNum = parseInt(weekMatch[1])
    const month = weekMatch[2]
    const year = weekMatch[3] || new Date().getFullYear()
    try {
      const d = new Date(`${month} 1, ${year}`)
      d.setDate(d.getDate() + (weekNum - 1) * 7)
      if (!isNaN(d)) return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
    } catch (e) {}
  }
  if (str.toLowerCase() === 'today') return new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
  if (str.toLowerCase() === 'tomorrow') {
    const d = new Date()
    d.setDate(d.getDate() + 1)
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
  }
  if (str.length > 20) return str.substring(0, 17) + '...'
  return str.length > 0 ? str : null
}

// ─── Pipeline stages ──────────────────────────────────────────────────────────
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
  po_requested:         { label: 'PO Requested',           color: 'bg-cyan-100 text-blue-700',       step: 8 },
  client_po_received:   { label: 'Client PO Received',     color: 'bg-cyan-100 text-blue-700',       step: 8 },
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
const sentGuard = new Set()
let shortlistReplyCheckPromise = null
let lastShortlistReplyCheckAt = 0

function shouldSendOnce(key) {
  if (!key) return false
  if (sentGuard.has(key)) return false
  sentGuard.add(key)
  return true
}

function syncShortlistRepliesIfDue(force = false) {
  const now = Date.now()
  if (!force && now - lastShortlistReplyCheckAt < REPLY_SYNC_THROTTLE_MS) return Promise.resolve(null)
  if (!shortlistReplyCheckPromise) {
    lastShortlistReplyCheckAt = now
    shortlistReplyCheckPromise = api.post('/emails/check-replies')
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
  const knownDetails = [`* Domain/Technology: ${req.technology_needed || 'Training'}`]
  const trainerBudget = req.trainer_visible_budget_per_session || req.trainer_requested_budget_per_session
  if (req.duration_days || req.duration_hours) knownDetails.push(`* Duration: ${req.duration_days ? `${req.duration_days} day(s)` : `${req.duration_hours} hour(s)`}`)
  if (req.mode) knownDetails.push(`* Mode: ${req.mode}`)
  if (req.participant_count) knownDetails.push(`* Participants: ${req.participant_count}`)
  if (req.timeline_start || req.training_dates) knownDetails.push(`* Training dates: ${req.training_dates || req.timeline_start}`)
  else knownDetails.push('* Training dates: To be shared once finalized by the client')
  if (trainerBudget) knownDetails.push(`* Commercial budget: INR ${Number(trainerBudget).toLocaleString('en-IN')} per session`)
  const requestedDetails = [
    '* Total years of experience',
    '* Number of trainings conducted previously',
    '* Relevant certifications',
    '* Preferred training mode (Online / Offline)',
    '* Availability for Full-Day or Half-Day sessions',
    !trainerBudget ? '* Expected commercial charges per day/session' : '',
    '* Current location',
    '* Availability for the mentioned dates',
  ].filter(Boolean).join('\n')
  return {
    subject: `Training Requirement - ${req.technology_needed} | Additional Details Required`,
    body: `${greeting(trainer)}\n\nThank you for your response.\n\nPlease find the current requirement details below:\n\n${knownDetails.join('\n')}\n\nTo proceed further, kindly share the below details:\n\n${requestedDetails}\n\nBest Regards,\nRecruitment Team\nClahan Technologies`
  }
}

function mail2FollowupTemplate(trainer, req) {
  return {
    subject: `Re: Training Requirement – ${req.technology_needed} | Details Required`,
    body: `${greeting(trainer)}\n\nThank you for confirming your interest.\n\nTo proceed further, kindly share the above requested details:\n\n* Total years of experience\n* Number of trainings conducted previously\n* Relevant certifications\n* Preferred training mode (Online / Offline)\n* Availability for Full-Day or Half-Day sessions\n* Expected commercial charges per day/session\n* Current location\n* Availability for the mentioned dates\n\nOnce we receive these details, we can move ahead with the next step.\n\nRegards,\nTrainerSync Team`
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
    body: `${greeting(trainer)}\n\nPlease share the Training Table of Contents / Course Agenda, including the day-wise session breakdown, any tools or prerequisites required, and estimated preparation time.\n\nOnce we receive these details, we will coordinate with the client and trainer to finalize the agenda.\n\nRegards,\nTrainerSync Team`
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
    'let us proceed', 'i can ', 'yes,', 'sure,',
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

  const checks = [
    /\b\d{1,2}\+?\s*(years|yrs|year|yr)\b/.test(t) || /\bexperience\s*[:-]/.test(t),
    hasTrainingCount(t),
    /certification|certified|certificate|certifications|not certified|no certification|none/i.test(t),
    /\b(online|offline|hybrid|classroom|remote)\b/.test(t),
    /\b(full[-\s]?day|half[-\s]?day|full day|half day)\b/.test(t),
    /\b(inr|rs\.?|₹|rate|charges?|commercial|fee|fees|per day|per session|cost)\b/i.test(t),
    /\b(location|based in|current city|city)\b/i.test(t) || /\b(bengaluru|bangalore|chennai|hyderabad|pune|mumbai|delhi|gurgaon|noida|kolkata|india)\b/i.test(t),
    /\b(available|availability|dates?|from|to|weekdays|weekends|morning|afternoon|evening)\b/i.test(t),
  ]

  return checks.filter(Boolean).length >= 3
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
  return messages
    .filter(m => m.direction === 'received' && new Date(m.sent_at || 0).getTime() > lastSentTime)
    .sort((a, b) => new Date(a.sent_at || 0).getTime() - new Date(b.sent_at || 0).getTime())
    .at(-1) || null
}

// ─── Send Mail Modal ──────────────────────────────────────────────────────────
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

function MailModal({ trainer, req, mailType, onClose, onSent }) {
  const [loading, setLoading]           = useState(false)
  const [hasDetails, setHasDetails]     = useState(false)
  const [details, setDetails]           = useState({ domain: req?.technology_needed || '', duration: '', mode: 'Online', participants: '' })
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

  const getPreview = () => {
    switch (mailType) {
      case 'mail1':          return mail1Template(trainer, req, hasDetails, details)
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

  const preview = getPreview()

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
      if (mailType === 'mail4') {
        await api.post('/shortlists/send-interview-link', {
          trainer_id:     trainer.trainer_id,
          trainer_name:   trainer.name,
          to_email:       trainer.email,
          requirement_id: req.requirement_id,
          platform,
          date_time:      dateTime,
          interview_link: interviewLink,
        })
      } else {
        await api.post('/shortlists/send-mail', {
          trainer_id:     trainer.trainer_id,
          trainer_name:   trainer.name,
          to_email:       trainer.email,
          requirement_id: req.requirement_id,
          subject:        preview.subject,
          body:           preview.body,
          mail_type:      mailType,
          client_email:   mailType === 'mail3' ? clientEmail.trim() : undefined,
          client_name:    mailType === 'mail3' ? clientName.trim() : undefined,
        })
      }
      toast.success(`✅ Email sent to ${trainer.name}!`)
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
            <p className="text-sm text-slate-500 mt-0.5">To: <strong>{trainer.name}</strong> · {trainer.email}</p>
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

          <div>
            <p className="label mb-1">Email Preview</p>
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
              <p className="text-xs text-slate-400 mb-1 font-semibold">Subject: <span className="text-slate-700 font-normal">{preview.subject}</span></p>
              <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed mt-2">{preview.body}</pre>
            </div>
          </div>
        </div>

        <div className="flex gap-3 p-5 border-t border-slate-100 sticky bottom-0 bg-white">
          <button onClick={handleSend} disabled={loading}
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
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
            <p className="text-xs text-blue-700 font-semibold uppercase">Client Invoice</p>
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
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-cyan-700 text-white font-semibold text-sm disabled:opacity-50">
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
            await api.post('/shortlists/send-mail', {
              trainer_id:     trainer.trainer_id,
              trainer_name:   trainer.name,
              to_email:       trainer.email,
              requirement_id: req.requirement_id,
              subject, body,
              mail_type: 'mail6_toc',
            })
            toast(`🤖 Auto: ToC request sent to ${trainer.name} 📄`, { icon: '🤖', duration: 4000 })
            onStatusUpdate(trainer.trainer_id, 'toc_requested')
            runningRef.current = false
            return
          }

          if (st === 'toc_requested') {
            await syncShortlistRepliesIfDue()
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
                `🤖 Auto: ${trainer.name} sent the ToC/Agenda ✅ — now send Training Confirmation manually`,
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
          for (const trainer of pendingTrainers) {
            const { subject, body } = mail1Template(trainer, req, false, {})
            await api.post('/shortlists/send-mail', {
              trainer_id:     trainer.trainer_id,
              trainer_name:   trainer.name,
              to_email:       trainer.email,
              requirement_id: req.requirement_id,
              subject, body,
              mail_type: 'mail1',
            })
            setStage(trainer, 'waiting_reply1', { mail1SentAt: Date.now(), reminders: 0 })
          }
          toast(`🤖 Auto: Mail 1 sent to all ${pendingTrainers.length} shortlisted trainers`, { icon: '📧', duration: 5000 })
          runningRef.current = false
          return
        }

        // Check all Mail 1 recipients for replies and reminders. Positive
        // replies join the queue; Mail 2 is still sent to only one trainer.
        await syncShortlistRepliesIfDue()
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
                await api.post('/shortlists/send-mail', {
                  trainer_id:     trainer.trainer_id,
                  trainer_name:   trainer.name,
                  to_email:       trainer.email,
                  requirement_id: req.requirement_id,
                  subject,
                  body,
                  mail_type: 'mail1_question_redirect',
                })
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
              await api.post('/shortlists/send-mail', {
                trainer_id:     trainer.trainer_id,
                trainer_name:   trainer.name,
                to_email:       trainer.email,
                requirement_id: req.requirement_id,
                subject, body,
                mail_type: 'mail1_reminder',
              })
              const rank = trainers.indexOf(trainer) + 1
              toast(`🤖 Auto: ${label} sent to ${trainer.name} (Rank ${rank}) 🔔`, { icon: '⏰', duration: 4000 })
              break
            }
          }
        }

        // If one trainer is already past Mail 1, keep that trainer's pipeline
        // exclusive until manual selection/rejection completes.
        const activeTrainer = trainers.find(t =>
          ['waiting_reply2', 'slot_booked', 'interview_scheduled'].includes(getStage(t))
        )
        const activeStage = activeTrainer ? getStage(activeTrainer) : null

        if (activeStage === 'interview_scheduled') {
          runningRef.current = false
          return
        }

        if (activeStage === 'slot_booked') {
          const messages = await getThread(activeTrainer)
          const latestDetailsReply = latestReplyAfter(messages, ['mail2', 'mail2_followup'])
          if (latestDetailsReply && hasRequestedTrainerDetails(latestDetailsReply.body) && !nextStates[activeTrainer.trainer_id]?.detailsAcceptedAt) {
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
              if (replyTime > handledAt) {
                const { subject, body } = mail2FollowupTemplate(activeTrainer, req)
                await api.post('/shortlists/send-mail', {
                  trainer_id:     activeTrainer.trainer_id,
                  trainer_name:   activeTrainer.name,
                  to_email:       activeTrainer.email,
                  requirement_id: req.requirement_id,
                  subject, body,
                  mail_type: 'mail2_followup',
                })
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
            toast(`🤖 Auto: ${activeTrainer.name} confirmed slot availability — send the interview link manually`, { icon: '📅', duration: 5000 })
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

          if (intent === 'negative') {
            toast(`🤖 Auto: ${activeTrainer.name} (Rank ${rank}) declined ❌ — moving to next Mail 1 responder`, { icon: '⏭️', duration: 5000 })
            setStage(activeTrainer, 'rejected')
            runningRef.current = false
            return
          }

          if (!hasRequestedTrainerDetails(latest.body)) {
            if (replyTime > handledAt) {
              const { subject, body } = mail2FollowupTemplate(activeTrainer, req)
              await api.post('/shortlists/send-mail', {
                trainer_id:     activeTrainer.trainer_id,
                trainer_name:   activeTrainer.name,
                to_email:       activeTrainer.email,
                requirement_id: req.requirement_id,
                subject, body,
                mail_type: 'mail2_followup',
              })
              toast(`🤖 Auto: ${activeTrainer.name} replied without the requested details — details request sent again`, { icon: '📋', duration: 6000 })
              setStage(activeTrainer, 'waiting_reply2', { detailsFollowupAt: replyTime })
            }
            runningRef.current = false
            return
          }

          const { subject, body } = mail3Template(activeTrainer, req, '')
          await api.post('/shortlists/send-mail', {
            trainer_id:     activeTrainer.trainer_id,
            trainer_name:   activeTrainer.name,
            to_email:       activeTrainer.email,
            requirement_id: req.requirement_id,
            subject, body,
            mail_type: 'mail3',
            client_email: req.client_email,
            client_name: req.client_name || req.client_company,
          })
          toast(`🤖 Auto: Slot Booking mail sent to ${activeTrainer.name}`, { icon: '📅', duration: 5000 })
          setStage(activeTrainer, 'slot_booked')
          runningRef.current = false
          return
        }

        // No trainer is currently past Mail 1. Start Mail 2 for the first
        // positive Mail 1 responder, ordered by reply time.
        const nextResponder = trainers
          .filter(t => getStage(t) === 'mail1_replied')
          .sort((a, b) => {
            const aTime = nextStates[a.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
            const bTime = nextStates[b.trainer_id]?.mail1ReplyAt || Number.MAX_SAFE_INTEGER
            return aTime - bTime || trainers.indexOf(a) - trainers.indexOf(b)
          })[0]

        if (nextResponder) {
          const { subject, body } = mail2Template(nextResponder, req)
          await api.post('/shortlists/send-mail', {
            trainer_id:     nextResponder.trainer_id,
            trainer_name:   nextResponder.name,
            to_email:       nextResponder.email,
            requirement_id: req.requirement_id,
            subject, body,
            mail_type: 'mail2',
          })
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

// ─── Mode Toggle ──────────────────────────────────────────────────────────────
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
        {autoMode && <span className="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full font-semibold animate-pulse">🤖 Active</span>}
      </div>
    </div>
  )
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

  const renderActions = () => {
    // ── ToC received — manual confirmation mail ──────────────────────────────
    if (stage === 'toc_received_pending') {
      return (
        <div className="flex flex-wrap gap-2 mt-3">
          <div className="w-full px-3 py-2 bg-teal-50 border border-teal-200 rounded-xl">
            <span className="text-xs text-teal-700 font-semibold">
              📄 ToC received from trainer! Now send the Training Confirmation with contact details.
            </span>
          </div>
          <button onClick={() => setMailModal('mail7_confirm')} className={clsx(BTN, 'bg-green-600 hover:bg-green-700')}>
            <CheckCircle2 className="w-3.5 h-3.5" /> Send Training Confirmation
          </button>
        </div>
      )
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
          <div className="space-y-2 mt-3">
            <div className="flex items-center gap-2 px-3 py-2 bg-sky-50 border border-sky-200 rounded-xl">
              <Loader2 className="w-3.5 h-3.5 text-sky-500 animate-spin flex-shrink-0" />
              <span className="text-xs text-sky-700 font-medium">{msgs[stage]}</span>
            </div>
            {stage === 'slot_booked' && (
              <button onClick={() => handleSendClientSlots({ force: true })} disabled={sendingClientSlots}
                className={clsx(BTN, 'bg-blue-600 hover:bg-blue-700 disabled:opacity-60')}>
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
                Interview done? Select or Reject — auto will immediately send ToC request on selection.
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
          <>
            <button onClick={() => setMailModal('mail3')} className={clsx(BTN, 'bg-amber-500 hover:bg-amber-600')}>
              <Calendar className="w-3.5 h-3.5" /> Book Interview Slot
            </button>
          </>
        )}
        {stage === 'slot_booked' && (
          <>
            <button onClick={() => handleSendClientSlots({ force: true })} disabled={sendingClientSlots}
              className={clsx(BTN, 'bg-blue-600 hover:bg-blue-700 disabled:opacity-60')}>
              {sendingClientSlots ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              {state?.clientSlotsSentAt ? 'Resend Slots to Client' : 'Send Slots to Client'}
            </button>
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
          onSent={handleMailSent} />
      )}
      {showThread && <ThreadModal trainer={trainer} req={req} onClose={() => setShowThread(false)} onThreadUpdate={handleThreadUpdate} />}
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
        { duration: 9000, icon: '⚡' }
      )
    } else {
      toast('Manual mode', { icon: '🎮' })
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
    if (!selectedReq || autoMode) return
    await syncShortlistRepliesIfDue()

    try {
      const res = await api.get('/emails', {
        params: { requirement_id: selectedReq.requirement_id, page: 1, limit: 200 },
      })
      const replied = (res.data.emails || []).filter(e => e.reply_received && e.trainer_id)
      if (!replied.length) return

      setStates(prev => {
        const next = { ...prev }
        let changed = false

        for (const email of replied) {
          const trainerId = email.trainer_id
          const trainer = trainers.find(item => String(item.trainer_id) === String(trainerId))
          const backendStage = backendAuthoritativeStage(trainer, selectedReq)
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

          if ((['mail2', 'mail2_followup'].includes(mailType) && ['pending', 'details_requested', 'waiting_reply2'].includes(current))) {
            if (!hasRequestedTrainerDetails(email.reply_text || '')) continue
            status = 'details_received'
          } else if ((mailType === 'mail3' && ['pending', 'slot_booked'].includes(current))) {
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
      ['waiting_reply2','slot_booked','interview_scheduled','selected','toc_requested','toc_received_pending'].includes(backendAuthoritativeStage(t, selectedReq) || states[t.trainer_id]?.status)
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

  useAutoPilot({
    trainers,
    req: selectedReq,
    states,
    onStatusUpdate: handleStatusUpdate,
    enabled: autoMode && !!selectedReq,
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
      <div>
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <Users className="w-6 h-6 text-blue-500" /> Shortlist
        </h1>
        <p className="text-sm text-slate-500 mt-0.5">
          7-stage pipeline · Auto handles mails, reminders & ToC · Manual for interview, selection & confirmation
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <ModeToggle autoMode={autoMode} onChange={handleAutoToggle} />
        <div className={clsx('flex-1 rounded-2xl border px-4 py-3 text-sm transition-all',
          autoMode ? 'bg-violet-50 border-violet-200 text-violet-700' : 'bg-slate-50 border-slate-200 text-slate-600'
        )}>
          {autoMode ? (
            <span>
              <strong>🤖 Auto:</strong> Mail 1 to all shortlisted trainers + reminders. Mail 2/Mail 3 run by reply queue, one trainer at a time.{' '}
              <strong>Manual:</strong> Interview Link · Select/Reject · Training Confirmation.
            </span>
          ) : (
            <span><strong>Manual:</strong> You control every step for every trainer.</span>
          )}
        </div>
      </div>

      {/* Pipeline legend */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5" /> Pipeline Flow
        </p>
        <div className="flex items-center gap-1 flex-wrap text-xs">
          {[
            { n:'1', l:'Mail 1',       c:'bg-blue-600',    auto:true  },
            { n:'🔔', l:'Reminders',   c:'bg-orange-500',  auto:true  },
            { n:'→' },
            { n:'2', l:'Mail 2',       c:'bg-indigo-600',  auto:true  },
            { n:'→' },
            { n:'3', l:'Slot',         c:'bg-amber-500',   auto:true  },
            { n:'→' },
            { n:'4', l:'Interview',    c:'bg-purple-600',  auto:false },
            { n:'→' },
            { n:'5', l:'Select',       c:'bg-emerald-600', auto:false },
            { n:'→' },
            { n:'6', l:'ToC',          c:'bg-teal-600',    auto:true  },
            { n:'→' },
            { n:'7', l:'Confirm',      c:'bg-green-600',   auto:false },
          ].map((s, i) => s.n === '→'
            ? <span key={i} className="text-slate-300 text-base">→</span>
            : <div key={i} className="flex items-center gap-1">
                <span className={clsx('w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0', s.c)}>{s.n}</span>
                {s.l && <span className="text-slate-600">{s.l}</span>}
                {s.auto === true  && <span className="text-[10px] text-violet-500 font-bold">🤖</span>}
                {s.auto === false && <span className="text-[10px] text-slate-400 font-bold">manual</span>}
              </div>
          )}
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
                const hiringStartDate = r.timeline_start || r.training_dates
                let trainingDateDisplay = 'TBD'
                if (hiringStartDate) {
                  try {
                    // Try ISO date first
                    let d = new Date(hiringStartDate)
                    if (!isNaN(d) && d.getFullYear() > 2000) {
                      trainingDateDisplay = d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
                    } else {
                      // Try parsing text like "21 June 2026"
                      const textMatch = hiringStartDate.match(/(\d{1,2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(\d{4})?/i)
                      if (textMatch) {
                        const [_, day, month, year] = textMatch
                        const yr = year || new Date().getFullYear()
                        const dateObj = new Date(`${month} ${day}, ${yr}`)
                        trainingDateDisplay = dateObj.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
                      } else {
                        trainingDateDisplay = hiringStartDate.substring(0, 12)
                      }
                    }
                  } catch (e) {
                    trainingDateDisplay = hiringStartDate.substring(0, 12)
                  }
                }
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
                      <p className="text-xs text-slate-400">{r.requirement_id} · Top {r.top_n}</p>
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
                <p className="text-xs text-slate-400">{selectedReq.requirement_id} · Top {selectedReq.top_n}</p>
                {(() => {
                  const hiringStart = selectedReq.timeline_start || selectedReq.training_dates
                  let dateDisplay = 'TBD'
                  if (hiringStart) {
                    try {
                      let d = new Date(hiringStart)
                      if (!isNaN(d) && d.getFullYear() > 2000) {
                        dateDisplay = d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
                      } else {
                        const textMatch = hiringStart.match(/(\d{1,2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(\d{4})?/i)
                        if (textMatch) {
                          const [_, day, month, year] = textMatch
                          const yr = year || new Date().getFullYear()
                          const dateObj = new Date(`${month} ${day}, ${yr}`)
                          dateDisplay = dateObj.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
                        } else {
                          dateDisplay = hiringStart.substring(0, 12)
                        }
                      }
                    } catch (e) {
                      dateDisplay = hiringStart.substring(0, 12)
                    }
                  }
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
              <p className="mt-0.5 text-blue-600">7 mails from outreach to confirmation</p>
            </div>
            <div className="rounded-xl bg-emerald-50 px-3 py-2 text-emerald-700">
              <p className="font-bold">Client handoff</p>
              <p className="mt-0.5 text-emerald-600">Slots, interview, selection, ToC</p>
            </div>
            <div className="rounded-xl bg-blue-50 px-3 py-2 text-blue-700">
              <p className="font-bold">Commercial closure</p>
              <p className="mt-0.5 text-blue-600">PO request, invoice generation, invoice sent</p>
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
