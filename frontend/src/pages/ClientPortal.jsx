import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarDays, CheckCircle2, LogOut, Mail, Sparkles, ArrowDown, ArrowUpRight, Building2 } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../utils/api'
import BrandMark from '../components/BrandMark'

const RAZORPAY_CHECKOUT_URL = 'https://checkout.razorpay.com/v1/checkout.js'
const SAMPLE_REQUEST = `Dear TrainerSync,\n\nWe have a confirmed requirement for a 20-day offline DevOps training batch starting from 20 September 2026.\n\nTraining Details:\n- Domain: DevOps\n- Duration: 20 Days\n- Start Date: 20 September 2026\n- Mode: Offline\n- Commercial: ₹8,80,000\n- Training: Conceptual sessions along with extensive hands-on activities\n- Hands-on Lab: 3 hours per day\n\nPlease share the following at the earliest:\n1. Trainer Profile / Updated CV\n2. Detailed Day-wise ToC (Table of Contents)\n3. 10-day lab cost separately for 3 hours of hands-on lab per day\n\nRegards,\n[Your name]`

function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = RAZORPAY_CHECKOUT_URL
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Payment checkout could not load'))
    document.body.appendChild(script)
  })
}

const emptyParsed = () => ({ domain: '', required_skills: [], duration_days: '', timeline_start: '', timeline_end: '', delivery_mode: '', commercial_amount: '', lab_hours_per_day: '', training_approach: '', business_context: '', requested_deliverables: [], min_experience_years: 0, participant_count: '', timing: '', location: '' })
const REQUEST_STAGES = ['Received', 'Matching', 'Team review', 'Client review', 'Confirmed', 'Closed']

function RequestProgress({ request }) {
  const stageIndexes = { received: 0, matching: 1, team_review: 2, client_review: 3, confirmed: 4, closed: 5 }
  const currentIndex = stageIndexes[request.tracking_stage] ?? 0
  return <ol aria-label="Request progress" className="mt-4 grid grid-cols-3 gap-2">
    {REQUEST_STAGES.map((label, index) => {
      const complete = index < currentIndex
      const current = index === currentIndex
      return <li key={label} className="min-w-0 text-center">
        <span className={`mx-auto flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${complete ? 'bg-green-600 text-white' : current ? 'bg-blue-700 text-white' : 'bg-slate-100 text-slate-500'}`}>
          {complete ? '✓' : index + 1}
        </span>
        <span className={`mt-1 block text-[10px] leading-4 sm:text-xs ${current ? 'font-semibold text-blue-800' : 'text-slate-500'}`}>{label}</span>
      </li>
    })}
  </ol>
}

export default function ClientPortal({ onLogout, user }) {
  const [profile, setProfile] = useState({ name: user?.name || '', email: user?.email || '', company: '', phone: '' })
  const [subscription, setSubscription] = useState({ active: false, expires_at: null, amount: 999, checkout_enabled: false })
  const [requests, setRequests] = useState([])
  const [requestText, setRequestText] = useState('')
  const [parsed, setParsed] = useState(null)
  const [requestId, setRequestId] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [profileSaving, setProfileSaving] = useState(false)
  const [emailCodeSent, setEmailCodeSent] = useState(false)
  const [emailCode, setEmailCode] = useState('')
  const [contactForm, setContactForm] = useState({ name: '', company: '', phone: '' })
  const welcomeName = profile.company || profile.name || 'Client'

  const refresh = async () => {
    const [account, plan, requestList] = await Promise.all([
      api.get('/client-portal/profile'), api.get('/client-portal/subscription'), api.get('/client-portal/requests'),
    ])
    setProfile(account.data.profile || { name: '', email: '', company: '', phone: '' })
    setContactForm({ name: account.data.profile?.name || '', company: account.data.profile?.company || '', phone: account.data.profile?.phone || '' })
    setSubscription(plan.data)
    setRequests(requestList.data.items || [])
  }

  useEffect(() => {
    refresh().catch(error => toast.error(error.message)).finally(() => setLoading(false))
  }, [])

  const saveContact = async event => {
    event.preventDefault()
    setProfileSaving(true)
    try {
      const { data } = await api.patch('/client-portal/profile', contactForm)
      setProfile(current => ({ ...current, ...data.profile }))
      toast.success('Company and contact details saved.')
    } catch (error) { toast.error(error.message) }
    finally { setProfileSaving(false) }
  }

  const sendEmailCode = async () => {
    try {
      await api.post('/client-portal/email-verification/send')
      setEmailCodeSent(true)
      toast.success('Verification code sent to your account email.')
    } catch (error) { toast.error(error.message) }
  }

  const verifyEmailCode = async event => {
    event.preventDefault()
    try {
      await api.post('/client-portal/email-verification/verify', { code: emailCode })
      setProfile(current => ({ ...current, email_verified: true }))
      setEmailCode('')
      toast.success('Email verified. You can now submit client requests.')
    } catch (error) { toast.error(error.message) }
  }

  const parseRequest = async () => {
    if (requestText.trim().length < 20) {
      toast.error('Paste or type the client training request first.')
      return
    }
    setBusy(true)
    try {
      const { data } = await api.post('/client-portal/parse-request', { text: requestText })
      setParsed({ ...emptyParsed(), ...data.parsed, duration_days: data.parsed.duration_days || '',
        commercial_amount: data.parsed.commercial_amount ?? '', lab_hours_per_day: data.parsed.lab_hours_per_day ?? '',
        participant_count: data.parsed.participant_count ?? '' })
      toast.success(data.missing_fields?.length ? `Request read. Please fill in: ${data.missing_fields.join(', ')}.` : 'Request read. Review the extracted details below.')
    } catch (error) { toast.error(error.message) }
    finally { setBusy(false) }
  }

  const setField = (key, value) => setParsed(current => ({ ...current, [key]: value }))

  const subscribe = async () => {
    if (!subscription.checkout_enabled) return
    setBusy(true)
    try {
      await loadRazorpay()
      const { data: order } = await api.post('/client-portal/subscription/order')
      const checkout = new window.Razorpay({
        key: order.key_id, amount: order.amount, currency: order.currency, order_id: order.order_id,
        name: 'TrainerSync', description: 'One-year client plan · unlimited trainer requests',
        prefill: { name: order.name || profile.name, email: order.email || profile.email },
        theme: { color: '#1d4ed8' },
        handler: async payment => {
          try {
            await api.post('/client-portal/subscription/verify', {
              razorpay_order_id: payment.razorpay_order_id,
              razorpay_payment_id: payment.razorpay_payment_id,
              razorpay_signature: payment.razorpay_signature,
            })
            await refresh()
            toast.success('Your one-year client plan is active. You can submit unlimited trainer requests.')
          } catch (error) { toast.error(error.message) }
          finally { setBusy(false) }
        },
        modal: { ondismiss: () => setBusy(false) },
      })
      checkout.on('payment.failed', failure => {
        setBusy(false)
        toast.error(failure.error?.description || 'Payment was not completed')
      })
      checkout.open()
    } catch (error) {
      setBusy(false)
      toast.error(error.message)
    }
  }

  const submitRequest = async () => {
    if (!parsed) return
    setBusy(true)
    try {
      const { data } = await api.post('/client-portal/requests', {
        request_text: requestText,
        ...parsed,
        required_skills: Array.isArray(parsed.required_skills) ? parsed.required_skills : String(parsed.required_skills || '').split(/[,;\n]/).map(value => value.trim()).filter(Boolean),
        requested_deliverables: Array.isArray(parsed.requested_deliverables) ? parsed.requested_deliverables : String(parsed.requested_deliverables || '').split(/[,;\n]/).map(value => value.trim()).filter(Boolean),
        duration_days: parsed.duration_days === '' ? null : Number(parsed.duration_days),
        commercial_amount: parsed.commercial_amount === '' ? null : Number(parsed.commercial_amount),
        lab_hours_per_day: parsed.lab_hours_per_day === '' ? null : Number(parsed.lab_hours_per_day),
        participant_count: parsed.participant_count === '' ? null : Number(parsed.participant_count),
        min_experience_years: Number(parsed.min_experience_years || 0),
      })
      setRequestId(data.requirement_id)
      setRequestText('')
      setParsed(null)
      await refresh()
      toast.success('Request submitted to the TrainerSync team. Trainer details are not shown in this portal.')
    } catch (error) { toast.error(error.message) }
    finally { setBusy(false) }
  }

  return <main className="min-h-screen bg-[#f4f6fb] text-slate-900" style={{ backgroundImage: 'radial-gradient(ellipse at 8% 0%, rgba(191,219,254,.42), transparent 34%), radial-gradient(ellipse at 94% 28%, rgba(221,214,254,.34), transparent 28%)' }}>
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-white/70 bg-white/85 px-5 py-4 shadow-sm backdrop-blur-xl sm:px-10"><BrandMark size="md" /><div className="flex items-center gap-2 sm:gap-4"><nav aria-label="Client navigation" className="flex items-center gap-1 rounded-xl bg-slate-100 p-1 text-sm font-semibold"><Link to="/home" className="rounded-lg px-3 py-2 text-slate-600 hover:bg-white hover:text-blue-700">Home</Link><Link to="/client-portal" aria-current="page" className="rounded-lg bg-white px-3 py-2 text-blue-700 shadow-sm">My portal</Link></nav><span className="hidden text-sm font-medium text-slate-500 xl:block">{profile.company || profile.name || profile.email}</span><button onClick={onLogout} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"><LogOut size={16} /> <span className="hidden sm:inline">Sign out</span></button></div></header>
    <div className="mx-auto max-w-6xl space-y-7 px-4 py-6 sm:px-8 sm:py-9">
      <section className="relative isolate overflow-hidden rounded-[28px] bg-[#101a38] px-6 py-8 text-white shadow-[0_28px_80px_-34px_rgba(24,39,82,.65)] sm:px-10 sm:py-10">
        <div className="pointer-events-none absolute -right-12 -top-32 -z-10 h-80 w-80 rounded-full bg-cyan-500/25 blur-3xl" /><div className="pointer-events-none absolute bottom-[-140px] right-[28%] -z-10 h-72 w-72 rounded-full bg-violet-500/20 blur-3xl" />
        <div className="grid items-end gap-8 lg:grid-cols-[1.3fr_.7fr]">
          <div><span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[.08] px-3 py-1.5 text-xs font-semibold uppercase tracking-[.16em] text-cyan-100"><Sparkles size={14} /> Client workspace</span><h1 className="mt-5 max-w-2xl text-3xl font-bold leading-tight tracking-[-.035em] text-white sm:text-5xl">Welcome, {welcomeName}.<br className="hidden sm:block" /> Let’s find the right trainer.</h1><p className="mt-4 max-w-xl text-sm leading-6 text-blue-100/80 sm:text-base">Share the training need in your own words. We’ll organize the details and guide your request through the TrainerSync team.</p><div className="mt-7 flex flex-wrap items-center gap-3"><a href="#request-builder" className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-bold text-[#16254c] shadow-lg shadow-black/10 transition hover:-translate-y-0.5 hover:bg-blue-50">Create a request <ArrowDown size={16} /></a><a href="#request-tracker" className="inline-flex items-center gap-2 rounded-xl border border-white/20 bg-white/[.07] px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/[.13]">Track requests <ArrowUpRight size={16} /></a></div></div>
          <div className="grid grid-cols-2 gap-3"><div className="rounded-2xl border border-white/10 bg-white/[.08] p-4 backdrop-blur-sm"><p className="text-xs font-medium uppercase tracking-wider text-blue-100/65">Requests submitted</p><p className="mt-2 text-3xl font-bold text-white">{loading ? '—' : requests.length}</p><p className="mt-1 text-xs text-blue-100/65">managed by our team</p></div><div className="rounded-2xl border border-white/10 bg-white/[.08] p-4 backdrop-blur-sm"><p className="text-xs font-medium uppercase tracking-wider text-blue-100/65">Plan status</p><p className="mt-2 text-lg font-bold text-white">{loading ? 'Loading' : subscription.active ? 'Active' : 'Available'}</p><p className="mt-1 text-xs text-blue-100/65">{loading ? 'Checking your client plan' : subscription.active ? 'Unlimited requests enabled' : 'One year · ₹999'}</p></div><div className="col-span-2 flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[.08] p-4 backdrop-blur-sm"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-cyan-300/15 text-cyan-200"><Building2 size={19} /></div><div><p className="text-sm font-semibold text-white">Your trainer search stays private</p><p className="mt-0.5 text-xs leading-5 text-blue-100/65">We coordinate matching. Trainer identities and contact details aren’t displayed here.</p></div></div></div>
        </div>
      </section>
      <div><p className="text-xs font-bold uppercase tracking-[.15em] text-blue-700">Step 1: Tell us what you need</p><h2 className="mt-1 text-2xl font-bold tracking-tight">Submit a trainer request</h2><p className="mt-2 text-slate-600">Paste your client request email or describe the training need. We will organize it for the TrainerSync team.</p></div>
      {loading ? <p className="rounded-2xl bg-white p-6 text-slate-500">Loading your client workspace…</p> : <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(290px,.65fr)]">
        <div className="space-y-6">
          <section id="request-builder" className="scroll-mt-24 rounded-[24px] border border-white bg-white p-5 shadow-[0_20px_60px_-38px_rgba(27,42,77,.35)] sm:p-7">
            <div className="mb-4"><h2 className="text-lg font-bold">Training request</h2><p className="mt-1 text-sm text-slate-500">The parser identifies the domain, duration, dates, mode, commercial, lab hours, and requested documents. Review and correct them before submitting.</p></div>
            <textarea rows="11" maxLength="12000" value={requestText} onChange={event => setRequestText(event.target.value)} placeholder="Paste the full client request email or type your request here…" className="w-full rounded-xl border border-slate-300 p-4 text-sm leading-6 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><span className="text-xs text-slate-500">You can parse and review before subscribing.</span><button disabled={busy || requestText.trim().length < 20} onClick={parseRequest} className="rounded-xl border border-blue-200 px-4 py-2.5 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50">{busy ? 'Reading request…' : 'Read and extract details'}</button></div>
            <details className="mt-4 rounded-xl bg-slate-50 p-3"><summary className="cursor-pointer text-sm font-semibold text-slate-700">Show example request email</summary><pre className="mt-3 whitespace-pre-wrap font-sans text-xs leading-5 text-slate-600">{SAMPLE_REQUEST}</pre><button type="button" onClick={() => { setRequestText(SAMPLE_REQUEST); setParsed(null) }} className="mt-3 text-xs font-semibold text-blue-700">Use this example</button></details>
          </section>

          {parsed && <section className="space-y-4 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm sm:p-7">
            <div><h2 className="text-lg font-bold">Review extracted details</h2><p className="mt-1 text-sm text-slate-500">Edit anything the parser missed before submitting.</p></div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-semibold">Domain *<input value={parsed.domain || ''} onChange={event => setField('domain', event.target.value)} placeholder="e.g. DevOps" className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold">Duration (days)<input type="number" min="1" max="365" value={parsed.duration_days} onChange={event => setField('duration_days', event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold">Start date<input type="date" value={parsed.timeline_start || ''} onChange={event => setField('timeline_start', event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold">End date<input type="date" value={parsed.timeline_end || ''} onChange={event => setField('timeline_end', event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold">Training mode<select value={parsed.delivery_mode || ''} onChange={event => setField('delivery_mode', event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal"><option value="">Select mode</option><option>Online</option><option>On-site</option><option>Hybrid</option></select></label>
              <label className="text-sm font-semibold">Commercial (₹)<input type="number" min="0" value={parsed.commercial_amount} onChange={event => setField('commercial_amount', event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold">Hands-on lab hours per day<input type="number" min="0" max="24" step="0.5" value={parsed.lab_hours_per_day} onChange={event => setField('lab_hours_per_day', event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold">Minimum trainer experience (years)<input type="number" min="0" max="70" value={parsed.min_experience_years} onChange={event => setField('min_experience_years', event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold sm:col-span-2">Skills / subskills<input value={(parsed.required_skills || []).join(', ')} onChange={event => setField('required_skills', event.target.value.split(/[,;\n]/).map(value => value.trim()).filter(Boolean))} placeholder="DevOps, Kubernetes, CI/CD" className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold sm:col-span-2">Training approach<textarea rows="2" value={parsed.training_approach || ''} onChange={event => setField('training_approach', event.target.value)} placeholder="Conceptual sessions and hands-on activities" className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold sm:col-span-2">Company industry / business use case (optional)<textarea rows="3" maxLength="1200" value={parsed.business_context || ''} onChange={event => setField('business_context', event.target.value)} placeholder="For example: banking operations, retail demand forecasting, or the workflow your team wants to improve with this training." className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /><span className="mt-1 block text-xs font-normal text-slate-500">This helps tailor the ToC, examples, and labs. Enter only details the client has shared.</span></label>
              <label className="text-sm font-semibold sm:col-span-2">Requested deliverables<input value={(parsed.requested_deliverables || []).join(', ')} onChange={event => setField('requested_deliverables', event.target.value.split(/[,;\n]/).map(value => value.trim()).filter(Boolean))} placeholder="Trainer profile / updated CV, detailed day-wise ToC, lab cost" className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold">Participants<input type="number" min="1" value={parsed.participant_count || ''} onChange={event => setField('participant_count', event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
              <label className="text-sm font-semibold">Location<input value={parsed.location || ''} onChange={event => setField('location', event.target.value)} placeholder="City / country" className="mt-1.5 w-full rounded-xl border border-slate-300 p-3 font-normal" /></label>
            </div>
            {!profile.email_verified && <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Verify your account email in the Client account panel before submitting a request.</p>}
            {!subscription.active && <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Subscribe to the annual client plan before submitting. Your extracted request stays here while you complete checkout.</p>}
            <button disabled={busy || !subscription.active || !profile.email_verified || !parsed.domain?.trim()} onClick={submitRequest} className="w-full rounded-xl bg-blue-700 px-5 py-3 font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50">{busy ? 'Submitting request…' : subscription.active ? 'Submit trainer request' : 'Subscribe to submit requests'}</button>
          </section>}
        </div>

        <aside id="request-tracker" className="scroll-mt-24 space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="font-bold">Client account</h2>
            <p className="mt-3 flex items-center gap-2 text-sm text-slate-600"><Mail size={15} />{profile.email}</p>
            <div className={`mt-3 rounded-xl p-3 text-sm ${profile.email_verified ? 'bg-green-50 text-green-800' : 'bg-amber-50 text-amber-900'}`}>
              {profile.email_verified ? 'Account email verified' : 'Verify your account email to submit requests.'}
              {!profile.email_verified && <div className="mt-2">{!emailCodeSent ? <button type="button" onClick={sendEmailCode} className="font-semibold underline">Send verification code</button> : <><form onSubmit={verifyEmailCode} className="flex gap-2"><input required inputMode="numeric" pattern="[0-9]{6}" maxLength="6" value={emailCode} onChange={event => setEmailCode(event.target.value)} placeholder="6-digit code" className="min-w-0 flex-1 rounded-lg border border-amber-300 px-3 py-2 text-slate-900" /><button className="rounded-lg bg-amber-800 px-3 py-2 font-semibold text-white">Verify</button></form><button type="button" onClick={sendEmailCode} className="mt-2 text-xs font-semibold underline">Resend code</button></>}</div>}
            </div>
            <form onSubmit={saveContact} className="mt-4 space-y-3">
              <label className="block text-xs font-semibold text-slate-600">Contact name<input required maxLength="120" value={contactForm.name} onChange={event => setContactForm(current => ({ ...current, name: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 p-2.5 text-sm" /></label>
              <label className="block text-xs font-semibold text-slate-600">Company<input required maxLength="160" value={contactForm.company} onChange={event => setContactForm(current => ({ ...current, company: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 p-2.5 text-sm" /></label>
              <label className="block text-xs font-semibold text-slate-600">Contact phone<input required maxLength="40" value={contactForm.phone} onChange={event => setContactForm(current => ({ ...current, phone: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 p-2.5 text-sm" /></label>
              <button disabled={profileSaving} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50">{profileSaving ? 'Saving…' : 'Save contact details'}</button>
            </form>
          </section>
          <section className="rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
            {loading ? <><h2 className="font-bold">Checking your client plan</h2><p className="mt-2 text-sm text-slate-600">Your plan details and available client offer will appear here.</p></> : <>
              <div className="flex items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-wide text-blue-700">{subscription.active ? 'Your client plan' : 'Client plan offer'}</p><h2 className="mt-1 text-2xl font-bold">₹999 <span className="text-sm font-medium text-slate-500">/ year</span></h2></div>{subscription.active && <CheckCircle2 className="text-green-600" size={23} />}</div>
              <p className="mt-2 text-sm text-slate-600">One payment for one year, with unlimited trainer requests, request tracking, and TrainerSync team coordination. Trainer profiles and personal contact details stay private in this portal.</p>
              {subscription.active ? <p className="mt-4 flex items-center gap-2 rounded-xl bg-green-50 p-3 text-sm font-semibold text-green-800"><CalendarDays size={16} /> Active until {subscription.expires_at ? new Date(subscription.expires_at).toLocaleDateString() : 'the plan expiry date'}</p> : <>
                <button disabled={busy || !subscription.checkout_enabled} onClick={subscribe} className="mt-4 w-full rounded-xl bg-blue-700 px-4 py-3 text-sm font-bold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50">{busy ? 'Opening secure checkout…' : 'Subscribe · ₹999 for one year'}</button>
                {!subscription.checkout_enabled && <p className="mt-3 text-xs text-amber-800">Secure checkout is not available yet. Contact TrainerSync to activate this client offer.</p>}
              </>}
            </>}
          </section>
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 font-semibold">Your requests</h2>
            {requestId && <div role="status" className="mb-4 rounded-xl border border-green-200 bg-green-50 p-3 text-sm text-green-900"><strong>Thank you — your request was submitted.</strong><p className="mt-1">Reference: {requestId}. Follow its progress below.</p></div>}
            {requests.length ? <div className="space-y-3">{requests.map(item => <div key={item.requirement_id} className={`rounded-xl border p-3 ${requestId === item.requirement_id ? 'border-blue-300 bg-blue-50' : 'border-slate-200'}`}>
              <div className="flex items-center justify-between gap-2"><p className="font-semibold">{item.domain || item.technology_needed || item.title}</p><span className="shrink-0 text-xs font-semibold text-blue-800">{item.tracking_label || 'Request received'}</span></div>
              <p className="mt-1 text-xs text-slate-500">{item.requirement_id}{item.duration_days ? ` · ${item.duration_days} training days` : ''}{item.timeline_start ? ` · starts ${item.timeline_start}` : ''}</p>
              <RequestProgress request={item} />
              {item.tracking_note && <p className="mt-3 rounded-lg bg-blue-50 p-2.5 text-xs leading-5 text-blue-900">Team update: {item.tracking_note}</p>}
              {item.tracking_updated_at && <p className="mt-1 text-[11px] text-slate-400">Updated {new Date(item.tracking_updated_at).toLocaleString()}</p>}
              <p className="mt-3 text-xs leading-5 text-slate-500">TrainerSync coordinates matching and updates here. Trainer names and contact details stay private in this portal.</p>
            </div>)}</div> : <p className="text-sm text-slate-500">Your submitted requests will appear here.</p>}
          </section>
        </aside>
      </div>}
    </div>
  </main>
}
