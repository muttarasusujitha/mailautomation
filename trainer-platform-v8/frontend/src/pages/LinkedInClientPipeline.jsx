import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  BriefcaseBusiness,
  CheckCircle2,
  ExternalLink,
  Mail,
  RefreshCw,
  Search,
  Send,
  Trash2,
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

function leadDomain(lead) {
  return String(lead?.domain || lead?.company_name || 'Unknown').trim()
}

function leadSearchText(lead) {
  return [
    lead?.domain,
    lead?.company_name,
    lead?.contact_name,
    lead?.post_text,
    lead?.notes,
    lead?.source_url,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function initials(value) {
  const words = String(value || '').replace(/[^a-zA-Z0-9\s]/g, ' ').split(/\s+/).filter(Boolean)
  return (words[0]?.[0] || 'L') + (words[1]?.[0] || '')
}

export default function LinkedInClientPipeline() {
  const [leads, setLeads] = useState([])
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [sendingLeadId, setSendingLeadId] = useState('')

  const loadLeads = async () => {
    setLoading(true)
    try {
      const params = { status: filter === 'all' ? 'all' : filter, q, limit: 200 }
      const res = await api.get('/client-leads', { params })
      setLeads(res.data.leads || [])
    } catch (e) {
      toast.error(e.message || 'Failed to load client leads')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadLeads()
  }, [filter])

  const visibleLeads = useMemo(() => {
    const query = q.trim().toLowerCase()
    return query ? leads.filter(lead => leadSearchText(lead).includes(query)) : leads
  }, [leads, q])

  const sendMail = async (lead) => {
    if (!lead.email && !lead.contact_email) {
      toast.error('No email address available for this lead')
      return
    }
    setSendingLeadId(lead.lead_id)
    try {
      await api.post(`/client-leads/${lead.lead_id}/send-email`)
      toast.success('Mail 1 sent to client lead')
      await loadLeads()
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'Failed to send mail')
    } finally {
      setSendingLeadId('')
    }
  }

  const patchLead = async (lead, payload) => {
    try {
      await api.patch(`/client-leads/${lead.lead_id}`, payload)
      await loadLeads()
    } catch (e) {
      toast.error(e.message || 'Unable to update lead')
    }
  }

  const stats = useMemo(() => ({
    total: leads.length,
    new: leads.filter(item => item.status === 'new').length,
    contacted: leads.filter(item => item.status === 'contacted').length,
    converted: leads.filter(item => item.status === 'converted').length,
  }), [leads])

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Mail className="h-6 w-6 text-blue-600" /> LinkedIn Client Pipeline
          </h1>
          <p className="mt-1 text-sm text-slate-500">Manage LinkedIn client posts, send the first outreach mail, and track contact status.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-[260px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={q}
              onChange={e => setQ(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && loadLeads()}
              placeholder="Search client posts"
              className="input bg-[#eaf6ff] pl-9"
            />
          </div>
          <button onClick={loadLeads} className="btn-secondary text-sm"><RefreshCw className="h-4 w-4" /> Refresh</button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Total posts', stats.total, BriefcaseBusiness, 'text-slate-700'],
          ['New', stats.new, Search, 'text-amber-700'],
          ['Contacted', stats.contacted, Send, 'text-blue-700'],
          ['Converted', stats.converted, CheckCircle2, 'text-emerald-700'],
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

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-bold text-slate-900">Client Pipeline Filters</p>
            <p className="mt-1 text-xs text-slate-500">Use status filters to focus on new posts and send Mail 1 outreach first.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {STATUS.map(item => (
              <button
                key={item}
                onClick={() => setFilter(item)}
                className={clsx('rounded-lg px-3 py-2 text-sm font-semibold transition', filter === item ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-600 hover:bg-slate-100')}
              >
                {STATUS_LABELS[item]}
              </button>
            ))}
          </div>
        </div>
      </div>

      {(() => {
        if (loading) {
          return <div className="rounded-lg border border-slate-200 bg-slate-50 p-12 text-center text-sm text-slate-400">Loading client pipeline...</div>
        }
        if (!visibleLeads.length) {
          return <div className="rounded-lg border border-slate-200 bg-slate-50 p-12 text-center text-sm text-slate-400">No client posts found for this filter.</div>
        }
        return (
          <div className="grid gap-4 xl:grid-cols-2">
            {visibleLeads.map(lead => (
              <article key={lead.lead_id} className="rounded-2xl border border-slate-200 bg-slate-50 p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="truncate text-lg font-bold text-slate-950">{lead.company_name || lead.domain || 'Client post'}</h2>
                      <span className={clsx('rounded-full border px-2 py-1 text-xs font-semibold uppercase', statusClass(lead.status))}>{lead.status || 'new'}</span>
                    </div>
                    <p className="mt-2 text-sm text-slate-600">{lead.contact_name ? `Contact: ${lead.contact_name}` : 'No contact name'}</p>
                    <p className="mt-1 text-sm text-slate-500">{leadDomain(lead)} · {relativeTime(lead.created_at)}</p>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    {lead.source_url && (
                      <a href={lead.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-1 font-semibold text-blue-700">
                        <ExternalLink className="h-3.5 w-3.5" /> Post
                      </a>
                    )}
                  </div>
                </div>

                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-slate-200 bg-white p-3">
                    <p className="text-[11px] uppercase tracking-wide text-slate-400">Email</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{lead.email || lead.contact_email || 'No email'}</p>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-white p-3">
                    <p className="text-[11px] uppercase tracking-wide text-slate-400">Phone</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{lead.phone || lead.contact_phone || 'No phone'}</p>
                  </div>
                </div>

                <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-700">
                  <p className="font-semibold text-slate-900">Post text</p>
                  <p className="mt-2 whitespace-pre-wrap">{lead.post_text || lead.notes || 'No post content available.'}</p>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    onClick={() => sendMail(lead)}
                    disabled={!lead.email && !lead.contact_email || sendingLeadId === lead.lead_id}
                    className="btn-primary text-sm disabled:opacity-50"
                  >
                    {sendingLeadId === lead.lead_id ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Send Mail 1
                  </button>
                  <button onClick={() => patchLead(lead, { status: 'reviewed' })} className="btn-secondary text-sm"><CheckCircle2 className="h-4 w-4" /> Reviewed</button>
                  <button onClick={() => patchLead(lead, { status: 'converted' })} className="btn-secondary text-sm text-emerald-700"><Mail className="h-4 w-4" /> Converted</button>
                  <button onClick={() => patchLead(lead, { status: 'rejected' })} className="btn-secondary text-sm text-red-600"><Trash2 className="h-4 w-4" /> Reject</button>
                </div>
              </article>
            ))}
          </div>
        )
      })()}
    </div>
  )
}
