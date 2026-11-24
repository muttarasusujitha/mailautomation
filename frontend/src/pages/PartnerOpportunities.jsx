import { useCallback, useEffect, useState } from 'react'
import { BriefcaseBusiness, Plus, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../utils/api'

const initial = { company_name: '', title: '', domain: '', description: '', location: '', delivery_mode: '', duration: '', start_date: '', required_skills: '' }

export default function PartnerOpportunities() {
  const [form, setForm] = useState(initial)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/trainers/portal/opportunities/manage')
      setItems(data.items || [])
    } catch (error) { toast.error(error.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    try {
      const { required_skills, ...rest } = form
      await api.post('/trainers/portal/opportunities/manage', {
        ...rest,
        required_skills: required_skills.split(',').map(value => value.trim()).filter(Boolean),
      })
      setForm(initial)
      toast.success('Partner opportunity added.')
      await load()
    } catch (error) { toast.error(error.message) }
    finally { setSaving(false) }
  }

  const toggleStatus = async item => {
    try {
      const { required_skills = [], ...rest } = item
      await api.patch(`/trainers/portal/opportunities/manage/${encodeURIComponent(item.opportunity_id)}`, {
        ...rest, required_skills, status: item.status === 'active' ? 'inactive' : 'active',
      })
      toast.success(item.status === 'active' ? 'Opportunity closed.' : 'Opportunity activated.')
      await load()
    } catch (error) { toast.error(error.message) }
  }

  const input = (key, label, required = false, placeholder = '') => <label className="block text-sm font-semibold">{label}<input required={required} maxLength={key === 'description' ? 3000 : 160} value={form[key]} onChange={event => setForm(current => ({ ...current, [key]: event.target.value }))} placeholder={placeholder} className="mt-1.5 w-full rounded-xl border border-slate-300 bg-white p-3 font-normal" /></label>

  return <div className="mx-auto max-w-6xl space-y-7 p-5 sm:p-8">
    <header>
      <p className="text-sm font-semibold uppercase tracking-wide text-blue-700">Partner network</p>
      <h1 className="mt-1 text-3xl font-bold text-slate-900">Trainer opportunities</h1>
      <p className="mt-2 max-w-3xl text-slate-600">Add confirmed company partnerships and active training openings. Trainers see active openings that match their domains or skills, inside their existing portal.</p>
    </header>

    <form onSubmit={submit} className="space-y-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
      <h2 className="flex items-center gap-2 text-lg font-bold"><Plus size={18} className="text-blue-700" /> Add partner opening</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {input('company_name', 'Confirmed partner company', true, 'Company name')}
        {input('title', 'Opportunity title', true, 'e.g. DevOps trainer for a 20-day batch')}
        {input('domain', 'Training domain', true, 'e.g. DevOps')}
        {input('location', 'Location', false, 'City or remote')}
        {input('delivery_mode', 'Delivery mode', false, 'Online, offline, hybrid')}
        {input('duration', 'Duration', false, 'e.g. 20 days')}
        {input('start_date', 'Expected start date', false, 'e.g. 20 September 2026')}
        {input('required_skills', 'Required skills', false, 'Comma-separated skills')}
      </div>
      <label className="block text-sm font-semibold">Opening details<textarea maxLength={3000} rows={4} value={form.description} onChange={event => setForm(current => ({ ...current, description: event.target.value }))} placeholder="Describe the training assignment and requirements" className="mt-1.5 w-full rounded-xl border border-slate-300 bg-white p-3 font-normal" /></label>
      <button disabled={saving} className="inline-flex items-center gap-2 rounded-xl bg-blue-700 px-5 py-3 font-semibold text-white hover:bg-blue-800 disabled:opacity-60"><Plus size={17} />{saving ? 'Adding…' : 'Add active opportunity'}</button>
    </form>

    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3"><div><h2 className="text-xl font-bold">Managed openings</h2><p className="mt-1 text-sm text-slate-600">Only active openings appear to trainers.</p></div><button type="button" onClick={load} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium"><RefreshCw size={15} />Refresh</button></div>
      {loading ? <p className="rounded-xl bg-white p-5 text-slate-500">Loading openings…</p> : items.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No partner openings have been entered yet.</p> : <div className="grid gap-3">{items.map(item => <article key={item.opportunity_id} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex min-w-0 items-start gap-3"><BriefcaseBusiness size={19} className="mt-1 shrink-0 text-blue-700" /><div><p className="font-semibold text-slate-900">{item.title} <span className="font-normal text-slate-500">· {item.company_name}</span></p><p className="mt-1 text-sm text-slate-600">{item.domain}{item.location ? ` · ${item.location}` : ''}{item.delivery_mode ? ` · ${item.delivery_mode}` : ''}</p><span className={`mt-2 inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${item.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>{item.status}</span><p className="mt-2 text-sm font-medium text-slate-700">{item.interest_count || 0} trainer{item.interest_count === 1 ? '' : 's'} interested</p>{item.interested_trainers?.length > 0 && <ul className="mt-1 space-y-1 text-sm text-slate-600">{item.interested_trainers.map((trainer, index) => <li key={`${trainer.email}-${index}`}>{trainer.profile_name || 'Trainer'}{trainer.email ? ` · ${trainer.email}` : ''}</li>)}</ul>}</div></div>
        <button type="button" onClick={() => toggleStatus(item)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold hover:bg-slate-50">{item.status === 'active' ? 'Close opening' : 'Activate opening'}</button>
      </article>)}</div>}
    </section>
  </div>
}
