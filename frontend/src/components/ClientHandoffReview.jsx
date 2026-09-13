import { useState } from 'react'
import api from '../utils/api'
import toast from 'react-hot-toast'

function errorText(error) {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : detail?.message || error.message || 'Package action failed'
}

function downloadAttachment(attachment) {
  const bytes = Uint8Array.from(atob(attachment.content_base64), c => c.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: `application/${attachment.subtype}` }))
  const link = document.createElement('a')
  link.href = url
  link.download = attachment.filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function ClientHandoffReview({ requirementId, trainer, onDelivered }) {
  const [review, setReview] = useState(null)
  const [busy, setBusy] = useState(false)
  const path = `/shortlists/handoff/${encodeURIComponent(requirementId)}/${encodeURIComponent(trainer.trainer_id)}`
  const delivered = trainer.client_slots_sent && trainer.client_slots_email_id
  const labCostAttached = review?.lab_cost_attached ?? false
  const needsInput = review?.status === 'needs_input' || trainer.slot_status === 'client_handoff_needs_input'

  async function loadReview() {
    const { data } = await api.get(path)
    setReview(data)
  }

  async function openReview() {
    setBusy(true)
    try {
      try {
        await loadReview()
      } catch (error) {
        if (error.response?.status !== 404) throw error
        const { data } = await api.post('/shortlists/send-client-slots', {
          requirement_id: requirementId, trainer_id: trainer.trainer_id,
          slot_text: trainer.slot_reply_text || '',
        }, { timeout: 300000 })
        if (data.already_sent) {
          toast.success('The client handoff has already been sent')
          onDelivered?.(data)
        } else {
          await loadReview()
        }
      }
    } catch (error) {
      toast.error(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  async function act(action) {
    setBusy(true)
    try {
      const { data } = await api.post(`${path}/${action}`, { package_id: review.package_id }, { timeout: 300000 })
      if (action === 'approve') {
        toast.success(data.success ? 'Client package sent' : 'Approved; delivery is queued')
        if (data.success) onDelivered?.(data)
      } else {
        toast.success('Package rebuilt. Review this version before approving.')
      }
      await loadReview()
    } catch (error) {
      toast.error(errorText(error))
      // Approval persists even if the first send fails; show the saved status.
      try { await loadReview() } catch { setReview(null) }
    } finally {
      setBusy(false)
    }
  }

  return <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
    <p className="text-sm font-semibold text-slate-900">
      {delivered ? 'Client package delivered' : needsInput ? 'Client handoff needs client input' : 'Client handoff is being sent automatically'}
    </p>
    <p className="mt-1 text-xs text-slate-600">{needsInput ? 'The package is prepared, but a required lab-cost input must be confirmed before delivery.' : 'The email, commercials, documents, and three interview slots are delivered automatically. Retries run automatically if needed.'}</p>
    <button type="button" disabled={busy} onClick={openReview} className="mt-2 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">
      {busy ? 'Please wait…' : 'View client package'}
    </button>
    {review && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="handoff-review-title">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <div><h2 id="handoff-review-title" className="text-lg font-bold">Client package</h2><p className="text-sm text-slate-600">{review.status === 'sent' ? 'Delivered' : review.status === 'needs_input' ? 'Waiting for required client input' : 'Delivery is automatic and retries when needed'}</p></div>
          <button type="button" onClick={() => setReview(null)} disabled={busy} className="rounded border px-3 py-1">Close</button>
        </div>
        <p className="mt-4 text-sm"><strong>To:</strong> {review.to}</p>
        <p className="mt-1 text-sm"><strong>Subject:</strong> {review.subject}</p>
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">Trainer profile attached</div>
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">Training ToC attached</div>
          <div className={`rounded-lg border p-3 text-sm ${labCostAttached ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
            {labCostAttached ? 'Lab-cost estimate attached' : 'Lab cost was not requested'}
          </div>
        </div>
        <pre className="my-4 whitespace-pre-wrap rounded-lg bg-slate-50 p-4 font-sans text-sm text-slate-800">{review.body}</pre>
        <h3 className="text-sm font-bold">Documents</h3>
        <ul className="my-2 space-y-2">{review.attachments.map(attachment => <li key={attachment.filename}><button type="button" onClick={() => downloadAttachment(attachment)} className="text-sm text-blue-700 underline">Download {attachment.filename}</button></li>)}</ul>
        {review.last_error && <p role="alert" className="my-3 rounded bg-amber-50 p-3 text-sm text-amber-900">{review.status === 'needs_input' ? 'Action required: ' : 'Delivery delayed: '}{review.last_error}</p>}
      </div>
    </div>}
  </div>
}
