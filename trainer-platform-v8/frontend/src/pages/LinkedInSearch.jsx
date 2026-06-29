import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  BriefcaseBusiness, CheckCircle2, ExternalLink, Globe2, Mail, RefreshCw,
  Search, Send, ShieldCheck, Target, Trash2, Users,
} from 'lucide-react'
import api from '../utils/api'
import { LinkedInLeadVerifyButton, TrustLegend, VerificationBadge } from '../components/VerificationBadge'

const STATUS = ['all', 'new', 'reviewed', 'contacted', 'converted', 'rejected']
const STATUS_LABELS = {
  all: 'All',
  new: 'New',
  reviewed: 'Reviewed',
  contacted: 'Contacted',
  converted: 'Converted',
  rejected: 'Rejected',
}

function statusClass(status) {
  if (status === 'converted') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'contacted') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'rejected') return 'border-red-200 bg-red-50 text-red-700'
  if (status === 'reviewed') return 'border-violet-200 bg-violet-50 text-violet-700'
  return 'border-amber-200 bg-amber-50 text-amber-700'
}

function relativeTime(value) {
  if (!value) return ''
  const diff = Math.max(0, Date.now() - new Date(value).getTime())
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? '' : 's'} ago`
  const days = Math.floor(hrs / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

function initials(value) {
  const words = String(value || '').replace(/[^a-zA-Z0-9\s]/g, ' ').split(/\s+/).filter(Boolean)
  return (words[0]?.[0] || 'L') + (words[1]?.[0] || '')
}

function leadDomain(lead) {
  return String(lead?.domain || '').trim() || 'Other'
}

function leadSearchText(lead) {
  return [
    lead?.domain,
    lead?.trainer_name,
    lead?.headline,
    lead?.profile_text,
    lead?.company_name,
    lead?.contact_name,
    lead?.post_text,
    lead?.notes,
  ].join(' ').toLowerCase()
}

function isTrainerProviderProfile(lead) {
  return Boolean(lead)
}

function buildLinkedInProfileQueries(domain) {
  const d = String(domain || '').trim()
  if (!d) return []
  return [
    `"${d}" trainer India site:linkedin.com/in`,
    `"${d}" "corporate trainer" India site:linkedin.com/in`,
    `"${d}" "freelance trainer" India site:linkedin.com/in`,
    `"${d}" "technical trainer" India site:linkedin.com/in`,
    `"${d}" "training consultant" India site:linkedin.com/in`,
    `"${d}" instructor India site:linkedin.com/in`,
    `"${d}" trainer Bangalore OR Hyderabad OR Mumbai OR Pune site:linkedin.com/in`,
    `"${d}" trainer India linkedin profile`,
    `"${d}" trainer India "years experience" linkedin`,
    `"${d}" "freelance trainer" India contact email linkedin`,
  ].map(q => ({ domain: d, q, intent: 'trainer' }))
}

function buildClientPostQueries(domain) {
  const d = String(domain || '').trim()
  const queries = d ? [
    `"${d}" "trainer required" India linkedin 2025`,
    `"${d}" "corporate trainer needed" India`,
    `"${d}" "training requirement" India company`,
    `"need ${d} trainer" India HR`,
    `"${d}" "looking for trainer" India`,
    `"${d}" "technical training requirement" India`,
  ] : [
    `"trainer required" India linkedin corporate 2025`,
    `"looking for trainer" India IT company 2025`,
    `"training requirement" India corporate immediate`,
    `"need trainer" India company HR linkedin`,
  ]
  return queries.map(query => ({ domain: d, q: query, intent: 'client_requirement' }))
}

function skippedReasonSummary(skipped = []) {
  const counts = skipped.reduce((acc, item) => {
    const reason = item?.reason || 'skipped'
    acc[reason] = (acc[reason] || 0) + 1
    return acc
  }, {})
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([reason, count]) => `${count} ${reason}`)
    .join(', ')
}

export default function LinkedInSearch() {
  const [mode, setMode] = useState('client')
  const [leads, setLeads] = useState([])
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')
  const [selectedDomain, setSelectedDomain] = useState('all')
  const [searchDomains, setSearchDomains] = useState('')
  const [loading, setLoading] = useState(false)
  const [searching, setSearching] = useState(false)
  const [deletingDomain, setDeletingDomain] = useState('')
  const [verifyingLead, setVerifyingLead] = useState('')

  const isTrainer = mode === 'trainer'

  const load = async () => {
    setLoading(true)
    try {
      const endpoint = isTrainer ? '/trainer-profile-leads' : '/client-leads'
      const res = await api.get(endpoint, { params: { status: filter, q, limit: 150 } })
      const rows = res.data.leads || []
      setLeads(isTrainer ? rows.filter(isTrainerProviderProfile) : rows)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [filter, mode])
  useEffect(() => {
    setSelectedDomain('all')
    setSearchDomains(isTrainer ? 'Python' : '')
  }, [mode, isTrainer])

  const runSearch = async () => {
    setSearching(true)
    try {
      const domains = searchDomains.split(',').map(item => item.trim()).filter(Boolean)
      const endpoint = isTrainer ? '/trainer-profile-leads/search-public' : '/client-leads/search-public'

      // ── CREDIT-SAFE payload ─────────────────────────────────────────────
      // max_queries:  8  = uses ~8-24 Tavily credits per run (was 180-480!)
      // max_results:  3  = 3 results per query (was 5-10)
      // max_domains:  4  = only top 4 IT domains at a time
      // deep_search: false = use high-signal phrases only (saves 6x credits)
      const payload = {
        source:      isTrainer ? 'linkedin' : undefined,
        max_results: isTrainer ? 8 : 3,
        max_queries: isTrainer ? 24 : 8,
        max_domains: 4,
        concurrency: 3,
        deep_search: false,
        deep_enrich: isTrainer,
      }
      if (domains.length) {
        payload.domains = domains
      }
      if (isTrainer && domains.length) {
        const queries = domains.flatMap(buildLinkedInProfileQueries)
        payload.queries = queries
        payload.max_queries = queries.length
        payload.concurrency = 5
      }
      if (!isTrainer) {
        const queries = (domains.length ? domains : ['']).flatMap(buildClientPostQueries)
        payload.queries = queries
        payload.max_queries = queries.length
        payload.max_results = 4
        payload.concurrency = 4
      }
      const res = await api.post(endpoint, payload)
      const savedCount = res.data.saved_count || 0
      const skippedCount = res.data.skipped_count || 0
      if (savedCount) {
        toast.success(`Saved ${savedCount} public result${savedCount === 1 ? '' : 's'}`)
      } else if (res.data.search_error) {
        toast.error(`Public search failed: ${res.data.search_error}`)
      } else if (isTrainer && skippedCount) {
        const reasonText = skippedReasonSummary(res.data.skipped)
        toast(`No new profiles saved; ${skippedCount} checked (${reasonText || 'mostly duplicates/no profile match'})`)
      } else {
        toast.success('No new public results saved')
      }
      if (isTrainer && (res.data.saved_count || 0) > 0) {
        const enrichResults = await Promise.allSettled(
          domains.map(domain => api.post('/trainer-profile-leads/enrich-public-emails', {
            domain,
            source: 'linkedin',
            limit: 200,
            deep_link_scan: true,
            fetch_source_page: true,
          }))
        )
        const enrichedCount = enrichResults.reduce((total, item) => (
          item.status === 'fulfilled' ? total + (item.value.data.enriched_count || 0) : total
        ), 0)
        if (enrichedCount) toast.success(`Fetched ${enrichedCount} verified public email${enrichedCount === 1 ? '' : 's'} from resumes/links`)
      }
      setFilter('all')
      setSelectedDomain('all')
      setQ('')
      const listEndpoint = isTrainer ? '/trainer-profile-leads' : '/client-leads'
      const listRes = await api.get(listEndpoint, { params: { status: 'all', q: '', limit: 150 } })
      setLeads(listRes.data.leads || [])
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSearching(false)
    }
  }

  const patchLead = async (lead, payload) => {
    try {
      const endpoint = isTrainer ? `/trainer-profile-leads/${lead.lead_id}` : `/client-leads/${lead.lead_id}`
      await api.patch(endpoint, payload)
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const removeLead = async (lead) => {
    try {
      const endpoint = isTrainer ? `/trainer-profile-leads/${lead.lead_id}` : `/client-leads/${lead.lead_id}`
      await api.delete(endpoint)
      toast.success('Lead removed')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const removeDomain = async (domain, count) => {
    if (!window.confirm(`Delete all ${count} saved result(s) for "${domain}" from this LinkedIn Search mode?`)) return
    setDeletingDomain(domain)
    try {
      const endpoint = isTrainer ? '/trainer-profile-leads/by-domain' : '/client-leads/by-domain'
      const res = await api.delete(endpoint, { params: { domain } })
      const deletedCount = res.data.deleted_count || 0
      toast.success(`Deleted ${deletedCount} result${deletedCount === 1 ? '' : 's'} for ${domain}`)
      if (selectedDomain === domain) setSelectedDomain('all')
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setDeletingDomain('')
    }
  }

  const verifyLead = async (lead) => {
    setVerifyingLead(lead.lead_id)
    try {
      const res = await api.post(`/trainer-profile-leads/${lead.lead_id}/verify-internal`)
      if (res.data.verified) toast.success(res.data.lead.verification_source || 'Trainer contact verified')
      else toast.error('No strong internal resume/trainer DB match found')
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setVerifyingLead('')
    }
  }

  const sendLead = async (lead) => {
    try {
      const res = await api.post(`/client-leads/${lead.lead_id}/send-email`)
      if (res.data.success) toast.success('Approach mail sent from Clahan')
      else toast.error(res.data.error || 'Mail failed')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const domainOptions = useMemo(() => {
    const counts = new Map()
    leads.forEach(lead => {
      const domain = leadDomain(lead)
      counts.set(domain, (counts.get(domain) || 0) + 1)
    })
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [leads])

  const visibleLeads = useMemo(() => {
    if (selectedDomain === 'all') return leads
    const selected = selectedDomain.toLowerCase()
    return leads.filter(lead => leadDomain(lead).toLowerCase() === selected || leadSearchText(lead).includes(selected))
  }, [leads, selectedDomain])

  const visibleStats = useMemo(() => ({
    total: visibleLeads.length,
    new: visibleLeads.filter(item => item.status === 'new').length,
    contacted: visibleLeads.filter(item => item.status === 'contacted').length,
    converted: visibleLeads.filter(item => item.status === 'converted').length,
  }), [visibleLeads])

  const cards = useMemo(() => [
    [isTrainer ? 'Trainer Profiles' : 'Client Posts', visibleStats.total, isTrainer ? Users : BriefcaseBusiness, 'text-slate-700'],
    ['New', visibleStats.new, Target, 'text-amber-700'],
    ['Contacted', visibleStats.contacted, Send, 'text-blue-700'],
    [isTrainer ? 'Added' : 'Converted', visibleStats.converted, CheckCircle2, 'text-emerald-700'],
  ], [visibleStats, isTrainer])

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Globe2 className="h-6 w-6 text-blue-600" /> LinkedIn Search
          </h1>
          <p className="mt-1 text-sm text-slate-500">Search public LinkedIn/web results for recent client trainer posts or Indian trainer profiles.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-[260px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && load()} placeholder="Search saved results" className="input bg-[#eaf6ff] pl-9" />
          </div>
          <button onClick={load} className="btn-secondary text-sm"><RefreshCw className="h-4 w-4" /> Search</button>
        </div>
      </div>

      <div className="linkedin-glow-panel flex flex-wrap gap-2 rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-2">
        <button onClick={() => setMode('client')} className={clsx('inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition', !isTrainer ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>
          <BriefcaseBusiness className="h-4 w-4" /> Client Requirement Posts
        </button>
        <button onClick={() => setMode('trainer')} className={clsx('inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition', isTrainer ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>
          <Users className="h-4 w-4" /> Indian Trainer Profiles
        </button>
      </div>

      <section className="linkedin-glow-panel rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-4">
        <div className="grid gap-3 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Search className="h-4 w-4 text-blue-700" />
              <h2 className="text-sm font-bold text-slate-900">
                {isTrainer ? 'Search Indian Trainer Profiles' : 'Search Recent Client Posts Seeking Trainers'}
              </h2>
            </div>
            <input
              className="input bg-[#eaf6ff]"
              value={searchDomains}
              onChange={e => setSearchDomains(e.target.value)}
              placeholder={isTrainer ? 'SAP S/4HANA, Apache APISIX, Python' : 'Leave blank to auto-discover client trainer requirements'}
            />
            <p className="mt-1 text-xs text-slate-400">
              💡 <strong>Credit-safe mode:</strong> Each search uses ~8–24 Tavily credits.
              Enter specific IT domains (e.g. <em>DevOps, Python</em>) to get the most relevant results.
              Non-IT domains like Excel or Soft Skills are excluded by default to save credits.
            </p>
          </div>
          <button onClick={runSearch} disabled={searching} className="btn-primary text-sm disabled:opacity-50">
            {searching ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {isTrainer ? 'Find Profiles' : 'Find Client Posts'}
          </button>
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(([label, value, Icon, tone]) => (
          <div key={label} className="linkedin-glow-card rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-4 transition-shadow">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-500">{label}</p>
              <Icon className={clsx('h-4 w-4', tone)} />
            </div>
            <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
          </div>
        ))}
      </div>

      <div className="linkedin-glow-panel rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <p className="text-sm font-bold text-slate-800">Domain Results</p>
          <span className="text-xs font-semibold text-slate-400">{visibleLeads.length} visible</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setSelectedDomain('all')}
            className={clsx('rounded-lg px-3 py-2 text-xs font-bold transition', selectedDomain === 'all' ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100')}
          >
            All Domains ({leads.length})
          </button>
          {domainOptions.map(([domain, count]) => (
            <div
              key={domain}
              className={clsx('inline-flex overflow-hidden rounded-lg text-xs font-bold transition', selectedDomain === domain ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100')}
            >
              <button
                onClick={() => setSelectedDomain(domain)}
                className="px-3 py-2"
              >
                {domain} ({count})
              </button>
              <button
                onClick={() => removeDomain(domain, count)}
                disabled={deletingDomain === domain}
                title={`Delete ${domain} results`}
                className={clsx('border-l px-2 transition disabled:opacity-50', selectedDomain === domain ? 'border-blue-500 hover:bg-blue-700' : 'border-slate-200 text-red-500 hover:bg-red-50 hover:text-red-600')}
              >
                {deletingDomain === domain ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="linkedin-glow-panel flex flex-wrap gap-2 rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-2">
        {STATUS.map(item => (
          <button key={item} onClick={() => setFilter(item)} className={clsx('rounded-lg px-3 py-2 text-sm font-semibold transition', filter === item ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>
            {STATUS_LABELS[item]}
          </button>
        ))}
      </div>

      {isTrainer && <TrustLegend />}

      {loading ? (
        <div className="py-14 text-center text-sm text-slate-400">Loading LinkedIn results...</div>
      ) : visibleLeads.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {visibleLeads.map(lead => (
            <article key={lead.lead_id} className="linkedin-glow-card rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-4 transition-shadow">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex min-w-0 gap-3">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-blue-100 bg-blue-50 text-sm font-bold uppercase text-blue-700">
                    {lead.profile_image ? (
                      <img src={lead.profile_image} alt="" className="h-full w-full object-cover" />
                    ) : (
                      initials(isTrainer ? (lead.trainer_name || lead.headline) : (lead.company_name || lead.contact_name || lead.domain))
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-bold text-slate-900">{isTrainer ? (lead.trainer_name || lead.headline || lead.domain || 'Trainer profile') : (lead.company_name || lead.contact_name || lead.domain || 'Client post')}</h3>
                      <span className={clsx('rounded-lg border px-2 py-0.5 text-xs font-semibold capitalize', statusClass(lead.status))}>{lead.status}</span>
                      {isTrainer && <VerificationBadge tier={lead.verification_tier || 'linkedin_signal'} />}
                      <span className="text-xs text-slate-400">{relativeTime(lead.created_at)}</span>
                    </div>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
                      <span className="font-semibold text-slate-800">{lead.domain || 'Domain pending'}</span>
                      <span>from {lead.source || 'Public Search'}</span>
                    </p>
                  </div>
                </div>
                <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">{Math.round((lead.confidence || 0) * 100)}%</span>
              </div>

              <p className="mt-3 line-clamp-4 text-sm leading-6 text-slate-600">
                {isTrainer ? (lead.profile_text || lead.headline || lead.notes || 'No public profile text saved.') : (lead.post_text || lead.notes || 'No post text saved.')}
              </p>

              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                {lead.verification_status === 'verified' && (
                  <span className="inline-flex items-center gap-1 rounded-lg bg-emerald-50 px-2 py-1 font-semibold text-emerald-700">
                    <ShieldCheck className="h-3 w-3" /> {lead.verification_source || 'Verified'}
                  </span>
                )}
                {lead.verification_status === 'unverified' && (
                  <span className="rounded-lg bg-amber-50 px-2 py-1 font-semibold text-amber-700">No internal match</span>
                )}
                {lead.contact_email && <a className={clsx('rounded-lg px-2 py-1 font-semibold', lead.verification_status === 'verified' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700')} href={`mailto:${lead.contact_email}`}>{lead.contact_email}</a>}
                {lead.contact_phone && <span className={clsx('rounded-lg px-2 py-1', lead.verification_status === 'verified' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-50')}>{lead.contact_phone}</span>}
                {lead.source_url && (
                  <a className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 font-semibold text-blue-700" href={lead.source_url} target="_blank" rel="noreferrer">
                    <ExternalLink className="h-3 w-3" /> {isTrainer ? 'Open LinkedIn Profile' : 'Open Post'}
                  </a>
                )}
              </div>

              {!isTrainer && lead.draft?.body && (
                <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
                  <summary className="cursor-pointer font-semibold text-slate-700">Client approach draft</summary>
                  <p className="mt-2 whitespace-pre-wrap text-slate-600">{lead.draft.body}</p>
                </details>
              )}

              <div className="mt-4 flex flex-wrap gap-2">
                {isTrainer && lead.source_url && <a href={lead.source_url} target="_blank" rel="noreferrer" className="btn-primary text-sm"><ExternalLink className="h-4 w-4" /> Open Profile</a>}
                {isTrainer && (
                  <LinkedInLeadVerifyButton
                    lead={lead}
                    loading={verifyingLead === lead.lead_id}
                    onVerify={verifyLead}
                  />
                )}
                {!isTrainer && <button onClick={() => sendLead(lead)} disabled={!lead.contact_email || lead.status === 'contacted'} className="btn-primary text-sm disabled:opacity-50"><Send className="h-4 w-4" /> Send Mail</button>}
                <button onClick={() => patchLead(lead, { status: 'reviewed' })} className="btn-secondary text-sm"><CheckCircle2 className="h-4 w-4" /> Reviewed</button>
                <button onClick={() => patchLead(lead, { status: 'converted' })} className="btn-secondary text-sm text-emerald-700"><Mail className="h-4 w-4" /> {isTrainer ? 'Added' : 'Converted'}</button>
                <button onClick={() => patchLead(lead, { status: 'rejected' })} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" /> Reject</button>
                <button onClick={() => removeLead(lead)} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" /> Delete</button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="linkedin-glow-panel rounded-lg border border-[#d8e6f5] bg-[#edf5ff] py-16 text-center text-slate-400">
          <Globe2 className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p>No {isTrainer ? 'trainer profiles' : 'client posts'} in this domain/status view.</p>
        </div>
      )}
    </div>
  )
}

