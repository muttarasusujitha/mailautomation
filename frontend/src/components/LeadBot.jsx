import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Bot, Pause, Play, Search } from 'lucide-react'
import api from '../utils/api'

function stamp(value) {
  if (!value) return ''
  const text = String(value)
  return text.endsWith('Z') || text.includes('+') ? text : `${text} (UTC)`
}

function domainList(value) {
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean).slice(0, 4)
}

function outcomeWarnings(config) {
  const messages = []
  const push = (value) => {
    const text = typeof value === 'string' ? value.trim() : String(value?.error || '').trim()
    if (text && !messages.includes(text)) messages.push(text)
  }
  for (const outcome of config?.domain_outcomes || []) {
    push(outcome.primary_error)
    for (const warning of outcome.warnings || []) push(warning)
  }
  push(config?.last_error)
  return messages
}

export default function LeadBot({ mode = 'trainer', onRefresh, onUseDomains, onViewResults }) {
  const isTrainer = mode === 'trainer'
  const [config, setConfig] = useState(null)
  const [domainsText, setDomainsText] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let stop = false
    const pull = async (replaceDomains) => {
      try {
        const res = await api.get(`/linkedin-leads/bot/${mode}`)
        if (stop) return
        setConfig(res.data || {})
        if (replaceDomains) setDomainsText((res.data?.domains || []).join(', '))
      } catch (error) {
        if (!stop) toast.error(error.message || 'Unable to load the collection bot')
      }
    }
    pull(true)
    const timer = window.setInterval(() => pull(false), 15000)
    return () => {
      stop = true
      window.clearInterval(timer)
    }
  }, [mode])

  const save = async (enabled) => {
    const domains = domainList(domainsText)
    if (isTrainer && enabled && !domains.length) {
      toast.error('Enter at least one trainer domain.')
      return
    }
    setSaving(true)
    try {
      const res = await api.put(`/linkedin-leads/bot/${mode}`, {
        enabled,
        domain_source: isTrainer ? 'manual' : (config?.domain_source || 'all'),
        domains: domains.length ? domains : (config?.domains || []),
        interval_minutes: isTrainer ? 60 : 10,
      })
      setConfig(res.data || {})
      setDomainsText((res.data?.domains || domains).join(', '))
      toast.success(enabled ? 'Collection bot enabled' : 'Collection bot paused')
      if (enabled) onRefresh?.()
    } catch (error) {
      toast.error(error.message || 'Unable to save the collection bot')
    } finally {
      setSaving(false)
    }
  }

  const warnings = outcomeWarnings(config)
  const runLabel = config?.status || 'not started'

  return (
    <section className="linkedin-glow-panel rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-4 space-y-3">
      <div className="flex items-start gap-3">
        <Bot className="mt-0.5 h-5 w-5 text-blue-700" />
        <div>
          <h2 className="text-sm font-bold text-slate-900">
            {isTrainer ? 'Automatic trainer profile collection' : 'Automatic client requirement collection'}
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            {isTrainer
              ? 'Searches trainer profiles every hour while enabled. Uses public results and your connected LinkedIn account. No paid API or outreach emails. Matches require review.'
              : 'Searches training-request posts every ten minutes while enabled. Uses public results and your connected LinkedIn account. No paid API or outreach emails. Matches require review.'}
          </p>
        </div>
      </div>

      <label className="block text-xs font-semibold text-slate-600">
        Domains (up to four)
        <input
          className="input mt-1 bg-[#eaf6ff]"
          value={domainsText}
          onChange={event => setDomainsText(event.target.value)}
          placeholder={isTrainer ? 'DevOps trainer, Python, soft skills' : 'Optional when all-domain collection is on'}
        />
      </label>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => save(true)} disabled={saving} className="btn-primary text-sm disabled:opacity-50">
          <Play className="h-4 w-4" /> Enable / save bot
        </button>
        <button type="button" onClick={() => save(false)} disabled={saving} className="btn-secondary text-sm disabled:opacity-50">
          <Pause className="h-4 w-4" /> Pause bot
        </button>
        {onUseDomains && (
          <button type="button" onClick={() => onUseDomains(domainList(domainsText))} className="btn-secondary text-sm">
            <Search className="h-4 w-4" /> Use bot domains for search
          </button>
        )}
        <button type="button" onClick={() => (onViewResults || onRefresh)?.()} className="btn-secondary text-sm">
          View collected profiles
        </button>
      </div>

      <p className="text-sm font-semibold text-slate-800">
        {config?.enabled ? 'Enabled' : 'Paused'} · Last automatic run: {runLabel} · Found: {config?.found || 0} · Saved: {config?.saved || 0}
      </p>
      <p className="text-xs text-slate-500">This panel shows the automatic collection run. Searches started with Find Profiles or Find Client Posts report their results below.</p>
      {(config?.domain_outcomes || []).map(outcome => (
        <p key={outcome.domain} className="text-sm text-slate-600">
          {outcome.domain}: {outcome.matched ?? 0} found (target: {outcome.target ?? 0}).
          {!outcome.target_met && (outcome.matched > 0
            ? ' Partial results; the target is not guaranteed.'
            : ' Target not reached.')}
        </p>
      ))}
      {warnings.map(message => <p key={message} className="text-sm text-amber-800">{message}</p>)}
      {isTrainer && <p className="text-xs text-slate-500">Saved counts new profiles only. Existing profiles keep their original domain label.</p>}
      {(config?.last_finished || config?.next_run) && (
        <p className="text-xs text-slate-500">
          {config.last_finished ? `Last completed: ${stamp(config.last_finished)}` : 'Not completed yet'}
          {config.next_run ? ` · Next run: ${stamp(config.next_run)}` : ''}
        </p>
      )}
    </section>
  )
}
