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
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

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

const DOMAIN_BADGES = {
  cloud: 'bg-sky-50 text-sky-700 border-sky-200',
  devops: 'bg-blue-50 text-blue-700 border-blue-200',
  sre: 'bg-cyan-50 text-cyan-700 border-cyan-200',
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

function compactResumeText(value) {
  if (!value) return ''
  const text = String(value).trim()
  if (/^https?:\/\//i.test(text)) return ''
  return text.length > 520 ? `${text.slice(0, 520).trim()}...` : text
}

function trainerDescription(t) {
  const skills = asArray(t.skills).slice(0, 6)
  const tags = specialisationTags(t).slice(0, 4)
  const certs = asArray(t.certifications).slice(0, 3)
  const category = primaryCategory(t)
  const experience = t.experience_raw || (t.experience_years ? `${t.experience_years}+ years` : '')

  const parts = [
    `${t.name || 'This trainer'} is profiled as a ${category} trainer${experience ? ` with ${experience} of experience` : ''}.`,
  ]
  if (skills.length) parts.push(`Key resume skills include ${skills.join(', ')}.`)
  if (tags.length) parts.push(`Training focus areas: ${tags.join(', ')}.`)
  if (certs.length) parts.push(`Certifications listed: ${certs.join(', ')}.`)
  if (t.summary) parts.push(String(t.summary))
  return parts.join(' ')
}

function TrainerDetail({ t, onClose }) {
  const category = primaryCategory(t)
  const tags = specialisationTags(t)
  const industries = asArray(t.industry_focus)
  const deliveryLanguages = asArray(t.language_of_delivery)
  const levels = skillLevels(t)
  const resumeText = compactResumeText(t.resume)
  const pastClients = asArray(t.past_clients)

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-3 sm:p-5 bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-card-lg w-full max-w-3xl max-h-[calc(100vh-1.5rem)] sm:max-h-[calc(100vh-2.5rem)] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between p-5 border-b border-slate-100 bg-white flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-brand-100 to-brand-50 flex items-center justify-center flex-shrink-0">
              <span className="font-display font-bold text-brand-600 text-lg">{t.name?.charAt(0).toUpperCase()}</span>
            </div>
            <div className="min-w-0">
              <h2 className="font-display font-bold text-slate-900 text-lg truncate">{t.name}</h2>
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
          <div className="rounded-xl border border-brand-100 bg-brand-50/60 p-4">
            <p className="text-xs font-semibold text-brand-600 uppercase tracking-wider mb-2">Trainer Profile</p>
            <p className="text-sm leading-6 text-slate-700">{trainerDescription(t)}</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {t.email && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl min-w-0">
                <Mail className="w-4 h-4 text-brand-500 flex-shrink-0" />
                <a href={`mailto:${t.email}`} className="text-sm text-slate-700 hover:text-brand-500 truncate">{t.email}</a>
              </div>
            )}
            {t.phone && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl">
                <Phone className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                <span className="text-sm text-slate-700">{t.phone}</span>
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

          {resumeText && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Resume Snapshot</p>
              <p className="text-sm text-slate-700 bg-slate-50 rounded-xl p-3 leading-relaxed whitespace-pre-wrap">{resumeText}</p>
            </div>
          )}

          {asArray(t.skills).length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Skills</p>
              <div className="flex flex-wrap gap-2">
                {asArray(t.skills).map(skill => <span key={skill} className="badge-blue text-xs">{skill}</span>)}
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

function TrainerRow({ t, onDelete, onView, onRecategorise, recategorising }) {
  const category = primaryCategory(t)
  const tags = specialisationTags(t)
  const industries = asArray(t.industry_focus)
  const deliveryLanguages = asArray(t.language_of_delivery)
  const levels = skillLevels(t)
  const skills = asArray(t.skills)

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
      className="card-hover cursor-pointer p-4 flex items-start gap-4 animate-fade-in group focus:outline-none focus:ring-2 focus:ring-brand-500/30"
    >
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onView(t) }}
        className="w-11 h-11 rounded-xl bg-gradient-to-br from-brand-100 to-brand-50 flex items-center justify-center flex-shrink-0 hover:from-brand-200 hover:to-brand-100 transition-all"
        aria-label={`View ${t.name || 'trainer'}`}
      >
        <span className="font-display font-bold text-brand-600 text-base">{t.name?.charAt(0).toUpperCase()}</span>
      </button>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <button type="button" className="text-left min-w-0 flex-1" onClick={(e) => { e.stopPropagation(); onView(t) }}>
            <h3 className="font-medium text-slate-900 group-hover:text-brand-600 transition-colors truncate">{t.name}</h3>
            <p className="text-xs text-slate-400 mt-0.5 line-clamp-1">{t.technologies || t.summary}</p>
            {tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tags.slice(0, 3).map(tag => <span key={tag} className="badge-purple text-xs">{tag}</span>)}
              </div>
            )}
          </button>

          <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
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
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          {(t.experience_raw || t.experience_years) && <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {t.experience_raw || `${t.experience_years} years`}</span>}
          {t.location && <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> {t.location}</span>}
          {t.email && <span className="flex items-center gap-1 min-w-0"><Mail className="w-3.5 h-3.5 flex-shrink-0" /> <span className="truncate">{t.email}</span></span>}
          {t.phone && <span className="flex items-center gap-1"><Phone className="w-3.5 h-3.5" /> {t.phone}</span>}
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
          onClick={(e) => { e.stopPropagation(); onView(t) }}
          className="p-2 rounded-lg text-slate-400 hover:text-brand-600 hover:bg-brand-50 transition-all"
          title="View trainer details"
          aria-label={`View details for ${t.name || 'trainer'}`}
        >
          <Eye className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onRecategorise(t) }}
          disabled={recategorising}
          className="p-2 rounded-lg text-slate-400 hover:text-brand-600 hover:bg-brand-50 transition-all disabled:opacity-50"
          title="Re-categorise trainer"
          aria-label={`Re-categorise ${t.name || 'trainer'}`}
        >
          <RefreshCw className={clsx('w-4 h-4', recategorising && 'animate-spin')} />
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(t) }}
          className="p-2 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-all"
          title="Delete trainer"
          aria-label={`Delete ${t.name || 'trainer'}`}
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
        <TrainerDetail t={selectedTrainer} onClose={() => setSelectedTrainer(null)} />
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
              onView={setSelectedTrainer}
              onDelete={setConfirmDelete}
              onRecategorise={handleRecategorise}
              recategorising={recategorisingId === t.trainer_id}
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
                    page === p ? 'bg-brand-500 text-white' : 'btn-secondary py-0 px-0')}>
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
