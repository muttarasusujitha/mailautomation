import { useState, useEffect, useCallback } from 'react'
import { getTrainers, deleteTrainer } from '../utils/api'
import { Search, MapPin, Mail, Phone, Linkedin, FileText, Clock,
         ChevronLeft, ChevronRight, Filter, Users, Trash2, X,
         Award, ChevronDown, ChevronUp } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

const STATUS_COLORS = {
  new:            'badge-slate',
  contacted:      'badge-blue',
  interested:     'badge-green',
  declined:       'badge-red',
  confirmed:      'badge-green',
  pending_review: 'badge-yellow',
}

const STATUSES = ['', 'new', 'contacted', 'interested', 'declined', 'pending_review']

function TrainerDetail({ t, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30 backdrop-blur-sm animate-fade-in">
      <div className="bg-white rounded-2xl shadow-card-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto animate-slide-up">
        <div className="flex items-center justify-between p-5 border-b border-slate-100 sticky top-0 bg-white z-10">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-brand-100 to-brand-50 flex items-center justify-center">
              <span className="font-display font-bold text-brand-600 text-lg">{t.name?.charAt(0).toUpperCase()}</span>
            </div>
            <div>
              <h2 className="font-display font-bold text-slate-900 text-lg">{t.name}</h2>
              <span className={clsx('text-xs', STATUS_COLORS[t.status] || 'badge-slate')}>{t.status}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-xl transition-colors">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>
        <div className="p-5 space-y-5">
          {/* Contact Info */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {t.email && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl">
                <Mail className="w-4 h-4 text-brand-500 flex-shrink-0" />
                <a href={`mailto:${t.email}`} className="text-sm text-slate-700 hover:text-brand-500 truncate">{t.email}</a>
              </div>
            )}
            {t.phone && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl">
                <Phone className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                <span className="text-sm text-slate-700">{t.phone}</span>
              </div>
            )}
            {t.location && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl">
                <MapPin className="w-4 h-4 text-amber-500 flex-shrink-0" />
                <span className="text-sm text-slate-700">{t.location}</span>
              </div>
            )}
            {t.experience_raw && (
              <div className="flex items-center gap-2 p-3 bg-slate-50 rounded-xl">
                <Clock className="w-4 h-4 text-purple-500 flex-shrink-0" />
                <span className="text-sm text-slate-700">{t.experience_raw}</span>
              </div>
            )}
          </div>

          {/* Technologies */}
          {t.technologies && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Technologies</p>
              <p className="text-sm text-slate-700 bg-slate-50 rounded-xl p-3 leading-relaxed">{t.technologies}</p>
            </div>
          )}

          {/* Skills */}
          {t.skills?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Skills</p>
              <div className="flex flex-wrap gap-2">
                {t.skills.map((s, i) => <span key={i} className="badge-blue text-xs">{s}</span>)}
              </div>
            </div>
          )}

          {/* Certifications */}
          {t.certifications?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Certifications</p>
              <div className="flex flex-wrap gap-2">
                {t.certifications.map((c, i) => (
                  <span key={i} className="flex items-center gap-1 badge bg-amber-50 text-amber-700 text-xs">
                    <Award className="w-3 h-3" /> {c}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Score breakdown */}
          {t.score_breakdown && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Match Score Breakdown</p>
              <div className="grid grid-cols-5 gap-3 bg-slate-50 rounded-xl p-4">
                {[
                  { label: 'Tech',  key: 'technology',    max: 35, color: 'bg-blue-500' },
                  { label: 'Skills',key: 'skills',        max: 30, color: 'bg-emerald-500' },
                  { label: 'Exp',   key: 'experience',    max: 20, color: 'bg-purple-500' },
                  { label: 'Cert',  key: 'certifications',max: 10, color: 'bg-amber-500' },
                  { label: 'Loc',   key: 'location',      max: 5,  color: 'bg-rose-500' },
                ].map(({ label, key, max, color }) => {
                  const val = t.score_breakdown[key]?.score ?? 0
                  const pct = Math.round((val / max) * 100)
                  return (
                    <div key={key} className="text-center">
                      <div className="h-2 bg-slate-200 rounded-full overflow-hidden mb-1">
                        <div className={clsx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
                      </div>
                      <p className="text-xs text-slate-500">{label}</p>
                      <p className="text-xs font-bold text-slate-800">{val}/{max}</p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Links */}
          <div className="flex gap-3 pt-2">
            {t.linkedin && t.linkedin !== '-' && (
              <a href={t.linkedin} target="_blank" rel="noreferrer"
                 className="flex items-center gap-2 px-4 py-2 bg-blue-50 text-blue-600 rounded-xl text-sm font-medium hover:bg-blue-100 transition-colors">
                <Linkedin className="w-4 h-4" /> LinkedIn Profile
              </a>
            )}
            {t.resume && t.resume !== '-' && (
              <a href={t.resume} target="_blank" rel="noreferrer"
                 className="flex items-center gap-2 px-4 py-2 bg-emerald-50 text-emerald-600 rounded-xl text-sm font-medium hover:bg-emerald-100 transition-colors">
                <FileText className="w-4 h-4" /> View Resume
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function TrainerRow({ t, onDelete, onView }) {
  return (
    <div className="card-hover p-4 flex items-start gap-4 animate-fade-in group">
      {/* Avatar — clickable */}
      <div
        onClick={() => onView(t)}
        className="w-11 h-11 rounded-xl bg-gradient-to-br from-brand-100 to-brand-50 flex items-center justify-center flex-shrink-0 cursor-pointer hover:from-brand-200 hover:to-brand-100 transition-all">
        <span className="font-display font-bold text-brand-600 text-base">{t.name?.charAt(0).toUpperCase()}</span>
      </div>

      <div className="flex-1 min-w-0 cursor-pointer" onClick={() => onView(t)}>
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div>
            <h3 className="font-medium text-slate-900 group-hover:text-brand-600 transition-colors">{t.name}</h3>
            <p className="text-xs text-slate-400 mt-0.5 line-clamp-1">{t.technologies?.substring(0, 100)}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {t.match_score != null && (
              <div className={clsx(
                'w-9 h-9 rounded-lg flex items-center justify-center text-sm font-bold',
                t.match_score >= 80 ? 'bg-emerald-100 text-emerald-700' :
                t.match_score >= 60 ? 'bg-blue-100 text-blue-700' :
                t.match_score >= 40 ? 'bg-amber-100 text-amber-700' :
                'bg-slate-100 text-slate-500'
              )}>
                {t.match_score}
              </div>
            )}
            <span className={STATUS_COLORS[t.status] || 'badge-slate'}>{t.status}</span>
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          {t.experience_raw && <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {t.experience_raw}</span>}
          {t.location && <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> {t.location}</span>}
          {t.email && <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5" /> {t.email}</span>}
          {t.phone && <span className="flex items-center gap-1"><Phone className="w-3.5 h-3.5" /> {t.phone}</span>}
        </div>

        {t.skills?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {t.skills.slice(0, 6).map((s, i) => <span key={i} className="badge-slate text-xs">{s}</span>)}
            {t.skills.length > 6 && <span className="badge-slate text-xs">+{t.skills.length - 6}</span>}
          </div>
        )}
      </div>

      {/* Delete button */}
      <button
        onClick={(e) => { e.stopPropagation(); onDelete(t) }}
        className="flex-shrink-0 p-2 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-all duration-200 opacity-0 group-hover:opacity-100">
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  )
}

export default function Trainers() {
  const [trainers, setTrainers] = useState([])
  const [total, setTotal]       = useState(0)
  const [pages, setPages]       = useState(1)
  const [page, setPage]         = useState(1)
  const [search, setSearch]     = useState('')
  const [status, setStatus]     = useState('')
  const [loading, setLoading]   = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [selectedTrainer, setSelectedTrainer] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)

  const load = useCallback(async (p = page, s = search, st = status) => {
    setLoading(true)
    try {
      const res = await getTrainers({ page: p, limit: 15, search: s || undefined, status: st || undefined })
      setTrainers(res.data.trainers)
      setTotal(res.data.total)
      setPages(res.data.pages)
    } catch {}
    finally { setLoading(false) }
  }, [page, search, status])

  useEffect(() => { load(1, search, status) }, [search, status])
  useEffect(() => { load(page, search, status) }, [page])

  const handleSearch = (e) => {
    e.preventDefault()
    setSearch(searchInput)
    setPage(1)
  }

  const handleDelete = async (trainer) => {
    try {
      await deleteTrainer(trainer.trainer_id)
      toast.success(`${trainer.name} deleted`)
      setConfirmDelete(null)
      load(page, search, status)
    } catch (e) { toast.error(e.message) }
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Trainer detail modal */}
      {selectedTrainer && (
        <TrainerDetail t={selectedTrainer} onClose={() => setSelectedTrainer(null)} />
      )}

      {/* Delete confirm modal */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-card-lg p-6 max-w-sm w-full animate-slide-up">
            <h3 className="font-bold text-slate-900 mb-2">Delete Trainer?</h3>
            <p className="text-sm text-slate-500 mb-4">Remove <strong>{confirmDelete.name}</strong> from the database? This cannot be undone.</p>
            <div className="flex gap-3">
              <button onClick={() => handleDelete(confirmDelete)} className="btn-danger flex-1 justify-center">
                <Trash2 className="w-4 h-4" /> Delete
              </button>
              <button onClick={() => setConfirmDelete(null)} className="btn-secondary">Cancel</button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="page-title">All Trainers</h1>
          <p className="text-sm text-slate-500 mt-0.5">{total} trainers in database</p>
        </div>
      </div>

      {/* Filters */}
      <div className="card p-4 flex flex-wrap gap-3 items-center">
        <form onSubmit={handleSearch} className="flex gap-2 flex-1 min-w-48">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              className="input pl-9"
              placeholder="Search by name, technology, location..."
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
            />
          </div>
          <button type="submit" className="btn-primary">Search</button>
        </form>
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400 flex-shrink-0" />
          <select className="input w-40" value={status}
            onChange={e => { setStatus(e.target.value); setPage(1) }}>
            <option value="">All Statuses</option>
            {STATUSES.filter(Boolean).map(s => (
              <option key={s} value={s}>{s.replace('_', ' ')}</option>
            ))}
          </select>
        </div>
      </div>

      {/* List */}
      {loading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="card p-4 animate-pulse">
              <div className="flex gap-4">
                <div className="w-11 h-11 rounded-xl bg-slate-100" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-slate-100 rounded w-1/3" />
                  <div className="h-3 bg-slate-100 rounded w-2/3" />
                  <div className="h-3 bg-slate-100 rounded w-1/2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : trainers.length === 0 ? (
        <div className="card p-16 text-center">
          <Users className="w-12 h-12 text-slate-200 mx-auto mb-3" />
          <p className="font-medium text-slate-500">No trainers found</p>
          <p className="text-sm text-slate-400 mt-1">Upload your Excel database to get started</p>
        </div>
      ) : (
        <div className="space-y-3">
          {trainers.map(t => (
            <TrainerRow
              key={t.trainer_id}
              t={t}
              onView={setSelectedTrainer}
              onDelete={setConfirmDelete}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-500">Page {page} of {pages} · {total} total</p>
          <div className="flex items-center gap-2">
            <button onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1} className="btn-secondary py-1.5 px-3 disabled:opacity-40">
              <ChevronLeft className="w-4 h-4" />
            </button>
            {[...Array(Math.min(pages, 5))].map((_, i) => {
              const p = i + 1
              return (
                <button key={p} onClick={() => setPage(p)}
                  className={clsx('w-8 h-8 rounded-lg text-sm font-medium',
                    page === p ? 'bg-brand-500 text-white' : 'btn-secondary py-0 px-0')}>
                  {p}
                </button>
              )
            })}
            <button onClick={() => setPage(p => Math.min(pages, p + 1))}
              disabled={page === pages} className="btn-secondary py-1.5 px-3 disabled:opacity-40">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
