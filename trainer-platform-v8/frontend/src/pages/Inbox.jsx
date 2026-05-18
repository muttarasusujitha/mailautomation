import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  AlertTriangle, Bot, CheckCircle2, Clock, ExternalLink, Mail, MessageSquare,
  RefreshCw, Send, ShieldCheck, SlidersHorizontal, Trash2, Zap
} from 'lucide-react'
import api from '../utils/api'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'pending_approval', label: 'Pending Approval' },
  { key: 'auto_sent', label: 'Auto Sent' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
]

const STATUS_LABELS = {
  pending_approval: 'Pending Approval',
  auto_sent: 'Auto Sent',
  approved: 'Approved',
  rejected: 'Rejected',
  spam: 'Spam',
}

function initials(name = '', email = '') {
  const source = name || email
  return source
    .split(/[.\s@_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]?.toUpperCase())
    .join('') || 'CL'
}

function relativeTime(value) {
  if (!value) return ''
  const then = new Date(value).getTime()
  const diff = Math.max(0, Date.now() - then)
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

function confidenceClass(score) {
  if (score >= 0.9) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (score >= 0.7) return 'bg-amber-50 text-amber-700 border-amber-200'
  return 'bg-red-50 text-red-700 border-red-200'
}

function urgencyClass(urgency = '') {
  if (urgency === 'urgent') return 'bg-red-50 text-red-700 border-red-200'
  if (urgency === 'flexible') return 'bg-slate-50 text-slate-600 border-slate-200'
  return 'bg-blue-50 text-blue-700 border-blue-200'
}

function Fact({ label, value }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <span className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600">
      {label}: <span className="ml-1 text-slate-900">{value}</span>
    </span>
  )
}

function EmailCard({ email, onApprove, onReject, onRegenerate }) {
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState(email.generated_reply?.body || '')
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState('')
  const navigate = useNavigate()
  const extracted = email.extracted || {}
  const reply = email.generated_reply || {}
  const confidence = Number(email.confidence ?? extracted.confidence ?? 0)
  const missing = extracted.needs_clarification || []
  const company = extracted.client_company || email.from_email?.split('@')[1] || 'Client'

  useEffect(() => {
    setBody(email.generated_reply?.body || '')
  }, [email.generated_reply?.body])

  const approve = async () => {
    setBusy('approve')
    try {
      await onApprove(email.email_id, { body, subject: reply.subject })
    } finally {
      setBusy('')
    }
  }

  const regenerate = async () => {
    setBusy('regenerate')
    try {
      await onRegenerate(email.email_id, instruction)
      setInstruction('')
      setOpen(true)
    } finally {
      setBusy('')
    }
  }

  return (
    <article className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex gap-3 min-w-0">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-blue-50 text-sm font-bold text-blue-700">
              {initials(email.from_name, email.from_email)}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold text-slate-900">{email.from_name || 'Client'}</h3>
                <span className="text-xs text-slate-400">{company}</span>
                <span className="text-xs text-slate-400">{relativeTime(email.received_at)}</span>
              </div>
              <p className="mt-1 truncate text-sm font-medium text-slate-800">{email.subject}</p>
              <p className="mt-2 text-sm leading-6 text-slate-600">{extracted.email_summary || 'No summary available yet.'}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 lg:justify-end">
            {email.auto_send_eligible && (
              <span className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                <Zap className="h-3.5 w-3.5" /> Auto-send eligible
              </span>
            )}
            <span className={clsx('rounded-lg border px-2.5 py-1 text-xs font-semibold', urgencyClass(extracted.urgency))}>
              {extracted.urgency || 'normal'}
            </span>
            <span className={clsx('rounded-lg border px-2.5 py-1 text-xs font-semibold', confidenceClass(confidence))}>
              {Math.round(confidence * 100)}%
            </span>
            <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">
              {STATUS_LABELS[email.status] || email.status}
            </span>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700">
            {extracted.technology_needed || 'Technology pending'}
          </span>
          <Fact label="Participants" value={extracted.participant_count} />
          <Fact label="Duration" value={extracted.duration_days ? `${extracted.duration_days} days` : extracted.duration_hours ? `${extracted.duration_hours} hours` : ''} />
          <Fact label="Mode" value={extracted.mode} />
          <Fact label="Budget" value={extracted.budget_total ? `${extracted.budget_currency || ''} ${extracted.budget_total}` : extracted.budget_per_day ? `${extracted.budget_currency || ''} ${extracted.budget_per_day}/day` : ''} />
        </div>

        {!!missing.length && (
          <div className="mt-3 flex flex-wrap gap-2">
            {missing.map(item => (
              <span key={item} className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700">
                <AlertTriangle className="h-3.5 w-3.5" /> {item}
              </span>
            ))}
          </div>
        )}

        {open && (
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Original Email</label>
              <div className="max-h-72 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700 whitespace-pre-wrap">
                {email.clean_body || email.raw_body || 'No body captured.'}
              </div>
            </div>
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Calhan Technologies Reply</label>
              <textarea
                value={body}
                onChange={e => setBody(e.target.value)}
                className="min-h-72 w-full resize-y rounded-lg border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-800 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10"
              />
            </div>
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button onClick={() => setOpen(v => !v)} className="btn-secondary text-sm">
            <Mail className="h-4 w-4" /> {open ? 'Collapse' : 'Review Draft'}
          </button>
          <button onClick={approve} disabled={busy === 'approve' || email.status === 'approved' || email.status === 'auto_sent'} className="btn-primary text-sm disabled:opacity-50">
            {busy === 'approve' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Approve and Send
          </button>
          <div className="flex min-w-[260px] flex-1 items-center gap-2">
            <input
              value={instruction}
              onChange={e => setInstruction(e.target.value)}
              placeholder="Optional instruction for regeneration"
              className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10"
            />
            <button onClick={regenerate} disabled={busy === 'regenerate'} className="btn-secondary text-sm">
              {busy === 'regenerate' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
              Regenerate
            </button>
          </div>
          <button onClick={() => onReject(email.email_id)} className="btn-secondary text-sm text-red-600 hover:bg-red-50">
            <Trash2 className="h-4 w-4" /> Reject
          </button>
          {email.requirement_id && (
            <button onClick={() => navigate('/requirements')} className="btn-secondary text-sm">
              <ExternalLink className="h-4 w-4" /> View Requirement
            </button>
          )}
        </div>
      </div>
    </article>
  )
}

export default function Inbox() {
  const [filter, setFilter] = useState('all')
  const [emails, setEmails] = useState([])
  const [stats, setStats] = useState({})
  const [logs, setLogs] = useState([])
  const [gmailStatus, setGmailStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [clientInboxCfg, setClientInboxCfg] = useState({})
  const [autoSendEnabled, setAutoSendEnabled] = useState(false)
  const [autoSendThreshold, setAutoSendThreshold] = useState(92)

  const queryStatus = filter === 'all' ? '' : filter
  const connected = !!gmailStatus?.connected

  const fetchInbox = async () => {
    setLoading(true)
    try {
      const res = await api.get('/inbox', { params: { status: queryStatus, limit: 50 } })
      setEmails(res.data.emails || [])
      setStats(res.data.stats || {})
      setLogs(res.data.whatsapp_logs || [])
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  const fetchStatus = async () => {
    try {
      const res = await api.get('/gmail/auth-status')
      setGmailStatus(res.data)
    } catch {
      setGmailStatus({ connected: false })
    }
  }

  const fetchSettings = async () => {
    try {
      const res = await api.get('/admin/settings')
      const cfg = res.data.clientInboxCfg || {}
      setClientInboxCfg(cfg)
      setAutoSendEnabled(!!cfg.autoSendEnabled)
      setAutoSendThreshold(Number(cfg.autoSendThreshold || 92))
    } catch {}
  }

  useEffect(() => {
    fetchInbox()
  }, [filter])

  useEffect(() => {
    fetchStatus()
    fetchSettings()
  }, [])

  const saveAutoSend = async (enabled = autoSendEnabled, threshold = autoSendThreshold) => {
    setAutoSendEnabled(enabled)
    setAutoSendThreshold(threshold)
    try {
      await api.post('/admin/settings', {
        clientInboxCfg: {
          ...clientInboxCfg,
          autoSendEnabled: enabled,
          autoSendThreshold: threshold,
        },
      })
      setClientInboxCfg(prev => ({ ...prev, autoSendEnabled: enabled, autoSendThreshold: threshold }))
      toast.success('Auto-send settings saved')
    } catch (e) {
      toast.error(e.message)
    }
  }

  const approve = async (emailId, payload) => {
    await api.post(`/inbox/${emailId}/approve`, payload)
    toast.success('Reply sent from Calhan Technologies')
    fetchInbox()
  }

  const reject = async (emailId) => {
    await api.post(`/inbox/${emailId}/reject`)
    toast.success('Email rejected')
    fetchInbox()
  }

  const regenerate = async (emailId, instruction) => {
    const res = await api.post(`/inbox/${emailId}/regenerate-reply`, { instruction })
    setEmails(items => items.map(item =>
      item.email_id === emailId ? { ...item, generated_reply: res.data.generated_reply } : item
    ))
    toast.success('Reply regenerated')
  }

  const connectGmail = async () => {
    try {
      if (!connected) {
        const res = await api.get('/gmail/oauth-url')
        window.location.href = res.data.auth_url
        return
      }

      await api.post('/gmail/renew-watch')
      toast.success('Gmail watch renewed')
      fetchStatus()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const statItems = useMemo(() => [
    { label: 'Today', value: stats.today || 0, icon: Clock },
    { label: 'Pending Approval', value: stats.pending_approval || 0, icon: AlertTriangle },
    { label: 'Auto Sent', value: stats.auto_sent || 0, icon: ShieldCheck },
    { label: 'Requirements Created', value: stats.requirements_created || 0, icon: CheckCircle2 },
  ], [stats])

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Mail className="h-6 w-6 text-blue-500" /> Client Inbox
          </h1>
          <p className="mt-1 text-sm text-slate-500">AI reads and drafts replies automatically</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className={clsx(
            'inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold',
            connected ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'
          )}>
            <span className={clsx('h-2 w-2 rounded-full', connected ? 'bg-emerald-500' : 'bg-red-500')} />
            {connected ? 'Connected' : 'Not Connected'}
          </span>
          <button onClick={connectGmail} className="btn-secondary text-sm">
            <RefreshCw className="h-4 w-4" /> {connected ? 'Renew Watch' : 'Connect Gmail'}
          </button>
          <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
            <SlidersHorizontal className="h-4 w-4 text-slate-400" />
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={autoSendEnabled}
                onChange={e => saveAutoSend(e.target.checked, autoSendThreshold)}
              />
              Auto-send
            </label>
            <input
              type="range"
              min="85"
              max="99"
              value={autoSendThreshold}
              onChange={e => setAutoSendThreshold(Number(e.target.value))}
              onMouseUp={() => saveAutoSend(autoSendEnabled, autoSendThreshold)}
              className="w-24"
            />
            <span className="text-xs font-semibold text-slate-500">{autoSendThreshold}%</span>
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {statItems.map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-500">{label}</span>
              <Icon className="h-4 w-4 text-blue-500" />
            </div>
            <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={clsx(
              'rounded-lg px-3 py-2 text-sm font-semibold transition',
              filter === tab.key ? 'bg-blue-600 text-white shadow-sm' : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-400">
          <RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Loading client inbox
        </div>
      ) : emails.length ? (
        <div className="space-y-4">
          {emails.map(email => (
            <EmailCard
              key={email.email_id}
              email={email}
              onApprove={approve}
              onReject={reject}
              onRegenerate={regenerate}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white py-16 text-center text-slate-400">
          <Mail className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p>No client emails in this view</p>
        </div>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-emerald-500" />
          <h2 className="text-sm font-bold text-slate-900">Recent WhatsApp Notifications</h2>
        </div>
        {logs.length ? (
          <div className="divide-y divide-slate-100">
            {logs.map(log => (
              <div key={log.whatsapp_id} className="py-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-slate-700">{log.status}</span>
                  <span className="text-xs text-slate-400">{relativeTime(log.created_at)}</span>
                </div>
                <p className="mt-1 text-slate-500">{log.body}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400">No WhatsApp notifications yet.</p>
        )}
      </section>
    </div>
  )
}
