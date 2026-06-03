import { useState, useEffect } from 'react'
import { getRequirements, getShortlist, scheduleInterview } from '../utils/api'
import toast from 'react-hot-toast'
import {
  Calendar, Mail, X, Loader2, ExternalLink,
  Clock, MapPin, RefreshCw, Users,
  Star, ChevronRight, AlertCircle, Phone
} from 'lucide-react'
import clsx from 'clsx'

const MEET_PLATFORMS = [
  { id: 'zoom',   label: 'Zoom',        icon: '📹', placeholder: 'https://zoom.us/j/...',               color: 'bg-blue-50 border-blue-200 text-blue-700' },
  { id: 'teams',  label: 'MS Teams',    icon: '💼', placeholder: 'https://teams.microsoft.com/...',      color: 'bg-violet-50 border-violet-200 text-violet-700' },
  { id: 'google', label: 'Google Meet', icon: '🎥', placeholder: 'https://meet.google.com/xxx-xxxx-xxx', color: 'bg-emerald-50 border-emerald-200 text-emerald-700' },
]

function ScheduleModal({ trainer, onClose, onSuccess }) {
  const [date, setDate]         = useState('')
  const [link, setLink]         = useState('')
  const [platform, setPlatform] = useState('zoom')
  const [loading, setLoading]   = useState(false)

  const selectedPlatform = MEET_PLATFORMS.find(p => p.id === platform)

  const handleSubmit = async () => {
    if (!date) return toast.error('Please select interview date and time')
    setLoading(true)
    try {
      const id = trainer.email_id || trainer.trainer_id
      const res = await scheduleInterview(id, date, link)
      if (res.data.success || res.data.message) {
        toast.success(`Interview scheduled & email sent to ${trainer.name || trainer.trainer_name}!`)
        onSuccess()
        onClose()
      } else {
        toast.error(`Failed: ${res.data.error || 'Unknown error'}`)
      }
    } catch (e) { toast.error(e.message) }
    finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30 backdrop-blur-sm animate-fade-in">
      <div className="bg-white rounded-2xl shadow-card-lg w-full max-w-md p-6 animate-slide-up">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="font-display font-bold text-slate-900">Schedule Interview</h3>
            <p className="text-sm text-slate-500 mt-0.5">For <strong>{trainer.name || trainer.trainer_name}</strong></p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-100 rounded-lg">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="label">Interview Date & Time</label>
            <input type="datetime-local" className="input" value={date} onChange={e => setDate(e.target.value)} />
          </div>

          <div>
            <label className="label">Meeting Platform</label>
            <div className="grid grid-cols-3 gap-2">
              {MEET_PLATFORMS.map(p => (
                <button key={p.id} type="button"
                  onClick={() => { setPlatform(p.id); setLink('') }}
                  className={clsx(
                    'flex flex-col items-center gap-1.5 p-3 rounded-xl border-2 text-xs font-semibold transition-all',
                    platform === p.id
                      ? `${p.color} border-current scale-105 shadow-sm`
                      : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
                  )}>
                  <span className="text-xl">{p.icon}</span>
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="label">
              {selectedPlatform?.label} Link
              <span className="text-slate-400 font-normal ml-1">(included in email)</span>
            </label>
            <input className="input" placeholder={selectedPlatform?.placeholder}
                   value={link} onChange={e => setLink(e.target.value)} />
            {link && (
              <a href={link} target="_blank" rel="noreferrer"
                 className="flex items-center gap-1 text-xs text-brand-500 hover:underline mt-1.5">
                <ExternalLink className="w-3 h-3" /> Test link
              </a>
            )}
          </div>

          {link && (
            <div className={clsx('flex items-center gap-2 p-3 rounded-xl border text-sm font-medium', selectedPlatform?.color)}>
              <span className="text-lg">{selectedPlatform?.icon}</span>
              <div className="min-w-0">
                <p className="font-semibold text-xs opacity-70">Meeting via {selectedPlatform?.label}</p>
                <p className="truncate text-xs">{link}</p>
              </div>
            </div>
          )}
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={handleSubmit} disabled={loading} className="btn-primary flex-1 justify-center">
            {loading
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Sending...</>
              : <><Calendar className="w-4 h-4" /> Send Interview Email</>}
          </button>
          <button onClick={onClose} className="btn-secondary">Cancel</button>
        </div>
      </div>
    </div>
  )
}

function TrainerCard({ trainer, onSchedule }) {
  const name  = trainer.name || trainer.trainer_name
  const email = trainer.email || trainer.to_email
  return (
    <div className="card p-4 flex items-center gap-4 hover:shadow-card-hover transition-all">
      <div className="w-10 h-10 rounded-xl bg-brand-50 flex items-center justify-center flex-shrink-0">
        <span className="font-display font-bold text-brand-600">{name?.charAt(0)?.toUpperCase()}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-slate-900">{name}</p>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5">
          {email             && <span className="text-xs text-slate-400 flex items-center gap-1"><Mail  className="w-3 h-3" />{email}</span>}
          {trainer.phone     && <span className="text-xs text-slate-400 flex items-center gap-1"><Phone className="w-3 h-3" />{trainer.phone}</span>}
          {trainer.location  && <span className="text-xs text-slate-400 flex items-center gap-1"><MapPin className="w-3 h-3" />{trainer.location}</span>}
          {(trainer.experience_raw || trainer.experience_years) && (
            <span className="text-xs text-slate-400 flex items-center gap-1">
              <Clock className="w-3 h-3" />{trainer.experience_raw || `${trainer.experience_years}yrs`}
            </span>
          )}
        </div>
        {trainer.skills?.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {trainer.skills.slice(0, 4).map((s, i) => <span key={i} className="badge-blue text-xs">{s}</span>)}
            {trainer.skills.length > 4 && <span className="badge-slate text-xs">+{trainer.skills.length - 4}</span>}
          </div>
        )}
      </div>
      <div className="flex-shrink-0 flex flex-col items-end gap-2">
        {trainer.match_score != null && (
          <span className={clsx('px-2 py-0.5 rounded-lg text-xs font-bold',
            trainer.match_score >= 80 ? 'bg-emerald-100 text-emerald-700' :
            trainer.match_score >= 60 ? 'bg-blue-100 text-blue-700' :
            'bg-amber-100 text-amber-700'
          )}>{trainer.match_score} pts</span>
        )}
        <button onClick={() => onSchedule(trainer)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold
                     bg-brand-500 hover:bg-brand-600 text-white shadow-sm transition-all active:scale-95">
          <Calendar className="w-3.5 h-3.5" /> Schedule Interview
        </button>
      </div>
    </div>
  )
}

export default function Interviews() {
  const [reqs, setReqs]               = useState([])
  const [selectedReq, setSelectedReq] = useState(null)
  const [trainers, setTrainers]       = useState([])
  const [scheduleFor, setScheduleFor] = useState(null)
  const [loadingReqs, setLoadingReqs]         = useState(false)
  const [loadingTrainers, setLoadingTrainers] = useState(false)

  useEffect(() => {
    setLoadingReqs(true)
    getRequirements()
      .then(r => setReqs(r.data.requirements || []))
      .catch(() => {})
      .finally(() => setLoadingReqs(false))
  }, [])

  useEffect(() => {
    if (!selectedReq) return
    setLoadingTrainers(true)
    setTrainers([])
    getShortlist(selectedReq.requirement_id)
      .then(r => setTrainers(r.data.trainers || r.data.shortlist || []))
      .catch(() => toast.error('Could not load shortlist'))
      .finally(() => setLoadingTrainers(false))
  }, [selectedReq])

  const reload = () => {
    if (!selectedReq) return
    setLoadingTrainers(true)
    getShortlist(selectedReq.requirement_id)
      .then(r => setTrainers(r.data.trainers || r.data.shortlist || []))
      .catch(() => {})
      .finally(() => setLoadingTrainers(false))
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {scheduleFor && (
        <ScheduleModal trainer={scheduleFor} onClose={() => setScheduleFor(null)} onSuccess={reload} />
      )}

      <div>
        <h1 className="page-title flex items-center gap-2">
          <Calendar className="w-6 h-6 text-brand-500" /> Interviews
        </h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Schedule interviews for shortlisted trainers — choose Zoom, Teams or Google Meet
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Requirements', value: reqs.length,     color: 'bg-blue-50 text-blue-600',    icon: '📋' },
          { label: 'Shortlisted',  value: trainers.length, color: 'bg-emerald-50 text-emerald-600', icon: '👥' },
          { label: 'Platforms',    value: 3,               color: 'bg-purple-50 text-purple-600', icon: '📹' },
        ].map(s => (
          <div key={s.label} className={clsx('card p-4 flex items-center gap-3 hover:shadow-card-hover transition-all', s.color)}>
            <span className="text-2xl">{s.icon}</span>
            <div>
              <p className="font-display text-2xl font-bold">{s.value}</p>
              <p className="text-xs opacity-70">{s.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Platform info */}
      <div className="card p-4">
        <p className="label mb-3 block">Available Meeting Platforms</p>
        <div className="flex flex-wrap gap-3">
          {MEET_PLATFORMS.map(p => (
            <div key={p.id} className={clsx('flex items-center gap-2 px-4 py-2 rounded-xl border text-sm font-semibold', p.color)}>
              <span className="text-lg">{p.icon}</span> {p.label}
            </div>
          ))}
        </div>
      </div>

      {/* Requirement picker */}
      <div className="card p-4">
        <label className="label mb-2 block">Select Requirement to View Shortlist</label>
        {loadingReqs ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading...
          </div>
        ) : reqs.length === 0 ? (
          <div className="flex items-center gap-2 p-3 bg-amber-50 rounded-xl text-sm text-amber-700">
            <AlertCircle className="w-4 h-4" />
            No requirements found. Run a search in "Find Trainers" first.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {reqs.map(r => (
              <button key={r.requirement_id} onClick={() => setSelectedReq(r)}
                className={clsx(
                  'flex items-center gap-3 p-3 rounded-xl border text-left transition-all',
                  selectedReq?.requirement_id === r.requirement_id
                    ? 'bg-brand-50 border-brand-300 text-brand-700'
                    : 'bg-white border-slate-200 hover:border-brand-300 text-slate-700'
                )}>
                <div className="w-8 h-8 rounded-lg bg-brand-100 flex items-center justify-center flex-shrink-0">
                  <Star className="w-4 h-4 text-brand-500" />
                </div>
                <div className="min-w-0">
                  <p className="font-semibold text-sm truncate">{r.technology_needed}</p>
                  <p className="text-xs text-slate-400 truncate">{r.requirement_id} · Top {r.top_n}</p>
                </div>
                <ChevronRight className="w-4 h-4 ml-auto opacity-40 flex-shrink-0" />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Shortlist */}
      {selectedReq && (
        <div className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="section-title">
              Shortlisted for: <span className="text-brand-600">{selectedReq.technology_needed}</span>
            </h2>
            <button onClick={reload} disabled={loadingTrainers} className="btn-secondary py-1.5 px-3 text-xs">
              <RefreshCw className={clsx('w-3.5 h-3.5', loadingTrainers && 'animate-spin')} /> Refresh
            </button>
          </div>

          {loadingTrainers ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="card p-4 animate-pulse flex gap-4">
                  <div className="w-10 h-10 rounded-xl bg-slate-100" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-slate-100 rounded w-1/3" />
                    <div className="h-3 bg-slate-100 rounded w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : trainers.length === 0 ? (
            <div className="card p-12 text-center">
              <Users className="w-12 h-12 text-slate-200 mx-auto mb-3" />
              <p className="font-medium text-slate-500">No shortlisted trainers for this requirement</p>
              <p className="text-sm text-slate-400 mt-1">Run "Shortlist Only" in Find Trainers first</p>
            </div>
          ) : (
            trainers.map(trainer => (
              <TrainerCard key={trainer.trainer_id} trainer={trainer} onSchedule={setScheduleFor} />
            ))
          )}
        </div>
      )}
    </div>
  )
}
