import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, FileSearch, Loader2, RefreshCw, UserRoundCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { getRequirements, getShortlist } from '../utils/api'

const clean = value => String(value || '').trim()

function Tone({ status }) {
  const normalized = clean(status).toLowerCase()
  const styles = normalized === 'strong_fit'
    ? 'border-green-200 bg-green-50 text-green-700'
    : normalized === 'partial_fit'
      ? 'border-amber-200 bg-amber-50 text-amber-700'
      : 'border-slate-200 bg-slate-50 text-slate-700'
  return <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-bold ${styles}`}>{clean(status || 'Not reviewed').replaceAll('_', ' ')}</span>
}

function RequirementLabel({ item }) {
  return (
    <div>
      <p className="font-bold text-slate-900">{clean(item.technology_needed || item.domain || item.title || 'Training Requirement')}</p>
      <p className="mt-1 text-xs text-slate-500">{clean(item.requirement_id || item.id)} · {clean(item.client_name || item.client_company || 'Client')}</p>
    </div>
  )
}

export default function ProfileReviews() {
  const [requirements, setRequirements] = useState([])
  const [reviews, setReviews] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await getRequirements()
      const items = data.requirements || data.items || data.data || []
      setRequirements(items)
      const settled = await Promise.allSettled(
        items.map(async requirement => {
          const requirementId = requirement.requirement_id || requirement.id
          if (!requirementId) return []
          const response = await getShortlist(requirementId)
          const trainers = response.data?.top_trainers || response.data?.shortlist?.top_trainers || []
          return trainers
            .filter(trainer => trainer.requirement_fit || trainer.document_review)
            .map(trainer => ({ requirement, trainer, fit: trainer.requirement_fit || trainer.document_review?.requirement_fit || {} }))
        }),
      )
      const nextReviews = settled.flatMap(result => result.status === 'fulfilled' ? result.value : [])
      setReviews(nextReviews)
      if (!selectedId && nextReviews[0]) setSelectedId(nextReviews[0].requirement.requirement_id || nextReviews[0].requirement.id)
    } catch (error) {
      toast.error(error.message || 'Could not load profile reviews')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const visible = useMemo(
    () => selectedId ? reviews.filter(item => (item.requirement.requirement_id || item.requirement.id) === selectedId) : reviews,
    [reviews, selectedId],
  )
  const selectedRequirement = requirements.find(item => (item.requirement_id || item.id) === selectedId)

  return (
    <main className="mx-auto max-w-7xl p-5 lg:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-blue-600">Evidence-based review</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">Trainer Profile Reviews</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">Each score belongs to one trainer and one requirement. It is based on extracted document evidence—not a generic trainer rating.</p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Refresh
        </button>
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-[290px_minmax(0,1fr)]">
        <aside className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
          <p className="px-2 pb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Requirements</p>
          <div className="max-h-[65vh] space-y-1 overflow-auto">
            {requirements.map(requirement => {
              const id = requirement.requirement_id || requirement.id
              const count = reviews.filter(item => (item.requirement.requirement_id || item.requirement.id) === id).length
              return <button key={id} type="button" onClick={() => setSelectedId(id)} className={`w-full rounded-lg px-3 py-3 text-left transition ${selectedId === id ? 'bg-blue-50 ring-1 ring-blue-200' : 'hover:bg-slate-50'}`}>
                <p className="truncate text-sm font-semibold text-slate-800">{clean(requirement.technology_needed || requirement.domain || 'Training')}</p>
                <p className="mt-1 text-xs text-slate-500">{id} · {count} review{count === 1 ? '' : 's'}</p>
              </button>
            })}
          </div>
        </aside>

        <section>
          {loading ? <div className="flex min-h-60 items-center justify-center text-slate-500"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading reviews…</div> : visible.length === 0 ? <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center"><FileSearch className="mx-auto h-8 w-8 text-slate-400" /><p className="mt-3 font-semibold text-slate-700">No document review saved yet</p><p className="mt-1 text-sm text-slate-500">A review appears when a shortlisted trainer replies with a profile or document.</p></div> : <>
            {selectedRequirement && <div className="mb-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><RequirementLabel item={selectedRequirement} /></div>}
            <div className="space-y-4">
              {visible.map(({ trainer, fit }) => {
                const skills = fit.skills || {}
                const seniority = fit.seniority || {}
                const projects = fit.projects || {}
                const readability = fit.readability || {}
                const contextReview = fit.context_review || {}
                const inventory = trainer.document_review?.document_inventory || []
                return <article key={trainer.trainer_id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><UserRoundCheck className="h-5 w-5 text-blue-600" /><h2 className="font-bold text-slate-900">{clean(trainer.name || trainer.trainer_name || 'Trainer')}</h2></div><p className="mt-1 text-xs text-slate-500">{clean(trainer.trainer_id)} · score based on supplied profile evidence</p></div><div className="text-right"><p className="text-2xl font-bold text-slate-900">{fit.score ?? '—'}<span className="text-sm text-slate-500">/100</span></p><Tone status={fit.status} /></div></div>
                  <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Skills</p><p className="mt-2 text-lg font-bold text-slate-900">{skills.coverage_percent ?? 0}%</p><p className="mt-1 text-xs text-slate-600">Matched: {(skills.matched || []).join(', ') || 'None'}</p></div>
                    <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Seniority</p><p className="mt-2 text-sm font-bold text-slate-900">{seniority.status?.replaceAll('_', ' ') || 'Not evidenced'}</p><p className="mt-1 text-xs text-slate-600">Required: {seniority.required_years ?? '—'} yrs · Evidenced: {seniority.evidenced_years ?? '—'} yrs</p></div>
                    <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Projects</p><p className="mt-2 text-sm font-bold text-slate-900">{projects.status?.replaceAll('_', ' ') || 'Not evidenced'}</p><p className="mt-1 text-xs text-slate-600">Relevant evidence: {projects.relevant_count ?? 0}</p></div>
                    <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Profile readability</p><p className="mt-2 text-sm font-bold text-slate-900">{readability.status?.replaceAll('_', ' ') || 'Not checked'}</p><p className="mt-1 text-xs text-slate-600">Extraction confidence: {readability.confidence ?? 0}%</p></div>
                  </div>
                  {(skills.missing || []).length > 0 && <p className="mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> Missing or not evidenced: {skills.missing.join(', ')}</p>}
                  <div className="mt-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Documents read</p><div className="mt-2 flex flex-wrap gap-2">{inventory.length ? inventory.map(file => <span key={`${file.filename}-${file.type}`} className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700"><CheckCircle2 className="h-3.5 w-3.5 text-green-600" /> {file.filename || 'Document'} · {file.type}</span>) : <span className="text-sm text-slate-500">No document inventory available.</span>}</div></div>
                  <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-slate-700"><p className="font-semibold text-blue-900">Context agent review <span className="font-normal">(advisory)</span></p><p className="mt-1">{contextReview.status === 'reviewed' ? `${contextReview.summary || 'Reviewed against the requirement context.'} Advisory score: ${contextReview.advisory_score ?? '—'}/100.` : 'Not run. The evidence-based score above remains available.'}</p></div>
                </article>
              })}
            </div>
          </>}
        </section>
      </div>
    </main>
  )
}
