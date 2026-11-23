import { useEffect, useMemo, useState } from 'react'
import { Bus, Car, ExternalLink, Hotel, Plane, RefreshCw, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../utils/api'

const statusText = value => String(value || 'awaiting_finance_approval').replaceAll('_', ' ')
const statusStyle = value => value === 'booked_pending_cost_review'
  ? 'bg-violet-100 text-violet-800'
  : value === 'ready_to_book'
    ? 'bg-emerald-100 text-emerald-800'
    : 'bg-amber-100 text-amber-900'

function searchUrl(kind, item) {
  const route = `from ${item.trainer_origin || 'trainer city'} to ${item.venue_address || 'training venue'} ${item.training_dates || ''} India`
  const search = kind === 'hotel'
    ? `hotels near ${item.venue_address || 'training venue'} ${item.training_dates || ''}`
    : `${kind} travel ${route}`
  return `https://www.google.com/search?q=${encodeURIComponent(search)}`
}

export default function TravelBookings() {
  const [bookings, setBookings] = useState([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/finance/travel-bookings')
      setBookings(data.bookings || [])
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Could not load travel bookings')
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  const visible = useMemo(() => bookings.filter(item => {
    const text = [item.client_name, item.client_email, item.trainer_name, item.requirement_id, item.venue_address, item.trainer_origin].join(' ').toLowerCase()
    return (status === 'all' || item.status === status) && text.includes(query.trim().toLowerCase())
  }), [bookings, query, status])

  return <main className="min-w-0 space-y-4 animate-fade-in">
    <header className="flex flex-wrap items-end justify-between gap-3 rounded-2xl border border-blue-100 bg-white px-5 py-4 shadow-sm">
      <div><p className="text-xs font-bold uppercase tracking-wide text-blue-700">Operations</p><h1 className="mt-1 page-title">Travel Bookings</h1><p className="mt-1 text-sm text-slate-500">See which client and trainer each ticket, bus, car, or hotel booking belongs to. Booking happens only after Clahan approval.</p></div>
      <button type="button" onClick={load} disabled={loading} className="btn-secondary text-sm"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh</button>
    </header>
    <div className="flex flex-wrap gap-3 rounded-xl border border-slate-200 bg-white p-3">
      <label className="relative min-w-[240px] flex-1"><Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Client, trainer, requirement or route" className="h-10 w-full rounded-lg border border-slate-200 pl-9 pr-3 text-sm" /></label>
      <select value={status} onChange={event => setStatus(event.target.value)} className="h-10 rounded-lg border border-slate-200 px-3 text-sm"><option value="all">All statuses</option><option value="awaiting_finance_approval">Awaiting finance approval</option><option value="ready_to_book">Ready for travel agent</option><option value="booked_pending_cost_review">Booked - cost review</option></select>
    </div>
    <p className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-xs text-blue-900">Live flight, bus, car, and hotel availability/prices require a connected travel supplier API. The links below open a comparison search; they do not reserve or buy anything.</p>
    {loading ? <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Loading travel tasks...</div> : visible.length === 0 ? <div className="rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500">No travel booking tasks match this view.</div> : <div className="grid gap-4 xl:grid-cols-2">
      {visible.map(item => <article key={item.booking_task_id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-xs font-bold uppercase tracking-wide text-blue-700">{item.booking_task_id}</p><h2 className="mt-1 text-base font-bold text-slate-950">{item.client_name}</h2><p className="text-sm text-slate-500">Requirement {item.requirement_id}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-bold ${statusStyle(item.status)}`}>{statusText(item.status)}</span></div>
        <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><div><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Trainer</p><p className="mt-1 font-semibold text-slate-900">{item.trainer_name || 'Selected trainer'}</p><p className="text-slate-600">From: {item.trainer_origin || 'Not recorded'}</p></div><div><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Training</p><p className="mt-1 font-semibold text-slate-900">{item.training_dates || 'Dates not recorded'}</p><p className="text-slate-600">To: {item.venue_address || 'Venue not recorded'}</p></div></div>
        <div className="mt-3 flex flex-wrap gap-2">{item.ticket_required && <span className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">Ticket required</span>}{item.hotel_required && <span className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">Hotel required</span>}{item.booking_reference && <span className="rounded-lg bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">Reference: {item.booking_reference}</span>}</div>
        <div className="mt-3 flex flex-wrap gap-2">{[['flight', Plane], ['bus', Bus], ['car', Car], ['hotel', Hotel]].map(([kind, Icon]) => <a key={kind} href={searchUrl(kind, item)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"><Icon className="h-3.5 w-3.5" /> Search {kind}<ExternalLink className="h-3 w-3" /></a>)}</div>
        <div className="mt-4 border-t border-slate-100 pt-3 text-sm"><p><span className="font-semibold">Client terms:</span> {item.client_travel_terms || 'Not recorded'}</p>{Number(item.actual_total_cost_inr || 0) > 0 && <p className="mt-1 font-semibold text-emerald-800">Recorded actual cost: INR {Number(item.actual_total_cost_inr).toLocaleString('en-IN')}</p>}</div>
      </article>)}
    </div>}
  </main>
}
