import { useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  CalendarCheck,
  Clock,
  Copy,
  ExternalLink,
  CalendarDays,
  FileText,
  Link2,
  Loader2,
  Mail,
  Mic,
  MicOff,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  UserRound,
  Users,
  Video,
} from 'lucide-react'
import api from '../utils/api'

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition

const SCHEDULE_ENDPOINTS = [
  '/interview-schedules',
  '/interview-reminders/interview-schedules',
]

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function parseMeetingDateText(value) {
  const text = String(value || '').trim()
  if (!text) return 0
  const normalized = text
    .replace(/\*\*/g, '')
    .replace(/\bInterview Date\s*&\s*Time\b\s*:?\s*/i, '')
    .trim()
  const match = normalized.match(
    /\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b[^0-9]*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?/i
  )
  if (!match) return 0
  const day = Number(match[1])
  const month = Number(match[2])
  const year = Number(match[3].length === 2 ? `20${match[3]}` : match[3])
  let hour = Number(match[4])
  const minute = Number(match[5] || 0)
  const meridiem = String(match[6] || '').toUpperCase()
  if (meridiem === 'PM' && hour < 12) hour += 12
  if (meridiem === 'AM' && hour === 12) hour = 0
  const date = new Date(year, month - 1, day, hour, minute, 0, 0)
  const time = date.getTime()
  return Number.isNaN(time) ? 0 : time
}

function meetingStartTime(item = {}) {
  const raw = meetingTime(item)
  const parsed = raw ? new Date(raw).getTime() : 0
  if (parsed && !Number.isNaN(parsed)) return parsed
  return parseMeetingDateText(item.date_time_text || item.interview_date || '')
}

function meetingTime(item = {}) {
  return item.start_iso || item.interview_at || item.sent_at || item.created_at || ''
}

function meetingState(item = {}) {
  if (item.reschedule_requested || String(item.slot_status || '').includes('reschedule') || String(item.pipeline_status || '').includes('reschedule')) {
    return 'reschedule'
  }
  const time = meetingStartTime(item)
  if (!time) return 'pending'
  const diff = time - Date.now()
  if (diff > 5 * 60 * 1000) return 'upcoming'
  if (diff > -90 * 60 * 1000) return 'starting'
  return 'completed'
}

function normalizeSchedule(item = {}) {
  const calendar = item.calendar_event || {}
  const isClientMail = String(item.mail_type || '').startsWith('client_')
  const email = item.trainer_email || item.email || item.to_email || ''
  return {
    ...item,
    domain: item.domain || item.technology || item.technology_needed || item.subject || 'Training',
    client_name: item.client_name || item.client_company || (isClientMail ? 'Client' : ''),
    client_email: item.client_email || (isClientMail ? item.to_email : ''),
    trainer_name: item.trainer_name || item.name || '',
    trainer_email: item.trainer_email || (!isClientMail ? email : ''),
    date_time_text: item.date_time_text || item.interview_date || '',
    meet_link: item.meet_link || item.interview_link || calendar.meet_link || calendar.html_link || '',
    start_iso: item.start_iso || item.interview_at || calendar.start || item.sent_at || item.created_at,
    timezone: item.timezone || calendar.timezone || '',
    calendar_event_id: item.calendar_event_id || calendar.event_id || item.email_id || '',
    reschedule_requested: Boolean(item.reschedule_requested),
    reschedule_requested_by: item.reschedule_requested_by || '',
    reschedule_request_text: item.reschedule_request_text || '',
    slot_status: item.slot_status || '',
    pipeline_status: item.pipeline_status || '',
  }
}

function openMeeting(link) {
  if (!link) {
    toast.error('Meeting link is not available yet')
    return
  }
  window.open(link, '_blank', 'noopener,noreferrer')
}

function meetingKey(item = {}) {
  return `${item.email_id || ''}-${item.calendar_event_id || ''}-${item.requirement_id || ''}-${item.trainer_id || ''}-${item.date_time_text || item.start_iso || ''}`
}

function defaultRescheduleNote(item = {}) {
  return `Hi ${item.trainer_name || 'Trainer'},

The client has requested to reschedule the interview for ${item.domain || 'the training requirement'}.

Client proposed slots:
- [Date and time 1]
- [Date and time 2]
- [Date and time 3]

Please confirm which slot works for you. Once confirmed, we will share the updated meeting link with both you and the client.

Regards,
Clahan Technologies`
}

function ReschedulePanel({ selected, onDone }) {
  const [slotsText, setSlotsText] = useState('')
  const [trainerNote, setTrainerNote] = useState('')
  const [finalDate, setFinalDate] = useState('')
  const [meetLink, setMeetLink] = useState('')
  const [sendingTrainer, setSendingTrainer] = useState(false)
  const [sendingFinal, setSendingFinal] = useState(false)

  useEffect(() => {
    setSlotsText('')
    setTrainerNote(defaultRescheduleNote(selected || {}))
    setFinalDate(selected?.date_time_text || '')
    setMeetLink(selected?.meet_link || '')
  }, [selected?.email_id, selected?.calendar_event_id])

  const sendClientSlotsToTrainer = async () => {
    if (!selected?.requirement_id || !selected?.trainer_id) {
      toast.error('Requirement or trainer id is missing')
      return
    }
    if (!selected?.trainer_email) {
      toast.error('Trainer email is missing')
      return
    }
    const proposedSlots = slotsText.trim()
    if (!proposedSlots) {
      toast.error('Add the client proposed dates/slots first')
      return
    }

    setSendingTrainer(true)
    try {
      const body = trainerNote.replace(
        '- [Date and time 1]\n- [Date and time 2]\n- [Date and time 3]',
        proposedSlots
      )
      const res = await api.post('/shortlists/send-mail', {
        requirement_id: selected.requirement_id,
        trainer_id: selected.trainer_id,
        trainer_name: selected.trainer_name,
        to_email: selected.trainer_email,
        subject: `Reschedule Request - ${selected.domain || 'Interview'}`,
        body,
        mail_type: 'mail4_reschedule_request',
      })
      if (!res.data?.success) throw new Error(res.data?.error || 'Could not send reschedule request')
      toast.success('Client proposed slots sent to trainer')
      onDone?.()
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Could not send to trainer')
    } finally {
      setSendingTrainer(false)
    }
  }

  const sendFinalReschedule = async () => {
    if (!selected?.requirement_id || !selected?.trainer_id) {
      toast.error('Requirement or trainer id is missing')
      return
    }
    if (!finalDate.trim()) {
      toast.error('Enter the confirmed new date/time')
      return
    }
    if (!meetLink.trim()) {
      toast.error('Paste the new Google Meet link')
      return
    }

    setSendingFinal(true)
    try {
      const res = await api.post('/shortlists/send-interview-link', {
        requirement_id: selected.requirement_id,
        trainer_id: selected.trainer_id,
        trainer_name: selected.trainer_name,
        to_email: selected.trainer_email,
        client_email: selected.client_email,
        client_name: selected.client_name || selected.client_company,
        technology: selected.domain,
        interview_date: finalDate.trim(),
        date_time: finalDate.trim(),
        interview_link: meetLink.trim(),
        platform: 'Google Meet',
      })
      if (!res.data?.success) throw new Error(res.data?.error || 'Could not send updated interview link')
      toast.success('Updated meeting link sent to client and trainer')
      onDone?.()
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Could not send updated link')
    } finally {
      setSendingFinal(false)
    }
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-bold text-amber-950">Reschedule Workflow</p>
          <p className="mt-1 text-xs font-semibold text-amber-700">Use when client asks for new dates or trainer says busy.</p>
        </div>
        <CalendarDays className="h-5 w-5 text-amber-600" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div className="rounded-lg border border-amber-200 bg-white p-3">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Client Proposed Slots</p>
          <textarea
            value={slotsText}
            onChange={e => setSlotsText(e.target.value)}
            rows={4}
            placeholder={'- 12 Aug 2026, 11:00 AM IST\n- 13 Aug 2026, 3:00 PM IST\n- 14 Aug 2026, 5:00 PM IST'}
            className="mt-2 w-full rounded-lg border border-slate-200 p-3 text-sm outline-none focus:border-blue-400"
          />
          <textarea
            value={trainerNote}
            onChange={e => setTrainerNote(e.target.value)}
            rows={7}
            className="mt-2 w-full rounded-lg border border-slate-200 p-3 text-sm outline-none focus:border-blue-400"
          />
          <button onClick={sendClientSlotsToTrainer} disabled={sendingTrainer} className="btn-secondary mt-3 w-full justify-center text-sm">
            {sendingTrainer ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
            Send Slots To Trainer
          </button>
        </div>

        <div className="rounded-lg border border-emerald-200 bg-white p-3">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Trainer Accepted Slot</p>
          <input
            value={finalDate}
            onChange={e => setFinalDate(e.target.value)}
            placeholder="Confirmed date/time"
            className="mt-2 h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
          />
          <input
            value={meetLink}
            onChange={e => setMeetLink(e.target.value)}
            placeholder="Google Meet link"
            className="mt-2 h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
          />
          <button onClick={sendFinalReschedule} disabled={sendingFinal} className="btn-primary mt-3 w-full justify-center text-sm">
            {sendingFinal ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
            Send Updated Link To Both
          </button>
        </div>
      </div>
    </div>
  )
}

function notesPayload(selected, transcript) {
  const emailKey = [selected?.email_id, selected?.calendar_event_id].filter(Boolean).join('-')
  const key = emailKey || selected?.reminder_id || 'interview'
  return {
    schedule_key: key,
    transcript,
    trainer_name: selected?.trainer_name || '',
    trainer_email: selected?.trainer_email || '',
    client_name: selected?.client_name || selected?.client_company || '',
    client_email: selected?.client_email || '',
    domain: selected?.domain || '',
    meeting_link: selected?.meet_link || '',
    meeting_time: selected?.date_time_text || selected?.start_iso || '',
  }
}

function scheduleDraftKey(selected, suffix) {
  const key = notesPayload(selected, '').schedule_key || 'interview'
  return `trainersync:${suffix}:${key}`
}

function assistantPayload(selected, transcript, profileText) {
  const base = notesPayload(selected, transcript)
  return {
    ...base,
    requirement_id: selected?.requirement_id || '',
    trainer_profile: profileText || [
      selected?.trainer_name,
      selected?.trainer_email,
      selected?.domain,
      selected?.summary,
      selected?.bio,
      selected?.resume,
      selected?.extracted_text,
      selected?.combined_text,
    ].filter(Boolean).join('\n'),
  }
}

function AIInterviewAssistant({ selected }) {
  const [open, setOpen] = useState(false)
  const [profileText, setProfileText] = useState('')
  const [notes, setNotes] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setProfileText([
      selected?.trainer_name,
      selected?.trainer_email,
      selected?.domain,
      selected?.summary,
      selected?.bio,
      selected?.resume,
      selected?.extracted_text,
      selected?.combined_text,
    ].filter(Boolean).join('\n'))
    try {
      setNotes(localStorage.getItem(scheduleDraftKey(selected, 'ai_interview_notes')) || '')
    } catch {
      setNotes('')
    }
    setResult(null)
  }, [selected?.email_id, selected?.calendar_event_id, selected?.trainer_id])

  useEffect(() => {
    if (!selected) return
    try {
      localStorage.setItem(scheduleDraftKey(selected, 'ai_interview_notes'), notes)
    } catch {
      // Draft autosave is best-effort.
    }
  }, [notes, selected])

  const runAssistant = async () => {
    if (!selected) return
    setLoading(true)
    try {
      const res = await api.post('/interview-schedules/assistant', assistantPayload(selected, notes, profileText))
      setResult(res.data)
      toast.success('AI interview assistant prepared')
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Could not generate interview assistant')
    } finally {
      setLoading(false)
    }
  }

  const copyQuestions = async () => {
    const q = result?.questions
    if (!q) {
      await runAssistant()
      return
    }
    const lines = [
      q.summary,
      '',
      'Focus Areas',
      ...(q.focus_areas || []).map(item => `- ${item}`),
      '',
      'Technical Questions',
      ...(q.technical_questions || []).map((item, index) => `${index + 1}. ${item}`),
      '',
      'Trainer Profile Questions',
      ...(q.profile_questions || []).map((item, index) => `${index + 1}. ${item}`),
      '',
      'Delivery Questions',
      ...(q.delivery_questions || []).map((item, index) => `${index + 1}. ${item}`),
      '',
      'Client Fit Questions',
      ...(q.client_fit_questions || []).map((item, index) => `${index + 1}. ${item}`),
    ]
    await navigator.clipboard.writeText(lines.join('\n'))
    toast.success('Interview questions copied')
  }

  const copySummary = async () => {
    const summary = result?.interview_summary
    if (!summary?.summary && notes.trim()) {
      await runAssistant()
      return
    }
    if (!summary?.summary) {
      toast.error('Add interview notes first')
      return
    }
    const lines = [
      `Summary: ${summary.summary}`,
      `Recommendation: ${summary.recommendation}`,
      '',
      'Strengths',
      ...(summary.strengths || []).map(item => `- ${item}`),
      '',
      'Concerns',
      ...(summary.concerns || []).map(item => `- ${item}`),
      '',
      'Next Steps',
      ...(summary.next_steps || []).map(item => `- ${item}`),
    ]
    await navigator.clipboard.writeText(lines.join('\n'))
    toast.success('Interview summary copied')
  }

  const questions = result?.questions
  const summary = result?.interview_summary

  return (
    <div className="rounded-lg border border-sky-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-bold text-slate-950">AI Interview Assistant</p>
          <p className="mt-1 text-xs text-slate-500">Generate client-specific interview questions and summarize interview notes for selection feedback.</p>
        </div>
        <button type="button" onClick={() => setOpen(value => !value)} className="rounded-full bg-sky-50 px-2.5 py-1 text-xs font-bold text-sky-700">
          {open ? 'Hide' : 'Open'} AI
        </button>
      </div>

      {!open && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
          <span className="rounded-lg bg-slate-50 px-2.5 py-1 font-semibold">Questions</span>
          <span className="rounded-lg bg-slate-50 px-2.5 py-1 font-semibold">Scorecard</span>
          <span className="rounded-lg bg-slate-50 px-2.5 py-1 font-semibold">Summary</span>
        </div>
      )}

      {open && (
      <>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div>
          <label className="text-xs font-bold uppercase tracking-wide text-slate-400">Trainer profile / context</label>
          <textarea
            value={profileText}
            onChange={e => setProfileText(e.target.value)}
            rows={5}
            placeholder="Paste trainer resume/profile highlights if not already captured..."
            className="mt-2 w-full rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 outline-none focus:border-blue-400 focus:bg-white"
          />
        </div>
        <div>
          <label className="text-xs font-bold uppercase tracking-wide text-slate-400">Interview notes / transcript</label>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={5}
            placeholder="Paste interview notes here to summarize after the call..."
            className="mt-2 w-full rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 outline-none focus:border-blue-400 focus:bg-white"
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={runAssistant} disabled={loading} className="btn-primary text-sm disabled:opacity-60">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          Generate Questions & Summary
        </button>
        <button type="button" onClick={copyQuestions} className="btn-secondary text-sm">
          <Copy className="h-4 w-4" />
          Copy Questions
        </button>
        <button type="button" onClick={copySummary} className="btn-secondary text-sm">
          <FileText className="h-4 w-4" />
          Copy Summary
        </button>
      </div>

      {questions && (
        <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_280px]">
          <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
            <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Technical Questions</p>
            <ol className="mt-2 space-y-2 text-sm leading-6 text-slate-700">
              {(questions.technical_questions || []).map((item, index) => <li key={item}>{index + 1}. {item}</li>)}
            </ol>
          </div>
          <div className="space-y-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Focus Areas</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(questions.focus_areas || []).map(item => <span key={item} className="badge-blue text-[11px]">{item}</span>)}
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white p-3">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Scorecard</p>
              <div className="mt-2 space-y-2">
                {(questions.scorecard || []).map(item => (
                  <div key={item.area} className="rounded-lg bg-slate-50 px-3 py-2 text-xs">
                    <div className="flex justify-between gap-2 font-bold text-slate-800">
                      <span>{item.area}</span>
                      <span>{item.weight}%</span>
                    </div>
                    <p className="mt-1 text-slate-500">{item.signal}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {summary?.summary && (
        <div className="mt-3 grid gap-3 lg:grid-cols-3">
          {[
            ['Strengths', summary.strengths, 'emerald'],
            ['Concerns', summary.concerns, 'amber'],
            ['Next Steps', summary.next_steps, 'blue'],
          ].map(([title, items, tone]) => (
            <div key={title} className={clsx(
              'rounded-lg border p-3',
              tone === 'emerald' ? 'border-emerald-200 bg-emerald-50' : tone === 'amber' ? 'border-amber-200 bg-amber-50' : 'border-blue-200 bg-blue-50'
            )}>
              <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-600">{title}</p>
              <ul className="space-y-1 text-xs leading-5 text-slate-700">
                {(items || []).map(item => <li key={item}>- {item}</li>)}
              </ul>
            </div>
          ))}
          <div className="rounded-lg border border-slate-200 bg-white p-3 lg:col-span-3">
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Recommendation</p>
            <p className="mt-2 text-sm font-semibold text-slate-800">{summary.recommendation}</p>
          </div>
        </div>
      )}
      </>
      )}
    </div>
  )
}

function MeetingNotesAssistant({ selected }) {
  const [open, setOpen] = useState(false)
  const [listening, setListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [analysis, setAnalysis] = useState(null)
  const [documentText, setDocumentText] = useState('')
  const [savedDocument, setSavedDocument] = useState(null)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)
  const recognitionRef = useMemo(() => ({ current: null }), [])
  const supported = Boolean(SpeechRecognition)

  useEffect(() => {
    setListening(false)
    try {
      setTranscript(localStorage.getItem(scheduleDraftKey(selected, 'meeting_notes')) || '')
    } catch {
      setTranscript('')
    }
    setAnalysis(null)
    setDocumentText('')
    setSavedDocument(null)
    recognitionRef.current?.stop?.()
  }, [selected?.email_id, selected?.calendar_event_id, recognitionRef])

  useEffect(() => {
    if (!selected) return
    try {
      localStorage.setItem(scheduleDraftKey(selected, 'meeting_notes'), transcript)
    } catch {
      // Draft autosave is best-effort.
    }
  }, [transcript, selected])

  const start = async () => {
    if (!supported) {
      toast.error('Voice capture is not supported in this browser. Type notes manually.')
      return
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      toast.error('This browser cannot request microphone access. Open the app in Chrome on localhost, or type notes manually.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach(track => track.stop())
    } catch (error) {
      const blocked = error?.name === 'NotAllowedError' || error?.name === 'SecurityError'
      const missing = error?.name === 'NotFoundError' || error?.name === 'DevicesNotFoundError'
      toast.error(
        blocked
          ? 'Microphone is blocked by Chrome. Click the lock/tune icon in the address bar, set Microphone to Allow, reload, then start notes again.'
          : missing
            ? 'No microphone was found. Connect/enable a microphone, or type notes manually.'
            : error?.message || 'Could not access microphone. You can type/paste notes manually.'
      )
      return
    }
    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-IN'
    recognition.onresult = event => {
      const text = Array.from(event.results).map(result => result[0]?.transcript || '').join(' ')
      setTranscript(text.trim())
    }
    recognition.onerror = event => {
      const message =
        event.error === 'not-allowed'
          ? 'Microphone access is blocked. Allow microphone permission for this site, or type/paste meeting notes manually.'
          : event.error === 'audio-capture'
            ? 'No microphone was found. Connect/enable a microphone, or type notes manually.'
            : event.error === 'network'
              ? 'Voice capture network error. You can type/paste notes and still analyze/save them.'
              : event.error || 'Could not capture meeting audio'
      toast.error(message)
      setListening(false)
    }
    recognition.onend = () => setListening(false)
    recognitionRef.current = recognition
    setListening(true)
    recognition.start()
  }

  const stop = () => {
    recognitionRef.current?.stop?.()
    setListening(false)
  }

  const analyze = async () => {
    if (!transcript.trim()) {
      toast.error('Add meeting notes or start voice capture first')
      return null
    }
    setLoading(true)
    try {
      const res = await api.post('/interview-schedules/notes/analyze', notesPayload(selected, transcript))
      setAnalysis(res.data.analysis)
      setDocumentText(res.data.document_text || '')
      return res.data
    } catch (error) {
      toast.error(error.message || 'Could not analyze meeting notes')
      return null
    } finally {
      setLoading(false)
    }
  }

  const saveDocument = async () => {
    if (!transcript.trim()) {
      toast.error('Add meeting notes before saving')
      return
    }
    setSaving(true)
    try {
      const res = await api.post('/interview-schedules/notes', notesPayload(selected, transcript))
      setAnalysis(res.data.document?.analysis || null)
      setDocumentText(res.data.document?.document_text || '')
      setSavedDocument(res.data.document || null)
      toast.success(`Meeting document saved: ${res.data.document?.document_id}`)
    } catch (error) {
      toast.error(error.message || 'Could not save meeting document')
    } finally {
      setSaving(false)
    }
  }

  const copyDocument = async () => {
    const text = documentText || (await analyze())?.document_text
    if (!text) return
    await navigator.clipboard.writeText(text)
    toast.success('Meeting document copied')
  }

  return (
    <div className="rounded-lg border border-blue-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-bold text-slate-950">Meeting Notes Assistant</p>
          <p className="mt-1 text-xs text-slate-500">Start this when the meeting begins. It captures transcript, key points, actions, and saves a document.</p>
        </div>
        <div className="flex gap-2">
          <span className={clsx('rounded-full px-2.5 py-1 text-xs font-bold', listening ? 'bg-red-50 text-red-600' : 'bg-slate-100 text-slate-500')}>
            {listening ? 'Listening' : transcript ? 'Draft saved' : 'Ready'}
          </span>
          <button type="button" onClick={() => setOpen(value => !value)} className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">
            {open ? 'Hide' : 'Open'} Notes
          </button>
        </div>
      </div>

      {!open && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
          <span className="rounded-lg bg-slate-50 px-2.5 py-1 font-semibold">{transcript ? 'Draft autosaved' : 'No notes yet'}</span>
          <span className="rounded-lg bg-slate-50 px-2.5 py-1 font-semibold">Analyze</span>
          <span className="rounded-lg bg-slate-50 px-2.5 py-1 font-semibold">Save document</span>
        </div>
      )}

      {open && (
      <>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={listening ? stop : start} className={clsx('btn-primary text-sm', listening && 'bg-red-600 hover:bg-red-700')}>
          {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          {listening ? 'Stop Notes' : 'Start Meeting Notes'}
        </button>
        <button type="button" onClick={analyze} disabled={loading} className="btn-secondary text-sm disabled:opacity-60">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          Analyze
        </button>
        <button type="button" onClick={saveDocument} disabled={saving} className="btn-secondary text-sm disabled:opacity-60">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save Document
        </button>
        <button type="button" onClick={copyDocument} className="btn-secondary text-sm">
          <Copy className="h-4 w-4" />
          Copy Document
        </button>
      </div>

      <textarea
        value={transcript}
        onChange={e => { setTranscript(e.target.value); setAnalysis(null); setDocumentText(''); setSavedDocument(null) }}
        rows={6}
        placeholder="Meeting transcript or manual notes will appear here..."
        className="mt-3 w-full rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 outline-none focus:border-blue-400 focus:bg-white"
      />

      {analysis && (
        <div className="mt-3 grid gap-3 lg:grid-cols-3">
          {[
            ['Key Points', analysis.key_points],
            ['Decisions', analysis.decisions],
            ['Action Items', analysis.action_items],
          ].map(([title, items]) => (
            <div key={title} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">{title}</p>
              <ul className="space-y-1 text-xs text-slate-700">
                {(items || []).map(item => <li key={item}>- {item}</li>)}
              </ul>
            </div>
          ))}
        </div>
      )}

      {documentText && (
        <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <summary className="cursor-pointer text-sm font-bold text-slate-800"><FileText className="mr-1 inline h-4 w-4" />Saved Document Preview</summary>
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap font-sans text-xs leading-5 text-slate-700">{documentText}</pre>
        </details>
      )}

      {savedDocument?.document_url && (
        <div className="mt-3 flex flex-wrap gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
          <a href={savedDocument.document_url} target="_blank" rel="noreferrer" className="btn-primary text-sm">
            <FileText className="h-4 w-4" />
            Open Document
          </a>
          {savedDocument.download_url && (
            <a href={savedDocument.download_url} className="btn-secondary bg-white text-sm">
              Download Text
            </a>
          )}
          {savedDocument.excel_url && (
            <a href={savedDocument.excel_url} className="btn-secondary bg-white text-sm">
              Download Excel
            </a>
          )}
          <span className="self-center text-xs font-semibold text-emerald-700">{savedDocument.document_id}</span>
        </div>
      )}
      </>
      )}
    </div>
  )
}

function ContactLine({ icon: Icon, label, value }) {
  return (
    <div className="flex min-w-0 items-center gap-2 text-sm">
      <Icon className="h-4 w-4 shrink-0 text-slate-400" />
      <span className="shrink-0 font-semibold text-slate-500">{label}</span>
      <span className="min-w-0 truncate text-slate-950">{value || '-'}</span>
    </div>
  )
}

function StepLabel({ step, title, icon: Icon }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-[11px] font-black text-white">{step}</span>
      <Icon className="h-4 w-4 text-blue-600" />
      <p className="text-xs font-black uppercase tracking-wide text-slate-600">{title}</p>
    </div>
  )
}

function MeetingRow({ item, active, onClick }) {
  const state = meetingState(item)
  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full rounded-lg border p-3 text-left transition hover:border-blue-200 hover:bg-white',
        active ? 'border-blue-300 bg-blue-50 ring-1 ring-blue-100' : 'border-slate-200 bg-white'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-950">{item.trainer_name || item.trainer_email || 'Selected trainer'}</p>
          <p className="mt-1 truncate text-xs font-semibold text-slate-500">{item.domain}</p>
        </div>
        <span className={clsx(
          'rounded-lg px-2 py-1 text-xs font-bold capitalize',
          state === 'starting' ? 'bg-emerald-50 text-emerald-700' :
            state === 'upcoming' ? 'bg-blue-50 text-blue-700' :
              state === 'reschedule' ? 'bg-amber-50 text-amber-700' :
              state === 'completed' ? 'bg-slate-100 text-slate-500' :
                'bg-amber-50 text-amber-700'
        )}>
          {state}
        </span>
      </div>
      <p className="mt-3 truncate text-xs font-semibold text-slate-600">{item.date_time_text || formatDate(item.start_iso)}</p>
      <p className="mt-1 truncate text-xs text-slate-400">{item.client_name || item.client_email || 'Client'}</p>
    </button>
  )
}

export default function InterviewSchedules() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('upcoming')
  const [selectedKey, setSelectedKey] = useState('')
  const [notified, setNotified] = useState({})
  const [hostPrompt, setHostPrompt] = useState(null)
  const [showMeetPreview, setShowMeetPreview] = useState(false)
  const [screenCaptureActive, setScreenCaptureActive] = useState(false)
  const meetingPreviewRef = useRef(null)
  const meetingStreamRef = useRef(null)

  const load = async () => {
    setLoading(true)
    try {
      let lastError
      for (const [index, endpoint] of SCHEDULE_ENDPOINTS.entries()) {
        try {
          const res = await api.get(endpoint, { params: { limit: 200 } })
          const schedules = (res.data.schedules || []).map(normalizeSchedule)
          if (schedules.length || index === SCHEDULE_ENDPOINTS.length - 1) {
            setItems(schedules)
            setSelectedKey(prev => prev || `${schedules[0]?.email_id || ''}-${schedules[0]?.calendar_event_id || ''}`)
            return
          }
        } catch (err) {
          lastError = err
        }
      }
      throw lastError
    } catch (err) {
      toast.error(err.message || 'Could not load interview schedules')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {})
    }
  }, [])

  useEffect(() => {
    const timer = setInterval(() => {
      const nextNotified = { ...notified }
      items.forEach(item => {
        const time = meetingStartTime(item)
        if (!time) return
        const key = meetingKey(item)
        const diff = time - Date.now()
        if (diff > 0 && diff <= 5 * 60 * 1000 && !nextNotified[`${key}:reminder`]) {
          nextNotified[`${key}:reminder`] = true
          const title = 'Meeting starts in 5 minutes'
          const body = `${item.trainer_name || 'Trainer'} with ${item.client_name || item.client_email || 'client'}`
          toast.success(`${title}: ${body}`, { duration: 10000 })
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(title, { body })
          }
        }
        if (diff <= 0 && diff > -2 * 60 * 1000 && !nextNotified[`${key}:start`]) {
          nextNotified[`${key}:start`] = true
          setSelectedKey(`${item.email_id || ''}-${item.calendar_event_id || ''}`)
          setFilter('starting')
          setHostPrompt(item)
          setShowMeetPreview(false)
          const title = 'It is time to start meeting'
          const body = `${item.trainer_name || 'Trainer'} interview is starting now`
          toast.success(`${title}: ${body}`, { duration: 15000 })
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(title, { body })
          }
          if (item.meet_link) {
            const opened = window.open(item.meet_link, '_blank', 'noopener,noreferrer')
            if (!opened) {
              toast.error('Browser blocked auto-open. Click Start Hosting in the popup.')
            }
          }
        }
      })
      setNotified(nextNotified)
    }, 30000)
    return () => clearInterval(timer)
  }, [items, notified])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter(item => {
      if (filter !== 'all' && meetingState(item) !== filter) return false
      if (!term) return true
      return [
        item.domain,
        item.requirement_id,
        item.client_name,
        item.client_email,
        item.trainer_name,
        item.trainer_email,
        item.date_time_text,
      ].some(value => String(value || '').toLowerCase().includes(term))
    })
  }, [items, query, filter])

  const selected = useMemo(
    () => filtered.find(item => `${item.email_id || ''}-${item.calendar_event_id || ''}` === selectedKey) || filtered[0] || null,
    [filtered, selectedKey]
  )

  useEffect(() => {
    if (meetingStreamRef.current) {
      meetingStreamRef.current.getTracks().forEach(track => track.stop())
      meetingStreamRef.current = null
    }
    setScreenCaptureActive(false)
  }, [selected?.email_id, selected?.calendar_event_id])

  const stopMeetingCapture = () => {
    if (meetingStreamRef.current) {
      meetingStreamRef.current.getTracks().forEach(track => track.stop())
      meetingStreamRef.current = null
    }
    if (meetingPreviewRef.current) {
      meetingPreviewRef.current.srcObject = null
    }
    setScreenCaptureActive(false)
  }

  const startMeetingCapture = async () => {
    if (!navigator.mediaDevices?.getDisplayMedia) {
      toast.error('Screen capture is not supported in this browser. Open Meet in a new tab and keep this page open for notes.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: true,
      })
      stopMeetingCapture()
      meetingStreamRef.current = stream
      stream.getVideoTracks()[0]?.addEventListener('ended', stopMeetingCapture)
      if (meetingPreviewRef.current) {
        meetingPreviewRef.current.srcObject = stream
        await meetingPreviewRef.current.play().catch(() => {})
      }
      setScreenCaptureActive(true)
      toast.success('Meeting tab is visible in the interview page')
    } catch (error) {
      toast.error(error?.name === 'NotAllowedError' ? 'Screen capture was cancelled or blocked.' : error?.message || 'Could not show meeting in the page')
    }
  }

  const counts = {
    all: items.length,
    upcoming: items.filter(item => meetingState(item) === 'upcoming').length,
    starting: items.filter(item => meetingState(item) === 'starting').length,
    reschedule: items.filter(item => meetingState(item) === 'reschedule').length,
    completed: items.filter(item => meetingState(item) === 'completed').length,
  }

  return (
    <div className="min-w-0 space-y-5 overflow-x-hidden animate-fade-in">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-bold uppercase tracking-wide text-blue-700 shadow-sm">
            <CalendarCheck className="h-3.5 w-3.5" /> Interview Meetings
          </div>
          <h1 className="mt-3 page-title">Interview Meeting Board</h1>
          <p className="mt-1 text-sm text-slate-500">Selected trainers, client/trainer emails, meeting date, and host join controls.</p>
        </div>
        <button onClick={load} disabled={loading} className="btn-secondary w-fit text-sm">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </button>
      </div>

      {hostPrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4">
          <div className="w-full max-w-[760px] rounded-lg border border-emerald-200 bg-white p-5 shadow-2xl">
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_300px]">
              <div className="flex items-start gap-3">
                <span className="rounded-lg bg-emerald-50 p-2 text-emerald-600">
                  <Video className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold uppercase tracking-wide text-emerald-700">It is time to start meeting</p>
                  <h2 className="mt-1 text-xl font-black text-slate-950">{hostPrompt.trainer_name || 'Trainer interview'}</h2>
                  <p className="mt-1 text-sm text-slate-500">{hostPrompt.domain} · {hostPrompt.date_time_text || formatDate(hostPrompt.start_iso)}</p>
                  <p className="mt-3 text-sm leading-6 text-slate-600">
                    Open the meeting as the Clahan Technologies host account in your browser, then admit the client and trainer from the waiting room.
                  </p>
                  {hostPrompt.meet_link ? (
                    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs font-semibold text-slate-600">
                      <a href={hostPrompt.meet_link} target="_blank" rel="noreferrer" className="break-all underline">{hostPrompt.meet_link}</a>
                    </div>
                  ) : (
                    <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm font-semibold text-amber-800">
                      Meeting link is not available yet.
                    </div>
                  )}
                </div>
              </div>

              <div className="h-[400px] w-[300px] overflow-hidden rounded-lg border border-slate-200 bg-slate-950 shadow-sm">
                {hostPrompt.meet_link && showMeetPreview ? (
                  <iframe
                    title="Google Meet host tab"
                    src={hostPrompt.meet_link}
                    className="h-full w-full bg-white"
                    allow="camera; microphone; fullscreen; display-capture; autoplay"
                  />
                ) : hostPrompt.meet_link ? (
                  <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-center text-sm font-semibold text-white">
                    <Video className="h-8 w-8 text-blue-200" />
                    <p>Preview is paused for faster page performance.</p>
                    <button type="button" onClick={() => setShowMeetPreview(true)} className="rounded-lg bg-white px-3 py-2 text-xs font-bold text-slate-900">
                      Load Preview
                    </button>
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center p-4 text-center text-sm font-semibold text-white">
                    Meeting link pending
                  </div>
                )}
              </div>
            </div>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => { setHostPrompt(null); setShowMeetPreview(false) }} className="btn-secondary text-sm">
                Dismiss
              </button>
              <button
                type="button"
                onClick={() => openMeeting(hostPrompt.meet_link)}
                disabled={!hostPrompt.meet_link}
                className="btn-primary text-sm disabled:opacity-50"
              >
                <Video className="h-4 w-4" />
                Start Hosting
                <ExternalLink className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-5">
        {[
          ['All', counts.all, 'all'],
          ['Upcoming', counts.upcoming, 'upcoming'],
          ['Starting Now', counts.starting, 'starting'],
          ['Reschedule', counts.reschedule, 'reschedule'],
          ['Completed', counts.completed, 'completed'],
        ].map(([label, count, key]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={clsx('rounded-lg border p-4 text-left shadow-sm transition', filter === key ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50')}
          >
            <p className="text-sm font-semibold text-slate-500">{label}</p>
            <p className="mt-1 text-2xl font-bold text-slate-950">{count}</p>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-5 text-sm font-semibold text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading scheduled interviews
        </div>
      ) : (
        <div className="grid min-w-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="min-w-0 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search trainer, client, domain..."
                className="h-11 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </div>
            <p className="mt-4 text-sm font-bold text-slate-950">{filtered.length} selected interview{filtered.length === 1 ? '' : 's'}</p>
            <div className="mt-3 max-h-[72vh] space-y-3 overflow-y-auto pr-1 [scrollbar-gutter:stable]">
              {filtered.length ? filtered.map(item => {
                const key = `${item.email_id || ''}-${item.calendar_event_id || ''}`
                return (
                  <MeetingRow
                    key={key}
                    item={item}
                    active={selected && key === `${selected.email_id || ''}-${selected.calendar_event_id || ''}`}
                    onClick={() => setSelectedKey(key)}
                  />
                )
              }) : (
                <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">
                  No interviews found.
                </div>
              )}
            </div>
          </aside>

          <section className="min-w-0 rounded-lg border border-slate-200 bg-white shadow-sm">
            {!selected ? (
              <div className="flex min-h-[520px] items-center justify-center text-sm text-slate-500">
                Select an interview.
              </div>
            ) : (
              <div className="min-w-0 p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">{selected.domain}</span>
                      {selected.requirement_id && <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">{selected.requirement_id}</span>}
                      <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-bold capitalize text-emerald-700">{meetingState(selected)}</span>
                    </div>
                    <h2 className="mt-3 text-2xl font-bold text-slate-950">{selected.trainer_name || selected.trainer_email || 'Selected Trainer'}</h2>
                    <p className="mt-1 text-sm text-slate-500">{selected.client_name || selected.client_email || 'Client'}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => openMeeting(selected.meet_link)} disabled={!selected.meet_link} className="btn-primary text-sm disabled:opacity-50">
                      <Video className="h-4 w-4" />
                      Start Meeting
                      <ExternalLink className="h-4 w-4" />
                    </button>
                    <button onClick={() => openMeeting(selected.meet_link)} disabled={!selected.meet_link} className="btn-secondary text-sm disabled:opacity-50">
                      <Users className="h-4 w-4" />
                      Host / Admit People
                    </button>
                  </div>
                </div>

                <div className="mt-5 space-y-4">
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <StepLabel step="1" title="Meeting Details" icon={Video} />
                    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
                      <div className="rounded-lg border border-blue-200 bg-white p-4">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Interview Date & Time</p>
                          <Clock className="h-4 w-4 text-blue-600" />
                        </div>
                        <p className="mt-3 text-xl font-black text-slate-950">{selected.date_time_text || formatDate(selected.start_iso)}</p>
                        <p className="mt-1 text-xs font-semibold text-slate-500">{selected.timezone || 'Timezone not captured'}</p>
                      </div>
                      <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
                        <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Host Action</p>
                        <p className="mt-2 text-sm font-semibold text-slate-700">Open meeting as host, then admit client and trainer.</p>
                        <button onClick={() => openMeeting(selected.meet_link)} disabled={!selected.meet_link} className="btn-primary mt-3 w-full justify-center text-sm disabled:opacity-50">
                          <Video className="h-4 w-4" />
                          Start Meeting
                        </button>
                      </div>
                    </div>
                    {selected.meet_link ? (
                      <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">
                        <Link2 className="mr-1 inline h-4 w-4" />
                        <a className="break-all underline" href={selected.meet_link} target="_blank" rel="noreferrer">{selected.meet_link}</a>
                      </div>
                    ) : (
                      <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm font-semibold text-amber-800">
                        <Link2 className="mr-1 inline h-4 w-4" />
                        Meeting link is pending.
                      </div>
                    )}
                    <p className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-xs font-semibold text-slate-500">
                      Reminder notification appears 5 minutes before the interview starts.
                    </p>
                  </div>

                  <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <StepLabel step="2" title="Meeting Window" icon={Video} />
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={startMeetingCapture}
                          disabled={!selected.meet_link}
                          className="btn-primary text-sm disabled:opacity-50"
                        >
                          <Video className="h-4 w-4" />
                          {screenCaptureActive ? 'Change Meet Tab' : 'Share Meet Tab Here'}
                        </button>
                        {screenCaptureActive && (
                          <button type="button" onClick={stopMeetingCapture} className="btn-secondary text-sm">
                            Hide Preview
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => openMeeting(selected.meet_link)}
                          disabled={!selected.meet_link}
                          className="btn-secondary text-sm disabled:opacity-50"
                        >
                          <ExternalLink className="h-4 w-4" />
                          Open in New Tab
                        </button>
                      </div>
                    </div>

                    <div className="mt-3 overflow-hidden rounded-lg border border-slate-200 bg-slate-950">
                      <video
                        ref={meetingPreviewRef}
                        className={clsx('h-[520px] w-full bg-slate-950 object-contain', !screenCaptureActive && 'hidden')}
                        autoPlay
                        muted
                        playsInline
                      />
                      {!screenCaptureActive && (
                        <div className="flex min-h-[360px] flex-col items-center justify-center gap-3 p-6 text-center text-sm font-semibold text-white">
                          <Video className="h-10 w-10 text-blue-200" />
                          <p>{selected.meet_link ? 'Open the Meet tab, then share that tab here to view the live meeting inside this interview page.' : 'Meeting link is pending.'}</p>
                          {selected.meet_link && (
                            <button type="button" onClick={startMeetingCapture} className="rounded-lg bg-white px-4 py-2 text-xs font-bold text-slate-900">
                              Share Meet Tab Here
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                    <p className="mt-2 text-xs font-semibold text-slate-500">
                      Chrome will ask what to share. Choose the Google Meet tab/window to make the live meeting visible here.
                    </p>
                  </div>

                  <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                    <StepLabel step="3" title="Client & Trainer" icon={Users} />
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                        <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Client</p>
                        <ContactLine icon={UserRound} label="Name" value={selected.client_name || selected.client_company} />
                        <div className="mt-2"><ContactLine icon={Mail} label="Email" value={selected.client_email} /></div>
                      </div>
                      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                        <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Trainer</p>
                        <ContactLine icon={Users} label="Name" value={selected.trainer_name} />
                        <div className="mt-2"><ContactLine icon={Mail} label="Email" value={selected.trainer_email} /></div>
                      </div>
                    </div>
                    {selected.reschedule_requested && (
                      <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                        <p className="font-bold">Reschedule requested by {selected.reschedule_requested_by || 'participant'}</p>
                        {selected.reschedule_request_text && (
                          <p className="mt-2 whitespace-pre-wrap text-xs font-semibold">{selected.reschedule_request_text}</p>
                        )}
                      </div>
                    )}
                  </div>

                  <div>
                    <StepLabel step="4" title="AI Interview Prep" icon={Sparkles} />
                    <AIInterviewAssistant selected={selected} />
                  </div>

                  <div>
                    <StepLabel step="5" title="Meeting Notes & Summary" icon={FileText} />
                    <MeetingNotesAssistant selected={selected} />
                  </div>

                  <div>
                    <StepLabel step="6" title="Reschedule Workflow" icon={CalendarDays} />
                  <ReschedulePanel selected={selected} onDone={load} />
                  </div>
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
