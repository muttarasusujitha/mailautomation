import { useEffect, useState } from 'react'
import api from '../utils/api'

export default function LabSupplierOrder({ requirementId }) {
  const [order, setOrder] = useState(null)
  const [busy, setBusy] = useState(true)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const path = '/purchase-orders/lab/' + encodeURIComponent(requirementId)

  useEffect(() => {
    let active = true
    api.get(path).then(({ data }) => {
      if (active) { setOrder(data.purchase_order); setReady(true) }
    }).catch(err => { if (active) setError(err.message) })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [path])

  const submit = async event => {
    event.preventDefault()
    const values = Object.fromEntries(new FormData(event.currentTarget))
    setBusy(true)
    setError('')
    try {
      if (order) {
        const { data } = await api.post('/purchase-orders/' + order.po_id + '/send', { to_email: order.vendor_email })
        if (!data.success) throw new Error('Supplier email delivery could not be confirmed')
        setOrder({ ...order, status: 'sent' })
      } else {
        const { data } = await api.post(path, values)
        setOrder(data.purchase_order)
      }
    } catch (err) { setError(err.message || 'Lab PO could not be processed') }
    finally { setBusy(false) }
  }

  return <form onSubmit={submit} className="mt-4 space-y-3 rounded-lg border border-slate-200 p-4">
    <h3 className="font-bold text-slate-900">Lab supplier purchase order</h3>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {ready && (order ? <p className="text-sm">{order.po_number} · {order.vendor_name} · {order.vendor_email} · ₹{Number(order.total_amount).toLocaleString('en-IN')} · {order.status}</p> :
      <div className="grid gap-2 sm:grid-cols-3">
        {[['supplier_name', 'Supplier name', 'text'], ['supplier_email', 'Supplier email', 'email'], ['purchase_cost', 'Purchase cost (INR)', 'number']].map(([name, label, type]) =>
          <label key={name} className="text-sm">{label}<input name={name} type={type} required min={type === 'number' ? '0.01' : undefined} step={type === 'number' ? '0.01' : undefined} className="mt-1 w-full rounded border border-slate-300 p-2" /></label>)}
      </div>)}
    {ready && order?.status !== 'sent' && <button disabled={busy} className="btn-secondary text-sm">{order ? 'Send PO to lab supplier' : 'Generate lab PO'}</button>}
  </form>
}
