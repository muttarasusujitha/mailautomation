import { useState, useEffect } from 'react'
import { getRequirements, getShortlist } from '../utils/api'
import api from '../utils/api'
import toast from 'react-hot-toast'
import {
  Users, Mail, Clock, MapPin, Phone, CheckCircle2, XCircle,
  ChevronRight, ChevronLeft, Loader2, Send, AlertCircle,
  RefreshCw, Star, MessageSquare, FileText, X, Eye,
  Calendar, PartyPopper, ThumbsDown, ClipboardList, Info
} from 'lucide-react'
import clsx from 'clsx'

// ─── localStorage ─────────────────────────────────────────────────────────────
function getLS(k) { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }
function setLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} }

// ─── Pipeline stages ──────────────────────────────────────────────────────────
// stage: pending → mail1_sent → details_requested → slot_booked → interview_scheduled → selected | rejected
const STAGES = {
  pending:              { label: 'Pending',              color: 'bg-slate-100 text-slate-500',      step: 0 },
  mail1_sent:           { label: '1st Mail Sent 📧',     color: 'bg-blue-100 text-blue-700',        step: 1 },
  details_requested:    { label: 'Details Requested 📋', color: 'bg-indigo-100 text-indigo-700',    step: 2 },
  slot_booked:          { label: 'Slot Booked 📅',       color: 'bg-amber-100 text-amber-700',      step: 3 },
  interview_scheduled:  { label: 'Interview Scheduled 🗓️',color: 'bg-purple-100 text-purple-700',  step: 4 },
  selected:             { label: 'Selected ✅',          color: 'bg-emerald-100 text-emerald-700',  step: 5 },
  rejected:             { label: 'Not Selected ❌',       color: 'bg-red-100 text-red-600',          step: 5 },
}

// ─── Email template builders ──────────────────────────────────────────────────
function mail1Template(trainer, req, hasDetails, details) {
  const domain = details.domain || req.technology_needed
  const subject = `Training Requirement – ${domain}`
  let body = `Dear Sir/Madam,\n\nWe have received a training requirement for ${domain} and are looking for a trainer with relevant experience.\n\nTraining Details:\n\nDomain/Technology: ${domain}`
  if (hasDetails) {
    if (details.duration)     body += `\nDuration: ${details.duration}`
    if (details.mode)         body += `\nMode: ${details.mode}`
    if (details.participants) body += `\nParticipants: ${details.participants}`
  }
  body += `\n\nPlease let us know if you are interested and available for this requirement. Kindly share your updated trainer profile along with relevant experience.\n\nRegards,\nTrainerSync Team`
  return { subject, body }
}

function mail2Template(req) {
  const domain = req.technology_needed
  return {
    subject: `Training Requirement – ${domain} | Additional Details Required`,
    body: `Dear Sir/Madam,\n\nThank you for your response.\n\nTo proceed further, kindly share the below details:\n\n* Total years of experience\n* Number of trainings conducted previously\n* Relevant certifications\n* Preferred training mode (Online / Offline)\n* Availability for Full-Day or Half-Day sessions\n* Expected commercial charges per day/session\n* Current location\n* Availability for the mentioned dates\n\nRegards,\nTrainerSync Team`
  }
}

function mail3Template(req, trainerDates) {
  const domain = req.technology_needed
  return {
    subject: `Interview Slot Booking – ${domain}`,
    body: `Dear Sir/Madam,\n\nThank you for sharing your details.\n\nWe would like to book an interview slot with you. Based on your availability, please confirm one of the following slots:\n\n${trainerDates || '• [Slot 1]\n• [Slot 2]\n• [Slot 3]'}\n\nKindly confirm your preferred slot at the earliest.\n\nRegards,\nTrainerSync Team`
  }
}

function mail4Template(req, interviewLink, platform, dateTime) {
  const domain = req.technology_needed
  return {
    subject: `Interview Schedule Confirmation – ${domain}`,
    body: `Dear Sir/Madam,\n\nYour interview has been scheduled. Please find the details below:\n\nDate & Time: ${dateTime || '[Date & Time]'}\nPlatform: ${platform || 'Zoom'}\nMeeting Link: ${interviewLink || '[Meeting Link]'}\n\nPlease join on time. Let us know if you need any assistance.\n\nRegards,\nTrainerSync Team`
  }
}

function mail5SelectedTemplate(req) {
  const domain = req.technology_needed
  return {
    subject: `Congratulations! You have been Selected – ${domain}`,
    body: `Dear Sir/Madam,\n\nCongratulations! We are pleased to inform you that you have been selected for the ${domain} training requirement.\n\nTo proceed further, kindly share the following:\n\n* Table of Contents (ToC) / Course Agenda for the training\n* Any prerequisite materials or tools required\n\nWe look forward to working with you!\n\nRegards,\nTrainerSync Team`
  }
}

function mail5RejectedTemplate(req) {
  const domain = req.technology_needed
  return {
    subject: `Update on Training Requirement – ${domain}`,
    body: `Dear Sir/Madam,\n\nThank you for your time and interest in the ${domain} training requirement.\n\nAfter careful consideration, we regret to inform you that we have decided to proceed with another trainer at this time.\n\nWe will keep your profile on record and reach out for future opportunities.\n\nThank you once again for your cooperation.\n\nRegards,\nTrainerSync Team`
  }
}

// ─── Send Mail Modal ──────────────────────────────────────────────────────────
function MailModal({ trainer, req, mailType, onClose, onSent }) {
  const [loading, setLoading] = useState(false)
  const [hasDetails, setHasDetails] = useState(false)
  const [details, setDetails] = useState({ domain: req?.technology_needed || '', duration: '', mode: 'Online', participants: '' })
  const [trainerDates, setTrainerDates] = useState('')
  const [interviewLink, setInterviewLink] = useState('')
  const [platform, setPlatform] = useState('Zoom')
  const [dateTime, setDateTime] = useState('')

  const getPreview = () => {
    switch (mailType) {
      case 'mail1':    return mail1Template(trainer, req, hasDetails, details)
      case 'mail2':    return mail2Template(req)
      case 'mail3':    return mail3Template(req, trainerDates)
      case 'mail4':    return mail4Template(req, interviewLink, platform, dateTime)
      case 'mail5_ok': return mail5SelectedTemplate(req)
      case 'mail5_no': return mail5RejectedTemplate(req)
      default:         return { subject: '', body: '' }
    }
  }

  const preview = getPreview()

  const TITLES = {
    mail1:    '📧 Send Shortlist Mail',
    mail2:    '📋 Request Trainer Details',
    mail3:    '📅 Book Interview Slot',
    mail4:    '🗓️ Send Interview Schedule',
    mail5_ok: '🎉 Send Selection Mail',
    mail5_no: '❌ Send Rejection Mail',
  }

  const NEXT_STAGES = {
    mail1:    'mail1_sent',
    mail2:    'details_requested',
    mail3:    'slot_booked',
    mail4:    'interview_scheduled',
    mail5_ok: 'selected',
    mail5_no: 'rejected',
  }

  const handleSend = async () => {
    setLoading(true)
    try {
      await api.post('/shortlists/send-mail', {
        trainer_id:     trainer.trainer_id,
        trainer_name:   trainer.name,
        to_email:       trainer.email,
        requirement_id: req.requirement_id,
        subject:        preview.subject,
        body:           preview.body,
        mail_type:      mailType,
      })
      toast.success(`✅ Email sent to ${trainer.name}!`)
      onSent(NEXT_STAGES[mailType])
      onClose()
    } catch (e) { toast.error(e.response?.data?.detail || e.message || 'Send failed') }
    finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-slate-100 sticky top-0 bg-white z-10">
          <div>
            <h3 className="font-bold text-lg text-slate-900">{TITLES[mailType]}</h3>
            <p className="text-sm text-slate-500 mt-0.5">To: <strong>{trainer.name}</strong> · {trainer.email}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg transition-colors"><X className="w-4 h-4 text-slate-500" /></button>
        </div>

        <div className="p-5 space-y-4">
          {/* Mail 1 extra fields */}
          {mailType === 'mail1' && (
            <div className="bg-slate-50 rounded-xl p-4 space-y-3 border border-slate-200">
              <div className="flex items-center gap-3">
                <input type="checkbox" id="hasDetails" checked={hasDetails} onChange={e => setHasDetails(e.target.checked)} className="w-4 h-4 accent-brand-500" />
                <label htmlFor="hasDetails" className="text-sm font-semibold text-slate-700 cursor-pointer">Client has shared training details</label>
              </div>
              {hasDetails && (
                <div className="grid grid-cols-2 gap-3 pt-2">
                  <div><label className="label">Domain</label><input className="input" value={details.domain} onChange={e => setDetails(d => ({...d, domain: e.target.value}))} /></div>
                  <div><label className="label">Duration</label><input className="input" placeholder="e.g. 3 days / 20 hrs" value={details.duration} onChange={e => setDetails(d => ({...d, duration: e.target.value}))} /></div>
                  <div><label className="label">Mode</label><select className="input" value={details.mode} onChange={e => setDetails(d => ({...d, mode: e.target.value}))}><option>Online</option><option>Offline</option><option>Hybrid</option></select></div>
                  <div><label className="label">Participants</label><input className="input" placeholder="e.g. 20" value={details.participants} onChange={e => setDetails(d => ({...d, participants: e.target.value}))} /></div>
                </div>
              )}
            </div>
          )}

          {/* Mail 3 extra fields */}
          {mailType === 'mail3' && (
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <label className="label">Trainer's Available Dates (from their reply)</label>
              <textarea className="input resize-none" rows={3} placeholder="• Monday 10 AM – 12 PM&#10;• Wednesday 2 PM – 4 PM&#10;• Friday anytime" value={trainerDates} onChange={e => setTrainerDates(e.target.value)} />
            </div>
          )}

          {/* Mail 4 extra fields */}
          {mailType === 'mail4' && (
            <div className="bg-slate-50 rounded-xl p-4 space-y-3 border border-slate-200">
              <div className="grid grid-cols-3 gap-2">
                {['Zoom','MS Teams','Google Meet'].map(p => (
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

          {/* Preview */}
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
          <button onClick={onClose}
            className="px-4 py-2.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-sm transition-all">
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Thread Modal ─────────────────────────────────────────────────────────────
function ThreadModal({ trainer, req, onClose }) {
  const [thread, setThread] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/shortlists/thread?trainer_id=${trainer.trainer_id}&requirement_id=${req.requirement_id}`)
      .then(r => setThread(r.data.messages || []))
      .catch(() => setThread([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-slate-100 sticky top-0 bg-white">
          <div>
            <h3 className="font-bold text-lg text-slate-900">💬 Conversation Thread</h3>
            <p className="text-sm text-slate-500">{trainer.name} · {req.technology_needed}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg"><X className="w-4 h-4 text-slate-500" /></button>
        </div>
        <div className="p-5 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-slate-400"><Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...</div>
          ) : thread.length === 0 ? (
            <div className="text-center py-10 text-slate-400"><MessageSquare className="w-10 h-10 mx-auto mb-2 opacity-30" /><p>No messages yet</p></div>
          ) : thread.map((msg, i) => {
            const isSent = msg.direction === 'sent'
            const STAGE_LABELS = { mail1:'1st Contact', mail2:'Details Request', mail3:'Slot Booking', mail4:'Interview Schedule', mail5_ok:'Selection', mail5_no:'Rejection', reply:'Trainer Reply', toc:'ToC Request' }
            return (
              <div key={i} className={clsx('rounded-xl p-4 border', isSent ? 'bg-blue-50 border-blue-100 ml-8' : 'bg-slate-50 border-slate-200 mr-8')}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className={clsx('text-xs font-bold', isSent ? 'text-blue-600' : 'text-slate-600')}>
                    {isSent ? '📤 You sent' : '📥 Trainer replied'}
                  </span>
                  <div className="flex items-center gap-2">
                    {msg.mail_type && <span className="text-xs px-2 py-0.5 rounded-full bg-white border border-slate-200 text-slate-500">{STAGE_LABELS[msg.mail_type] || msg.mail_type}</span>}
                    <span className="text-xs text-slate-400">{msg.sent_at ? new Date(msg.sent_at).toLocaleString() : ''}</span>
                  </div>
                </div>
                <p className="text-xs text-slate-500 mb-1"><span className="font-semibold">Subject:</span> {msg.subject}</p>
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
  const steps = ['1st Mail', 'Details', 'Slot', 'Interview', 'Result']
  const current = STAGES[stage]?.step ?? 0
  const isDone = stage === 'selected' || stage === 'rejected'

  return (
    <div className="flex items-center gap-0 mt-2">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center">
          <div className={clsx('w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold transition-all',
            i < current ? (stage === 'rejected' && i === 4 ? 'bg-red-500 text-white' : 'bg-blue-500 text-white') :
            i === current && isDone ? (stage === 'selected' ? 'bg-emerald-500 text-white' : 'bg-red-500 text-white') :
            i === current ? 'bg-blue-500 text-white ring-2 ring-blue-200' :
            'bg-slate-200 text-slate-400'
          )}>
            {i < current || (i === current && isDone) ? '✓' : i + 1}
          </div>
          <div className="hidden sm:block mx-0.5 text-xs text-slate-400 whitespace-nowrap">{s}</div>
          {i < steps.length - 1 && <div className={clsx('w-4 h-0.5 mx-0.5', i < current ? 'bg-blue-400' : 'bg-slate-200')} />}
        </div>
      ))}
    </div>
  )
}

// ─── Action Buttons per stage ─────────────────────────────────────────────────
function ActionButtons({ stage, trainer, req, onMailModal, onStatusUpdate }) {
  const BTN = 'flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-white transition-all active:scale-95 shadow-sm'

  if (stage === 'selected' || stage === 'rejected') return null

  return (
    <div className="flex flex-wrap gap-2 mt-1">
      {/* Stage 0 → send mail1 */}
      {stage === 'pending' && (
        <button onClick={() => onMailModal('mail1')} className={clsx(BTN, 'bg-blue-600 hover:bg-blue-700')}>
          <Mail className="w-3.5 h-3.5" /> Send Shortlist Mail
        </button>
      )}

      {/* Stage 1 → trainer replied, now request details */}
      {stage === 'mail1_sent' && (
        <>
          <button onClick={() => onMailModal('mail1')} className={clsx(BTN, 'bg-slate-500 hover:bg-slate-600')}>
            <Mail className="w-3.5 h-3.5" /> Resend Mail
          </button>
          <button onClick={() => onMailModal('mail2')} className={clsx(BTN, 'bg-indigo-600 hover:bg-indigo-700')}>
            <ClipboardList className="w-3.5 h-3.5" /> Request Details
          </button>
        </>
      )}

      {/* Stage 2 → trainer sent details, book slot */}
      {stage === 'details_requested' && (
        <button onClick={() => onMailModal('mail3')} className={clsx(BTN, 'bg-amber-500 hover:bg-amber-600')}>
          <Calendar className="w-3.5 h-3.5" /> Book Interview Slot
        </button>
      )}

      {/* Stage 3 → slot confirmed, send interview link */}
      {stage === 'slot_booked' && (
        <button onClick={() => onMailModal('mail4')} className={clsx(BTN, 'bg-purple-600 hover:bg-purple-700')}>
          <Calendar className="w-3.5 h-3.5" /> Send Interview Link
        </button>
      )}

      {/* Stage 4 → interview done, select or reject */}
      {stage === 'interview_scheduled' && (
        <>
          <button onClick={() => onMailModal('mail5_ok')} className={clsx(BTN, 'bg-emerald-600 hover:bg-emerald-700')}>
            <PartyPopper className="w-3.5 h-3.5" /> Send Selection Mail
          </button>
          <button onClick={() => onMailModal('mail5_no')} className={clsx(BTN, 'bg-red-500 hover:bg-red-600')}>
            <ThumbsDown className="w-3.5 h-3.5" /> Send Rejection Mail
          </button>
        </>
      )}
    </div>
  )
}

// ─── Trainer Card ─────────────────────────────────────────────────────────────
function TrainerCard({ trainer, rank, state, req, onStatusUpdate }) {
  const stage = state?.status || 'pending'
  const stageInfo = STAGES[stage] || STAGES.pending
  const [mailModal, setMailModal] = useState(null)
  const [showThread, setShowThread] = useState(false)

  return (
    <>
      {mailModal && (
        <MailModal trainer={trainer} req={req} mailType={mailModal}
          onClose={() => setMailModal(null)}
          onSent={(nextStage) => { onStatusUpdate(trainer.trainer_id, nextStage); setMailModal(null) }} />
      )}
      {showThread && <ThreadModal trainer={trainer} req={req} onClose={() => setShowThread(false)} />}

      <div className={clsx('bg-white rounded-2xl border p-4 transition-all hover:shadow-md',
        stage === 'selected' ? 'border-emerald-300 bg-emerald-50/30' :
        stage === 'rejected' ? 'border-red-200 bg-red-50/10' :
        'border-slate-200'
      )}>
        <div className="flex items-start gap-3">
          {/* Rank */}
          <div className={clsx('w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 font-bold text-sm',
            rank === 1 ? 'bg-amber-100 text-amber-700' :
            rank === 2 ? 'bg-slate-200 text-slate-600' :
            rank === 3 ? 'bg-orange-100 text-orange-600' : 'bg-slate-100 text-slate-500'
          )}>{rank}</div>

          {/* Info */}
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
            </div>

            <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500">
              {trainer.email    && <span className="flex items-center gap-1"><Mail  className="w-3 h-3" />{trainer.email}</span>}
              {trainer.phone    && <span className="flex items-center gap-1"><Phone className="w-3 h-3" />{trainer.phone}</span>}
              {trainer.location && <span className="flex items-center gap-1"><MapPin className="w-3 h-3" />{trainer.location}</span>}
              {(trainer.experience_raw || trainer.experience_years) && (
                <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{trainer.experience_raw || `${trainer.experience_years} yrs`}</span>
              )}
            </div>

            {trainer.skills?.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {trainer.skills.slice(0,5).map((s,i)=>(
                  <span key={i} className="px-2 py-0.5 rounded-full text-xs bg-blue-50 text-blue-700 border border-blue-100">{s}</span>
                ))}
                {trainer.skills.length>5 && <span className="px-2 py-0.5 rounded-full text-xs bg-slate-100 text-slate-500">+{trainer.skills.length-5}</span>}
              </div>
            )}

            {/* Progress bar */}
            <StepBar stage={stage} />

            {/* Action buttons */}
            <ActionButtons stage={stage} trainer={trainer} req={req}
              onMailModal={setMailModal} onStatusUpdate={onStatusUpdate} />
          </div>

          {/* Thread button always visible */}
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
  const [reqs, setReqs]               = useState([])
  const [selectedReq, setSelectedReq] = useState(null)
  const [trainers, setTrainers]       = useState([])
  const [states, setStates]           = useState({})
  const [loadingReqs, setLoadingReqs]         = useState(false)
  const [loadingTrainers, setLoadingTrainers] = useState(false)

  useEffect(() => {
    setLoadingReqs(true)
    getRequirements().then(r => setReqs(r.data.requirements || [])).catch(()=>{}).finally(()=>setLoadingReqs(false))
  }, [])

  useEffect(() => {
    if (!selectedReq) return
    setLoadingTrainers(true)
    setTrainers([])
    getShortlist(selectedReq.requirement_id)
      .then(r => {
        const list = r.data.top_trainers || r.data.trainers || []
        setTrainers(list)
        setStates(getLS(`sl_v2_${selectedReq.requirement_id}`) || {})
      })
      .catch(() => toast.error('Could not load shortlist'))
      .finally(() => setLoadingTrainers(false))
  }, [selectedReq])

  const handleStatusUpdate = (trainerId, newStage) => {
    const newStates = { ...states, [trainerId]: { status: newStage } }
    setStates(newStates)
    if (selectedReq) setLS(`sl_v2_${selectedReq.requirement_id}`, newStates)
  }

  const reload = () => {
    if (!selectedReq) return
    setLoadingTrainers(true)
    getShortlist(selectedReq.requirement_id)
      .then(r => setTrainers(r.data.top_trainers || r.data.trainers || []))
      .catch(()=>{})
      .finally(()=>setLoadingTrainers(false))
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <Users className="w-6 h-6 text-blue-500" /> Shortlist
        </h1>
        <p className="text-sm text-slate-500 mt-0.5">
          5-stage pipeline — send the right email at the right time to each trainer
        </p>
      </div>

      {/* Pipeline legend */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5" /> Pipeline Stages
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {[
            { n:'1', label:'Send Shortlist Mail',     color:'bg-blue-600' },
            { n:'2', label:'Request Trainer Details', color:'bg-indigo-600' },
            { n:'3', label:'Book Interview Slot',     color:'bg-amber-500' },
            { n:'4', label:'Send Interview Link',     color:'bg-purple-600' },
            { n:'5a',label:'Selection Mail + ToC',    color:'bg-emerald-600' },
            { n:'5b',label:'Rejection Mail',          color:'bg-red-500' },
          ].map(s => (
            <div key={s.n} className="flex items-center gap-2">
              <span className={clsx('w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0', s.color)}>{s.n}</span>
              <span className="text-xs text-slate-600">{s.label}</span>
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
                <button key={r.requirement_id} onClick={() => setSelectedReq(r)}
                  className="flex items-center gap-3 p-3 rounded-xl border bg-white border-slate-200 hover:border-blue-300 hover:bg-blue-50 text-left transition-all group">
                  <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                    <Star className="w-4 h-4 text-blue-500" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-sm truncate text-slate-800">{r.technology_needed}</p>
                    <p className="text-xs text-slate-400 truncate">{r.requirement_id} · Top {r.top_n}</p>
                  </div>
                  <ChevronRight className="w-4 h-4 opacity-30 group-hover:opacity-70 flex-shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {/* Header */}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h2 className="text-lg font-bold text-slate-900">
                Shortlisted for: <span className="text-blue-600">{selectedReq.technology_needed}</span>
              </h2>
              <p className="text-xs text-slate-400">{selectedReq.requirement_id} · Top {selectedReq.top_n}</p>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setSelectedReq(null)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition-all">
                <ChevronLeft className="w-3.5 h-3.5" /> Back
              </button>
              <button onClick={reload} disabled={loadingTrainers}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition-all">
                <RefreshCw className={clsx('w-3.5 h-3.5', loadingTrainers && 'animate-spin')} /> Refresh
              </button>
            </div>
          </div>

          {/* Status legend */}
          <div className="flex flex-wrap gap-2">
            {Object.entries(STAGES).map(([k,v]) => (
              <span key={k} className={clsx('px-2 py-1 rounded-full text-xs font-semibold', v.color)}>{v.label}</span>
            ))}
          </div>

          {/* Trainer cards */}
          {loadingTrainers ? (
            <div className="space-y-3">
              {[...Array(4)].map((_,i) => (
                <div key={i} className="bg-white rounded-2xl border border-slate-200 p-4 animate-pulse flex gap-3">
                  <div className="w-9 h-9 rounded-xl bg-slate-100 flex-shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-slate-100 rounded w-1/3" />
                    <div className="h-3 bg-slate-100 rounded w-1/2" />
                    <div className="h-3 bg-slate-100 rounded w-1/4" />
                  </div>
                </div>
              ))}
            </div>
          ) : trainers.length === 0 ? (
            <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center">
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
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
