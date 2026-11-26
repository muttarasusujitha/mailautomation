import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { Bot, CheckCircle2, Clock3, ExternalLink, FileUp, Newspaper, Pause, Play, RefreshCw, Search, Send, Trash2, Users } from 'lucide-react'
import api from '../utils/api'
import Pager from '../components/Pager'
import SearchSourceReport from '../components/SearchSourceReport'
import { LEAD_PAGE_SIZE, leadListParams, listPage, pageToReload, readyForMail1, statusCountInView } from '../utils/leadPaging'
import { newSearchRef } from '../utils/leadSearchFeedback'
import { firstContactMail } from '../utils/trainerOutreachMail'

const STATUSES = ['all', 'found', 'reviewed', 'contacted', 'converted', 'rejected']
const STATUS_LABELS = { all: 'All', found: 'New', reviewed: 'Reviewed', contacted: 'Contacted', converted: 'Added', rejected: 'Rejected' }

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

function formatTimestamp(value) {
  if (!value) return ''
  const text = String(value)
  const date = new Date(text.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(text) ? text : `${text}Z`)
  return Number.isNaN(date.getTime()) ? text : date.toLocaleString(undefined, { timeZoneName: 'short' })
}

const IMPORT_FIELDS = [
  { key: 'name', label: 'Candidate name', aliases: ['name', 'candidate name', 'full name', 'applicant name', 'resume name'] },
  { key: 'headline', label: 'Headline / designation', aliases: ['headline', 'designation', 'current designation', 'title', 'profile headline', 'current role'] },
  { key: 'skills', label: 'Skills', aliases: ['skills', 'key skills', 'skill set', 'keywords', 'domain'] },
  { key: 'location', label: 'Location', aliases: ['location', 'current location', 'preferred location', 'city'] },
  { key: 'experience', label: 'Experience', aliases: ['experience', 'total experience', 'work experience', 'years of experience'] },
  { key: 'company', label: 'Current company', aliases: ['company', 'current company', 'employer', 'organization'] },
  { key: 'email', label: 'Email', aliases: ['email', 'email id', 'e-mail', 'candidate email'] },
  { key: 'phone', label: 'Phone', aliases: ['phone', 'mobile', 'mobile number', 'contact number', 'phone number'] },
  { key: 'profile_url', label: 'Naukri profile URL', aliases: ['profile url', 'naukri profile', 'profile link', 'resume url', 'url'] },
  { key: 'summary', label: 'Resume summary', aliases: ['summary', 'resume summary', 'profile summary', 'resume headline', 'description'] },
]

function parseDelimited(text, delimiter) {
  const rows = []
  let row = []; let cell = ''; let quoted = false
  const input = String(text || '').replace(/^\uFEFF/, '')
  for (let i = 0; i < input.length; i += 1) {
    const char = input[i]
    if (char === '"') {
      if (quoted && input[i + 1] === '"') { cell += '"'; i += 1 }
      else quoted = !quoted
    } else if (!quoted && char === delimiter) { row.push(cell.trim()); cell = '' }
    else if (!quoted && (char === '\n' || char === '\r')) {
      if (char === '\r' && input[i + 1] === '\n') i += 1
      row.push(cell.trim()); cell = ''
      if (row.some(Boolean)) rows.push(row)
      row = []
    } else cell += char
  }
  row.push(cell.trim())
  if (row.some(Boolean)) rows.push(row)
  return rows
}

function normalizeHeader(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
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
  const [page, setPage] = useState(1)
  const [list, setList] = useState(listPage())
  const [searchReport, setSearchReport] = useState(null)
  const [importHeaders, setImportHeaders] = useState([])
  const [importRows, setImportRows] = useState([])
  const [importMapping, setImportMapping] = useState({})
  const [importing, setImporting] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const loadSeq = useRef(0)
  const [botSettings, setBotSettings] = useState(null)
  const [savingBot, setSavingBot] = useState(false)
  const previousBotRun = useRef('')

  const load = useCallback(async () => {
    // Only the latest request updates the list: the search box reloads on every keystroke.
    const seq = ++loadSeq.current
    setLoading(true)
    try {
      // The server keeps only public Naukri profile pages (kind=naukri_profile), so every page is full.
      const response = await api.get('/trainer-profile-leads', {
        params: leadListParams({ kind: 'naukri_profile', status, q: searchText, page }),
      })
      if (seq !== loadSeq.current) return
      const reload = pageToReload(response.data, page)
      if (reload) {
        setPage(reload)
        return
      }
      setLeads(response.data.leads || [])
      setList(listPage(response.data))
    } catch (error) {
      if (seq === loadSeq.current) toast.error(error.message || 'Could not load Naukri results')
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }, [status, searchText, page])

  useEffect(() => { load() }, [load, reloadKey])

  // Reloads with the filters as they are when the reload runs, not when an action started.
  const refresh = useCallback(() => setReloadKey(key => key + 1), [])

  useEffect(() => {
    let active = true
    let reportedError = false
    const refreshBot = () => api.get('/linkedin-leads/bot/naukri')
      .then(response => {
        if (!active) return
        reportedError = false
        const nextSettings = response.data || {}
        if (previousBotRun.current && nextSettings.last_finished && nextSettings.last_finished !== previousBotRun.current) refresh()
        previousBotRun.current = nextSettings.last_finished || ''
        setBotSettings(nextSettings)
      })
      .catch(error => {
        if (active && !reportedError) toast.error(error.message || 'Could not load Naukri bot settings')
        reportedError = true
      })
    refreshBot()
    const timer = window.setInterval(refreshBot, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [refresh])

  const domains = useMemo(() => domainsText.split(',').map(value => value.trim()).filter(Boolean), [domainsText])
  const queries = useMemo(() => domains.map(domain => ({ domain, query: buildNaukriQuery(domain, location) })), [domains, location])

  const runSearch = async () => {
    if (!domains.length) {
      toast.error('Enter at least one skill or domain')
      return
    }
    setSearching(true)
    setSearchReport(null)
    const searchRef = newSearchRef()
    try {
      const response = await api.post('/trainer-profile-leads/search-public', {
        source: 'naukri', domains, queries, location,
        max_results: targetCount, max_queries: queries.length, search_ref: searchRef,
      })
      setSearchReport(response.data)
      const saved = response.data.saved_count || 0
      const found = response.data.found || 0
      if (response.data.search_error) {
        toast.error(response.data.search_error)
      } else if (!found) {
        toast.error('No public Naukri profiles were found for these skills. Try a broader skill or location.')
      } else {
        toast.success(`Naukri search found ${found} profile${found === 1 ? '' : 's'}; ${saved} new result${saved === 1 ? '' : 's'} saved.`)
      }
      setPage(1)
      refresh()
    } catch (error) {
      setSearchReport({ requestFailed: true, searchRef, search_error: error.message || 'Naukri search failed' })
      toast.error(error.message || 'Naukri search failed')
    } finally {
      setSearching(false)
    }
  }

  const loadExportFile = async file => {
    if (!file) return
    try {
      const raw = await file.text()
      const firstLine = raw.split(/\r?\n/, 1)[0] || ''
      const delimiter = firstLine.includes('\t') ? '\t' : ','
      const parsed = parseDelimited(raw, delimiter)
      if (parsed.length < 2) { toast.error('This file has no candidate rows'); return }
      const headers = parsed[0].map((header, index) => header || `Column ${index + 1}`)
      const rows = parsed.slice(1).filter(row => row.some(Boolean)).slice(0, 500)
      const mapping = {}
      for (const field of IMPORT_FIELDS) {
        const aliases = field.aliases.map(normalizeHeader)
        const index = headers.findIndex(header => aliases.includes(normalizeHeader(header)))
        if (index >= 0) mapping[field.key] = String(index)
      }
      setImportHeaders(headers)
      setImportRows(rows)
      setImportMapping(mapping)
      if (parsed.length - 1 > 500) toast('Only the first 500 rows can be imported per batch.')
    } catch (error) {
      toast.error(error.message || 'Could not read this file')
    }
  }

  const importExport = async () => {
    if (!importRows.length) return
    if (importMapping.name === undefined || importMapping.name === '') { toast.error('Map a column to Candidate name first'); return }
    setImporting(true)
    try {
      const candidates = importRows.map(row => Object.fromEntries(IMPORT_FIELDS.map(field => [
        field.key, importMapping[field.key] === undefined ? '' : (row[Number(importMapping[field.key])] || ''),
      ])))
      const response = await api.post('/trainer-profile-leads/import-resdex', { candidates })
      toast.success(`${response.data.imported} imported, ${response.data.duplicates} already saved, ${response.data.skipped} skipped.`)
      setImportRows([]); setImportHeaders([]); setImportMapping({})
      setPage(1); refresh()
    } catch (error) {
      toast.error(error.message || 'Could not import Resdex export')
    } finally {
      setImporting(false)
    }
  }

  const saveBot = async enabled => {
    const botDomains = domains.slice(0, 4)
    if (enabled && !botDomains.length) {
      toast.error('Enter at least one skill or domain')
      return
    }
    setSavingBot(true)
    try {
      const response = await api.put('/linkedin-leads/bot/naukri', {
        enabled,
        domains: botDomains.length ? botDomains : (botSettings?.domains || []),
        location,
        interval_minutes: Number(botSettings?.interval_minutes || 360),
      })
      setBotSettings(response.data || {})
      toast.success(enabled ? 'Naukri recruiter bot enabled' : 'Naukri recruiter bot paused')
    } catch (error) {
      toast.error(error.message || 'Could not update Naukri bot')
    } finally {
      setSavingBot(false)
    }
  }

  const saveInterval = async value => {
    const interval_minutes = Number(value)
    setBotSettings(current => ({ ...current, interval_minutes }))
    try {
      const response = await api.put('/linkedin-leads/bot/naukri', {
        enabled: Boolean(botSettings?.enabled),
        domains: botSettings?.domains?.length ? botSettings.domains : (domains.length ? domains.slice(0, 4) : ['Python']),
        location: botSettings?.location || location,
        interval_minutes,
      })
      setBotSettings(response.data || {})
    } catch (error) {
      toast.error(error.message || 'Could not save bot schedule')
    }
  }

  const updateLead = async (lead, patch) => {
    try {
      await api.patch(`/trainer-profile-leads/${lead.lead_id}`, patch)
      refresh()
    } catch (error) {
      toast.error(error.message || 'Could not update result')
    }
  }

  const deleteLead = async lead => {
    try {
      await api.delete(`/trainer-profile-leads/${lead.lead_id}`)
      toast.success('Naukri result deleted')
      refresh()
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
      const response = await api.post(`/trainer-profile-leads/${lead.lead_id}/send-email`, {
        ...firstContactMail({ lead, mailContext: { domain: lead.domain, mode: 'Online' }, foundOn: 'Naukri profile' }),
        to_email: email, sent_status: 'contacted',
      })
      if (response.data.success) toast.success('Approach email sent')
      else toast.error(response.data.error || 'Email could not be sent')
      refresh()
    } catch (error) {
      toast.error(error.message || 'Email could not be sent')
    }
  }

  // The cards count every page of the open status tab and search text.
  const withEmail = list.counts?.with_email || 0
  const contacted = statusCountInView(list.counts, status, 'contacted')

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2"><Newspaper className="h-6 w-6 text-blue-600" />Naukri Search</h1>
          <p className="mt-1 text-sm text-slate-500">Find publicly indexed Naukri job-seeker profiles. Private resumes require recruiter Resdex access.</p>
        </div>
        <div className="flex gap-2">
          <input className="input min-w-0" value={searchText} onChange={event => { setSearchText(event.target.value); setPage(1) }} onKeyDown={event => event.key === 'Enter' && load()} placeholder="Search saved Naukri results" />
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

      <section className="space-y-4 rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 shadow-sm">
        <div className="flex items-center gap-2"><FileUp className="h-4 w-4 text-emerald-700" /><h2 className="text-sm font-bold text-slate-900">Import authorized Resdex export</h2></div>
        <p className="text-xs text-slate-600">Upload a CSV or TSV downloaded through your Naukri recruiter account. The file is read here, and candidate columns are matched before import. This does not sign in to Naukri or access private resumes.</p>
        <input type="file" accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values" onChange={event => loadExportFile(event.target.files?.[0])} className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-white file:px-3 file:py-2 file:text-sm file:font-semibold file:text-slate-700" />
        {importRows.length > 0 && <>
          <p className="text-xs font-semibold text-slate-700">{importRows.length} rows ready. Check the column matches:</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {IMPORT_FIELDS.map(field => <label key={field.key} className="block text-xs font-semibold text-slate-600">{field.label}{field.key === 'name' ? ' *' : ''}
              <select className="input mt-1 bg-white" value={importMapping[field.key] ?? ''} onChange={event => setImportMapping(current => ({ ...current, [field.key]: event.target.value }))}>
                <option value="">Not mapped</option>
                {importHeaders.map((header, index) => <option key={`${index}-${header}`} value={String(index)}>{header}</option>)}
              </select>
            </label>)}
          </div>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="min-w-full text-left text-xs"><thead><tr>{importHeaders.map((header, index) => <th key={`${index}-${header}`} className="whitespace-nowrap px-3 py-2 font-semibold text-slate-600">{header}</th>)}</tr></thead>
              <tbody>{importRows.slice(0, 3).map((row, index) => <tr key={index} className="border-t border-slate-100">{importHeaders.map((_, column) => <td key={column} className="max-w-56 truncate px-3 py-2 text-slate-600">{row[column] || '—'}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <button onClick={importExport} disabled={importing || importMapping.name === undefined || importMapping.name === ''} className="btn-primary text-sm disabled:opacity-50"><FileUp className="h-4 w-4" />{importing ? 'Importing…' : `Import ${importRows.length} candidates`}</button>
        </>}
      </section>

      <section className="space-y-3 rounded-xl border border-blue-200 bg-blue-50 p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <Bot className="mt-0.5 h-5 w-5 text-blue-700" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-bold text-slate-900">Naukri Recruiter Bot</h2>
            <p className="mt-1 text-xs text-slate-600">Automatically checks publicly indexed Naukri profiles on a schedule and saves new matches for review. Private Resdex resumes are not accessed.</p>
          </div>
          <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${botSettings?.enabled ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>
            {botSettings?.status === 'running' ? 'Running search' : botSettings?.enabled ? 'Enabled' : 'Paused'}
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <label className="block text-xs font-semibold text-slate-600">Check every
            <select className="input mt-1 bg-white" disabled={!botSettings || savingBot} value={botSettings?.interval_minutes || 360} onChange={event => saveInterval(event.target.value)}>
              <option value="60">1 hour</option><option value="180">3 hours</option><option value="360">6 hours</option><option value="720">12 hours</option><option value="1440">24 hours</option>
            </select>
          </label>
          <div className="flex gap-2">
            <button onClick={() => saveBot(true)} disabled={savingBot} className="btn-primary text-sm disabled:opacity-50"><Play className="h-4 w-4" />Enable bot</button>
            <button onClick={() => saveBot(false)} disabled={savingBot} className="btn-secondary text-sm disabled:opacity-50"><Pause className="h-4 w-4" />Pause</button>
          </div>
        </div>
        {botSettings?.last_finished && <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
          <span><Clock3 className="mr-1 inline h-3.5 w-3.5" />Last check: {formatTimestamp(botSettings.last_finished)}</span>
          <span>{botSettings.found || 0} matches, {botSettings.saved || 0} new profiles saved</span>
          {botSettings.last_error && <span className="text-amber-800">{botSettings.last_error}</span>}
        </div>}
        {(botSettings?.last_started || botSettings?.next_run) && <p className="text-xs text-slate-500">
          {botSettings.last_started ? `Last started: ${formatTimestamp(botSettings.last_started)}` : ''}
          {botSettings.next_run ? ` · Next run: ${formatTimestamp(botSettings.next_run)}` : ''}
        </p>}
      </section>

      <SearchSourceReport report={searchReport} noun="Naukri profiles" />

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-sm text-slate-500">Job Seeker Profiles</p><p className="mt-2 text-2xl font-bold text-slate-900">{list.total}</p></div>
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-sm text-slate-500">With Email</p><p className="mt-2 text-2xl font-bold text-slate-900">{withEmail}</p></div>
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-sm text-slate-500">Contacted</p><p className="mt-2 text-2xl font-bold text-slate-900">{contacted}</p></div>
      </div>

      <div className="flex flex-wrap gap-2 rounded-xl border border-slate-200 bg-white p-3">
        {STATUSES.map(item => <button key={item} onClick={() => { setStatus(item); setPage(1) }} className={clsx('rounded-lg px-3 py-2 text-sm font-semibold', status === item ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>{STATUS_LABELS[item]}</button>)}
        <span className="ml-auto self-center text-xs text-slate-500">{list.total} Naukri candidates</span>
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
              {lead.source_url ? <a href={lead.source_url} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-blue-50 px-2.5 py-1.5 text-xs font-semibold text-blue-700"><ExternalLink className="h-3.5 w-3.5" />Naukri profile</a> : <span className="inline-flex shrink-0 rounded-lg bg-emerald-50 px-2.5 py-1.5 text-xs font-semibold text-emerald-700">Resdex import</span>}
            </div>
            <p className="mt-4 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-slate-600">{lead.profile_text || lead.snippet || lead.headline || 'No profile summary available.'}</p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
              {(lead.contact_email || lead.email) && <a className="rounded-lg bg-emerald-50 px-2 py-1 font-semibold text-emerald-700" href={`mailto:${lead.contact_email || lead.email}`}>{lead.contact_email || lead.email}</a>}
              {(lead.contact_phone || lead.phone) && <span className="rounded-lg bg-slate-50 px-2 py-1">{lead.contact_phone || lead.phone}</span>}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={() => sendLead(lead)} disabled={!readyForMail1(lead)} title={readyForMail1(lead) ? undefined : 'The approach email goes to profiles not yet contacted, added or rejected'} className="btn-primary text-sm disabled:opacity-50"><Send className="h-4 w-4" />{lead.contact_email || lead.email ? 'Send Email' : 'Enter Email & Send'}</button>
              <button onClick={() => updateLead(lead, { status: 'reviewed' })} className="btn-secondary text-sm"><CheckCircle2 className="h-4 w-4" />Reviewed</button>
              <button onClick={() => updateLead(lead, { status: 'converted' })} className="btn-secondary text-sm text-emerald-700"><Users className="h-4 w-4" />Added</button>
              <button onClick={() => updateLead(lead, { status: 'rejected' })} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" />Reject</button>
              <button onClick={() => deleteLead(lead)} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" />Delete</button>
            </div>
          </article>)}
        </div>
      ) : <div className="rounded-xl border border-slate-200 bg-white py-16 text-center text-slate-400"><Newspaper className="mx-auto mb-3 h-10 w-10 opacity-40" /><p>No Naukri candidates in this view. Run public search or import an authorized Resdex export above.</p></div>}

      <Pager page={list.page} pages={list.pages} total={list.total} pageSize={LEAD_PAGE_SIZE} loading={loading} onPage={setPage} noun="Naukri profiles" />
    </div>
  )
}
