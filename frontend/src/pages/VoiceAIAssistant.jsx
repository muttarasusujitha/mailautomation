import { useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  Bot,
  BriefcaseBusiness,
  CalendarClock,
  Copy,
  FileText,
  Mail,
  Mic,
  MicOff,
  PhoneCall,
  RefreshCw,
  Send,
  Sparkles,
  UserRoundSearch,
  Volume2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { analyzeVoiceAI, createVoiceAITask, executeVoiceAIAction, getVoiceAINotes, getVoiceAITasks, saveVoiceAINote } from '../utils/api'

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition

const QUICK_PROMPTS = [
  'Find a DevOps trainer for Hyderabad with AWS Docker Kubernetes Jenkins Terraform.',
  'Draft a follow up to a trainer asking for availability, profile, commercials, and interview slots.',
  'Summarise this client requirement and prepare shortlist criteria.',
  'Create a recruiter call script for screening a Python AWS trainer.',
]

function inferIntent(text) {
  const lower = text.toLowerCase()
  if (lower.includes('shortlist') || lower.includes('find') || lower.includes('trainer')) return 'Trainer shortlist'
  if (lower.includes('follow') || lower.includes('mail') || lower.includes('email')) return 'Email drafting'
  if (lower.includes('interview') || lower.includes('slot') || lower.includes('schedule')) return 'Interview scheduling'
  if (lower.includes('client') || lower.includes('requirement')) return 'Requirement intake'
  return 'Recruiter assistance'
}

function responseDraft(text) {
  const clean = text.trim()
  if (!clean) return 'Start speaking or type a recruiter instruction to generate a draft.'
  const intent = inferIntent(clean)
  return [
    `Intent: ${intent}`,
    '',
    'Suggested next action:',
    intent === 'Trainer shortlist'
      ? 'Search trainer database, rank matching profiles, and prepare top candidates with resume evidence.'
      : intent === 'Email drafting'
        ? 'Prepare a concise trainer/client email with availability, commercials, location, and interview-slot details.'
        : intent === 'Interview scheduling'
          ? 'Collect trainer slots, confirm client availability, and send calendar-ready meeting details.'
          : intent === 'Requirement intake'
            ? 'Extract skill, location, timeline, budget, delivery mode, and shortlist criteria from the client request.'
            : 'Turn the voice note into a structured recruiting task.',
    '',
    'Draft:',
    `Hi, noted. I will proceed with: ${clean}`,
    '',
    'Checklist:',
    '- Confirm technology and seniority',
    '- Check location or remote preference',
    '- Verify resume/profile availability',
    '- Capture commercials and trainer availability',
    '- Prepare client-ready summary',
  ].join('\n')
}

export default function VoiceAIAssistant() {
  const [listening, setListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [analysis, setAnalysis] = useState(null)
  const [notes, setNotes] = useState([])
  const [tasks, setTasks] = useState([])
  const [outputMode, setOutputMode] = useState('draft')
  const [executionResult, setExecutionResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState('')
  const [error, setError] = useState('')
  const recognitionRef = useRef(null)
  const draft = useMemo(() => {
    if (!analysis) return responseDraft(transcript)
    if (outputMode === 'script' && analysis.call_script) return analysis.call_script
    return [
      `Intent: ${analysis.intent_label}`,
      '',
      `Suggested next action:`,
      analysis.draft,
      '',
      'Checklist:',
      ...(analysis.checklist || []).map(item => `- ${item}`),
    ].join('\n')
  }, [analysis, outputMode, transcript])
  const supported = Boolean(SpeechRecognition)

  const loadHistory = async () => {
    try {
      const [notesRes, tasksRes] = await Promise.all([
        getVoiceAINotes({ limit: 5 }),
        getVoiceAITasks({ limit: 5 }),
      ])
      setNotes(notesRes.data.items || [])
      setTasks(tasksRes.data.items || [])
    } catch {
      setNotes([])
      setTasks([])
    }
  }

  useEffect(() => {
    loadHistory()
  }, [])

  const runAnalysis = async () => {
    if (!transcript.trim()) {
      toast.error('Add a voice note or typed instruction first')
      return null
    }
    setLoading(true)
    setError('')
    try {
      const res = await analyzeVoiceAI(transcript)
      setAnalysis(res.data.analysis)
      setExecutionResult(null)
      setOutputMode('draft')
      return res.data.analysis
    } catch (err) {
      setError(err.message || 'Could not analyze voice note')
      return null
    } finally {
      setLoading(false)
    }
  }

  const startListening = () => {
    if (!supported) {
      setError('Voice capture is not supported in this browser. You can still type the instruction.')
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
      setError(event.error || 'Could not capture voice')
      setListening(false)
    }
    recognition.onend = () => setListening(false)
    recognitionRef.current = recognition
    setError('')
    setListening(true)
    recognition.start()
  }

  const stopListening = () => {
    recognitionRef.current?.stop()
    setListening(false)
  }

  const speakDraft = () => {
    if (!window.speechSynthesis) {
      toast.error('Voice playback is not supported in this browser')
      return
    }
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(draft))
  }

  const copyDraft = async () => {
    await navigator.clipboard.writeText(draft)
    toast.success('Draft copied')
  }

  const handleSaveNote = async () => {
    if (!transcript.trim()) {
      toast.error('Add a voice note or typed instruction first')
      return
    }
    setSaving('note')
    try {
      await saveVoiceAINote(transcript)
      toast.success('Voice note saved')
      await loadHistory()
    } catch (err) {
      toast.error(err.message || 'Could not save note')
    } finally {
      setSaving('')
    }
  }

  const handleCreateTask = async () => {
    if (!transcript.trim()) {
      toast.error('Add a voice note or typed instruction first')
      return
    }
    setSaving('task')
    try {
      const current = analysis || await runAnalysis()
      await createVoiceAITask(transcript, {
        title: current?.summary || 'Voice AI recruiter task',
        priority: current?.priority || 'medium',
      })
      toast.success('Recruiter task created')
      await loadHistory()
    } catch (err) {
      toast.error(err.message || 'Could not create task')
    } finally {
      setSaving('')
    }
  }

  const handleExecuteAction = async () => {
    if (!transcript.trim()) {
      toast.error('Add a voice note or typed instruction first')
      return
    }
    setSaving('execute')
    setError('')
    try {
      const res = await executeVoiceAIAction(transcript)
      setAnalysis(res.data.analysis)
      setExecutionResult(res.data.result)
      setOutputMode('draft')
      toast.success(`Requirement ${res.data.result?.requirement_id || ''} created`)
      await loadHistory()
    } catch (err) {
      setError(err.message || 'Could not execute voice action')
      toast.error(err.message || 'Could not execute voice action')
    } finally {
      setSaving('')
    }
  }

  const handleCallScript = async () => {
    const current = analysis || await runAnalysis()
    if (!current) return
    setOutputMode('script')
    toast.success('Call script ready')
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title">Voice AI HR/Recruiter Assistant</h1>
          <p className="mt-1 text-sm text-slate-500">Capture recruiter instructions, structure them, and prepare the next action.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={listening ? stopListening : startListening} className={clsx('btn-primary', listening && 'bg-red-600 hover:bg-red-700')}>
            {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            {listening ? 'Stop Listening' : 'Start Voice'}
          </button>
          <button type="button" onClick={() => { setTranscript(''); setAnalysis(null); setExecutionResult(null); setOutputMode('draft'); setError('') }} className="btn-secondary">
            <RefreshCw className="h-4 w-4" />
            Reset
          </button>
        </div>
      </div>

      {error && <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-700">{error}</div>}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="card p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="rounded-xl bg-blue-50 p-2 text-blue-600"><Bot className="h-5 w-5" /></span>
              <div>
                <h2 className="font-bold text-slate-900">Voice Command</h2>
                <p className="text-xs text-slate-500">{supported ? 'English India voice capture enabled' : 'Type mode available'}</p>
              </div>
            </div>
            <span className={clsx('rounded-full px-2.5 py-1 text-xs font-bold', listening ? 'bg-red-50 text-red-600' : 'bg-slate-100 text-slate-500')}>
              {listening ? 'Listening' : 'Idle'}
            </span>
          </div>

          <textarea
            value={transcript}
            onChange={e => { setTranscript(e.target.value); setAnalysis(null); setOutputMode('draft') }}
            placeholder="Speak or type: Find Java trainer in Pune, draft mail, schedule interview, summarize client requirement..."
            className="min-h-56 w-full rounded-xl border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-800 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />

          <div className="mt-4 grid grid-cols-1 gap-2">
            {QUICK_PROMPTS.map(prompt => (
              <button key={prompt} type="button" onClick={() => { setTranscript(prompt); setAnalysis(null); setOutputMode('draft') }} className="rounded-lg border border-slate-200 px-3 py-2 text-left text-xs font-semibold text-slate-600 hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700">
                {prompt}
              </button>
            ))}
          </div>
        </section>

        <section className="card p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="rounded-xl bg-emerald-50 p-2 text-emerald-600"><Sparkles className="h-5 w-5" /></span>
              <div>
                <h2 className="font-bold text-slate-900">Assistant Output</h2>
                <p className="text-xs text-slate-500">Structured recruiter task and draft response</p>
              </div>
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={runAnalysis} disabled={loading} className="btn-primary disabled:opacity-60">
                {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                Analyze
              </button>
              <button type="button" onClick={copyDraft} className="btn-secondary"><Copy className="h-4 w-4" />Copy</button>
              <button type="button" onClick={speakDraft} className="btn-secondary"><Volume2 className="h-4 w-4" />Speak</button>
            </div>
          </div>
          <pre className="min-h-96 whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 p-4 font-sans text-sm leading-6 text-slate-700">{draft}</pre>
        </section>
      </div>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {[
          [UserRoundSearch, 'Screen Trainers', 'Voice notes become profile checks and shortlist criteria.'],
          [Mail, 'Draft Emails', 'Create trainer and client follow-ups from spoken instructions.'],
          [CalendarClock, 'Schedule Slots', 'Turn availability into interview and training actions.'],
          [BriefcaseBusiness, 'Client Intake', 'Capture requirement details before matching trainers.'],
        ].map(([Icon, title, body]) => (
          <div key={title} className="card p-4">
            <Icon className="mb-3 h-5 w-5 text-blue-600" />
            <h3 className="font-bold text-slate-900">{title}</h3>
            <p className="mt-1 text-sm leading-6 text-slate-500">{body}</p>
          </div>
        ))}
      </section>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={handleCreateTask} disabled={!!saving} className="btn-primary disabled:opacity-60">
          {saving === 'task' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          Create Task
        </button>
        <button type="button" onClick={handleExecuteAction} disabled={!!saving} className="btn-primary disabled:opacity-60">
          {saving === 'execute' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <UserRoundSearch className="h-4 w-4" />}
          Execute Search
        </button>
        <button type="button" onClick={handleSaveNote} disabled={!!saving} className="btn-secondary disabled:opacity-60">
          {saving === 'note' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
          Save Note
        </button>
        <button type="button" onClick={handleCallScript} disabled={loading} className="btn-secondary disabled:opacity-60">
          <PhoneCall className="h-4 w-4" />
          Call Script
        </button>
      </div>

      {executionResult && (
        <section className="card p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-bold text-slate-900">Executed Requirement</h3>
              <p className="mt-1 text-sm text-slate-500">
                {executionResult.requirement_id} · {executionResult.total_matched || 0} matched · {executionResult.top_trainers || 0} shortlisted
              </p>
            </div>
            <a href={`/shortlist1?req=${executionResult.requirement_id}`} className="btn-secondary">
              Open Pipeline
            </a>
          </div>
          {(executionResult.top_trainers_list || []).length > 0 && (
            <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
              {executionResult.top_trainers_list.slice(0, 6).map(trainer => (
                <div key={trainer.trainer_id || trainer.email} className="rounded-lg border border-slate-200 p-3">
                  <p className="text-sm font-semibold text-slate-800">{trainer.name || trainer.trainer_name || 'Trainer'}</p>
                  <p className="mt-1 text-xs text-slate-500">{trainer.email || 'No email'} · {trainer.match_score ?? 0} pts</p>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="card p-4">
          <h3 className="font-bold text-slate-900">Recent Tasks</h3>
          <div className="mt-3 space-y-2">
            {tasks.length ? tasks.map(task => (
              <div key={task.task_id} className="rounded-lg border border-slate-200 p-3">
                <p className="text-sm font-semibold text-slate-800">{task.title}</p>
                <p className="mt-1 text-xs text-slate-500">{task.task_id} · {task.priority} · {task.status}</p>
              </div>
            )) : <p className="text-sm text-slate-500">No voice tasks saved yet.</p>}
          </div>
        </div>

        <div className="card p-4">
          <h3 className="font-bold text-slate-900">Recent Voice Notes</h3>
          <div className="mt-3 space-y-2">
            {notes.length ? notes.map(note => (
              <div key={note.note_id} className="rounded-lg border border-slate-200 p-3">
                <p className="line-clamp-2 text-sm text-slate-700">{note.transcript}</p>
                <p className="mt-1 text-xs text-slate-500">{note.note_id} · {note.analysis?.intent_label || 'Voice note'}</p>
              </div>
            )) : <p className="text-sm text-slate-500">No voice notes saved yet.</p>}
          </div>
        </div>
      </section>
    </div>
  )
}
