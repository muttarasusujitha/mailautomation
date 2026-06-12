import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  CheckCircle2, ExternalLink, Mail, RefreshCw,
  Search, Send, Target, Trash2, Linkedin, Users, BookOpen,
} from 'lucide-react'
import api from '../utils/api'

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUS = ['all', 'new', 'reviewed', 'contacted', 'converted', 'rejected']
const STATUS_LABELS = {
  all: 'All', new: 'New', reviewed: 'Reviewed',
  contacted: 'Contacted', converted: 'Added', rejected: 'Rejected',
}

// ─── Query generator ─────────────────────────────────────────────────────────
// Produces 10–15 unique LinkedIn queries per domain across 3 intents.
// More query variety = more unique people found = more emails/phones saved.

function buildTrainerQueries(domain) {
  const d = domain.trim()
  return [
    // Exact title searches on linkedin.com/in (trainer profiles)
    { q: `"${d} trainer" site:linkedin.com/in`,                    intent: 'trainer' },
    { q: `"${d} instructor" site:linkedin.com/in`,                 intent: 'trainer' },
    { q: `"freelance ${d} trainer" site:linkedin.com/in`,          intent: 'trainer' },
    { q: `"corporate ${d} trainer" site:linkedin.com/in`,          intent: 'trainer' },
    { q: `"${d} corporate training" site:linkedin.com/in`,         intent: 'trainer' },
    { q: `"${d} training" "freelance" site:linkedin.com/in`,       intent: 'trainer' },
    { q: `"${d}" "training delivery" site:linkedin.com/in`,        intent: 'trainer' },
    { q: `"${d}" "conduct trainings" site:linkedin.com/in`,        intent: 'trainer' },
    { q: `"${d}" "workshop" "trainer" site:linkedin.com/in`,       intent: 'trainer' },
    { q: `"${d} trainer" India site:linkedin.com/in`,              intent: 'trainer' },
    { q: `"${d} trainer" Bangalore site:linkedin.com/in`,          intent: 'trainer' },
    { q: `"${d} trainer" Mumbai site:linkedin.com/in`,             intent: 'trainer' },
    { q: `"${d} trainer" Hyderabad site:linkedin.com/in`,          intent: 'trainer' },
    // Requirement / client-side queries
    { q: `"looking for ${d} trainer" site:linkedin.com`,           intent: 'requirement' },
    { q: `"need a ${d} trainer" site:linkedin.com`,                intent: 'requirement' },
    { q: `"${d} training requirement" site:linkedin.com`,          intent: 'requirement' },
    { q: `"${d} trainer required" site:linkedin.com`,              intent: 'requirement' },
    { q: `"${d} trainer needed" site:linkedin.com`,                intent: 'requirement' },
    { q: `"hiring ${d} trainer" site:linkedin.com`,                intent: 'requirement' },
    { q: `"${d} training for our team" site:linkedin.com`,         intent: 'requirement' },
  ]
}

// Visible query pill labels for the search preview
const QUERY_INTENT_LABELS = {
  trainer:     'Trainer Profiles',
  requirement: 'Client Requirements',
}

// ─── Styling helpers ───────────────────────────────────────────────────────────

function statusClass(status) {
  if (status === 'converted') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'contacted') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'rejected')  return 'border-red-200 bg-red-50 text-red-700'
  if (status === 'reviewed')  return 'border-violet-200 bg-violet-50 text-violet-700'
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
  return (words[0]?.[0] || 'N') + (words[1]?.[0] || '')
}

// ─── Lead classification ───────────────────────────────────────────────────────

function leadDomain(lead) {
  return String(lead?.domain || '').trim() || 'Other'
}

// Comprehensive search text — includes all fields a user might search by
function leadSearchText(lead) {
  return [
    lead?.domain,
    lead?.trainer_name,
    lead?.headline,
    lead?.profile_text,
    lead?.source_url,
    lead?.notes,
    lead?.contact_email,
    lead?.contact_phone,
  ].join(' ').toLowerCase()
}

// Detect job postings / recruiter noise that aren't trainer profiles or client leads
// Kept deliberately tight — better to keep a borderline lead than lose a good one
function isIrrelevantNoise(lead) {
  const text  = leadSearchText(lead)
  const url   = String(lead?.source_url || '').toLowerCase()

  const noiseUrlTokens = [
    'job-listings', 'jobs-in', 'job-vacancies', 'apply-to',
    'jobdetail', 'job-detail', 'jobsearch', 'job-search',
    'trainer-jobs', 'jobs-careers',
  ]
  const noiseTextTokens = [
    'job vacancies', 'job vacancy', 'job description', 'required candidate profile',
    'we are hiring', 'current ctc', 'expected ctc', 'notice period',
    'immediate joiner', 'last working day', 'offer in hand',
    'application for', 'my resume', 'ready to work from office',
    'salary range', 'lacs p.a', 'recruiter at',
  ]

  if (noiseUrlTokens.some(t => url.includes(t)))  return true
  if (noiseTextTokens.some(t => text.includes(t))) return true
  return false
}

// Detect trainer profiles — broad signals; more signals = more leads captured
function isTrainerProfile(lead) {
  const text = leadSearchText(lead)
  const trainerSignals = [
    // Core trainer identity
    'trainer', 'instructor', 'faculty', 'coach', 'mentor', 'facilitator',
    // Training activity
    'training delivery', 'conduct training', 'conducted training', 'delivered training',
    'training sessions', 'classroom training', 'online training', 'corporate training',
    'hands-on training', 'bootcamp', 'workshop', 'upskilling', 'reskilling',
    // LinkedIn-specific phrases
    'freelance trainer', 'independent trainer', 'corporate trainer', 'technical trainer',
    'subject matter expert', 'sme', 'learning and development', 'l&d',
    'learning & development', 'enablement', 'knowledge transfer',
    // Certifications & teaching
    'certified trainer', 'certified instructor', 'teach', 'teaching experience',
    'trained professionals', 'trained teams', 'trained over', 'trained more than',
  ]
  return trainerSignals.some(t => text.includes(t))
}

// Detect client requirement posts — these are leads asking for trainers
function isClientRequirement(lead) {
  const text = leadSearchText(lead)
  const requirementSignals = [
    'looking for a trainer', 'looking for trainer', 'need a trainer', 'need trainer',
    'require a trainer', 'require trainer', 'training requirement', 'training requirements',
    'trainer required', 'trainer needed', 'hiring a trainer', 'hiring trainer',
    'seeking a trainer', 'seeking trainer', 'want a trainer', 'want trainer',
    'training vendor', 'training partner', 'training provider needed',
    'can anyone recommend a trainer', 'recommend a good trainer',
    'who can train', 'anyone who trains', 'training for our team',
  ]
  return requirementSignals.some(t => text.includes(t))
}

// A lead is relevant if it's a trainer profile OR a client requirement
function isRelevantLead(lead) {
  return isTrainerProfile(lead) || isClientRequirement(lead)
}

// Tag the result type for display
function leadType(lead) {
  if (isClientRequirement(lead)) return 'requirement'
  if (isTrainerProfile(lead))    return 'trainer'
  return 'other'
}

// ─── Domain matching ───────────────────────────────────────────────────────────

function normaliseDomain(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/\b(trainer|training|jobs?|job|online|corporate|technical|faculty|instructor)\b/g, ' ')
    .replace(/[^a-z0-9+#./\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function domainAliases(domain) {
  const clean   = normaliseDomain(domain)
  const compact = clean.replace(/[^a-z0-9]/g, '')
  const aliases = new Set([clean, compact])
  const checks  = [
    ['devops',       'devops'],
    ['python',       'python'],
    ['aws',          'aws'],
    ['azure',        'azure'],
    ['gcp',          'gcp'],
    ['fullstack',    'fullstack'],
    ['react',        'react'],
    ['angular',      'angular'],
    ['node',         'node'],
    ['kubernetes',   'kubernetes'],
    ['docker',       'docker'],
    ['terraform',    'terraform'],
    ['ansible',      'ansible'],
    ['java',         'java'],
    ['salesforce',   'salesforce'],
    ['tableau',      'tableau'],
    ['powerbi',      'powerbi'],
    ['s4hana',       's4hana'],
    ['sap',          'sap'],
    ['apisix',       'apisix'],
    ['apacheapisix', 'apacheapisix'],
  ]
  checks.forEach(([key, alias]) => {
    if (compact.includes(key)) aliases.add(alias)
  })
  return Array.from(aliases).filter(Boolean)
}

function titleMatchesDomain(lead, domain) {
  if (!domain || domain === 'all') return true
  const domainText    = leadSearchText(lead)
  const domainCompact = domainText.replace(/[^a-z0-9]/g, '')
  return domainAliases(domain).some(alias => {
    const aliasCompact = alias.replace(/[^a-z0-9]/g, '')
    return aliasCompact && (domainCompact.includes(aliasCompact) || domainText.includes(alias))
  })
}

function leadMatchesSelectedDomain(lead, domain) {
  if (!domain || domain === 'all') return true
  // Fuzzy match: check saved domain OR full text — avoids losing leads with slightly different domain strings
  const savedDomain = leadDomain(lead).toLowerCase()
  const selected    = String(domain).toLowerCase()
  if (savedDomain === selected) return true
  // Fallback: check if the domain keyword appears anywhere in the lead
  return titleMatchesDomain(lead, domain)
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function LinkedInSearch() {
  const [leads,          setLeads]          = useState([])
  const [filter,         setFilter]         = useState('all')
  const [q,              setQ]              = useState('')
  const [selectedDomain, setSelectedDomain] = useState('all')
  const [searchDomains,  setSearchDomains]  = useState('Python')
  const [searchMode,     setSearchMode]     = useState('all') // 'all' | 'trainer' | 'requirement'
  const [loading,        setLoading]        = useState(false)
  const [searching,      setSearching]      = useState(false)
  const [searchProgress, setSearchProgress] = useState(null) // { done, total, saved }
  const [emailScanning,  setEmailScanning]  = useState(false)
  const [mailScanning,   setMailScanning]   = useState(false)
  const [targetCount,    setTargetCount]    = useState(10)   // min results user wants

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.get('/trainer-profile-leads', {
        params: { status: filter, q, source: 'linkedin', limit: 200, compact: true, include_stats: false },
      })
      const rows = (res.data.leads || [])
        .filter(item => !isIrrelevantNoise(item))
        .filter(item => isRelevantLead(item))
      setLeads(rows)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [filter])

  // Main search — fires 21 query variations, crawls each profile page,
  // extracts phone/email from profile text, follows "People Also Viewed" links
  const runSearch = async () => {
    setSearching(true)
    setSearchProgress(null)
    try {
      const domains = searchDomains.split(',').map(d => d.trim()).filter(Boolean)

      const allQueries = []
      domains.forEach(domain => {
        buildTrainerQueries(domain)
          .filter(q => searchMode === 'all' || searchMode === q.intent)
          .forEach(q => allQueries.push({ domain, ...q }))
      })

      const perQuery = Math.max(10, Math.ceil(targetCount / Math.max(allQueries.length, 1)) + 5)
      setSearchProgress({ done: 0, total: allQueries.length, saved: 0, phase: 'search' })

      const BATCH = 6
      let totalSaved = 0
      for (let i = 0; i < allQueries.length; i += BATCH) {
        const batch = allQueries.slice(i, i + BATCH)
        const res = await api.post('/trainer-profile-leads/search-public', {
          domains,
          queries: batch,
          source: 'linkedin',
          max_results: perQuery,
          max_queries: batch.length,
          concurrency: 6,
          // ── Deep crawl flags ──────────────────────────────────────────────
          crawl_profiles: true,          // visit each linkedin.com/in/xxx page
          extract_contact: true,         // pull phone/email from profile text
          follow_also_viewed: true,      // crawl "People Also Viewed" links (+8 per profile)
          also_viewed_depth: 1,          // 1 level deep (don't recurse infinitely)
          search_resume_sites: true,     // also search naukri/indeed/shine for same trainer names
          resume_sites: ['naukri.com', 'shine.com', 'indeed.co.in', 'unstop.com'],
        })
        totalSaved += res.data.saved_count || 0
        setSearchProgress({
          done: Math.min(i + BATCH, allQueries.length),
          total: allQueries.length,
          saved: totalSaved,
          phase: 'search',
        })
      }

      // Phase 2 — re-enrich all saved leads for this domain to get phone/email
      setSearchProgress({ done: 0, total: 1, saved: totalSaved, phase: 'enrich' })
      await api.post('/trainer-profile-leads/enrich-public-emails', {
        source: 'linkedin',
        domain: domains[0] || '',
        limit: 100,
      })
      await api.post('/trainer-profile-leads/enrich-from-mails', {
        source: 'linkedin',
        domain: domains[0] || '',
        limit: 100,
      })

      toast.success(`Found ${totalSaved} LinkedIn trainers — scanning for contact info done`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSearching(false)
      setSearchProgress(null)
    }
  }

  // Expand leads by crawling "People Also Viewed" on all existing profiles
  // Use this when you already have some results but want more from the same network
  const expandFromProfiles = async () => {
    setSearching(true)
    setSearchProgress({ done: 0, total: 1, saved: 0, phase: 'expand' })
    try {
      const profileUrls = leads
        .filter(l => l.source_url && l.source_url.includes('linkedin.com/in'))
        .map(l => l.source_url)
        .slice(0, 30) // take up to 30 existing profiles to expand from

      if (!profileUrls.length) {
        toast.error('No LinkedIn profiles to expand from — run a search first')
        return
      }

      const res = await api.post('/trainer-profile-leads/expand-from-profiles', {
        source: 'linkedin',
        profile_urls: profileUrls,
        domain: selectedDomain === 'all' ? searchDomains.split(',')[0]?.trim() : selectedDomain,
        follow_also_viewed: true,
        extract_contact: true,
        also_viewed_depth: 1,
      })

      toast.success(`Expanded: ${res.data.saved_count || 0} new trainer(s) found from existing profiles`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSearching(false)
      setSearchProgress(null)
    }
  }

  const patchLead = async (lead, payload) => {
    try {
      await api.patch(`/trainer-profile-leads/${lead.lead_id}`, payload)
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const removeLead = async (lead) => {
    try {
      await api.delete(`/trainer-profile-leads/${lead.lead_id}`)
      toast.success('LinkedIn result removed')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const findPublicEmails = async () => {
    setEmailScanning(true)
    try {
      const res = await api.post('/trainer-profile-leads/enrich-public-emails', {
        source: 'linkedin',
        domain: selectedDomain === 'all' ? '' : selectedDomain,
        limit: 40,
      })
      toast.success(`Email scan: ${res.data.enriched_count || 0} email(s) found from ${res.data.checked || 0} checked`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setEmailScanning(false)
    }
  }

  const findEmailsFromMails = async () => {
    setMailScanning(true)
    try {
      const res = await api.post('/trainer-profile-leads/enrich-from-mails', {
        source: 'linkedin',
        domain: selectedDomain === 'all' ? '' : selectedDomain,
        limit: 60,
      })
      toast.success(`Mail scan: ${res.data.enriched_count || 0} email(s) matched from ${res.data.checked || 0} lead(s)`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setMailScanning(false)
    }
  }

  const sendLead = async (lead) => {
    try {
      let toEmail = String(lead.contact_email || '').trim()
      if (!toEmail) {
        toEmail = window.prompt('Email not found on this LinkedIn result. Enter email to send approach mail:')
        toEmail = String(toEmail || '').trim()
        if (!toEmail) return
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(toEmail)) {
          toast.error('Enter a valid email address')
          return
        }
      }
      const res = await api.post(`/trainer-profile-leads/${lead.lead_id}/send-email`, {
        to_email: toEmail,
        domain: lead.domain,
        mode: 'Online',
      })
      if (res.data.success) toast.success('Approach mail sent')
      else toast.error(res.data.error || 'Mail failed')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  // Domain pill counts — fuzzy bucketing so near-duplicate domain strings group together
  const domainOptions = useMemo(() => {
    const counts = new Map()
    leads.forEach(lead => {
      const domain = leadDomain(lead)
      counts.set(domain, (counts.get(domain) || 0) + 1)
    })
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [leads])

  const visibleLeads = useMemo(() => {
    let rows = selectedDomain === 'all'
      ? leads
      : leads.filter(lead => leadMatchesSelectedDomain(lead, selectedDomain))

    // Filter by search mode (trainer vs requirement)
    if (searchMode === 'trainer')     rows = rows.filter(l => leadType(l) === 'trainer')
    if (searchMode === 'requirement') rows = rows.filter(l => leadType(l) === 'requirement')

    return rows
  }, [leads, selectedDomain, searchMode])

  const stats = useMemo(() => ({
    total:     visibleLeads.length,
    trainers:  visibleLeads.filter(l => leadType(l) === 'trainer').length,
    requirements: visibleLeads.filter(l => leadType(l) === 'requirement').length,
    contacted: visibleLeads.filter(l => l.status === 'contacted').length,
    added:     visibleLeads.filter(l => l.status === 'converted').length,
  }), [visibleLeads])

  return (
    <div className="space-y-6 animate-fade-in">

      {/* ── Header ── */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Linkedin className="h-6 w-6 text-blue-600" /> LinkedIn Search
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Find trainer profiles, client requirement posts, and training leads from LinkedIn.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-[260px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={q}
              onChange={e => setQ(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && load()}
              placeholder="Search by name, domain, email…"
              className="input pl-9"
            />
          </div>
          <button onClick={load} className="btn-secondary text-sm">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
        </div>
      </div>

      {/* ── Search panel ── */}
      <section className="rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-4 shadow-sm space-y-4">
        <div className="flex items-center gap-2">
          <Linkedin className="h-4 w-4 text-blue-700" />
          <h2 className="text-sm font-bold text-slate-900">Search LinkedIn for Leads</h2>
        </div>

        <div className="grid gap-3 lg:grid-cols-[1fr_auto_auto] lg:items-end">
          <div>
            <label className="mb-1 block text-xs font-semibold text-slate-600">Domains (comma separated)</label>
            <input
              className="input bg-white"
              value={searchDomains}
              onChange={e => setSearchDomains(e.target.value)}
              placeholder="Python, DevOps, AWS, SAP S/4HANA"
            />
          </div>

          {/* Search mode toggle */}
          <div>
            <label className="mb-1 block text-xs font-semibold text-slate-600">Search for</label>
            <div className="flex rounded-lg border border-slate-200 bg-white overflow-hidden text-sm font-semibold">
              {[
                { value: 'all',         label: 'Both' },
                { value: 'trainer',     label: 'Trainers only' },
                { value: 'requirement', label: 'Requirements only' },
              ].map(opt => (
                <button
                  key={opt.value}
                  onClick={() => setSearchMode(opt.value)}
                  className={clsx(
                    'px-3 py-2 transition',
                    searchMode === opt.value ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <button onClick={runSearch} disabled={searching} className="btn-primary text-sm disabled:opacity-50 self-end">
            {searching ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {searching ? 'Searching…' : 'Find LinkedIn Results'}
          </button>
        </div>

        {/* Target count slider */}
        <div className="flex items-center gap-4">
          <label className="text-xs font-semibold text-slate-600 whitespace-nowrap">
            Target results: <span className="text-blue-700 font-bold">{targetCount}+</span>
          </label>
          <input
            type="range" min={10} max={50} step={5}
            value={targetCount}
            onChange={e => setTargetCount(Number(e.target.value))}
            className="flex-1 accent-blue-600"
          />
          <span className="text-xs text-slate-400 whitespace-nowrap">
            {(() => {
              const domains = searchDomains.split(',').filter(Boolean)
              const qCount = domains.flatMap(d =>
                buildTrainerQueries(d.trim()).filter(q =>
                  searchMode === 'all' || searchMode === q.intent
                )
              ).length
              return `${qCount} queries × 10 results = up to ${qCount * 10} profiles`
            })()}
          </span>
        </div>

        {/* Progress bar while searching */}
        {searching && searchProgress && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-slate-500">
              <span>
                {searchProgress.phase === 'search' && `Running query ${searchProgress.done} of ${searchProgress.total}…`}
                {searchProgress.phase === 'enrich' && `Phase 2: scanning profiles for phone & email…`}
                {searchProgress.phase === 'expand' && `Expanding from "People Also Viewed" links…`}
              </span>
              <span className="font-semibold text-blue-700">{searchProgress.saved} saved</span>
            </div>
            <div className="h-2 w-full rounded-full bg-blue-100 overflow-hidden">
              <div
                className="h-2 rounded-full bg-blue-600 transition-all duration-300"
                style={{
                  width: searchProgress.phase === 'search'
                    ? `${Math.round((searchProgress.done / Math.max(searchProgress.total, 1)) * 100)}%`
                    : '100%'
                }}
              />
            </div>
            {searchProgress.phase === 'enrich' && (
              <p className="text-xs text-slate-400">Visiting each profile page to extract phone numbers and emails…</p>
            )}
          </div>
        )}

        {/* Live query preview — collapsed by default, expandable */}
        {searchDomains && !searching && (
          <details className="text-xs">
            <summary className="cursor-pointer text-blue-700 font-semibold select-none">
              Preview queries ({(() => {
                const domains = searchDomains.split(',').filter(Boolean)
                return domains.flatMap(d =>
                  buildTrainerQueries(d.trim()).filter(q =>
                    searchMode === 'all' || searchMode === q.intent
                  )
                ).length
              })()} total)
            </summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {searchDomains.split(',').filter(Boolean).map(d => d.trim()).flatMap(domain =>
                buildTrainerQueries(domain)
                  .filter(q => searchMode === 'all' || searchMode === q.intent)
                  .map((q, i) => (
                    <span
                      key={`${domain}-${i}`}
                      className={clsx(
                        'rounded-full border px-2.5 py-1 font-mono',
                        q.intent === 'requirement'
                          ? 'border-amber-200 bg-amber-50 text-amber-700'
                          : 'border-blue-200 bg-[#f7fbff] text-blue-700'
                      )}
                    >
                      {q.q}
                    </span>
                  ))
              )}
            </div>
          </details>
        )}
      </section>

      {/* ── Stats ── */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Total Results',  stats.total,        Linkedin,      'text-blue-700'],
          ['Trainer Profiles', stats.trainers,   Users,         'text-violet-700'],
          ['Requirements',   stats.requirements, BookOpen,      'text-amber-700'],
          ['Contacted',      stats.contacted,    Send,          'text-emerald-700'],
        ].map(([label, value, Icon, tone]) => (
          <div key={label} className="rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-500">{label}</p>
              <Icon className={clsx('h-4 w-4', tone)} />
            </div>
            <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
          </div>
        ))}
      </div>

      {/* ── Domain pills ── */}
      <div className="rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-3 shadow-sm">
        <div className="mb-2 flex items-center justify-between gap-3">
          <p className="text-sm font-bold text-slate-800">Filter by Domain</p>
          <span className="text-xs font-semibold text-slate-400">{visibleLeads.length} visible</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setSelectedDomain('all')}
            className={clsx('rounded-lg px-3 py-2 text-xs font-bold transition',
              selectedDomain === 'all' ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100'
            )}
          >
            All Domains ({leads.length})
          </button>
          {domainOptions.map(([domain, count]) => (
            <button
              key={domain}
              onClick={() => setSelectedDomain(domain)}
              className={clsx('rounded-lg px-3 py-2 text-xs font-bold transition',
                selectedDomain === domain ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100'
              )}
            >
              {domain} ({count})
            </button>
          ))}
        </div>
      </div>

      {/* ── Toolbar: email actions + status filter ── */}
      <div className="flex flex-wrap gap-2 rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-2 shadow-sm">
        <button onClick={findPublicEmails} disabled={emailScanning} className="btn-secondary text-sm disabled:opacity-50">
          {emailScanning ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
          Find Public Emails
        </button>
        <button onClick={findEmailsFromMails} disabled={mailScanning} className="btn-secondary text-sm disabled:opacity-50">
          {mailScanning ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
          Find Emails From Mails
        </button>
        <button
          onClick={expandFromProfiles}
          disabled={searching || !leads.length}
          className="btn-secondary text-sm disabled:opacity-50 text-violet-700"
          title="Crawl 'People Also Viewed' on your existing profiles to find more trainers"
        >
          {searching && searchProgress?.phase === 'expand'
            ? <RefreshCw className="h-4 w-4 animate-spin" />
            : <Users className="h-4 w-4" />}
          Expand Network ({leads.filter(l => l.source_url?.includes('linkedin.com/in')).length} profiles)
        </button>
        <div className="ml-auto flex flex-wrap gap-1">
          {STATUS.map(item => (
            <button
              key={item}
              onClick={() => setFilter(item)}
              className={clsx('rounded-lg px-3 py-2 text-sm font-semibold transition',
                filter === item ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50'
              )}
            >
              {STATUS_LABELS[item]}
            </button>
          ))}
        </div>
      </div>

      {/* ── Result type tabs ── */}
      <div className="flex gap-2">
        {[
          { value: 'all',         label: `All (${leads.length})` },
          { value: 'trainer',     label: `Trainer Profiles (${stats.trainers})` },
          { value: 'requirement', label: `Client Requirements (${stats.requirements})` },
        ].map(tab => (
          <button
            key={tab.value}
            onClick={() => setSearchMode(tab.value)}
            className={clsx('rounded-lg px-4 py-2 text-sm font-semibold transition',
                  searchMode === tab.value ? 'bg-blue-600 text-white shadow-sm' : 'bg-[#f7fbff] border border-[#d8e6f5] text-slate-600 hover:bg-white'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Lead cards ── */}
      {loading ? (
        <div className="py-14 text-center text-sm text-slate-400">Loading LinkedIn results…</div>
      ) : visibleLeads.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {visibleLeads.map(lead => {
            const type = leadType(lead)
            return (
              <article key={lead.lead_id} className="rounded-lg border border-[#d8e6f5] bg-[#edf5ff] p-4 shadow-sm">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex min-w-0 gap-3">
                    <div className={clsx(
                      'flex h-12 w-12 shrink-0 items-center justify-center rounded-full border text-sm font-bold uppercase',
                      type === 'requirement'
                        ? 'border-amber-100 bg-amber-50 text-amber-700'
                        : 'border-blue-100 bg-blue-50 text-blue-700'
                    )}>
                      {initials(lead.trainer_name || lead.headline || lead.domain)}
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-bold text-slate-900">
                          {lead.trainer_name || lead.headline || lead.domain || 'LinkedIn result'}
                        </h3>
                        <span className={clsx('rounded-lg border px-2 py-0.5 text-xs font-semibold capitalize', statusClass(lead.status))}>
                          {lead.status}
                        </span>
                        {/* Result type badge */}
                        <span className={clsx(
                          'rounded-full px-2 py-0.5 text-xs font-bold',
                          type === 'requirement'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-blue-100 text-blue-700'
                        )}>
                          {type === 'requirement' ? '📋 Requirement' : '👤 Trainer'}
                        </span>
                        <span className="text-xs text-slate-400">{relativeTime(lead.created_at)}</span>
                      </div>
                      <p className="mt-1 text-sm font-semibold text-slate-700">{lead.domain || 'Domain pending'}</p>
                    </div>
                  </div>
                  <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">
                    {Math.round((lead.confidence || 0) * 100)}%
                  </span>
                </div>

                <p className="mt-3 line-clamp-5 text-sm leading-6 text-slate-600">
                  {lead.profile_text || lead.headline || lead.notes || 'No text saved.'}
                </p>

                <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                  {lead.contact_email && (
                    <a className="rounded-lg bg-emerald-50 px-2 py-1 font-semibold text-emerald-700" href={`mailto:${lead.contact_email}`}>
                      {lead.contact_email}
                    </a>
                  )}
                  {lead.contact_phone && (
                    <span className="rounded-lg bg-slate-50 px-2 py-1">{lead.contact_phone}</span>
                  )}
                  {lead.source_url && (
                    <a className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 font-semibold text-blue-700" href={lead.source_url} target="_blank" rel="noreferrer">
                      <ExternalLink className="h-3 w-3" /> View on LinkedIn
                    </a>
                  )}
                  {lead.public_website_url && (
                    <a className="inline-flex items-center gap-1 rounded-lg bg-violet-50 px-2 py-1 font-semibold text-violet-700" href={lead.public_website_url} target="_blank" rel="noreferrer">
                      <ExternalLink className="h-3 w-3" /> Website
                    </a>
                  )}
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button onClick={() => sendLead(lead)} disabled={lead.status === 'contacted'} className="btn-primary text-sm disabled:opacity-50">
                    <Send className="h-4 w-4" /> {lead.contact_email ? 'Send Mail' : 'Enter Email & Send'}
                  </button>
                  <button onClick={() => patchLead(lead, { status: 'reviewed' })} className="btn-secondary text-sm">
                    <CheckCircle2 className="h-4 w-4" /> Reviewed
                  </button>
                  <button onClick={() => patchLead(lead, { status: 'converted' })} className="btn-secondary text-sm text-emerald-700">
                    <Mail className="h-4 w-4" /> Added
                  </button>
                  <button onClick={() => patchLead(lead, { status: 'rejected' })} className="btn-secondary text-sm text-red-600">
                    <Trash2 className="h-4 w-4" /> Reject
                  </button>
                  <button onClick={() => removeLead(lead)} className="btn-secondary text-sm text-red-600">
                    <Trash2 className="h-4 w-4" /> Delete
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-[#d8e6f5] bg-[#edf5ff] py-16 text-center text-slate-400">
          <Linkedin className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p>No LinkedIn results in this domain/status view.</p>
        </div>
      )}
    </div>
  )
}
