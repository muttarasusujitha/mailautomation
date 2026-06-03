import { useState, useEffect } from 'react'
import { createRequirement, deleteRequirement, getRequirements } from '../utils/api'
import toast from 'react-hot-toast'
import {
  Search, Plus, X, Star, MapPin, Mail,
  Phone, Linkedin, FileText, Award, Clock, Loader2,
  TrendingUp, Users, Trash2, Eye, BriefcaseBusiness, BookOpenCheck
} from 'lucide-react'
import clsx from 'clsx'

const SKILLS_PRESETS = {
  'Python': ['python', 'django', 'flask', 'machine learning', 'pandas'],
  'React': ['react', 'javascript', 'typescript', 'html', 'css', 'redux'],
  'AWS': ['aws', 'cloud', 'ec2', 's3', 'lambda', 'devops'],
  'Data Science': ['data science', 'machine learning', 'python', 'statistics', 'tableau'],
  'Java': ['java', 'spring boot', 'maven', 'microservices', 'hibernate'],
  'DevOps': ['docker', 'kubernetes', 'jenkins', 'ci/cd', 'terraform', 'ansible'],
}

const ScoreBadge = ({ score }) => {
  const color = score >= 80 ? 'bg-emerald-100 text-emerald-700'
              : score >= 60 ? 'bg-blue-100 text-blue-700'
              : score >= 40 ? 'bg-amber-100 text-amber-700'
              : 'bg-red-100 text-red-700'
  return (
    <div className={clsx('w-12 h-12 rounded-xl flex flex-col items-center justify-center flex-shrink-0', color)}>
      <span className="font-display font-bold text-lg leading-none">{score}</span>
      <span className="text-xs leading-none opacity-70">pts</span>
    </div>
  )
}

function toList(value) {
  if (Array.isArray(value)) return value.filter(Boolean)
  if (!value) return []
  return String(value).split(/[,;\n]/).map(item => item.trim()).filter(Boolean)
}

function textValue(value, fallback = 'Not available') {
  if (Array.isArray(value)) return value.filter(Boolean).join(', ') || fallback
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

function resumeExcerpt(value) {
  if (!value) return ''
  const raw = String(value).trim()
  if (/^https?:\/\//i.test(raw)) return ''
  return raw.length > 1200 ? `${raw.slice(0, 1200).trim()}...` : raw
}

function buildFitDescription(trainer, _requirement) {
  const tech = _requirement?.technology_needed || 'this requirement'
  const matchedSkills = trainer.score_breakdown?.skills?.matched_required || []
  const preferred = trainer.score_breakdown?.skills?.matched_preferred || []
  const parts = [
    `${trainer.name} is shortlisted for ${tech} with a match score of ${trainer.match_score ?? 0}/100.`,
  ]
  if (trainer.experience_raw || trainer.experience_years) {
    parts.push(`The profile shows ${trainer.experience_raw || `${trainer.experience_years}+ years`} of experience.`)
  }
  if (matchedSkills.length) {
    parts.push(`Resume should clearly highlight hands-on work in ${matchedSkills.join(', ')}.`)
  } else if (_requirement?.required_skills?.length) {
    parts.push(`Resume should explicitly mention the required skills: ${_requirement.required_skills.join(', ')}.`)
  }
  if (preferred.length) {
    parts.push(`Preferred strengths found include ${preferred.join(', ')}.`)
  }
  if (trainer.certifications?.length) {
    parts.push(`Certifications to verify: ${toList(trainer.certifications).join(', ')}.`)
  }
  if (trainer.past_clients?.length) {
    parts.push(`Past client/training evidence should include ${toList(trainer.past_clients).slice(0, 5).join(', ')}.`)
  }
  if (trainer.ai_match_reason) parts.push(`AI fit note: ${trainer.ai_match_reason}`)
  return parts.join(' ')
}

function DetailSection({ title, icon: Icon, children }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h4 className="mb-3 flex items-center gap-2 text-sm font-bold text-slate-800">
        <Icon className="h-4 w-4 text-brand-500" /> {title}
      </h4>
      {children}
    </section>
  )
}

function TrainerDetailModal({ trainer, rank, requirement, onClose }) {
  const skills = toList(trainer.skills)
  const certs = toList(trainer.certifications)
  const clients = toList(trainer.past_clients)
  const secondary = toList(trainer.secondary_categories)
  const industries = toList(trainer.industry_focus)
  const languages = toList(trainer.language_of_delivery)
  const excerpt = resumeExcerpt(trainer.resume)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 p-5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-lg bg-brand-50 px-2.5 py-1 text-xs font-bold text-brand-600">Rank #{rank}</span>
              <span className="rounded-lg bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700">{trainer.match_score ?? 0}/100 match</span>
              {trainer.status && <span className="badge-slate">{trainer.status}</span>}
            </div>
            <h3 className="mt-2 font-display text-2xl font-bold text-slate-900">{trainer.name}</h3>
            <p className="mt-1 text-sm text-slate-500">{textValue(trainer.technologies)}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="space-y-4">
              <DetailSection title="Profile Description" icon={BookOpenCheck}>
                <p className="text-sm leading-6 text-slate-700">{buildFitDescription(trainer, requirement)}</p>
                {trainer.summary && (
                  <p className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-700">
                    {trainer.summary}
                  </p>
                )}
              </DetailSection>

              <DetailSection title="Resume Evidence" icon={FileText}>
                {excerpt ? (
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-3 font-sans text-sm leading-6 text-slate-700">{excerpt}</pre>
                ) : trainer.resume ? (
                  <a href={trainer.resume} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm font-semibold text-brand-600 hover:underline">
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
                {secondary.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {secondary.map(item => <span key={item} className="badge-slate">{item}</span>)}
                  </div>
                )}
              </DetailSection>
            </div>

            <div className="space-y-4">
              <DetailSection title="Contact & Experience" icon={BriefcaseBusiness}>
                <div className="space-y-2 text-sm text-slate-700">
                  <p><strong>Experience:</strong> {trainer.experience_raw || `${trainer.experience_years || 0} years`}</p>
                  <p><strong>Location:</strong> {textValue(trainer.location)}</p>
                  <p><strong>Email:</strong> {textValue(trainer.email)}</p>
                  <p><strong>Phone:</strong> {textValue(trainer.phone)}</p>
                  <p><strong>LinkedIn:</strong> {trainer.linkedin ? <a className="text-brand-600 hover:underline" href={trainer.linkedin} target="_blank" rel="noreferrer">Open profile</a> : 'Not available'}</p>
                  <p><strong>Trainings:</strong> {trainer.training_count ?? 'Not available'}</p>
                  <p><strong>Day rate:</strong> {trainer.day_rate ? `INR ${Number(trainer.day_rate).toLocaleString('en-IN')}` : 'Not available'}</p>
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
                      {clients.length ? clients.map(client => <span key={client} className="badge-slate">{client}</span>) : <span className="text-sm text-slate-500">No past clients listed</span>}
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
                    const item = trainer.score_breakdown?.[key] || {}
                    const max = item.max || 1
                    const score = item.score || 0
                    return (
                      <div key={key}>
                        <div className="mb-1 flex justify-between text-xs font-semibold text-slate-500">
                          <span>{label}</span><span>{score}/{max}</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                          <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.min(100, Math.round((score / max) * 100))}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </DetailSection>

              {(industries.length > 0 || languages.length > 0 || trainer.domain || trainer.primary_category) && (
                <DetailSection title="Category Details" icon={Users}>
                  <div className="space-y-2 text-sm text-slate-700">
                    <p><strong>Primary:</strong> {textValue(trainer.primary_category || trainer.technology_category || trainer.category)}</p>
                    <p><strong>Domain:</strong> {textValue(trainer.domain)}</p>
                    {industries.length > 0 && <p><strong>Industry:</strong> {industries.join(', ')}</p>}
                    {languages.length > 0 && <p><strong>Language:</strong> {languages.join(', ')}</p>}
                  </div>
                </DetailSection>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function AutomationPipelinePreview({ trainer, requirement }) {
  const clientEmail = requirement?.client_email || ''
  const stages = [
    { step: '01', title: 'Mail 1', desc: 'First contact to trainer', tone: 'blue' },
    { step: '02', title: 'Mail 2', desc: 'Request trainer details', tone: 'indigo' },
    { step: '03', title: 'Mail 3', desc: 'Ask interview slots', tone: 'amber' },
    { step: 'C', title: 'Client Mail', desc: clientEmail ? `Slots go to ${clientEmail}` : 'Client email missing', tone: clientEmail ? 'cyan' : 'orange' },
    { step: '04', title: 'Mail 4', desc: 'Interview link to trainer', tone: 'purple' },
    { step: '05', title: 'Mail 5', desc: 'Selection or rejection', tone: 'emerald' },
    { step: '06', title: 'Mail 6', desc: 'ToC / agenda request', tone: 'teal' },
    { step: '07', title: 'Mail 7', desc: 'Training confirmation', tone: 'green' },
  ]
  const toneClass = {
    blue: 'border-blue-100 bg-blue-50 text-blue-700',
    indigo: 'border-indigo-100 bg-indigo-50 text-indigo-700',
    amber: 'border-amber-100 bg-amber-50 text-amber-700',
    cyan: 'border-cyan-100 bg-cyan-50 text-cyan-700',
    orange: 'border-orange-100 bg-orange-50 text-orange-700',
    purple: 'border-purple-100 bg-purple-50 text-purple-700',
    emerald: 'border-emerald-100 bg-emerald-50 text-emerald-700',
    teal: 'border-teal-100 bg-teal-50 text-teal-700',
    green: 'border-green-100 bg-green-50 text-green-700',
  }

  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-white p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">7-stage automation pipeline</p>
          <p className="mt-0.5 text-xs text-slate-500">For {trainer.name}: trainer mails, client slot mail, ToC, and final confirmation.</p>
        </div>
        <a
          href="/shortlist1"
          onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand-500 px-3 py-2 text-xs font-bold text-white transition hover:bg-brand-600"
        >
          <TrendingUp className="h-3.5 w-3.5" /> Open AI Pipeline
        </a>
      </div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {stages.map(item => (
          <div key={`${item.step}-${item.title}`} className={clsx('rounded-lg border px-2.5 py-2', toneClass[item.tone])}>
            <div className="flex items-center gap-2">
              <span className="flex h-5 min-w-5 items-center justify-center rounded-md bg-white/75 px-1 text-[10px] font-black">{item.step}</span>
              <span className="text-xs font-bold">{item.title}</span>
            </div>
            <p className="mt-1 text-[11px] leading-4 opacity-80">{item.desc}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

const TrainerCard = ({ trainer, rank, requirement, onOpen }) => (
  <div
    role="button"
    tabIndex={0}
    onClick={() => onOpen(trainer, rank)}
    onKeyDown={e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onOpen(trainer, rank)
      }
    }}
    className="card-hover cursor-pointer p-5 animate-slide-up focus:outline-none focus:ring-2 focus:ring-brand-500/30"
  >
    <div className="flex items-start gap-4">
      <div className="w-8 h-8 rounded-lg bg-brand-50 flex items-center justify-center flex-shrink-0">
        <span className="font-display font-bold text-brand-600 text-sm">#{rank}</span>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h3 className="font-display font-semibold text-slate-900">{trainer.name}</h3>
            <p className="text-sm text-slate-500 mt-0.5 line-clamp-1">{trainer.technologies?.substring(0, 80)}</p>
            {trainer.ai_match_reason && (
              <p className="mt-1 text-xs text-slate-500 line-clamp-1">{trainer.ai_match_reason}</p>
            )}
          </div>
          <ScoreBadge score={trainer.match_score} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
          <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5 text-slate-400" />{trainer.experience_raw || `${trainer.experience_years}yrs`}</span>
          {trainer.location && <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5 text-slate-400" />{trainer.location}</span>}
          {trainer.email && <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5 text-slate-400" />{trainer.email}</span>}
          {trainer.phone && <span className="flex items-center gap-1"><Phone className="w-3.5 h-3.5 text-slate-400" />{trainer.phone}</span>}
        </div>
        {trainer.skills?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {trainer.skills.slice(0, 5).map((s, i) => (
              <span key={i} className="badge-blue text-xs">{s}</span>
            ))}
            {trainer.skills.length > 5 && <span className="badge-slate">+{trainer.skills.length - 5}</span>}
          </div>
        )}
        {trainer.score_breakdown && (
          <div className="mt-3 grid grid-cols-5 gap-2">
            {[
              { label: 'Tech',  key: 'technology',    max: 35, color: 'bg-blue-500' },
              { label: 'Skills',key: 'skills',        max: 30, color: 'bg-emerald-500' },
              { label: 'Exp',   key: 'experience',    max: 20, color: 'bg-purple-500' },
              { label: 'Cert',  key: 'certifications',max: 10, color: 'bg-amber-500' },
              { label: 'Loc',   key: 'location',      max: 5,  color: 'bg-rose-500' },
            ].map(({ label, key, max, color }) => {
              const val = trainer.score_breakdown[key]?.score ?? 0
              const pct = Math.round((val / max) * 100)
              return (
                <div key={key} className="text-center">
                  <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden mb-1">
                    <div className={clsx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
                  </div>
                  <p className="text-xs text-slate-400">{label}</p>
                  <p className="text-xs font-semibold text-slate-700">{val}/{max}</p>
                </div>
              )
            })}
          </div>
        )}
        <AutomationPipelinePreview trainer={trainer} requirement={requirement} />
        <div className="mt-3 flex items-center gap-3">
          {trainer.has_linkedin && (
            <a href={trainer.linkedin} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
               className="flex items-center gap-1 text-xs text-brand-500 hover:underline">
              <Linkedin className="w-3.5 h-3.5" /> LinkedIn
            </a>
          )}
          {trainer.has_resume && (
            <a href={trainer.resume} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
               className="flex items-center gap-1 text-xs text-brand-500 hover:underline">
              <FileText className="w-3.5 h-3.5" /> Resume
            </a>
          )}
          <span className="flex items-center gap-1 text-xs font-semibold text-brand-500">
            <Eye className="w-3.5 h-3.5" /> View details
          </span>
          <span className={clsx('ml-auto badge',
            trainer.status === 'interested' ? 'badge-green' :
            trainer.status === 'contacted'  ? 'badge-blue'  :
            trainer.status === 'declined'   ? 'badge-red'   : 'badge-slate')}>
            {trainer.status}
          </span>
        </div>
      </div>
    </div>
  </div>
)

export default function Requirements() {
  const [reqs, setReqs]         = useState([])
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading]   = useState(false)
  const [loadingMode, setLoadingMode] = useState('')
  const [result, setResult]     = useState(null)
  const [selectedTrainer, setSelectedTrainer] = useState(null)
  const [skillInput, setSkillInput] = useState('')
  const [skillSuggestions, setSkillSuggestions] = useState([])
  const [deletingReqId, setDeletingReqId] = useState('')
  const [form, setForm] = useState({
    technology_needed: '',
    job_title: '',
    job_description: '',
    min_experience_years: 2,
    required_skills: [],
    preferred_skills: [],
    required_certifications: [],
    preferred_location: '',
    client_name: '',
    client_company: '',
    client_email: '',
    must_have_linkedin: false,
    must_have_resume: false,
    top_n: 5,
  })

  useEffect(() => {
    getRequirements().then(r => setReqs(r.data.requirements || [])).catch(() => {})
  }, [])

  // Generate skill suggestions based on input
  useEffect(() => {
    if (!skillInput.trim()) { setSkillSuggestions([]); return }
    const allSkills = [
      'python','javascript','typescript','react','angular','vue','node.js','django','flask','fastapi',
      'aws','azure','gcp','docker','kubernetes','jenkins','terraform','ansible','linux','git',
      'machine learning','deep learning','data science','statistics','tensorflow','pytorch','scikit-learn',
      'pandas','numpy','tableau','power bi','sql','mongodb','postgresql','redis','elasticsearch',
      'java','spring boot','microservices','hibernate','maven','gradle',
      'c++','c#','.net','unity','rust','go','kotlin','swift','flutter','react native',
      'ci/cd','devops','agile','scrum','jira','confluence','selenium','cypress',
    ]
    const q = skillInput.toLowerCase()
    const matches = allSkills.filter(s => s.includes(q) && !form.required_skills.includes(s)).slice(0, 6)
    setSkillSuggestions(matches)
  }, [skillInput, form.required_skills])

  const addSkill = (skill, field = 'required_skills') => {
    const s = skill.trim().toLowerCase()
    if (s && !form[field].includes(s))
      setForm(f => ({ ...f, [field]: [...f[field], s] }))
    setSkillInput('')
    setSkillSuggestions([])
  }

  const removeSkill = (skill, field) =>
    setForm(f => ({ ...f, [field]: f[field].filter(s => s !== skill) }))

  const applyPreset = (tech) => {
    setForm(f => ({
      ...f,
      technology_needed: tech,
      job_title: `${tech} Trainer`,
      required_skills: SKILLS_PRESETS[tech] || [],
    }))
  }

  // Only shortlist, no email
  const handleShortlistOnly = async (topN = form.top_n) => {
    if (!form.technology_needed) return toast.error('Technology is required')
    if (!form.client_email.trim()) return toast.error('Client email is required for automatic slot handoff')
    const shortlistCount = Number(topN) || form.top_n
    setLoading(true); setLoadingMode(shortlistCount === 1 ? 'top1' : 'shortlist'); setResult(null)
    try {
      const res = await createRequirement({ ...form, top_n: shortlistCount, send_emails: false })
      setResult(res.data)
      setShowForm(false)
      toast.success(`✅ Shortlisted ${res.data.top_trainers} trainers!`)
      getRequirements().then(r => setReqs(r.data.requirements || []))
    } catch (e) { toast.error(e.message) }
    finally { setLoading(false); setLoadingMode('') }
  }

  const handleDeleteRequirement = async requirement => {
    const requirementId = requirement?.requirement_id || requirement
    if (!requirementId || deletingReqId) return
    const label = requirement?.technology_needed || form.technology_needed || requirementId
    if (!globalThis.confirm(`Delete "${label}" from Find Trainers? This removes its shortlist and pipeline data.`)) return

    setDeletingReqId(requirementId)
    try {
      await deleteRequirement(requirementId)
      localStorage.removeItem(`sl_v5_${requirementId}`)
      setReqs(prev => prev.filter(item => item.requirement_id !== requirementId))
      if (result?.requirement_id === requirementId) {
        setResult(null)
        setSelectedTrainer(null)
      }
      toast.success(`${label} deleted`)
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Could not delete search')
    } finally {
      setDeletingReqId('')
    }
  }



  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="page-title">Find Trainers</h1>
          <p className="text-sm text-slate-500 mt-0.5">Search and shortlist top trainers for your requirement</p>
        </div>
        <button onClick={() => { setShowForm(true); setResult(null); setSelectedTrainer(null) }} className="btn-primary">
          <Plus className="w-4 h-4" /> New Search
        </button>
      </div>

      {/* Search Form */}
      {showForm && (
        <div className="card p-6 animate-slide-up">
          <div className="flex items-center justify-between mb-5">
            <h2 className="section-title">Search Requirements</h2>
            <button onClick={() => setShowForm(false)} className="p-1.5 hover:bg-slate-100 rounded-lg">
              <X className="w-4 h-4 text-slate-500" />
            </button>
          </div>

          {/* Quick presets */}
          <div className="mb-5">
            <p className="label">Quick Presets</p>
            <div className="flex flex-wrap gap-2">
              {Object.keys(SKILLS_PRESETS).map(tech => (
                <button key={tech} onClick={() => applyPreset(tech)}
                  className={clsx('px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors',
                    form.technology_needed === tech
                      ? 'bg-brand-500 text-white border-brand-500'
                      : 'bg-white text-slate-600 border-slate-200 hover:border-brand-400 hover:text-brand-600'
                  )}>{tech}</button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="label">Technology / Domain *</label>
              <input className="input" placeholder="e.g. Python, AWS, React"
                value={form.technology_needed}
                onChange={e => setForm(f => ({ ...f, technology_needed: e.target.value }))} />
            </div>
            <div>
              <label className="label">Job Title</label>
              <input className="input" placeholder="e.g. Python Trainer"
                value={form.job_title}
                onChange={e => setForm(f => ({ ...f, job_title: e.target.value }))} />
            </div>
            <div>
              <label className="label">Client Email *</label>
              <input className="input" type="email" placeholder="client@company.com"
                value={form.client_email}
                onChange={e => setForm(f => ({ ...f, client_email: e.target.value }))} />
            </div>
            <div>
              <label className="label">Client Name / Company</label>
              <input className="input" placeholder="e.g. Test Client or ABC Corp"
                value={form.client_name || form.client_company}
                onChange={e => setForm(f => ({ ...f, client_name: e.target.value, client_company: e.target.value }))} />
            </div>
            <div>
              <label className="label">Minimum Experience</label>
              <select className="input" value={form.min_experience_years}
                onChange={e => setForm(f => ({ ...f, min_experience_years: parseInt(e.target.value) }))}>
                {[1,2,3,5,8,10,12,15].map(y => (
                  <option key={y} value={y}>{y}+ year{y > 1 ? 's' : ''}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Preferred Location <span className="text-slate-400 font-normal">(optional)</span></label>
              <input className="input" placeholder="e.g. Bangalore, Pune"
                value={form.preferred_location}
                onChange={e => setForm(f => ({ ...f, preferred_location: e.target.value }))} />
            </div>
            <div>
              <label className="label">Shortlist Top</label>
              <select className="input" value={form.top_n}
                onChange={e => setForm(f => ({ ...f, top_n: parseInt(e.target.value) }))}>
                {[1,3,5,8,10].map(n => <option key={n} value={n}>Top {n} Trainer{n > 1 ? 's' : ''}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Required Certifications <span className="text-slate-400 font-normal">(optional)</span></label>
              <input className="input" placeholder="e.g. AWS Certified, PMP"
                value={form.required_certifications.join(', ')}
                onChange={e => setForm(f => ({
                  ...f,
                  required_certifications: e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                }))} />
            </div>
          </div>

          <div className="mt-4">
            <label className="label">Job Description <span className="text-slate-400 font-normal">(optional)</span></label>
            <textarea className="input resize-none" rows={3}
              placeholder="Describe the training role, batch details, etc."
              value={form.job_description}
              onChange={e => setForm(f => ({ ...f, job_description: e.target.value }))} />
          </div>

          {/* Required Skills with autocomplete suggestions */}
          <div className="mt-4">
            <label className="label">Required Skills</label>
            <div className="flex gap-2 mb-2">
              <div className="relative flex-1">
                <input className="input w-full" placeholder="Type skill + Enter or click suggestion"
                  value={skillInput}
                  onChange={e => setSkillInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addSkill(skillInput)} />
                {/* Suggestions dropdown */}
                {skillSuggestions.length > 0 && (
                  <div className="absolute top-full left-0 right-0 z-10 mt-1 bg-white border border-slate-200 rounded-xl shadow-lg overflow-hidden">
                    {skillSuggestions.map(s => (
                      <button key={s} type="button"
                        onClick={() => addSkill(s)}
                        className="w-full text-left px-4 py-2.5 text-sm text-slate-700 hover:bg-brand-50 hover:text-brand-600 transition-colors">
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button onClick={() => addSkill(skillInput)} className="btn-secondary">Add</button>
            </div>
            <div className="flex flex-wrap gap-2">
              {form.required_skills.map(s => (
                <span key={s} className="badge-blue flex items-center gap-1">
                  {s}
                  <button onClick={() => removeSkill(s, 'required_skills')}><X className="w-3 h-3" /></button>
                </span>
              ))}
            </div>
          </div>

          {/* Preferred Skills */}
          <div className="mt-4">
            <label className="label">Preferred Skills <span className="text-slate-400 font-normal">(bonus scoring)</span></label>
            <div className="flex gap-2 mb-2">
              <input className="input flex-1" placeholder="Type preferred skill + Enter"
                onKeyDown={e => { if (e.key === 'Enter') { addSkill(e.target.value, 'preferred_skills'); e.target.value = '' }}} />
            </div>
            <div className="flex flex-wrap gap-2">
              {form.preferred_skills.map(s => (
                <span key={s} className="badge-slate flex items-center gap-1">
                  {s}
                  <button onClick={() => removeSkill(s, 'preferred_skills')}><X className="w-3 h-3" /></button>
                </span>
              ))}
            </div>
          </div>

          <div className="mt-4 flex items-center gap-6">
            {[
              { key: 'must_have_linkedin', label: 'Must have LinkedIn' },
              { key: 'must_have_resume',   label: 'Must have Resume'   },
            ].map(({ key, label }) => (
              <label key={key} className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" className="w-4 h-4 accent-brand-500"
                  checked={form[key]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.checked }))} />
                <span className="text-sm text-slate-700">{label}</span>
              </label>
            ))}
          </div>

          {/* TWO SEPARATE BUTTONS */}
          <div className="mt-6 flex gap-3 flex-wrap">
            <button onClick={() => handleShortlistOnly(1)} disabled={loading} className="btn-primary flex-1 justify-center py-3 min-w-40">
              {loading && loadingMode === 'top1' ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Finding Top 1...</>
              ) : (
                <><Star className="w-4 h-4" /> Top 1 Shortlist</>
              )}
            </button>
            <button onClick={() => handleShortlistOnly()} disabled={loading} className="btn-secondary flex-1 justify-center py-3 min-w-40">
              {loading && loadingMode === 'shortlist' ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Finding...</>
              ) : (
                <><Users className="w-4 h-4" /> Shortlist Only</>
              )}
            </button>
            <button onClick={() => setShowForm(false)} className="btn-secondary">Cancel</button>
          </div>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4 animate-fade-in">
          <div className="card p-5 bg-brand-50 border-brand-100">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <TrendingUp className="w-5 h-5 text-brand-500" />
              <h2 className="section-title text-brand-800">Pipeline Results — {result.requirement_id}</h2>
              </div>
              <button
                onClick={() => handleDeleteRequirement(result)}
                disabled={deletingReqId === result.requirement_id}
                className="inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-white px-3 py-2 text-xs font-bold text-red-600 transition hover:bg-red-50 disabled:opacity-50">
                {deletingReqId === result.requirement_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                Delete
              </button>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Scanned',      value: result.total_trainers_scanned },
                { label: 'Matched',      value: result.total_matched },
                { label: 'Shortlisted',  value: result.top_trainers },
                { label: 'Client Mail',  value: result.client_email || form.client_email || 'Missing' },
              ].map(s => (
                <div key={s.label} className="bg-white rounded-xl p-3 text-center border border-brand-100">
                  <p className={clsx(
                    'font-display font-bold text-brand-700',
                    s.label === 'Client Mail' ? 'break-all text-sm' : 'text-2xl'
                  )}>{s.value}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{s.label}</p>
                </div>
              ))}
            </div>
          </div>
          <h2 className="section-title">Top Matched Trainers</h2>
          <div className="space-y-3">
            {(result.top_trainers_list || []).map((t, i) => (
              <TrainerCard
                key={t.trainer_id}
                trainer={t}
                rank={i + 1}
                requirement={{ ...form, ...result, client_email: result.client_email || form.client_email }}
                onOpen={(trainer, rank) => setSelectedTrainer({ trainer, rank })}
              />
            ))}
          </div>
        </div>
      )}

      {selectedTrainer && (
        <TrainerDetailModal
          trainer={selectedTrainer.trainer}
          rank={selectedTrainer.rank}
          requirement={form}
          onClose={() => setSelectedTrainer(null)}
        />
      )}

      {/* Past Requirements */}
      {reqs.length > 0 && !result && (
        <div>
          <h2 className="section-title mb-4">Past Searches</h2>
          <div className="space-y-3">
            {reqs.map(r => (
              <div key={r.requirement_id} className="card-hover p-4 flex items-center gap-4 group">
                <div className="w-10 h-10 rounded-xl bg-brand-50 flex items-center justify-center flex-shrink-0">
                  <Search className="w-5 h-5 text-brand-500" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-slate-800">{r.technology_needed}</p>
                  <p className={clsx('mt-1 flex items-center gap-1 text-xs', r.client_email ? 'text-emerald-600' : 'text-amber-600')}>
                    <Mail className="h-3 w-3" />
                    {r.client_email ? `Client: ${r.client_email}` : 'Client email missing'}
                  </p>
                  <p className="text-xs text-slate-400">{r.requirement_id} • {r.min_experience_years}+ yrs exp • Top {r.top_n}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="badge-blue">{r.total_matched || 0} matched</span>
                  <button
                    onClick={e => {
                      e.stopPropagation()
                      handleDeleteRequirement(r)
                    }}
                    disabled={deletingReqId === r.requirement_id}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-xs font-bold text-red-600 transition-all hover:bg-red-100 disabled:opacity-50">
                    {deletingReqId === r.requirement_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
