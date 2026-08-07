import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Award, FileText, Mail, MapPin, Phone, RefreshCw, Search, Star, Users, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { getTocKnowledge, getTrainer, getTrainers } from '../utils/api'

function clean(value) {
  const text = String(value || '').trim()
  return text && !['-', '--', 'unknown', 'n/a', 'na', 'none', 'null', 'not available'].includes(text.toLowerCase()) ? text : ''
}

function skillsText(trainer) {
  if (Array.isArray(trainer.skills)) return trainer.skills.filter(Boolean).join(', ')
  return clean(trainer.skills || trainer.technologies || trainer.domain || trainer.technology_category)
}

function trainerLocation(trainer, fallback = '') {
  return clean(
    trainer.location ||
    trainer.city ||
    trainer.current_location ||
    trainer.preferred_location ||
    trainer.base_location ||
    trainer.address ||
    trainer.country
  ) || clean(fallback)
}

function trainerScore(trainer) {
  const values = [trainer.resume_rank_score, trainer.profile_score, trainer.overall_score, trainer.match_score]
  for (const value of values) {
    const number = Number(value)
    if (Number.isFinite(number) && number > 0) return Math.round(number)
  }
  return 0
}

function compactResumeText(value) {
  const text = String(value || '').trim()
  if (!text || /^https?:\/\//i.test(text)) return ''
  return text.length > 2200 ? `${text.slice(0, 2200).trim()}...` : text
}

function resumeText(trainer) {
  return compactResumeText(trainer.resume || trainer.extracted_text || trainer.combined_text || trainer.summary || trainer.bio)
}

function trainerDescription(trainer) {
  const name = clean(trainer.name) || 'This trainer'
  const score = trainerScore(trainer)
  const skills = skillsText(trainer)
  const domain = clean(trainer.primary_category || trainer.technology_category || trainer.domain || trainer.category) || 'training'
  const excerpt = compactResumeText(trainer.summary || trainer.bio || trainer.resume || trainer.extracted_text)
  return `${name}${score ? ` has a ${score}/100 trainer profile` : ' has a trainer profile'} for ${domain}.${skills ? ` Profile extracted: ${skills}. Skills found in resume: ${skills}.` : ''}${excerpt ? ` Resume summary excerpt: ${excerpt}` : ''}`
}

const KNOWN_LOCATIONS = [
  'hyderabad', 'bangalore', 'bengaluru', 'chennai', 'pune', 'mumbai', 'delhi',
  'new delhi', 'gurgaon', 'gurugram', 'noida', 'kolkata', 'ahmedabad',
  'coimbatore', 'kochi', 'trivandrum', 'bhubaneswar', 'jaipur', 'india',
  'hyd', 'hyderbad', 'hyderabafd', 'hyderabd',
]

function compactText(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '')
}

function tocTermsFromDomains(domains) {
  return domains.flatMap(domain => {
    const source = domain.level_map ? domain : { ...domain, ...(domain.toc || {}) }
    return [
      source.name,
      source.key,
      source.domain,
      ...(source.aliases || []),
    ].map(clean).filter(Boolean)
  })
}

function normaliseTechnology(value, tocTerms = []) {
  const text = value.trim()
  const compact = compactText(text)
  if (!compact) return ''
  if (compact === 'fullstack') return 'Full Stack'
  const match = tocTerms.find(term => compactText(term) === compact)
  return match || text
}

function parseSearch(value, tocTerms = []) {
  const text = value.trim()
  if (!text) return { skill: '', location: '' }
  const words = text.split(/\s+/)
  const lowerWords = words.map(word => word.toLowerCase())
  let location = ''
  for (let size = Math.min(3, words.length); size >= 1; size -= 1) {
    for (let index = 0; index <= words.length - size; index += 1) {
      const phrase = lowerWords.slice(index, index + size).join(' ')
      if (KNOWN_LOCATIONS.includes(phrase)) {
        location = words.slice(index, index + size).join(' ')
        if (['hyd', 'hyderbad', 'hyderabafd', 'hyderabd'].includes(phrase)) location = 'Hyderabad'
        if (phrase === 'bangalore') location = 'Bengaluru'
        if (phrase === 'gurgaon') location = 'Gurugram'
        let skill = words.filter((_, wordIndex) => wordIndex < index || wordIndex >= index + size).join(' ')
        skill = normaliseTechnology(skill, tocTerms)
        return { skill, location: location.trim() }
      }
    }
  }
  return { skill: normaliseTechnology(text, tocTerms), location: '' }
}

export default function TrainerLocations() {
  const [trainers, setTrainers] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [tocDomains, setTocDomains] = useState([])
  const [selectedTrainer, setSelectedTrainer] = useState(null)
  const [loadingTrainerId, setLoadingTrainerId] = useState('')

  const tocTerms = useMemo(() => tocTermsFromDomains(tocDomains), [tocDomains])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const parsed = parseSearch(query, tocTerms)
      const res = await getTrainers({
        limit: 1000,
        domain: parsed.skill || undefined,
        location: parsed.location || undefined,
        strict_location: parsed.location ? true : undefined,
        search: !parsed.location ? parsed.skill || undefined : undefined,
      })
      setTrainers(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch (error) {
      toast.error(error.message || 'Could not load trainer locations')
    } finally {
      setLoading(false)
    }
  }, [query, tocTerms])

  useEffect(() => {
    const loadTocDomains = async () => {
      try {
        const { data } = await getTocKnowledge()
        setTocDomains(data.domains || data.items || [])
      } catch {
        setTocDomains([])
      }
    }
    loadTocDomains()
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const groups = useMemo(() => {
    const map = new Map()
    const parsed = parseSearch(query, tocTerms)
    trainers.forEach(trainer => {
      const location = trainerLocation(trainer, parsed.location) || 'Location not added'
      if (!map.has(location)) map.set(location, [])
      map.get(location).push(trainer)
    })
    map.forEach(items => {
      items.sort((a, b) => trainerScore(b) - trainerScore(a) || clean(a.name).localeCompare(clean(b.name)))
    })
    return [...map.entries()].sort(([a], [b]) => {
      if (a === 'Location not added') return 1
      if (b === 'Location not added') return -1
      return a.localeCompare(b)
    })
  }, [query, tocTerms, trainers])

  const visibleCount = groups.reduce((sum, [, items]) => sum + items.length, 0)
  const parsedQuery = parseSearch(query, tocTerms)

  const openTrainer = async (trainer) => {
    const trainerId = clean(trainer.trainer_id || trainer._id)
    setSelectedTrainer(trainer)
    if (!trainerId) return
    setLoadingTrainerId(trainerId)
    try {
      const res = await getTrainer(trainerId)
      setSelectedTrainer(current => {
        const currentId = clean(current?.trainer_id || current?._id)
        return currentId === trainerId ? { ...trainer, ...(res.data?.trainer || res.data || {}) } : current
      })
    } catch (error) {
      toast.error(error.message || 'Could not load trainer resume')
    } finally {
      setLoadingTrainerId('')
    }
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/trainers" className="mb-2 inline-flex items-center gap-2 text-sm font-semibold text-blue-600 hover:text-blue-700">
            <ArrowLeft className="h-4 w-4" />
            Trainer Database
          </Link>
          <h1 className="page-title">Trainer Locations</h1>
          <p className="mt-0.5 text-sm text-slate-500">{visibleCount} of {total || visibleCount} trainers grouped by location</p>
        </div>
        <button onClick={load} disabled={loading} className="btn-secondary disabled:opacity-60">
          <RefreshCw className={loading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
          Refresh
        </button>
      </div>

      <div className="card p-4">
        <div className="flex flex-col gap-3 md:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input pl-9"
              placeholder="Search any ToC technology and city, example: Azure AI Hyderabad"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') load() }}
            />
          </div>
          <button type="button" onClick={load} disabled={loading} className="btn-primary justify-center disabled:opacity-60">
            {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Search
          </button>
        </div>
        {(parsedQuery.skill || parsedQuery.location) && (
          <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-slate-500">
            {parsedQuery.skill && <span className="rounded-full bg-blue-50 px-2.5 py-1 text-blue-600">Skill: {parsedQuery.skill}</span>}
            {parsedQuery.location && <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-700">Location: {parsedQuery.location}</span>}
          </div>
        )}
      </div>

      {loading ? (
        <div className="card p-8 text-center text-sm font-medium text-slate-500">Loading trainer locations...</div>
      ) : groups.length === 0 ? (
        <div className="card p-12 text-center">
          <MapPin className="mx-auto mb-3 h-10 w-10 text-slate-200" />
          <p className="font-medium text-slate-500">No matching trainer locations</p>
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map(([location, items]) => (
            <section key={location} className="card p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="flex min-w-0 items-center gap-2 font-bold text-slate-900">
                  <MapPin className="h-4 w-4 flex-shrink-0 text-blue-500" />
                  <span className="truncate">{location}</span>
                </h2>
                <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-600">
                  {items.length} trainer{items.length === 1 ? '' : 's'}
                </span>
              </div>
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                {items.map((trainer, index) => (
                  <button
                    type="button"
                    key={trainer.trainer_id || trainer._id || trainer.email || trainer.name}
                    onClick={() => openTrainer(trainer)}
                    className="rounded-lg border border-slate-200 bg-white p-3 text-left transition-colors hover:border-blue-200 hover:bg-blue-50/40 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-slate-900">{clean(trainer.name) || 'Unnamed Trainer'}</p>
                        <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">{skillsText(trainer) || 'No skills listed'}</p>
                      </div>
                      <div className="flex flex-shrink-0 items-center gap-1 rounded-full bg-slate-50 px-2 py-1 text-xs font-bold text-slate-600">
                        <Users className="h-3 w-3 text-slate-300" />
                        #{index + 1}{trainerScore(trainer) ? ` · ${trainerScore(trainer)}` : ''}
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                      {clean(trainer.email) && <span className="flex items-center gap-1"><Mail className="h-3 w-3" />{clean(trainer.email)}</span>}
                      {clean(trainer.phone) && <span className="flex items-center gap-1"><Phone className="h-3 w-3" />{clean(trainer.phone)}</span>}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {selectedTrainer && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 p-3 backdrop-blur-sm sm:p-5">
          <div className="flex max-h-[calc(100vh-1.5rem)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-card-lg sm:max-h-[calc(100vh-2.5rem)]">
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 p-5">
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-600">
                    <Award className="h-3.5 w-3.5" />
                    {trainerScore(selectedTrainer) || 0}/100
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-lg bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-700">
                    <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
                    {(Math.max(0, Math.min(5, trainerScore(selectedTrainer) / 20)) || 0).toFixed(1)}
                  </span>
                  {loadingTrainerId && (
                    <span className="inline-flex items-center gap-1 rounded-lg bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-500">
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                      Loading resume
                    </span>
                  )}
                </div>
                <h2 className="truncate font-jakarta text-2xl font-bold text-slate-900">{clean(selectedTrainer.name) || 'Unnamed Trainer'}</h2>
                <p className="mt-1 line-clamp-2 text-sm text-slate-500">{skillsText(selectedTrainer) || 'No skills listed'}</p>
              </div>
              <button type="button" onClick={() => setSelectedTrainer(null)} className="rounded-xl p-2 transition-colors hover:bg-slate-100" aria-label="Close trainer resume">
                <X className="h-5 w-5 text-slate-500" />
              </button>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="mb-2 flex items-center gap-2 text-sm font-bold text-slate-900">
                  <FileText className="h-4 w-4 text-blue-500" />
                  Profile Description
                </div>
                <p className="text-sm leading-6 text-slate-700">{trainerDescription(selectedTrainer)}</p>
              </section>

              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="mb-2 flex items-center gap-2 text-sm font-bold text-slate-900">
                  <FileText className="h-4 w-4 text-blue-500" />
                  Resume Evidence
                </div>
                {resumeText(selectedTrainer) ? (
                  <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 font-sans text-sm leading-6 text-slate-700">{resumeText(selectedTrainer)}</pre>
                ) : (
                  <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-500">Resume text is still loading or was not stored for this trainer.</p>
                )}
              </section>

              <section className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700 md:grid-cols-2">
                <p><strong>Location:</strong> {trainerLocation(selectedTrainer, parsedQuery.location) || 'Not available'}</p>
                <p><strong>Email:</strong> {clean(selectedTrainer.email) || 'Not available'}</p>
                <p><strong>Phone:</strong> {clean(selectedTrainer.phone) || 'Not available'}</p>
                <p><strong>Skills:</strong> {skillsText(selectedTrainer) || 'Not available'}</p>
              </section>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
