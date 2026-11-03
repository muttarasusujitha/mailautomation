import { useEffect, useMemo, useState } from 'react'
import { ExternalLink, FileDown, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../utils/api'

export default function TrainerApplications() {
  const [items, setItems] = useState([])
  const [domain, setDomain] = useState('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [approving, setApproving] = useState('')
  const [reviewNotes, setReviewNotes] = useState({})
  const [reviewing, setReviewing] = useState('')
  const domains = useMemo(() => [...new Set(items.flatMap(item => item.domains || []))].sort((a, b) => a.localeCompare(b)), [items])

  useEffect(() => {
    let active = true
    setLoading(true)
    api.get('/trainers/portal/applications').then(({ data }) => { if (active) setItems(data.items || []) })
      .catch(error => toast.error(error.message)).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const filteredItems = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase()
    return items.filter(profile => {
      if (domain && !(profile.domains || []).some(value => value.toLocaleLowerCase() === domain.toLocaleLowerCase())) return false
      if (!needle) return true
      const text = [profile.profile_name, profile.email, profile.linkedin_url, ...(profile.domains || []), ...(profile.skills || []).flatMap(skill => [skill.name, ...(skill.subskills || [])])].join(' ').toLocaleLowerCase()
      return text.includes(needle)
    })
  }, [items, domain, search])

  const download = async profile => {
    try {
      const { data } = await api.get(`/trainers/portal/applications/${encodeURIComponent(profile.owner_user_id)}/resume`, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = profile.resume_filename || 'trainer-resume'; anchor.click()
      URL.revokeObjectURL(url)
    } catch (error) { toast.error(error.message) }
  }

  const approve = async profile => {
    setApproving(profile.owner_user_id)
    try {
      const { data } = await api.post(`/trainers/portal/applications/${encodeURIComponent(profile.owner_user_id)}/approve`)
      setItems(current => current.map(item => item.owner_user_id === profile.owner_user_id ? { ...item, status: data.status } : item))
      toast.success('Trainer profile approved and added to matching.')
    } catch (error) { toast.error(error.message) }
    finally { setApproving('') }
  }

  const updateStatus = async (profile, status) => {
    const note = reviewNotes[profile.owner_user_id] || ''
    if (status === 'needs_information' && !note.trim()) {
      toast.error('Add a note describing the information needed.')
      return
    }
    setReviewing(profile.owner_user_id)
    try {
      const { data } = await api.patch(`/trainers/portal/applications/${encodeURIComponent(profile.owner_user_id)}/status`, { status, note })
      setItems(current => current.map(item => item.owner_user_id === profile.owner_user_id ? { ...item, status: data.status, review_note: data.review_note } : item))
      toast.success(status === 'rejected' ? 'Application marked not approved.' : 'Information request sent to trainer.')
    } catch (error) { toast.error(error.message) }
    finally { setReviewing('') }
  }

  const groups = useMemo(() => {
    const result = new Map()
    for (const profile of filteredItems) for (const name of profile.domains?.length ? profile.domains : ['Other']) {
      if (!result.has(name)) result.set(name, [])
      result.get(name).push(profile)
    }
    return [...result.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [filteredItems])

  return <div className="space-y-6 p-6 lg:p-8">
    <div><p className="text-sm font-semibold uppercase tracking-wide text-blue-700">Trainer directory</p><h1 className="mt-1 text-2xl font-bold text-slate-900">Trainer applications</h1><p className="mt-1 text-sm text-slate-600">Profiles, LinkedIn pages and resumes submitted by trainers.</p></div>
    <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 sm:flex-row">
      <label className="relative flex-1"><Search size={17} className="absolute left-3 top-3 text-slate-400" /><input aria-label="Search trainer profiles" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search name, domain or email" className="w-full rounded-xl border border-slate-300 py-2.5 pl-10 pr-3" /></label>
      <select value={domain} onChange={e => setDomain(e.target.value)} aria-label="Filter by domain" className="rounded-xl border border-slate-300 px-3 py-2.5"><option value="">All domains</option>{domains.map(value => <option key={value}>{value}</option>)}</select>
    </div>
    {loading ? <p className="rounded-2xl bg-white p-6 text-slate-500">Loading trainer profiles…</p> : groups.length === 0 ? <p className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-500">No trainer profiles found.</p> : groups.map(([name, profiles]) => <section key={name} className="space-y-3"><h2 className="text-lg font-bold text-slate-800">{name} <span className="text-sm font-medium text-slate-500">({profiles.length})</span></h2><div className="grid gap-4 xl:grid-cols-2">{profiles.map(profile => <article key={`${profile.owner_user_id}:${name}`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-lg font-semibold">{profile.profile_name}</h3><p className="text-sm text-slate-500">{profile.email} · {profile.experience_years} years experience</p></div><span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold capitalize text-amber-800">{String(profile.status || 'pending review').replaceAll('_', ' ')}</span></div>
      {profile.skills?.length > 0 && <div className="mt-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Skills and subskills</p><div className="mt-2 flex flex-wrap gap-2">{profile.skills.map(skill => <span key={skill.name} className="rounded-lg bg-slate-100 px-2.5 py-1.5 text-sm"><strong>{skill.name}</strong>{skill.subskills?.length ? ` · ${skill.subskills.join(', ')}` : ''}</span>)}</div></div>}
      {profile.certifications?.length > 0 && <p className="mt-3 text-sm"><span className="font-semibold">Certifications:</span> {profile.certifications.join(', ')}</p>}
      <div className="mt-3 grid gap-2 text-sm text-slate-600 sm:grid-cols-2">{profile.availability && <p><strong>Availability:</strong> {profile.availability}</p>}{profile.timezone && <p><strong>Timezone:</strong> {profile.timezone}</p>}{profile.preferred_delivery_modes?.length > 0 && <p><strong>Delivery:</strong> {profile.preferred_delivery_modes.join(', ')}</p>}{profile.expected_day_rate != null && <p><strong>Expected day rate:</strong> INR {Number(profile.expected_day_rate).toLocaleString()}</p>}</div>
      {profile.summary && <p className="mt-3 text-sm text-slate-600">{profile.summary}</p>}
      {profile.review_note && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><strong>Previous review note:</strong> {profile.review_note}</p>}
      {['pending_review', 'needs_information'].includes(profile.status) && <label className="mt-4 block text-xs font-semibold text-slate-600">Review note<textarea maxLength={1000} value={reviewNotes[profile.owner_user_id] ?? profile.review_note ?? ''} onChange={event => setReviewNotes(current => ({ ...current, [profile.owner_user_id]: event.target.value }))} placeholder="Tell the trainer what to update or why the application is not approved" rows={2} className="mt-1 w-full rounded-lg border border-slate-300 p-2.5 text-sm font-normal" /></label>}
      <div className="mt-4 flex flex-wrap gap-2">{profile.linkedin_url && <a href={profile.linkedin_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-lg border border-blue-200 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50">LinkedIn profile <ExternalLink size={15} /></a>}<button onClick={() => download(profile)} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"><FileDown size={15} /> Resume</button>{['pending_review', 'needs_information'].includes(profile.status) && <><button disabled={approving === profile.owner_user_id || reviewing === profile.owner_user_id} onClick={() => approve(profile)} className="rounded-lg bg-green-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">{approving === profile.owner_user_id ? 'Approving…' : 'Approve trainer'}</button><button disabled={reviewing === profile.owner_user_id} onClick={() => updateStatus(profile, 'needs_information')} className="rounded-lg border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-800 disabled:opacity-50">Needs information</button><button disabled={reviewing === profile.owner_user_id} onClick={() => updateStatus(profile, 'rejected')} className="rounded-lg border border-red-200 px-3 py-2 text-sm font-semibold text-red-700 disabled:opacity-50">Not approved</button></>}</div>
    </article>)}</div></section>)}
  </div>
}
