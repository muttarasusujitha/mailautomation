import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  Building2,
  CalendarClock,
  CheckCircle2,
  Clock,
  Filter,
  Link2,
  Loader2,
  Mail,
  MessageSquare,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  UserRound,
} from 'lucide-react'
import api from '../utils/api'

function fmtDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function relativeTime(value) {
  if (!value) return ''
  const then = new Date(value).getTime()
  const diff = Math.max(0, Date.now() - then)
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function messageTime(value) {
  if (!value) return 0
  const parsed = new Date(value).getTime()
  return Number.isFinite(parsed) ? parsed : 0
}

function orderedThreadMessages(messages = []) {
  return [...messages].sort((a, b) => {
    const timeDiff = messageTime(a.sort_at || a.sent_at) - messageTime(b.sort_at || b.sent_at)
    if (timeDiff) return timeDiff
    return Number(a.sort_order || 50) - Number(b.sort_order || 50)
  })
}

function initials(name = '', email = '') {
  const source = name || email || 'Client'
  return source
    .split(/[.\s@_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]?.toUpperCase())
    .join('') || 'CL'
}

function statusClass(status = '') {
  if (['auto_sent', 'approved', 'confirmed_scheduled'].includes(status)) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (['pending_approval', 'needs_manual_review', 'calendar_failed'].includes(status)) return 'border-amber-200 bg-amber-50 text-amber-700'
  if (['rejected', 'failed', 'trainer_email_failed'].includes(status)) return 'border-red-200 bg-red-50 text-red-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function sourceLabel(source = '') {
  const labels = {
    client_inbox: 'Client email',
    calhan_reply: 'Calhan reply',
    client_slot_options: 'Slot options',
    client_slot_reply: 'Client slot reply',
    client_slot_confirmation: 'Slot confirmation',
    client_interview_schedule: 'Schedule sent',
    client_message: 'Client message',
    google_calendar: 'Google Calendar',
  }
  return labels[source] || source.replaceAll('_', ' ') || 'Message'
}

function MessageBubble({ message }) {
  const isSent = message.direction === 'sent'
  const isDraft = message.direction === 'draft'
  const isSystem = message.direction === 'system'
  const isReceived = message.direction === 'received'
  const Icon = isSystem ? CalendarClock : isSent ? Send : isDraft ? Sparkles : Mail

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_40px_minmax(0,1fr)] items-start gap-2">
      <div className={clsx(isReceived ? 'col-start-1 row-start-1' : 'col-start-3 row-start-1')}>
      <div className={clsx(
        'rounded-2xl border p-4 shadow-sm',
        isSent && 'border-blue-100 bg-blue-50',
        isDraft && 'border-violet-200 bg-violet-50',
        isReceived && 'border-slate-200 bg-white',
        isSystem && 'border-emerald-200 bg-emerald-50'
      )}>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className={clsx(
            'inline-flex h-7 w-7 items-center justify-center rounded-lg',
            isSent && 'bg-blue-600 text-white',
            isDraft && 'bg-violet-600 text-white',
            isReceived && 'bg-slate-100 text-slate-600',
            isSystem && 'bg-emerald-600 text-white'
          )}>
            <Icon className="h-3.5 w-3.5" />
          </span>
          <span className="text-sm font-bold text-slate-900">{message.from_label || (isReceived ? 'Client' : 'Calhan Technologies')}</span>
          <span className="text-xs text-slate-400">to {message.to_label || (isReceived ? 'Calhan Technologies' : 'Client')}</span>
          <span className={clsx('rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize', statusClass(message.status))}>
            {isDraft ? 'draft' : sourceLabel(message.source)}
          </span>
        </div>
        {message.subject && <p className="mb-2 text-sm font-semibold text-slate-800">{message.subject}</p>}
        <pre className="whitespace-pre-wrap font-sans text-sm leading-6 text-slate-700">{message.body || 'No body captured.'}</pre>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
          <span>{fmtDate(message.sent_at)}</span>
          {message.meta?.meet_link && (
            <a href={message.meta.meet_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-emerald-700 hover:text-emerald-800">
              <Link2 className="h-3.5 w-3.5" /> Open Meet
            </a>
          )}
        </div>
      </div>
      </div>
      <div className="col-start-2 row-start-1 flex flex-col items-center pt-3">
        <span className={clsx(
          'flex h-8 w-8 items-center justify-center rounded-full border-2 bg-white shadow-sm',
          isReceived && 'border-slate-200 text-slate-500',
          (isSent || isDraft) && 'border-blue-200 text-blue-600',
          isSystem && 'border-emerald-200 text-emerald-600'
        )}>
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="mt-1 w-px flex-1 bg-slate-200" />
      </div>
    </div>
  )
}

function ThreadListItem({ thread, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'w-full rounded-xl border p-4 text-left transition hover:border-blue-200 hover:bg-white hover:shadow-sm',
        active ? 'border-blue-300 bg-white shadow-sm ring-2 ring-blue-500/10' : 'border-white/80 bg-white/70'
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-sky-500 text-sm font-bold text-white shadow-sm">
          {initials(thread.client_name, thread.client_email)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className="truncate font-bold text-slate-950">{thread.client_name || 'Client'}</p>
            <span className="shrink-0 text-xs font-semibold text-slate-400">{relativeTime(thread.latest_at)}</span>
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500">{thread.client_email || thread.client_company || '-'}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded-lg border border-violet-200 bg-violet-50 px-2 py-0.5 text-[11px] font-bold text-violet-700">
              {thread.domain || 'Training'}
            </span>
            {thread.requirement_id && (
              <span className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-bold text-slate-600">
                {thread.requirement_id}
              </span>
            )}
            <span className="rounded-lg border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-bold text-sky-700">
              {thread.message_count} msg
            </span>
          </div>
          <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{thread.last_preview || thread.last_subject || 'No preview available'}</p>
        </div>
      </div>
    </button>
  )
}

export default function ClientConversations() {
  const [threads, setThreads] = useState([])
  const [clients, setClients] = useState([])
  const [domains, setDomains] = useState([])
  const [selectedKey, setSelectedKey] = useState('')
  const [q, setQ] = useState('')
  const [client, setClient] = useState('')
  const [domain, setDomain] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const selected = useMemo(
    () => threads.find(thread => thread.thread_key === selectedKey) || threads[0] || null,
    [threads, selectedKey]
  )
  const selectedMessages = useMemo(
    () => orderedThreadMessages(selected?.messages || []),
    [selected]
  )

  const loadThreads = async (silent = false) => {
    if (silent) setRefreshing(true)
    else setLoading(true)
    try {
      const res = await api.get('/client-conversations', {
        params: {
          q: q || undefined,
          client: client || undefined,
          domain: domain || undefined,
          limit: 80,
        },
      })
      const nextThreads = res.data.threads || []
      setThreads(nextThreads)
      setClients(res.data.clients || [])
      setDomains(res.data.domains || [])
      if (!selectedKey || !nextThreads.some(thread => thread.thread_key === selectedKey)) {
        setSelectedKey(nextThreads[0]?.thread_key || '')
      }
    } catch (e) {
      toast.error(e.message || 'Could not load client conversations')
      setThreads([])
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => loadThreads(false), 250)
    return () => clearTimeout(timer)
  }, [q, client, domain])

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-violet-200 bg-white/70 px-3 py-1 text-xs font-bold uppercase tracking-wide text-violet-700 shadow-sm">
            <MessageSquare className="h-3.5 w-3.5" /> Client Threads
          </div>
          <h1 className="mt-3 page-title">Client Conversation Threads</h1>
          <p className="mt-1 text-sm text-slate-500">
            View one client and Calhan Technologies conversation by domain, requirement, and Gmail thread.
          </p>
        </div>
        <button onClick={() => loadThreads(true)} className="btn-secondary text-sm" disabled={refreshing}>
          <RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} /> Refresh
        </button>
      </div>

      <section className="rounded-xl border border-white/80 bg-white/75 p-4 shadow-sm backdrop-blur">
        <div className="grid gap-3 lg:grid-cols-[1.3fr_1fr_1fr_auto]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={q}
              onChange={e => setQ(e.target.value)}
              placeholder="Search subject, body, client, requirement..."
              className="h-11 w-full rounded-lg border border-slate-200 bg-white/80 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/10"
            />
          </div>
          <select
            value={client}
            onChange={e => setClient(e.target.value)}
            className="h-11 rounded-lg border border-slate-200 bg-white/80 px-3 text-sm outline-none focus:border-blue-400"
          >
            <option value="">All clients</option>
            {clients.map(item => (
              <option key={item.email || item.name} value={item.email || item.name}>
                {item.name || item.email} {item.company ? `- ${item.company}` : ''}
              </option>
            ))}
          </select>
          <select
            value={domain}
            onChange={e => setDomain(e.target.value)}
            className="h-11 rounded-lg border border-slate-200 bg-white/80 px-3 text-sm outline-none focus:border-blue-400"
          >
            <option value="">All domains</option>
            {domains.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
          <button
            type="button"
            onClick={() => { setQ(''); setClient(''); setDomain('') }}
            className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 hover:bg-slate-50"
          >
            <Filter className="h-4 w-4" /> Clear
          </button>
        </div>
      </section>

      <div className="grid min-h-[620px] gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
        <aside className="rounded-xl border border-white/80 bg-white/55 p-3 shadow-sm backdrop-blur">
          <div className="mb-3 flex items-center justify-between px-1">
            <p className="text-sm font-bold text-slate-900">{threads.length} conversation{threads.length === 1 ? '' : 's'}</p>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
          </div>
          <div className="max-h-[72vh] space-y-3 overflow-y-auto pr-1">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-32 animate-pulse rounded-xl border border-white/80 bg-white/70" />
              ))
            ) : threads.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 bg-white/70 p-6 text-center text-sm text-slate-500">
                No client conversations found for this filter.
              </div>
            ) : (
              threads.map(thread => (
                <ThreadListItem
                  key={thread.thread_key}
                  thread={thread}
                  active={selected?.thread_key === thread.thread_key}
                  onClick={() => setSelectedKey(thread.thread_key)}
                />
              ))
            )}
          </div>
        </aside>

        <section className="rounded-xl border border-white/80 bg-white/75 shadow-sm backdrop-blur">
          {!selected ? (
            <div className="flex h-full min-h-[520px] items-center justify-center p-8 text-center text-slate-500">
              Select a client conversation to view the full thread.
            </div>
          ) : (
            <div className="flex h-full min-h-[620px] flex-col">
              <header className="border-b border-slate-200/70 p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-sky-500 text-sm font-bold text-white">
                        {initials(selected.client_name, selected.client_email)}
                      </span>
                      <div>
                        <h2 className="text-lg font-bold text-slate-950">{selected.client_name || 'Client'}</h2>
                        <p className="text-sm text-slate-500">{selected.client_email || selected.client_company || '-'}</p>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <span className="inline-flex items-center gap-1 rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs font-bold text-violet-700">
                        <Building2 className="h-3.5 w-3.5" /> {selected.client_company || 'Client'}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-lg border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-bold text-sky-700">
                        <UserRound className="h-3.5 w-3.5" /> {selected.domain || 'Training'}
                      </span>
                      {selected.requirement_id && (
                        <span className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">
                          <Link2 className="h-3.5 w-3.5" /> {selected.requirement_id}
                        </span>
                      )}
                      <span className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700">
                        <CheckCircle2 className="h-3.5 w-3.5" /> {selected.message_count} messages
                      </span>
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-500">
                    <div className="flex items-center gap-2 font-semibold text-slate-900">
                      <Clock className="h-4 w-4 text-slate-400" /> Latest activity
                    </div>
                    <p className="mt-1">{fmtDate(selected.latest_at)}</p>
                  </div>
                </div>
              </header>

              <div className="flex-1 space-y-4 overflow-y-auto p-5">
                {selectedMessages.length ? (
                  selectedMessages.map((message, index) => (
                    <MessageBubble key={`${message.source}-${message.message_id}-${index}`} message={message} />
                  ))
                ) : (
                  <div className="rounded-xl border border-dashed border-slate-200 bg-white/70 p-8 text-center text-sm text-slate-500">
                    No messages captured for this thread yet.
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
