import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { AlertCircle, CheckCircle2, Download, FileSpreadsheet, Loader2, RefreshCw, Users } from 'lucide-react'
import { getRequirements } from '../utils/api'
import api from '../utils/api'

const packages = [
  { value: 'basic', label: 'Basic', note: 'Essential individual labs' },
  { value: 'standard', label: 'Standard', note: 'Recommended guided lab environment' },
  { value: 'advanced', label: 'Advanced', note: 'Higher-capacity labs and capstone work' },
]

function requirementLabel(req) {
  const reference = req.requirement_id || req.id || 'Requirement'
  const technology = req.technology_needed || req.domain || req.job_title || 'Training'
  const client = req.client_name || req.client_company || req.client_email || 'Client not specified'
  return `${reference} - ${technology} - ${client}`
}

function labDeliveryStatus(req = {}) {
  const status = String(req.lab_cost_status || '').toLowerCase()
  if (status === 'revised_estimate_sent') return { label: 'Revised estimate sent', detail: 'The latest client participant and access inputs were used.', tone: 'success' }
  if (status === 'revised_estimate_failed') return { label: 'Delivery failed', detail: 'The calculation or email delivery failed. Review inputs and generate/send again.', tone: 'error' }
  if (status === 'inputs_received') return { label: 'Inputs received', detail: 'The client inputs are saved. A revised estimate is being prepared.', tone: 'pending' }
  if (req.lab_cost_requested) return { label: 'Lab cost requested', detail: 'The system will use the TOC and the latest client inputs.', tone: 'pending' }
  return { label: 'Not requested', detail: 'No lab-cost workbook will be sent until the client asks for it.', tone: 'neutral' }
}

export default function LabCost() {
  const [view, setView] = useState('deliveries')
  const [requirements, setRequirements] = useState([])
  const [requirementId, setRequirementId] = useState('')
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [catalogJson, setCatalogJson] = useState('{}')
  const [labMode, setLabMode] = useState('ai')
  const [manualMapping, setManualMapping] = useState('[]')
  const [deliveries, setDeliveries] = useState([])
  const [deliveryLoading, setDeliveryLoading] = useState(true)
  const [clientKey, setClientKey] = useState('')
  const [deliveryEmailId, setDeliveryEmailId] = useState('')
  const [pricingProfile, setPricingProfile] = useState({ status: 'idle', detail: '' })
  const [form, setForm] = useState({
    cloud_provider: '',
    cloud_region: '',
    hours_per_day: '',
    participant_count: '',
    fx_rate: '',
    disk_gb_per_node: '',
    storage_gb: '',
    egress_gb: '',
    build_minutes: '',
    monitoring_gb: '',
    k8s_worker_nodes: '',
    contingency_percent: 10,
    tax_percent: 0,
    lab_package: 'standard',
    quote_validity_days: 7,
  })

  const selected = useMemo(
    () => requirements.find(item => (item.requirement_id || item.id) === requirementId),
    [requirements, requirementId],
  )
  const delivery = labDeliveryStatus(selected)
  const clients = useMemo(() => {
    const grouped = new Map()
    deliveries.forEach(item => {
      const key = item.client_email || item.client_name || 'client'
      if (!grouped.has(key)) grouped.set(key, { key, name: item.client_name || 'Client', email: item.client_email || '', items: [] })
      grouped.get(key).items.push(item)
    })
    return [...grouped.values()]
  }, [deliveries])
  const selectedClient = clients.find(item => item.key === clientKey) || clients[0]
  const selectedDelivery = selectedClient?.items.find(item => item.email_id === deliveryEmailId) || selectedClient?.items[0]

  const loadRequirements = async () => {
    setLoading(true)
    try {
      const { data } = await getRequirements()
      const items = data.requirements || data.items || data.data || []
      setRequirements(items)
      if (!requirementId && items[0]) setRequirementId(items[0].requirement_id || items[0].id)
    } catch (error) {
      toast.error(error.message || 'Could not load requirements')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadRequirements() }, [])

  const loadDeliveries = async () => {
    setDeliveryLoading(true)
    try {
      const { data } = await api.get('/toc/lab-cost/client-deliveries')
      const items = data.items || []
      setDeliveries(items)
      if (!clientKey && items[0]) setClientKey(items[0].client_email || items[0].client_name || 'client')
      if (!deliveryEmailId && items[0]) setDeliveryEmailId(items[0].email_id)
    } catch (error) {
      toast.error(error.message || 'Could not load client lab-cost deliveries')
    } finally {
      setDeliveryLoading(false)
    }
  }

  useEffect(() => { loadDeliveries() }, [])

  useEffect(() => {
    if (!selected) return
    setForm(previous => ({
      ...previous,
      participant_count: selected.participant_count || selected.participants || selected.batch_size || '',
      hours_per_day: selected.lab_hours_per_day || '',
      cloud_provider: selected.cloud_provider || '',
      cloud_region: selected.cloud_region || '',
      fx_rate: selected.fx_rate || '',
    }))
  }, [selected])

  useEffect(() => {
    if (!form.cloud_provider || !form.cloud_region) {
      setPricingProfile({ status: 'idle', detail: '' })
      return
    }
    let active = true
    setPricingProfile({ status: 'checking', detail: 'Checking live-pricing profile…' })
    api.get(`/toc/lab-cost/pricing-catalog/${form.cloud_provider}/${encodeURIComponent(form.cloud_region)}`)
      .then(({ data }) => {
        if (active) setPricingProfile({ status: 'ready', detail: `Verified profile configured ${data.validated_at ? `on ${new Date(data.validated_at).toLocaleString()}` : ''}. Rates will refresh when the workbook is generated.` })
      })
      .catch(error => {
        if (!active) return
        const message = error?.response?.status === 404
          ? 'No verified pricing profile is configured for this provider and region. Configure the lab resource architecture before generating a client quote.'
          : (error.message || 'Could not check the live-pricing profile')
        setPricingProfile({ status: 'missing', detail: message })
      })
    return () => { active = false }
  }, [form.cloud_provider, form.cloud_region])

  const update = (key, value) => setForm(previous => ({ ...previous, [key]: value }))

  const downloadSentWorkbook = async () => {
    if (!selectedDelivery?.email_id) return
    try {
      const response = await api.get(`/toc/lab-cost/client-deliveries/${selectedDelivery.email_id}/download`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([response.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
      const link = document.createElement('a')
      link.href = url
      link.download = selectedDelivery.workbook_filename || 'Lab Cost Estimate.xlsx'
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(error.message || 'Could not download the sent workbook')
    }
  }

  const saveSetup = async (catalog = false) => {
    if (!selected || !form.cloud_provider || !form.cloud_region) return toast.error('Select requirement, provider and region')
    setSaving(true)
    try {
      if (catalog) {
        const selections = JSON.parse(catalogJson)
        if (!selections || Array.isArray(selections) || typeof selections !== 'object' || !Object.keys(selections).length) throw new Error('Enter resource SKU selections as a JSON object')
        await api.put('/toc/lab-cost/pricing-catalog', { cloud_provider: form.cloud_provider, cloud_region: form.cloud_region, selections })
        setPricingProfile({ status: 'ready', detail: 'Selections verified and saved. Provider prices refresh for every workbook.' })
      } else {
        const participants = Number(form.participant_count), hours = Number(form.hours_per_day), fx = Number(form.fx_rate)
        if (!Number.isInteger(participants) || participants < 1 || !Number.isFinite(hours) || hours <= 0 || hours > 24 || !Number.isFinite(fx) || fx <= 0) throw new Error('Confirm whole participant count, lab hours (up to 24), and positive exchange rate')
        const values = { participant_count: participants, lab_hours_per_day: hours, fx_rate: fx, cloud_provider: form.cloud_provider, cloud_region: form.cloud_region }
        await api.patch(`/requirements/${encodeURIComponent(requirementId)}`, values)
        setRequirements(previous => previous.map(item => (item.requirement_id || item.id) === requirementId ? { ...item, ...values } : item))
      }
      toast.success(catalog ? 'Pricing catalog verified and saved' : 'Lab inputs saved for shortlist handoff')
    } catch (error) { toast.error(error.message || 'Could not save lab setup') }
    finally { setSaving(false) }
  }

  const downloadLabCost = async () => {
    if (!selected) return toast.error('Select a requirement first')
    const technology = selected.technology_needed || selected.domain || selected.job_title
    const durationDays = Number(selected.duration_days || Math.ceil(Number(selected.duration_hours || 0) / 8) || 3)
    if (!technology) return toast.error('The selected requirement needs a technology')
    if ([form.hours_per_day, form.participant_count, form.fx_rate, form.quote_validity_days].some(value => Number(value) <= 0)) {
      return toast.error('Hours, participants, FX rate, and validity must be positive')
    }

    setGenerating(true)
    try {
      const usage = Object.fromEntries(['disk_gb_per_node', 'storage_gb', 'egress_gb', 'build_minutes', 'monitoring_gb', 'k8s_worker_nodes'].map(key => {
        if (form[key] === '' || !Number.isFinite(Number(form[key])) || Number(form[key]) < 0) throw new Error(`Confirm ${key.replaceAll('_', ' ')}; enter 0 when unused`)
        return [key, Number(form[key])]
      }))
      const mapping = labMode === 'manual' ? JSON.parse(manualMapping) : undefined
      const tocResponse = await api.post('/toc/generate', {
        generation_mode: labMode === 'manual' ? 'template' : 'ai',
        allow_ai_enrichment: labMode !== 'manual',
        requirement_id: selected.requirement_id || selected.id,
        technology,
        duration_days: durationDays,
        audience_level: selected.audience_level || selected.level || 'intermediate',
        mode: selected.mode || selected.training_mode || 'Online',
        training_dates: selected.training_dates || selected.preferred_dates || '',
        timing: selected.timing || selected.schedule || '',
      })
      const response = await api.post('/toc/generate-lab-cost', {
        ...usage,
        lab_generation_mode: labMode,
        lab_day_mapping: mapping,
        toc_id: tocResponse.data.toc_id,
        cloud_provider: form.cloud_provider,
        cloud_region: form.cloud_region,
        hours_per_day: Number(form.hours_per_day),
        participant_count: Number(form.participant_count),
        fx_rate: Number(form.fx_rate),
        contingency_percent: Number(form.contingency_percent),
        tax_percent: Number(form.tax_percent),
        lab_package: form.lab_package,
        quote_validity_days: Number(form.quote_validity_days),
      }, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }))
      const link = document.createElement('a')
      link.href = url
      link.download = `${String(technology).replace(/[^a-z0-9]+/gi, '_')}_${form.cloud_provider}_lab_cost.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      toast.success('Lab cost workbook generated. Review it before sending to the client.')
    } catch (error) {
      let detail = error.message || 'Lab cost generation failed'
      if (error.response?.data instanceof Blob) {
        try { const body = JSON.parse(await error.response.data.text()); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail) } catch { /* Preserve the original error. */ }
      }
      toast.error(detail)
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Lab Cost</h1>
          <p className="mt-1 text-sm text-slate-600">Prepare the approved Lab Cost workbook only when the client explicitly asks for a lab cost or estimate.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setView('deliveries')} className={`rounded-lg px-3 py-2 text-sm font-semibold ${view === 'deliveries' ? 'bg-slate-900 text-white' : 'border border-slate-200 bg-white text-slate-700'}`}>Client lab-costs</button>
          <button type="button" onClick={() => setView('create')} className={`rounded-lg px-3 py-2 text-sm font-semibold ${view === 'create' ? 'bg-emerald-700 text-white' : 'border border-slate-200 bg-white text-slate-700'}`}>Create workbook</button>
          <button type="button" onClick={view === 'deliveries' ? loadDeliveries : loadRequirements} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
            <RefreshCw className={`h-4 w-4 ${(view === 'deliveries' ? deliveryLoading : loading) ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
      </div>

      {view === 'deliveries' && <section className="grid gap-5 lg:grid-cols-[0.85fr_1.15fr]">
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <div className="flex items-center gap-2"><Users className="h-4 w-4 text-slate-500" /><h2 className="font-bold text-slate-900">Clients</h2></div>
          <p className="mt-1 text-sm text-slate-500">Select a client, then the requirement whose workbook was sent.</p>
          <div className="mt-4 space-y-2">
            {clients.map(client => <button key={client.key} type="button" onClick={() => { setClientKey(client.key); setDeliveryEmailId(client.items[0]?.email_id || '') }} className={`w-full rounded-lg border p-3 text-left text-sm ${selectedClient?.key === client.key ? 'border-emerald-500 bg-emerald-50' : 'border-slate-200 hover:bg-slate-50'}`}><p className="font-bold text-slate-800">{client.name}</p><p className="text-slate-500">{client.email || 'Client email unavailable'} · {client.items.length} sent</p></button>)}
            {!deliveryLoading && !clients.length && <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">No sent lab-cost workbook is recorded yet. Future client deliveries will appear here with their exact download.</p>}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          {selectedClient && <><h2 className="font-bold text-slate-900">Requirements for {selectedClient.name}</h2><div className="mt-3 flex flex-wrap gap-2">{selectedClient.items.map(item => <button type="button" key={item.email_id} onClick={() => setDeliveryEmailId(item.email_id)} className={`rounded-lg border px-3 py-2 text-left text-sm ${selectedDelivery?.email_id === item.email_id ? 'border-blue-500 bg-blue-50' : 'border-slate-200'}`}><span className="block font-bold">{item.requirement_id}</span><span className="text-slate-500">{item.technology}</span></button>)}</div></>}
          {selectedDelivery && <div className="mt-5 rounded-lg border border-slate-100 bg-slate-50 p-4"><div className="grid gap-3 sm:grid-cols-2 text-sm"><Info label="Client" value={selectedDelivery.client_name} /><Info label="Requirement ID" value={selectedDelivery.requirement_id} /><Info label="Training" value={selectedDelivery.technology} /><Info label="Duration / dates" value={[selectedDelivery.duration_days && `${selectedDelivery.duration_days} days`, selectedDelivery.training_dates].filter(Boolean).join(' · ') || 'Not specified'} /><Info label="Sent template" value={selectedDelivery.workbook_filename} /><Info label="Sent on" value={selectedDelivery.sent_at ? new Date(selectedDelivery.sent_at).toLocaleString() : 'Recorded'} /></div><div className="mt-4 rounded-md border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900"><p className="font-bold">Lab-cost summary</p><p className="mt-1">{selectedDelivery.summary?.scope}. {selectedDelivery.summary?.cost_status}.</p><p className="mt-1 text-blue-700">{selectedDelivery.summary?.note}</p></div><button type="button" onClick={downloadSentWorkbook} disabled={!selectedDelivery.has_download} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"><Download className="h-4 w-4" /> Download sent workbook</button></div>}
          {!selectedClient && !deliveryLoading && <p className="text-sm text-slate-500">Choose a client to view its sent lab-cost template and requirement details.</p>}
        </div>
      </section>}

      {view === 'create' && <>
      <section className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Requirement</label>
          <select className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm" value={requirementId} onChange={event => setRequirementId(event.target.value)} disabled={loading}>
            <option value="">Select a requirement</option>
            {requirements.map(requirement => <option key={requirement.requirement_id || requirement.id} value={requirement.requirement_id || requirement.id}>{requirementLabel(requirement)}</option>)}
          </select>
          {selected && <div className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 text-sm">
            <div><p className="text-slate-500">Technology</p><p className="font-semibold text-slate-800">{selected.technology_needed || selected.domain || selected.job_title}</p></div>
            <div><p className="text-slate-500">Duration</p><p className="font-semibold text-slate-800">{selected.duration_days || Math.ceil(Number(selected.duration_hours || 0) / 8) || 3} days</p></div>
          </div>}
          {selected && <div className={`mt-4 flex gap-3 rounded-lg border p-3 text-sm ${delivery.tone === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : delivery.tone === 'error' ? 'border-red-200 bg-red-50 text-red-800' : delivery.tone === 'pending' ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
            {delivery.tone === 'success' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
            <div><p className="font-bold">Lab-cost status: {delivery.label}</p><p className="mt-0.5 leading-5">{delivery.detail}</p></div>
          </div>}
        </div>

        <div className="rounded-lg border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
          <p className="font-bold">Send rule</p>
          <p className="mt-1 leading-6">When a client later gives participant count, lab hours, dates, or other lab inputs, the automated workflow recalculates from the TOC and sends a revised workbook. If delivery fails, the status panel above shows it for manual retry.</p>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-base font-bold text-slate-900">Cost assumptions</h2>
        <div className="my-4 grid gap-4 sm:grid-cols-2">
          {Object.entries({ disk_gb_per_node: 'Disk GB per VM / worker', storage_gb: 'Object storage GB', egress_gb: 'Outbound transfer GB', build_minutes: 'Build runner minutes', monitoring_gb: 'Monitoring GB', k8s_worker_nodes: 'Shared Kubernetes workers' }).map(([key, label]) => <Field key={key} label={label}><input type="number" min="0" step={key === 'k8s_worker_nodes' ? '1' : 'any'} value={form[key]} onChange={event => update(key, event.target.value)} /></Field>)}
        </div>
        <p className="text-sm text-slate-600">Enter confirmed usage; use 0 for unused resources. Compute is charged for access hours. Disk and object storage remain billable while retained. Resource quantities are totals for the group.</p>
        <button type="button" disabled={saving || !selected} onClick={() => saveSetup()} className="my-3 rounded border px-4 py-2 disabled:opacity-50">Save confirmed inputs for Shortlist</button>
        <details className="my-3 rounded border p-3">
          <summary>Configure provider pricing catalog</summary>
          <p className="my-2 text-sm">Enter exact resource selections for the selected provider and region. AWS requires service and SKU/rate_code or product attributes; Azure requires meter_id. The server verifies prices before saving.</p>
          <textarea aria-label="Pricing resource selections JSON" rows={8} className="w-full border p-2 font-mono" value={catalogJson} onChange={event => setCatalogJson(event.target.value)} />
          <button type="button" disabled={saving || !selected} onClick={() => saveSetup(true)} className="mt-2 rounded border px-4 py-2 disabled:opacity-50">Verify and save pricing catalog</button>
        </details>
        <Field label="Lab cost mode"><select value={labMode} onChange={event => setLabMode(event.target.value)}><option value="ai">AI — LLM resource planning + pricing retrieval</option><option value="manual">Manual — entered resources + pricing retrieval</option></select></Field>
        {labMode === 'manual' && <div className="mt-4"><label htmlFor="manual-lab-mapping">Daily resource mapping (JSON array, one entry per TOC day)</label><textarea id="manual-lab-mapping" className="w-full border rounded p-3 font-mono" rows={8} value={manualMapping} onChange={event => setManualMapping(event.target.value)} /><p className="text-sm">Each entry needs vm_qty, vm_profile (None, Light or Heavy), k8s_control_plane, k8s_worker_nodes, managed_db, object_storage_gb and active_days. Quantities are totals for the group.</p></div>}
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Cloud provider"><select value={form.cloud_provider} onChange={event => setForm(previous => ({ ...previous, cloud_provider: event.target.value, cloud_region: '' }))}><option value="">Confirm provider</option><option value="aws">AWS</option><option value="azure">Azure</option><option value="gcp">GCP</option></select></Field>
          <Field label="Cloud region"><select value={form.cloud_region} onChange={event => update('cloud_region', event.target.value)}><option value="">Confirm region</option>{form.cloud_provider === 'aws' && <option value="ap-south-1">Mumbai</option>}{form.cloud_provider === 'azure' && <option value="central-india">Central India</option>}{form.cloud_provider === 'gcp' && <option value="asia-south1">Mumbai</option>}</select></Field>
          <Field label="Lab package"><select value={form.lab_package} onChange={event => update('lab_package', event.target.value)}>{packages.map(item => <option key={item.value} value={item.value}>{item.label} - {item.note}</option>)}</select></Field>
          <Field label="Lab hours per day"><input type="number" min="0.5" step="0.5" value={form.hours_per_day} onChange={event => update('hours_per_day', event.target.value)} /></Field>
          <Field label="Participants"><input type="number" min="1" value={form.participant_count} onChange={event => update('participant_count', event.target.value)} /></Field>
          <Field label="USD to INR"><input type="number" min="1" step="0.01" value={form.fx_rate} onChange={event => update('fx_rate', event.target.value)} /></Field>
          <Field label="Contingency %"><input type="number" min="0" max="100" value={form.contingency_percent} onChange={event => update('contingency_percent', event.target.value)} /></Field>
          <Field label="Tax / GST %"><input type="number" min="0" max="100" value={form.tax_percent} onChange={event => update('tax_percent', event.target.value)} /></Field>
          <Field label="Quote validity (days)"><input type="number" min="1" value={form.quote_validity_days} onChange={event => update('quote_validity_days', event.target.value)} /></Field>
        </div>
        {pricingProfile.status !== 'idle' && <div className={`mt-4 flex gap-3 rounded-lg border p-3 text-sm ${pricingProfile.status === 'ready' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : pricingProfile.status === 'missing' ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
          {pricingProfile.status === 'ready' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
          <div><p className="font-bold">Live pricing profile {pricingProfile.status === 'ready' ? 'ready' : pricingProfile.status === 'checking' ? 'checking' : 'needs setup'}</p><p className="mt-0.5 leading-5">{pricingProfile.detail}</p></div>
        </div>}
      </section>

      <button type="button" onClick={downloadLabCost} disabled={!selected || generating || pricingProfile.status !== 'ready'} className="inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50">
        {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
        {generating ? 'Generating lab cost...' : 'Generate Lab Cost Excel'}
        {!generating && <Download className="h-4 w-4" />}
      </button>
      </>}
    </div>
  )
}

function Info({ label, value }) {
  return <div><p className="text-slate-500">{label}</p><p className="font-semibold text-slate-800 break-words">{value || '—'}</p></div>
}

function Field({ label, children }) {
  return <label className="block"><span className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">{label}</span>{children && <div className="[&>input]:h-10 [&>input]:w-full [&>input]:rounded-lg [&>input]:border [&>input]:border-slate-200 [&>input]:bg-white [&>input]:px-3 [&>input]:text-sm [&>select]:h-10 [&>select]:w-full [&>select]:rounded-lg [&>select]:border [&>select]:border-slate-200 [&>select]:bg-white [&>select]:px-3 [&>select]:text-sm">{children}</div>}</label>
}
