import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronLeft,
  Clock,
  Database,
  Eye,
  Mail,
  MessageSquare,
  Phone,
  RefreshCw,
  Send,
  Sparkles,
  Star,
  UserCheck,
  Users,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import api, { getRequirements, getShortlist } from '../utils/api'

const trainerStages = ['Mail 1', 'Details', 'Slot', 'Interview', 'Selected', 'ToC', 'Confirmed']
const clientStages = ['Requirement', 'Profiles', 'Commercial', 'Slots', 'PO', 'Invoice', 'Closed']

const trainerRequirements = [
  {
    id: 'REQ-AWS-0826',
    title: 'AWS DevOps Corporate Training',
    client: 'TechNova Systems',
    domain: 'AWS DevOps',
    topN: 8,
    clientEmail: 'learning@technova.com',
    status: 'Trainer shortlisting active',
  },
  {
    id: 'REQ-PY-1142',
    title: 'Python Full Stack Batch',
    client: 'SkillBridge Learning',
    domain: 'Python',
    topN: 6,
    clientEmail: 'ops@skillbridge.in',
    status: 'Replies under review',
  },
]

const clientRequirements = [
  {
    id: 'CL-AWS-2201',
    title: 'AWS DevOps Trainer Proposal',
    client: 'TechNova Systems',
    domain: 'AWS DevOps',
    topN: 3,
    clientEmail: 'learning@technova.com',
    status: 'Profiles ready for client',
  },
  {
    id: 'CL-JAVA-7780',
    title: 'Java Microservices Commercial Discussion',
    client: 'BrightPath Learning',
    domain: 'Java Microservices',
    topN: 2,
    clientEmail: 'ops@brightpath.in',
    status: 'Budget negotiation',
  },
]

const trainerCards = [
  {
    id: 2,
    name: 'Naveen R',
    score: 81,
    status: 'Not Selected',
    email: 'sweety78864@gmail.com',
    phone: '+91 9102852031',
    experience: '5 years',
    skills: ['Python', 'Vue.js', 'Django', 'FastAPI', 'AWS'],
    stageIndex: 4,
    next: 'Rejection behavior',
    progress: 58,
    signal: 'negative',
    reply: 'Client selected another profile. Need polite not-selected reply.',
    behavior: {
      trigger: 'Client selected another trainer',
      decision: 'Mark trainer as not selected and close current requirement',
      response: 'Thank the trainer, say another trainer was finalized, keep profile for future opportunities.',
      guardrail: 'Do not say the trainer was weak. Do not reveal client evaluation details.',
    },
  },
  {
    id: 4,
    name: 'Priya Nair',
    score: 92,
    status: 'Positive Reply',
    email: 'priya.azure@gmail.com',
    phone: '+91 9845012234',
    experience: '9 years',
    skills: ['Azure', 'DevOps', 'Kubernetes', 'Terraform'],
    stageIndex: 2,
    next: 'Slot behavior',
    progress: 38,
    signal: 'positive',
    reply: 'Available after 6 PM. Rate is INR 22,000 per day.',
    behavior: {
      trigger: 'Trainer is interested and available',
      decision: 'Move to slot booking if profile and commercial fit',
      response: 'Acknowledge availability, ask for two or three interview slots, mention client discussion.',
      guardrail: 'Do not confirm final training until client approves the trainer.',
    },
  },
  {
    id: 7,
    name: 'Rahul Verma',
    score: 88,
    status: 'Rate Gap',
    email: 'rahul.ml@gmail.com',
    phone: '+91 9988776655',
    experience: '11 years',
    skills: ['AI/ML', 'Python', 'MLOps', 'AWS'],
    stageIndex: 2,
    next: 'Rate gap behavior',
    progress: 42,
    signal: 'review',
    reply: 'Trainer quoted INR 35,000 but client budget is INR 25,000.',
    behavior: {
      trigger: 'Trainer rate is above client budget',
      decision: 'Ask for flexibility or route to recruiter approval',
      response: 'Explain budget alignment professionally and ask whether trainer can consider revised commercial.',
      guardrail: 'Do not promise client budget increase or discount without approval.',
    },
  },
]

const clientCards = [
  {
    id: 1,
    name: 'TechNova Systems',
    score: 94,
    status: 'Profiles Ready',
    email: 'learning@technova.com',
    phone: '+91 9876501200',
    experience: 'AWS DevOps batch',
    skills: ['AWS', 'DevOps', 'CI/CD', 'Kubernetes'],
    stageIndex: 1,
    next: 'Profile sharing behavior',
    progress: 28,
    signal: 'positive',
    reply: 'Client needs three trainer profiles with commercials and available interview slots.',
    behavior: {
      trigger: 'Matching trainers are ready',
      decision: 'Send client-ready trainer profile summary',
      response: 'Share trainers with skills, experience, availability, commercials, and interview slot options.',
      guardrail: 'Do not share unverified trainer rates or unavailable slots.',
    },
  },
  {
    id: 3,
    name: 'BrightPath Learning',
    score: 76,
    status: 'Budget Negotiation',
    email: 'ops@brightpath.in',
    phone: '+91 9000011122',
    experience: 'Java corporate training',
    skills: ['Java', 'Spring Boot', 'Microservices'],
    stageIndex: 2,
    next: 'Budget behavior',
    progress: 36,
    signal: 'review',
    reply: 'Client requested 15% discount and extra lab support.',
    behavior: {
      trigger: 'Client asks for discount',
      decision: 'Draft acknowledgement and keep approval required',
      response: 'Acknowledge request, say team will review commercials, avoid confirming discount immediately.',
      guardrail: 'Discount above margin must stay in recruiter approval.',
    },
  },
  {
    id: 6,
    name: 'Nexora Finance',
    score: 98,
    status: 'PO Request',
    email: 'training@nexora.com',
    phone: '+91 9123456780',
    experience: 'Data Analytics training',
    skills: ['Power BI', 'SQL', 'Python', 'Excel'],
    stageIndex: 4,
    next: 'PO behavior',
    progress: 70,
    signal: 'positive',
    reply: 'Client approved trainer and asked for PO and invoice process.',
    behavior: {
      trigger: 'Client approved trainer and commercials',
      decision: 'Move to PO and billing details',
      response: 'Request PO, billing entity, GST, invoice contact, payment terms, and delivery confirmation.',
      guardrail: 'Do not mark closed until PO/invoice details are captured.',
    },
  },
]

const trainerTrainingRows = [
  ['positive availability', 'Yes, I am available next week for AWS.', 'Move to Details/Slot', 'Ask slots, profile, commercial if missing.'],
  ['incomplete reply', 'Interested. Please share details.', 'Ask missing details', 'Ask experience, availability, mode, charges, location.'],
  ['negative availability', 'Not available for these dates.', 'Mark unavailable', 'Thank trainer and ask future availability if useful.'],
  ['rate gap', 'My rate is 35k per day.', 'Commercial review', 'Ask flexibility; do not promise client-side approval.'],
  ['selected', 'Client selected this trainer.', 'Move to ToC', 'Congratulate and ask course agenda/prerequisites.'],
  ['not selected', 'Client selected another trainer.', 'Close trainer path', 'Polite not-selected mail; keep profile for future.'],
]

const clientTrainingRows = [
  ['new requirement', 'Need AWS trainer next week.', 'Clarify requirement', 'Ask dates, duration, mode, audience, budget, location.'],
  ['profile request', 'Send trainer profiles.', 'Share profiles', 'Send verified trainers, skills, availability, commercial note.'],
  ['budget objection', 'Client budget is INR 50,000.', 'Apply margin rule', 'Keep 30% Clahan margin and use INR 35,000 as trainer-side target.'],
  ['slot confirmation', 'Tomorrow 4 PM works.', 'Schedule interview', 'Confirm slot, trainer, meeting link, and agenda.'],
  ['profile rejected', 'This trainer is not suitable.', 'Replacement flow', 'Ask mismatch reason and offer replacement trainers.'],
  ['PO request', 'Share invoice and PO details.', 'Billing flow', 'Ask billing entity, GST, PO, invoice contact, payment terms.'],
]

function numericMoney(value) {
  if (value === null || value === undefined) return 0
  const text = String(value).replaceAll(',', '')
  const match = text.match(/\d+(?:\.\d+)?/)
  return match ? Number(match[0]) : 0
}

function formatMoney(value, currency = 'INR') {
  if (!value) return 'Not available'
  return `${currency} ${Math.round(value).toLocaleString('en-IN')}`
}

function commercialPlan(source = {}) {
  const budget = numericMoney(
    source.client_budget
    || source.budget_total
    || source.budget_per_day
    || source.budget
    || source.commercial
    || source.commercials
  )
  const currency = source.budget_currency || source.currency || 'INR'
  const clahanMargin = budget ? budget * 0.3 : 0
  const trainerTarget = budget ? budget * 0.7 : 0
  return {
    clientBudget: budget,
    clahanMargin,
    trainerTarget,
    currency,
    summary: budget
      ? `Client budget ${formatMoney(budget, currency)}. Clahan 30% margin ${formatMoney(clahanMargin, currency)}. Trainer-side target ${formatMoney(trainerTarget, currency)}.`
      : 'Client budget not captured yet. Ask for budget before confirming trainer commercials.',
  }
}

function normalizeRequirement(req = {}) {
  const extracted = req.extracted || {}
  const domain = req.technology_needed || extracted.technology_needed || req.domain || req.title || req.requirement_title || 'Requirement'
  return {
    ...req,
    id: req.requirement_id || req.id || req.email_id || domain,
    title: req.title || req.requirement_title || req.subject || `${domain} Requirement`,
    client: req.client_name || extracted.client_name || req.from_name || req.client_company || extracted.client_company || req.company || req.client || 'Client not saved',
    domain,
    topN: req.top_n || req.topN || req.shortlist_count || 0,
    clientEmail: req.client_email || extracted.client_email || req.from_email || req.email || '',
    status: req.status || req.pipeline_status || req.selection_status || 'Requirement active',
    description: req.description || req.notes || req.clean_body || req.raw_body || '',
    notes: req.notes || req.clean_body || req.raw_body || '',
    commercialPlan: commercialPlan({ ...req, ...extracted }),
  }
}

function stageFromTrainer(trainer = {}) {
  const raw = String(trainer.pipeline_stage || trainer.status || trainer.selection_status || '').toLowerCase()
  if (raw.includes('confirm')) return 6
  if (raw.includes('toc')) return 5
  if (raw.includes('selected') || raw.includes('reject') || raw.includes('not selected')) return 4
  if (raw.includes('interview')) return 3
  if (raw.includes('slot')) return 2
  if (raw.includes('detail') || raw.includes('reply')) return 1
  return 0
}

function signalFromText(value = '') {
  const text = String(value || '').toLowerCase()
  if (text.includes('not selected') || text.includes('reject') || text.includes('unavailable') || text.includes('not available')) return 'negative'
  if (text.includes('rate') || text.includes('budget') || text.includes('commercial') || text.includes('negotiat')) return 'review'
  return 'positive'
}

function mapTrainerCard(trainer = {}, index = 0) {
  const stageIndex = stageFromTrainer(trainer)
  const status = trainer.selection_status || trainer.pipeline_stage || trainer.status || 'Shortlisted'
  const signal = signalFromText(`${status} ${trainer.latest_reply || trainer.reply_summary || ''}`)
  const name = trainer.name || trainer.trainer_name || `Trainer ${index + 1}`
  const skills = Array.isArray(trainer.skills)
    ? trainer.skills
    : String(trainer.skills || trainer.primary_skills || trainer.matched_skills || '').split(',').map(s => s.trim()).filter(Boolean)
  return {
    id: index + 1,
    trainerId: trainer.trainer_id || trainer.id || trainer.email || trainer.trainer_email || index + 1,
    requirementId: trainer.requirement_id || trainer.req_id || '',
    name,
    score: Math.round(Number(trainer.score || trainer.match_score || trainer.points || 0)),
    status,
    email: trainer.email || trainer.trainer_email || '',
    phone: trainer.phone || trainer.mobile || trainer.contact || '',
    experience: trainer.experience || trainer.total_experience || trainer.years_experience || '',
    skills: skills.length ? skills.slice(0, 6) : ['Skill match pending'],
    stageIndex,
    next: stageIndex >= 4 ? 'Selection behavior' : stageIndex >= 2 ? 'Slot behavior' : 'First reply behavior',
    progress: Math.min(100, Math.round((stageIndex / (trainerStages.length - 1)) * 100)),
    signal,
    reply: trainer.latest_reply || trainer.reply_summary || trainer.last_message || 'No synced reply summary yet.',
    behavior: behaviorForSignal(signal, 'trainer'),
    commercialPlan: commercialPlan(trainer),
  }
}

function mapClientCard(req = {}) {
  const signal = signalFromText(`${req.status || ''} ${req.notes || ''}`)
  const stageIndex = req.client_email ? 1 : 0
  return {
    id: 1,
    requirementId: req.id,
    clientEmail: req.clientEmail,
    name: req.client,
    score: req.client_email ? 80 : 40,
    status: req.status || 'Requirement active',
    email: req.clientEmail || 'Client email missing',
    phone: req.client_phone || req.phone || '',
    experience: req.title,
    skills: [req.domain, req.mode, req.duration, req.location].filter(Boolean),
    stageIndex,
    next: req.clientEmail ? 'Profile sharing behavior' : 'Requirement clarification behavior',
    progress: req.clientEmail ? 20 : 8,
    signal,
    reply: req.description || req.notes || 'Requirement record selected. Client reply history will appear here after sync.',
    behavior: behaviorForSignal(signal, 'client'),
    commercialPlan: req.commercialPlan || commercialPlan(req),
  }
}

function behaviorForSignal(signal, type) {
  if (signal === 'negative') {
    return type === 'trainer'
      ? {
          trigger: 'Trainer is unavailable or not selected',
          decision: 'Close this trainer path respectfully',
          response: 'Acknowledge, avoid criticism, and keep the trainer for future relevant requirements.',
          guardrail: 'Do not expose client evaluation details.',
        }
      : {
          trigger: 'Client rejected profile or requirement changed',
          decision: 'Ask mismatch reason and prepare replacement flow',
          response: 'Acknowledge feedback, ask for the exact gap, and offer alternate profiles.',
          guardrail: 'Do not argue with client feedback.',
        }
  }
  if (signal === 'review') {
    return {
      trigger: 'Commercial or budget-sensitive reply',
      decision: 'Apply Clahan 30% margin before reply',
      response: 'Use 70% of client budget as trainer-side target and keep discounts or exceptions in approval.',
      guardrail: 'Do not reveal Clahan margin to trainers or clients unless explicitly approved.',
    }
  }
  return type === 'trainer'
    ? {
        trigger: 'Trainer replied positively',
        decision: 'Move to missing details or slot booking',
        response: 'Thank trainer and ask for missing details, available slots, profile, or commercials.',
        guardrail: 'Do not confirm final selection before client approval.',
      }
    : {
        trigger: 'Client requirement is actionable',
        decision: 'Move to profile sharing or clarification',
        response: 'Ask missing requirement details or share verified profiles and next steps.',
        guardrail: 'Do not share unverified trainer availability or commercials.',
      }
}

function parseGeneratedReply(text = '') {
  const subjectMatch = /SUBJECT:\s*(.+)/i.exec(text)
  const bodyMatch = /BODY:\s*([\s\S]+)/i.exec(text)
  return {
    subject: subjectMatch?.[1]?.trim() || 'Generated Reply',
    body: bodyMatch?.[1]?.trim() || String(text || '').trim(),
  }
}

function tone(signal) {
  if (signal === 'positive') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (signal === 'negative') return 'border-red-200 bg-red-50 text-red-700'
  if (signal === 'review') return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function formatThreadTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return String(value)
  return date.toLocaleString()
}

function normalizeThreadMessage(message = {}, fallbackDirection = 'received') {
  const direction = message.direction || fallbackDirection
  return {
    ...message,
    direction,
    subject: message.subject || message.email_subject || message.title || 'No subject',
    body: message.body || message.message || message.reply_body || message.generated_reply || message.raw_body || '',
    sent_at: message.sent_at || message.created_at || message.received_at || message.latest_at || message.updated_at,
  }
}

function ThreadModal({ item, type, requirement, onClose }) {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadThread = async () => {
    setLoading(true)
    setError('')
    try {
      if (type === 'trainer') {
        const trainerId = item.trainerId || item.id
        const requirementId = item.requirementId || requirement?.id
        const res = await api.get(`/shortlists/thread?trainer_id=${encodeURIComponent(trainerId)}&requirement_id=${encodeURIComponent(requirementId)}&_ts=${Date.now()}`)
        const list = res.data?.messages || []
        setMessages(list.map(msg => normalizeThreadMessage(msg)))
      } else {
        const res = await api.get('/client-conversations', {
          params: { requirement_id: requirement?.id, page_size: 50, _ts: Date.now() },
        })
        const conversations = res.data?.conversations || []
        const list = conversations.flatMap(conv => {
          if (Array.isArray(conv.messages) && conv.messages.length) {
            return conv.messages.map(msg => normalizeThreadMessage(msg, msg.direction || 'received'))
          }
          const inbound = normalizeThreadMessage(conv, 'received')
          const draft = conv.reply_body || conv.generated_reply || conv.ai_reply
          return draft
            ? [
                inbound,
                normalizeThreadMessage({
                  direction: 'sent',
                  subject: conv.reply_subject || `Re: ${inbound.subject}`,
                  body: draft,
                  sent_at: conv.reply_sent_at || conv.updated_at || conv.created_at,
                }, 'sent'),
              ]
            : [inbound]
        })
        setMessages(list)
      }
    } catch (err) {
      setError(err.message || 'Could not load thread')
      setMessages([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadThread()
  }, [item.trainerId, item.id, requirement?.id, type])

  const sorted = [...messages].sort((a, b) => new Date(a.sent_at || 0) - new Date(b.sent_at || 0))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 p-5">
          <div>
            <h3 className="flex items-center gap-2 text-lg font-bold text-slate-900">
              <MessageSquare className="h-5 w-5 text-blue-600" />
              Conversation Thread
            </h3>
            <p className="mt-1 text-sm text-slate-500">
              {item.name} · {requirement?.domain || requirement?.title || requirement?.id}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={loadThread} className="btn-secondary py-1.5 text-xs">
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
            <button type="button" onClick={onClose} className="rounded-lg p-2 hover:bg-slate-100">
              <X className="h-4 w-4 text-slate-500" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-5">
          {loading ? (
            <div className="py-10 text-center text-sm font-semibold text-slate-400">Loading conversation...</div>
          ) : error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-700">{error}</div>
          ) : sorted.length === 0 ? (
            <div className="py-10 text-center text-slate-400">
              <MessageSquare className="mx-auto mb-2 h-10 w-10 opacity-30" />
              <p>No messages found for this {type === 'trainer' ? 'trainer' : 'client'} pipeline yet.</p>
            </div>
          ) : sorted.map((msg, index) => {
            const isSent = msg.direction === 'sent' || msg.direction === 'outbound'
            return (
              <div
                key={`${msg.email_id || msg.subject || index}-${msg.sent_at || index}`}
                className={clsx(
                  'rounded-xl border p-4',
                  isSent ? 'ml-8 border-blue-100 bg-blue-50' : 'mr-8 border-slate-200 bg-slate-50'
                )}
              >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <span className={clsx('text-xs font-bold', isSent ? 'text-blue-700' : 'text-slate-700')}>
                    {isSent ? 'Clahan sent' : type === 'trainer' ? 'Trainer replied' : 'Client replied'}
                  </span>
                  <span className="text-xs text-slate-400">{formatThreadTime(msg.sent_at)}</span>
                </div>
                <p className="mb-2 text-xs text-slate-500">
                  <span className="font-semibold">Subject:</span> {msg.subject}
                </p>
                <pre className="whitespace-pre-wrap font-sans text-sm leading-6 text-slate-700">{msg.body || 'No body saved.'}</pre>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function StageRail({ stages, current }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      {stages.map((stage, index) => {
        const done = index < current
        const active = index === current
        return (
          <div key={stage} className="flex items-center gap-1">
            <span className={clsx(
              'flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold',
              done && 'bg-blue-600 text-white',
              active && (current >= 4 ? 'bg-red-500 text-white' : 'bg-blue-600 text-white'),
              !done && !active && 'bg-slate-200 text-slate-400'
            )}>
              {done ? '✓' : index + 1}
            </span>
            <span className={clsx(active ? 'font-semibold text-slate-800' : 'text-slate-400')}>{stage}</span>
          </div>
        )
      })}
    </div>
  )
}

function RequirementSelector({ requirements, onSelect, mode, loading, error }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <p className="mb-3 text-sm font-semibold text-slate-700">
        Select {mode === 'trainer' ? 'Requirement for Trainer Pipeline' : 'Client Requirement Pipeline'}
      </p>
      {loading && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-sm font-semibold text-slate-500">
          Loading real requirements...
        </div>
      )}
      {!loading && error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm font-semibold text-red-700">
          {error}
        </div>
      )}
      {!loading && !error && requirements.length === 0 && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-sm font-semibold text-slate-500">
          No requirements found. Create a requirement first, then this pipeline will show it here.
        </div>
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        {requirements.map(req => (
          <button
            key={req.id}
            onClick={() => onSelect(req)}
            className="group flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:border-blue-300 hover:bg-blue-50"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-100 text-blue-600">
              <Star className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-bold text-slate-900">{req.title}</p>
              <p className="text-xs text-slate-500">{req.client} · {req.domain} · Top {req.topN}</p>
              <p className="mt-1 text-xs font-semibold text-blue-600">{req.status}</p>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

function PipelineCard({ item, type, stages, draft, generating, onGenerate, onThread }) {
  return (
    <div className={clsx('rounded-2xl border bg-white p-4 shadow-sm', item.signal === 'negative' ? 'border-red-200' : 'border-slate-200')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-slate-100 text-sm font-bold text-slate-700">
            {item.id}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-bold text-slate-950">{item.name}</h3>
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-bold text-emerald-700">{item.score} pts</span>
              <span className={clsx('rounded-full border px-2 py-0.5 text-xs font-bold', tone(item.signal))}>
                {type === 'trainer' ? 'TRAINER STATUS' : 'CLIENT STATUS'}: {item.status}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              <span className="flex items-center gap-1"><Mail className="h-3.5 w-3.5" />{item.email}</span>
              <span className="flex items-center gap-1"><Phone className="h-3.5 w-3.5" />{item.phone}</span>
              <span className="flex items-center gap-1"><Clock className="h-3.5 w-3.5" />{item.experience}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {item.skills.map(skill => (
                <span key={skill} className="rounded-full bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700">{skill}</span>
              ))}
            </div>
            <div className="mt-3">
              <StageRail stages={stages} current={item.stageIndex} />
            </div>
          </div>
        </div>
        <button type="button" onClick={() => onThread(item)} className="btn-secondary py-1.5 text-xs">
          <Eye className="h-3.5 w-3.5" />
          Thread
        </button>
      </div>

      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Pipeline Progress</p>
            <p className="text-sm font-bold text-slate-900">{item.next} is next</p>
          </div>
          <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-bold text-slate-700">{item.progress}%</span>
        </div>
        <div className="mt-3 h-1.5 rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-blue-600" style={{ width: `${item.progress}%` }} />
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-4">
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-bold uppercase text-slate-400">{type === 'trainer' ? 'Trainer mails' : 'Client mails'}</p>
            <p className="mt-1 text-sm font-bold text-slate-900">{item.stageIndex}/{stages.length} complete</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-bold uppercase text-slate-400">Reply Signal</p>
            <p className="mt-1 text-sm font-bold capitalize text-slate-900">{item.signal}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-bold uppercase text-slate-400">LLM Decision</p>
            <p className="mt-1 text-sm font-bold text-slate-900">{item.behavior.decision}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-bold uppercase text-slate-400">Current Stage</p>
            <p className="mt-1 text-sm font-bold text-slate-900">{item.status}</p>
          </div>
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Latest reply data used to train behavior</p>
            <p className="mt-1 text-sm leading-6 text-slate-700">{item.reply}</p>
            <p className="mt-2 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
              Commercial rule: {item.commercialPlan?.summary || 'Clahan keeps 30% margin; trainer-side target is 70% of client budget.'}
            </p>
          </div>

      <div className="mt-3 rounded-xl border border-blue-100 bg-blue-50 p-3">
        <div className="grid gap-3 lg:grid-cols-4">
          <div>
            <p className="text-[11px] font-bold uppercase text-blue-500">Trigger</p>
            <p className="mt-1 text-sm font-semibold text-blue-900">{item.behavior.trigger}</p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase text-blue-500">LLM should reply</p>
            <p className="mt-1 text-sm text-blue-900">{item.behavior.response}</p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase text-blue-500">Guardrail</p>
            <p className="mt-1 text-sm text-blue-900">{item.behavior.guardrail}</p>
          </div>
          <div className="flex items-end justify-end">
            <button className="btn-primary" onClick={() => onGenerate(item)} disabled={generating}>
              <Send className="h-4 w-4" />
              {generating ? 'Generating...' : 'Generate Reply'}
            </button>
          </div>
        </div>
      </div>
      {draft && (
        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-600">Generated AI Draft</p>
              <h4 className="mt-1 text-sm font-bold text-emerald-950">{draft.subject}</h4>
            </div>
            <span className="badge-green">ready for review</span>
          </div>
          <pre className="mt-3 whitespace-pre-wrap rounded-lg border border-emerald-100 bg-white p-3 font-sans text-sm leading-6 text-slate-700">
            {draft.body}
          </pre>
        </div>
      )}
    </div>
  )
}

function ClientRequestContextPanel({ requirement, cards }) {
  const activeCard = cards[0]
  const requestText = requirement.description || requirement.notes || requirement.requirement_description || requirement.raw_body || 'No request text saved yet. Open Client Requests or sync inbox to capture the client mail body.'
  return (
    <div className="rounded-2xl border border-blue-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-blue-600">Client Request Seen By GPT</p>
          <h3 className="mt-1 text-lg font-bold text-slate-950">{requirement.title}</h3>
          <p className="mt-1 text-sm text-slate-500">{requirement.client} · {requirement.clientEmail || 'Client email missing'}</p>
        </div>
        <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">
          Used in Generate Reply
        </span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-[11px] font-bold uppercase text-slate-400">Domain</p>
          <p className="mt-1 text-sm font-bold text-slate-900">{requirement.domain}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-[11px] font-bold uppercase text-slate-400">Client Budget</p>
          <p className="mt-1 text-sm font-bold text-slate-900">{formatMoney(requirement.commercialPlan?.clientBudget, requirement.commercialPlan?.currency)}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-[11px] font-bold uppercase text-slate-400">Trainer Target</p>
          <p className="mt-1 text-sm font-bold text-slate-900">{formatMoney(requirement.commercialPlan?.trainerTarget, requirement.commercialPlan?.currency)}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-[11px] font-bold uppercase text-slate-400">GPT Decision</p>
          <p className="mt-1 text-sm font-bold text-slate-900">{activeCard?.behavior?.decision || 'Clarify requirement'}</p>
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
        <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Client Mail / Request Text</p>
        <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-700">{requestText}</p>
      </div>
    </div>
  )
}

export default function CommunicationPipeline({ fixedMode = '' }) {
  const mode = fixedMode || 'trainer'
  const [requirements, setRequirements] = useState([])
  const [selectedReq, setSelectedReq] = useState(null)
  const [shortlistCards, setShortlistCards] = useState([])
  const [loadingReqs, setLoadingReqs] = useState(false)
  const [loadingCards, setLoadingCards] = useState(false)
  const [error, setError] = useState('')
  const [showTraining, setShowTraining] = useState(true)
  const [drafts, setDrafts] = useState({})
  const [generatingId, setGeneratingId] = useState('')
  const [threadItem, setThreadItem] = useState(null)

  useEffect(() => {
    let cancelled = false
    const params = new URLSearchParams(window.location.search)
    const requestedRequirementId = params.get('requirement_id')
    const requestedClientEmailId = params.get('client_email_id')
    setLoadingReqs(true)
    setError('')
    getRequirements()
      .then(res => {
        if (cancelled) return
        const list = res.data?.requirements || res.data?.items || []
        const normalized = list.map(normalizeRequirement)
        setRequirements(normalized)
        if (mode === 'client' && requestedRequirementId) {
          const match = normalized.find(req => String(req.id) === String(requestedRequirementId))
          if (match) setSelectedReq(match)
        }
        if (mode === 'client' && requestedClientEmailId) {
          api.get('/inbox', { params: { include_hidden: true, limit: 500 } })
            .then(inboxRes => {
              if (cancelled) return
              const inboxItems = inboxRes.data?.emails || []
              const mail = inboxItems.find(item => String(item.email_id) === String(requestedClientEmailId))
              if (!mail) return
              const mailReq = normalizeRequirement(mail)
              setSelectedReq(prev => prev?.id === mailReq.id ? prev : mailReq)
            })
            .catch(() => {})
        }
      })
      .catch(err => {
        if (!cancelled) setError(err.message || 'Could not load requirements')
      })
      .finally(() => {
        if (!cancelled) setLoadingReqs(false)
      })
    return () => { cancelled = true }
  }, [mode])

  useEffect(() => {
    if (!selectedReq) {
      setShortlistCards([])
      return
    }
    if (mode === 'client') {
      setShortlistCards([mapClientCard(selectedReq)])
      return
    }

    let cancelled = false
    setLoadingCards(true)
    setShortlistCards([])
    getShortlist(selectedReq.id)
      .then(res => {
        if (cancelled) return
        const list = res.data?.top_trainers || res.data?.trainers || []
        setShortlistCards(list.map(mapTrainerCard))
      })
      .catch(() => {
        if (!cancelled) setShortlistCards([])
      })
      .finally(() => {
        if (!cancelled) setLoadingCards(false)
      })
    return () => { cancelled = true }
  }, [selectedReq, mode])

  const cards = shortlistCards
  const stages = mode === 'trainer' ? trainerStages : clientStages
  const rows = mode === 'trainer' ? trainerTrainingRows : clientTrainingRows
  const stats = useMemo(() => ({
    total: cards.length,
    positive: cards.filter(c => c.signal === 'positive').length,
    negative: cards.filter(c => c.signal === 'negative').length,
    review: cards.filter(c => c.signal === 'review').length,
  }), [cards])

  const handleGenerateReply = async item => {
    const key = `${mode}-${item.id}`
    setGeneratingId(key)
    try {
      const prompt = `Generate the next ${mode === 'trainer' ? 'trainer' : 'client'} communication reply for Clahan / TrainerSync.

Requirement:
- ID: ${selectedReq?.id || ''}
- Domain: ${selectedReq?.domain || ''}
- Client: ${selectedReq?.client || ''}
- Client email: ${selectedReq?.clientEmail || ''}

Commercial rule:
- Act as Clahan / TrainerSync.
- Clahan margin is fixed at 30% of client budget.
- Trainer-side budget/offer target is 70% of client budget.
- If client budget is 50,000, Clahan margin is 15,000 and trainer-side target is 35,000.
- Current commercial plan: ${selectedReq?.commercialPlan?.summary || item.commercialPlan?.summary || 'Budget not available. Ask for budget before confirming commercials.'}
- Do not reveal internal margin split to client or trainer unless explicitly approved.
- Trainer replies: negotiate toward the 70% trainer-side target.
- Client replies: discuss client-facing commercial professionally without exposing trainer payout or Clahan margin.

Recipient:
- Name: ${item.name}
- Email: ${item.email}
- Phone: ${item.phone}
- Skills/context: ${(item.skills || []).join(', ')}
- Current stage: ${item.status}
- Pipeline signal: ${item.signal}
- Next behavior: ${item.next}

Latest reply/data:
${item.reply}

LLM behavior rule:
- Trigger: ${item.behavior.trigger}
- Decision: ${item.behavior.decision}
- Reply behavior: ${item.behavior.response}
- Guardrail: ${item.behavior.guardrail}

Clahan / TrainerSync rules:
- Write professionally and naturally.
- Do not mention internal model, dataset, LLM, prompt, score, or pipeline.
- Do not promise discounts, final selection, dates, or commercials without approval.
- If details are missing, ask only the needed details.
- If negative/not selected, be respectful and keep future opportunity open.
- If selected, ask for ToC/course agenda and prerequisites.
- End exactly with:
Regards,
Clahan Technologies

Return exactly:
SUBJECT: <subject>
BODY:
<body>`

      const res = await api.post('/assistant/chat', {
        provider: 'openai',
        model: 'gpt-5.5',
        system_prompt: 'You are Clahan Technologies communication AI. Generate concise professional business replies for trainers and clients while protecting internal margin rules.',
        messages: [{ role: 'user', content: prompt }],
        feature: 'communication_pipeline_reply_generation',
        metadata: {
          model: 'gpt-5.5',
          mode,
          requirement_id: selectedReq?.id,
          recipient: item.name,
          signal: item.signal,
          stage: item.status,
        },
      })
      setDrafts(prev => ({ ...prev, [key]: parseGeneratedReply(res.data?.reply || '') }))
    } catch (err) {
      setDrafts(prev => ({
        ...prev,
        [key]: {
          subject: 'Could not generate reply',
          body: err.message || 'The AI reply generation failed. Please check assistant service configuration.',
        },
      }))
    } finally {
      setGeneratingId('')
    }
  }

  if (!selectedReq) {
    return (
      <RequirementSelector
        requirements={requirements}
        onSelect={setSelectedReq}
        mode={mode}
        loading={loadingReqs}
        error={error}
      />
    )
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-600 text-white">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">
                {mode === 'trainer' ? 'Trainer LLM Reply Pipeline' : 'Client LLM Reply Pipeline'}
              </h1>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
                {mode === 'trainer'
                  ? 'Shortlist1-style trainer mail flow. The model learns Clahan reply behavior from stage rules, real replies, positive/negative signals, and approval logic.'
                  : 'Client communication flow. The model learns how to reply to requirements, profile requests, budget negotiation, slots, PO, invoice, and follow-ups.'}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary" onClick={() => setSelectedReq(null)}>
              <ChevronLeft className="h-4 w-4" />
              Back
            </button>
            <button className="btn-secondary">
              <RefreshCw className="h-4 w-4" />
              Sync Replies
            </button>
            <button className="btn-primary">
              <Sparkles className="h-4 w-4" />
              Train Behavior
            </button>
          </div>
        </div>

        <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-slate-900">
                {mode === 'trainer' ? 'Shortlisted for:' : 'Client pipeline for:'}{' '}
                <span className="text-blue-600">{selectedReq.domain}</span>
              </h2>
              <div className="mt-1 inline-flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                <Mail className="h-3.5 w-3.5" />
                <span>Client: {selectedReq.clientEmail}</span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{selectedReq.id} · {selectedReq.client} · Top {selectedReq.topN}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {[
                ['Cards', stats.total],
                ['Positive', stats.positive],
                ['Negative', stats.negative],
                ['Review', stats.review],
              ].map(([label, value]) => (
                <div key={label} className="min-w-[88px] rounded-xl border border-slate-200 bg-white px-3 py-2">
                  <p className="text-xs font-semibold text-slate-400">{label}</p>
                  <p className="text-lg font-bold text-slate-900">{value}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-3 text-xs sm:grid-cols-3">
        <div className="rounded-xl bg-blue-50 px-3 py-2 text-blue-700">
          <p className="font-bold">{mode === 'trainer' ? 'Trainer mail pipeline' : 'Client mail pipeline'}</p>
          <p className="mt-0.5 text-blue-600">7 stages from first reply to closure</p>
        </div>
        <div className="rounded-xl bg-emerald-50 px-3 py-2 text-emerald-700">
          <p className="font-bold">LLM behavior training</p>
          <p className="mt-0.5 text-emerald-600">Learns when to ask, send, negotiate, reject, or approve</p>
        </div>
        <div className="rounded-xl bg-amber-50 px-3 py-2 text-amber-700">
          <p className="font-bold">Approval safety</p>
          <p className="mt-0.5 text-amber-600">Rate gap and discount replies stay in review</p>
        </div>
      </div>

      {mode === 'client' && (
        <ClientRequestContextPanel requirement={selectedReq} cards={cards} />
      )}

      <div className="space-y-4">
        {loadingCards ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center">
            <Users className="mx-auto mb-3 h-12 w-12 text-slate-200" />
            <p className="font-medium text-slate-500">Loading real pipeline cards...</p>
          </div>
        ) : cards.length === 0 ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center">
            <Users className="mx-auto mb-3 h-12 w-12 text-slate-200" />
            <p className="font-medium text-slate-500">
              {mode === 'trainer' ? 'No shortlisted trainers found for this requirement yet' : 'No client pipeline data found for this requirement yet'}
            </p>
            <p className="mt-1 text-sm text-slate-400">
              {mode === 'trainer' ? 'Run shortlist generation first, then this LLM pipeline will show the real trainers.' : 'Save client email and requirement details first.'}
            </p>
          </div>
        ) : (
          cards.map(card => {
            const key = `${mode}-${card.id}`
            return (
              <PipelineCard
                key={card.id}
                item={card}
                type={mode}
                stages={stages}
                draft={drafts[key]}
                generating={generatingId === key}
                onGenerate={handleGenerateReply}
                onThread={setThreadItem}
              />
            )
          })
        )}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <button
          type="button"
          onClick={() => setShowTraining(v => !v)}
          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        >
          <span className="flex items-center gap-2 text-sm font-bold text-slate-800">
            <Database className="h-4 w-4" />
            Dataset rows used to teach reply behavior
          </span>
          <span className="text-xs font-semibold text-slate-400">{showTraining ? 'Hide' : 'Show'}</span>
        </button>
        {showTraining && (
          <div className="border-t border-slate-100 p-4">
            <div className="table-wrap rounded-xl">
              <table className="table">
                <thead>
                  <tr>
                    <th>Signal</th>
                    <th>Example Reply</th>
                    <th>Decision</th>
                    <th>LLM Should Do</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(([signal, example, decision, action]) => (
                    <tr key={`${signal}-${decision}`}>
                      <td className="font-semibold capitalize">{signal}</td>
                      <td>{example}</td>
                      <td>{decision}</td>
                      <td>{action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            Positive reply behavior
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600">Move forward automatically: ask details, ask slots, send profiles, or confirm next action.</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <X className="h-4 w-4 text-red-600" />
            Negative reply behavior
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600">Mark unavailable, not selected, rejected, or mismatch and draft respectful closure.</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            Review behavior
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600">Rate gap, discount, cancellation, and low-confidence replies stay in approval before sending.</p>
        </div>
      </div>
      {threadItem && (
        <ThreadModal
          item={threadItem}
          type={mode}
          requirement={selectedReq}
          onClose={() => setThreadItem(null)}
        />
      )}
    </div>
  )
}
