import { useState, useEffect, useRef } from 'react'
import { getEmails, checkReplies, retryEmail, scheduleInterview, sendMailToOne } from '../utils/api'
import toast from 'react-hot-toast'
import {
  Mail, RefreshCw, MessageSquare, AlertCircle, Send,
  RotateCcw, Calendar, ChevronDown, ChevronUp, CheckCircle,
  X, Loader2, MessageCircle, Eye
} from 'lucide-react'
import clsx from 'clsx'

const SENTIMENT = {
  positive: { color: 'badge-green',  label: 'Interested' },
  negative: { color: 'badge-red',    label: 'Declined'   },
  neutral:  { color: 'badge-yellow', label: 'Neutral'    },
}

const REPLY_REFRESH_INTERVAL_MS = 10000

/* ── Interview Modal ────────────────────────────────────────── */
function InterviewModal({ email, onClose, onSuccess }) {
  const [date, setDate]     = useState('')
  const [link, setLink]     = useState('')
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

/* ── Thread Bubble ──────────────────────────────────────────── */
function ThreadBubble({ msg }) {
  const isSent = msg.direction === 'sent'
  const LABELS = {
    mail1: '1st Contact', mail2: 'Details Request', mail3: 'Slot Booking',
    mail4: 'Interview Schedule', mail5_ok: 'Selection', mail5_no: 'Rejection',
    reply: 'Trainer Reply', toc: 'ToC Request', first: '1st Contact'
  }

  return (
    <div className={clsx('flex gap-2 mb-3', isSent ? 'flex-row-reverse' : 'flex-row')}>
      <div className={clsx(
        'w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold mt-0.5',
        isSent ? 'bg-blue-100 text-blue-700' : 'bg-emerald-100 text-emerald-700'
      )}>
        {isSent ? 'You' : 'T'}
      </div>
      <div className={clsx(
        'max-w-[78%] rounded-2xl px-3.5 py-2.5 text-xs',
        isSent ? 'bg-blue-50 border border-blue-100 rounded-tr-sm' : 'bg-slate-50 border border-slate-200 rounded-tl-sm'
      )}>
        <div className={clsx('flex items-center gap-2 mb-1.5', isSent ? 'justify-end' : 'justify-start')}>
          {msg.mail_type && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-white border border-slate-200 text-slate-500">
              {LABELS[msg.mail_type] || msg.mail_type}
            </span>
          )}
          <span className="text-[10px] text-slate-400">
            {msg.sent_at ? new Date(msg.sent_at).toLocaleString() : ''}
          </span>
        </div>
        {msg.subject && (
          <p className="text-[10px] font-semibold text-slate-500 mb-1">
            Subject: <span className="font-normal">{msg.subject}</span>
          </p>
        )}
        <pre className="whitespace-pre-wrap font-sans text-slate-700 leading-relaxed">{msg.body}</pre>
      </div>
    </div>
  )
}

/* ── Thread Panel ───────────────────────────────────────────── */
function ThreadPanel({ email, onClose }) {
  const seedThread = () => {
    const msgs = []
    if (email.body) {
      msgs.push({
        direction: 'sent',
        mail_type: email.mail_type || 'first',
        subject: email.subject,
        body: email.body,
        sent_at: email.sent_at || email.created_at,
      })
    }
    if (email.reply_received && email.reply_text) {
      msgs.push({
        direction: 'received',
        mail_type: 'reply',
        subject: `Re: ${email.subject}`,
        body: email.reply_text,
        sent_at: email.replied_at || email.created_at,
      })
    }
    return msgs
  }
  const [thread, setThread]     = useState(seedThread)
  const [loading, setLoading]   = useState(() => seedThread().length === 0)
  const bottomRef               = useRef(null)
  const pollingRef              = useRef(null)

  // Load thread from conversations API
  const loadThread = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await fetch(
        `/api/shortlists/thread?trainer_id=${email.trainer_id}&requirement_id=${email.requirement_id}`
      )
      const data = await res.json()
      const messages = data.messages || []

      // Also inject any reply already stored in email_log directly
      const allMsgs = [...messages]

      // If email has reply but it's not yet in thread, add it
      if (email.reply_received && email.reply_text) {
        const alreadyInThread = allMsgs.some(
          m => m.direction === 'received' && m.body === email.reply_text
        )
        if (!alreadyInThread) {
          allMsgs.push({
            direction: 'received',
            mail_type: 'reply',
            subject: `Re: ${email.subject}`,
            body: email.reply_text,
            sent_at: email.replied_at || email.created_at,
          })
        }
      }

      // Sort by sent_at
      allMsgs.sort((a, b) => {
        const ta = a.sent_at ? new Date(a.sent_at).getTime() : 0
        const tb = b.sent_at ? new Date(b.sent_at).getTime() : 0
        return ta - tb
      })

      setThread(allMsgs)
    } catch {
      // Fallback: build thread from email_log data alone
      const msgs = []
      if (email.body) {
        msgs.push({
          direction: 'sent',
          mail_type: email.mail_type || 'first',
          subject: email.subject,
          body: email.body,
          sent_at: email.sent_at,
        })
      }
      if (email.reply_received && email.reply_text) {
        msgs.push({
          direction: 'received',
          mail_type: 'reply',
          subject: `Re: ${email.subject}`,
          body: email.reply_text,
          sent_at: email.replied_at,
        })
      }
      setThread(msgs)
    }
    finally { setLoading(false) }
  }

  useEffect(() => {
    const seeded = seedThread()
    if (seeded.length) {
      setThread(seeded)
      setLoading(false)
      loadThread(true)
    } else {
      loadThread()
    }
    pollingRef.current = setInterval(() => loadThread(true), REPLY_REFRESH_INTERVAL_MS)
    return () => clearInterval(pollingRef.current)
  }, [email.email_id, email.reply_received, email.reply_text, email.replied_at])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [thread])

  return (
    <div className="border-t border-slate-100 bg-gradient-to-b from-slate-50 to-white animate-slide-up">
      {/* Thread header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <MessageCircle className="w-4 h-4 text-blue-500" />
          <span className="text-sm font-semibold text-slate-700">Conversation Thread</span>
          {thread.length > 0 && (
            <span className="text-xs bg-blue-100 text-blue-700 font-bold px-2 py-0.5 rounded-full">
              {thread.length}
            </span>
          )}
          <span className="text-xs text-emerald-500 flex items-center gap-1">
            <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
            Auto-updating
          </span>
        </div>
        <button onClick={() => loadThread(false)}
          className="flex items-center gap-1 text-xs text-slate-400 hover:text-blue-500 transition-colors px-2 py-1 rounded-lg hover:bg-blue-50">
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>

      {/* Messages */}
      <div className="p-4 max-h-72 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-slate-400 gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm">Loading conversation...</span>
          </div>
        ) : thread.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-slate-400">
            <MessageCircle className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-sm">No messages yet</p>
            <p className="text-xs text-slate-300 mt-1">Replies will appear here automatically</p>
          </div>
        ) : (
          <>
            {thread.map((msg, i) => <ThreadBubble key={i} msg={msg} />)}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Original email body */}
      {!loading && email.body && (
        <div className="border-t border-slate-100 px-4 py-3">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Original Email Body</p>
          <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans bg-white rounded-xl p-4 border border-slate-100 max-h-56 overflow-y-auto">
            {email.body}
          </pre>
        </div>
      )}

      {/* Interview details */}
      {email.interview_date && (
        <div className="border-t border-slate-100 px-4 py-3">
          <div className="flex items-center gap-2 text-sm text-purple-700 bg-purple-50 rounded-xl p-3">
            <Calendar className="w-4 h-4" />
            <span>Interview: <strong>{email.interview_date}</strong></span>
            {email.interview_link && (
              <a href={email.interview_link} target="_blank" rel="noreferrer"
                 className="ml-auto text-brand-500 hover:underline">Join →</a>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Email Row ──────────────────────────────────────────────── */
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

  const isFailed     = email.status === 'failed'
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
        {/* Main row */}
        <div className="p-4 flex items-start gap-4 cursor-pointer hover:bg-slate-50 transition-colors"
             onClick={() => setExpanded(e => !e)}>
          <div className={clsx(
            'w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 transition-transform group-hover:scale-105',
            email.interview_scheduled ? 'bg-purple-100' :
            email.reply_received      ? 'bg-emerald-100' :
            email.opened              ? 'bg-cyan-50' :
            isFailed                  ? 'bg-red-50' : 'bg-blue-50'
          )}>
            {email.interview_scheduled ? <Calendar className="w-5 h-5 text-purple-600" /> :
             email.reply_received      ? <MessageSquare className="w-5 h-5 text-emerald-600" /> :
             email.opened              ? <Eye className="w-5 h-5 text-cyan-600" /> :
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
                  <span className={clsx('badge', SENTIMENT[email.reply_sentiment]?.color || 'badge-slate')}>
                    {SENTIMENT[email.reply_sentiment]?.label}
                  </span>
                )}
                {email.opened && (
                  <span className="badge bg-cyan-50 text-cyan-700">
                    <Eye className="w-3 h-3 mr-1" /> Opened
                  </span>
                )}
                {email.interview_scheduled && (
                  <span className="badge bg-purple-50 text-purple-700">
                    <Calendar className="w-3 h-3 mr-1" /> Interview Scheduled
                  </span>
                )}
                {retryCount > 0 && <span className="badge-yellow">Retry #{retryCount}</span>}

                {isFailed && !maxRetries && (
                  <button onClick={handleRetry} disabled={retrying}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold
                               bg-red-500 hover:bg-red-600 text-white transition-all active:scale-95 shadow-sm disabled:opacity-60">
                    {retrying ? <><Loader2 className="w-3 h-3 animate-spin" /> Retrying...</> : <><RotateCcw className="w-3 h-3" /> Retry</>}
                  </button>
                )}
                {isFailed && maxRetries && <span className="badge-red text-xs">Max retries reached</span>}

                {!isFailed && (
                  <button onClick={handleSendMail} disabled={mailing}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold
                               bg-blue-50 hover:bg-blue-100 text-blue-600 border border-blue-200 transition-all active:scale-95">
                    {mailing ? <><Loader2 className="w-3 h-3 animate-spin" /> Sending...</> : <><Send className="w-3 h-3" /> Send Mail</>}
                  </button>
                )}

                {canSchedule && (
                  <button onClick={e => { e.stopPropagation(); setShowSched(true) }}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold
                               bg-emerald-500 hover:bg-emerald-600 text-white transition-all active:scale-95 shadow-sm">
                    <Calendar className="w-3 h-3" /> Schedule Interview
                  </button>
                )}

                <div className={clsx(
                  'w-6 h-6 rounded-full flex items-center justify-center transition-all',
                  expanded ? 'bg-slate-200 rotate-180' : 'bg-slate-100'
                )}>
                  <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
                </div>
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
              {email.opened && (
                <span className="text-cyan-500 flex items-center gap-1">
                  <Eye className="w-3 h-3" />
                  Opened{email.open_count > 1 ? ` ${email.open_count}x` : ''}
                  {email.last_opened_at ? ` at ${new Date(email.last_opened_at).toLocaleString()}` : ''}
                </span>
              )}
              {isFailed && email.error_message && (
                <span className="text-red-400 truncate max-w-xs">{email.error_message}</span>
              )}
            </div>
          </div>
        </div>

        {/* Thread panel — always shows when expanded */}
        {expanded && (
          <ThreadPanel email={email} onClose={() => setExpanded(false)} />
        )}
      </div>
    </>
  )
}

/* ── Main Emails Page ───────────────────────────────────────── */
export default function Emails() {
  const [emails,   setEmails]   = useState([])
  const [total,    setTotal]    = useState(0)
  const [page,     setPage]     = useState(1)
  const [loading,  setLoading]  = useState(false)
  const [checking, setChecking] = useState(false)
  const [filter,   setFilter]   = useState('all')
  const autoCheckRef            = useRef(null)
  const pageRef                 = useRef(1)
  const checkingRef             = useRef(false)
  const cacheKey                = 'emails_v1'

  const load = async (p = 1, silent = false) => {
    if (!silent && emails.length === 0) setLoading(true)
    try {
      const res = await getEmails({ page: p, limit: 20 })
      setEmails(res.data.emails || [])
      setTotal(res.data.total || 0)
      setPage(p)
      pageRef.current = p
      try { sessionStorage.setItem(cacheKey, JSON.stringify(res.data)) } catch {}
    } catch {}
    finally { if (!silent) setLoading(false) }
  }

  // Auto-check replies in the background while the current rows stay visible.
  const silentCheckReplies = async () => {
    if (checkingRef.current) return
    checkingRef.current = true
    try {
      await load(pageRef.current, true)
      await checkReplies()
      await load(pageRef.current, true)
    } catch {
      try { await load(pageRef.current, true) } catch {}
    } finally {
      checkingRef.current = false
    }
  }

  useEffect(() => {
    try {
      const cached = JSON.parse(sessionStorage.getItem(cacheKey) || 'null')
      if (cached?.emails?.length) {
        setEmails(cached.emails)
        setTotal(cached.total || 0)
        setPage(cached.page || 1)
        pageRef.current = cached.page || 1
      }
    } catch {}
    load()
    silentCheckReplies()
    autoCheckRef.current = setInterval(silentCheckReplies, REPLY_REFRESH_INTERVAL_MS)
    return () => clearInterval(autoCheckRef.current)
  }, [])

  // Manual check replies (still available via button)
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
    filter === 'opened'    ? emails.filter(e => e.opened) :
    filter === 'pending'   ? emails.filter(e => !e.reply_received && e.status === 'sent') :
    filter === 'failed'    ? emails.filter(e => e.status === 'failed') :
    filter === 'scheduled' ? emails.filter(e => e.interview_scheduled) :
    emails

  const sentCount      = emails.filter(e => e.status === 'sent').length
  const openedCount    = emails.filter(e => e.opened).length
  const repliedCount   = emails.filter(e => e.reply_received).length
  const failedCount    = emails.filter(e => e.status === 'failed').length
  const scheduledCount = emails.filter(e => e.interview_scheduled).length

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="page-title">Email Logs</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {total} outreach emails tracked
            <span className="ml-2 text-xs text-emerald-500 inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
              Replies auto-update every 60s
            </span>
          </p>
        </div>
        <button onClick={handleCheckReplies} disabled={checking} className="btn-primary">
          <RefreshCw className={clsx('w-4 h-4', checking && 'animate-spin')} />
          {checking ? 'Checking...' : 'Check Replies Now'}
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
        {[
          { label: 'Sent',      value: sentCount,      icon: Send,          color: 'bg-blue-50 text-brand-500',      key: 'all'       },
          { label: 'Opened',    value: openedCount,    icon: Eye,           color: 'bg-cyan-50 text-cyan-500',       key: 'opened'    },
          { label: 'Replied',   value: repliedCount,   icon: MessageSquare, color: 'bg-emerald-50 text-emerald-500', key: 'replied'   },
          { label: 'Failed',    value: failedCount,    icon: AlertCircle,   color: 'bg-red-50 text-red-500',         key: 'failed'    },
          { label: 'Scheduled', value: scheduledCount, icon: Calendar,      color: 'bg-purple-50 text-purple-500',   key: 'scheduled' },
        ].map(s => (
          <div key={s.label}
            onClick={() => setFilter(s.key)}
            className={clsx(
              'card p-4 flex items-center gap-3 hover:shadow-card-hover hover:-translate-y-0.5 transition-all duration-200 cursor-pointer group',
              filter === s.key && 'ring-2 ring-brand-300'
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
          { key: 'opened',    label: 'Opened'       },
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
