import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  BriefcaseBusiness, CheckCircle2, ExternalLink, Globe2, Link2, Mail, Plus, RefreshCw,
  Save, Search, Send, Target, Trash2, Users,
} from 'lucide-react'
import api from '../utils/api'

const STATUS = ['all', 'new', 'reviewed', 'contacted', 'converted', 'rejected']
const STATUS_LABELS = {
  all: 'All',
  new: 'New',
  reviewed: 'Reviewed',
  contacted: 'Contacted',
  converted: 'Converted',
  rejected: 'Rejected',
}

const emptyForm = {
  source: 'LinkedIn',
  source_url: '',
  company_name: '',
  contact_name: '',
  contact_email: '',
  contact_phone: '',
  domain: '',
  post_text: '',
  notes: '',
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

export default function ClientLeads() {
  const [leads, setLeads] = useState([])
  const [stats, setStats] = useState({})
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [searchingPublic, setSearchingPublic] = useState(false)
  const [leadMode, setLeadMode] = useState('client')
  const [searchDomains, setSearchDomains] = useState('DevOps, AWS, Azure, Full Stack, Power BI, Python, Java, SAP')

  const load = async () => {
    setLoading(true)
    try {
      const endpoint = leadMode === 'trainer' ? '/trainer-profile-leads' : '/client-leads'
      const res = await api.get(endpoint, { params: { status: filter, q, limit: 150 } })
      setLeads(res.data.leads || [])
      setStats(res.data.stats || {})
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [filter, leadMode])

  const update = (key, value) => setForm(prev => ({ ...prev, [key]: value }))

  const analyze = async () => {
    try {
      const res = await api.post('/client-leads/analyze', form)
      setAnalysis(res.data)
      toast.success('Lead analysed')
    } catch (e) {
      toast.error(e.message)
    }
  }

  const saveLead = async () => {
    setSaving(true)
    try {
      await api.post('/client-leads', form)
      toast.success('Client lead saved')
      setForm(emptyForm)
      setAnalysis(null)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const patchLead = async (lead, payload) => {
    try {
      const endpoint = leadMode === 'trainer' ? `/trainer-profile-leads/${lead.lead_id}` : `/client-leads/${lead.lead_id}`
      await api.patch(endpoint, payload)
      await load()
    } catch (e) {
      toast.error(e.message)
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

  const removeLead = async (lead) => {
    try {
      const endpoint = leadMode === 'trainer' ? `/trainer-profile-leads/${lead.lead_id}` : `/client-leads/${lead.lead_id}`
      await api.delete(endpoint)
      toast.success('Lead removed')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const findPublicLeads = async () => {
    setSearchingPublic(true)
    try {
      const domains = searchDomains.split(',').map(item => item.trim()).filter(Boolean)
      const endpoint = leadMode === 'trainer' ? '/trainer-profile-leads/search-public' : '/client-leads/search-public'
      const res = await api.post(endpoint, {
        domains,
        max_results: 50,
        max_queries: leadMode === 'trainer' ? 20 : 12,
      })
      toast.success(`Public search saved ${res.data.saved_count || 0} lead(s)`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSearchingPublic(false)
    }
  }

  const cards = useMemo(() => [
    [leadMode === 'trainer' ? 'Trainer Profiles' : 'Total Leads', stats.total || 0, leadMode === 'trainer' ? Users : BriefcaseBusiness, 'text-slate-700'],
    [leadMode === 'trainer' ? 'New Profiles' : 'New Leads', stats.new || 0, Target, 'text-amber-700'],
    ['Contacted', stats.contacted || 0, Send, 'text-blue-700'],
    ['Converted', stats.converted || 0, CheckCircle2, 'text-emerald-700'],
  ], [stats, leadMode])

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <BriefcaseBusiness className="h-6 w-6 text-blue-600" /> Client Leads
          </h1>
          <p className="mt-1 text-sm text-slate-500">Search public LinkedIn/web results for client requirements or trainer profiles, then review before action.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-[260px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && load()} placeholder="Search leads" className="input pl-9" />
          </div>
          <button onClick={load} className="btn-secondary text-sm"><RefreshCw className="h-4 w-4" /> Search</button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
        <button
          onClick={() => setLeadMode('client')}
          className={clsx('inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition', leadMode === 'client' ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}
        >
          <BriefcaseBusiness className="h-4 w-4" /> Client Requirement Posts
        </button>
        <button
          onClick={() => setLeadMode('trainer')}
          className={clsx('inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition', leadMode === 'trainer' ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}
        >
          <Users className="h-4 w-4" /> Trainer Profiles
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(([label, value, Icon, tone]) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-500">{label}</p>
              <Icon className={clsx('h-4 w-4', tone)} />
            </div>
            <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
          </div>
        ))}
      </div>

      <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 shadow-sm">
          <div className="flex flex-col gap-3">
            <div className="min-w-0 flex-1">
              <div className="mb-2 flex items-center gap-2">
                <Globe2 className="h-4 w-4 text-blue-700" />
                <h2 className="text-sm font-bold text-slate-900">{leadMode === 'trainer' ? 'Find Public Trainer Profiles' : 'Find Public Client Leads'}</h2>
              </div>
              <p className="mb-3 text-xs leading-5 text-slate-600">
                {leadMode === 'trainer'
                  ? 'Searches public LinkedIn profile results for trainers in the selected domain. It does not login to LinkedIn or scrape private data.'
                  : 'Searches public web results for trainer requirement posts. It does not login to LinkedIn or send LinkedIn messages.'}
              </p>
              <input
                className="input bg-white"
                value={searchDomains}
                onChange={e => setSearchDomains(e.target.value)}
                placeholder={leadMode === 'trainer' ? 'Trainer domain, e.g. SAP S/4HANA, Apache APISIX' : 'Domains, comma separated'}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button onClick={findPublicLeads} disabled={searchingPublic} className="btn-primary text-sm disabled:opacity-50">
              {searchingPublic ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {leadMode === 'trainer' ? 'Find Trainer Profiles' : 'Find Leads Now'}
              </button>
              <span className="rounded-lg border border-blue-200 bg-white/70 px-3 py-2 text-xs font-semibold text-blue-700">
                Requires TAVILY_API_KEY
              </span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Plus className="h-4 w-4 text-blue-600" />
            <h2 className="text-sm font-bold text-slate-900">Add Public Requirement Lead</h2>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <input className="input" value={form.source} onChange={e => update('source', e.target.value)} placeholder="Source: LinkedIn / Google / Website" />
            <input className="input" value={form.domain} onChange={e => update('domain', e.target.value)} placeholder="Domain, e.g. DevOps" />
            <input className="input" value={form.company_name} onChange={e => update('company_name', e.target.value)} placeholder="Company name" />
            <input className="input" value={form.contact_name} onChange={e => update('contact_name', e.target.value)} placeholder="Contact person" />
            <input className="input lg:col-span-2" value={form.source_url} onChange={e => update('source_url', e.target.value)} placeholder="Post URL" />
            <input className="input lg:col-span-2" value={form.contact_email} onChange={e => update('contact_email', e.target.value)} placeholder="Public email if available" />
          </div>
          <textarea className="input mt-3 min-h-28" value={form.post_text} onChange={e => update('post_text', e.target.value)} placeholder="Paste public post text here, e.g. Need DevOps trainer for corporate batch..." />
          <div className="mt-3 flex flex-wrap gap-2">
            <button onClick={analyze} className="btn-secondary text-sm"><Search className="h-4 w-4" /> Analyse</button>
            <button onClick={saveLead} disabled={saving} className="btn-primary text-sm disabled:opacity-50"><Save className="h-4 w-4" /> Save Lead</button>
          </div>
          {analysis && (
            <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-slate-700">
              <p><strong>Detected:</strong> {analysis.analysis.is_trainer_requirement_lead ? 'Trainer requirement lead' : 'Needs review'}</p>
              <p><strong>Domain:</strong> {analysis.analysis.domain || 'Not detected'} | <strong>Confidence:</strong> {Math.round((analysis.analysis.confidence || 0) * 100)}%</p>
              <p className="mt-2 whitespace-pre-wrap"><strong>Draft:</strong> {analysis.draft.body}</p>
            </div>
          )}
        </div>
      </section>

      <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
        {STATUS.map(item => (
          <button key={item} onClick={() => setFilter(item)} className={clsx('rounded-lg px-3 py-2 text-sm font-semibold transition', filter === item ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>
            {STATUS_LABELS[item]}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="py-14 text-center text-sm text-slate-400">Loading leads...</div>
      ) : leads.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {leads.map(lead => (
            <article key={lead.lead_id} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-bold text-slate-900">
                      {leadMode === 'trainer'
                        ? (lead.trainer_name || lead.headline || lead.domain || 'Trainer profile')
                        : (lead.company_name || lead.contact_name || lead.domain || 'Client lead')}
                    </h3>
                    <span className={clsx('rounded-lg border px-2 py-0.5 text-xs font-semibold capitalize', statusClass(lead.status))}>{lead.status}</span>
                    <span className="text-xs text-slate-400">{relativeTime(lead.created_at)}</span>
                  </div>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
                    <span className="font-semibold text-slate-800">{lead.domain || 'Domain pending'}</span>
                    <span>from {lead.source || 'Manual'}</span>
                  </p>
                </div>
                <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">{Math.round((lead.confidence || 0) * 100)}%</span>
              </div>
              <p className="mt-3 line-clamp-3 text-sm leading-6 text-slate-600">
                {leadMode === 'trainer' ? (lead.profile_text || lead.headline || lead.notes || 'No public profile text saved.') : (lead.post_text || lead.notes || 'No post text saved.')}
              </p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                {lead.contact_email && <span className="rounded-lg bg-slate-50 px-2 py-1">{lead.contact_email}</span>}
                {lead.contact_phone && <span className="rounded-lg bg-slate-50 px-2 py-1">{lead.contact_phone}</span>}
                {lead.source_url && (
                  <a
                    className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 font-semibold text-blue-700"
                    href={lead.source_url}
                    target="_blank"
                    rel="noreferrer"
                    title={leadMode === 'trainer' ? 'Open this trainer profile on LinkedIn' : 'Open source post'}
                  >
                    {leadMode === 'trainer' ? <ExternalLink className="h-3 w-3" /> : <Link2 className="h-3 w-3" />}
                    {leadMode === 'trainer' ? 'Open LinkedIn Profile' : 'Source'}
                  </a>
                )}
              </div>
              {leadMode === 'client' && lead.draft?.body && (
                <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
                  <summary className="cursor-pointer font-semibold text-slate-700">Approach draft</summary>
                  <p className="mt-2 whitespace-pre-wrap text-slate-600">{lead.draft.body}</p>
                </details>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                {leadMode === 'trainer' && lead.source_url && (
                  <a
                    href={lead.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="btn-primary text-sm"
                  >
                    <ExternalLink className="h-4 w-4" /> Open Profile
                  </a>
                )}
                {leadMode === 'client' && (
                  <button onClick={() => sendLead(lead)} disabled={!lead.contact_email || lead.status === 'contacted'} className="btn-primary text-sm disabled:opacity-50"><Send className="h-4 w-4" /> Send Mail</button>
                )}
                <button onClick={() => patchLead(lead, { status: 'reviewed' })} className="btn-secondary text-sm"><CheckCircle2 className="h-4 w-4" /> Reviewed</button>
                <button onClick={() => patchLead(lead, { status: 'converted' })} className="btn-secondary text-sm text-emerald-700"><Mail className="h-4 w-4" /> {leadMode === 'trainer' ? 'Added' : 'Converted'}</button>
                <button onClick={() => patchLead(lead, { status: 'rejected' })} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" /> Reject</button>
                <button onClick={() => removeLead(lead)} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" /> Delete</button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white py-16 text-center text-slate-400">
          <BriefcaseBusiness className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p>No {leadMode === 'trainer' ? 'trainer profile leads' : 'client leads'} in this view.</p>
        </div>
      )}
    </div>
  )
}
