import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getTrainers,
  getTrainer,
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
  TrendingUp,
  BookOpenCheck,
  BriefcaseBusiness,
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
  interview_scheduled: 'badge-purple',
  selected: 'badge-green',
  rejected: 'badge-red',
  toc_requested: 'badge-blue',
  toc_received_pending: 'badge-blue',
  training_confirmed: 'badge-green',
}

function trainerStatusLabel(value = '') {
  return String(value || 'new').replaceAll('_', ' ')
}

function trainerStatusClass(value = '') {
  return STATUS_COLORS[value] || 'badge-slate'
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

const EMPTY_TEXT_VALUES = new Set(['', '-', '--', 'unknown', 'n/a', 'na', 'none', 'null', 'undefined', 'not available', 'not specified'])
const EMPTY_CATEGORY_VALUES = new Set(['uncategorised', 'uncategorized', 'unknown', 'general', 'multi-skillset', 'not categorised', 'not categorized'])
const CATEGORY_RULES = [
  {
    category: 'DevOps',
    keywords: ['devops', 'docker', 'kubernetes', 'jenkins', 'terraform', 'ansible', 'ci/cd', 'prometheus', 'grafana', 'helm'],
  },
  {
    category: 'Cloud',
    keywords: ['aws', 'azure', 'gcp', 'cloud', 'ec2', 's3', 'lambda'],
  },
  {
    category: 'Data Science',
    keywords: ['data science', 'machine learning', 'deep learning', 'pandas', 'numpy', 'statistics', 'tensorflow', 'pytorch'],
  },
  {
    category: 'Data Engineering',
    keywords: ['data engineering', 'spark', 'databricks', 'kafka', 'airflow', 'etl', 'bigquery'],
  },
  {
    category: 'Cybersecurity',
    keywords: ['cybersecurity', 'security', 'soc', 'siem', 'ethical hacking', 'vapt'],
  },
  {
    category: 'Database',
    keywords: ['sql', 'postgresql', 'mysql', 'mongodb', 'oracle', 'database'],
  },
  {
    category: 'Frontend Development',
    keywords: ['react', 'angular', 'vue', 'html', 'css', 'redux', 'frontend'],
  },
  {
    category: 'Backend Development',
    keywords: ['node.js', 'node', 'express', 'django', 'flask', 'fastapi', 'spring boot', 'backend', 'api'],
  },
  {
    category: 'Programming Languages',
    keywords: ['python', 'java', 'javascript', 'typescript', 'c++', 'c#', 'go', 'rust'],
  },
]
const SKILL_PATTERNS = [
  ['Python', ['python', 'python trainer']],
  ['Java', ['java', 'java trainer']],
  ['JavaScript', ['javascript', 'js']],
  ['TypeScript', ['typescript', 'ts']],
  ['React', ['react', 'react.js', 'reactjs', 'react trainer']],
  ['Angular', ['angular']],
  ['Vue.js', ['vue', 'vue.js']],
  ['Node.js', ['node', 'node.js', 'nodejs']],
  ['Express.js', ['express', 'express.js']],
  ['MERN Stack', ['mern', 'mern stack']],
  ['MongoDB', ['mongodb', 'mongo db']],
  ['Django', ['django']],
  ['Flask', ['flask']],
  ['FastAPI', ['fastapi', 'fast api']],
  ['Spring Boot', ['spring boot']],
  ['HTML', ['html']],
  ['CSS', ['css']],
  ['Redux', ['redux']],
  ['Next.js', ['next.js', 'nextjs']],
  ['AWS', ['aws', 'amazon web services']],
  ['Azure', ['azure']],
  ['GCP', ['gcp', 'google cloud']],
  ['Docker', ['docker']],
  ['Kubernetes', ['kubernetes', 'k8s']],
  ['Jenkins', ['jenkins']],
  ['Terraform', ['terraform']],
  ['SQL', ['sql']],
  ['PostgreSQL', ['postgresql', 'postgres']],
]

function displayText(value, preferredKeys = []) {
  if (value == null) return ''
  if (typeof value === 'string') {
    const text = value.trim()
    return EMPTY_TEXT_VALUES.has(text.toLowerCase()) ? '' : text
  }
  if (typeof value === 'number') return value === 0 ? '' : String(value)
  if (typeof value === 'boolean') return value ? 'Yes' : ''
  if (Array.isArray(value)) return value.map(item => displayText(item, preferredKeys)).filter(Boolean).join(', ')
  if (typeof value === 'object') {
    const keys = [...preferredKeys, 'label', 'value', 'name', 'domain', 'category', 'industry', 'technology_category']
    for (const key of keys) {
      const text = displayText(value[key], preferredKeys)
      if (text) return text
    }
    return ''
  }
  return String(value).trim()
}

function asArray(value) {
  if (Array.isArray(value)) return value.map(item => displayText(item)).filter(Boolean)
  if (!value) return []
  return displayText(value).split(/[,;\n]/).map(item => item.trim()).filter(Boolean)
}

function uniqueByLower(values) {
  const seen = new Set()
  const items = []
  values.forEach(value => {
    const text = displayText(value)
    const key = text.toLowerCase()
    if (text && !seen.has(key)) {
      seen.add(key)
      items.push(text)
    }
  })
  return items
}

function hasSkillAlias(text, alias) {
  const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\\$&`)
  return new RegExp(`(^|[^a-z0-9+#.])${escaped}($|[^a-z0-9+#.])`, 'i').test(text)
}

function isUsefulCategory(value) {
  const text = displayText(value)
  return Boolean(text && !EMPTY_CATEGORY_VALUES.has(text.toLowerCase()))
}

function uniqueSorted(values) {
  return [...new Set(values.map(item => displayText(item)).filter(Boolean))].sort((a, b) => a.localeCompare(b))
}

function softwareDomainsOnly(values) {
  return values
    .map(domain => displayText(domain))
    .filter(domain => domain && !NON_SOFTWARE_DOMAINS.has(domain.toLowerCase()))
}

function searchableTrainerText(t) {
  return [
    t.name,
    t.primary_category,
    t.technology_category,
    t.category,
    t.domain,
    t.role_designation,
    t.technologies,
    t.summary,
    t.bio,
    t.resume,
    ...(asArray(t.skills)),
    ...(asArray(t.secondary_categories)),
    ...(specialisationTags(t)),
  ].map(item => displayText(item)).filter(Boolean).join(' ').toLowerCase()
}

function detectedSkillsFromText(text) {
  if (!text) return []
  const matches = []
  SKILL_PATTERNS.forEach(([skill, aliases]) => {
    if (aliases.some(alias => hasSkillAlias(text, alias))) matches.push(skill)
  })
  if (matches.includes('MERN Stack')) {
    matches.push('MongoDB', 'Express.js', 'React', 'Node.js', 'JavaScript')
  }
  return uniqueByLower(matches)
}

function allTrainerSkills(t) {
  return uniqueByLower([
    ...asArray(t.skills),
    ...detectedSkillsFromText(searchableTrainerText(t)),
  ])
}

function trainerDisplayName(t) {
  const raw = displayText(t.name)
  if (!raw) return ''
  const [namePart] = raw.split(/\s[-|]\s/)
  return displayText(namePart) || raw
}

function trainerTitle(t) {
  const role = displayText(t.role_designation)
  if (role && role !== trainerDisplayName(t)) return role
  const raw = displayText(t.name)
  const titlePart = raw.split(/\s-\s/).slice(1).join(' - ')
  return displayText(titlePart || t.technologies || t.primary_category || t.technology_category || t.category || t.domain)
}

function cleanSummary(t) {
  const summary = displayText(t.summary || t.bio)
  if (!summary) return ''
  const name = trainerDisplayName(t).toLowerCase()
  const title = trainerTitle(t).toLowerCase()
  const lower = summary.toLowerCase()
  if (lower === name || lower === title || lower === displayText(t.name).toLowerCase()) return ''
  return summary
}

function inferredCategory(t) {
  const explicit = [t.primary_category, t.technology_category, t.category, t.domain]
    .map(item => displayText(item))
    .find(isUsefulCategory)
  if (explicit) return explicit

  const text = searchableTrainerText(t)
  const hasFrontend = ['react', 'angular', 'vue', 'javascript', 'typescript', 'html', 'css'].some(keyword => text.includes(keyword))
  const hasBackend = ['python', 'java', 'node', 'django', 'flask', 'fastapi', 'spring boot', 'api'].some(keyword => text.includes(keyword))
  if (hasFrontend && hasBackend) return 'Full Stack'

  const matched = CATEGORY_RULES
    .map(rule => ({
      category: rule.category,
      count: rule.keywords.filter(keyword => text.includes(keyword)).length,
    }))
    .filter(item => item.count > 0)
    .sort((a, b) => b.count - a.count)
  if (matched.length) return matched[0].category
  return allTrainerSkills(t).length ? 'Software Development' : ''
}

function primaryCategory(t) {
  return inferredCategory(t) || 'Uncategorised'
}

function specialisationTags(t) {
  return asArray(t.specialisation_tags?.length ? t.specialisation_tags : t.specialty_tags)
}

function domainBadge(domain) {
  return DOMAIN_BADGES[displayText(domain).toLowerCase()] || 'bg-slate-100 text-slate-600 border-slate-200'
}

function levelBadge(level) {
  const normalized = String(level || '').toLowerCase()
  if (normalized === 'expert') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (normalized === 'beginner') return 'bg-slate-50 text-slate-600 border-slate-200'
  return 'bg-blue-50 text-blue-700 border-blue-200'
}

function skillLevels(t) {
  const map = t.skill_level_map || {}
  if (!map || typeof map !== 'object' || Array.isArray(map)) return []
  return Object.entries(map)
    .map(([skill, level]) => [displayText(skill), displayText(level)])
    .filter(([skill]) => skill)
    .slice(0, 3)
}

function numericValue(value) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : 0
}

function normaliseScore(value) {
  const number = numericValue(value)
  if (!number) return 0
  if (number <= 1) return number * 100
  if (number <= 5) return number * 20
  return Math.min(100, number)
}

function experienceYears(t) {
  const explicit = numericValue(t.experience_years)
  if (explicit) return explicit
  const raw = displayText(t.experience_raw || t.experience || t.total_experience)
  const match = /(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)/i.exec(raw)
  return match ? Number(match[1]) : 0
}

function inferredProfileScore(t) {
  const skills = allTrainerSkills(t)
  const certs = asArray(t.certifications)
  const clients = asArray(t.past_clients)
  const years = experienceYears(t)
  let score = skills.length ? 30 : 0
  score += Math.min(25, skills.length * 4)
  score += isUsefulCategory(primaryCategory(t)) ? 12 : 0
  score += displayText(t.name) ? 6 : 0
  score += Math.min(12, [t.email, t.phone, t.linkedin].filter(item => displayText(item)).length * 4)
  score += Math.min(15, Math.round(years * 2.5))
  score += displayText(t.location) ? 4 : 0
  score += displayText(t.summary || t.bio || t.resume) ? 7 : 0
  score += Math.min(7, certs.length * 3)
  score += Math.min(4, clients.length * 2)
  score += numericValue(t.training_count) ? 3 : 0
  return Math.max(0, Math.min(100, Math.round(score)))
}

function trainerProfileScore(t) {
  const explicitScores = [
    t.profile_score,
    t.resume_rank_score,
    t.overall_score,
    t.match_score,
    t.fit_score,
    t.confidence_score,
    t.confidence,
  ].map(normaliseScore).filter(Boolean)
  return Math.round(Math.max(inferredProfileScore(t), ...explicitScores, 0))
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
  const raw = explicitRating ?? trainerProfileScore(t)
  let rating = Number(raw) || 0
  if (rating > 5) rating /= 20
  else if (rating > 0 && rating <= 1) rating *= 5
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
  return text.length > 1600 ? `${text.slice(0, 1600).trim()}...` : text
}

function textValue(value, fallback = 'Not available') {
  const text = displayText(value)
  return text || fallback
}

function dayRateText(value) {
  const rate = numericValue(value)
  return rate ? `INR ${rate.toLocaleString('en-IN')}` : 'Not available'
}

function trainerBreakdown(t) {
  const existing = t.score_breakdown && typeof t.score_breakdown === 'object' ? t.score_breakdown : {}
  const skills = allTrainerSkills(t)
  const certs = asArray(t.certifications)
  const years = experienceYears(t)
  const fallback = {
    technology: { score: isUsefulCategory(primaryCategory(t)) ? 35 : 0, max: 35 },
    skills: { score: Math.min(25, skills.length * 4 + (displayText(t.technologies) ? 1 : 0)), max: 25 },
    experience: { score: Math.min(15, Math.round(years * 2.5)), max: 15 },
    certifications: { score: Math.min(10, certs.length * 5), max: 10 },
    location: { score: displayText(t.location) ? 10 : 0, max: 10 },
  }
  const bestItem = (key) => {
    const current = existing[key] && typeof existing[key] === 'object' ? existing[key] : {}
    const currentScore = numericValue(current.score)
    const fallbackScore = numericValue(fallback[key].score)
    if (!current.max || fallbackScore > currentScore) return fallback[key]
    return { ...current, score: currentScore, max: numericValue(current.max) || fallback[key].max }
  }
  return {
    technology: bestItem('technology'),
    skills: bestItem('skills'),
    experience: bestItem('experience'),
    certifications: bestItem('certifications'),
    location: bestItem('location'),
  }
}

function trainerDescription(t) {
  const skills = allTrainerSkills(t).slice(0, 8)
  const tags = specialisationTags(t).slice(0, 4)
  const certs = asArray(t.certifications).slice(0, 3)
  const category = primaryCategory(t)
  const years = experienceYears(t)
  const experience = displayText(t.experience_raw) || (years ? `${years}+ years` : '')
  const role = trainerTitle(t) || category
  const score = trainerProfileScore(t)
  const name = trainerDisplayName(t) || 'This trainer'
  const summary = cleanSummary(t)

  const parts = []
  if (score) {
    parts.push(`${name} has a ${score}/100 trainer profile for ${category}.`)
  }
  if (role || experience) {
    parts.push(`Profile extracted: ${[role, experience].filter(Boolean).join(' | ')}.`)
  }
  if (skills.length) parts.push(`Skills found in resume: ${skills.join(', ')}.`)
  if (tags.length) parts.push(`Specialisation tags from resume skills: ${tags.join(', ')}.`)
  if (certs.length) parts.push(`Certifications found in resume: ${certs.join(', ')}.`)
  if (summary) parts.push(`Resume summary excerpt: ${summary}`)
  return parts.join(' ')
}

function DetailSection({ title, icon: Icon, children }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-bold text-slate-800">
        <Icon className="h-4 w-4 text-blue-600" /> {title}
      </h4>
      {children}
    </section>
  )
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
            Trainer Status: <span className="font-bold capitalize">{statusText}</span>
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
  const category = primaryCategory(t)
  const skills = allTrainerSkills(t)
  const tags = specialisationTags(t)
  const industries = asArray(t.industry_focus)
  const deliveryLanguages = asArray(t.language_of_delivery)
  const secondary = asArray(t.secondary_categories)
  const levels = skillLevels(t)
  const resumeText = compactResumeText(t.resume || t.combined_text || t.extracted_text)
  const pastClients = asArray(t.past_clients)
  const certs = asArray(t.certifications)
  const profileScore = trainerProfileScore(t)
  const breakdown = trainerBreakdown(t)
  const years = experienceYears(t)
  const displayName = trainerDisplayName(t)
  const summary = cleanSummary(t)
  const resumeUrl = /^https?:\/\//i.test(String(t.resume || '')) ? t.resume : ''
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
      <div className="bg-white rounded-2xl shadow-card-lg w-full max-w-5xl max-h-[calc(100vh-1.5rem)] sm:max-h-[calc(100vh-2.5rem)] overflow-hidden flex flex-col">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 bg-white p-5 flex-shrink-0">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-lg bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-600">Trainer DB</span>
              <span className="rounded-lg bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700">{profileScore}/100 profile</span>
              <span className={trainerStatusClass(t.status)}>Trainer Status: {trainerStatusLabel(t.status)}</span>
              <span className={clsx('px-2.5 py-1 rounded-full border text-xs font-semibold', domainBadge(category))}>{category}</span>
              {t.needs_review && <span className="badge-yellow text-xs">Needs review</span>}
            </div>
            <h2 className="mt-2 font-jakarta text-2xl font-bold text-slate-900 truncate">{displayName || 'Unnamed Trainer'}</h2>
            <p className="mt-1 text-sm text-slate-500 line-clamp-2">
              {displayText(t.technologies) || trainerTitle(t) || skills.slice(0, 10).join(', ') || 'No technologies listed'}
            </p>
          </div>
          <div className="flex flex-shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setShowSingleShortlist(value => !value)}
              className={clsx(
                'hidden items-center gap-2 rounded-xl px-3 py-2 text-xs font-bold transition-colors sm:flex',
                showSingleShortlist
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-blue-50 text-blue-600 border border-blue-100 hover:bg-blue-100'
              )}
            >
              <Sparkles className="h-4 w-4" />
              Pipeline
            </button>
            <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-xl transition-colors" aria-label="Close trainer detail">
              <X className="w-5 h-5 text-slate-500" />
            </button>
          </div>
        </div>

        <div className="p-5 overflow-y-auto flex-1">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="space-y-4">
              <DetailSection title="Profile Description" icon={BookOpenCheck}>
                <p className="text-sm leading-6 text-slate-700">{trainerDescription(t) || 'Trainer profile details are still being collected.'}</p>
                {summary && (
                  <p className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-700">
                    {summary}
                  </p>
                )}
              </DetailSection>

              <DetailSection title="Resume Evidence" icon={FileText}>
                {resumeText ? (
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-3 font-sans text-sm leading-6 text-slate-700">{resumeText}</pre>
                ) : resumeUrl ? (
                  <a href={resumeUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm font-semibold text-blue-600 hover:underline">
                    <FileText className="h-4 w-4" /> Open resume
                  </a>
                ) : (
                  <p className="text-sm text-slate-500">No resume text or link is stored for this trainer.</p>
                )}
              </DetailSection>

              <DetailSection title="Skills & Technologies" icon={Star}>
                <div className="flex flex-wrap gap-2">
                  {skills.length ? skills.map(skill => <span key={skill} className="badge-blue text-xs">{skill}</span>) : <span className="text-sm text-slate-500">No skills listed</span>}
                </div>
                {tags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {tags.map(tag => <span key={tag} className="badge-purple text-xs">{tag}</span>)}
                  </div>
                )}
                {secondary.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {secondary.map(item => <span key={item} className="badge-slate text-xs">{item}</span>)}
                  </div>
                )}
                {levels.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {levels.map(([skill, level]) => (
                      <span key={skill} className={clsx('px-2.5 py-1 rounded-full border text-xs font-semibold', levelBadge(level))}>
                        {skill}: {level}
                      </span>
                    ))}
                  </div>
                )}
              </DetailSection>

              <DetailSection title="Microsoft Teams Direct Chat" icon={MessageSquare}>
                <div className="flex flex-col gap-2 sm:flex-row">
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
              </DetailSection>
            </div>

            <div className="space-y-4">
              <DetailSection title="Contact & Experience" icon={BriefcaseBusiness}>
                <div className="space-y-2 text-sm text-slate-700">
                  <p><strong>Experience:</strong> {displayText(t.experience_raw) || (years ? `${years} years` : 'Not available')}</p>
                  <p><strong>Location:</strong> {textValue(t.location)}</p>
                  <p><strong>Email:</strong> {textValue(t.email)}</p>
                  <p><strong>Phone:</strong> {textValue(t.phone)}</p>
                  <p><strong>Teams:</strong> {textValue(t.teams_email || t.microsoft_teams_email || t.teams_upn)}</p>
                  <p><strong>LinkedIn:</strong> {displayText(t.linkedin) ? <a className="text-blue-600 hover:underline" href={t.linkedin} target="_blank" rel="noreferrer">Open profile</a> : 'Not available'}</p>
                  <p><strong>Trainings:</strong> {textValue(t.training_count)}</p>
                  <p><strong>Day rate:</strong> {dayRateText(t.day_rate)}</p>
                </div>
              </DetailSection>

              <DetailSection title="Certifications & Clients" icon={Award}>
                <div className="space-y-3">
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Certifications</p>
                    <div className="flex flex-wrap gap-2">
                      {certs.length ? certs.map(cert => <span key={cert} className="badge-blue text-xs">{cert}</span>) : <span className="text-sm text-slate-500">No certifications listed</span>}
                    </div>
                  </div>
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Past Clients</p>
                    <div className="flex flex-wrap gap-2">
                      {pastClients.length ? pastClients.map(client => <span key={client} className="badge-slate text-xs">{client}</span>) : <span className="text-sm text-slate-500">No past clients listed</span>}
                    </div>
                  </div>
                </div>
              </DetailSection>

              <DetailSection title="Match Breakdown" icon={TrendingUp}>
                <div className="space-y-2">
                  {[
                    ['Technology', 'technology'],
                    ['Skills', 'skills'],
                    ['Experience', 'experience'],
                    ['Certifications', 'certifications'],
                    ['Location', 'location'],
                  ].map(([label, key]) => {
                    const item = breakdown[key] || {}
                    const max = numericValue(item.max) || 1
                    const score = Math.min(max, numericValue(item.score))
                    return (
                      <div key={key}>
                        <div className="mb-1 flex justify-between text-xs font-semibold text-slate-500">
                          <span>{label}</span><span>{Math.round(score)}/{Math.round(max)}</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                          <div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.min(100, Math.round((score / max) * 100))}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </DetailSection>

              {(industries.length > 0 || deliveryLanguages.length > 0 || category || displayText(t.domain)) && (
                <DetailSection title="Category Details" icon={Users}>
                  <div className="space-y-2 text-sm text-slate-700">
                    <p><strong>Primary:</strong> {category}</p>
                    <p><strong>Domain:</strong> {textValue(t.domain || category)}</p>
                    {industries.length > 0 && <p><strong>Industry:</strong> {industries.join(', ')}</p>}
                    {deliveryLanguages.length > 0 && <p><strong>Language:</strong> {deliveryLanguages.join(', ')}</p>}
                    {displayText(t.reasoning) && <p><strong>Reason:</strong> {displayText(t.reasoning)}</p>}
                  </div>
                </DetailSection>
              )}
            </div>
          </div>

          {showSingleShortlist && (
            <div className="mt-4 space-y-4 rounded-2xl border border-blue-100 bg-blue-50/40 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-bold uppercase tracking-wider text-blue-700">Single Person Shortlist</p>
                  <p className="mt-0.5 text-xs text-blue-600">Pipeline and communication for {displayName || 'this trainer'}.</p>
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

          <div className="mt-4 flex flex-wrap gap-3 pt-2">
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
            {displayText(t.linkedin) && (
              <a href={t.linkedin} target="_blank" rel="noreferrer"
                 className="flex items-center gap-2 px-4 py-2 bg-blue-50 text-blue-600 rounded-xl text-sm font-medium hover:bg-blue-100 transition-colors">
                <Linkedin className="w-4 h-4" /> LinkedIn Profile
              </a>
            )}
            {resumeUrl && (
              <a href={resumeUrl} target="_blank" rel="noreferrer"
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
  const category = primaryCategory(t)
  const tags = specialisationTags(t)
  const industries = asArray(t.industry_focus)
  const deliveryLanguages = asArray(t.language_of_delivery)
  const levels = skillLevels(t)
  const skills = allTrainerSkills(t)
  const profileScore = trainerProfileScore(t)
  const years = experienceYears(t)
  const displayName = trainerDisplayName(t)

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
        aria-label={`View ${displayName || 'trainer'}`}
      >
        <span className="font-jakarta font-bold text-blue-600 text-base">{(displayName || t.name || 'T').charAt(0).toUpperCase()}</span>
      </button>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <button type="button" className="text-left min-w-0 flex-1" onClick={(e) => { e.stopPropagation(); onView(t) }}>
            <h3 className="font-medium text-slate-900 group-hover:text-blue-600 transition-colors truncate">{displayName || 'Unnamed Trainer'}</h3>
            <p className="text-xs text-slate-400 mt-0.5 line-clamp-1">{displayText(t.technologies) || trainerTitle(t) || skills.slice(0, 8).join(', ')}</p>
            {tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tags.slice(0, 3).map(tag => <span key={tag} className="badge-purple text-xs">{tag}</span>)}
              </div>
            )}
          </button>

          <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
            <TrainerRatingStars trainer={t} />
            <span className={clsx('px-2.5 py-1 rounded-full border text-xs font-semibold', domainBadge(category))}>{category}</span>
            <div
              className={clsx(
                'w-12 h-9 rounded-lg flex flex-col items-center justify-center text-xs font-bold',
                profileScore >= 80 ? 'bg-emerald-100 text-emerald-700' :
                profileScore >= 60 ? 'bg-blue-100 text-blue-700' :
                profileScore >= 40 ? 'bg-amber-100 text-amber-700' :
                'bg-slate-100 text-slate-500'
              )}
              title={`${profileScore}/100 trainer profile score`}
            >
              <span className="leading-none">{profileScore}</span>
              <span className="text-[10px] leading-none opacity-70">score</span>
            </div>
            <span className={trainerStatusClass(t.status)}>Trainer Status: {trainerStatusLabel(t.status)}</span>
            <TrainerCardTrustPill trainer={t} />
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          {Boolean(displayText(t.experience_raw) || years) && <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {displayText(t.experience_raw) || `${years} years`}</span>}
          {displayText(t.location) && <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> {displayText(t.location)}</span>}
          {displayText(t.email) && <span className="flex items-center gap-1 min-w-0"><Mail className="w-3.5 h-3.5 flex-shrink-0" /> <span className="truncate">{displayText(t.email)}</span></span>}
          {Boolean(t.teams_email || t.microsoft_teams_email || t.teams_upn) && (
            <span className="flex items-center gap-1 min-w-0 text-indigo-600">
              <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
              <span className="truncate">{displayText(t.teams_email || t.microsoft_teams_email || t.teams_upn)}</span>
            </span>
          )}
          {displayText(t.phone) && <span className="flex items-center gap-1"><Phone className="w-3.5 h-3.5" /> {displayText(t.phone)}</span>}
        </div>

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
          aria-label={`Start automation pipeline for ${displayName || 'trainer'}`}
        >
          {sendingAutomation ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onRequestResume(t) }}
          disabled={requestingResume}
          className="p-2 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all disabled:opacity-50"
          title="Request updated resume"
          aria-label={`Request updated resume from ${displayName || 'trainer'}`}
        >
          {requestingResume ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onView(t) }}
          className="p-2 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all"
          title="View trainer details"
          aria-label={`View details for ${displayName || 'trainer'}`}
        >
          <Eye className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onRecategorise(t) }}
          disabled={recategorising}
          className="p-2 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all disabled:opacity-50"
          title="Re-categorise trainer"
          aria-label={`Re-categorise ${displayName || 'trainer'}`}
        >
          <RefreshCw className={clsx('w-4 h-4', recategorising && 'animate-spin')} />
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(t) }}
          className="p-2 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-all"
          title="Delete trainer"
          aria-label={`Delete ${displayName || 'trainer'}`}
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
      })
      setTrainers(res.data.items || [])
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
  }, [page, search, status, domain, category, industry, experience])

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
    setPage(1)
  }

  const handleViewTrainer = async (trainer) => {
    setSelectedTrainer(trainer)
    if (!trainer?.trainer_id) return
    try {
      const res = await getTrainer(trainer.trainer_id)
      const fullTrainer = res.data?.trainer || res.data
      if (fullTrainer?.trainer_id) {
        setSelectedTrainer(current => current?.trainer_id === trainer.trainer_id ? { ...trainer, ...fullTrainer } : current)
      }
    } catch (error) {
      toast.error(error.message || 'Could not load trainer details')
    }
  }

  const handleDelete = async (trainer) => {
    try {
      await deleteTrainer(trainer.trainer_id)
      toast.success(`${trainer.name} deleted`)
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
      toast.success(`${trainer.name} categorised`)
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
      toast.success(`Resume request sent to ${resumeRequestTrainer.name || 'trainer'}`)
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
      })
      const updated = res.data.trainer
      if (updated?.trainer_id) {
        setTrainers(prev => prev.map(item => item.trainer_id === updated.trainer_id ? updated : item))
        setSelectedTrainer(current => current?.trainer_id === updated.trainer_id ? updated : current)
      }
      toast.success(`Automation mail sent to ${automationMailTrainer.name || 'trainer'}`)
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
                    ? <>Add client details once. Mail 1 starts automatically for <strong>{automationMailTrainer.name || 'Trainer'}</strong>.</>
                    : <>Send one trainer pipeline template only to <strong>{automationMailTrainer.name || 'Trainer'}</strong>.</>}
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
                  Send a resume/profile request to <strong>{resumeRequestTrainer.name || 'Trainer'}</strong>.
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
            <p className="text-sm text-slate-500 mb-4">Remove <strong>{confirmDelete.name}</strong> from the database? This cannot be undone.</p>
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

        <div className="card p-4 space-y-3">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-600">
          <Filter className="w-4 h-4 text-slate-400" />
          Trainer filters
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-3">
          <form onSubmit={handleSearch} className="md:col-span-2 xl:col-span-2 flex gap-2">
            <div className="relative flex-1 min-w-0">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                className="input pl-9"
                placeholder="Search name or skill"
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
        </div>

        <div className="flex flex-wrap gap-2">
          <select className="input w-44" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
            <option value="">All Statuses</option>
            {STATUSES.filter(Boolean).map(item => (
              <option key={item} value={item}>{item.replace('_', ' ')}</option>
            ))}
          </select>
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
              onView={handleViewTrainer}
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
