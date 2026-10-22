import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { CheckCircle2, FileSearch, Loader2, RefreshCw, XCircle } from 'lucide-react'
import api from '../utils/api'

const emptyForm = {
  client_name: '', client_email: '', po_number: '', po_date: '', total_amount: '', gst_rate: '',
  billing_address: '', gstin: '', payment_terms: '', description: 'Professional training services', due_date: '',
}

function formFor(item = {}) {
  const fields = item.extracted_po_fields || {}
  return {
    ...emptyForm,
    client_name: fields.client_name || item.client_name || '',
    client_email: item.client_email || '',
    po_number: fields.po_number || '',
    po_date: fields.po_date || '',
    total_amount: fields.total_amount || '',
    gst_rate: fields.gst_rate || '',
    billing_address: fields.billing_address || '',
    gstin: fields.gstin || '',
    payment_terms: fields.payment_terms || '',
    due_date: fields.due_date || '',
    description: fields.description || (item.requirement_id ? `Training services for ${item.requirement_id}` : emptyForm.description),
  }
}

export default function FinanceApprovals() {
  const [items, setItems] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const selected = useMemo(() => items.find(item => item.finance_id === selectedId) || items.find(item => item.status === 'pending_human_approval') || items[0] || null, [items, selectedId])
  const extraction = selected?.purchase_order_extraction || {}
  const fields = selected?.extracted_po_fields || {}

  const load = async () => {
    setLoading(true)
    try {
      const response = await api.get('/finance/approvals')
      const rows = response.data.approvals || []
      setItems(rows)
      setSelectedId(current => rows.some(item => item.finance_id === current) ? current : rows.find(item => item.status === 'pending_human_approval')?.finance_id || rows[0]?.finance_id || '')
    } catch (error) {
      toast.error(error.message || 'Could not load finance approvals')
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { setForm(formFor(selected || {})) }, [selected?.finance_id])

  const update = (key, value) => setForm(current => ({ ...current, [key]: value }))

  const openSource = async () => {
    if (!selected) return
    const preview = window.open('about:blank', '_blank')
    setBusy('source')
    try {
      const response = await api.get(`/finance/approvals/${selected.finance_id}/source-document`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }))
      if (preview) preview.location.href = url
      else toast.error('Allow pop-ups to open the source PDF')
      window.setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (error) { preview?.close(); toast.error(error.message || 'Source PDF is unavailable') }
    finally { setBusy('') }
  }

  const approve = async () => {
    if (!selected) return
    if (!form.po_number.trim() || Number(form.total_amount) <= 0) return toast.error('Confirm the PO number and total amount from the source document')
    setBusy('approve')
    try {
      await api.post(`/finance/approvals/${selected.finance_id}/approve-send`, {
        ...form,
        total_amount: Number(form.total_amount),
        gst_rate: Number(form.gst_rate || 0),
      })
      toast.success('Invoice created and sent to the client')
      await load()
    } catch (error) { toast.error(error.message || 'Could not approve the PO') }
    finally { setBusy('') }
  }

  const reject = async () => {
    if (!selected) return
    setBusy('reject')
    try {
      await api.post(`/finance/approvals/${selected.finance_id}/reject`, { reason: 'Rejected during finance review' })
      toast.success('Finance item rejected')
      await load()
    } catch (error) { toast.error(error.message || 'Could not reject this item') }
    finally { setBusy('') }
  }

  const input = (key, label, type = 'text') => (
    <label key={key} className="space-y-1">
      <span className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</span>
      <input type={type} value={form[key]} onChange={event => update(key, event.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" />
    </label>
  )

  return (
    <main className="min-w-0 space-y-4 animate-fade-in">
      <header className="flex flex-wrap items-end justify-between gap-3 rounded-2xl border border-blue-100 bg-white px-5 py-4 shadow-sm">
        <div><p className="text-xs font-bold uppercase tracking-wide text-blue-700">Client finance</p><h1 className="mt-1 page-title">PO PDF review</h1><p className="mt-1 text-sm text-slate-500">When the PO number and amount are read, the system creates a draft invoice and advances the pipeline. Check the extracted values against the source PDF before approving and sending it.</p></div>
        <button type="button" onClick={load} disabled={loading} className="btn-secondary text-sm"><RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} /> Refresh</button>
      </header>
      <div className="grid min-w-0 gap-4 xl:grid-cols-[310px_minmax(0,1fr)]">
        <aside className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-bold">Finance approvals <span className="ml-1 text-slate-400">{items.filter(item => item.status === 'pending_human_approval').length} pending</span></div>
          {loading ? <div className="p-5 text-sm text-slate-500">Loading approvals…</div> : items.length ? items.map(item => (
            <button key={item.finance_id} type="button" onClick={() => setSelectedId(item.finance_id)} className={clsx('block w-full border-b border-slate-100 px-4 py-3 text-left hover:bg-slate-50', item.finance_id === selected?.finance_id && 'bg-blue-50')}>
              <span className="block truncate text-sm font-semibold text-slate-900">{item.client_name || item.client_email || 'Client PO'}</span>
              <span className="mt-1 block truncate text-xs text-slate-500">{item.extracted_po_fields?.po_number || item.subject || item.finance_id}</span>
              <span className="mt-1 block text-xs text-slate-500">{item.status?.replaceAll('_', ' ')}</span>
            </button>
          )) : <div className="p-6 text-sm text-slate-500">No PO or invoice approvals yet.</div>}
        </aside>

        {!selected ? <div className="rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500">Select a finance item to review.</div> : <section className="min-w-0 space-y-4 rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><h2 className="text-lg font-bold text-slate-950">{selected.request_type === 'po_to_invoice' ? 'Client purchase order' : 'Client invoice request'}</h2><p className="mt-1 text-sm text-slate-500">{selected.subject} · {selected.client_email}</p></div>
            <button type="button" onClick={openSource} disabled={busy === 'source'} className="btn-secondary text-sm">{busy === 'source' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />} Open source PDF</button>
          </div>
          <div className={clsx('rounded-lg border p-3 text-sm', extraction.status === 'parsed' ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-amber-200 bg-amber-50 text-amber-900')}>
            PDF read status: <strong>{extraction.status || 'not processed'}</strong>{extraction.documents?.some(item => item.ocr_used) ? ' · OCR used' : ''}. Extracted values are suggestions and must be checked against the PDF.
            {fields.missing_fields?.length > 0 && <span className="block mt-1">Needs review: {fields.missing_fields.join(', ').replaceAll('_', ' ')}</span>}
          </div>
          {selected.attachment_names?.length > 0 && <p className="text-xs text-slate-500">Attachments: {selected.attachment_names.join(', ')}</p>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {input('client_name', 'Client name')}{input('client_email', 'Client email', 'email')}{input('po_number', 'PO number')}{input('po_date', 'PO date')}{input('total_amount', 'PO total amount', 'number')}{input('gst_rate', 'GST rate %', 'number')}{input('gstin', 'Client GSTIN')}{input('payment_terms', 'Payment terms')}{input('due_date', 'Invoice due date')}
            <label className="space-y-1 sm:col-span-2 lg:col-span-3"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Billing address</span><textarea rows={2} value={form.billing_address} onChange={event => update('billing_address', event.target.value)} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400" /></label>
            <label className="space-y-1 sm:col-span-2 lg:col-span-3"><span className="text-xs font-bold uppercase tracking-wide text-slate-500">Invoice description</span><input value={form.description} onChange={event => update('description', event.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" /></label>
          </div>
          <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 pt-4">
            <button type="button" onClick={reject} disabled={!!busy || selected.status !== 'pending_human_approval'} className="btn-secondary text-sm"><XCircle className="h-4 w-4" /> Reject</button>
            <button type="button" onClick={approve} disabled={!!busy || selected.status !== 'pending_human_approval'} className="btn-primary text-sm">{busy === 'approve' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Approve and send invoice</button>
          </div>
        </section>}
      </div>
    </main>
  )
}
