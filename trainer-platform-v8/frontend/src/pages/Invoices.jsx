import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { Download, Loader2, Plus, ReceiptText, RefreshCw, Search, Send, Trash2 } from 'lucide-react'
import api from '../utils/api'

const TAX_OPTIONS = [
  { value: 'cgst_sgst', label: 'CGST + SGST (Intra-State)', gstRate: 18 },
  { value: 'igst', label: 'IGST (Inter-State)', gstRate: 18 },
  { value: 'none', label: 'No GST', gstRate: 0 },
]

function money(value) {
  const num = Number(value || 0)
  if (!num) return '-'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(num)
}

function toInputDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  return date.toISOString().slice(0, 10)
}

function invoiceStatus(item = {}) {
  if (item.invoice?.status === 'sent' || item.requirement?.invoice_status === 'sent') return 'Sent'
  if (item.invoice?.invoice_id) return 'Generated'
  if (item.client_po?.client_po_number || item.requirement?.client_po_number) return 'PO Received'
  if (item.selected_trainer?.trainer_id) return 'Ready'
  return 'Pending'
}

function statusClass(status) {
  if (status === 'Sent') return 'bg-emerald-50 text-emerald-700 ring-emerald-200'
  if (status === 'Generated') return 'bg-blue-50 text-blue-700 ring-blue-200'
  if (status === 'PO Received') return 'bg-blue-50 text-blue-700 ring-cyan-200'
  if (status === 'Ready') return 'bg-amber-50 text-amber-700 ring-amber-200'
  return 'bg-slate-50 text-slate-500 ring-slate-200'
}

function nextDueDate() {
  const date = new Date()
  date.setDate(date.getDate() + 30)
  return date.toISOString().slice(0, 10)
}

function defaultItem(item = {}) {
  const req = item.requirement || {}
  const po = item.client_po || {}
  const qty = Number(po.quantity || req.duration_days || 1) || 1
  const amount = Number(po.total_amount || po.grand_total || req.budget_total || 0)
  return {
    description: `${item.domain || req.technology || req.technology_needed || 'Training'} Training`,
    hsn_sac: po.hsn_sac || '999293',
    quantity: qty,
    rate: amount && qty ? Math.round(amount / qty) : '',
  }
}

function initialForm(item = {}) {
  const req = item.requirement || {}
  const po = item.client_po || {}
  const today = new Date().toISOString().slice(0, 10)
  return {
    invoice_number: item.invoice?.invoice_number || '',
    invoice_date: toInputDate(item.invoice?.issue_date) || today,
    due_date: toInputDate(item.invoice?.due_date) || nextDueDate(),
    client_name: item.client?.company || item.client?.name || req.client_company || req.client_name || '',
    client_email: item.client?.email || req.client_email || '',
    client_address: po.client_billing_address || req.client_address || '',
    client_po_number: po.client_po_number || req.client_po_number || '',
    client_pan: po.client_pan || req.client_pan || '',
    client_gstin: po.client_gstin || '',
    tax_type: Number(po.gst_rate || 18) ? 'cgst_sgst' : 'none',
    items: [defaultItem(item)],
    notes: '',
  }
}

function lineTotal(row) {
  return Number(row.quantity || 0) * Number(row.rate || 0)
}

function InvoiceRow({ item, active, onClick }) {
  const status = invoiceStatus(item)
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx('w-full border-b border-slate-100 px-4 py-3 text-left transition hover:bg-slate-50', active && 'bg-blue-50')}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-950">{item.client?.company || item.client?.name || item.client?.email || 'Client'}</p>
          <p className="mt-1 truncate text-xs text-slate-500">{item.domain || 'Training'} - {item.requirement_id}</p>
        </div>
        <span className={clsx('shrink-0 rounded-full px-2 py-1 text-[11px] font-bold ring-1', statusClass(status))}>{status}</span>
      </div>
      <p className="mt-2 truncate text-xs text-slate-500">
        {item.invoice?.invoice_number || item.client_po?.client_po_number || item.requirement?.client_po_number || 'No PO'} - {money(item.invoice?.commercials?.grand_total || item.client_po?.grand_total || item.client_po?.total_amount)}
      </p>
    </button>
  )
}

export default function Invoices() {
  const [items, setItems] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [form, setForm] = useState(initialForm())
  const [invoiceType, setInvoiceType] = useState('beulix')

  const selected = useMemo(
    () => items.find(item => item.requirement_id === selectedId) || items[0] || null,
    [items, selectedId]
  )
  const selectedTax = TAX_OPTIONS.find(item => item.value === form.tax_type) || TAX_OPTIONS[0]
  const subtotal = form.items.reduce((sum, item) => sum + lineTotal(item), 0)
  const gstRate = selectedTax.gstRate
  const gstAmount = Math.round(subtotal * (gstRate / 100))
  const grandTotal = subtotal + gstAmount

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await api.get('/client-pipeline', { params: { q: q || undefined, limit: 150 } })
      const next = (res.data.pipeline || []).map(item => ({
        ...item,
        domain: item.domain || item.technology_needed || item.technology_key || 'Training',
        client: item.client || {
          name: item.client_name || item.client_company || '',
          company: item.client_company || item.client_name || '',
          email: item.client_email || item.email || '',
        },
      }))
      setItems(next)
      if (!next.some(item => item.requirement_id === selectedId)) setSelectedId(next[0]?.requirement_id || '')
    } catch (e) {
      toast.error(e.message || 'Could not load invoices')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => load(false), 250)
    return () => clearTimeout(timer)
  }, [q])

  useEffect(() => {
    setForm(initialForm(selected || {}))
  }, [selected?.requirement_id])

  const update = (key, value) => setForm(prev => ({ ...prev, [key]: value }))
  const updateItem = (index, key, value) => setForm(prev => ({
    ...prev,
    items: prev.items.map((item, i) => i === index ? { ...item, [key]: value } : item),
  }))
  const addItem = () => setForm(prev => ({
    ...prev,
    items: [...prev.items, { description: '', hsn_sac: '999293', quantity: 1, rate: '' }],
  }))
  const removeItem = index => setForm(prev => ({
    ...prev,
    items: prev.items.length === 1 ? prev.items : prev.items.filter((_, i) => i !== index),
  }))

  const generateInvoice = async () => {
    if (!selected) return
    if (!form.client_email) return toast.error('Client email is missing')
    if (!form.client_po_number.trim()) return toast.error('PO Number is required')
    if (!subtotal) return toast.error('Add item quantity and rate before generating invoice')
    const trainer = selected.selected_trainer || {}
    setBusy('generate')
    try {
      const first = form.items[0] || {}
      const res = await api.post(`/requirements/${selected.requirement_id}/client-po/generate-invoice`, {
        invoice_number: form.invoice_number,
        invoice_date: form.invoice_date,
        due_date: form.due_date,
        invoice_type: invoiceType,
        trainer_id: trainer.trainer_id,
        client_email: form.client_email,
        client_name: form.client_name,
        client_po_number: form.client_po_number,
        client_po_date: selected.client_po?.client_po_date || selected.requirement?.client_po_date || '',
        total_amount: subtotal,
        gst_rate: gstRate,
        tax_type: selectedTax.label,
        client_gstin: form.client_gstin,
        client_pan: form.client_pan,
        client_billing_address: form.client_address,
        client_po_notes: form.notes,
        technology: form.course_name || selected.domain,
        course_name: form.course_name,
        classroom_location: form.classroom_location,
        mode_of_lecture: form.mode_of_lecture,
        contact_person: form.contact_person,
        contact_number: form.contact_number,
        hsn_sac: first.hsn_sac || '999293',
        quantity: first.quantity || 1,
        items: form.items.map(item => ({ ...item, amount: lineTotal(item) })),
      })
      toast.success(`Invoice ${res.data.invoice?.invoice_number} generated`)
      await load(true)
    } catch (e) {
      toast.error(e.message || 'Invoice generation failed')
    } finally {
      setBusy('')
    }
  }

  const downloadInvoice = async () => {
    if (!selected?.invoice?.invoice_id) return toast.error('Generate invoice first')
    setBusy('download')
    try {
      const res = await api.get(`/invoices/${selected.invoice.invoice_id}/download`, { responseType: 'blob' })
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${selected.invoice.invoice_number || 'invoice'}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(e.message || 'Invoice download failed')
    } finally {
      setBusy('')
    }
  }

  const sendInvoice = async () => {
    if (!selected?.invoice?.invoice_id) return toast.error('Generate invoice first')
    setBusy('send')
    try {
      const toEmail = form.client_email || selected.client?.email || selected.invoice?.client_email || ''
      await api.post(`/invoices/${selected.invoice.invoice_id}/send`, { to_email: toEmail })
      toast.success(`Invoice sent to ${toEmail}`)
      await load(true)
    } catch (e) {
      toast.error(e.message || 'Invoice send failed')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="min-w-0 space-y-4 animate-fade-in">
      <div className="relative overflow-hidden rounded-2xl border border-blue-100 bg-white px-5 py-4 shadow-[0_18px_55px_rgba(37,99,235,0.12)]">
        <div className="absolute right-8 top-0 h-20 w-56 rounded-full bg-blue-200/40 blur-3xl" />
        <div className="relative flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold uppercase tracking-wide text-blue-700 ring-1 ring-blue-100">
              <ReceiptText className="h-3.5 w-3.5" /> Manual Billing
            </div>
            <h1 className="mt-2 page-title">Generate Invoice</h1>
            <p className="mt-1 text-sm text-slate-500">Choose Beulix or Self Invoice format, then generate PDF.</p>
          </div>
          <button onClick={() => load(true)} className="btn-secondary text-sm" disabled={loading}>
            <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 p-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={q}
                onChange={e => setQ(e.target.value)}
                placeholder="Search client, trainer, PO..."
                className="h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none focus:border-blue-400"
              />
            </div>
            <p className="mt-3 text-sm font-bold text-slate-950">{items.length} shown</p>
          </div>
          <div className="max-h-[72vh] overflow-y-auto [scrollbar-gutter:stable]">
            {loading ? (
              Array.from({ length: 6 }).map((_, index) => <div key={index} className="mx-4 my-3 h-16 animate-pulse rounded-lg bg-slate-100" />)
            ) : items.length ? (
              items.map(item => (
                <InvoiceRow
                  key={item.requirement_id}
                  item={item}
                  active={selected?.requirement_id === item.requirement_id}
                  onClick={() => setSelectedId(item.requirement_id)}
                />
              ))
            ) : (
              <div className="p-8 text-center text-sm text-slate-500">No invoice records found.</div>
            )}
          </div>
        </aside>

        <section className="min-w-0 overflow-hidden rounded-xl border border-blue-100 bg-white shadow-[0_18px_45px_rgba(37,99,235,0.08)]">
          {!selected ? (
            <div className="flex min-h-[620px] items-center justify-center text-sm text-slate-500">Select an invoice record.</div>
          ) : (
            <div className="flex max-h-[calc(100vh-285px)] min-w-0 flex-col">
              <div className="shrink-0 border-b border-blue-100 bg-blue-50/60 px-5 py-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h2 className="text-lg font-bold text-slate-950">{invoiceType === 'murali' ? 'Self Invoice Generator' : 'Generate Beulix Invoice'}</h2>
                  <p className="mt-1 text-sm text-slate-500">{selected.client?.email || form.client_email || 'Client email missing'}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={downloadInvoice} disabled={!!busy || !selected.invoice?.invoice_id} className="btn-secondary text-sm">
                    {busy === 'download' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                    Download
                  </button>
                  <button onClick={sendInvoice} disabled={!!busy || !selected.invoice?.invoice_id || selected.invoice?.status === 'sent'} className="btn-secondary text-sm">
                    {busy === 'send' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    Send
                  </button>
                </div>
              </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 [scrollbar-gutter:stable]">
              <div className="mb-4 inline-flex rounded-xl border border-blue-100 bg-white p-1 shadow-sm">
                {[
                  ['beulix', 'Beulix Invoice'],
                  ['murali', 'Self Invoice'],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setInvoiceType(value)}
                    className={clsx(
                      'rounded-lg px-4 py-2 text-sm font-bold transition',
                      invoiceType === value ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-50'
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <label className="space-y-1">
                  <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Invoice Number</span>
                  <input value={form.invoice_number} onChange={e => update('invoice_number', e.target.value)} placeholder={invoiceType === 'murali' ? 'INV0052' : 'BLX-IN/24-25/26-9'} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                </label>
                <label className="space-y-1">
                  <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Invoice Date</span>
                  <input type="date" value={form.invoice_date} onChange={e => update('invoice_date', e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                </label>
                <label className="space-y-1">
                  <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Due Date</span>
                  <input type="date" value={form.due_date} onChange={e => update('due_date', e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                </label>
              </div>

              {invoiceType === 'murali' && (
                <div className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-white p-4 md:grid-cols-3">
                  <label className="space-y-1">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Course Name</span>
                    <input value={form.course_name || ''} onChange={e => update('course_name', e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Classroom Location</span>
                    <input value={form.classroom_location || ''} onChange={e => update('classroom_location', e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Mode of Lecture</span>
                    <input value={form.mode_of_lecture || ''} onChange={e => update('mode_of_lecture', e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                  </label>
                </div>
              )}

              <div className="mt-5 rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="text-sm font-bold text-slate-950">{invoiceType === 'murali' ? 'Company Info' : 'Client Info'}</h3>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">{invoiceType === 'murali' ? 'Company Name' : 'Client Name'}</span>
                    <input value={form.client_name} onChange={e => update('client_name', e.target.value)} placeholder="e.g. TechNova Pvt Ltd." className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">PO Number</span>
                    <input value={form.client_po_number} onChange={e => update('client_po_number', e.target.value)} placeholder="PONumber" className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                  </label>
                  <label className="space-y-1 md:col-span-2">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Address</span>
                    <textarea value={form.client_address} onChange={e => update('client_address', e.target.value)} placeholder="Billing address" rows={2} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">{invoiceType === 'murali' ? 'PAN Number' : 'PAN'}</span>
                    <input value={form.client_pan} onChange={e => update('client_pan', e.target.value)} placeholder="e.g. AAAAA9999A" className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">{invoiceType === 'murali' ? 'GST Number' : 'GST'}</span>
                    <input value={form.client_gstin} onChange={e => update('client_gstin', e.target.value)} placeholder="e.g. 22AAAAA0000A1Z5" className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                  </label>
                  {invoiceType === 'murali' && (
                    <>
                      <label className="space-y-1">
                        <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Contact Person</span>
                        <input value={form.contact_person || ''} onChange={e => update('contact_person', e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Contact Number</span>
                        <input value={form.contact_number || ''} onChange={e => update('contact_number', e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10" />
                      </label>
                    </>
                  )}
                  {invoiceType === 'beulix' && <label className="space-y-1 md:col-span-2">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Tax Type</span>
                    <select value={form.tax_type} onChange={e => update('tax_type', e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10">
                      {TAX_OPTIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
                    </select>
                  </label>}
                </div>
              </div>

              <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-bold text-slate-950">Item Details</h3>
                  <button type="button" onClick={addItem} className="btn-secondary text-sm">
                    <Plus className="h-4 w-4" /> {invoiceType === 'murali' ? 'Add Another Item' : 'Add Item'}
                  </button>
                </div>
                <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
                  <table className={clsx('w-full text-sm', invoiceType === 'murali' ? 'min-w-[620px]' : 'min-w-[760px]')}>
                    <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-3 py-2 text-left">Description</th>
                        {invoiceType === 'beulix' && <th className="px-3 py-2 text-left">HSN/SAC</th>}
                        <th className="px-3 py-2 text-right">Qty</th>
                        <th className="px-3 py-2 text-right">{invoiceType === 'murali' ? 'Price' : 'Rate'}</th>
                        <th className="px-3 py-2 text-right">Amount</th>
                        <th className="px-3 py-2 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {form.items.map((item, index) => (
                        <tr key={index}>
                          <td className="px-3 py-2">
                            <input value={item.description} onChange={e => updateItem(index, 'description', e.target.value)} placeholder={invoiceType === 'murali' ? 'e.g. Python Training' : ''} className="h-9 w-full rounded-md border border-slate-200 px-2 outline-none focus:border-blue-400" />
                          </td>
                          {invoiceType === 'beulix' && <td className="px-3 py-2">
                            <input value={item.hsn_sac} onChange={e => updateItem(index, 'hsn_sac', e.target.value)} className="h-9 w-28 rounded-md border border-slate-200 px-2 outline-none focus:border-blue-400" />
                          </td>}
                          <td className="px-3 py-2 text-right">
                            <input type="number" value={item.quantity} onChange={e => updateItem(index, 'quantity', e.target.value)} className="h-9 w-20 rounded-md border border-slate-200 px-2 text-right outline-none focus:border-blue-400" />
                          </td>
                          <td className="px-3 py-2 text-right">
                            <input type="number" value={item.rate} onChange={e => updateItem(index, 'rate', e.target.value)} className="h-9 w-28 rounded-md border border-slate-200 px-2 text-right outline-none focus:border-blue-400" />
                          </td>
                          <td className="px-3 py-2 text-right font-semibold text-slate-900">{money(lineTotal(item))}</td>
                          <td className="px-3 py-2 text-right">
                            <button type="button" onClick={() => removeItem(index)} className="inline-flex h-9 w-9 items-center justify-center rounded-md text-slate-400 hover:bg-red-50 hover:text-red-600">
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="mt-5 flex flex-col gap-4 border-t border-slate-200 pt-5 lg:flex-row lg:items-end lg:justify-between">
                <div className="w-full max-w-sm space-y-2 text-sm">
                  <p className="flex justify-between"><span className="text-slate-500">Subtotal</span><strong>{money(subtotal)}</strong></p>
                  <p className="flex justify-between"><span className="text-slate-500">{selectedTax.label}</span><strong>{money(gstAmount)}</strong></p>
                  <p className="flex justify-between border-t border-slate-200 pt-2 text-base"><span className="font-bold text-slate-700">Grand Total</span><strong>{money(grandTotal)}</strong></p>
                </div>
                <button onClick={generateInvoice} disabled={!!busy} className="btn-primary text-sm">
                  {busy === 'generate' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ReceiptText className="h-4 w-4" />}
                  {invoiceType === 'murali' ? 'Generate Self Invoice' : 'Generate Beulix Invoice'}
                </button>
              </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
