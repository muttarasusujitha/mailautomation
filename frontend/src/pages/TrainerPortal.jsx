import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LogOut, Plus, Trash2, UploadCloud, UserRound, Linkedin, Award, BriefcaseBusiness, MapPin, CalendarDays, ArrowDown, ShieldCheck, ArrowUpRight, Home, FileText } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../utils/api'
import BrandMark from '../components/BrandMark'

const split = value => value.split(',').map(item => item.trim()).filter(Boolean)
const emptySkill = () => ({ name: '', subskills: '' })
const TRAINER_APPLICATION_STAGES = ['Profile submitted', 'TrainerSync review', 'Approved for matching']
const loadRazorpay = () => new Promise((resolve, reject) => {
  if (window.Razorpay) return resolve(true)
  const script = document.createElement('script')
  script.src = 'https://checkout.razorpay.com/v1/checkout.js'
  script.onload = () => resolve(true)
  script.onerror = () => reject(new Error('Secure checkout could not be loaded.'))
  document.body.appendChild(script)
})

export default function TrainerPortal({ onLogout, user }) {
  const [form, setForm] = useState({ profile_name: '', experience_years: '', linkedin_url: '', domains: [''], skills: [emptySkill()], certifications: [''], summary: '', availability: '', timezone: '', preferred_delivery_modes: [], expected_day_rate: '' })
  const [resume, setResume] = useState(null)
  const [status, setStatus] = useState('incomplete')
  const [reviewNote, setReviewNote] = useState('')
  const [resumeName, setResumeName] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [opportunities, setOpportunities] = useState([])
  const [opportunitiesLoading, setOpportunitiesLoading] = useState(true)
  const [interestBusy, setInterestBusy] = useState('')
  const [membership, setMembership] = useState(null)
  const [membershipLoading, setMembershipLoading] = useState(true)
  const [membershipBusy, setMembershipBusy] = useState(false)
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
        availability: p.availability || '', timezone: p.timezone || '',
        preferred_delivery_modes: p.preferred_delivery_modes || [], expected_day_rate: p.expected_day_rate ?? '',
      })
      setStatus(p.status || 'incomplete')
      setReviewNote(p.review_note || '')
      setResumeName(p.resume_filename || '')
    }).catch(error => toast.error(error.message)).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    api.get('/trainer-membership/status').then(({ data }) => setMembership(data))
      .catch(error => toast.error(error.message)).finally(() => setMembershipLoading(false))
  }, [])

  useEffect(() => {
    if (membershipLoading) return
    if (!membership?.active) { setOpportunities([]); setOpportunitiesLoading(false); return }
    setOpportunitiesLoading(true)
    api.get('/trainers/portal/opportunities').then(({ data }) => setOpportunities(data.items || []))
      .catch(error => toast.error(error.message)).finally(() => setOpportunitiesLoading(false))
  }, [membership, membershipLoading])

  const subscribe = async () => {
    setMembershipBusy(true)
    try {
      await loadRazorpay()
      const { data: order } = await api.post('/trainer-membership/order')
      const checkout = new window.Razorpay({
        key: order.key_id, amount: order.amount, currency: order.currency,
        name: 'TrainerSync', description: 'One-time Trainer Priority membership',
        order_id: order.order_id, prefill: { name: order.name, email: order.email },
        theme: { color: '#2563eb' },
        handler: async payment => {
          try {
            const { data } = await api.post('/trainer-membership/verify', {
              razorpay_order_id: payment.razorpay_order_id,
              razorpay_payment_id: payment.razorpay_payment_id,
              razorpay_signature: payment.razorpay_signature,
            })
            setMembership(current => ({ ...current, ...data, active: true, priority: true }))
            toast.success('Trainer Priority membership is active.')
          } catch (error) { toast.error(error.message) }
          finally { setMembershipBusy(false) }
        },
        modal: { ondismiss: () => setMembershipBusy(false) },
      })
      checkout.on('payment.failed', () => { setMembershipBusy(false); toast.error('Payment did not complete. You have not been charged.') })
      checkout.open()
    } catch (error) { setMembershipBusy(false); toast.error(error.message) }
  }

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
    body.append('availability', form.availability)
    body.append('timezone', form.timezone)
    body.append('preferred_delivery_modes_json', JSON.stringify(form.preferred_delivery_modes))
    body.append('expected_day_rate', form.expected_day_rate)
    if (resume) body.append('file', resume)
    setSaving(true)
    try {
      const { data } = await api.post('/trainers/portal/profile', body)
      setStatus(data.profile.status)
      setReviewNote(data.profile.review_note || '')
      setResumeName(data.profile.resume_filename)
      setResume(null)
      toast.success('Profile saved. TrainerSync will review it shortly.')
    } catch (error) { toast.error(error.message) }
    finally { setSaving(false) }
  }

  return <main className="min-h-screen bg-[#F7F8FA] text-slate-900 lg:pl-64">
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-slate-200 bg-white px-5 py-6 lg:flex">
      <BrandMark size="md" />
      <p className="mt-8 px-3 text-[11px] font-bold uppercase tracking-[.16em] text-slate-400">Trainer workspace</p>
      <nav aria-label="Trainer portal sidebar" className="mt-3 space-y-1">
        <a href="#portal-home" className="flex items-center gap-3 rounded-xl bg-blue-50 px-3 py-2.5 text-sm font-semibold text-blue-700"><Home size={17} /> Home</a>
        <a href="#trainer-profile" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 hover:text-blue-700"><FileText size={17} /> My profile</a>
        <a href="#trainer-opportunities" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 hover:text-blue-700"><BriefcaseBusiness size={17} /> Opportunities</a>
      </nav>
      <div className="mt-auto"><button onClick={onLogout} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50"><LogOut size={17} /> Sign out</button></div>
    </aside>
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-[#E5E8EE] bg-white/95 px-5 py-4 shadow-sm backdrop-blur-xl sm:px-10">
      <BrandMark size="md" />
      <div className="flex items-center gap-2 sm:gap-4"><nav aria-label="Trainer navigation" className="flex items-center gap-1 rounded-xl bg-slate-100 p-1 text-sm font-semibold"><Link to="/home" className="rounded-lg px-3 py-2 text-slate-600 hover:bg-white hover:text-blue-700">Home</Link><Link to="/trainer-portal" aria-current="page" className="rounded-lg bg-white px-3 py-2 text-blue-700 shadow-sm">My portal</Link></nav><button onClick={onLogout} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"><LogOut size={16} /> <span className="hidden sm:inline">Sign out</span></button></div>
    </header>
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-8 sm:py-9">
      <section id="portal-home" className="mb-8 scroll-mt-24 grid overflow-hidden rounded-[28px] border border-[#E5E8EE] bg-white shadow-[0_22px_60px_-40px_rgba(15,23,42,.35)] lg:grid-cols-[1.05fr_.95fr]">
        <div className="relative min-h-[330px] overflow-hidden bg-gradient-to-br from-[#F8FBFF] via-[#EAF3FF] to-white sm:min-h-[440px]">
          <img src="/images/office-girl.png" alt="Professional trainer using a laptop" className="absolute inset-0 h-full w-full object-contain object-center" />
          <div className="absolute inset-0 bg-gradient-to-r from-white/55 via-white/5 to-blue-50/50" />
          <div className="absolute bottom-5 left-5 right-5 grid gap-2 sm:bottom-7 sm:left-7 sm:right-7">
            <div className="flex w-[88%] items-center gap-3 rounded-2xl border border-white/70 bg-white/90 p-3 shadow-lg backdrop-blur sm:p-3.5"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-sm font-bold text-blue-700">{(firstName[0] || 'T').toUpperCase()}</span><span className="min-w-0 flex-1"><span className="block text-xs font-extrabold text-slate-900">Trainer profile</span><span className="mt-0.5 block truncate text-[11px] font-semibold text-slate-600">{form.profile_name || firstName}</span></span><span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-bold text-blue-700">{profileProgress}/5</span></div>
            <div className="ml-auto flex w-[82%] items-center gap-3 rounded-2xl border border-white/70 bg-white/90 p-3 shadow-lg backdrop-blur sm:p-3.5"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-xs font-bold text-emerald-700">CV</span><span className="min-w-0 flex-1"><span className="block text-xs font-extrabold text-slate-900">Resume and expertise</span><span className="mt-0.5 block truncate text-[11px] font-semibold text-slate-600">{resumeName || (resume ? resume.name : 'Add your CV to complete your profile')}</span></span><span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${resumeName || resume ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{resumeName || resume ? 'Ready' : 'Add CV'}</span></div>
          </div>
        </div>
        <div className="flex flex-col justify-center p-6 sm:p-9 lg:p-10">
          <p className="text-xs font-bold uppercase tracking-[.18em] text-blue-700">Your trainer workspace</p>
          <h1 className="mt-3 max-w-2xl text-3xl font-bold leading-tight tracking-[-.035em] text-slate-950 sm:text-4xl">Welcome{firstName !== 'Trainer' ? `, ${firstName}` : ''}.<br />Your next opportunity starts here.</h1>
          <p className="mt-4 max-w-xl text-sm leading-6 text-slate-600 sm:text-base">Share your experience, CV, and LinkedIn profile. TrainerSync reviews your profile and contacts you when a relevant opportunity comes up.</p>
          <div className="mt-6 flex flex-wrap items-center gap-3"><a href="#trainer-profile" className="inline-flex items-center gap-2 rounded-xl bg-blue-700 px-4 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-blue-800">Complete your profile <ArrowDown size={16} /></a>{membership?.active && <a href="#trainer-opportunities" className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50">Explore opportunities <ArrowUpRight size={16} /></a>}</div>
          <div className="mt-7 grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Profile status</p><p className="mt-1.5 font-bold text-slate-900">{status === 'approved' ? 'Approved' : status === 'needs_information' ? 'Needs information' : status === 'rejected' ? 'Not approved' : status === 'pending_review' ? 'In review' : 'Getting started'}</p></div>
            <div className="rounded-2xl bg-slate-50 p-4"><div className="flex items-center justify-between gap-3"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Profile checklist</p><span className="text-xs font-bold text-blue-700">{profileProgress}/5</span></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-blue-700 transition-all" style={{ width: `${profileProgress * 20}%` }} /></div></div>
            {membership?.active && <div className="rounded-2xl bg-blue-50 p-4 sm:col-span-2"><p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Matching openings</p><p className="mt-1.5 font-bold text-slate-900">{opportunitiesLoading ? 'Loading opportunities...' : `${opportunities.length} opportunities in your areas`}</p></div>}
          </div>
        </div>
      </section>
      {status !== 'incomplete' && <section aria-label="Trainer application tracking" className="mb-6 rounded-2xl border border-blue-100 bg-white p-5 shadow-sm sm:p-6">
        <div role="status" className="flex items-start gap-3 rounded-xl border border-green-200 bg-green-50 p-4 text-sm text-green-950">
          <ShieldCheck size={19} className="mt-0.5 shrink-0 text-green-700" />
              <div><p className="font-semibold">{status === 'approved' ? 'Your trainer application is approved.' : status === 'needs_information' ? 'TrainerSync needs more information.' : status === 'rejected' ? 'Your application was not approved.' : 'Thank you — your profile and CV have been submitted.'}</p><p className="mt-1">{status === 'approved' ? 'Your approved profile is in the trainer network.' : status === 'needs_information' ? 'Please update your profile using the team note below, then save it again.' : status === 'rejected' ? 'Your application status and the review note are shown below.' : 'Your details are saved for review. You can update your profile while the team reviews it.'}</p>{reviewNote && <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950"><strong>TrainerSync team note:</strong> {reviewNote}</p>}</div>
        </div>
        <ol className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Application stages">
          {TRAINER_APPLICATION_STAGES.map((label, index) => {
            const activeIndex = status === 'approved' ? 2 : 1
            const complete = index < activeIndex
            const current = index === activeIndex
            return <li key={label} className={`flex items-center gap-3 rounded-xl border p-3 text-sm ${current ? 'border-blue-300 bg-blue-50 text-blue-900' : complete ? 'border-green-200 bg-green-50 text-green-900' : 'border-slate-200 bg-slate-50 text-slate-500'}`}>
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${complete ? 'bg-green-600 text-white' : current ? 'bg-blue-700 text-white' : 'bg-slate-200 text-slate-600'}`}>{complete ? '✓' : index + 1}</span>
              <span className={current ? 'font-semibold' : ''}>{label}</span>
            </li>
          })}
        </ol>
      </section>}
      <section className="mb-7 rounded-2xl border border-blue-100 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="trainer-plan-title">
        {membershipLoading ? <p className="text-sm text-slate-500">Checking trainer membership…</p> : membership?.active ? <div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-wide text-blue-700">Trainer Priority</p><h2 id="trainer-plan-title" className="mt-1 text-xl font-bold">Membership active</h2><p className="mt-1 max-w-2xl text-sm text-slate-600">Your profile is prioritized among suitable matches for partner companies and for the team’s review. Client selection still depends on the requirement.</p></div><span className="rounded-full bg-green-50 px-3 py-1.5 text-sm font-semibold text-green-700">₹99 paid once</span></div> : <div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-wide text-blue-700">Free trainer account</p><h2 id="trainer-plan-title" className="mt-1 text-xl font-bold">Upload your CV and LinkedIn profile</h2><p className="mt-1 max-w-2xl text-sm text-slate-600">Your profile is saved for TrainerSync review. A one-time ₹99 membership adds priority in suitable client matches and opens partner opportunities.</p></div><button type="button" disabled={membershipBusy || !membership?.checkout_enabled} onClick={subscribe} className="rounded-xl bg-blue-700 px-5 py-3 text-sm font-bold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50">{membershipBusy ? 'Opening secure checkout…' : membership?.checkout_enabled ? 'Get priority · ₹99 once' : 'Checkout unavailable'}</button></div>}
      </section>
      {loading ? <div id="trainer-profile" className="rounded-3xl border border-white bg-white/90 p-8 text-slate-500 shadow-xl shadow-slate-300/30">Loading your profileâ€¦</div> : <form id="trainer-profile" onSubmit={submit} className="space-y-7 rounded-[28px] border border-white bg-white/95 p-5 shadow-[0_20px_60px_-38px_rgba(27,42,77,.35)] sm:p-8">
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
        <section className="grid gap-4 rounded-2xl border border-slate-100 p-4 sm:grid-cols-2 sm:p-5">
          <label className="text-sm font-semibold">Availability <span className="font-normal text-slate-500">(optional)</span><input maxLength="500" value={form.availability} onChange={e => update('availability', e.target.value)} placeholder="e.g. Weekdays after 6 PM; available from January" className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
          <label className="text-sm font-semibold">Timezone<input maxLength="80" value={form.timezone} onChange={e => update('timezone', e.target.value)} placeholder="e.g. Asia/Kolkata" className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
          <label className="text-sm font-semibold">Preferred delivery modes<input value={form.preferred_delivery_modes.join(', ')} onChange={e => update('preferred_delivery_modes', split(e.target.value))} placeholder="Online, on-site, hybrid" className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
          <label className="text-sm font-semibold">Expected day rate (INR)<input type="number" min="0" max="10000000" step="100" value={form.expected_day_rate} onChange={e => update('expected_day_rate', e.target.value)} placeholder="Optional" className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
        </section>
        <label className="block rounded-2xl border border-dashed border-blue-200 bg-blue-50/40 p-4 text-sm font-semibold sm:p-5">Resume / profile document<input type="file" required={!resumeName} accept=".pdf,.doc,.docx" onChange={e => setResume(e.target.files?.[0] || null)} className="mt-2 block w-full rounded-xl border border-dashed border-slate-300 bg-white p-4 font-normal" /><span className="mt-1 inline-flex items-center gap-1 text-xs font-normal text-slate-500"><UploadCloud size={14} /> PDF or DOCX, up to 10 MB {resumeName && `• Current: ${resumeName}`}</span></label>
        <button disabled={saving} className="w-full rounded-xl bg-gradient-to-r from-blue-700 to-indigo-700 px-5 py-3.5 font-bold text-white shadow-lg shadow-blue-900/15 transition hover:-translate-y-0.5 hover:from-blue-800 hover:to-indigo-800 disabled:translate-y-0 disabled:opacity-60">{saving ? 'Saving profile…' : 'Save trainer profile'}</button>
      </form>}
      {membership?.active && <section id="trainer-opportunities" className="mt-10 scroll-mt-24" aria-labelledby="opportunities-heading">
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
      </section>}
    </div>
  </main>
}
