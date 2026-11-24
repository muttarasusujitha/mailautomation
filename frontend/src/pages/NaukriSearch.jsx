import { useCallback, useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { CheckCircle2, ExternalLink, Newspaper, RefreshCw, Search, Send, Trash2, Users } from 'lucide-react'
import api from '../utils/api'

const STATUSES = ['all', 'found', 'reviewed', 'contacted', 'converted', 'rejected']
const STATUS_LABELS = { all: 'All', found: 'New', reviewed: 'Reviewed', contacted: 'Contacted', converted: 'Added', rejected: 'Rejected' }
const NAUKRI_HOST = /(^|\.)naukri\.com$/i
const NAUKRI_PROFILE_PATH = /(?:^|\/)(?:resume|profile|candidate)(?:\/|$)|(?:^|\/)(?:resume|candidate|profile)-/i
const NAUKRI_NON_PROFILE_PATH = /(?:^|\/)(?:jobs?|job-listings?|career-advice|profile-summary|blog|campus|companies|company|services|resume-maker|resume-templates|recruiter-zone)(?:\/|$)|-jobs?(?:-|$)/i

function isNaukriUrl(value) {
  try {
    const parsed = new URL(value)
    return NAUKRI_HOST.test(parsed.hostname) &&
      NAUKRI_PROFILE_PATH.test(parsed.pathname) &&
      !NAUKRI_NON_PROFILE_PATH.test(parsed.pathname)
  } catch {
    return false
  }
}

function buildNaukriQuery(domain, location) {
  const skill = domain.trim()
  const place = location.trim()
  return [skill, place].filter(Boolean).join(' ')
}

function getStatusClass(status) {
  if (status === 'converted') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'contacted') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'rejected') return 'border-red-200 bg-red-50 text-red-700'
  if (status === 'reviewed') return 'border-violet-200 bg-violet-50 text-violet-700'
  return 'border-amber-200 bg-amber-50 text-amber-700'
}

function initials(value) {
  return String(value || 'Naukri result').replace(/[^a-zA-Z0-9\s]/g, ' ').split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase()
}

export default function NaukriSearch() {
  const [leads, setLeads] = useState([])
  const [status, setStatus] = useState('all')
  const [searchText, setSearchText] = useState('')
  const [domainsText, setDomainsText] = useState('Python')
  const [location, setLocation] = useState('India')
  const [targetCount, setTargetCount] = useState(20)
  const [loading, setLoading] = useState(false)
  const [searching, setSearching] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response = await api.get('/trainer-profile-leads', {
        params: { source: 'naukri', status, q: searchText, limit: 200 },
      })
      setLeads((response.data.leads || []).filter(lead => lead.source === 'naukri' && isNaukriUrl(lead.source_url)))
    } catch (error) {
      toast.error(error.message || 'Could not load Naukri results')
    } finally {
      setLoading(false)
    }
  }, [status, searchText])

  useEffect(() => { load() }, [load])

  const domains = useMemo(() => domainsText.split(',').map(value => value.trim()).filter(Boolean), [domainsText])
  const queries = useMemo(() => domains.map(domain => ({ domain, query: buildNaukriQuery(domain, location) })), [domains, location])

  const runSearch = async () => {
    if (!domains.length) {
      toast.error('Enter at least one skill or domain')
      return
    }
    setSearching(true)
    try {
      const response = await api.post('/trainer-profile-leads/search-public', {
        source: 'naukri', domains, queries, location,
        max_results: targetCount, max_queries: queries.length,
      })
      const saved = response.data.saved_count || 0
      const found = response.data.found || 0
      if (response.data.search_error) {
        toast.error(response.data.search_error)
      } else if (!found) {
        toast.error('No public Naukri profiles were found for these skills. Try a broader skill or location.')
      } else {
        toast.success(`Naukri search found ${found} profile${found === 1 ? '' : 's'}; ${saved} new result${saved === 1 ? '' : 's'} saved.`)
      }
      await load()
    } catch (error) {
      toast.error(error.message || 'Naukri search failed')
    } finally {
      setSearching(false)
    }
  }

  const updateLead = async (lead, patch) => {
    try {
      await api.patch(`/trainer-profile-leads/${lead.lead_id}`, patch)
      await load()
    } catch (error) {
      toast.error(error.message || 'Could not update result')
    }
  }

  const deleteLead = async lead => {
    try {
      await api.delete(`/trainer-profile-leads/${lead.lead_id}`)
      toast.success('Naukri result deleted')
      await load()
    } catch (error) {
      toast.error(error.message || 'Could not delete result')
    }
  }

  const sendLead = async lead => {
    let email = String(lead.contact_email || lead.email || '').trim()
    if (!email) email = String(window.prompt('Enter the trainer email address:') || '').trim()
    if (!email) return
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      toast.error('Enter a valid email address')
      return
    }
    try {
      const response = await api.post(`/trainer-profile-leads/${lead.lead_id}/send-email`, { to_email: email, domain: lead.domain, mode: 'Online' })
      if (response.data.success) toast.success('Approach email sent')
      else toast.error(response.data.error || 'Email could not be sent')
      await load()
    } catch (error) {
      toast.error(error.message || 'Email could not be sent')
    }
  }

  const withEmail = leads.filter(lead => lead.contact_email || lead.email).length
  const contacted = leads.filter(lead => lead.status === 'contacted').length

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2"><Newspaper className="h-6 w-6 text-blue-600" />Naukri Search</h1>
          <p className="mt-1 text-sm text-slate-500">Find publicly indexed Naukri job-seeker profiles. Private resumes require recruiter Resdex access.</p>
        </div>
        <div className="flex gap-2">
          <input className="input min-w-0" value={searchText} onChange={event => setSearchText(event.target.value)} onKeyDown={event => event.key === 'Enter' && load()} placeholder="Search saved Naukri results" />
          <button onClick={load} className="btn-secondary text-sm"><RefreshCw className="h-4 w-4" />Refresh</button>
        </div>
      </div>

      <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2"><Newspaper className="h-4 w-4 text-blue-700" /><h2 className="text-sm font-bold text-slate-900">Search public Naukri profiles</h2></div>
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <label className="block text-xs font-semibold text-slate-600">Skills or domains (comma separated)
            <input className="input mt-1 bg-white" value={domainsText} onChange={event => setDomainsText(event.target.value)} placeholder="Python, DevOps, AWS" />
          </label>
          <label className="block text-xs font-semibold text-slate-600">Location
            <input className="input mt-1 bg-white" value={location} onChange={event => setLocation(event.target.value)} placeholder="India, Bengaluru" />
          </label>
          <button onClick={runSearch} disabled={searching} className="btn-primary text-sm disabled:opacity-50"><Search className="h-4 w-4" />{searching ? 'Searching Naukri…' : 'Find Naukri Results'}</button>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <label className="shrink-0 font-semibold">Target results: {targetCount}</label>
          <input type="range" min="10" max="30" step="5" value={targetCount} onChange={event => setTargetCount(Number(event.target.value))} className="w-full accent-blue-600" />
          <span className="shrink-0">{queries.length} Naukri public-index queries</span>
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-sm text-slate-500">Job Seeker Profiles</p><p className="mt-2 text-2xl font-bold text-slate-900">{leads.length}</p></div>
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-sm text-slate-500">With Email</p><p className="mt-2 text-2xl font-bold text-slate-900">{withEmail}</p></div>
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-sm text-slate-500">Contacted</p><p className="mt-2 text-2xl font-bold text-slate-900">{contacted}</p></div>
      </div>

      <div className="flex flex-wrap gap-2 rounded-xl border border-slate-200 bg-white p-3">
        {STATUSES.map(item => <button key={item} onClick={() => setStatus(item)} className={clsx('rounded-lg px-3 py-2 text-sm font-semibold', status === item ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>{STATUS_LABELS[item]}</button>)}
        <span className="ml-auto self-center text-xs text-slate-500">{leads.length} public Naukri profiles</span>
      </div>

      {loading ? <div className="py-14 text-center text-sm text-slate-400">Loading Naukri results…</div> : leads.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {leads.map(lead => <article key={lead.lead_id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-blue-50 text-sm font-bold text-blue-700">{initials(lead.trainer_name || lead.name || lead.headline || lead.domain)}</div>
                <div className="min-w-0">
                  <h3 className="truncate font-bold text-slate-900">{lead.name || lead.headline || lead.domain || 'Naukri job seeker'}</h3>
                  <p className="mt-1 text-sm text-slate-600">{lead.domain || lead.searched_domain || 'Job seeker profile'}</p>
                  <span className={clsx('mt-2 inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold capitalize', getStatusClass(lead.status))}>{STATUS_LABELS[lead.status] || lead.status || 'New'}</span>
                </div>
              </div>
              <a href={lead.source_url} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-blue-50 px-2.5 py-1.5 text-xs font-semibold text-blue-700"><ExternalLink className="h-3.5 w-3.5" />Naukri profile</a>
            </div>
            <p className="mt-4 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-slate-600">{lead.profile_text || lead.snippet || lead.headline || 'No profile summary available.'}</p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
              {(lead.contact_email || lead.email) && <a className="rounded-lg bg-emerald-50 px-2 py-1 font-semibold text-emerald-700" href={`mailto:${lead.contact_email || lead.email}`}>{lead.contact_email || lead.email}</a>}
              {(lead.contact_phone || lead.phone) && <span className="rounded-lg bg-slate-50 px-2 py-1">{lead.contact_phone || lead.phone}</span>}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={() => sendLead(lead)} disabled={lead.status === 'contacted'} className="btn-primary text-sm disabled:opacity-50"><Send className="h-4 w-4" />{lead.contact_email || lead.email ? 'Send Email' : 'Enter Email & Send'}</button>
              <button onClick={() => updateLead(lead, { status: 'reviewed' })} className="btn-secondary text-sm"><CheckCircle2 className="h-4 w-4" />Reviewed</button>
              <button onClick={() => updateLead(lead, { status: 'converted' })} className="btn-secondary text-sm text-emerald-700"><Users className="h-4 w-4" />Added</button>
              <button onClick={() => updateLead(lead, { status: 'rejected' })} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" />Reject</button>
              <button onClick={() => deleteLead(lead)} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" />Delete</button>
            </div>
          </article>)}
        </div>
      ) : <div className="rounded-xl border border-slate-200 bg-white py-16 text-center text-slate-400"><Newspaper className="mx-auto mb-3 h-10 w-10 opacity-40" /><p>No public Naukri profiles in this view.</p></div>}
    </div>
  )
}
