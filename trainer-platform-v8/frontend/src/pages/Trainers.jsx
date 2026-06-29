import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getTrainers,
  deleteTrainer,
  getTrainerCategories,
  getTrainerDomains,
  getTrainerIndustries,
  categoriseTrainer,
  categoriseAllTrainers,
  getCategoriseJob,
  updateTrainer,
  requestTrainerResume,
  sendTrainerAutomationMail,
  tickTrainerAutomationPipeline,
  getTrainerConversationThread,
} from '../utils/api'
import {
  Search,
  MapPin,
  Mail,
  Phone,
  Linkedin,
  FileText,
  Clock,
  ChevronLeft,
  ChevronRight,
  Filter,
  Users,
  Trash2,
  X,
  Award,
  Sparkles,
  RefreshCw,
  Languages,
  Briefcase,
  Eye,
  MessageSquare,
  Save,
  Send,
  Star,
  CheckCircle2,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { TrainerCardTrustPill } from '../components/VerificationBadge'

const STATUS_COLORS = {
  new: 'badge-slate',
  contacted: 'badge-blue',
  interested: 'badge-green',
  declined: 'badge-red',
  confirmed: 'badge-green',
  pending_review: 'badge-yellow',
}

const STATUSES = ['', 'new', 'contacted', 'interested', 'declined', 'pending_review']
const SOFTWARE_DOMAINS = [
  'Software Development',
  'Frontend Development',
  'Backend Development',
  'Full Stack',
  'Programming Languages',
  'Cloud',
  'DevOps',
  'SRE',
  'Data Engineering',
  'Data Analytics',
  'Data Science',
  'Business Intelligence',
  'AI',
  'Gen AI',
  'Agentic AI',
  'Machine Learning',
  'MLOps',
  'LLMOps',
  'AIOps',
  'Cybersecurity',
  'Blockchain',
  'Database',
  'QA and Testing',
  'Automation Testing',
  'Enterprise Software',
  'ERP Software',
  'CRM Software',
  'Salesforce',
  'ServiceNow',
  'SAP Technical',
  'Mobile Development',
  'Game Development',
  'AR and VR',
  'IoT',
  'Embedded Systems',
  'Robotics',
  'Quantum Computing',
]
const NON_SOFTWARE_DOMAINS = new Set([
  'business',
  'finance',
  'financial',
  'creative',
  'healthcare',
  'manufacturing',
  'language',
  'languages',
  'non-software training',
])
const EXPERIENCE_OPTIONS = [
  { value: '', label: 'Any Experience' },
  { value: '0-3', label: '0-3 years' },
  { value: '3-7', label: '3-7 years' },
  { value: '7+', label: '7+ years' },
]
const PROFILE_FILTERS = [
  { value: '', label: 'All profiles', icon: Users },
  { value: 'complete', label: 'Ready profiles', icon: CheckCircle2 },
  { value: 'email', label: 'Has email', icon: Mail },
  { value: 'phone', label: 'Has phone', icon: Phone },
  { value: 'linkedin', label: 'LinkedIn', icon: Linkedin },
  { value: 'teams', label: 'Teams ready', icon: MessageSquare },
  { value: 'rated', label: 'Rated', icon: Star },
  { value: 'needs_review', label: 'Needs review', icon: ShieldCheck },
]
const SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'rating_desc', label: 'Best rated' },
  { value: 'experience_desc', label: 'Most experience' },
  { value: 'name_asc', label: 'Name A-Z' },
]
const PIPELINE_MAIL_TEMPLATES = [
  { value: 'mail1', label: 'Mail 1 - First Contact' },
  { value: 'mail2', label: 'Mail 2 - Details Request' },
  { value: 'mail2_followup', label: 'Mail 2 Follow-up - Ask Details Again' },
  { value: 'mail3', label: 'Mail 3 - Interview Slot Booking' },
  { value: 'mail4', label: 'Mail 4 - Interview Schedule' },
  { value: 'mail5_ok', label: 'Mail 5 - Selection' },
  { value: 'mail5_no', label: 'Mail 5 - Rejection' },
  { value: 'mail6_toc', label: 'Mail 6 - ToC Request' },
  { value: 'mail7_confirm', label: 'Mail 7 - Training Confirmation' },
]

const DOMAIN_BADGES = {
  cloud: 'bg-sky-50 text-sky-700 border-sky-200',
  devops: 'bg-blue-50 text-blue-700 border-blue-200',
  sre: 'bg-blue-50 text-blue-700 border-blue-200',
  cybersecurity: 'bg-red-50 text-red-700 border-red-200',
  blockchain: 'bg-violet-50 text-violet-700 border-violet-200',
  'data engineering': 'bg-teal-50 text-teal-700 border-teal-200',
  'data science': 'bg-emerald-50 text-emerald-700 border-emerald-200',
  'data analytics': 'bg-indigo-50 text-indigo-700 border-indigo-200',
  'business intelligence': 'bg-amber-50 text-amber-700 border-amber-200',
  ai: 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200',
  'gen ai': 'bg-purple-50 text-purple-700 border-purple-200',
  'agentic ai': 'bg-purple-50 text-purple-700 border-purple-200',
  'programming languages': 'bg-slate-100 text-slate-700 border-slate-200',
  'enterprise software': 'bg-orange-50 text-orange-700 border-orange-200',
}

function asArray(value) {
  if (Array.isArray(value)) return value.filter(Boolean)
  if (!value) return []
  return String(value).split(/[,;\n]/).map(item => item.trim()).filter(Boolean)
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b))
}

function softwareDomainsOnly(values) {
  return values.filter(domain => domain && !NON_SOFTWARE_DOMAINS.has(String(domain).toLowerCase()))
}

function primaryCategory(t) {
  return t.primary_category || t.technology_category || t.category || 'Uncategorised'
}

function specialisationTags(t) {
  return asArray(t.specialisation_tags?.length ? t.specialisation_tags : t.specialty_tags)
}

function domainBadge(domain) {
  return DOMAIN_BADGES[String(domain || '').toLowerCase()] || 'bg-slate-100 text-slate-600 border-slate-200'
}

function levelBadge(level) {
  const normalized = String(level || '').toLowerCase()
  if (normalized === 'expert') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (normalized === 'beginner') return 'bg-slate-50 text-slate-600 border-slate-200'
  return 'bg-blue-50 text-blue-700 border-blue-200'
}

function skillLevels(t) {
  const map = t.skill_level_map || {}
  return Object.entries(map).filter(([skill]) => skill).slice(0, 3)
}

function technologyList(t) {
  return uniqueCompact([
    ...asArray(t.skills),
    ...asArray(t.technical_skills),
    ...asArray(t.core_skills),
    ...asArray(t.key_skills),
    ...asArray(t.tools),
    ...specialisationTags(t),
    ...Object.keys(t.skill_level_map || {}),
    ...String(t.technologies || '').split(/[,;|\n]/),
  ]).slice(0, 12)
}

function trainerRating(t) {
  const ratingFields = [
    t.rating,
    t.trainer_rating,
    t.average_rating,
    t.feedback_rating,
    t.review_rating,
    t.star_rating,
  ]
  const explicitRating = ratingFields.find(value => Number.isFinite(Number(value)) && Number(value) > 0)
  if (explicitRating != null) {
    let explicit = Number(explicitRating) || 0
    if (explicit > 5) explicit /= 20
    else if (explicit > 0 && explicit <= 1) explicit *= 5
    return Math.max(0, Math.min(5, Math.round(explicit * 10) / 10))
  }

  const skills = technologyList(t)
  const hasContact = [t.email, t.phone, t.linkedin, t.teams_email, t.microsoft_teams_email, t.teams_upn].some(hasProfileValue)
  const hasExperience = hasProfileValue(t.experience_raw) || Number(t.experience_years || 0) > 0
  const hasSummary = hasProfileValue(t.summary) || hasProfileValue(t.objective)
  const hasCategory = hasProfileValue(primaryCategory(t)) && primaryCategory(t).toLowerCase() !== 'uncategorised'
  if (!skills.length && !hasContact && !hasSummary && !hasCategory) return 0

  const profileChecks = [
    !isBadTrainerName(t?.display_name || t?.name || t?.role_designation),
    hasContact,
    skills.length > 0,
    hasCategory,
    hasExperience,
    hasSummary,
  ]
  const profileRatio = profileChecks.filter(Boolean).length / profileChecks.length
  let rating = 2.8 + (profileRatio * 1.2)
  if (skills.length >= 8) rating += 0.4
  else if (skills.length >= 4) rating += 0.25
  if (hasExperience) rating += 0.15
  if (hasContact) rating += 0.15

  const score = Math.max(Number(t.resume_rank_score || 0), Number(t.match_score || 0))
  if (score >= 40) rating = Math.max(rating, score / 20)
  return Math.max(0, Math.min(5, Math.round(rating * 10) / 10))
}

function TrainerRatingStars({ trainer }) {
  const rating = trainerRating(trainer)
  const filledStars = Math.round(rating)
  const label = rating > 0 ? `${rating.toFixed(1)} / 5` : 'Not rated'

  return (
    <div className="inline-flex items-center gap-1 rounded-full border border-amber-100 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700" title={`Trainer rating: ${label}`}>
      <span className="flex items-center gap-0.5" aria-hidden="true">
        {[1, 2, 3, 4, 5].map(item => (
          <Star
            key={item}
            className={clsx('h-3.5 w-3.5', item <= filledStars ? 'fill-amber-400 text-amber-400' : 'text-amber-200')}
          />
        ))}
      </span>
      <span>{label}</span>
    </div>
  )
}

function compactResumeText(value) {
  if (!value) return ''
  const text = String(value).trim()
  if (/^https?:\/\//i.test(text)) return ''
  return text.length > 520 ? `${text.slice(0, 520).trim()}...` : text
}

const BAD_TRAINER_NAMES = new Set([
  'professional summary',
  'trainer profile',
  'profile summary',
  'career summary',
  'executive summary',
  'resume details',
  'summary',
  'profile',
  'objective',
  'skills',
  'technical skills',
  'technologies',
  'cloud',
])

function titleFromText(value) {
  return String(value || '')
    .replace(/\.[^.]+$/, '')
    .replace(/\b(resume|cv|profile|trainer)\b/gi, ' ')
    .replace(/[_\-+.]+/g, ' ')
    .replace(/\d+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}

function normalizeTrainerText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function isDuplicateTrainerText(value, trainer) {
  const text = normalizeTrainerText(value).toLowerCase()
  if (!text) return false
  const candidates = [
    trainer?.display_name,
    trainer?.name,
    trainer?.role_designation,
    trainer?.summary,
    trainer?.technologies,
    trainer?.objective,
  ].map(normalizeTrainerText).filter(Boolean)
  return candidates.some(candidate => candidate.toLowerCase() === text && candidate !== normalizeTrainerText(value))
}

function hasProfileValue(value) {
  if (Array.isArray(value)) return value.some(item => hasProfileValue(item))
  const text = normalizeTrainerText(value)
  if (!text) return false
  return !['-', 'na', 'n/a', 'none', 'null', 'unknown'].includes(text.toLowerCase())
}

function uniqueCompact(values) {
  const seen = new Set()
  return values
    .map(normalizeTrainerText)
    .filter(Boolean)
    .filter(item => {
      const key = item.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function joinPhrase(items) {
  const values = uniqueCompact(items)
  if (values.length <= 1) return values[0] || ''
  if (values.length === 2) return `${values[0]} and ${values[1]}`
  return `${values.slice(0, -1).join(', ')}, and ${values[values.length - 1]}`
}

function trainerSubtitleText(t) {
  const category = primaryCategory(t)
  const role = normalizeTrainerText(t.role_designation)
  const experience = t.experience_raw || (t.experience_years ? `${t.experience_years}+ years` : '')
  return uniqueCompact([role || category, experience, t.location]).join(' | ') || category
}

function isBadTrainerName(value) {
  const clean = String(value || '').trim()
  const normalized = clean.toLowerCase().replace(/[^a-z\s]/g, ' ').replace(/\s+/g, ' ').trim()
  if (!normalized) return true
  if (BAD_TRAINER_NAMES.has(normalized)) return true
  if (/resume extracted|skills found|certifications found|summary excerpt/i.test(clean)) return true
  if (/^professional\s+summary\b/i.test(clean)) return true
  return false
}

function trainerDisplayName(t) {
  if (!isBadTrainerName(t?.display_name)) return String(t.display_name).trim()
  if (!isBadTrainerName(t?.name)) return String(t.name).trim()
  if (!isBadTrainerName(t?.role_designation)) return String(t.role_designation).trim()
  const emailName = titleFromText(String(t?.email || '').split('@')[0])
  if (emailName && !isBadTrainerName(emailName)) return emailName
  const fileName = titleFromText(t?.filename || t?.source_filename || '')
  if (fileName && !isBadTrainerName(fileName)) return fileName
  return t?.trainer_id ? `Trainer ${t.trainer_id}` : 'Trainer'
}

function trainerInitial(t) {
  return trainerDisplayName(t).charAt(0).toUpperCase()
}

function cleanProfileText(value) {
  return normalizeTrainerText(value)
    .replace(/^resume\s+extracted\s*:\s*/i, '')
    .replace(/^resume\s+summary\s+excerpt\s*:\s*/i, '')
    .replace(/^professional\s+summary\s*:\s*/i, '')
}

function truncateText(value, max = 280) {
  const text = cleanProfileText(value)
  return text.length > max ? `${text.slice(0, max).trim()}...` : text
}

function objectiveRole(t) {
  const role = cleanProfileText(t.role_designation)
  if (role && !isBadTrainerName(role) && role.length <= 90) {
    return role.replace(/\s*\|\s*/g, ' and ')
  }
  const category = primaryCategory(t)
  const tags = specialisationTags(t).filter(tag => !String(tag).match(/trainer|training/i))
  const roleParts = uniqueCompact([category, ...tags]).slice(0, 2)
  return joinPhrase(roleParts) || 'Technology Professional'
}

function objectiveWorkAreas(skills) {
  const text = skills.join(' ').toLowerCase()
  const areas = []
  if (/react|javascript|typescript|html|css|frontend|full stack|mern|node|django|fastapi|flask|web/.test(text)) {
    areas.push('web applications')
  }
  if (/api|fastapi|flask|django|spring|node|express|rest/.test(text)) {
    areas.push('REST APIs')
  }
  if (/power bi|tableau|dashboard|analytics|excel|sql|data/.test(text)) {
    areas.push('interactive dashboards')
  }
  if (/trainer|training|corporate|faculty|instructor/.test(text)) {
    areas.push('hands-on training programs')
  }
  return areas.length ? areas : ['real-world technology solutions']
}

function objectiveStrengths(skills) {
  const text = skills.join(' ').toLowerCase()
  const strengths = []
  if (/ai|machine learning|ml|gen ai|generative|llm|prompt/.test(text)) strengths.push('AI-powered solutions')
  if (/data|sql|analytics|analysis|power bi|tableau|visualization|visualisation/.test(text)) strengths.push('data analysis and visualization')
  if (/react|javascript|python|fastapi|flask|mongo|sql|full stack|mern/.test(text)) strengths.push('scalable application development')
  return strengths.length ? strengths : ['problem solving and practical delivery']
}

function objectiveInterests(skills) {
  const text = skills.join(' ').toLowerCase()
  const interests = []
  if (/machine learning|ml/.test(text)) interests.push('Machine Learning')
  if (/gen ai|generative|llm|prompt/.test(text)) interests.push('Generative AI')
  if (/data|analytics|analysis|sql|power bi/.test(text)) interests.push('data-driven problem solving')
  if (/cloud|devops|aws|azure|docker|kubernetes/.test(text)) interests.push('cloud and automation')
  return interests
}

function trainerDescription(t) {
  const objective = !isDuplicateTrainerText(t.objective, t) ? truncateText(t.objective, 520) : ''
  if (objective) return objective

  const skills = technologyList(t)
  const category = primaryCategory(t)
  const summary = !isDuplicateTrainerText(t.summary, t) ? truncateText(t.summary, 220) : ''
  const role = objectiveRole(t)
  const skillPhrase = joinPhrase(skills.slice(0, 9))
  const workAreas = objectiveWorkAreas([role, category, ...skills])
  const strengths = objectiveStrengths([role, category, ...skills])
  const interests = objectiveInterests([role, category, ...skills])
  const parts = []

  parts.push(`${role}${skillPhrase ? ` with hands-on experience in ${skillPhrase}` : ''}.`)
  parts.push(`Experienced in developing ${joinPhrase(workAreas)} using practical, real-world scenarios.`)
  parts.push(`Skilled in ${joinPhrase(strengths)}${interests.length ? `, with a strong interest in ${joinPhrase(interests)}` : ''}.`)
  parts.push('Passionate about building scalable applications and delivering impactful technology solutions.')
  if (summary) parts.push(summary)

  return parts.join(' ') || `${trainerDisplayName(t)} is listed for ${category}. Add skills, contact details, and an objective to complete this database profile.`
}

function trainerProfileQuality(t) {
  const category = primaryCategory(t)
  const checks = [
    { key: 'name', label: 'name', ok: !isBadTrainerName(t?.display_name || t?.name || t?.role_designation) },
    { key: 'email', label: 'email', ok: hasProfileValue(t.email) },
    { key: 'phone', label: 'phone', ok: hasProfileValue(t.phone) },
    { key: 'linkedin', label: 'LinkedIn', ok: hasProfileValue(t.linkedin) },
    { key: 'skills', label: 'skills', ok: technologyList(t).length > 0 },
    { key: 'category', label: 'category', ok: hasProfileValue(category) && category.toLowerCase() !== 'uncategorised' },
    { key: 'experience', label: 'experience', ok: hasProfileValue(t.experience_raw) || Number(t.experience_years || 0) > 0 },
    { key: 'summary', label: 'summary', ok: hasProfileValue(t.summary) || hasProfileValue(t.objective) },
  ]
  const completed = checks.filter(item => item.ok).length
  return {
    completed,
    total: checks.length,
    percent: Math.round((completed / checks.length) * 100),
    missing: checks.filter(item => !item.ok).map(item => item.label),
  }
}

function trainerContactChannels(t) {
  return [
    { key: 'email', label: 'Email', value: t.email, Icon: Mail, tone: 'text-blue-600 bg-blue-50 border-blue-100' },
    { key: 'phone', label: 'Phone', value: t.phone, Icon: Phone, tone: 'text-emerald-600 bg-emerald-50 border-emerald-100' },
    { key: 'linkedin', label: 'LinkedIn', value: t.linkedin && t.linkedin !== '-' ? t.linkedin : '', Icon: Linkedin, tone: 'text-sky-600 bg-sky-50 border-sky-100' },
    { key: 'teams', label: 'Teams', value: t.teams_email || t.microsoft_teams_email || t.teams_upn, Icon: MessageSquare, tone: 'text-indigo-600 bg-indigo-50 border-indigo-100' },
  ].filter(item => hasProfileValue(item.value))
}

function TrainerPipelinePanel({ trainer, onStartAutomation, sendingAutomation }) {
  const clientEmail = trainer.last_automation_client_email || trainer.client_email || ''
  const clientName = trainer.last_automation_client_name || trainer.client_name || ''
  const mailStageByType = {
    mail1: 1,
    mail2: 2,
    mail2_followup: 2,
    mail3: 3,
    mail4: 4,
    mail5_ok: 5,
    mail5_no: 5,
    mail6_toc: 6,
    mail7_confirm: 7,
  }
  const statusStageByType = {
    contacted: 1,
    interested: 1,
    pending_review: 2,
    interview_scheduled: 4,
    selected: 5,
    rejected: 5,
    toc_requested: 6,
    training_confirmed: 7,
    confirmed: 7,
  }
  const currentStage = Math.max(
    mailStageByType[trainer.last_automation_mail_type] || 0,
    statusStageByType[trainer.status] || 0
  )
  const isRejected = trainer.status === 'rejected' || trainer.last_automation_mail_type === 'mail5_no'
  const stageState = step => {
    if (!currentStage) return 'pending'
    if (isRejected && step === 5) return 'rejected'
    if (step < currentStage) return 'done'
    if (step === currentStage) return currentStage === 7 ? 'done' : 'current'
    return 'pending'
  }
  const stateLabel = state => ({
    done: 'Completed',
    current: 'Current',
    rejected: 'Rejected',
    pending: 'Pending',
  }[state] || 'Pending')
  const stages = [
    { step: 1, code: '01', title: 'Mail 1', desc: 'First contact / interest check' },
    { step: 2, code: '02', title: 'Mail 2', desc: 'Details request and follow-up' },
    { step: 3, code: '03', title: 'Mail 3', desc: 'Interview slot booking' },
    { step: 4, code: '04', title: 'Mail 4', desc: 'Interview schedule/link' },
    { step: 5, code: '05', title: 'Mail 5', desc: 'Selection or rejection update' },
    { step: 6, code: '06', title: 'Mail 6', desc: 'ToC / agenda request' },
    { step: 7, code: '07', title: 'Mail 7', desc: 'Training confirmation' },
  ]
  const stateClass = {
    done: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    current: 'border-blue-200 bg-blue-50 text-blue-700 ring-2 ring-blue-100',
    rejected: 'border-red-200 bg-red-50 text-red-700',
    pending: 'border-slate-200 bg-slate-50 text-slate-500',
  }
  const statusText = currentStage
    ? `${stages.find(item => item.step === currentStage)?.title || 'Pipeline'} ${isRejected ? 'rejected' : currentStage === 7 ? 'completed' : 'in progress'}`
    : 'Not started'

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Trainer Pipeline</p>
          <h3 className="mt-1 text-sm font-bold text-slate-900">7-stage automation status for this person</h3>
          <p className="mt-1 text-xs text-slate-500">
            Automation mail uses {trainer.email ? <span className="font-semibold text-slate-700">{trainer.email}</span> : 'this trainer email'}.
          </p>
          {trainer.last_automation_mail_type && (
            <p className="mt-1 text-xs text-slate-500">
              Last sent: <span className="font-semibold text-slate-700">{trainer.last_automation_mail_type}</span>
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className={clsx(
            'rounded-lg border px-3 py-2 text-xs',
            isRejected ? 'border-red-200 bg-red-50 text-red-700' :
            currentStage ? 'border-blue-200 bg-blue-50 text-blue-700' :
                           'border-slate-200 bg-slate-50 text-slate-600'
          )}>
            Status: <span className="font-bold capitalize">{statusText}</span>
          </div>
          <button
            type="button"
            onClick={() => onStartAutomation(trainer)}
            disabled={sendingAutomation}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-blue-700 disabled:opacity-60"
          >
            {sendingAutomation ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            Start Automation
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {stages.map(item => {
          const state = stageState(item.step)
          return (
          <div key={item.step} className={clsx('rounded-lg border px-3 py-2.5', stateClass[state])}>
            <div className="flex items-center gap-2">
              <span className="flex h-6 min-w-6 items-center justify-center rounded-md bg-white px-1 text-[11px] font-black">
                {state === 'done' ? 'OK' : state === 'rejected' ? 'NO' : item.code}
              </span>
              <span className="text-sm font-bold">{item.title}</span>
              <span className="ml-auto rounded-full bg-white px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                {stateLabel(state)}
              </span>
            </div>
            <p className="mt-1 text-xs leading-5 opacity-80">{item.desc}</p>
          </div>
          )
        })}
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2">
          <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Client Mail</p>
          <p className="mt-0.5 truncate text-xs font-semibold text-blue-700">{clientEmail || 'Add in automation popup'}</p>
          {clientName && <p className="mt-0.5 truncate text-[11px] text-cyan-600">{clientName}</p>}
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Email</p>
          <p className="mt-0.5 truncate text-xs font-semibold text-slate-700">{trainer.email || 'Missing'}</p>
        </div>
        <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2">
          <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">WhatsApp</p>
          <p className="mt-0.5 truncate text-xs font-semibold text-emerald-700">{trainer.phone || 'Phone missing'}</p>
        </div>
        <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-2 sm:col-span-3">
          <p className="text-[11px] font-bold uppercase tracking-wide text-indigo-700">Teams</p>
          <p className="mt-0.5 truncate text-xs font-semibold text-indigo-700">{trainer.teams_email || trainer.microsoft_teams_email || trainer.teams_upn || trainer.email || 'Not set'}</p>
        </div>
      </div>
    </div>
  )
}

function formatThreadTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString([], {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function threadDirectionLabel(msg) {
  if (msg.direction === 'received') return 'Trainer replied'
  if (msg.direction === 'client_sent') return 'Sent to client'
  if (msg.direction === 'client_received') return 'Client replied'
  return 'Sent to trainer'
}

function threadTone(msg) {
  if (msg.direction === 'received') return 'border-emerald-100 bg-emerald-50/70'
  if (msg.direction === 'client_sent') return 'border-blue-100 bg-blue-50/70'
  if (msg.direction === 'client_received') return 'border-amber-100 bg-amber-50/70'
  return 'border-blue-100 bg-blue-50/70'
}

function TrainerConversationThread({ trainer }) {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadThread = useCallback(async () => {
    if (!trainer?.trainer_id) return
    setLoading(true)
    setError('')
    try {
      const res = await getTrainerConversationThread(trainer.trainer_id, { _ts: Date.now() })
      setMessages(res.data?.messages || [])
    } catch (err) {
      setError(err.message || 'Could not load conversation thread')
    } finally {
      setLoading(false)
    }
  }, [trainer?.trainer_id])

  useEffect(() => {
    loadThread()
  }, [loadThread])

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Conversation Thread</p>
          <p className="mt-0.5 text-xs text-slate-500">Trainer mails, replies, client slot messages, and interview schedule updates.</p>
        </div>
        <button
          type="button"
          onClick={loadThread}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-60"
        >
          <RefreshCw className={clsx('h-3.5 w-3.5', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs font-medium text-red-600">{error}</p>}
      {!error && loading && !messages.length && (
        <div className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">
          <RefreshCw className="h-4 w-4 animate-spin" />
          Loading conversation...
        </div>
      )}
      {!error && !loading && !messages.length && (
        <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">No conversation yet for this trainer.</p>
      )}
      {messages.length > 0 && (
        <div className="max-h-80 space-y-3 overflow-y-auto pr-1">
          {messages.map((msg, index) => (
            <div key={`${msg.email_id || index}-${msg.sent_at || index}`} className={clsx('rounded-xl border p-3', threadTone(msg))}>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-bold text-slate-800">{threadDirectionLabel(msg)}</span>
                  {msg.mail_type && <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-500">{msg.mail_type}</span>}
                  {msg.status && <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-500">{msg.status}</span>}
                </div>
                <span className="text-[11px] font-medium text-slate-500">{formatThreadTime(msg.sent_at)}</span>
              </div>
              {msg.subject && <p className="mb-1 text-xs font-semibold text-slate-700">{msg.subject}</p>}
              {msg.to_email && <p className="mb-1 text-[11px] text-slate-500">To: {msg.to_email}</p>}
              {msg.client_email && msg.direction?.startsWith('client') && (
                <p className="mb-1 text-[11px] text-blue-700">Client: {msg.client_name || 'Client'} ({msg.client_email})</p>
              )}
              {msg.slot_ref && <p className="mb-1 text-[11px] text-slate-500">Slot ref: {msg.slot_ref}</p>}
              <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{msg.body || 'No body saved.'}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function TrainerDetail({ t, onClose, onUpdate, onRequestResume, onStartAutomation, requestingResume, sendingAutomation }) {
  const displayName = trainerDisplayName(t)
  const category = primaryCategory(t)
  const tags = specialisationTags(t)
  const industries = asArray(t.industry_focus)
  const deliveryLanguages = asArray(t.language_of_delivery)
  const levels = skillLevels(t)
  const resumeText = compactResumeText(t.resume)
  const pastClients = asArray(t.past_clients)
  const quality = trainerProfileQuality(t)
  const contactChannels = trainerContactChannels(t)
  const profileSkills = technologyList(t)
  const profileSummary = trainerDescription(t)
  const extractedObjective = !isDuplicateTrainerText(t.objective, t) ? truncateText(t.objective, 520) : ''
  const headline = trainerSubtitleText(t)
  const [teamsEmail, setTeamsEmail] = useState(t.teams_email || t.microsoft_teams_email || t.teams_upn || '')
  const [savingTeams, setSavingTeams] = useState(false)
  const [showSingleShortlist, setShowSingleShortlist] = useState(false)

  useEffect(() => {
    setTeamsEmail(t.teams_email || t.microsoft_teams_email || t.teams_upn || '')
  }, [t])

  const saveTeamsEmail = async () => {
    setSavingTeams(true)
    try {
      await onUpdate(t.trainer_id, {
        teams_email: teamsEmail,
        microsoft_teams_email: teamsEmail,
        teams_upn: teamsEmail,
      })
      toast.success('Teams email saved')
    } catch (error) {
      toast.error(error.message || 'Could not save Teams email')
    } finally {
      setSavingTeams(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-3 sm:p-5 bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-card-lg w-full max-w-3xl max-h-[calc(100vh-1.5rem)] sm:max-h-[calc(100vh-2.5rem)] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between p-5 border-b border-slate-100 bg-white flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-100 to-blue-50 flex items-center justify-center flex-shrink-0">
              <span className="font-jakarta font-bold text-blue-600 text-lg">{trainerInitial(t)}</span>
            </div>
            <div className="min-w-0">
              <h2 className="font-jakarta font-bold text-slate-900 text-lg truncate">{displayName}</h2>
              <div className="flex flex-wrap gap-1 mt-1">
                <span className={clsx('text-xs', STATUS_COLORS[t.status] || 'badge-slate')}>{t.status || 'new'}</span>
                <span className={clsx('px-2 py-0.5 rounded-full border text-xs font-semibold', domainBadge(t.domain))}>
                  {category}
                </span>
                {t.needs_review && <span className="badge-yellow text-xs">Needs review</span>}
              </div>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-xl transition-colors" aria-label="Close trainer detail">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        <div className="p-5 space-y-5 overflow-y-auto flex-1">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <p className="eyebrow mb-1">Professional Objective</p>
                <h3 className="text-base font-bold text-slate-900">{headline}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-700">{profileSummary}</p>
                {quality.missing.length > 0 && (
                  <p className="mt-2 text-xs text-slate-500">
                    Missing: {quality.missing.slice(0, 4).join(', ')}{quality.missing.length > 4 ? ` +${quality.missing.length - 4}` : ''}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setShowSingleShortlist(value => !value)}
                className={clsx(
                  'flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-bold transition-colors',
                  showSingleShortlist
                    ? 'bg-blue-600 text-white hover:bg-blue-700'
                    : 'bg-white text-blue-600 border border-blue-100 hover:bg-blue-50'
                )}
              >
                <Sparkles className="h-4 w-4" />
                {showSingleShortlist ? 'Hide Pipeline' : 'Open Pipeline'}
              </button>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[
                ['Profile score', `${quality.percent}%`, `${quality.completed}/${quality.total} fields`],
                ['Contact', `${contactChannels.length}`, 'channels saved'],
                ['Skills', `${profileSkills.length}`, 'profile skills'],
                ['Rating', trainerRating(t) ? trainerRating(t).toFixed(1) : 'New', 'trainer score'],
              ].map(([label, value, sub]) => (
                <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{label}</p>
                  <p className="mt-1 text-lg font-black text-slate-900">{value}</p>
                  <p className="text-[11px] text-slate-400">{sub}</p>
                </div>
              ))}
            </div>

            {contactChannels.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {contactChannels.map(({ key, label, Icon, tone }) => (
                  <span key={key} className={clsx('inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold', tone)}>
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </span>
                ))}
              </div>
            )}
          </div>

          {showSingleShortlist && (
            <div className="space-y-4 rounded-2xl border border-blue-100 bg-blue-50/40 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-bold uppercase tracking-wider text-blue-700">Single Trainer Pipeline</p>
                  <p className="mt-0.5 text-xs text-blue-600">Use this only when a client requirement is ready for this trainer.</p>
                </div>
                <button
                  type="button"
                  onClick={() => onStartAutomation(t)}
                  disabled={sendingAutomation}
                  className="flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {sendingAutomation ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Start Automation
                </button>
              </div>
              <TrainerPipelinePanel trainer={t} onStartAutomation={onStartAutomation} sendingAutomation={sendingAutomation} />
              <TrainerConversationThread trainer={t} />
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {t.email && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl min-w-0">
                <Mail className="w-4 h-4 text-blue-600 flex-shrink-0" />
                <a href={`mailto:${t.email}`} className="text-sm text-slate-700 hover:text-blue-600 truncate">{t.email}</a>
              </div>
            )}
            {t.phone && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl">
                <Phone className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                <span className="text-sm text-slate-700">{t.phone}</span>
              </div>
            )}
            {(t.teams_email || t.microsoft_teams_email || t.teams_upn) && (
              <div className="flex items-center gap-2 p-3 bg-indigo-50 rounded-xl min-w-0">
                <MessageSquare className="w-4 h-4 text-indigo-500 flex-shrink-0" />
                <span className="text-sm text-indigo-700 truncate">{t.teams_email || t.microsoft_teams_email || t.teams_upn}</span>
              </div>
            )}
            {t.location && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl">
                <MapPin className="w-4 h-4 text-amber-500 flex-shrink-0" />
                <span className="text-sm text-slate-700">{t.location}</span>
              </div>
            )}
            {(t.experience_raw || t.experience_years) && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl">
                <Clock className="w-4 h-4 text-purple-500 flex-shrink-0" />
                <span className="text-sm text-slate-700">{t.experience_raw || `${t.experience_years} years`}</span>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-4">
            <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wider mb-2">Microsoft Teams Direct Chat</p>
            {t.email && (
              <p className="mb-2 text-xs text-indigo-600">
                Resume email found: <span className="font-semibold">{t.email}</span>. Use Teams override only after confirming the real Teams account.
              </p>
            )}
            <div className="flex flex-col sm:flex-row gap-2">
              <div className="relative flex-1">
                <MessageSquare className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-indigo-400" />
                <input
                  type="email"
                  value={teamsEmail}
                  onChange={e => setTeamsEmail(e.target.value)}
                  placeholder="Optional Teams email override"
                  className="w-full rounded-xl border border-indigo-100 bg-white pl-9 pr-3 py-2.5 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300"
                />
              </div>
              <button
                type="button"
                onClick={saveTeamsEmail}
                disabled={savingTeams}
                className="flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60"
              >
                {savingTeams ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                Save Teams
              </button>
            </div>
            <p className="mt-2 text-xs text-indigo-500">The app will not treat a resume email as verified Teams ID. Add an override only when Teams uses a confirmed email.</p>
          </div>

          {tags.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Specialisation</p>
              <div className="flex flex-wrap gap-2">
                {tags.map(tag => <span key={tag} className="badge-purple text-xs">{tag}</span>)}
              </div>
            </div>
          )}

          {t.technologies && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Technologies</p>
              <p className="text-sm text-slate-700 bg-slate-50 rounded-xl p-3 leading-relaxed">{t.technologies}</p>
            </div>
          )}

          {extractedObjective && extractedObjective !== profileSummary && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Extracted Objective</p>
              <p className="text-sm text-slate-700 bg-slate-50 rounded-xl p-3 leading-relaxed whitespace-pre-wrap">{extractedObjective}</p>
            </div>
          )}

          {resumeText && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Resume Snapshot</p>
              <p className="text-sm text-slate-700 bg-slate-50 rounded-xl p-3 leading-relaxed whitespace-pre-wrap">{resumeText}</p>
            </div>
          )}

          {profileSkills.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Skills</p>
              <div className="flex flex-wrap gap-2">
                {profileSkills.map(skill => <span key={skill} className="badge-blue text-xs">{skill}</span>)}
              </div>
            </div>
          )}

          {levels.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Skill Levels</p>
              <div className="flex flex-wrap gap-2">
                {levels.map(([skill, level]) => (
                  <span key={skill} className={clsx('px-2.5 py-1 rounded-full border text-xs font-semibold', levelBadge(level))}>
                    {skill}: {level}
                  </span>
                ))}
              </div>
            </div>
          )}

          {(deliveryLanguages.length > 0 || industries.length > 0) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {deliveryLanguages.length > 0 && (
                <div className="flex items-start gap-2 p-3 bg-slate-50 rounded-xl">
                  <Languages className="w-4 h-4 text-teal-500 mt-0.5 flex-shrink-0" />
                  <span className="text-sm text-slate-700">{deliveryLanguages.join(', ')}</span>
                </div>
              )}
              {industries.length > 0 && (
                <div className="flex items-start gap-2 p-3 bg-slate-50 rounded-xl">
                  <Briefcase className="w-4 h-4 text-orange-500 mt-0.5 flex-shrink-0" />
                  <span className="text-sm text-slate-700">{industries.join(', ')}</span>
                </div>
              )}
            </div>
          )}

          {asArray(t.certifications).length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Certifications</p>
              <div className="flex flex-wrap gap-2">
                {asArray(t.certifications).map(cert => (
                  <span key={cert} className="flex items-center gap-1 badge bg-amber-50 text-amber-700 text-xs">
                    <Award className="w-3 h-3" /> {cert}
                  </span>
                ))}
              </div>
            </div>
          )}

          {pastClients.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Past Clients / Training Exposure</p>
              <div className="flex flex-wrap gap-2">
                {pastClients.map(client => <span key={client} className="badge-slate text-xs">{client}</span>)}
              </div>
            </div>
          )}

          {t.reasoning && (
            <p className="text-sm text-slate-600 bg-slate-50 rounded-xl p-3">{t.reasoning}</p>
          )}

          <div className="flex flex-wrap gap-3 pt-2">
            <button
              type="button"
              onClick={() => setShowSingleShortlist(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-50 text-blue-600 rounded-xl text-sm font-medium hover:bg-blue-100 transition-colors disabled:opacity-60"
            >
              <Sparkles className="w-4 h-4" />
              Single Shortlist / Pipeline
            </button>
            <button
              type="button"
              onClick={() => onRequestResume(t)}
              disabled={requestingResume}
              className="flex items-center gap-2 px-4 py-2 bg-blue-50 text-blue-600 rounded-xl text-sm font-medium hover:bg-blue-100 transition-colors disabled:opacity-60"
            >
              {requestingResume ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              Request Resume
            </button>
            {t.linkedin && t.linkedin !== '-' && (
              <a href={t.linkedin} target="_blank" rel="noreferrer"
                 className="flex items-center gap-2 px-4 py-2 bg-blue-50 text-blue-600 rounded-xl text-sm font-medium hover:bg-blue-100 transition-colors">
                <Linkedin className="w-4 h-4" /> LinkedIn Profile
              </a>
            )}
            {t.resume && t.resume !== '-' && (
              <a href={t.resume} target="_blank" rel="noreferrer"
                 className="flex items-center gap-2 px-4 py-2 bg-emerald-50 text-emerald-600 rounded-xl text-sm font-medium hover:bg-emerald-100 transition-colors">
                <FileText className="w-4 h-4" /> View Resume
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function TrainerRow({ t, onDelete, onView, onRecategorise, onRequestResume, onStartAutomation, recategorising, requestingResume, sendingAutomation }) {
  const displayName = trainerDisplayName(t)
  const category = primaryCategory(t)
  const tags = specialisationTags(t)
  const industries = asArray(t.industry_focus)
  const deliveryLanguages = asArray(t.language_of_delivery)
  const levels = skillLevels(t)
  const skills = technologyList(t)
  const quality = trainerProfileQuality(t)
  const contactChannels = trainerContactChannels(t)
  const profileSummary = trainerDescription(t)

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onView(t)}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onView(t)
        }
      }}
      className="card-hover cursor-pointer p-4 flex items-start gap-4 animate-fade-in group focus:outline-none focus:ring-2 focus:ring-blue-500/30"
    >
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onView(t) }}
        className="w-11 h-11 rounded-xl bg-gradient-to-br from-blue-100 to-blue-50 flex items-center justify-center flex-shrink-0 hover:from-blue-200 hover:to-blue-100 transition-all"
        aria-label={`View ${displayName}`}
      >
        <span className="font-jakarta font-bold text-blue-600 text-base">{trainerInitial(t)}</span>
      </button>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <button type="button" className="text-left min-w-0 flex-1" onClick={(e) => { e.stopPropagation(); onView(t) }}>
            <h3 className="font-medium text-slate-900 group-hover:text-blue-600 transition-colors truncate">{displayName}</h3>
            <p className="text-xs text-slate-400 mt-0.5 line-clamp-1">{trainerSubtitleText(t)}</p>
            <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600">{profileSummary}</p>
            {tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tags.slice(0, 3).map(tag => <span key={tag} className="badge-purple text-xs">{tag}</span>)}
              </div>
            )}
          </button>

          <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
            <TrainerRatingStars trainer={t} />
            <span className={clsx(
              'rounded-full border px-2.5 py-1 text-xs font-semibold',
              quality.percent >= 80 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' :
              quality.percent >= 60 ? 'border-blue-200 bg-blue-50 text-blue-700' :
                                      'border-amber-200 bg-amber-50 text-amber-700'
            )}>
              {quality.percent}% profile
            </span>
            <span className={clsx('px-2.5 py-1 rounded-full border text-xs font-semibold', domainBadge(t.domain))}>{category}</span>
            {t.match_score != null && (
              <div className={clsx(
                'w-9 h-9 rounded-lg flex items-center justify-center text-sm font-bold',
                t.match_score >= 80 ? 'bg-emerald-100 text-emerald-700' :
                t.match_score >= 60 ? 'bg-blue-100 text-blue-700' :
                t.match_score >= 40 ? 'bg-amber-100 text-amber-700' :
                'bg-slate-100 text-slate-500'
              )}>
                {Math.round(t.match_score)}
              </div>
            )}
            <span className={STATUS_COLORS[t.status] || 'badge-slate'}>{t.status || 'new'}</span>
            <TrainerCardTrustPill trainer={t} />
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          {(t.experience_raw || t.experience_years) && <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {t.experience_raw || `${t.experience_years} years`}</span>}
          {t.location && <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> {t.location}</span>}
          {t.email && <span className="flex items-center gap-1 min-w-0"><Mail className="w-3.5 h-3.5 flex-shrink-0" /> <span className="truncate">{t.email}</span></span>}
          {(t.teams_email || t.microsoft_teams_email || t.teams_upn) && (
            <span className="flex items-center gap-1 min-w-0 text-indigo-600">
              <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
              <span className="truncate">{t.teams_email || t.microsoft_teams_email || t.teams_upn}</span>
            </span>
          )}
          {t.phone && <span className="flex items-center gap-1"><Phone className="w-3.5 h-3.5" /> {t.phone}</span>}
        </div>

        {contactChannels.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {contactChannels.map(({ key, label, Icon, tone }) => (
              <span key={key} className={clsx('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold', tone)}>
                <Icon className="h-3 w-3" />
                {label}
              </span>
            ))}
          </div>
        )}

        {skills.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {skills.slice(0, 6).map(skill => <span key={skill} className="badge-slate text-xs">{skill}</span>)}
            {skills.length > 6 && <span className="badge-slate text-xs">+{skills.length - 6}</span>}
          </div>
        )}

        {levels.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {levels.map(([skill, level]) => (
              <span key={skill} className={clsx('px-2 py-0.5 rounded-full border text-[11px] font-semibold', levelBadge(level))}>
                {skill}: {level}
              </span>
            ))}
          </div>
        )}

        {(deliveryLanguages.length > 0 || industries.length > 0) && (
          <div className="mt-3 grid grid-cols-1 lg:grid-cols-2 gap-2 text-xs text-slate-500">
            {deliveryLanguages.length > 0 && (
              <span className="flex items-center gap-1.5 min-w-0">
                <Languages className="w-3.5 h-3.5 text-teal-500 flex-shrink-0" />
                <span className="truncate">{deliveryLanguages.join(', ')}</span>
              </span>
            )}
            {industries.length > 0 && (
              <span className="flex items-center gap-1.5 min-w-0">
                <Briefcase className="w-3.5 h-3.5 text-orange-500 flex-shrink-0" />
                <span className="truncate">{industries.join(', ')}</span>
              </span>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2 flex-shrink-0">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onStartAutomation(t) }}
          disabled={sendingAutomation}
          className="p-2 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all disabled:opacity-50"
          title="Start automation pipeline"
          aria-label={`Start automation pipeline for ${displayName}`}
        >
          {sendingAutomation ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onRequestResume(t) }}
          disabled={requestingResume}
          className="p-2 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all disabled:opacity-50"
          title="Request updated resume"
          aria-label={`Request updated resume from ${displayName}`}
        >
          {requestingResume ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onView(t) }}
          className="p-2 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all"
          title="View trainer details"
          aria-label={`View details for ${displayName}`}
        >
          <Eye className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onRecategorise(t) }}
          disabled={recategorising}
          className="p-2 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all disabled:opacity-50"
          title="Re-categorise trainer"
          aria-label={`Re-categorise ${displayName}`}
        >
          <RefreshCw className={clsx('w-4 h-4', recategorising && 'animate-spin')} />
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(t) }}
          className="p-2 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-all"
          title="Delete trainer"
          aria-label={`Delete ${displayName}`}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

export default function Trainers() {
  const [trainers, setTrainers] = useState([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(1)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [domain, setDomain] = useState('')
  const [category, setCategory] = useState('')
  const [industry, setIndustry] = useState('')
  const [experience, setExperience] = useState('')
  const [profileFilter, setProfileFilter] = useState('')
  const [sortBy, setSortBy] = useState('newest')
  const [categories, setCategories] = useState([])
  const [domains, setDomains] = useState([])
  const [industries, setIndustries] = useState([])
  const [loading, setLoading] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [selectedTrainer, setSelectedTrainer] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [recategorisingId, setRecategorisingId] = useState('')
  const [resumeRequestTrainer, setResumeRequestTrainer] = useState(null)
  const [resumeRequestDomain, setResumeRequestDomain] = useState('')
  const [requestingResumeId, setRequestingResumeId] = useState('')
  const [automationMailTrainer, setAutomationMailTrainer] = useState(null)
  const [automationMode, setAutomationMode] = useState('manual')
  const [automationPollingTrainerId, setAutomationPollingTrainerId] = useState('')
  const [automationForm, setAutomationForm] = useState({
    mail_type: 'mail1',
    domain: '',
    duration: '',
    mode: 'Online',
    participants: '',
    client_name: '',
    client_email: '',
    slots: '',
    date_time: '',
    platform: 'Google Meet',
    interview_link: '',
    training_date: '',
    venue: '',
    contact_name: 'Clahan Technologies Team',
    contact_phone: '',
    contact_email: '',
    message: '',
  })
  const [sendingAutomationId, setSendingAutomationId] = useState('')
  const [categorisingAll, setCategorisingAll] = useState(false)
  const [categoryJob, setCategoryJob] = useState(null)
  const pollRef = useRef(null)

  const loadMeta = useCallback(async () => {
    try {
      const [catRes, domainRes, industryRes] = await Promise.all([
        getTrainerCategories(),
        getTrainerDomains(),
        getTrainerIndustries(),
      ])
      setCategories(catRes.data.categories || [])
      setDomains(domainRes.data.domains || [])
      setIndustries(industryRes.data.industries || [])
    } catch {
      // Filter metadata is helpful, but the trainer list can still render without it.
    }
  }, [])

  const load = useCallback(async (targetPage = page) => {
    setLoading(true)
    try {
      const res = await getTrainers({
        page: targetPage,
        limit: 15,
        search: search || undefined,
        status: status || undefined,
        domain: domain || undefined,
        category: category || undefined,
        industry: industry || undefined,
        experience: experience || undefined,
        profile_filter: profileFilter || undefined,
        sort: sortBy || undefined,
      })
      setTrainers(res.data.trainers || [])
      setTotal(res.data.total || 0)
      setPages(res.data.pages || 1)
      if (res.data.categories) setCategories(res.data.categories)
      if (res.data.domains) setDomains(res.data.domains)
      if (res.data.industries) setIndustries(res.data.industries)
    } catch (error) {
      toast.error(error.message)
    } finally {
      setLoading(false)
    }
  }, [page, search, status, domain, category, industry, experience, profileFilter, sortBy])

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current)
    pollRef.current = null
  }, [])

  const pollCategorisationJob = useCallback((jobId) => {
    stopPolling()
    const tick = async () => {
      try {
        const res = await getCategoriseJob(jobId)
        const job = res.data
        setCategoryJob(job)
        if (job.status === 'completed') {
          setCategorisingAll(false)
          toast.success(`${job.succeeded || 0} trainers categorised`)
          setPage(1)
          load(1)
          loadMeta()
          return
        }
        if (job.status === 'failed') {
          setCategorisingAll(false)
          toast.error(job.error || 'Categorisation job failed')
          return
        }
        pollRef.current = setTimeout(tick, 2500)
      } catch (error) {
        setCategorisingAll(false)
        toast.error(error.message)
      }
    }
    pollRef.current = setTimeout(tick, 1200)
  }, [load, loadMeta, stopPolling])

  useEffect(() => {
    loadMeta()
    return stopPolling
  }, [loadMeta, stopPolling])

  useEffect(() => {
    load(page)
  }, [load, page])

  useEffect(() => {
    if (!automationPollingTrainerId || !selectedTrainer || selectedTrainer.trainer_id !== automationPollingTrainerId) return undefined
    const tick = async () => {
      try {
        const res = await tickTrainerAutomationPipeline(automationPollingTrainerId, {
          domain: selectedTrainer.last_automation_mail_domain || selectedTrainer.primary_category || selectedTrainer.domain || 'Training',
          client_email: selectedTrainer.last_automation_client_email || selectedTrainer.client_email || '',
          client_name: selectedTrainer.last_automation_client_name || selectedTrainer.client_name || '',
        })
        applyUpdatedTrainer(res.data.trainer)
        if (res.data.sent_next) {
          toast.success(`${res.data.next_mail_type || 'Next mail'} sent automatically`)
        }
      } catch {
        // Keep the visible pipeline usable even if a background poll fails once.
      }
    }
    const interval = setInterval(tick, 15000)
    return () => clearInterval(interval)
  }, [automationPollingTrainerId, selectedTrainer])

  const handleSearch = (e) => {
    e.preventDefault()
    setSearch(searchInput.trim())
    setPage(1)
  }

  const handleClearFilters = () => {
    setSearch('')
    setSearchInput('')
    setStatus('')
    setDomain('')
    setCategory('')
    setIndustry('')
    setExperience('')
    setProfileFilter('')
    setSortBy('newest')
    setPage(1)
  }

  const handleDelete = async (trainer) => {
    try {
      await deleteTrainer(trainer.trainer_id)
      toast.success(`${trainerDisplayName(trainer)} deleted`)
      setConfirmDelete(null)
      load(page)
      loadMeta()
    } catch (error) {
      toast.error(error.message)
    }
  }

  const handleRecategorise = async (trainer) => {
    setRecategorisingId(trainer.trainer_id)
    try {
      const res = await categoriseTrainer(trainer.trainer_id)
      const updated = res.data.trainer
      setTrainers(prev => prev.map(item => item.trainer_id === trainer.trainer_id ? updated : item))
      setSelectedTrainer(current => current?.trainer_id === trainer.trainer_id ? updated : current)
      toast.success(`${trainerDisplayName(trainer)} categorised`)
      loadMeta()
    } catch (error) {
      toast.error(error.message)
    } finally {
      setRecategorisingId('')
    }
  }

  const handleUpdateTrainer = async (trainerId, updates) => {
    const res = await updateTrainer(trainerId, updates)
    const updated = res.data.trainer
    setTrainers(prev => prev.map(item => item.trainer_id === trainerId ? updated : item))
    setSelectedTrainer(current => current?.trainer_id === trainerId ? updated : current)
    return updated
  }

  const openResumeRequest = (trainer) => {
    if (!trainer?.email) {
      toast.error('Trainer email is required to request a resume')
      return
    }
    setResumeRequestTrainer(trainer)
    setResumeRequestDomain(domain || category || trainer.primary_category || trainer.technology_category || trainer.domain || '')
  }

  const closeResumeRequest = () => {
    if (requestingResumeId) return
    setResumeRequestTrainer(null)
    setResumeRequestDomain('')
  }

  const handleRequestResume = async () => {
    if (!resumeRequestTrainer) return
    const wantedDomain = resumeRequestDomain.trim() || resumeRequestTrainer.primary_category || resumeRequestTrainer.domain || 'Training'
    setRequestingResumeId(resumeRequestTrainer.trainer_id)
    try {
      const res = await requestTrainerResume(resumeRequestTrainer.trainer_id, {
        domain: wantedDomain,
      })
      const updated = res.data.trainer
      if (updated?.trainer_id) {
        setTrainers(prev => prev.map(item => item.trainer_id === updated.trainer_id ? updated : item))
        setSelectedTrainer(current => current?.trainer_id === updated.trainer_id ? updated : current)
      }
      toast.success(`Resume request sent to ${trainerDisplayName(resumeRequestTrainer)}`)
      setResumeRequestTrainer(null)
      setResumeRequestDomain('')
    } catch (error) {
      toast.error(error.message || 'Could not send resume request')
    } finally {
      setRequestingResumeId('')
    }
  }

  const closeAutomationMail = () => {
    if (sendingAutomationId) return
    setAutomationMailTrainer(null)
    setAutomationMode('manual')
    setAutomationForm({
      mail_type: 'mail1',
      domain: '',
      duration: '',
      mode: 'Online',
      participants: '',
      client_name: '',
      client_email: '',
      slots: '',
      date_time: '',
      platform: 'Google Meet',
      interview_link: '',
      training_date: '',
      venue: '',
      contact_name: 'Clahan Technologies Team',
      contact_phone: '',
      contact_email: '',
      message: '',
    })
  }

  const handleAutomationFormChange = (field, value) => {
    setAutomationForm(prev => ({ ...prev, [field]: value }))
  }

  const applyUpdatedTrainer = (updated) => {
    if (!updated?.trainer_id) return
    setTrainers(prev => prev.map(item => item.trainer_id === updated.trainer_id ? updated : item))
    setSelectedTrainer(current => current?.trainer_id === updated.trainer_id ? updated : current)
  }

  const startAutomationPipeline = async (trainer, overrides = {}) => {
    if (!trainer?.email) {
      toast.error('Trainer email is required to start automation')
      return
    }
    const clientEmail = overrides.client_email || trainer.last_automation_client_email || trainer.client_email || ''
    if (!clientEmail) {
      const defaultDomain = domain || category || trainer.primary_category || trainer.technology_category || trainer.domain || ''
      setAutomationMode('auto_start')
      setAutomationMailTrainer(trainer)
      setAutomationForm(prev => ({
        ...prev,
        mail_type: 'mail1',
        domain: defaultDomain || 'Training',
        client_name: trainer.last_automation_client_name || trainer.client_name || '',
        client_email: '',
      }))
      toast.error('Add client email once, then automation will start')
      return
    }

    setSendingAutomationId(trainer.trainer_id)
    try {
      const res = await tickTrainerAutomationPipeline(trainer.trainer_id, {
        ...automationForm,
        ...overrides,
        domain: overrides.domain || automationForm.domain || trainer.last_automation_mail_domain || trainer.primary_category || trainer.domain || 'Training',
        client_email: clientEmail,
        client_name: overrides.client_name || trainer.last_automation_client_name || trainer.client_name || '',
        trainer_name: trainerDisplayName(trainer),
      })
      applyUpdatedTrainer(res.data.trainer)
      if (res.data.sent_next) {
        toast.success(`${res.data.next_mail_type || 'Next mail'} sent automatically`)
      } else {
        toast.success(`Automation checked: ${res.data.reason || 'waiting for reply'}`)
      }
      setAutomationPollingTrainerId(trainer.trainer_id)
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Could not start automation')
    } finally {
      setSendingAutomationId('')
    }
  }

  const handleSendAutomationMail = async () => {
    if (!automationMailTrainer) return
    if (automationMode === 'auto_start') {
      if (!automationForm.client_email.trim()) {
        toast.error('Client email is required to start automation')
        return
      }
      await startAutomationPipeline(automationMailTrainer, {
        ...automationForm,
        client_email: automationForm.client_email.trim(),
        client_name: automationForm.client_name.trim(),
      })
      setAutomationMailTrainer(null)
      setAutomationMode('manual')
      return
    }
    const trainerId = automationMailTrainer.trainer_id
    setSendingAutomationId(trainerId)
    try {
      const res = await sendTrainerAutomationMail(trainerId, {
        ...automationForm,
        domain: automationForm.domain.trim() || automationMailTrainer.primary_category || automationMailTrainer.domain || 'Training',
        trainer_name: trainerDisplayName(automationMailTrainer),
      })
      const updated = res.data.trainer
      if (updated?.trainer_id) {
        setTrainers(prev => prev.map(item => item.trainer_id === updated.trainer_id ? updated : item))
        setSelectedTrainer(current => current?.trainer_id === updated.trainer_id ? updated : current)
      }
      toast.success(`Automation mail sent to ${trainerDisplayName(automationMailTrainer)}`)
      setAutomationMailTrainer(null)
      setAutomationForm({
        mail_type: 'mail1',
        domain: '',
        duration: '',
        mode: 'Online',
        participants: '',
        client_name: '',
        client_email: '',
        slots: '',
        date_time: '',
        platform: 'Google Meet',
        interview_link: '',
        training_date: '',
        venue: '',
        contact_name: 'Clahan Technologies Team',
        contact_phone: '',
        contact_email: '',
        message: '',
      })
    } catch (error) {
      toast.error(error.message || 'Could not send automation mail')
    } finally {
      setSendingAutomationId('')
    }
  }

  const handleCategoriseAll = async () => {
    setCategorisingAll(true)
    setCategoryJob(null)
    try {
      const res = await categoriseAllTrainers()
      setCategoryJob({
        job_id: res.data.job_id,
        status: 'queued',
        total_pending: res.data.total_pending || 0,
        processed: 0,
        succeeded: 0,
        failed: 0,
      })
      toast.success('Categorisation job started')
      pollCategorisationJob(res.data.job_id)
    } catch (error) {
      setCategorisingAll(false)
      toast.error(error.message)
    }
  }

  const domainOptions = uniqueSorted(softwareDomainsOnly([...SOFTWARE_DOMAINS, ...domains]))
  const categoryOptions = uniqueSorted(categories)
  const industryOptions = uniqueSorted(industries)
  const activeProfileFilter = PROFILE_FILTERS.find(item => item.value === profileFilter) || PROFILE_FILTERS[0]
  const activeFilterCount = [search, status, domain, category, industry, experience, profileFilter].filter(Boolean).length

  return (
    <>
      {selectedTrainer && (
        <TrainerDetail
          t={selectedTrainer}
          onClose={() => setSelectedTrainer(null)}
          onUpdate={handleUpdateTrainer}
          onRequestResume={openResumeRequest}
          onStartAutomation={startAutomationPipeline}
          requestingResume={requestingResumeId === selectedTrainer.trainer_id}
          sendingAutomation={sendingAutomationId === selectedTrainer.trainer_id}
        />
      )}

      {automationMailTrainer && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/30 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-card-lg p-6 max-w-lg w-full max-h-[90vh] overflow-y-auto animate-slide-up">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-bold text-slate-900">{automationMode === 'auto_start' ? 'Start Automation' : 'Send Automation Mail'}</h3>
                <p className="text-sm text-slate-500 mt-1">
                  {automationMode === 'auto_start'
                    ? <>Add client details once. Mail 1 starts automatically for <strong>{trainerDisplayName(automationMailTrainer)}</strong>.</>
                    : <>Send one trainer pipeline template only to <strong>{trainerDisplayName(automationMailTrainer)}</strong>.</>}
                </p>
              </div>
              <button onClick={closeAutomationMail} className="p-2 rounded-lg hover:bg-slate-100" aria-label="Close automation mail">
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="sm:col-span-2">
                <label className="label">Pipeline Mail Template</label>
                <select
                  className="input"
                  value={automationForm.mail_type}
                  onChange={e => handleAutomationFormChange('mail_type', e.target.value)}
                  disabled={automationMode === 'auto_start'}
                >
                  {PIPELINE_MAIL_TEMPLATES.map(item => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="label">Domain / Technology</label>
                <input
                  className="input"
                  value={automationForm.domain}
                  onChange={e => handleAutomationFormChange('domain', e.target.value)}
                  placeholder="Example: Python, AWS, Data Science"
                  autoFocus
                />
              </div>
              <div>
                <label className="label">Client Name</label>
                <input
                  className="input"
                  value={automationForm.client_name}
                  onChange={e => handleAutomationFormChange('client_name', e.target.value)}
                  placeholder="Example: ABC Corp"
                />
              </div>
              <div>
                <label className="label">Client Email</label>
                <input
                  className="input"
                  type="email"
                  value={automationForm.client_email}
                  onChange={e => handleAutomationFormChange('client_email', e.target.value)}
                  placeholder="client@company.com"
                />
              </div>
              <div>
                <label className="label">Duration</label>
                <input
                  className="input"
                  value={automationForm.duration}
                  onChange={e => handleAutomationFormChange('duration', e.target.value)}
                  placeholder="Example: 2 days"
                />
              </div>
              <div>
                <label className="label">Mode</label>
                <select
                  className="input"
                  value={automationForm.mode}
                  onChange={e => handleAutomationFormChange('mode', e.target.value)}
                >
                  <option value="Online">Online</option>
                  <option value="Offline">Offline</option>
                  <option value="Hybrid">Hybrid</option>
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="label">Participants</label>
                <input
                  className="input"
                  value={automationForm.participants}
                  onChange={e => handleAutomationFormChange('participants', e.target.value)}
                  placeholder="Example: 20 learners"
                />
              </div>
              {automationForm.mail_type === 'mail3' && (
                <div className="sm:col-span-2">
                  <label className="label">Slot Options</label>
                  <textarea
                    className="input min-h-24 resize-y"
                    value={automationForm.slots}
                    onChange={e => handleAutomationFormChange('slots', e.target.value)}
                    placeholder={'Example:\n10 Jun, 11:00 AM - 11:30 AM\n11 Jun, 3:00 PM - 3:30 PM'}
                  />
                </div>
              )}
              {automationForm.mail_type === 'mail4' && (
                <>
                  <div>
                    <label className="label">Date & Time</label>
                    <input
                      className="input"
                      value={automationForm.date_time}
                      onChange={e => handleAutomationFormChange('date_time', e.target.value)}
                      placeholder="Example: 10 Jun, 11:00 AM IST"
                    />
                  </div>
                  <div>
                    <label className="label">Platform</label>
                    <input
                      className="input"
                      value={automationForm.platform}
                      onChange={e => handleAutomationFormChange('platform', e.target.value)}
                      placeholder="Google Meet"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="label">Meeting Link</label>
                    <input
                      className="input"
                      value={automationForm.interview_link}
                      onChange={e => handleAutomationFormChange('interview_link', e.target.value)}
                      placeholder="https://meet.google.com/..."
                    />
                  </div>
                </>
              )}
              {automationForm.mail_type === 'mail7_confirm' && (
                <>
                  <div>
                    <label className="label">Training Date</label>
                    <input
                      className="input"
                      value={automationForm.training_date}
                      onChange={e => handleAutomationFormChange('training_date', e.target.value)}
                      placeholder="Example: 15-16 Jun"
                    />
                  </div>
                  <div>
                    <label className="label">Venue / Platform</label>
                    <input
                      className="input"
                      value={automationForm.venue}
                      onChange={e => handleAutomationFormChange('venue', e.target.value)}
                      placeholder="Online / client platform"
                    />
                  </div>
                  <div>
                    <label className="label">Contact Name</label>
                    <input
                      className="input"
                      value={automationForm.contact_name}
                      onChange={e => handleAutomationFormChange('contact_name', e.target.value)}
                      placeholder="Clahan Technologies Team"
                    />
                  </div>
                  <div>
                    <label className="label">Contact Phone</label>
                    <input
                      className="input"
                      value={automationForm.contact_phone}
                      onChange={e => handleAutomationFormChange('contact_phone', e.target.value)}
                      placeholder="+91..."
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="label">Contact Email</label>
                    <input
                      className="input"
                      value={automationForm.contact_email}
                      onChange={e => handleAutomationFormChange('contact_email', e.target.value)}
                      placeholder="team@company.com"
                    />
                  </div>
                </>
              )}
              <div className="sm:col-span-2">
                <label className="label">Optional note</label>
                <textarea
                  className="input min-h-24 resize-y"
                  value={automationForm.message}
                  onChange={e => handleAutomationFormChange('message', e.target.value)}
                  placeholder="Optional custom note to add before the automated message"
                />
              </div>
              <div className="sm:col-span-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                <p className="font-semibold text-slate-700">Trainer Mail To</p>
                <p className="mt-1 break-words">{automationMailTrainer.email}</p>
                <p className="mt-3 font-semibold text-slate-700">Client Mail</p>
                <p className="mt-1 break-words">{automationForm.client_email || 'Not added yet'}</p>
              </div>
            </div>
            <div className="mt-5 flex gap-3">
              <button onClick={handleSendAutomationMail} disabled={!!sendingAutomationId} className="btn-primary flex-1 justify-center disabled:opacity-60">
                {sendingAutomationId ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {automationMode === 'auto_start' ? 'Start Automation' : 'Send Automation Mail'}
              </button>
              <button onClick={closeAutomationMail} disabled={!!sendingAutomationId} className="btn-secondary">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {resumeRequestTrainer && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/30 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-card-lg p-6 max-w-md w-full animate-slide-up">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-bold text-slate-900">Request Updated Resume</h3>
                <p className="text-sm text-slate-500 mt-1">
                  Send a resume/profile request to <strong>{trainerDisplayName(resumeRequestTrainer)}</strong>.
                </p>
              </div>
              <button onClick={closeResumeRequest} className="p-2 rounded-lg hover:bg-slate-100" aria-label="Close resume request">
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>
            <div className="mt-4 space-y-3">
              <div>
                <label className="label">Wanted Domain / Technology</label>
                <input
                  className="input"
                  value={resumeRequestDomain}
                  onChange={e => setResumeRequestDomain(e.target.value)}
                  placeholder="Example: Python, AWS, Data Science"
                  autoFocus
                />
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                <p className="font-semibold text-slate-700">To</p>
                <p className="mt-1 break-words">{resumeRequestTrainer.email}</p>
              </div>
            </div>
            <div className="mt-5 flex gap-3">
              <button onClick={handleRequestResume} disabled={!!requestingResumeId} className="btn-primary flex-1 justify-center disabled:opacity-60">
                {requestingResumeId ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                Send Request
              </button>
              <button onClick={closeResumeRequest} disabled={!!requestingResumeId} className="btn-secondary">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-card-lg p-6 max-w-sm w-full animate-slide-up">
            <h3 className="font-bold text-slate-900 mb-2">Delete Trainer?</h3>
            <p className="text-sm text-slate-500 mb-4">Remove <strong>{trainerDisplayName(confirmDelete)}</strong> from the database? This cannot be undone.</p>
            <div className="flex gap-3">
              <button onClick={() => handleDelete(confirmDelete)} className="btn-danger flex-1 justify-center">
                <Trash2 className="w-4 h-4" /> Delete
              </button>
              <button onClick={() => setConfirmDelete(null)} className="btn-secondary">Cancel</button>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-5 animate-fade-in">
        <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="page-title">All Trainers</h1>
          <p className="text-sm text-slate-500 mt-0.5">{total} trainers in database</p>
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center gap-2">
          {categoryJob && (
            <span className="text-xs text-slate-500">
              {categoryJob.status === 'completed'
                ? `${categoryJob.succeeded || 0} categorised, ${categoryJob.failed || 0} failed`
                : `Categorising ${categoryJob.total_pending || 0} pending trainers`}
            </span>
          )}
          <button onClick={handleCategoriseAll} disabled={categorisingAll} className="btn-primary disabled:opacity-60">
            <Sparkles className={clsx('w-4 h-4', categorisingAll && 'animate-pulse')} />
            {categorisingAll ? 'Categorising...' : 'Categorise All'}
          </button>
        </div>
        </div>

        <div className="card p-4 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
            <SlidersHorizontal className="w-4 h-4 text-slate-400" />
            Trainer database filters
            {activeFilterCount > 0 && <span className="badge-blue text-xs">{activeFilterCount} active</span>}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="font-semibold text-slate-600">{activeProfileFilter.label}</span>
            <span>{total.toLocaleString('en-IN')} matching trainers</span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-7 gap-3">
          <form onSubmit={handleSearch} className="md:col-span-2 xl:col-span-2 flex gap-2">
            <div className="relative flex-1 min-w-0">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                className="input pl-9"
                placeholder="Search name, skill, email, location"
                value={searchInput}
                onChange={e => setSearchInput(e.target.value)}
              />
            </div>
            <button type="submit" className="btn-primary px-4">Search</button>
          </form>

          <select className="input" value={domain} onChange={e => { setDomain(e.target.value); setPage(1) }}>
            <option value="">All Software Domains</option>
            {domainOptions.map(item => <option key={item} value={item}>{item}</option>)}
          </select>

          <select className="input" value={category} onChange={e => { setCategory(e.target.value); setPage(1) }}>
            <option value="">All Categories</option>
            {categoryOptions.map(item => <option key={item} value={item}>{item}</option>)}
          </select>

          <select className="input" value={industry} onChange={e => { setIndustry(e.target.value); setPage(1) }}>
            <option value="">All Industries</option>
            {industryOptions.map(item => <option key={item} value={item}>{item}</option>)}
          </select>

          <select className="input" value={experience} onChange={e => { setExperience(e.target.value); setPage(1) }}>
            {EXPERIENCE_OPTIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>

          <select className="input" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
            <option value="">All Statuses</option>
            {STATUSES.filter(Boolean).map(item => (
              <option key={item} value={item}>{item.replace('_', ' ')}</option>
            ))}
          </select>

          <select className="input" value={sortBy} onChange={e => { setSortBy(e.target.value); setPage(1) }}>
            {SORT_OPTIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <div className="flex items-center gap-1.5 pr-1 text-xs font-bold uppercase tracking-wide text-slate-400">
            <Filter className="h-3.5 w-3.5" />
            Profile quality
          </div>
          {PROFILE_FILTERS.map(item => {
            const Icon = item.icon
            const active = profileFilter === item.value
            return (
              <button
                key={item.value || 'all'}
                type="button"
                onClick={() => { setProfileFilter(item.value); setPage(1) }}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition',
                  active
                    ? 'border-blue-200 bg-blue-50 text-blue-700'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:bg-blue-50'
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {item.label}
              </button>
            )
          })}
          <button type="button" onClick={handleClearFilters} className="btn-secondary px-4">
            <X className="w-4 h-4" /> Clear all filters
          </button>
        </div>
        </div>

        {loading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="card p-4 animate-pulse">
              <div className="flex gap-4">
                <div className="w-11 h-11 rounded-xl bg-slate-100" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-slate-100 rounded w-1/3" />
                  <div className="h-3 bg-slate-100 rounded w-2/3" />
                  <div className="h-3 bg-slate-100 rounded w-1/2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : trainers.length === 0 ? (
        <div className="card p-16 text-center">
          <Users className="w-12 h-12 text-slate-200 mx-auto mb-3" />
          <p className="font-medium text-slate-500">No trainers found</p>
          <p className="text-sm text-slate-400 mt-1">Upload trainer resumes or clear filters to widen the search</p>
        </div>
      ) : (
        <div className="space-y-3">
          {trainers.map(t => (
            <TrainerRow
              key={t.trainer_id}
              t={t}
              onView={setSelectedTrainer}
              onDelete={setConfirmDelete}
              onRecategorise={handleRecategorise}
              onRequestResume={openResumeRequest}
              onStartAutomation={startAutomationPipeline}
              recategorising={recategorisingId === t.trainer_id}
              requestingResume={requestingResumeId === t.trainer_id}
              sendingAutomation={sendingAutomationId === t.trainer_id}
            />
          ))}
        </div>
        )}

        {pages > 1 && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-sm text-slate-500">Page {page} of {pages} - {total} total</p>
          <div className="flex items-center gap-2">
            <button onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1} className="btn-secondary py-1.5 px-3 disabled:opacity-40">
              <ChevronLeft className="w-4 h-4" />
            </button>
            {[...Array(Math.min(pages, 5))].map((_, i) => {
              const p = i + 1
              return (
                <button key={p} onClick={() => setPage(p)}
                  className={clsx('w-8 h-8 rounded-lg text-sm font-medium',
                    page === p ? 'bg-blue-500 text-white' : 'btn-secondary py-0 px-0')}>
                  {p}
                </button>
              )
            })}
            <button onClick={() => setPage(p => Math.min(pages, p + 1))}
              disabled={page === pages} className="btn-secondary py-1.5 px-3 disabled:opacity-40">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
        )}
      </div>
    </>
  )
}
