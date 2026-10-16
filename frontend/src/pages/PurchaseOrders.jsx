import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { ArrowLeft, Download, FileText, Loader2, Plus, RefreshCw, Search, Send, Trash2 } from 'lucide-react'
import api from '../utils/api'
import { usePipelineRecords } from '../utils/usePipelineRecords'

function money(value) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(Number(value || 0))
}

function lineAmount(item = {}) {
  return Number(item.quantity || 0) * Number(item.rate || 0)
}

function poStatus(item = {}) {
  const po = item.client_po || {}
  if (po.status === 'acknowledged') return 'Acknowledged'
  if (po.status === 'sent') return 'Sent'
  if (po.po_id) return 'Generated'
  if (item.selected_trainer?.trainer_id) return 'Ready'
  return 'Select trainer'
}

const statusStyles = {
  Acknowledged: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  Sent: 'bg-blue-50 text-blue-700 ring-blue-200',
  Generated: 'bg-violet-50 text-violet-700 ring-violet-200',
  Ready: 'bg-amber-50 text-amber-700 ring-amber-200',
  'Select trainer': 'bg-slate-50 text-slate-500 ring-slate-200',
}

function initialForm(item = {}) {
  const requirement = item.requirement || item
  const po = item.client_po || {}
  const trainer = item.selected_trainer || {}
  const duration = Number(po.duration || requirement.duration_days || 1) || 1
  const total = Number(po.total_amount || requirement.budget_total || 0)
  return {
    po_number: po.po_number || '',
    vendor_name: po.vendor_name || trainer.name || trainer.trainer_name || '',
    client_name: po.client_name || item.client?.company || item.client?.name || requirement.client_company || requirement.client_name || '',
    client_email: po.client_email || item.client?.email || requirement.client_email || '',
    billing_address: po.client_billing_address || requirement.client_billing_address || requirement.client_address || '',
    gstin: po.client_gstin || requirement.client_gstin || '',
    training_domain: po.training_domain || item.domain || requirement.technology_needed || requirement.technology || 'Training',
    training_dates: po.training_dates || requirement.training_dates || '',
    duration: po.duration || String(duration),
    mode: po.mode || requirement.mode || '',
    day_rate: po.day_rate || (total && duration ? Math.round(total / duration) : ''),
    payment_terms: po.payment_terms || '',
    notes: po.notes || '',
    items: po.items?.length ? po.items.map(row => ({ ...row })) : [{
      description: `${item.domain || requirement.technology_needed || requirement.technology || 'Training'} Training`,
      quantity: duration,
      rate: total && duration ? Math.round(total / duration) : '',
    }],
  }
}

function PipelineRow({ item, active, onClick }) {
  const status = poStatus(item)
  const client = item.client?.company || item.client?.name || item.client?.email || 'Client'
  const trainer = item.selected_trainer?.name || item.selected_trainer?.trainer_name || 'No trainer selected'
  return (
    <button type="button" onClick={onClick} className={clsx('w-full border-b border-slate-100 px-4 py-3 text-left transition hover:bg-slate-50', active && 'bg-blue-50')}>
      <div className="flex items-start justify-between gap-3">
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-slate-950">{client}</span>
          <span className="mt-1 block truncate text-xs text-slate-500">{item.domain || item.technology_needed || 'Training'} · {item.requirement_id}</span>
        </span>
        <span className={clsx('shrink-0 rounded-full px-2 py-1 text-[11px] font-bold ring-1', statusStyles[status])}>{status}</span>
      </div>
      <span className="mt-2 block truncate text-xs text-slate-500">{trainer} · {money(item.client_po?.total_amount || item.requirement?.budget_total)}</span>
    </button>
  )
}

export default function PurchaseOrders() {
  const [selectedId, setSelectedId] = useState('')
  const [query, setQuery] = useState('')
  const [form, setForm] = useState(initialForm())
  const [busy, setBusy] = useState('')
  const [mobileShowDetails, setMobileShowDetails] = useState(false)
  const { items, setItems, loading, refreshing, error, load } = usePipelineRecords(query)
  const selected = useMemo(() => items.find(item => item.requirement_id === selectedId) || items[0] || null, [items, selectedId])
  const po = selected?.client_po || {}
  const subtotal = form.items.reduce((sum, row) => sum + lineAmount(row), 0)

  useEffect(() => {
    setSelectedId(previous => items.some(row => row.requirement_id === previous) ? previous : items[0]?.requirement_id || '')
  }, [items])

  useEffect(() => { setForm(initialForm(selected || {})) }, [selected?.requirement_id, selected?.client_po?.po_id])

  const update = (key, value) => setForm(current => ({ ...current, [key]: value }))
  const updateItem = (index, key, value) => setForm(current => ({
    ...current,
    items: current.items.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: value } : row),
  }))
  const addItem = () => setForm(current => ({ ...current, items: [...current.items, { description: '', quantity: 1, rate: '' }] }))
  const removeItem = index => setForm(current => ({
    ...current,
    items: current.items.length > 1 ? current.items.filter((_, rowIndex) => rowIndex !== index) : current.items,
  }))

  const generate = async () => {
    if (!selected) return
    const trainer = selected.selected_trainer || {}
    if (!trainer.trainer_id) return toast.error('Select a trainer for this requirement before generating a PO')
    if (!form.vendor_name.trim() || !form.client_name.trim()) return toast.error('Vendor and client names are required')
    if (!form.items.length || subtotal <= 0) return toast.error('Add at least one line item with a quantity and rate')
    setBusy('generate')
    try {
      const response = await api.post('/purchase-orders/generate', {
        requirement_id: selected.requirement_id,
        trainer_id: trainer.trainer_id,
        vendor_name: form.vendor_name,
        client_name: form.client_name,
        client_email: form.client_email,
        client_po_number: form.po_number,
        client_po_date: '',
        client_billing_address: form.billing_address,
        client_gstin: form.gstin,
        training_domain: form.training_domain,
        training_dates: form.training_dates,
        duration: form.duration,
        mode: form.mode,
        day_rate: Number(form.day_rate || (subtotal / Number(form.duration || 1))),
        total_amount: subtotal,
        gst_rate: Number(selected.client_po?.gst_rate || 0),
        payment_terms: form.payment_terms,
        items: form.items.map(row => ({ ...row, quantity: Number(row.quantity || 0), rate: Number(row.rate || 0), amount: lineAmount(row) })),
        notes: form.notes,
      })
      if (!response.data.purchase_order?.po_id) throw new Error('Purchase order was not saved')
      const saved = response.data.purchase_order
      setItems(rows => rows.map(row => row.requirement_id === selected.requirement_id ? { ...row, client_po: saved } : row))
      toast.success(`Purchase order ${response.data.purchase_order.po_number} generated`)
      await load(true)
    } catch (error) {
      toast.error(error.message || 'Purchase order generation failed')
    } finally {
      setBusy('')
    }
  }

  const download = async () => {
    if (!po.po_id) return toast.error('Generate the purchase order first')
    setBusy('download')
    try {
      const response = await api.get(`/purchase-orders/${po.po_id}/download`, { responseType: 'blob', timeout: 60000 })
      const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `${po.po_number || po.po_id}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(error.message || 'Purchase order download failed')
    } finally { setBusy('') }
  }

  const send = async () => {
    if (!po.po_id) return toast.error('Generate the purchase order first')
    if (!form.client_email.trim()) return toast.error('Add the recipient email address')
    setBusy('send')
    try {
      await api.post(`/purchase-orders/${po.po_id}/send`, { to_email: form.client_email })
      toast.success(`Purchase order sent to ${form.client_email}`)
      await load(true)
    } catch (error) {
      toast.error(error.message || 'Could not send purchase order')
    } finally { setBusy('') }
  }

  return (
    <main className="min-w-0 space-y-4 animate-fade-in">
      <header className="relative overflow-hidden rounded-2xl border border-blue-100 bg-white px-5 py-4 shadow-[0_18px_55px_rgba(37,99,235,0.12)]">
        <div className="absolute right-8 top-0 h-20 w-56 rounded-full bg-blue-200/40 blur-3xl" />
        <div className="relative flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold uppercase tracking-wide text-blue-700 ring-1 ring-blue-100"><FileText className="h-3.5 w-3.5" /> Purchase Orders</div>
            <h1 className="mt-2 page-title">Generate Purchase Order</h1>
            <p className="mt-1 text-sm text-slate-500">Choose a client requirement, confirm the assigned trainer and prepare the PO PDF. Purchase-order mail is sent as Murali Mohan M, and only when a PO is the request. It is not sent with a ToC or lab-cost reply.</p>
          </div>
          <button onClick={() => load(true)} className="btn-secondary text-sm" disabled={refreshing}><RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} /> Refresh</button>
        </div>
      </header>

      {error && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><span>{error} {items.length > 0 && 'Showing the last loaded records.'}</span><button type="button" onClick={() => load(true)} disabled={refreshing} className="btn-secondary">Try again</button></div>}
      <div className="grid min-w-0 items-start gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <aside className={clsx('min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm', mobileShowDetails && 'hidden xl:block')}>
          <div className="border-b border-slate-200 p-4">
            <div className="relative"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search client, trainer, PO..." className="h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none focus:border-blue-400" /></div>
            <p className="mt-3 text-sm font-bold text-slate-950">{items.length} requirements</p>
          </div>
          <div className="xl:max-h-[72dvh] xl:overflow-y-auto [scrollbar-gutter:stable]" aria-busy={loading}>
            {loading ? Array.from({ length: 5 }, (_, index) => <div key={index} className="mx-4 my-3 h-16 animate-pulse rounded-lg bg-slate-100" />) : items.length ? items.map(item => <PipelineRow key={item.requirement_id} item={item} active={item.requirement_id === selected?.requirement_id} onClick={() => { setSelectedId(item.requirement_id); setMobileShowDetails(true) }} />) : <div className="p-8 text-center text-sm text-slate-500">{error ? 'Records could not be loaded.' : 'No requirements found.'}</div>}
          </div>
        </aside>

        <section className={clsx('min-w-0 overflow-hidden rounded-xl border border-blue-100 bg-white shadow-[0_18px_45px_rgba(37,99,235,0.08)]', !mobileShowDetails && 'hidden xl:block')}>
          <button type="button" onClick={() => setMobileShowDetails(false)} className="btn-secondary m-3 xl:hidden"><ArrowLeft className="h-4 w-4" /> All requirements</button>
          {!selected ? <div className="flex min-h-96 items-center justify-center p-6 text-center text-sm text-slate-500">Select a requirement to prepare a purchase order.</div> : <>
            <div className="flex flex-col gap-3 border-b border-blue-100 bg-blue-50/60 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div><h2 className="text-lg font-bold text-slate-950">{po.po_id ? `Purchase Order ${po.po_number || po.po_id}` : 'New Purchase Order'}</h2><p className="mt-1 text-sm text-slate-500">{form.client_name || 'Client'} · {form.vendor_name || 'Trainer/vendor'}</p></div>
              <div className="flex flex-wrap gap-2">
                <button onClick={download} disabled={!!busy || !po.po_id} className="btn-secondary text-sm">{busy === 'download' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} Download PDF</button>
                <button onClick={send} disabled={!!busy || !po.po_id || po.status === 'sent' || po.status === 'acknowledged'} className="btn-secondary text-sm">{busy === 'send' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Send</button>
              </div>
            </div>
            <div className="space-y-4 px-3 py-4 sm:px-5">
              {po.po_id && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">Saved PO · {po.status || 'draft'}. Download the saved document or send it using the buttons above.</div>}
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className="space-y-1"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">PO Number (optional)</span><input value={form.po_number} onChange={event => update('po_number', event.target.value)} disabled={!!po.po_id} placeholder="Generated automatically if blank" className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 disabled:bg-slate-50" /></label>
                <label className="space-y-1"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Vendor / Trainer</span><input value={form.vendor_name} onChange={event => update('vendor_name', event.target.value)} disabled={!!po.po_id} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 disabled:bg-slate-50" /></label>
                <label className="space-y-1"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Client</span><input value={form.client_name} onChange={event => update('client_name', event.target.value)} disabled={!!po.po_id} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 disabled:bg-slate-50" /></label>
                <label className="space-y-1"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Send to email</span><input type="email" value={form.client_email} onChange={event => update('client_email', event.target.value)} placeholder="recipient@company.com" className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" /></label>
                <label className="space-y-1 sm:col-span-2"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Billing Address</span><input value={form.billing_address} onChange={event => update('billing_address', event.target.value)} disabled={!!po.po_id} placeholder="Client billing address" className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 disabled:bg-slate-50" /></label>
                <label className="space-y-1"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Client GSTIN</span><input value={form.gstin} onChange={event => update('gstin', event.target.value)} disabled={!!po.po_id} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 disabled:bg-slate-50" /></label>
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                <h3 className="text-sm font-bold text-slate-950">Training Details</h3>
                <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {[
                    ['training_domain', 'Course / Domain'], ['training_dates', 'Training Dates'], ['duration', 'Duration'], ['mode', 'Training Mode'],
                  ].map(([key, label]) => <label key={key} className="space-y-1"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</span><input value={form[key]} onChange={event => update(key, event.target.value)} disabled={!!po.po_id} className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400 disabled:bg-slate-100" /></label>)}
                  <label className="space-y-1"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Payment Terms</span><input value={form.payment_terms} onChange={event => update('payment_terms', event.target.value)} disabled={!!po.po_id} placeholder="e.g. Net 30 days" className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400 disabled:bg-slate-100" /></label>
                </div>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-bold text-slate-950">Line Items</h3><button type="button" disabled={!!po.po_id} onClick={addItem} className="btn-secondary text-sm disabled:opacity-50"><Plus className="h-4 w-4" /> Add Item</button></div>
                <div className="mt-3 space-y-3">
                  {form.items.map((row, index) => <div key={index} className="grid min-w-0 gap-2 rounded-lg border border-slate-200 p-3 sm:grid-cols-2 sm:items-end 2xl:grid-cols-[minmax(0,1fr)_72px_110px_120px_40px]">
                    <label className="space-y-1"><span className="text-xs font-semibold text-slate-500">Description</span><input value={row.description} onChange={event => updateItem(index, 'description', event.target.value)} disabled={!!po.po_id} placeholder="Training service" className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm disabled:bg-slate-50" /></label>
                    <label className="space-y-1"><span className="text-xs font-semibold text-slate-500">Quantity</span><input type="number" min="0" step="any" value={row.quantity} onChange={event => updateItem(index, 'quantity', event.target.value)} disabled={!!po.po_id} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm disabled:bg-slate-50" /></label>
                    <label className="space-y-1"><span className="text-xs font-semibold text-slate-500">Rate (INR)</span><input type="number" min="0" step="any" value={row.rate} onChange={event => updateItem(index, 'rate', event.target.value)} disabled={!!po.po_id} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm disabled:bg-slate-50" /></label>
                    <div className="space-y-1"><span className="block text-xs font-semibold text-slate-500">Amount</span><div className="flex h-10 items-center text-sm font-bold text-slate-800">{money(lineAmount(row))}</div></div>
                    <button type="button" disabled={!!po.po_id || form.items.length === 1} onClick={() => removeItem(index)} aria-label={`Remove line ${index + 1}`} className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"><Trash2 className="h-4 w-4" /></button>
                  </div>)}
                </div>
              </div>

              <label className="block space-y-1"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Notes</span><textarea value={form.notes} onChange={event => update('notes', event.target.value)} disabled={!!po.po_id} rows={2} placeholder="Additional delivery or commercial notes" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400 disabled:bg-slate-50" /></label>
              <div className="flex flex-col gap-4 border-t border-slate-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex justify-between gap-8 text-base sm:min-w-64"><span className="font-bold text-slate-600">PO Total</span><strong className="text-slate-950">{money(po.total_amount ?? subtotal)}</strong></div>
                <button onClick={generate} disabled={!!busy || !!po.po_id} className="btn-primary text-sm disabled:opacity-60">{busy === 'generate' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />} Generate Purchase Order</button>
              </div>
            </div>
          </>}
        </section>
      </div>
    </main>
  )
}
