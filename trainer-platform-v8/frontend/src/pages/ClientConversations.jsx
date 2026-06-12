import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  Building2,
  CalendarClock,
  Clock3,
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

function startOfDay(date) {
  const copy = new Date(date)
  copy.setHours(0, 0, 0, 0)
  return copy
}

function chatDateLabel(value) {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  const today = startOfDay(new Date())
  const target = startOfDay(date)
  const diffDays = Math.round((today.getTime() - target.getTime()) / 86400000)
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  return date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}

function chatTimeLabel(value) {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function fullMailDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return fmtDate(value)
  return date.toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function cleanMailBody(value = '') {
  let text = String(value || '')
  const splitPatterns = [
    /\n\s*On\s.+?wrote:\s*/is,
    /\n\s*From:\s.+?\n\s*Sent:\s.+?\n\s*To:\s.+/is,
    /\n\s*-{2,}\s*Original Message\s*-{2,}/i,
    /\n\s*_{8,}\s*/i,
  ]
  for (const pattern of splitPatterns) {
    const parts = text.split(pattern)
    if (parts.length > 1) {
      text = parts[0]
      break
    }
  }
  return text
    .split('\n')
    .filter(line => !line.trim().startsWith('>'))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
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
  if (['auto_sent', 'approved', 'confirmed_scheduled', 'sent'].includes(status)) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (['pending_approval', 'needs_manual_review', 'calendar_failed'].includes(status)) return 'border-amber-200 bg-amber-50 text-amber-700'
  if (['rejected', 'failed', 'trainer_email_failed'].includes(status)) return 'border-red-200 bg-red-50 text-red-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function sourceLabel(source = '') {
  const labels = {
    client_inbox: 'Client email',
    calhan_reply: 'Clahan reply',
    client_slot_options: 'Slot options',
    client_slot_reply: 'Client slot reply',
    client_slot_confirmation: 'Slot confirmation',
    client_interview_schedule: 'Schedule sent',
    client_message: 'Client message',
    google_calendar: 'Google Calendar',
    invoice: 'Invoice',
    client_po: 'Client PO',
  }
  return labels[source] || source.replaceAll('_', ' ') || 'Message'
}

function domainCounts(threads) {
  return threads.reduce((acc, thread) => {
    const key = thread.domain || 'Training'
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
}

function trainerKey(trainer = {}) {
  return String(trainer.trainer_id || trainer.trainer_name || trainer.name || 'general').toLowerCase()
}

function messageTrainerKey(message = {}) {
  const meta = message.meta || {}
  return String(meta.trainer_id || meta.trainer_name || '').toLowerCase()
}

function trainerNameFromMessage(message = {}) {
  const meta = message.meta || {}
  return meta.trainer_name || meta.trainer_id || ''
}

function buildTrainerItems(threads = []) {
  const rows = []
  threads.forEach(thread => {
    const seen = new Set()
    const trainers = [...(thread.trainers || [])]
    ;(thread.messages || []).forEach(message => {
      const name = trainerNameFromMessage(message)
      const key = messageTrainerKey(message)
      if (key && !trainers.some(item => trainerKey(item) === key)) {
        trainers.push({ trainer_id: (message.meta || {}).trainer_id || '', trainer_name: name })
      }
    })
    trainers
      .filter(item => trainerKey(item) !== 'general')
      .forEach(trainer => {
        const key = `${thread.thread_key}::${trainerKey(trainer)}`
        if (seen.has(key)) return
        seen.add(key)
        const relatedMessages = (thread.messages || []).filter(message => messageTrainerKey(message) === trainerKey(trainer))
        const latest = relatedMessages
          .slice()
          .sort((a, b) => messageTime(b.sort_at || b.sent_at) - messageTime(a.sort_at || a.sent_at))[0]
        rows.push({
          key,
          thread,
          trainer,
          trainer_name: trainer.trainer_name || trainer.name || trainer.trainer_id || 'Trainer',
          message_count: relatedMessages.length,
          latest_at: latest?.sent_at || thread.latest_at,
          preview: latest?.body || thread.last_preview || thread.last_subject || '',
        })
      })
    if (!trainers.length) {
      rows.push({
        key: `${thread.thread_key}::general`,
        thread,
        trainer: { trainer_id: '', trainer_name: 'General Client Thread' },
        trainer_name: 'General Client Thread',
        message_count: thread.message_count || 0,
        latest_at: thread.latest_at,
        preview: thread.last_preview || thread.last_subject || '',
      })
    }
  })
  return rows.sort((a, b) => messageTime(b.latest_at) - messageTime(a.latest_at))
}

function messagesForTrainer(thread, trainer) {
  const key = trainerKey(trainer)
  const messages = orderedThreadMessages(thread?.messages || [])
  if (key === 'general') return messages
  return messages.filter(message => {
    const source = message.source || ''
    const msgKey = messageTrainerKey(message)
    return msgKey === key || ['client_inbox', 'calhan_reply'].includes(source)
  })
}

function MessageBubble({ message, compact = false, mailNumber = 1 }) {
  const isSent = message.direction === 'sent'
  const isDraft = message.direction === 'draft'
  const isSystem = message.direction === 'system'
  const isReceived = message.direction === 'received'
  const Icon = isSystem ? CalendarClock : isSent ? Send : isDraft ? Sparkles : Mail
  const fromLabel = message.from_label || (isReceived ? 'Client' : 'Clahan Technologies')
  const toLabel = message.to_label || (isReceived ? 'Clahan Technologies' : 'Client')
  const displayBody = cleanMailBody(message.body) || 'No body captured.'

  return (
    <div className={clsx('flex min-w-0', isReceived ? 'justify-start' : 'justify-end', compact && 'h-full')}>
      <div className={clsx(
        'min-w-0 w-full overflow-hidden rounded-lg border shadow-sm',
        compact ? 'max-w-none' : 'max-w-3xl',
        isSent && 'border-blue-100 bg-blue-50',
        isDraft && 'border-violet-200 bg-violet-50',
        isReceived && 'border-slate-200 bg-white',
        isSystem && 'border-emerald-200 bg-emerald-50'
      )}>
        <div className={clsx(
          'border-b px-4 py-3',
          isSent && 'border-blue-100 bg-blue-100/60',
          isDraft && 'border-violet-200 bg-violet-100/60',
          isReceived && 'border-slate-200 bg-slate-50',
          isSystem && 'border-emerald-200 bg-emerald-100/60'
        )}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <span className={clsx(
                'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                isSent && 'bg-blue-600 text-white',
                isDraft && 'bg-violet-600 text-white',
                isReceived && 'bg-slate-100 text-slate-600',
                isSystem && 'bg-emerald-600 text-white'
              )}>
                <Icon className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-bold text-slate-950">Mail {String(mailNumber).padStart(2, '0')}</p>
                <p className="truncate text-[11px] font-semibold text-slate-500">{isDraft ? 'Draft' : sourceLabel(message.source)}</p>
              </div>
            </div>
            <span className={clsx('rounded-full border px-2 py-1 text-[11px] font-bold capitalize', statusClass(message.status))}>
              {message.status || (isDraft ? 'draft' : 'mail')}
            </span>
          </div>
          <div className="mt-3 grid min-w-0 gap-1 text-xs text-slate-600">
            <p className="min-w-0 break-words [overflow-wrap:anywhere]"><span className="font-bold text-slate-800">From:</span> {fromLabel}</p>
            <p className="min-w-0 break-words [overflow-wrap:anywhere]"><span className="font-bold text-slate-800">To:</span> {toLabel}</p>
            <p className="min-w-0 break-words [overflow-wrap:anywhere]"><span className="font-bold text-slate-800">Date:</span> {fullMailDateTime(message.sent_at || message.sort_at)}</p>
          </div>
        </div>
        <div className="min-w-0 p-4">
          <div className="mb-3 min-w-0 rounded-md border border-slate-200 bg-white/70 px-3 py-2">
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Subject</p>
            <p className="mt-0.5 min-w-0 break-words text-sm font-semibold text-slate-900 [overflow-wrap:anywhere]">{message.subject || '(No subject)'}</p>
          </div>
          <pre className="min-w-0 max-w-full whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-white/80 p-3 font-sans text-sm leading-6 text-slate-700 [overflow-wrap:anywhere]">{displayBody}</pre>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-4 py-2 text-xs text-slate-400">
          <span>{chatTimeLabel(message.sent_at) || fmtDate(message.sent_at)}</span>
          {message.meta?.meet_link && (
            <a href={message.meta.meet_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-emerald-700 hover:text-emerald-800">
              <Link2 className="h-3.5 w-3.5" /> Open Meet
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

function ParallelChat({ messages = [] }) {
  let lastDateLabel = ''
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="max-h-[680px] overflow-y-auto bg-slate-50 p-3 [scrollbar-gutter:stable]">
        {messages.length ? (
          <div className="space-y-3">
            {messages.map((message, index) => {
              const clientSide = message.direction === 'received'
              const key = `${message.source}-${message.message_id}-${index}`
              const dateLabel = chatDateLabel(message.sent_at || message.sort_at)
              const showDate = dateLabel && dateLabel !== lastDateLabel
              if (showDate) lastDateLabel = dateLabel
              if (message.direction === 'system') {
                return (
                  <div key={key} className="space-y-3">
                    {showDate && (
                      <div className="flex justify-center">
                        <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-bold text-slate-500 shadow-sm">
                          {dateLabel}
                        </span>
                      </div>
                    )}
                    <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
                      <span className="h-px bg-slate-200" />
                      <MessageBubble message={message} compact mailNumber={index + 1} />
                      <span className="h-px bg-slate-200" />
                    </div>
                  </div>
                )
              }
              return (
                <div key={key} className="space-y-3">
                  {showDate && (
                    <div className="flex justify-center">
                      <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-bold text-slate-500 shadow-sm">
                        {dateLabel}
                      </span>
                    </div>
                  )}
                  <div className={clsx('flex min-w-0', clientSide ? 'justify-start' : 'justify-end')}>
                    <div className="min-w-0 w-full lg:w-[82%]">
                      <MessageBubble message={message} compact mailNumber={index + 1} />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            No messages captured for this thread yet.
          </div>
        )}
      </div>
    </div>
  )
}

function TrainerListItem({ item, active, onClick }) {
  const thread = item.thread || {}
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'w-full rounded-lg border p-4 text-left transition hover:border-blue-200 hover:bg-white hover:shadow-sm',
        active ? 'border-blue-300 bg-white shadow-sm ring-2 ring-blue-500/10' : 'border-slate-200 bg-white/70'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white shadow-sm">
            {initials(item.trainer_name, thread.client_email)}
          </div>
          <div className="min-w-0">
            <p className="truncate font-bold text-slate-950">{item.trainer_name || 'Trainer'}</p>
            <p className="mt-0.5 truncate text-xs text-slate-500">{thread.client_name || thread.client_email || 'Client'}</p>
          </div>
        </div>
        <span className="shrink-0 text-xs font-semibold text-slate-400">{relativeTime(item.latest_at)}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-[11px] font-bold text-blue-700">
          {thread.domain || 'Training'}
        </span>
        {thread.requirement_id && (
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-bold text-slate-600">
            {thread.requirement_id}
          </span>
        )}
        <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-bold text-emerald-700">
          {item.message_count} msg
        </span>
      </div>
      <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500">{item.preview || 'No preview available'}</p>
    </button>
  )
}

export default function ClientConversations() {
  const [threads, setThreads] = useState([])
  const [clients, setClients] = useState([])
  const [domains, setDomains] = useState([])
  const [selectedPersonKey, setSelectedPersonKey] = useState('')
  const [q, setQ] = useState('')
  const [client, setClient] = useState('')
  const [domain, setDomain] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const trainerItems = useMemo(() => buildTrainerItems(threads), [threads])
  const selectedPerson = useMemo(
    () => trainerItems.find(item => item.key === selectedPersonKey) || trainerItems[0] || null,
    [trainerItems, selectedPersonKey]
  )
  const selected = useMemo(
    () => selectedPerson?.thread || null,
    [selectedPerson]
  )
  const selectedMessages = useMemo(
    () => messagesForTrainer(selected, selectedPerson?.trainer),
    [selected, selectedPerson]
  )
  const counts = useMemo(() => domainCounts(threads), [threads])

  const loadThreads = async (silent = false) => {
    if (silent) setRefreshing(true)
    else setLoading(true)
    try {
      const res = await api.get('/client-conversations', {
        params: {
          q: q || undefined,
          client: client || undefined,
          domain: domain || undefined,
          limit: 100,
        },
      })
      const nextThreads = res.data.threads || []
      setThreads(nextThreads)
      setClients(res.data.clients || [])
      setDomains(res.data.domains || [])
      const nextTrainerItems = buildTrainerItems(nextThreads)
      if (!selectedPersonKey || !nextTrainerItems.some(item => item.key === selectedPersonKey)) {
        setSelectedPersonKey(nextTrainerItems[0]?.key || '')
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
    <div className="min-w-0 space-y-5 overflow-x-hidden animate-fade-in">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-bold uppercase tracking-wide text-blue-700 shadow-sm">
            <MessageSquare className="h-3.5 w-3.5" /> Client Threads
          </div>
          <h1 className="mt-3 page-title">Client Conversation Threads</h1>
          <p className="mt-1 text-sm text-slate-500">
            Select a domain, click a person, and view that person-specific client and Clahan conversation.
          </p>
        </div>
        <button onClick={() => loadThreads(true)} className="btn-secondary text-sm" disabled={refreshing}>
          <RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} /> Refresh
        </button>
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[220px_290px_minmax(0,1fr)]">
        <aside className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-400">Hiring Domains</p>
          <button
            onClick={() => setDomain('')}
            className={clsx('mt-3 flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm font-bold', !domain ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}
          >
            All Domains <span>{threads.length}</span>
          </button>
          <div className="mt-2 max-h-[68vh] space-y-1 overflow-y-auto [scrollbar-gutter:stable]">
            {domains.map(item => (
              <button
                key={item}
                onClick={() => setDomain(item)}
                className={clsx('flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm font-semibold', domain === item ? 'bg-blue-50 text-blue-700 ring-1 ring-blue-100' : 'text-slate-600 hover:bg-slate-50')}
              >
                <span className="truncate">{item}</span>
                <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs">{counts[item] || ''}</span>
              </button>
            ))}
          </div>
        </aside>

        <aside className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="space-y-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={q}
                onChange={e => setQ(e.target.value)}
                placeholder="Search subject, body, client..."
                className="h-11 w-full rounded-full border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
              <select
                value={client}
                onChange={e => setClient(e.target.value)}
                className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400"
              >
                <option value="">All clients</option>
                {clients.map(item => (
                  <option key={item.email || item.name} value={item.email || item.name}>
                    {item.name || item.email} {item.company ? `- ${item.company}` : ''}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => { setQ(''); setClient(''); setDomain('') }}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-600 hover:bg-slate-50"
              >
                <Filter className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <p className="text-sm font-bold text-slate-950">{trainerItems.length} trainer{trainerItems.length === 1 ? '' : 's'}</p>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
          </div>
          <div className="mt-3 max-h-[72vh] space-y-3 overflow-y-auto pr-1 [scrollbar-gutter:stable]">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-32 animate-pulse rounded-lg border border-slate-200 bg-slate-100" />
              ))
            ) : trainerItems.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
                No trainer conversations found for this domain.
              </div>
            ) : (
              trainerItems.map(item => (
                <TrainerListItem
                  key={item.key}
                  item={item}
                  active={selectedPerson?.key === item.key}
                  onClick={() => setSelectedPersonKey(item.key)}
                />
              ))
            )}
          </div>
        </aside>

        <section className="min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm">
          {!selected ? (
            <div className="flex h-full min-h-[620px] items-center justify-center p-8 text-center text-slate-500">
              Select a domain and trainer name.
            </div>
          ) : (
            <div className="flex h-full min-h-[720px] flex-col">
              <header className="border-b border-slate-200 p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white">
                        {initials(selected.client_name, selected.client_email)}
                      </span>
                      <div>
                        <h2 className="text-lg font-bold text-slate-950">{selectedPerson?.trainer_name || 'Trainer'}</h2>
                        <p className="text-sm text-slate-500">{selected.client_name || selected.client_email || 'Client'}</p>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <span className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">
                        <Building2 className="h-3.5 w-3.5" /> {selected.client_company || 'Client'}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">
                        <UserRound className="h-3.5 w-3.5" /> {selected.domain || 'Training'}
                      </span>
                      {selected.requirement_id && (
                        <span className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-600">
                          <Link2 className="h-3.5 w-3.5" /> {selected.requirement_id}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
                    <div className="flex items-center gap-2 font-semibold text-slate-900">
                      <Clock3 className="h-4 w-4 text-slate-400" /> Latest activity
                    </div>
                    <p className="mt-1">{fmtDate(selected.latest_at)}</p>
                  </div>
                </div>
              </header>

              <div className="min-w-0 flex-1 p-5">
                <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50">
                  <div className="flex items-center justify-between border-b border-slate-200 p-4">
                    <div>
                      <p className="text-sm font-bold text-slate-950">Client and Clahan Conversation</p>
                      <p className="mt-0.5 text-xs text-slate-500">Client and Clahan messages shown in parallel.</p>
                    </div>
                    <MessageSquare className="h-5 w-5 text-slate-400" />
                  </div>
                  <div className="min-w-0 p-4">
                    <ParallelChat messages={selectedMessages} />
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
