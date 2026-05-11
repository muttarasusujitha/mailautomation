import { useState, useEffect } from 'react'
import { getEmails, checkReplies, retryEmail, scheduleInterview, sendMailToOne } from '../utils/api'
import toast from 'react-hot-toast'
import { Mail, RefreshCw, MessageSquare, AlertCircle, Send,
         RotateCcw, Calendar, ChevronDown, ChevronUp, CheckCircle, X, Loader2 } from 'lucide-react'
import clsx from 'clsx'

const SENTIMENT = {
  positive: { color: 'badge-green',  label: 'Interested' },
  negative: { color: 'badge-red',    label: 'Declined'   },
  neutral:  { color: 'badge-yellow', label: 'Neutral'    },
}

function InterviewModal({ email, onClose, onSuccess }) {
  const [date, setDate]   = useState('')
  const [link, setLink]   = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async () => {
    setLoading(true)
    try {
      const res = await scheduleInterview(email.email_id, date, link)
      if (res.data.success) {
        toast.success(`✅ Interview scheduled & email sent to ${email.trainer_name}!`)
        onSuccess()
        onClose()
      } else {
        toast.error(`Failed: ${res.data.error}`)
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
            <p className="text-sm text-slate-500 mt-0.5">For <strong>{email.trainer_name}</strong></p>
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
            <label className="label">Meeting Link <span className="text-slate-400 font-normal">(optional)</span></label>
            <input className="input" placeholder="https://meet.google.com/..." value={link} onChange={e => setLink(e.target.value)} />
          </div>
        </div>
        <div className="flex gap-3 mt-6">
          <button onClick={handleSubmit} disabled={loading} className="btn-primary flex-1 justify-center">
            {loading ? <><Loader2 className="w-4 h-4 animate-spin" /> Sending...</> : <><Calendar className="w-4 h-4" /> Send Interview Email</>}
          </button>
          <button onClick={onClose} className="btn-secondary">Cancel</button>
        </div>
      </div>
    </div>
  )
}

function EmailRow({ email, onRefresh }) {
  const [expanded,  setExpanded]  = useState(false)
  const [retrying,  setRetrying]  = useState(false)
  const [mailing,   setMailing]   = useState(false)
  const [showSched, setShowSched] = useState(false)

  const handleRetry = async (e) => {
    e.stopPropagation()
    setRetrying(true)
    try {
      const res = await retryEmail(email.email_id)
      if (res.data.success) {
        toast.success(`✅ Email resent to ${email.trainer_name}!`)
        onRefresh()
      } else {
        toast.error(`Retry failed: ${res.data.error}`)
      }
    } catch (err) { toast.error(err.message) }
    finally { setRetrying(false) }
  }

  const handleSendMail = async (e) => {
    e.stopPropagation()
    setMailing(true)
    try {
      await sendMailToOne(email.email_id)
      toast.success(`Email sent to ${email.trainer_name}!`)
      onRefresh()
    } catch (err) { toast.error(err.message) }
    finally { setMailing(false) }
  }

  const isFailed    = email.status === 'failed'
  const isInterested = email.reply_sentiment === 'positive' && email.reply_received
  const canSchedule  = isInterested && !email.interview_scheduled
  const retryCount   = email.retry_count || 0
  const maxRetries   = retryCount >= 3

  return (
    <>
      {showSched && (
        <InterviewModal email={email} onClose={() => setShowSched(false)} onSuccess={onRefresh} />
      )}
      <div className={clsx(
        'card overflow-hidden transition-all duration-300 hover:shadow-card-hover group',
        isFailed && 'border-red-100',
        isInterested && 'border-emerald-100',
        email.interview_scheduled && 'border-purple-100'
      )}>
        <div className="p-4 flex items-start gap-4 cursor-pointer hover:bg-slate-50 transition-colors"
             onClick={() => setExpanded(e => !e)}>
          <div className={clsx(
            'w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 transition-transform group-hover:scale-105',
            email.interview_scheduled ? 'bg-purple-100' :
            email.reply_received      ? 'bg-emerald-100' :
            isFailed                  ? 'bg-red-50' : 'bg-blue-50'
          )}>
            {email.interview_scheduled ? <Calendar className="w-5 h-5 text-purple-600" /> :
             email.reply_received      ? <MessageSquare className="w-5 h-5 text-emerald-600" /> :
             isFailed                  ? <AlertCircle className="w-5 h-5 text-red-500" /> :
                                         <Mail className="w-5 h-5 text-brand-500" />}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2 flex-wrap">
              <div>
                <p className="font-semibold text-slate-900">{email.trainer_name}</p>
                <p className="text-xs text-slate-400">{email.to_email}</p>
              </div>
              <div className="flex items-center gap-2 flex-wrap flex-shrink-0">
                <span className={clsx('badge', email.status === 'sent' ? 'badge-blue' : email.status === 'failed' ? 'badge-red' : 'badge-slate')}>
                  {email.status}
                </span>
                {email.reply_received && email.reply_sentiment && (
                  <span className={SENTIMENT[email.reply_sentiment]?.color || 'badge-slate'}>
                    {SENTIMENT[email.reply_sentiment]?.label}
                  </span>
                )}
                {email.interview_scheduled && (
                  <span className="badge bg-purple-50 text-purple-700">
                    <Calendar className="w-3 h-3" /> Interview Scheduled
                  </span>
                )}
                {retryCount > 0 && <span className="badge-yellow">Retry #{retryCount}</span>}

                {/* RETRY BUTTON — inline */}
                {isFailed && !maxRetries && (
                  <button onClick={handleRetry} disabled={retrying}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold
                               bg-red-500 hover:bg-red-600 text-white transition-all active:scale-95 shadow-sm disabled:opacity-60">
                    {retrying ? <><Loader2 className="w-3 h-3 animate-spin" /> Retrying...</> : <><RotateCcw className="w-3 h-3" /> Retry</>}
                  </button>
                )}
                {isFailed && maxRetries && <span className="badge-red text-xs">Max retries reached</span>}

                {/* SEND MAIL to this person */}
                {!isFailed && (
                  <button onClick={handleSendMail} disabled={mailing}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold
                               bg-blue-50 hover:bg-blue-100 text-blue-600 border border-blue-200 transition-all active:scale-95">
                    {mailing ? <><Loader2 className="w-3 h-3 animate-spin" /> Sending...</> : <><Send className="w-3 h-3" /> Send Mail</>}
                  </button>
                )}

                {/* SCHEDULE INTERVIEW */}
                {canSchedule && (
                  <button onClick={e => { e.stopPropagation(); setShowSched(true) }}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold
                               bg-emerald-500 hover:bg-emerald-600 text-white transition-all active:scale-95 shadow-sm">
                    <Calendar className="w-3 h-3" /> Schedule Interview
                  </button>
                )}

                {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
              </div>
            </div>
            <p className="text-sm text-slate-600 mt-1 line-clamp-1">{email.subject}</p>
            <div className="mt-1 flex gap-4 text-xs text-slate-400 flex-wrap">
              <span>Ref: {email.requirement_id}</span>
              {email.sent_at && <span>{new Date(email.sent_at).toLocaleString()}</span>}
              {email.reply_received && (
                <span className="text-emerald-500 flex items-center gap-1">
                  <CheckCircle className="w-3 h-3" /> Replied
                </span>
              )}
              {isFailed && email.error_message && (
                <span className="text-red-400 truncate max-w-xs">{email.error_message}</span>
              )}
            </div>
          </div>
        </div>

        {expanded && (
          <div className="border-t border-slate-100 bg-slate-50 p-4 space-y-4 animate-slide-up">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Email Sent</p>
              <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans bg-white rounded-xl p-4 border border-slate-100 max-h-56 overflow-y-auto">
                {email.body}
              </pre>
            </div>
            {email.reply_received && email.reply_text && (
              <div>
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Trainer Reply</p>
                <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans bg-white rounded-xl p-4 border border-emerald-100 max-h-40 overflow-y-auto">
                  {email.reply_text}
                </pre>
              </div>
            )}
            {email.interview_date && (
              <div className="flex items-center gap-2 text-sm text-purple-700 bg-purple-50 rounded-xl p-3">
                <Calendar className="w-4 h-4" />
                <span>Interview: <strong>{email.interview_date}</strong></span>
                {email.interview_link && (
                  <a href={email.interview_link} target="_blank" rel="noreferrer"
                     className="ml-auto text-brand-500 hover:underline">Join →</a>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}

export default function Emails() {
  const [emails,   setEmails]   = useState([])
  const [total,    setTotal]    = useState(0)
  const [page,     setPage]     = useState(1)
  const [loading,  setLoading]  = useState(false)
  const [checking, setChecking] = useState(false)
  const [filter,   setFilter]   = useState('all')

  const load = async (p = 1) => {
    setLoading(true)
    try {
      const res = await getEmails({ page: p, limit: 20 })
      setEmails(res.data.emails || [])
      setTotal(res.data.total || 0)
      setPage(p)
    } catch {}
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const handleCheckReplies = async () => {
    setChecking(true)
    try {
      const res = await checkReplies()
      toast.success(`Found ${res.data.replies_found} replies, processed ${res.data.processed}`)
      load()
    } catch (e) { toast.error(e.message) }
    finally { setChecking(false) }
  }

  const filtered =
    filter === 'replied'   ? emails.filter(e => e.reply_received) :
    filter === 'pending'   ? emails.filter(e => !e.reply_received && e.status === 'sent') :
    filter === 'failed'    ? emails.filter(e => e.status === 'failed') :
    filter === 'scheduled' ? emails.filter(e => e.interview_scheduled) :
    emails

  const sentCount      = emails.filter(e => e.status === 'sent').length
  const repliedCount   = emails.filter(e => e.reply_received).length
  const failedCount    = emails.filter(e => e.status === 'failed').length
  const scheduledCount = emails.filter(e => e.interview_scheduled).length

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="page-title">Email Logs</h1>
          <p className="text-sm text-slate-500 mt-0.5">{total} outreach emails tracked</p>
        </div>
        <button onClick={handleCheckReplies} disabled={checking} className="btn-primary">
          <RefreshCw className={clsx('w-4 h-4', checking && 'animate-spin')} />
          {checking ? 'Checking...' : 'Check Replies'}
        </button>
      </div>

      {/* Summary cards — clickable to filter */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Sent',      value: sentCount,      icon: Send,          color: 'bg-blue-50 text-brand-500',      key: 'all'       },
          { label: 'Replied',   value: repliedCount,   icon: MessageSquare, color: 'bg-emerald-50 text-emerald-500', key: 'replied'   },
          { label: 'Failed',    value: failedCount,    icon: AlertCircle,   color: 'bg-red-50 text-red-500',         key: 'failed'    },
          { label: 'Scheduled', value: scheduledCount, icon: Calendar,      color: 'bg-purple-50 text-purple-500',   key: 'scheduled' },
        ].map(s => (
          <div key={s.label}
            onClick={() => setFilter(s.key)}
            className={clsx(
              "card p-4 flex items-center gap-3 hover:shadow-card-hover hover:-translate-y-0.5 transition-all duration-200 cursor-pointer group",
              filter === s.key && "ring-2 ring-brand-300"
            )}>
            <div className={clsx('w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 transition-transform group-hover:scale-110', s.color)}>
              <s.icon className="w-4 h-4" />
            </div>
            <div>
              <p className="font-display text-xl font-bold text-slate-900">{s.value}</p>
              <p className="text-xs text-slate-400">{s.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 flex-wrap">
        {[
          { key: 'all',       label: 'All'          },
          { key: 'failed',    label: '🔴 Failed'    },
          { key: 'replied',   label: '💬 Replied'   },
          { key: 'scheduled', label: '📅 Scheduled' },
          { key: 'pending',   label: '⏳ Awaiting'  },
        ].map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={clsx('px-4 py-2 rounded-xl text-sm font-medium border transition-all duration-150',
              filter === f.key
                ? 'bg-brand-500 text-white border-brand-500 shadow-sm'
                : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300 hover:bg-slate-50')}>
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="card p-4 animate-pulse">
              <div className="flex gap-4">
                <div className="w-10 h-10 rounded-xl bg-slate-100" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-slate-100 rounded w-1/4" />
                  <div className="h-3 bg-slate-100 rounded w-1/2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-16 text-center">
          <Mail className="w-12 h-12 text-slate-200 mx-auto mb-3" />
          <p className="font-medium text-slate-500">No emails in this category</p>
          <p className="text-sm text-slate-400 mt-1">Run a trainer search to send outreach emails</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((e, i) => (
            <EmailRow key={e.email_id || i} email={e} onRefresh={() => load(page)} />
          ))}
        </div>
      )}

      {total > 20 && (
        <div className="flex justify-center gap-2">
          <button onClick={() => load(page - 1)} disabled={page === 1} className="btn-secondary disabled:opacity-40">← Prev</button>
          <span className="btn-secondary pointer-events-none">Page {page}</span>
          <button onClick={() => load(page + 1)} disabled={emails.length < 20} className="btn-secondary disabled:opacity-40">Next →</button>
        </div>
      )}
    </div>
  )
}
