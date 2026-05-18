import { useState, useEffect, useRef } from 'react'
import { getRequirements, getShortlist } from '../utils/api'
import api from '../utils/api'
import toast from 'react-hot-toast'
import {
  Users, Mail, Clock, MapPin, Phone,
  ChevronRight, ChevronLeft, Loader2, Send, AlertCircle,
  RefreshCw, Star, MessageSquare, X, Eye,
  Calendar, PartyPopper, ThumbsDown, ClipboardList, Info,
  FileText, CheckCircle2, Bell, PhoneCall, Download, Wand2
} from 'lucide-react'
import clsx from 'clsx'

// ─── localStorage helpers ─────────────────────────────────────────────────────
function getLS(k) { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }
function setLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} }
function money(v) {
  const n = Number(v || 0)
  return `INR ${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
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
  toc_requested:        { label: 'ToC Requested 📄',      color: 'bg-teal-100 text-teal-700',       step: 6 },
  toc_received_pending: { label: 'ToC Received 📄',       color: 'bg-teal-100 text-teal-700',       step: 6 },
  training_confirmed:   { label: 'Training Confirmed 🎓', color: 'bg-green-100 text-green-700',     step: 7 },
}

// ─── Reminder intervals for Mail 1 (in ms) ───────────────────────────────────
const REMINDER_INTERVALS = [
  { hours: 6,  label: '6h follow-up'  },
  { hours: 12, label: '12h follow-up' },
  { hours: 24, label: '24h follow-up' },
]

const SHORTLIST_REFRESH_INTERVAL_MS = 10000

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
  body += `\n\nPlease let us know if you are interested and available for this requirement. Kindly share your updated trainer profile along with relevant experience.\n\nRegards,\nTrainerSync Team`
  const subject = isReminder
    ? `[Reminder ${reminderNum}] Training Requirement – ${domain}`
    : `Training Requirement – ${domain}`
  return { subject, body }
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

function mail3Template(trainer, req, trainerDates) {
  return {
    subject: `Interview Slot Booking – ${req.technology_needed}`,
    body: `${greeting(trainer)}\n\nThank you for sharing your details.\n\nWe would like to book an interview slot with you. Based on your availability, please confirm one of the following slots:\n\n${trainerDates || '• [Slot 1]\n• [Slot 2]\n• [Slot 3]'}\n\nKindly confirm your preferred slot at the earliest.\n\nRegards,\nTrainerSync Team`
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

function hasRequestedTrainerDetails(text = '') {
  const t = stripQuotedEmail(text).toLowerCase()
  if (!t) return false

  const checks = [
    /\b\d{1,2}\+?\s*(years|yrs|year|yr)\b/.test(t) || /\bexperience\s*[:\-]/.test(t),
    /(training|trainings|session|sessions|batch|batches|conducted)\s*[:\-]?\s*\d+/i.test(t) || /\b\d+\s*(training|trainings|session|sessions|batch|batches)\b/.test(t),
    /certification|certified|certificate|certifications|not certified|no certification|none/i.test(t),
    /\b(online|offline|hybrid|classroom|remote)\b/.test(t),
    /\b(full[-\s]?day|half[-\s]?day|full day|half day)\b/.test(t),
    /\b(inr|rs\.?|₹|rate|charges?|commercial|fee|fees|per day|per session|cost)\b/i.test(t),
    /\b(location|based in|current city|city)\b/i.test(t) || /\b(bengaluru|bangalore|chennai|hyderabad|pune|mumbai|delhi|gurgaon|noida|kolkata|india)\b/i.test(t),
    /\b(available|availability|dates?|from|to|weekdays|weekends|morning|afternoon|evening)\b/i.test(t),
  ]

  return checks.filter(Boolean).length >= 3
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
        })
      }
      toast.success(`✅ Email sent to ${trainer.name}!`)
      onSent(
        NEXT_STAGES[mailType],
        mailType === 'mail7_confirm'
          ? { trainingDate, venue, contactName, contactPhone, contactEmail }
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
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
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
// TOC Generator Modal
function TocModal({ trainer, req, onClose }) {
  const [form, setForm] = useState({
    duration_days: 3,
    audience_level: 'intermediate',
    mode: 'Online',
    toc_type: 'standard',
    custom_topics: '',
  })
  const [tocId, setTocId] = useState('')
  const [tocData, setTocData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [sending, setSending] = useState(false)

  const update = (key, value) => setForm(prev => ({ ...prev, [key]: value }))

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
        toc_type: form.toc_type,
        custom_topics: form.custom_topics,
      })
      setTocId(res.data.toc_id)
      setTocData(res.data.toc_data)
      toast.success('TOC generated successfully')
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'TOC generation failed')
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
                <input type="number" min="1" max="15" className="input" value={form.duration_days}
                  onChange={e => update('duration_days', e.target.value)} />
              </div>
              <div>
                <label className="label">Audience Level</label>
                <select className="input" value={form.audience_level} onChange={e => update('audience_level', e.target.value)}>
                  <option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
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
            </div>

            <button onClick={handleGenerate} disabled={loading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-teal-600 hover:bg-teal-700 text-white font-bold text-sm transition-all disabled:opacity-60">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              {loading ? 'Generating...' : 'Generate TOC'}
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
    payment_terms: 'Payment will be processed within 30 days from successful completion of training and receipt of a valid invoice.',
  }
}

function PurchaseOrderModal({ trainer, req, state, onClose }) {
  const [form, setForm] = useState(() => initialPoForm(trainer, req, state))
  const [po, setPo] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [sending, setSending] = useState(false)

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
            <div className="md:col-span-2">
              <label className="label">Payment Terms</label>
              <textarea rows={3} className="input resize-none" value={form.payment_terms} onChange={e => update('payment_terms', e.target.value)} />
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

  useEffect(() => {
    let cancelled = false

    const loadThread = async (silent = false) => {
      if (!silent) setLoading(true)
      try {
        const r = await api.get(`/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}`)
        if (cancelled) return
        const all = r.data.messages || []
        const filtered = all.filter(m => {
          const trainerMatch = !m.trainer_id || String(m.trainer_id) === String(trainer.trainer_id)
          const reqMatch = !m.requirement_id || String(m.requirement_id) === String(req.requirement_id)
          return trainerMatch && reqMatch
        })
        filtered.sort((a, b) => new Date(a.sent_at || 0) - new Date(b.sent_at || 0))
        setThread(filtered)
        onThreadUpdate?.(filtered)
      } catch {
        if (!cancelled) setThread([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadThread()
    const interval = setInterval(() => loadThread(true), SHORTLIST_REFRESH_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
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
  const isDone     = stage === 'training_confirmed'

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
        const getStage = trainer => nextStates[trainer.trainer_id]?.status || 'pending'
        const setStage = (trainer, status, extra = {}) => {
          nextStates[trainer.trainer_id] = { status, ...extra }
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
            try { await api.post('/emails/check-replies') } catch {}
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
        try { await api.post('/emails/check-replies') } catch {}
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

          if (intent === 'positive') {
            toast(`🤖 Auto: ${activeTrainer.name} confirmed slot availability — send the interview link manually`, { icon: '📅', duration: 5000 })
            setStage(activeTrainer, 'slot_booked', { slotReplyAt: replyTime, slotConfirmed: true })
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
        console.error('AutoPilot error:', e.message)
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
function TrainerCard({ trainer, rank, state, req, onStatusUpdate, autoMode, isActive }) {
  const stage     = state?.status || 'pending'
  const stageInfo = STAGES[stage] || STAGES.pending
  const [mailModal, setMailModal] = useState(null)
  const [showThread, setShowThread] = useState(false)
  const [showTocModal, setShowTocModal] = useState(false)
  const [showPoModal, setShowPoModal] = useState(false)
  const [sendingToc, setSendingToc] = useState(false)

  const BTN = 'flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-white transition-all active:scale-95 shadow-sm'

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
          <div className="flex items-center gap-2 px-3 py-2 mt-3 bg-sky-50 border border-sky-200 rounded-xl">
            <Loader2 className="w-3.5 h-3.5 text-sky-500 animate-spin flex-shrink-0" />
            <span className="text-xs text-sky-700 font-medium">{msgs[stage]}</span>
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
          <button onClick={() => setMailModal('mail4')} className={clsx(BTN, 'bg-purple-600 hover:bg-purple-700')}>
            <Calendar className="w-3.5 h-3.5" /> Send Interview Link
          </button>
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
      update('slot_booked', {
        slotReplyAt: new Date(latestSlotReply.sent_at || Date.now()).getTime(),
        slotConfirmed: true,
      })
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
      {showPoModal && <PurchaseOrderModal trainer={trainer} req={req} state={state} onClose={() => setShowPoModal(false)} />}

      <div className={clsx('bg-white rounded-2xl border p-4 transition-all hover:shadow-md',
        stage === 'training_confirmed'   ? 'border-green-300 bg-green-50/30'   :
        stage === 'toc_received_pending' ? 'border-teal-300 bg-teal-50/20'     :
        stage === 'toc_requested'        ? 'border-teal-200 bg-teal-50/10'     :
        stage === 'selected'             ? 'border-emerald-300 bg-emerald-50/20':
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
              {autoMode && isActive && !['selected','rejected','toc_requested','toc_received_pending','training_confirmed','slot_booked','interview_scheduled'].includes(stage) && (
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
        setStates(getLS(`sl_v5_${selectedReq.requirement_id}`) || {})
      })
      .catch(() => toast.error('Could not load shortlist'))
      .finally(() => setLoadingTrainers(false))
  }, [selectedReq])

  const handleStatusUpdate = (trainerId, newStage, extra = {}) => {
    setStates(prev => {
      const next = { ...prev, [trainerId]: { status: newStage, ...extra } }
      if (selectedReq) setLS(`sl_v5_${selectedReq.requirement_id}`, next)
      return next
    })
  }

  const handleAutoToggle = val => {
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

  const reload = () => {
    if (!selectedReq) return
    setLoadingTrainers(true)
    getShortlist(selectedReq.requirement_id)
      .then(r => setTrainers(r.data.top_trainers || r.data.trainers || []))
      .catch(() => {})
      .finally(() => setLoadingTrainers(false))
  }

  const syncReplyStates = async () => {
    if (!selectedReq || autoMode) return
    try { await api.post('/emails/check-replies') } catch {}

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
          const current = next[trainerId]?.status || 'pending'
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
      ['waiting_reply2','slot_booked','interview_scheduled','selected','toc_requested','toc_received_pending'].includes(states[t.trainer_id]?.status)
    )
    if (active) return active.trainer_id

    const queued = trainers
      .filter(t => states[t.trainer_id]?.status === 'mail1_replied')
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

  return (
    <div className="space-y-5">
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
              {reqs.map(r => (
                <button key={r.requirement_id} onClick={() => setSelectedReq(r)}
                  className="flex items-center gap-3 p-3 rounded-xl border bg-white border-slate-200 hover:border-blue-300 hover:bg-blue-50 text-left transition-all group">
                  <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                    <Star className="w-4 h-4 text-blue-500" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-sm truncate text-slate-800">{r.technology_needed}</p>
                    <p className="text-xs text-slate-400">{r.requirement_id} · Top {r.top_n}</p>
                  </div>
                  <ChevronRight className="w-4 h-4 opacity-30 group-hover:opacity-70 flex-shrink-0" />
                </button>
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

          <div className="flex flex-wrap gap-2">
            {Object.entries(STAGES).map(([k, v]) => (
              <span key={k} className={clsx('px-2 py-1 rounded-full text-xs font-semibold', v.color)}>{v.label}</span>
            ))}
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
