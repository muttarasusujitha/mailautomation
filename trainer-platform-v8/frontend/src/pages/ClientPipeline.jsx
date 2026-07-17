import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  Download,
  FileText,
  IndianRupee,
  Loader2,
  Mail,
  MessageSquareText,
  ReceiptText,
  RefreshCw,
  Search,
  Send,
  UserRoundCheck,
  X,
} from 'lucide-react'
import api from '../utils/api'

const STAGES = [
  ['client_request', 'Request In', 'Received from client'],
  ['calhan_reply', 'Reply Out', 'Clahan sent'],
  ['client_slots', 'Slots Out', 'Slots sent'],
  ['client_slot_reply', 'Slot In', 'Client replied'],
  ['client_toc_details_request', 'TOC Info Out', 'Details asked'],
  ['client_budget_revision_request', 'Budget Out', 'Revision asked'],
  ['client_po_request', 'PO Out', 'PO requested'],
  ['client_po', 'PO In', 'PO received'],
  ['invoice', 'Invoice Out', 'Invoice sent'],
]

function fmtDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function money(value) {
  const num = Number(value || 0)
  if (!num) return '-'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(num)
}

function clientName(item = {}) {
  return item.client?.company || item.client?.name || item.client_company || item.requirement?.client_company || item.requirement?.client_name || 'Client'
}

function clientEmail(item = {}) {
  return item.client?.email || item.client_email || item.requirement?.client_email || ''
}

function matchesPipelineItem(item = {}, query = '') {
  const text = [
    item.requirement_id,
    item.domain,
    item.client?.name,
    item.client?.company,
    item.client?.email,
    item.client_name,
    item.client_company,
    item.client_email,
    item.selected_trainer?.name,
    item.selected_trainer?.email,
    item.last_preview,
    item.job_title,
    item.technology_needed,
    item.status,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return text.includes(query.toLowerCase())
}

function msgTone(direction) {
  if (direction === 'received') return 'border-slate-200 bg-white text-slate-800'
  if (direction === 'sent') return 'border-blue-200 bg-blue-600 text-white'
  return 'border-emerald-200 bg-emerald-50 text-emerald-900'
}

function msgAlign(direction) {
  if (direction === 'received') return 'mr-auto'
  return 'ml-auto'
}

function msgSpeaker(message = {}) {
  return message.direction === 'received' ? 'Client' : 'Clahan'
}

function cleanConversationBody(value = '') {
  const text = String(value || '').replace(/\r\n/g, '\n')
  const quoteMarkers = [
    /\nOn .+ wrote:\s*$/im,
    /\nOn .+\n.+wrote:\s*$/im,
    /\nFrom:\s.+$/im,
    /\n-----Original Message-----/im,
    /\n_{5,}\s*$/m,
  ]
  const cutAt = quoteMarkers
    .map(pattern => {
      const match = text.match(pattern)
      return match?.index ?? -1
    })
    .filter(index => index >= 0)
    .sort((a, b) => a - b)[0]
  const currentMessage = cutAt >= 0 ? text.slice(0, cutAt) : text
  return currentMessage
    .split('\n')
    .filter(line => !line.trim().startsWith('>'))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function clientMailStages(item = {}) {
  const messages = item.messages || []
  const has = predicate => messages.some(predicate)
  const sent = (...types) => has(m => m.direction === 'sent' && types.includes(m.type))
  const received = (...types) => has(m => m.direction === 'received' && types.includes(m.type))
  const selected = Boolean(item.selected_trainer?.name || item.requirement?.selected_trainer_id)
  const invoice = item.invoice || {}
  const poRequested = item.requirement?.po_request_status === 'requested' || item.requirement?.po_requested_at || sent('client_po_request')
  const invoiceSent = invoice.status === 'sent' || item.requirement?.invoice_status === 'sent' || has(m => m.type === 'invoice' && m.status === 'sent')

  return {
    client_request: received('client_request') || item.stages?.client_request === 'done' ? 'done' : 'pending',
    calhan_reply: sent('calhan_reply') ? 'done' : received('client_request') ? 'ready' : 'locked',
    client_slots: sent('client_slots') ? 'done' : selected ? 'ready' : 'locked',
    client_slot_reply: received('client_slot_reply', 'client_confirmation') ? 'done' : sent('client_slots') ? 'pending' : 'locked',
    client_toc_details_request: sent('client_toc_details_request', 'client_toc') ? 'done' : selected ? 'ready' : 'locked',
    client_budget_revision_request: sent('client_budget_revision_request') ? 'done' : selected ? 'ready' : 'locked',
    client_po_request: poRequested ? 'done' : selected ? 'ready' : 'locked',
    client_po: received('client_po') || item.stages?.client_po === 'done' ? 'done' : poRequested ? 'pending' : 'locked',
    invoice: invoiceSent ? 'done' : item.invoice?.invoice_id ? 'ready' : item.stages?.client_po === 'done' ? 'ready' : 'locked',
  }
}

function progressCount(item = {}) {
  return Object.values(clientMailStages(item)).filter(value => value === 'done').length
}

function progressPercent(item = {}) {
  return Math.round((progressCount(item) / STAGES.length) * 100)
}

function currentStageLabel(item = {}) {
  const stages = clientMailStages(item)
  const pending = STAGES.find(([key]) => stages[key] !== 'done')
  return pending ? pending[1] : 'Completed'
}

function SummaryTile({ label, value, sub, tone = 'slate' }) {
  const tones = {
    blue: 'border-blue-200 bg-blue-50 text-blue-700',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-700',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }
  return (
    <div className={clsx('rounded-lg border p-3', tones[tone] || tones.slate)}>
      <p className="text-[11px] font-bold uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-1 truncate text-lg font-black">{value}</p>
      {sub && <p className="mt-0.5 truncate text-xs opacity-70">{sub}</p>}
    </div>
  )
}

function StageRail({ item }) {
  const stages = clientMailStages(item)
  return (
    <div className="overflow-x-auto pb-2 [scrollbar-gutter:stable]">
      <div className="flex min-w-max items-start gap-0">
      {STAGES.map(([key, title, sub], index) => {
        const state = stages[key] || 'pending'
        const done = state === 'done'
        const ready = state === 'ready'
        const locked = state === 'locked'
        return (
          <div key={key} className="flex items-start">
            <div className="flex w-[108px] flex-col items-center text-center">
              <span className={clsx(
                'flex h-7 w-7 items-center justify-center rounded-full border text-xs font-black shadow-sm',
                done ? 'border-blue-500 bg-blue-600 text-white' :
                  ready ? 'border-emerald-300 bg-emerald-50 text-emerald-700' :
                    locked ? 'border-slate-200 bg-slate-100 text-slate-400' :
                      'border-amber-300 bg-amber-50 text-amber-700'
              )}>
                {done ? <CheckCircle2 className="h-4 w-4" /> : index + 1}
              </span>
              <p className={clsx('mt-1.5 text-[11px] font-black', done ? 'text-blue-700' : ready ? 'text-emerald-700' : locked ? 'text-slate-400' : 'text-slate-600')}>
                {title}
              </p>
              <p className="mt-0.5 max-w-[96px] text-[10px] leading-3 text-slate-400">{sub}</p>
            </div>
            {index < STAGES.length - 1 && (
              <div className={clsx(
                'mt-3 h-0.5 w-10 rounded-full',
                done ? 'bg-blue-500' : 'bg-slate-200'
              )} />
            )}
          </div>
        )
      })}
      </div>
    </div>
  )
}

function PoInvoiceModal({ item, onClose, onDone }) {
  const req = item?.requirement || {}
  const trainer = item?.selected_trainer || {}
  const [form, setForm] = useState({
    client_po_number: item?.client_po?.client_po_number || req.client_po_number || '',
    client_po_date: item?.client_po?.client_po_date || req.client_po_date || '',
    total_amount: item?.client_po?.total_amount || req.budget_total || '',
    gst_rate: item?.client_po?.gst_rate || 18,
    client_gstin: item?.client_po?.client_gstin || '',
    client_billing_address: item?.client_po?.client_billing_address || '',
    client_po_notes: '',
  })
  const [busy, setBusy] = useState('')

  const update = (key, value) => setForm(prev => ({ ...prev, [key]: value }))

  const clientEmailValue = clientEmail(item)
  const clientNameValue = clientName(item)
  const generate = async () => {
    if (!clientEmailValue) return toast.error('Client email is missing')
    if (!form.client_po_number.trim()) return toast.error('Client PO number is required')
    if (!Number(form.total_amount || 0)) return toast.error('Client PO amount is required')
    setBusy('generate')
    try {
      const amount = Number(form.total_amount || 0)
      const items = [{
        description: item.domain || 'Training',
        hsn_sac: '999293',
        quantity: Number(req.duration_days || 1) || 1,
        rate: amount && Number(req.duration_days || 1) ? Math.round(amount / Number(req.duration_days || 1)) : amount,
        amount,
      }]

      const res = await api.post(`/requirements/${item.requirement_id}/client-po/generate-invoice`, {
        trainer_id: trainer.trainer_id,
        client_email: clientEmailValue,
        client_name: clientNameValue,
        client_po_number: form.client_po_number,
        client_po_date: form.client_po_date,
        total_amount: amount,
        gst_rate: Number(form.gst_rate || 18),
        client_gstin: form.client_gstin,
        client_billing_address: form.client_billing_address,
        client_po_notes: form.client_po_notes,
        technology: item.domain,
        course_name: item.domain,
        duration_days: req.duration_days,
        mode: req.mode,
        items,
      })
      toast.success(`Invoice ${res.data.invoice?.invoice_number} generated from client PO`)
      onDone?.()
      onClose()
    } catch (e) {
      toast.error(e.message || 'Invoice generation failed')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5">
          <div>
            <h3 className="text-lg font-bold text-slate-950">Generate Invoice From Client PO</h3>
            <p className="mt-1 text-sm text-slate-500">{item.domain} · {item.client?.email || 'Client email missing'}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid gap-4 p-5 md:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Client PO Number</span>
            <input value={form.client_po_number} onChange={e => update('client_po_number', e.target.value)} className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Client PO Date</span>
            <input type="date" value={form.client_po_date} onChange={e => update('client_po_date', e.target.value)} className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">PO Amount</span>
            <input type="number" value={form.total_amount} onChange={e => update('total_amount', e.target.value)} className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">GST %</span>
            <input type="number" value={form.gst_rate} onChange={e => update('gst_rate', e.target.value)} className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" />
          </label>
          <label className="space-y-1 md:col-span-2">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Client GSTIN</span>
            <input value={form.client_gstin} onChange={e => update('client_gstin', e.target.value)} className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" />
          </label>
          <label className="space-y-1 md:col-span-2">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Billing Address</span>
            <textarea value={form.client_billing_address} onChange={e => update('client_billing_address', e.target.value)} rows={3} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400" />
          </label>
          <label className="space-y-1 md:col-span-2">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">PO Notes</span>
            <textarea value={form.client_po_notes} onChange={e => update('client_po_notes', e.target.value)} rows={2} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400" />
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 p-5">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={generate} disabled={!!busy} className="btn-primary text-sm">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ReceiptText className="h-4 w-4" />}
            Generate Invoice
          </button>
        </div>
      </div>
    </div>
  )
}

function RequirementListItem({ item, active, onClick }) {
  const doneCount = progressCount(item)
  const percent = progressPercent(item)
  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full rounded-xl border p-3 text-left transition hover:border-blue-200 hover:bg-white hover:shadow-sm',
        active ? 'border-blue-300 bg-white shadow-md ring-2 ring-blue-500/10' : 'border-slate-200 bg-white/80'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={clsx(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-xs font-black',
            active ? 'bg-blue-600 text-white' : 'bg-blue-50 text-blue-700'
          )}>
            {doneCount}/{STAGES.length}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-slate-950">{item.domain}</p>
            <p className="mt-1 truncate text-xs text-slate-500">{item.client?.name || item.client?.email || 'Client'}</p>
          </div>
        </div>
        <span className={clsx(
          'rounded-full border px-2 py-1 text-xs font-bold',
          percent >= 85 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : percent >= 45 ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-amber-200 bg-amber-50 text-amber-700'
        )}>
          {percent}%
        </span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-blue-600" style={{ width: `${percent}%` }} />
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="truncate text-xs font-bold text-slate-600">{currentStageLabel(item)}</p>
        {item.selected_trainer?.name && <span className="shrink-0 text-xs font-bold text-emerald-600">Selected</span>}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-[11px] font-bold text-blue-700">
          {item.requirement_id}
        </span>
        {item.shortlist_count > 0 && (
          <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] font-bold text-violet-700">
            {item.shortlist_count} matched
          </span>
        )}
      </div>
      {item.selected_trainer?.name && (
        <p className="mt-3 truncate text-xs font-semibold text-emerald-700">
          Trainer: {item.selected_trainer.name}
        </p>
      )}
      <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500">{item.last_preview || 'No client conversation yet.'}</p>
    </button>
  )
}

export default function ClientPipeline() {
  const [items, setItems] = useState([])
  const [domains, setDomains] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [domain, setDomain] = useState('')
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [sendingInvoice, setSendingInvoice] = useState(false)
  const [poModalOpen, setPoModalOpen] = useState(false)

  const selected = useMemo(
    () => items.find(item => item.requirement_id === selectedId) || items[0] || null,
    [items, selectedId]
  )

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await api.get('/client-pipeline', {
        params: { limit: 150 },
      })
      const rawItems = (res.data.pipeline || []).map(item => ({
        ...item,
        domain: item.domain || item.technology_needed || item.technology_key || 'Training',
      }))
      const allDomains = res.data.domains || Array.from(new Set(rawItems.map(item => item.domain).filter(Boolean)))
      const filteredItems = rawItems.filter(item => (
        (!q || matchesPipelineItem(item, q)) &&
        (!domain || item.domain === domain)
      ))
      setItems(filteredItems)
      setDomains(allDomains)
      if (!filteredItems.some(item => item.requirement_id === selectedId)) {
        setSelectedId(filteredItems[0]?.requirement_id || '')
      }
    } catch (e) {
      toast.error(e.message || 'Could not load client pipeline')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => load(false), 250)
    return () => clearTimeout(timer)
  }, [q, domain])

  const syncGmail = async () => {
    setSyncing(true)
    try {
      const res = await api.post('/gmail/sync-now?limit=100')
      if (res.data?.queued) {
        toast.success(res.data?.message || 'Gmail sync started. Refreshing shortly.')
        window.setTimeout(() => load(true), 6000)
        return
      }
      toast.success(`Gmail checked: ${res.data?.processed_count || 0} new mail(s) processed`)
      await load(true)
    } catch (e) {
      toast.error(e.message || 'Gmail sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const downloadInvoice = async () => {
    if (!selected?.invoice?.invoice_id) return
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
    }
  }

  const sendInvoice = async () => {
    if (!selected?.invoice?.invoice_id) return
    setSendingInvoice(true)
    try {
      await api.post(`/invoices/${selected.invoice.invoice_id}/send`, {})
      toast.success(`Invoice sent to ${clientEmail(selected)}`)
      await load(true)
    } catch (e) {
      toast.error(e.message || 'Invoice send failed')
    } finally {
      setSendingInvoice(false)
    }
  }

  const domainCounts = useMemo(() => {
    const counts = {}
    items.forEach(item => { counts[item.domain] = (counts[item.domain] || 0) + 1 })
    return counts
  }, [items])

  return (
    <div className="min-w-0 space-y-5 overflow-x-hidden animate-fade-in">
      {poModalOpen && selected && (
        <PoInvoiceModal item={selected} onClose={() => setPoModalOpen(false)} onDone={() => load(true)} />
      )}

      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-bold uppercase tracking-wide text-blue-700 shadow-sm">
            <BriefcaseBusiness className="h-3.5 w-3.5" /> Client Pipeline
          </div>
          <h1 className="mt-3 page-title">Client Match Pipeline</h1>
          <p className="mt-1 text-sm text-slate-500">
            Shortlist-style client workflow: requirement, selected trainer, PO, invoice, and client reply in one clean board.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={syncGmail} disabled={syncing} className="btn-secondary text-sm">
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
            Check Gmail for PO
          </button>
          <button onClick={() => load(true)} className="btn-secondary text-sm">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="flex items-center gap-2 overflow-x-auto pb-1 [scrollbar-gutter:stable]">
          <button
            onClick={() => setDomain('')}
            className={clsx(
              'shrink-0 rounded-xl border px-3 py-2 text-sm font-bold',
              !domain ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            )}
          >
            All Domains <span className="ml-1 opacity-75">{items.length}</span>
          </button>
          {domains.map(item => (
            <button
              key={item}
              onClick={() => setDomain(item)}
              className={clsx(
                'shrink-0 rounded-xl border px-3 py-2 text-sm font-semibold',
                domain === item ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
              )}
            >
              {item} <span className="ml-1 text-xs opacity-60">{domainCounts[item] || 0}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={q}
              onChange={e => setQ(e.target.value)}
              placeholder="Search client, trainer, PO..."
              className="h-11 w-full rounded-full border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:bg-white"
            />
          </div>
          <div className="mt-4 flex items-center justify-between">
            <p className="text-sm font-bold text-slate-950">{items.length} client match{items.length === 1 ? '' : 'es'}</p>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
          </div>
          <div className="mt-3 max-h-[72vh] space-y-3 overflow-y-auto pr-1 [scrollbar-gutter:stable]">
            {loading ? (
              Array.from({ length: 5 }).map((_, index) => <div key={index} className="h-32 animate-pulse rounded-lg bg-slate-100" />)
            ) : items.length ? (
              items.map(item => (
                <RequirementListItem
                  key={item.requirement_id}
                  item={item}
                  active={selected?.requirement_id === item.requirement_id}
                  onClick={() => setSelectedId(item.requirement_id)}
                />
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">
                No client pipeline found for this filter.
              </div>
            )}
          </div>
        </aside>

        <section className="min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm">
          {!selected ? (
            <div className="flex min-h-[620px] items-center justify-center text-sm text-slate-500">
              Select a domain and client process.
            </div>
          ) : (
            <div className="flex min-h-[720px] min-w-0 flex-col">
              <header className="border-b border-slate-200 p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">{selected.domain}</span>
                      <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">{selected.requirement_id}</span>
                    </div>
                    <h2 className="mt-3 text-xl font-bold text-slate-950">{clientName(selected)}</h2>
                    <p className="mt-1 text-sm text-slate-500">{clientEmail(selected) || 'Client email missing'}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => setPoModalOpen(true)} className="btn-secondary text-sm">
                      <ReceiptText className="h-4 w-4" /> Client PO / Invoice
                    </button>
                    {selected.invoice?.invoice_id && (
                      <>
                        <button onClick={downloadInvoice} className="btn-secondary text-sm">
                          <Download className="h-4 w-4" /> Invoice
                        </button>
                        <button onClick={sendInvoice} disabled={sendingInvoice || selected.invoice?.status === 'sent'} className="btn-primary text-sm">
                          {sendingInvoice ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                          {selected.invoice?.status === 'sent' ? 'Invoice Sent' : 'Send Invoice'}
                        </button>
                      </>
                    )}
                  </div>
                </div>
                <div className="mt-5 grid gap-3 md:grid-cols-4">
                  <SummaryTile label="Pipeline" value={`${progressPercent(selected)}%`} sub={currentStageLabel(selected)} tone="blue" />
                  <SummaryTile label="AI Matches" value={selected.shortlist_count || 0} sub="shortlisted trainers" tone="slate" />
                  <SummaryTile label="Trainer" value={selected.selected_trainer?.name || 'Pending'} sub={selected.selected_trainer?.email || 'selection status'} tone={selected.selected_trainer?.name ? 'emerald' : 'amber'} />
                  <SummaryTile label="Commercials" value={money(selected.invoice?.commercials?.grand_total || selected.client_po?.grand_total || selected.client_po?.total_amount)} sub={selected.invoice?.invoice_number || selected.client_po?.client_po_number || 'PO / invoice'} tone={selected.invoice?.invoice_id ? 'emerald' : 'slate'} />
                </div>
                <div className="mt-5">
                  <StageRail item={selected} />
                </div>
              </header>

              <div className="flex min-w-0 flex-1 flex-col gap-5 p-5">
                <div className="grid min-w-0 gap-4 xl:grid-cols-3">
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-bold uppercase tracking-wide text-emerald-700">Selected Trainer Match</p>
                      <span className="rounded-full bg-white px-2 py-1 text-[11px] font-bold text-emerald-700">
                        {selected.selected_trainer?.name ? 'Matched' : 'Waiting'}
                      </span>
                    </div>
                    <div className="mt-4 flex items-start gap-3">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-emerald-600 text-white">
                        <UserRoundCheck className="h-5 w-5" />
                      </span>
                      <div className="min-w-0">
                        <p className="font-bold text-emerald-950">{selected.selected_trainer?.name || 'Not selected yet'}</p>
                        <p className="mt-1 break-words text-xs text-emerald-700">{selected.selected_trainer?.email || 'Client selection not confirmed yet'}</p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Client PO</p>
                      <FileText className="h-4 w-4 text-blue-500" />
                    </div>
                    <div className="mt-3 space-y-2 text-sm">
                      <p className="flex justify-between gap-3"><span className="text-slate-500">PO Number</span><strong className="break-words text-right text-slate-900">{selected.client_po?.client_po_number || selected.requirement?.client_po_number || '-'}</strong></p>
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Status</span><strong className="text-right capitalize text-slate-900">{(selected.client_po?.status || selected.requirement?.client_po_status || 'pending').replaceAll('_', ' ')}</strong></p>
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Amount</span><strong className="text-right text-slate-900">{money(selected.client_po?.grand_total || selected.client_po?.total_amount)}</strong></p>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Invoice</p>
                      <ReceiptText className="h-4 w-4 text-emerald-500" />
                    </div>
                    <div className="mt-3 space-y-2 text-sm">
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Number</span><strong className="break-words text-right text-slate-900">{selected.invoice?.invoice_number || '-'}</strong></p>
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Status</span><strong className="text-right capitalize text-slate-900">{(selected.invoice?.status || selected.requirement?.invoice_status || 'pending').replaceAll('_', ' ')}</strong></p>
                      <p className="flex justify-between gap-3"><span className="text-slate-500">Grand Total</span><strong className="text-right text-slate-900">{money(selected.invoice?.commercials?.grand_total)}</strong></p>
                    </div>
                  </div>
                </div>

                <div className="min-w-0 rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
                  <div className="flex items-center justify-between border-b border-slate-200 bg-white p-4">
                    <div>
                      <p className="text-sm font-bold text-slate-950">Client and Clahan Conversation</p>
                      <p className="mt-0.5 text-xs text-slate-500">Requirement, slot, PO and invoice messages in a chat-style timeline.</p>
                    </div>
                    <MessageSquareText className="h-5 w-5 text-slate-400" />
                  </div>
                  <div className="max-h-[680px] space-y-4 overflow-y-auto bg-slate-100/70 p-4 [scrollbar-gutter:stable]">
                    {selected.messages?.length ? selected.messages.map((message, index) => (
                      <div
                        key={`${message.type}-${index}`}
                        className={clsx(
                          'min-w-0 max-w-[82%] rounded-2xl border p-4 shadow-sm',
                          message.direction === 'received' ? 'rounded-bl-sm' : 'rounded-br-sm',
                          msgAlign(message.direction),
                          msgTone(message.direction)
                        )}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            {message.type === 'invoice' ? <IndianRupee className={clsx('h-4 w-4', message.direction === 'sent' ? 'text-white' : 'text-emerald-600')} /> : message.type === 'client_po' ? <FileText className={clsx('h-4 w-4', message.direction === 'sent' ? 'text-white' : 'text-blue-600')} /> : <Mail className={clsx('h-4 w-4', message.direction === 'sent' ? 'text-white' : 'text-slate-500')} />}
                            <p className={clsx('text-sm font-bold', message.direction === 'sent' ? 'text-white' : 'text-slate-950')}>
                              {msgSpeaker(message)} · {message.label}
                            </p>
                          </div>
                          <span className={clsx('inline-flex items-center gap-1 text-xs font-semibold', message.direction === 'sent' ? 'text-blue-100' : 'text-slate-400')}>
                            <Clock3 className="h-3.5 w-3.5" /> {fmtDate(message.at)}
                          </span>
                        </div>
                        {message.subject && <p className={clsx('mt-2 break-words text-sm font-semibold [overflow-wrap:anywhere]', message.direction === 'sent' ? 'text-white' : 'text-slate-800')}>{message.subject}</p>}
                        <pre className={clsx('mt-2 max-w-full whitespace-pre-wrap break-words font-sans text-sm leading-6 [overflow-wrap:anywhere]', message.direction === 'sent' ? 'text-blue-50' : 'text-slate-600')}>{cleanConversationBody(message.body) || 'No body captured.'}</pre>
                      </div>
                    )) : (
                      <div className="rounded-lg border border-dashed border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
                        No client conversation captured yet. Click Check Gmail for PO after the client replies.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
