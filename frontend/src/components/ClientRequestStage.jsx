import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import api from '../utils/api'

const stages = [
  ['received', 'Request received'],
  ['matching', 'Finding trainers'],
  ['team_review', 'TrainerSync team review'],
  ['client_review', 'Client review'],
  ['confirmed', 'Confirmed'],
  ['closed', 'Closed'],
]

export default function ClientRequestStage({ requirement }) {
  const requirementId = requirement?.requirement_id
  const [stage, setStage] = useState(requirement?.client_portal_stage || 'received')
  const [note, setNote] = useState(requirement?.client_portal_stage_note || '')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setStage(requirement?.client_portal_stage || 'received')
    setNote(requirement?.client_portal_stage_note || '')
  }, [requirementId, requirement?.client_portal_stage, requirement?.client_portal_stage_note])

  if (!requirementId || requirement?.client_portal_source !== true) return null

  const save = async () => {
    setBusy(true)
    try {
      await api.patch(`/client-portal/requests/${encodeURIComponent(requirementId)}/stage`, { stage, note })
      toast.success('Client request tracking updated')
    } catch (error) {
      toast.error(error.message || 'Could not update client request tracking')
    } finally {
      setBusy(false)
    }
  }

  return <section className="mb-3 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
    <h3 className="text-sm font-bold text-indigo-950">Client portal tracking</h3>
    <p className="mt-1 text-xs text-indigo-800">This status and note are visible to the client in their portal.</p>
    <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,220px)_1fr_auto] sm:items-end">
      <label className="space-y-1">
        <span className="text-xs font-semibold text-slate-600">Request status</span>
        <select value={stage} onChange={event => setStage(event.target.value)} className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm">
          {stages.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <label className="space-y-1">
        <span className="text-xs font-semibold text-slate-600">Client update</span>
        <input value={note} onChange={event => setNote(event.target.value)} maxLength={1000} placeholder="Optional note for the client" className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm" />
      </label>
      <button type="button" onClick={save} disabled={busy} className="btn-primary h-10 justify-center text-sm disabled:opacity-60">{busy ? 'Saving…' : 'Save & notify client'}</button>
    </div>
  </section>
}
