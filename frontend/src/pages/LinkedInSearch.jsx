import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  BriefcaseBusiness, CheckCircle2, ChevronRight, ExternalLink, Globe2, Mail, RefreshCw,
  Search, Send, ShieldCheck, Target, Trash2, Users,
} from 'lucide-react'
import api from '../utils/api'
import { AUTOMATIC_LINKEDIN_DOMAINS, leadSearchWarnings, leadSourceLabel, linkedInSearchPayload, newSearchRef, visibleSearchLeads } from '../utils/leadSearchFeedback'
import { LEAD_PAGE_SIZE, domainChips, leadListParams, listPage, pageToReload, statusCountInView } from '../utils/leadPaging'
import LeadBot from '../components/LeadBot'
import Pager from '../components/Pager'
import SearchSourceReport from '../components/SearchSourceReport'
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

function leadEmail(lead) {
  return String(lead?.email || lead?.contact_email || '').trim()
}

function leadPhone(lead) {
  return String(lead?.phone || lead?.contact_phone || '').trim()
}

export default function LinkedInSearch() {
  const navigate = useNavigate()
  const [mode, setMode] = useState('client')
  const [leads, setLeads] = useState([])
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')
  const [selectedDomain, setSelectedDomain] = useState('all')
  const [searchDomains, setSearchDomains] = useState('')
  const [loading, setLoading] = useState(false)
  const [searching, setSearching] = useState(false)
  const [searchReport, setSearchReport] = useState(null)
  const [showSearchMatches, setShowSearchMatches] = useState(false)
  const [deletingDomain, setDeletingDomain] = useState('')
  const [verifyingLead, setVerifyingLead] = useState('')
  const [page, setPage] = useState(1)
  const [list, setList] = useState(listPage())
  const listToken = useRef(0)
  const loadSeq = useRef(0)
  // Set when search text is submitted, before its response arrives, so a tab or chip clicked
  // meanwhile keeps that text.
  const appliedQuery = useRef('')
  const searchingRef = useRef(false)

  const isTrainer = mode === 'trainer'

  // selectedDomain is 'all' or a domain chip value (domain_exact). The server applies the trainer
  // profile rules (kind=linkedin_profile), so each page is full and the totals cover every saved lead.
  // query defaults to the last submitted search text, so typing without Enter does not filter.
  const load = async ({ query = appliedQuery.current, statusFilter = filter, searchMode = mode, pageNumber = page, domainValue = selectedDomain } = {}) => {
    const token = listToken.current
    appliedQuery.current = String(query || '').trim()
    // Only the latest list request updates the page, whatever order the responses arrive in.
    const seq = ++loadSeq.current
    const current = () => token === listToken.current && seq === loadSeq.current
    setLoading(true)
    try {
      const trainerList = searchMode === 'trainer'
      const endpoint = trainerList ? '/trainer-profile-leads' : '/client-leads'
      const params = leadListParams({
        q: query, status: statusFilter, page: pageNumber, domainExact: domainValue,
        kind: trainerList ? 'linkedin_profile' : '',
      })
      const res = await api.get(endpoint, { params })
      if (!current()) return
      const reload = pageToReload(res.data, pageNumber)
      if (reload) {
        setPage(reload)
        await load({ query, statusFilter, searchMode, pageNumber: reload, domainValue })
        return
      }
      setLeads(res.data.leads || [])
      // The filters of this list, so a domain delete removes exactly what its chip counted.
      setList({ ...listPage(res.data), query: params.q || '', status: statusFilter })
    } catch (e) {
      if (current()) toast.error(e.message)
    } finally {
      if (current()) setLoading(false)
    }
  }

  const runSearch = async ({ domainText = searchDomains, automatic = false, searchMode = mode } = {}) => {
    const token = ++listToken.current
    const trainerSearch = searchMode === 'trainer'
    const searchRef = newSearchRef()
    searchingRef.current = true
    setSearching(true)
    setSearchReport(null)
    setSelectedDomain('all')
    setPage(1)
    try {
      // Show the saved leads while the search runs. The search below reports its own result.
      await load({ query: '', statusFilter: 'all', searchMode, pageNumber: 1, domainValue: 'all' })
      const payload = { ...linkedInSearchPayload(searchMode, domainText), search_ref: searchRef }
      const res = await api.post('/linkedin-leads/search', payload)
      if (token !== listToken.current) return
      const savedCount = res.data.saved_count || 0
      const skippedCount = res.data.skipped_count || 0
      const autoSentCount = res.data.auto_sent_count || 0
      const warnings = leadSearchWarnings(res.data)
      setSearchReport({ ...res.data, warnings })
      setShowSearchMatches((res.data.results || []).length > 0)
      if (!automatic && savedCount) {
        const savedText = `Saved ${savedCount} LinkedIn result${savedCount === 1 ? '' : 's'}`
        toast.success(autoSentCount ? `${savedText}; auto-sent Mail 1 to ${autoSentCount}` : savedText)
      } else if (!automatic && warnings.length) {
        // Keep failures in the persistent report below, once per distinct cause.
      } else if (!automatic && trainerSearch && skippedCount) {
        const firstReason = res.data.skipped?.[0]?.reason
        const reasonText = firstReason === 'already_saved'
          ? 'already saved'
          : firstReason === 'duplicate_in_search'
            ? 'duplicate results'
            : 'already saved or duplicate'
        toast.success(`No new profiles saved. Showing ${skippedCount} ${reasonText} in the list below.`)
      } else if (!automatic) {
        toast.success('No new LinkedIn results saved')
      }
      setFilter('all')
      setSelectedDomain('all')
      setQ('')
      setPage(1)
      // Search results already carry the saved lead IDs; the saved list is reloaded, not merged with them.
      await load({ query: '', statusFilter: 'all', searchMode, pageNumber: 1, domainValue: 'all' })
    } catch (e) {
      if (token !== listToken.current) return
      setSearchReport(current => current
        ? { ...current, warnings: [...current.warnings, e.message || 'Unable to refresh saved results.'] }
        : { found: 0, saved_count: 0, warnings: [e.message || 'Unable to complete the search.'], requestFailed: true, searchRef })
      setShowSearchMatches(false)
      toast.error(e.message)
    } finally {
      if (token === listToken.current) {
        searchingRef.current = false
        setSearching(false)
      }
    }
  }

  // Status tabs, domain chips, the search box and paging reload the saved list from the server.
  const changeFilter = (statusFilter) => {
    setFilter(statusFilter)
    setPage(1)
    // A running search resets the filters and reloads the list when it finishes.
    if (!searchingRef.current) load({ statusFilter, pageNumber: 1 })
  }

  const chooseDomain = (domainValue) => {
    setShowSearchMatches(false)
    setSelectedDomain(domainValue)
    setPage(1)
    load({ domainValue, pageNumber: 1 })
  }

  const changePage = (pageNumber) => {
    setPage(pageNumber)
    load({ pageNumber })
  }

  const filterSaved = (query = q) => {
    setShowSearchMatches(false)
    setPage(1)
    load({ query, pageNumber: 1 })
  }

  useEffect(() => {
    const domains = AUTOMATIC_LINKEDIN_DOMAINS.join(', ')
    setSelectedDomain('all')
    setSearchDomains(domains)
    setSearchReport(null)
    setShowSearchMatches(false)
    runSearch({ domainText: domains, automatic: true, searchMode: mode })
    return () => { listToken.current += 1 }
  }, [mode])



  // Keeps the latest search matches in step with the saved leads they show.
  const updateSearchMatches = (leadId, change) => {
    setSearchReport(current => (current?.results
      ? { ...current, results: change ? current.results.map(item => (item.lead_id === leadId ? { ...item, ...change } : item)) : current.results.filter(item => item.lead_id !== leadId) }
      : current))
  }

  const patchLead = async (lead, payload) => {
    try {
      const endpoint = isTrainer ? `/trainer-profile-leads/${lead.lead_id}` : `/client-leads/${lead.lead_id}`
      await api.patch(endpoint, payload)
      updateSearchMatches(lead.lead_id, payload)
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
      updateSearchMatches(lead.lead_id, null)
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const removeDomain = async (chip) => {
    if (!window.confirm(`Delete all ${chip.count} saved result(s) for "${chip.label}" from this LinkedIn Search mode?`)) return
    setDeletingDomain(chip.value)
    try {
      const endpoint = isTrainer ? '/trainer-profile-leads/by-domain' : '/client-leads/by-domain'
      // The same filters as the chip's count, so exactly the results it counted are deleted.
      const params = { domain: chip.value }
      if (isTrainer) params.kind = 'linkedin_profile'
      if (list.status && list.status !== 'all') params.status = list.status
      if (list.query) params.q = list.query
      const res = await api.delete(endpoint, { params })
      const deletedCount = res.data.deleted_count || 0
      toast.success(`Deleted ${deletedCount} result${deletedCount === 1 ? '' : 's'} for ${chip.label}`)
      const domainValue = selectedDomain === chip.value ? 'all' : selectedDomain
      setSelectedDomain(domainValue)
      await load({ domainValue })
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

  const openLinkedInPipeline = (domain) => {
    const targetDomain = domain === 'all' ? (searchDomains || q || '') : domain
    navigate(`/linkedin-pipeline?domain=${encodeURIComponent(targetDomain)}&from=linkedin-search`)
  }

  const domainOptions = useMemo(() => domainChips(list.counts), [list])

  const showingMatches = showSearchMatches
    && (searchReport?.results || []).some(lead => lead?.source_url || lead?.linkedin_url || lead?.lead_id)

  const visibleLeads = useMemo(() => (
    showingMatches ? visibleSearchLeads([], searchReport.results, true) : leads
  ), [leads, showingMatches, searchReport])

  // The saved list's cards count every page of the open status tab and domain, from the server.
  const visibleStats = useMemo(() => (showingMatches ? {
    total: visibleLeads.length,
    new: visibleLeads.filter(item => item.status === 'new').length,
    contacted: visibleLeads.filter(item => item.status === 'contacted').length,
    converted: visibleLeads.filter(item => item.status === 'converted').length,
  } : {
    total: list.total,
    new: statusCountInView(list.counts, filter, 'new'),
    contacted: statusCountInView(list.counts, filter, 'contacted'),
    converted: statusCountInView(list.counts, filter, 'converted'),
  }), [showingMatches, visibleLeads, list, filter])

  const cards = useMemo(() => [
    [isTrainer ? 'Trainer Profiles' : 'Client Posts', visibleStats.total, isTrainer ? Users : BriefcaseBusiness, 'text-slate-700'],
    ['New', visibleStats.new, Target, 'text-amber-700'],
    ['Contacted', visibleStats.contacted, Send, 'text-blue-700'],
    [isTrainer ? 'Added' : 'Converted', visibleStats.converted, CheckCircle2, 'text-emerald-700'],
  ], [visibleStats, isTrainer])

  return (
    <div className="space-y-6 animate-fade-in">
      <LeadBot
        mode={isTrainer ? 'trainer' : 'client'}
        onRefresh={load}
        onUseDomains={domains => setSearchDomains(domains.join(', '))}
        onViewResults={() => {
          setShowSearchMatches(false)
          setQ('')
          setFilter('all')
          setSelectedDomain('all')
          setPage(1)
          load({ query: '', statusFilter: 'all', pageNumber: 1, domainValue: 'all' })
        }}
      />
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Globe2 className="h-6 w-6 text-blue-600" /> LinkedIn Search
          </h1>
          <p className="mt-1 text-sm text-slate-500">Client posts from people seeking trainers, and trainer profiles, are fetched automatically into this LinkedIn Search.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-[260px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') filterSaved() }} placeholder="Search saved results" className="input bg-[#eaf6ff] pl-9" />
          </div>
          <button onClick={() => { setQ(q.trim()); filterSaved(q.trim()) }} className="btn-secondary text-sm"><RefreshCw className="h-4 w-4" /> Filter saved results</button>
          {q && <button onClick={() => { setQ(''); filterSaved('') }} className="btn-secondary text-sm">Clear filter</button>}
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
                {isTrainer ? 'Search Trainer Profiles' : 'Search Recent Client Posts Seeking Trainers'}
              </h2>
            </div>
            <input
              className="input bg-[#eaf6ff]"
              value={searchDomains}
              onChange={e => setSearchDomains(e.target.value)}
              placeholder="Python"
            />
            <p className="mt-1 text-xs text-slate-400">
              <strong>Automatic search:</strong> {isTrainer ? 'Up to 100 trainer profiles' : 'Client posts seeking trainers'} for {searchDomains || AUTOMATIC_LINKEDIN_DOMAINS.join(', ')} load into the list below. Search matches appear here as soon as the search finishes; trainer profile collection stops at 100.
              Change the domains and choose {isTrainer ? 'Find Profiles' : 'Find Client Posts'} to search again. Fetching does not send email.
            </p>
          </div>
          <button onClick={runSearch} disabled={searching} className="btn-primary text-sm disabled:opacity-50">
            {searching ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {searching ? 'Searching…' : isTrainer ? 'Find Profiles' : 'Find Client Posts'}
          </button>
        </div>
      </section>

      <SearchSourceReport report={searchReport} noun="results">
        {(searchReport?.skipped || []).some(item => item.reason === 'already_saved_updated' || item.reason === 'already_saved') && <p className="text-sm text-slate-600">Some matches were already saved. They are included in the search matches below, as the saved leads.</p>}
        {searchReport && !searchReport.requestFailed && <button className="btn-secondary text-sm" onClick={() => { setShowSearchMatches(!showSearchMatches) }}>{showSearchMatches ? 'Show all saved results' : 'Show latest search matches'}</button>}
        {(searchReport?.warnings || []).length > 0 && <p className="text-xs text-slate-600">Any results already saved remain available below.</p>}
      </SearchSourceReport>

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
          <span className="text-xs font-semibold text-slate-400">{showingMatches ? `${visibleLeads.length} latest search matches` : `${list.total} saved in this view`}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => chooseDomain('all')}
            className={clsx('rounded-lg px-3 py-2 text-xs font-bold transition', selectedDomain === 'all' ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100')}
          >
            All Domains ({list.counts?.all_domains_total ?? list.total})
          </button>
          {domainOptions.map(chip => (
            <div
              key={chip.value}
              className={clsx('inline-flex overflow-hidden rounded-lg text-xs font-bold transition', selectedDomain === chip.value ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100')}
            >
              <button
                onClick={() => chooseDomain(chip.value)}
                className="px-3 py-2"
              >
                {chip.label} ({chip.count})
              </button>
              {isTrainer && (
                <button
                  onClick={() => openLinkedInPipeline(chip.label)}
                  title={`Open ${chip.label} LinkedIn pipeline`}
                  className={clsx('border-l px-2 transition', selectedDomain === chip.value ? 'border-blue-500 hover:bg-blue-700' : 'border-slate-200 text-blue-600 hover:bg-blue-50')}
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              )}
              <button
                onClick={() => removeDomain(chip)}
                disabled={deletingDomain === chip.value}
                title={`Delete ${chip.label} results`}
                className={clsx('border-l px-2 transition disabled:opacity-50', selectedDomain === chip.value ? 'border-blue-500 hover:bg-blue-700' : 'border-slate-200 text-red-500 hover:bg-red-50 hover:text-red-600')}
              >
                {deletingDomain === chip.value ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              </button>
            </div>
          ))}
          {(list.counts?.domains_total || 0) > domainOptions.length && (
            <span className="self-center text-xs text-slate-400">and {list.counts.domains_total - domainOptions.length} smaller domains: search saved results to see them</span>
          )}
        </div>
      </div>

      <div className="linkedin-glow-panel flex flex-wrap gap-2 rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-2">
        {STATUS.map(item => (
          <button key={item} onClick={() => changeFilter(item)} className={clsx('rounded-lg px-3 py-2 text-sm font-semibold transition', filter === item ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>
            {STATUS_LABELS[item]}
          </button>
        ))}
      </div>

      {isTrainer && <TrustLegend />}

      {searching && (
        <div className="linkedin-glow-panel rounded-lg border border-[#d8e6f5] bg-[#edf5ff] px-4 py-3 text-center text-sm text-slate-500">
          <RefreshCw className="mr-2 inline h-4 w-4 animate-spin text-blue-600" />
          Fetching {isTrainer ? 'trainer profiles' : 'client posts seeking trainers'} into LinkedIn Search. Saved profiles stay in the list.
        </div>
      )}

      {loading && !visibleLeads.length ? (
        <div className="py-14 text-center text-sm text-slate-400">Loading LinkedIn results...</div>
      ) : visibleLeads.length ? (
        <div className="flex flex-col gap-5">
          {visibleLeads.map(lead => (
            <article
              key={lead.lead_id || lead.source_url || lead.linkedin_url}
              className="rounded-xl border border-slate-300 bg-white p-5 shadow-sm"
              style={{
                backgroundColor: '#ffffff',
                border: '1px solid #cbd5e1',
                boxShadow: '0 2px 8px rgba(15, 23, 42, 0.10)',
                marginBottom: '1.25rem',
              }}
            >
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
                      <h3 className="font-bold text-slate-900">{isTrainer ? (lead.trainer_name || lead.name || lead.headline || lead.domain || 'Trainer profile') : (lead.company_name || lead.contact_name || lead.domain || 'Client post')}</h3>
                      <span className={clsx('rounded-lg border px-2 py-0.5 text-xs font-semibold capitalize', statusClass(lead.status))}>{lead.status}</span>
                      {isTrainer && <VerificationBadge tier={lead.verification_tier || 'linkedin_signal'} />}
                      <span className="text-xs text-slate-400">{relativeTime(lead.created_at)}</span>
                    </div>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
                      <span className="font-semibold text-slate-800">{lead.domain || 'Domain pending'}</span>
                      <span>from {leadSourceLabel(lead)}</span>
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
                {leadEmail(lead) && <a className={clsx('rounded-lg px-2 py-1 font-semibold', lead.verification_status === 'verified' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700')} href={`mailto:${leadEmail(lead)}`}>{leadEmail(lead)}</a>}
                {leadPhone(lead) && <span className={clsx('rounded-lg px-2 py-1', lead.verification_status === 'verified' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-50')}>{leadPhone(lead)}</span>}
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

      {!showingMatches && <Pager page={list.page} pages={list.pages} total={list.total} pageSize={LEAD_PAGE_SIZE} loading={loading} onPage={changePage} noun={isTrainer ? 'saved profiles' : 'saved posts'} />}
    </div>
  )
}

