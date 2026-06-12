import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  BriefcaseBusiness, CheckCircle2, ExternalLink, Globe2, Mail, RefreshCw,
  Search, Send, Trash2, Users,
} from 'lucide-react'
import api from '../utils/api'
import { TrustLegend, VerificationBadge } from '../components/VerificationBadge'

const VISIBLE_STATUSES = ['new', 'reviewed', 'contacted', 'converted', 'rejected']
const STATUS = ['all', 'new', 'reviewed', 'contacted', 'converted', 'rejected']
const STATUS_LABELS = {
  all: 'All',
  new: 'New',
  reviewed: 'Reviewed',
  contacted: 'Contacted',
  converted: 'Added / Converted',
  rejected: 'Rejected',
}

function statusClass(status) {
  if (status === 'converted') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'contacted') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'reviewed') return 'border-violet-200 bg-violet-50 text-violet-700'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

function initials(value) {
  const words = String(value || '').replace(/[^a-zA-Z0-9\s]/g, ' ').split(/\s+/).filter(Boolean)
  return (words[0]?.[0] || 'L') + (words[1]?.[0] || '')
}

function relativeTime(value) {
  if (!value) return ''
  const diff = Math.max(0, Date.now() - new Date(value).getTime())
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${Math.max(1, mins)} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? '' : 's'} ago`
  const days = Math.floor(hrs / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
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
  const text = leadSearchText(lead)
  const blockers = [
    ' job ', ' jobs ', 'job vacancies', 'job vacancy', 'apply to', 'job description', 'required candidate profile',
    'current ctc', 'expected ctc', 'notice period', 'immediate joiner',
    'last working day', 'offer in hand', 'actively exploring', 'open to opportunities',
    'willing to relocate', 'application for', 'my resume', 'ready to work from office',
    'work preference', 'looking for job', 'seeking opportunity',
    'institute', 'academy', 'pvt ltd', 'private limited', 'solutions', 'technologies',
    'consultant', 'consulting', 'consultant1 day ago', 'consultant2 days ago', 'consultant3 days ago', 'recruiter',
    'location ', 'experience ', 'yrs · consultant', 'yrs consultant',
  ]
  if (blockers.some(token => text.includes(token))) return false
  const signals = [
    'trainer profile', 'freelance trainer', 'corporate trainer', 'technical trainer',
    'training delivery', 'conduct trainings', 'conducted trainings', 'delivered training',
    'instructor', 'faculty',
    'mentor', 'coach', 'online training', 'classroom training',
  ]
  return signals.some(token => text.includes(token))
}

export default function LinkedInShortlist() {
  const [mode, setMode] = useState('trainer')
  const [status, setStatus] = useState('all')
  const [q, setQ] = useState('')
  const [domainFilter, setDomainFilter] = useState('')
  const [mailContext, setMailContext] = useState({
    domain: '',
    duration: '',
    mode: 'Online',
    participants: '',
    requirement_note: '',
  })
  const [domainOptions, setDomainOptions] = useState([])
  const [leads, setLeads] = useState([])
  const [loading, setLoading] = useState(false)
  const [bulkLoading, setBulkLoading] = useState(false)
  const isTrainer = mode === 'trainer'

  const load = async () => {
    setLoading(true)
    try {
      const endpoint = isTrainer ? '/trainer-profile-leads' : '/client-leads'
      const res = await api.get(endpoint, { params: { status: 'all', q, limit: 300 } })
      const allLinkedInRows = (res.data.leads || [])
        .filter(item => VISIBLE_STATUSES.includes(String(item.status || '').toLowerCase()))
        .filter(item => !isTrainer || isTrainerProviderProfile(item))
      const counts = new Map()
      allLinkedInRows.forEach(item => {
        const domain = leadDomain(item)
        counts.set(domain, (counts.get(domain) || 0) + 1)
      })
      setDomainOptions(Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])))
      const rows = allLinkedInRows
        .filter(item => {
          const domain = domainFilter.trim().toLowerCase()
          if (!domain) return true
          return leadDomain(item).toLowerCase() === domain || leadSearchText(item).includes(domain)
        })
      setLeads(status === 'all' ? rows : rows.filter(item => item.status === status))
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [mode, status, domainFilter])

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
      toast.success('Removed from shortlist')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const sendLead = async (lead) => {
    try {
      let toEmail = String(lead.contact_email || '').trim()
      if (!toEmail) {
        toEmail = window.prompt('Email is not public on this LinkedIn profile. Enter email to send Clahan approach mail:')
        toEmail = String(toEmail || '').trim()
        if (!toEmail) return
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(toEmail)) {
          toast.error('Enter a valid email address')
          return
        }
      }
      const endpoint = isTrainer ? `/trainer-profile-leads/${lead.lead_id}/send-email` : `/client-leads/${lead.lead_id}/send-email`
      const payload = isTrainer ? {
        ...mailContext,
        to_email: toEmail,
        domain: mailContext.domain || lead.domain,
      } : { to_email: toEmail }
      const res = await api.post(endpoint, payload)
      if (res.data.success) toast.success('Approach mail sent from Clahan')
      else toast.error(res.data.error || 'Mail failed')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const enrichPublicEmails = async () => {
    if (!isTrainer) {
      toast.error('Public email enrichment is available for trainer profiles')
      return
    }
    setBulkLoading(true)
    try {
      const res = await api.post('/trainer-profile-leads/enrich-public-emails', {
        domain: domainFilter || mailContext.domain,
        limit: 100,
      })
      toast.success(`Public email scan complete: ${res.data.enriched_count || 0} profile(s) updated`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBulkLoading(false)
    }
  }

  const sendPublicEmailOutreach = async () => {
    if (!isTrainer) {
      toast.error('Bulk outreach is available for trainer profiles')
      return
    }
    const domainLabel = domainFilter || mailContext.domain || 'all visible domains'
    if (!window.confirm(`Send Clahan outreach mail to all valid public emails for ${domainLabel}? Already-contacted and rejected profiles will be skipped.`)) return
    setBulkLoading(true)
    try {
      const res = await api.post('/trainer-profile-leads/send-public-email-outreach', {
        ...mailContext,
        domain: domainFilter || mailContext.domain,
        limit: 50,
      })
      toast.success(`Outreach sent: ${res.data.sent_count || 0}, skipped: ${res.data.skipped_count || 0}, failed: ${res.data.failed_count || 0}`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBulkLoading(false)
    }
  }

  const counts = useMemo(() => ({
    total: leads.length,
    reviewed: leads.filter(item => item.status === 'reviewed').length,
    contacted: leads.filter(item => item.status === 'contacted').length,
    converted: leads.filter(item => item.status === 'converted').length,
  }), [leads])

  const groupedDomains = useMemo(() => {
    const groups = new Map()
    leads.forEach(lead => {
      const domain = leadDomain(lead)
      if (!groups.has(domain)) groups.set(domain, [])
      groups.get(domain).push(lead)
    })
    return Array.from(groups.entries()).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
  }, [leads])

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <CheckCircle2 className="h-6 w-6 text-blue-600" /> LinkedIn Shortlist
          </h1>
          <p className="mt-1 text-sm text-slate-500">Maintain LinkedIn searched domains, trainer profiles, and client posts in one clean shortlist view.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-[260px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && load()} placeholder="Search shortlist" className="input pl-9" />
          </div>
          <button onClick={load} className="btn-secondary text-sm"><RefreshCw className="h-4 w-4" /> Search</button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
        <button onClick={() => setMode('trainer')} className={clsx('inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition', isTrainer ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>
          <Users className="h-4 w-4" /> Trainer Profiles
        </button>
        <button onClick={() => setMode('client')} className={clsx('inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition', !isTrainer ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>
          <BriefcaseBusiness className="h-4 w-4" /> Client Posts
        </button>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr] xl:grid-cols-[1fr_1fr_1fr_1fr]">
          <div>
            <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Domain Filter</label>
            <input className="input" value={domainFilter} onChange={e => setDomainFilter(e.target.value)} onKeyDown={e => e.key === 'Enter' && load()} placeholder="Example: SAP, Python, DevOps" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Mail Domain</label>
            <input className="input" value={mailContext.domain} onChange={e => setMailContext(prev => ({ ...prev, domain: e.target.value }))} placeholder="Used in trainer mail" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Duration</label>
            <input className="input" value={mailContext.duration} onChange={e => setMailContext(prev => ({ ...prev, duration: e.target.value }))} placeholder="Example: 5 days" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Mode</label>
            <select className="input" value={mailContext.mode} onChange={e => setMailContext(prev => ({ ...prev, mode: e.target.value }))}>
              <option>Online</option>
              <option>Offline</option>
              <option>Hybrid</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Participants</label>
            <input className="input" value={mailContext.participants} onChange={e => setMailContext(prev => ({ ...prev, participants: e.target.value }))} placeholder="Example: 20" />
          </div>
          <div className="lg:col-span-2 xl:col-span-3">
            <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Requirement Note</label>
            <input className="input" value={mailContext.requirement_note} onChange={e => setMailContext(prev => ({ ...prev, requirement_note: e.target.value }))} placeholder="Optional note for trainer mail" />
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button onClick={load} className="btn-secondary text-sm"><Search className="h-4 w-4" /> Apply Filter</button>
          {isTrainer && (
            <>
              <button onClick={enrichPublicEmails} disabled={bulkLoading} className="btn-secondary text-sm disabled:opacity-50"><RefreshCw className="h-4 w-4" /> Find Public Emails</button>
              <button onClick={sendPublicEmailOutreach} disabled={bulkLoading} className="btn-primary text-sm disabled:opacity-50"><Send className="h-4 w-4" /> Send Public Email Outreach</button>
            </>
          )}
          <span className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700">
            Trainer mail uses these fields, similar to shortlist pipeline Mail 1.
          </span>
        </div>
      </section>

      <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
        <div className="mb-2 flex items-center justify-between gap-3">
          <p className="text-sm font-bold text-slate-800">Domain Shortlist</p>
          <span className="text-xs font-semibold text-slate-400">{leads.length} visible</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setDomainFilter('')}
            className={clsx('rounded-lg px-3 py-2 text-xs font-bold transition', !domainFilter ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100')}
          >
            All Domains
          </button>
          {domainOptions.map(([domain, count]) => (
            <button
              key={domain}
              onClick={() => setDomainFilter(domain)}
              className={clsx('rounded-lg px-3 py-2 text-xs font-bold transition', domainFilter === domain ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100')}
            >
              {domain} ({count})
            </button>
          ))}
        </div>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-bold text-slate-900">Decide Profiles By Domain</h2>
            <p className="mt-1 text-xs text-slate-500">Open a domain like Python, AWS, or SAP S/4HANA, then review and decide those profiles only.</p>
          </div>
          <span className="rounded-lg bg-slate-50 px-3 py-2 text-xs font-bold text-slate-600">{groupedDomains.length} domain(s)</span>
        </div>
        {groupedDomains.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {groupedDomains.map(([domain, items]) => {
              const reviewed = items.filter(item => item.status === 'reviewed').length
              const contacted = items.filter(item => item.status === 'contacted').length
              const added = items.filter(item => item.status === 'converted').length
              const fresh = items.filter(item => item.status === 'new').length
              return (
                <button
                  key={domain}
                  onClick={() => setDomainFilter(domain)}
                  className={clsx(
                    'rounded-lg border p-4 text-left transition hover:border-blue-200 hover:bg-blue-50',
                    domainFilter === domain ? 'border-blue-300 bg-blue-50 ring-1 ring-blue-100' : 'border-slate-200 bg-white'
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-bold text-slate-900">{domain}</p>
                      <p className="mt-1 text-xs font-semibold text-slate-500">{items.length} profile/result(s)</p>
                    </div>
                    <span className="rounded-lg bg-white px-2 py-1 text-xs font-bold text-blue-700">{items.length}</span>
                  </div>
                  <div className="mt-3 grid grid-cols-4 gap-2 text-center text-[11px] font-bold">
                    <div className="rounded-md bg-amber-50 px-2 py-1 text-amber-700">New {fresh}</div>
                    <div className="rounded-md bg-violet-50 px-2 py-1 text-violet-700">Rev {reviewed}</div>
                    <div className="rounded-md bg-blue-50 px-2 py-1 text-blue-700">Mail {contacted}</div>
                    <div className="rounded-md bg-emerald-50 px-2 py-1 text-emerald-700">Add {added}</div>
                  </div>
                </button>
              )
            })}
          </div>
        ) : (
          <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">No domains available in this view.</p>
        )}
      </section>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Shortlisted', counts.total, Globe2, 'text-slate-700'],
          ['Reviewed', counts.reviewed, CheckCircle2, 'text-violet-700'],
          ['Contacted', counts.contacted, Send, 'text-blue-700'],
          [isTrainer ? 'Added' : 'Converted', counts.converted, Mail, 'text-emerald-700'],
        ].map(([label, value, Icon, tone]) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-500">{label}</p>
              <Icon className={clsx('h-4 w-4', tone)} />
            </div>
            <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
        {STATUS.map(item => (
          <button key={item} onClick={() => setStatus(item)} className={clsx('rounded-lg px-3 py-2 text-sm font-semibold transition', status === item ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50')}>
            {STATUS_LABELS[item]}
          </button>
        ))}
      </div>

      {isTrainer && <TrustLegend />}

      {loading ? (
        <div className="py-14 text-center text-sm text-slate-400">Loading shortlist...</div>
      ) : leads.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {leads.map(lead => (
            <article key={lead.lead_id} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex min-w-0 gap-3">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-blue-100 bg-blue-50 text-sm font-bold uppercase text-blue-700">
                    {lead.profile_image ? <img src={lead.profile_image} alt="" className="h-full w-full object-cover" /> : initials(isTrainer ? (lead.trainer_name || lead.headline) : (lead.company_name || lead.contact_name || lead.domain))}
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-bold text-slate-900">{isTrainer ? (lead.trainer_name || lead.headline || 'Trainer profile') : (lead.company_name || lead.contact_name || lead.domain || 'Client post')}</h3>
                      <span className={clsx('rounded-lg border px-2 py-0.5 text-xs font-semibold capitalize', statusClass(lead.status))}>{lead.status}</span>
                      {isTrainer && <VerificationBadge tier={lead.verification_tier || 'linkedin_signal'} />}
                      <span className="text-xs text-slate-400">{relativeTime(lead.updated_at || lead.created_at)}</span>
                    </div>
                    <p className="mt-1 text-sm font-semibold text-slate-700">{lead.domain || 'Domain pending'}</p>
                  </div>
                </div>
                <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">{Math.round((lead.confidence || 0) * 100)}%</span>
              </div>
              <p className="mt-3 line-clamp-4 text-sm leading-6 text-slate-600">
                {isTrainer ? (lead.profile_text || lead.headline || lead.notes || 'No public profile text saved.') : (lead.post_text || lead.notes || 'No post text saved.')}
              </p>
              <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
                <summary className="cursor-pointer font-semibold text-slate-700">Full details</summary>
                <div className="mt-2 space-y-2 text-slate-600">
                  <p><strong>Source:</strong> {lead.source || 'Public Search'}</p>
                  <p><strong>Domain:</strong> {lead.domain || 'Not detected'}</p>
                  <p><strong>Email:</strong> {lead.contact_email || 'Not available publicly'}</p>
                  <p><strong>Phone:</strong> {lead.contact_phone || 'Not available publicly'}</p>
                  {lead.public_resume_url && <p><strong>Public Resume:</strong> {lead.public_resume_url}</p>}
                  {lead.public_website_url && <p><strong>Public Website:</strong> {lead.public_website_url}</p>}
                  <p className="whitespace-pre-wrap">{isTrainer ? (lead.profile_text || lead.notes || '') : (lead.post_text || lead.notes || '')}</p>
                </div>
              </details>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                {lead.contact_email && <a className="rounded-lg bg-emerald-50 px-2 py-1 font-semibold text-emerald-700" href={`mailto:${lead.contact_email}`}>{lead.contact_email}</a>}
                {lead.contact_phone && <span className="rounded-lg bg-slate-50 px-2 py-1">{lead.contact_phone}</span>}
                {lead.source_url && <a className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 font-semibold text-blue-700" href={lead.source_url} target="_blank" rel="noreferrer"><ExternalLink className="h-3 w-3" /> {isTrainer ? 'Open Profile' : 'Open Post'}</a>}
                {lead.public_resume_url && <a className="inline-flex items-center gap-1 rounded-lg bg-amber-50 px-2 py-1 font-semibold text-amber-700" href={lead.public_resume_url} target="_blank" rel="noreferrer"><ExternalLink className="h-3 w-3" /> Public Resume</a>}
                {lead.public_website_url && <a className="inline-flex items-center gap-1 rounded-lg bg-violet-50 px-2 py-1 font-semibold text-violet-700" href={lead.public_website_url} target="_blank" rel="noreferrer"><ExternalLink className="h-3 w-3" /> Public Website</a>}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button onClick={() => sendLead(lead)} disabled={lead.status === 'contacted'} className="btn-primary text-sm disabled:opacity-50"><Send className="h-4 w-4" /> {lead.contact_email ? 'Send Mail' : 'Enter Email & Send'}</button>
                {isTrainer && lead.source_url && <a href={lead.source_url} target="_blank" rel="noreferrer" className="btn-primary text-sm"><ExternalLink className="h-4 w-4" /> Open Profile</a>}
                <button onClick={() => patchLead(lead, { status: 'converted' })} className="btn-secondary text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4" /> {isTrainer ? 'Mark Added' : 'Converted'}</button>
                <button onClick={() => patchLead(lead, { status: 'reviewed' })} className="btn-secondary text-sm"><CheckCircle2 className="h-4 w-4" /> Reviewed</button>
                <button onClick={() => patchLead(lead, { status: 'rejected' })} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" /> Reject</button>
                <button onClick={() => removeLead(lead)} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" /> Delete</button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white py-16 text-center text-slate-400">
          <CheckCircle2 className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p>No {isTrainer ? 'trainer profiles' : 'client posts'} in this domain/status view.</p>
        </div>
      )}
    </div>
  )
}
