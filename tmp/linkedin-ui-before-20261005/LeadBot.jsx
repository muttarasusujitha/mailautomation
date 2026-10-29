import { useEffect, useRef, useState } from 'react'
import api from '../utils/api'

export default function LeadBot({ mode, onRefresh, onUseDomains, onViewResults }) {
  const [status, setStatus] = useState(null)
  const [domains, setDomains] = useState('')
  const [domainSource, setDomainSource] = useState('manual')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const refresh = useRef(onRefresh)
  refresh.current = onRefresh
  useEffect(() => {
    let active = true
    let previous
    let initialized = false
    setStatus(null)
    setDomains('')
    setDomainSource('manual')
    const load = async () => {
      try {
        const { data } = await api.get(`/linkedin-leads/bot/${mode}`)
        if (!active) return
        setStatus(data)
        setError('')
        if (!initialized) {
          setDomains((data.domains || []).join(', '))
          setDomainSource(data.domain_source === 'it_catalog' ? 'all' : data.domain_source || 'manual')
          initialized = true
        }
        if (data.last_finished && data.last_finished !== previous) refresh.current?.()
        previous = data.last_finished
      } catch { if (active) setError('Cannot reach the lead bot service') }
    }
    load()
    const timer = setInterval(load, 15000)
    return () => { active = false; clearInterval(timer) }
  }, [mode])
  const save = async enabled => {
    setSaving(true)
    try {
      const { data } = await api.put(`/linkedin-leads/bot/${mode}`, {
        enabled, domain_source: domainSource, domains: domains.split(',').map(x => x.trim()).filter(Boolean), interval_minutes: mode === 'client' ? 10 : 60,
      })
      setStatus(data); setDomains((data.domains || []).join(', ')); setError('')
      if (enabled && domainSource === 'manual') onUseDomains?.(data.domains || [])
    } catch (e) { setError(e.message || 'Unable to save collection settings.') }
    finally { setSaving(false) }
  }
  return <section className="rounded-xl border border-slate-200 p-4 space-y-2">
    <h2 className="font-semibold">Automatic {mode === 'trainer' ? 'trainer profile' : 'client requirement'} collection</h2>
    <p className="text-sm">{mode === 'client' ? 'Scans training-request posts every 10 minutes. All domains includes every training request found, including non-IT and unclassified requests.' : 'Searches trainer profiles every hour while enabled.'} Uses public results and your connected LinkedIn account. No paid API or outreach emails. Matches require review.</p>
    {mode === 'client' && <label className="block text-sm">Domains to search
      <select className="input w-full" value={domainSource} onChange={e => setDomainSource(e.target.value)}>
        <option value="all">All domains — every training requirement found</option>
        <option value="manual">Choose up to four domains</option>
      </select>
    </label>}
    {domainSource === 'manual' && <label className="block text-sm">Domains (up to four)
      <input className="input w-full" value={domains} onChange={e => setDomains(e.target.value)} placeholder="Python, AWS" />
    </label>}
    {domainSource === 'all' && <div className="text-sm">
      <p>Domain labels help organize posts; they do not exclude requirements. Requests without a recognized domain appear as Unclassified. Each source post is saved once.</p>
    </div>}
    <button className="btn-primary" disabled={saving || !status} onClick={() => save(true)}>Enable / save bot</button>{' '}
    <button className="btn-secondary" disabled={saving || !status} onClick={() => save(false)}>Pause bot</button>
    {onUseDomains && domainSource === 'manual' && <button className="btn-secondary" disabled={!status} onClick={() => onUseDomains(status.domains || [])}>Use bot domains for search</button>}
    {onViewResults && <button className="btn-secondary" onClick={onViewResults}>{mode === 'client' ? 'View collected client requests' : 'View collected profiles'}</button>}
    <p className="text-sm" role="status">{status?.enabled ? 'Enabled' : 'Paused'} · {status?.status || 'Not run'} · Found: {status?.found || 0} · Saved: {status?.saved || 0}</p>
    {(status?.domain_outcomes || []).filter(item => mode !== 'client' || item.matched > 0).map(item => <p key={item.domain} className="text-sm">
      {item.domain}: {item.matched} found{item.target != null && ` (target: ${item.target})`}. {item.reason}
      {item.target != null && !item.target_met && ' Partial results; the target is not guaranteed.'}
      {' '}{item.warnings?.map(warning => typeof warning === 'string' ? warning : warning.error).filter(Boolean).join(' ')}
    </p>)}
    {(status?.scan_warnings || []).map((warning, index) => <p key={index} className="text-sm text-amber-700">{warning.error}</p>)}
    {status?.last_finished && <p className="text-sm">{mode === 'client' ? `${status.scanned_posts || 0} training-request posts scanned. Saved counts new posts only; previously saved posts are updated.` : 'Saved counts new profiles only. Existing profiles keep their original domain label.'}</p>}
    <p className="text-sm">Last completed: {status?.last_finished || 'Never'} · Next run: {status?.enabled ? status.next_run || 'Pending' : 'Paused'} (UTC)</p>
    {(error || status?.last_error || status?.catalog_error) && <p role="alert" className="text-red-600">{error || status.last_error || status.catalog_error}</p>}
  </section>
}
