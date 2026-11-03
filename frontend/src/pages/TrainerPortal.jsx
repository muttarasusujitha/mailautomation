import { useEffect, useState } from 'react'
import { LogOut, Plus, Trash2, UploadCloud, UserRound, Linkedin, Award, BriefcaseBusiness, MapPin, CalendarDays, Sparkles, ArrowDown, ShieldCheck, ArrowUpRight } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../utils/api'
import BrandMark from '../components/BrandMark'

const split = value => value.split(',').map(item => item.trim()).filter(Boolean)
const emptySkill = () => ({ name: '', subskills: '' })

export default function TrainerPortal({ onLogout, user }) {
  const [form, setForm] = useState({ profile_name: '', experience_years: '', linkedin_url: '', domains: [''], skills: [emptySkill()], certifications: [''], summary: '' })
  const [resume, setResume] = useState(null)
  const [status, setStatus] = useState('incomplete')
  const [resumeName, setResumeName] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [opportunities, setOpportunities] = useState([])
  const [opportunitiesLoading, setOpportunitiesLoading] = useState(true)
  const [interestBusy, setInterestBusy] = useState('')
  const firstName = (form.profile_name || user?.name || 'Trainer').trim().split(/\s+/)[0]
  const profileProgress = [form.profile_name, form.experience_years !== '', form.domains.some(value => value.trim()), form.skills.some(value => value.name.trim()), Boolean(resumeName || resume)].filter(Boolean).length
  const update = (key, value) => setForm(current => ({ ...current, [key]: value }))

  useEffect(() => {
    api.get('/trainers/portal/profile').then(({ data }) => {
      const p = data.profile || {}
      setForm({
        profile_name: p.profile_name || '', experience_years: p.experience_years ?? '', linkedin_url: p.linkedin_url || '',
        domains: p.domains?.length ? p.domains : [''],
        skills: p.skills?.length ? p.skills.map(item => ({ name: item.name || '', subskills: (item.subskills || []).join(', ') })) : [emptySkill()],
        certifications: p.certifications?.length ? p.certifications : [''], summary: p.summary || '',
      })
      setStatus(p.status || 'incomplete')
      setResumeName(p.resume_filename || '')
    }).catch(error => toast.error(error.message)).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    api.get('/trainers/portal/opportunities').then(({ data }) => setOpportunities(data.items || []))
      .catch(error => toast.error(error.message)).finally(() => setOpportunitiesLoading(false))
  }, [])

  const expressInterest = async opportunity => {
    setInterestBusy(opportunity.opportunity_id)
    try {
      await api.post(`/trainers/portal/opportunities/${encodeURIComponent(opportunity.opportunity_id)}/interest`)
      setOpportunities(items => items.map(item => item.opportunity_id === opportunity.opportunity_id ? { ...item, interest_submitted: true } : item))
      toast.success('Your interest has been shared with the TrainerSync team.')
    } catch (error) { toast.error(error.message) }
    finally { setInterestBusy('') }
  }

  const submit = async event => {
    event.preventDefault()
    const body = new FormData()
    body.append('profile_name', form.profile_name)
    body.append('experience_years', form.experience_years)
    body.append('linkedin_url', form.linkedin_url)
    body.append('domains_json', JSON.stringify(split(form.domains.join(','))))
    body.append('skills_json', JSON.stringify(form.skills.filter(item => item.name.trim()).map(item => ({ name: item.name.trim(), subskills: split(item.subskills) }))))
    body.append('certifications_json', JSON.stringify(split(form.certifications.join(','))))
    body.append('summary', form.summary)
    if (resume) body.append('file', resume)
    setSaving(true)
    try {
      const { data } = await api.post('/trainers/portal/profile', body)
      setStatus(data.profile.status)
      setResumeName(data.profile.resume_filename)
      setResume(null)
      toast.success('Profile saved. TrainerSync will review it shortly.')
    } catch (error) { toast.error(error.message) }
    finally { setSaving(false) }
  }

  return <main className="min-h-screen bg-[#f4f6fb] text-slate-900" style={{ backgroundImage: 'radial-gradient(ellipse at 8% 0%, rgba(191,219,254,.42), transparent 34%), radial-gradient(ellipse at 94% 28%, rgba(221,214,254,.34), transparent 28%)' }}>
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-white/70 bg-white/85 px-5 py-4 shadow-sm backdrop-blur-xl sm:px-10">
      <BrandMark size="md" />
      <div className="flex items-center gap-3"><span className="hidden text-sm text-slate-500 sm:inline">Trainer workspace</span><button onClick={onLogout} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"><LogOut size={16} /> Sign out</button></div>
    </header>
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-8 sm:py-9">
      <section className="relative isolate mb-8 overflow-hidden rounded-[28px] bg-[#101a38] px-6 py-8 text-white shadow-[0_28px_80px_-34px_rgba(24,39,82,.65)] sm:px-10 sm:py-10">
        <div className="pointer-events-none absolute -right-12 -top-32 -z-10 h-80 w-80 rounded-full bg-blue-500/30 blur-3xl" />
        <div className="pointer-events-none absolute bottom-[-140px] right-[28%] -z-10 h-72 w-72 rounded-full bg-violet-500/20 blur-3xl" />
        <div className="grid items-end gap-8 lg:grid-cols-[1.3fr_.7fr]">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[.08] px-3 py-1.5 text-xs font-semibold uppercase tracking-[.16em] text-blue-100"><Sparkles size={14} /> Your TrainerSync space</span>
            <h1 className="mt-5 max-w-2xl text-3xl font-bold leading-tight tracking-[-.035em] text-white sm:text-5xl">Welcome{firstName !== 'Trainer' ? `, ${firstName}` : ''}.<br className="hidden sm:block" /> Your next opportunity starts here.</h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-blue-100/80 sm:text-base">Show the world what you teach best. Build your trainer profile, then explore verified training opportunities from our partner network.</p>
            <div className="mt-7 flex flex-wrap items-center gap-3"><a href="#trainer-profile" className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-bold text-[#16254c] shadow-lg shadow-black/10 transition hover:-translate-y-0.5 hover:bg-blue-50">Build your profile <ArrowDown size={16} /></a><a href="#trainer-opportunities" className="inline-flex items-center gap-2 rounded-xl border border-white/20 bg-white/[.07] px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/[.13]">Explore opportunities <ArrowUpRight size={16} /></a></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-white/10 bg-white/[.08] p-4 backdrop-blur-sm"><p className="text-xs font-medium uppercase tracking-wider text-blue-100/65">Matching openings</p><p className="mt-2 text-3xl font-bold text-white">{opportunitiesLoading ? '—' : opportunities.length}</p><p className="mt-1 text-xs text-blue-100/65">in your areas of expertise</p></div>
            <div className="rounded-2xl border border-white/10 bg-white/[.08] p-4 backdrop-blur-sm"><p className="text-xs font-medium uppercase tracking-wider text-blue-100/65">Profile status</p><p className="mt-2 text-lg font-bold text-white">{status === 'approved' ? 'Approved' : status === 'pending_review' ? 'In review' : 'Getting started'}</p><p className="mt-1 text-xs text-blue-100/65">{status === 'approved' ? 'You are in the trainer network' : 'Complete your profile to be considered'}</p></div>
            <div className="col-span-2 rounded-2xl border border-white/10 bg-white/[.08] p-4 backdrop-blur-sm"><div className="flex items-center justify-between gap-3"><p className="text-xs font-medium uppercase tracking-wider text-blue-100/65">Profile checklist</p><span className="text-xs font-semibold text-white">{profileProgress} of 5 ready</span></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/15"><div className="h-full rounded-full bg-gradient-to-r from-cyan-300 to-blue-400 transition-all duration-500" style={{ width: `${profileProgress * 20}%` }} /></div></div>
          </div>
        </div>
      </section>
      {status === 'pending_review' && <div className="mb-6 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950 shadow-sm"><ShieldCheck size={19} className="mt-0.5 shrink-0 text-amber-700" /><p><strong>Your profile is with our review team.</strong> You can make updates any time; we’ll review your latest details.</p></div>}
      {loading ? <div id="trainer-profile" className="rounded-3xl border border-white bg-white/90 p-8 text-slate-500 shadow-xl shadow-slate-300/30">Loading your profile…</div> : <form id="trainer-profile" onSubmit={submit} className="space-y-7 rounded-[28px] border border-white bg-white/95 p-5 shadow-[0_20px_60px_-38px_rgba(27,42,77,.35)] sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-5"><div><p className="text-xs font-bold uppercase tracking-[.15em] text-blue-700">Step 1 · Your profile</p><h2 className="mt-1 text-2xl font-bold tracking-tight">Make your expertise stand out</h2><p className="mt-1 text-sm text-slate-500">A complete profile helps us match you to the right training assignments.</p></div><span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1.5 text-xs font-bold text-blue-800"><ShieldCheck size={14} /> Private to TrainerSync</span></div>
        <section className="grid gap-5 rounded-2xl bg-slate-50/80 p-4 sm:grid-cols-2 sm:p-5">
          <label className="block text-sm font-semibold">Profile name<input required maxLength="120" value={form.profile_name} onChange={e => update('profile_name', e.target.value)} placeholder="Your professional name" className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
          <label className="block text-sm font-semibold">Years of experience<input required type="number" min="0" max="70" step="0.5" value={form.experience_years} onChange={e => update('experience_years', e.target.value)} placeholder="e.g. 8" className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
        </section>
        <section className="rounded-2xl border border-slate-100 p-4 sm:p-5">
          <h2 className="mb-3 flex items-center gap-2 font-semibold"><BriefcaseBusiness size={18} className="text-blue-700" /> Training domains</h2>
          <div className="space-y-2">{form.domains.map((value, index) => <div key={index} className="flex gap-2"><input required value={value} onChange={e => update('domains', form.domains.map((item, i) => i === index ? e.target.value : item))} placeholder="e.g. Cloud computing" className="w-full rounded-xl border border-slate-300 p-3" />{form.domains.length > 1 && <button type="button" aria-label="Remove domain" onClick={() => update('domains', form.domains.filter((_, i) => i !== index))} className="rounded-lg px-3 text-slate-500 hover:bg-slate-100"><Trash2 size={17} /></button>}</div>)}</div>
          <button type="button" onClick={() => update('domains', [...form.domains, ''])} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-blue-700"><Plus size={16} /> Add domain</button>
        </section>
        <section className="rounded-2xl border border-slate-100 p-4 sm:p-5">
          <h2 className="mb-3 flex items-center gap-2 font-semibold"><UserRound size={18} className="text-blue-700" /> Skills and subskills</h2>
          <div className="space-y-3">{form.skills.map((skill, index) => <div key={index} className="grid gap-2 rounded-xl bg-slate-50 p-3 sm:grid-cols-[1fr_1.5fr_auto]"><input required value={skill.name} onChange={e => update('skills', form.skills.map((item, i) => i === index ? { ...item, name: e.target.value } : item))} placeholder="Skill (e.g. AWS)" className="rounded-lg border border-slate-300 bg-white p-3" /><input value={skill.subskills} onChange={e => update('skills', form.skills.map((item, i) => i === index ? { ...item, subskills: e.target.value } : item))} placeholder="Subskills, separated by commas" className="rounded-lg border border-slate-300 bg-white p-3" />{form.skills.length > 1 && <button type="button" aria-label="Remove skill" onClick={() => update('skills', form.skills.filter((_, i) => i !== index))} className="px-2 text-slate-500"><Trash2 size={17} /></button>}</div>)}</div>
          <button type="button" onClick={() => update('skills', [...form.skills, emptySkill()])} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-blue-700"><Plus size={16} /> Add skill</button>
        </section>
        <section className="rounded-2xl border border-slate-100 p-4 sm:p-5">
          <h2 className="mb-3 flex items-center gap-2 font-semibold"><Award size={18} className="text-blue-700" /> Certifications <span className="font-normal text-slate-500">(optional)</span></h2>
          <div className="space-y-2">{form.certifications.map((value, index) => <div key={index} className="flex gap-2"><input value={value} onChange={e => update('certifications', form.certifications.map((item, i) => i === index ? e.target.value : item))} placeholder="Certification name" className="w-full rounded-xl border border-slate-300 p-3" />{form.certifications.length > 1 && <button type="button" aria-label="Remove certification" onClick={() => update('certifications', form.certifications.filter((_, i) => i !== index))} className="px-2 text-slate-500"><Trash2 size={17} /></button>}</div>)}</div>
          <button type="button" onClick={() => update('certifications', [...form.certifications, ''])} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-blue-700"><Plus size={16} /> Add certification</button>
        </section>
        <label className="block rounded-2xl border border-slate-100 p-4 text-sm font-semibold sm:p-5"><span className="mb-2 flex items-center gap-2"><Linkedin size={18} className="text-blue-700" /> LinkedIn profile URL <span className="font-normal text-slate-500">(optional)</span></span><input type="url" value={form.linkedin_url} onChange={e => update('linkedin_url', e.target.value)} placeholder="https://www.linkedin.com/in/your-profile" className="w-full rounded-xl border border-slate-300 p-3 font-normal transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10" /></label>
        <label className="block rounded-2xl border border-slate-100 p-4 text-sm font-semibold sm:p-5">Professional summary <span className="font-normal text-slate-500">(optional)</span><textarea rows="3" maxLength="2000" value={form.summary} onChange={e => update('summary', e.target.value)} placeholder="Briefly describe your training experience" className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10" /></label>
        <label className="block rounded-2xl border border-dashed border-blue-200 bg-blue-50/40 p-4 text-sm font-semibold sm:p-5">Resume / profile document<input type="file" required={!resumeName} accept=".pdf,.doc,.docx" onChange={e => setResume(e.target.files?.[0] || null)} className="mt-2 block w-full rounded-xl border border-dashed border-slate-300 bg-white p-4 font-normal" /><span className="mt-1 inline-flex items-center gap-1 text-xs font-normal text-slate-500"><UploadCloud size={14} /> PDF or DOCX, up to 10 MB {resumeName && `• Current: ${resumeName}`}</span></label>
        <button disabled={saving} className="w-full rounded-xl bg-gradient-to-r from-blue-700 to-indigo-700 px-5 py-3.5 font-bold text-white shadow-lg shadow-blue-900/15 transition hover:-translate-y-0.5 hover:from-blue-800 hover:to-indigo-800 disabled:translate-y-0 disabled:opacity-60">{saving ? 'Saving profile…' : 'Save trainer profile'}</button>
      </form>}
      <section id="trainer-opportunities" className="mt-10 scroll-mt-24" aria-labelledby="opportunities-heading">
        <div className="mb-4">
          <p className="text-xs font-bold uppercase tracking-[.15em] text-blue-700">Step 2 · Your next move</p>
          <h2 id="opportunities-heading" className="mt-1 text-3xl font-bold tracking-tight">Training opportunities</h2>
          <p className="mt-1 text-sm text-slate-600">Openings shared by TrainerSync partner companies that match your profile.</p>
        </div>
        {opportunitiesLoading ? <p className="rounded-xl bg-white p-5 text-sm text-slate-500">Loading opportunities…</p> : opportunities.length === 0 ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">No matching active opportunities yet. Keep your domains and skills up to date; new partner openings will appear here.</div>
        ) : <div className="grid gap-4">{opportunities.map(item => <article key={item.opportunity_id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><p className="text-sm font-semibold text-blue-700">{item.company_name}</p><h3 className="mt-1 text-lg font-bold">{item.title}</h3><p className="mt-1 text-sm text-slate-600">{item.domain}{item.delivery_mode ? ` · ${item.delivery_mode}` : ''}</p></div>
            <button type="button" disabled={item.interest_submitted || interestBusy === item.opportunity_id} onClick={() => expressInterest(item)} className="rounded-xl bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300">{item.interest_submitted ? 'Interest sent' : interestBusy === item.opportunity_id ? 'Sending…' : "I'm interested"}</button>
          </div>
          {item.description && <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{item.description}</p>}
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500">
            {item.location && <span className="inline-flex items-center gap-1"><MapPin size={14} />{item.location}</span>}
            {item.start_date && <span className="inline-flex items-center gap-1"><CalendarDays size={14} />Starts {item.start_date}</span>}
            {item.duration && <span>{item.duration}</span>}
          </div>
          {item.required_skills?.length > 0 && <p className="mt-3 text-xs text-slate-600"><span className="font-semibold">Skills:</span> {item.required_skills.join(', ')}</p>}
        </article>)}</div>}
      </section>
    </div>
  </main>
}
