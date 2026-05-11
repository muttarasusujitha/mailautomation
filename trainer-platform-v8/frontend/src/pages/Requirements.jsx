import { useState, useEffect } from 'react'
import { createRequirement, shortlistOnly, getRequirements } from '../utils/api'
import api from '../utils/api'
import toast from 'react-hot-toast'
import {
  Search, Plus, X, Star, MapPin, Mail,
  Phone, Linkedin, FileText, Award, Clock, Loader2, ChevronRight,
  TrendingUp, Users, Trash2
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

const TrainerCard = ({ trainer, rank }) => (
  <div className="card-hover p-5 animate-slide-up">
    <div className="flex items-start gap-4">
      <div className="w-8 h-8 rounded-lg bg-brand-50 flex items-center justify-center flex-shrink-0">
        <span className="font-display font-bold text-brand-600 text-sm">#{rank}</span>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h3 className="font-display font-semibold text-slate-900">{trainer.name}</h3>
            <p className="text-sm text-slate-500 mt-0.5 line-clamp-1">{trainer.technologies?.substring(0, 80)}</p>
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
        <div className="mt-3 flex items-center gap-3">
          {trainer.has_linkedin && (
            <a href={trainer.linkedin} target="_blank" rel="noreferrer"
               className="flex items-center gap-1 text-xs text-brand-500 hover:underline">
              <Linkedin className="w-3.5 h-3.5" /> LinkedIn
            </a>
          )}
          {trainer.has_resume && (
            <a href={trainer.resume} target="_blank" rel="noreferrer"
               className="flex items-center gap-1 text-xs text-brand-500 hover:underline">
              <FileText className="w-3.5 h-3.5" /> Resume
            </a>
          )}
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
  const [skillInput, setSkillInput] = useState('')
  const [skillSuggestions, setSkillSuggestions] = useState([])
  const [form, setForm] = useState({
    technology_needed: '',
    job_title: '',
    job_description: '',
    min_experience_years: 2,
    required_skills: [],
    preferred_skills: [],
    required_certifications: [],
    preferred_location: '',
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
  const handleShortlistOnly = async () => {
    if (!form.technology_needed) return toast.error('Technology is required')
    setLoading(true); setLoadingMode('shortlist'); setResult(null)
    try {
      const res = await createRequirement({ ...form, send_emails: false })
      setResult(res.data)
      setShowForm(false)
      toast.success(`✅ Shortlisted ${res.data.top_trainers} trainers!`)
      getRequirements().then(r => setReqs(r.data.requirements || []))
    } catch (e) { toast.error(e.message) }
    finally { setLoading(false); setLoadingMode('') }
  }



  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="page-title">Find Trainers</h1>
          <p className="text-sm text-slate-500 mt-0.5">Search and shortlist top trainers for your requirement</p>
        </div>
        <button onClick={() => { setShowForm(true); setResult(null) }} className="btn-primary">
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
                {[3,5,8,10].map(n => <option key={n} value={n}>Top {n} Trainers</option>)}
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
            <button onClick={handleShortlistOnly} disabled={loading} className="btn-secondary flex-1 justify-center py-3 min-w-40">
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
            <div className="flex items-center gap-3 mb-3">
              <TrendingUp className="w-5 h-5 text-brand-500" />
              <h2 className="section-title text-brand-800">Pipeline Results — {result.requirement_id}</h2>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Scanned',      value: result.total_trainers_scanned },
                { label: 'Matched',      value: result.total_matched },
                { label: 'Shortlisted',  value: result.top_trainers },
              ].map(s => (
                <div key={s.label} className="bg-white rounded-xl p-3 text-center border border-brand-100">
                  <p className="font-display text-2xl font-bold text-brand-700">{s.value}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{s.label}</p>
                </div>
              ))}
            </div>
          </div>
          <h2 className="section-title">Top Matched Trainers</h2>
          <div className="space-y-3">
            {(result.top_trainers_list || []).map((t, i) => (
              <TrainerCard key={t.trainer_id} trainer={t} rank={i + 1} />
            ))}
          </div>
        </div>
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
                  <p className="text-xs text-slate-400">{r.requirement_id} • {r.min_experience_years}+ yrs exp • Top {r.top_n}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="badge-blue">{r.total_matched || 0} matched</span>
                  <button
                    onClick={async (e) => {
                      e.stopPropagation()
                      if (!confirm(`Remove search for "${r.technology_needed}"?`)) return
                      try {
                        await api.delete(`/requirements/${r.requirement_id}`)
                        toast.success('Search removed')
                        getRequirements().then(res => setReqs(res.data.requirements || []))
                      } catch (err) { toast.error(err.message) }
                    }}
                    className="p-1.5 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-all opacity-0 group-hover:opacity-100">
                    <Trash2 className="w-4 h-4" />
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
