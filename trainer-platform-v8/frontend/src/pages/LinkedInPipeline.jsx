import { useEffect, useMemo, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  CheckCircle2, ExternalLink, Globe2, Mail, Phone, RefreshCw,
  Search, Send, ShieldCheck, Sparkles, Users, Clock, Star, ChevronRight, ChevronLeft, Trash2,
} from 'lucide-react'
import api from '../utils/api'
import { VerificationBadge } from '../components/VerificationBadge'

const STATUSES = ['all', 'found', 'reviewed', 'outreach_sent', 'matched', 'converted', 'rejected']
const BACKEND_STATUSES = new Set(['all', 'found', 'reviewed', 'outreach_sent', 'matched', 'converted', 'rejected'])
const PIPELINE_MAIL_OPTIONS = [
  { value: 'mail1', label: 'Mail 1 - First Contact' },
  { value: 'mail2', label: 'Mail 2 - Details Request' },
  { value: 'mail2_followup', label: 'Mail 2 Follow-up' },
  { value: 'trainer_acknowledgment', label: 'Trainer Acknowledgment' },
  { value: 'trainer_commercials_to_client', label: 'Send Commercials to Client' },
  { value: 'client_budget_reply', label: 'Client Budget Reply' },
  { value: 'client_budget_acknowledgment', label: 'Client Budget Acknowledgment' },
  { value: 'rate_gap_resolution', label: 'Rate Gap Resolution' },
  { value: 'client_rate_gap_option1', label: 'Client Chose Option 1 (Proceed)' },
  { value: 'client_rate_gap_option2', label: 'Client Chose Option 2 (Alternative)' },
  { value: 'client_toc_details_request', label: 'Client TOC Details Request' },
  { value: 'trainer_rate_discussion', label: 'Trainer Rate Discussion' },
  { value: 'mail3', label: 'Mail 3 - Slot Booking' },
  { value: 'mail3_too_many_slots', label: 'Mail 3 - Too Many Slots (Ask for 3)' },
  { value: 'mail3_too_few_slots', label: 'Mail 3 - Too Few Slots (Ask for 3)' },
  { value: 'mail4', label: 'Mail 4 - Interview Schedule' },
  { value: 'mail5_ok', label: 'Mail 5 - Selection' },
  { value: 'mail5_no', label: 'Mail 5 - Rejection' },
  { value: 'mail6_toc', label: 'Mail 6 - ToC Request' },
  { value: 'mail7_confirm', label: 'Mail 7 - Training Confirmation' },
]
const MAIL_STATUS = {
  mail1: 'outreach_sent',
  mail2: 'details_requested',
  mail2_followup: 'details_requested',
  trainer_acknowledgment: 'acknowledged',
  trainer_commercials_to_client: 'commercials_sent',
  client_budget_reply: 'budget_reply_sent',
  client_budget_acknowledgment: 'budget_acknowledged',
  rate_gap_resolution: 'rate_gap_resolution',
  client_rate_gap_option1: 'rate_option1',
  client_rate_gap_option2: 'rate_option2',
  client_toc_details_request: 'toc_details_requested',
  trainer_rate_discussion: 'rate_discussion',
  mail3: 'slot_requested',
  mail3_too_many_slots: 'slot_clarification',
  mail3_too_few_slots: 'slot_clarification',
  mail4: 'interview_scheduled',
  mail5_ok: 'selected',
  mail5_no: 'rejected',
  mail6_toc: 'toc_requested',
  mail7_confirm: 'training_confirmed',
}

function reqDomain(req) {
  return clean(req?.technology_needed || req?.domain || req?.title || req?.job_title, 'Requirement')
}

function reqClient(req) {
  return clean(req?.client_name || req?.client_company || req?.contact_name, 'Client')
}

function reqDates(req) {
  const start = clean(req?.timeline_start || req?.start_date || req?.training_start_date)
  const end = clean(req?.timeline_end || req?.end_date || req?.training_end_date)
  if (start && end) return `${start} - ${end}`
  return start || end || clean(req?.training_dates || req?.timeline || req?.duration)
}

function clean(value, fallback = '') {
  return String(value || '').trim() || fallback
}

function leadName(lead) {
  return clean(lead.name || lead.trainer_name || lead.headline, 'LinkedIn Trainer')
}

function leadEmail(lead) {
  return clean(lead.email || lead.contact_email)
}

function leadPhone(lead) {
  return clean(lead.phone || lead.contact_phone)
}

function leadUrl(lead) {
  return clean(lead.linkedin_url || lead.source_url)
}

function leadText(lead) {
  return clean(lead.profile_text || lead.snippet || lead.headline || lead.notes, 'No public profile summary saved yet.')
}

function hasContact(lead) {
  return Boolean(leadEmail(lead) || leadPhone(lead))
}

function initials(value) {
  const words = clean(value, 'LI').replace(/[^a-zA-Z0-9\s]/g, ' ').split(/\s+/).filter(Boolean)
  return `${words[0]?.[0] || 'L'}${words[1]?.[0] || 'I'}`
}

function statusTone(status) {
  if (status === 'outreach_sent') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (['matched', 'converted', 'selected', 'training_confirmed'].includes(status)) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (['reviewed', 'details_requested', 'toc_requested'].includes(status)) return 'border-violet-200 bg-violet-50 text-violet-700'
  if (['slot_requested', 'interview_scheduled'].includes(status)) return 'border-amber-200 bg-amber-50 text-amber-700'
  if (status === 'rejected') return 'border-red-200 bg-red-50 text-red-700'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

function templateLabel(mailType) {
  return PIPELINE_MAIL_OPTIONS.find(item => item.value === mailType)?.label || 'Mail 1 - First Contact'
}

function buildMail({ lead, mailContext, mailType = 'mail1' }) {
  const domain = clean(mailContext.domain || lead.domain, 'your domain')
  const durationLine = mailContext.duration ? `Duration: ${mailContext.duration}\n` : ''
  const modeLine = mailContext.mode ? `Mode: ${mailContext.mode}\n` : ''
  const participantsLine = mailContext.participants ? `Participants: ${mailContext.participants}\n` : ''
  const noteLine = mailContext.requirement_note ? `\nRequirement note:\n${mailContext.requirement_note}\n` : ''
  const trainer = leadName(lead)
  const commonClose = `\n\nRegards,\nRecruitment Team\nClahan Technologies`
  const requirementBlock =
    `Domain: ${domain}\n` +
    durationLine +
    modeLine +
    participantsLine +
    noteLine
  const templates = {
    mail1: {
      subject: `Training Opportunity - ${domain}`,
      body:
        `Dear ${trainer},\n\n` +
        `We found your LinkedIn trainer profile while searching for ${domain} expertise.\n\n` +
        `We have a training requirement that may match your profile:\n${requirementBlock}\n` +
        `Please confirm your interest, availability, commercials, and a brief trainer profile/TOC if relevant.` +
        commonClose,
    },
    mail2: {
      subject: `Training Requirement - ${domain} | Additional Details Required`,
      body:
        `Dear ${trainer},\n\n` +
        `Thank you for your response. Kindly share your total experience, trainings delivered, certifications, preferred mode, availability, location, and commercials for the ${domain} requirement.` +
        commonClose,
    },
    mail2_followup: {
      subject: `Re: Training Requirement - ${domain} | Details Required`,
      body: `Dear ${trainer},\n\nFollowing up for the requested trainer details, availability, and commercials for the ${domain} requirement. Please share them when convenient.${commonClose}`,
    },
    trainer_acknowledgment: {
      subject: `Acknowledgement - ${domain} Training Requirement`,
      body: `Dear ${trainer},\n\nThank you for confirming your interest in the ${domain} training requirement. We have noted your response and will review the next details with the client.${commonClose}`,
    },
    trainer_commercials_to_client: {
      subject: `Trainer Commercials - ${domain}`,
      body: `Dear Client,\n\nPlease find the trainer commercial details for the ${domain} requirement. Trainer: ${trainer}. We will proceed further based on your confirmation.${commonClose}`,
    },
    client_budget_reply: {
      subject: `Client Budget Update - ${domain}`,
      body: `Dear ${trainer},\n\nThe client has shared a budget update for the ${domain} requirement. Please review and confirm whether you can proceed within the revised commercials.${commonClose}`,
    },
    client_budget_acknowledgment: {
      subject: `Budget Acknowledgement - ${domain}`,
      body: `Dear Client,\n\nThank you for sharing the budget confirmation for the ${domain} requirement. We will coordinate with the trainer and update you on the next step.${commonClose}`,
    },
    rate_gap_resolution: {
      subject: `Commercial Discussion - ${domain}`,
      body: `Dear ${trainer},\n\nThere is a gap between the trainer commercials and client budget for the ${domain} requirement. Please let us know your best possible revised rate so we can close this smoothly.${commonClose}`,
    },
    client_rate_gap_option1: {
      subject: `Proceeding With Commercial Option - ${domain}`,
      body: `Dear ${trainer},\n\nThe client has chosen to proceed with the discussed commercial option for the ${domain} requirement. We will coordinate the next steps shortly.${commonClose}`,
    },
    client_rate_gap_option2: {
      subject: `Alternative Commercial Option - ${domain}`,
      body: `Dear ${trainer},\n\nThe client has requested an alternative commercial option for the ${domain} requirement. Please share your best feasible option.${commonClose}`,
    },
    client_toc_details_request: {
      subject: `TOC Details Required - ${domain}`,
      body: `Dear ${trainer},\n\nThe client has requested TOC/course details for the ${domain} training. Please share a day-wise agenda, tools, prerequisites, and expected outcomes.${commonClose}`,
    },
    trainer_rate_discussion: {
      subject: `Trainer Rate Discussion - ${domain}`,
      body: `Dear ${trainer},\n\nWe would like to discuss your commercials for the ${domain} requirement and align them with the client expectation. Please share your best possible rate.${commonClose}`,
    },
    mail3: {
      subject: `Interview Slot Booking - ${domain}`,
      body: `Dear ${trainer},\n\nPlease share three suitable interview/discussion slots for the client interaction regarding the ${domain} requirement.${commonClose}`,
    },
    mail3_too_many_slots: {
      subject: `Interview Slots - Please Share Best 3 Options`,
      body: `Dear ${trainer},\n\nThank you for sharing your availability. To keep coordination simple, please share your best 3 interview slot options.${commonClose}`,
    },
    mail3_too_few_slots: {
      subject: `Interview Slots - Please Share 3 Options`,
      body: `Dear ${trainer},\n\nCould you please share 3 suitable interview slot options for the client discussion?${commonClose}`,
    },
    mail4: {
      subject: `Interview Schedule Confirmation - ${domain}`,
      body: `Dear ${trainer},\n\nYour interview/discussion for the ${domain} requirement is being scheduled. We will share the confirmed date, time, and meeting link shortly.${commonClose}`,
    },
    mail5_ok: {
      subject: `Congratulations! You Have Been Selected - ${domain}`,
      body: `Dear ${trainer},\n\nCongratulations, your profile has been selected for the ${domain} training requirement. Please share the final TOC/course agenda and prerequisites.${commonClose}`,
    },
    mail5_no: {
      subject: `Update on Training Requirement - ${domain}`,
      body: `Dear ${trainer},\n\nThank you for your time and response. For this ${domain} requirement, the client has moved ahead with another profile. We will keep your profile for future suitable requirements.${commonClose}`,
    },
    mail6_toc: {
      subject: `Action Required: TOC / Course Agenda - ${domain}`,
      body: `Dear ${trainer},\n\nPlease share the detailed TOC/course agenda for the ${domain} training, including day-wise topics, tools, prerequisites, labs, and outcomes.${commonClose}`,
    },
    mail7_confirm: {
      subject: `Training Schedule Confirmed - ${domain}`,
      body: `Dear ${trainer},\n\nThe ${domain} training is confirmed. We will share the final schedule, platform/venue, and coordination details for smooth delivery.${commonClose}`,
    },
  }
  return templates[mailType] || templates.mail1
}

function pipelineStep(status) {
  if (['training_confirmed'].includes(status)) return 7
  if (['toc_requested'].includes(status)) return 6
  if (['selected', 'rejected'].includes(status)) return 5
  if (['interview_scheduled'].includes(status)) return 4
  if (['slot_requested', 'slot_clarification'].includes(status)) return 3
  if (['details_requested', 'acknowledged', 'commercials_sent', 'rate_discussion'].includes(status)) return 2
  if (['outreach_sent'].includes(status)) return 1
  return 0
}

function PipelineRail({ status }) {
  const step = pipelineStep(status)
  const labels = ['Mail 1', 'Details', 'Slot', 'Interview', 'Selected', 'ToC', 'Confirmed']
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5">
      {labels.map((label, index) => (
        <div key={label} className="flex items-center gap-1">
          <span className={clsx(
            'flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold',
            index < Math.max(step, 1) ? 'bg-blue-500 text-white shadow-sm shadow-blue-200' : 'bg-slate-200 text-slate-500',
          )}>
            {index + 1}
          </span>
          <span className={clsx('text-xs font-medium', index < Math.max(step, 1) ? 'text-blue-600' : 'text-slate-400')}>{label}</span>
        </div>
      ))}
    </div>
  )
}

function stageLabel(status) {
  const labels = {
    found: 'Mail 1 is next',
    reviewed: 'Mail 1 is next',
    outreach_sent: 'Waiting for Reply',
    details_requested: 'Details Requested',
    acknowledged: 'Details Review',
    slot_requested: 'Slot Requested',
    interview_scheduled: 'Interview Scheduled',
    selected: 'Selected',
    toc_requested: 'ToC Requested',
    training_confirmed: 'Training Confirmed',
    converted: 'Converted',
    rejected: 'Rejected',
  }
  return labels[status] || status.replaceAll('_', ' ')
}

function leadSkills(lead) {
  const raw = [
    lead.domain,
    lead.skills,
    lead.technologies,
    lead.headline,
  ].flatMap(item => Array.isArray(item) ? item : String(item || '').split(/[,|]/))
  const seen = new Set()
  return raw
    .map(item => String(item || '').trim())
    .filter(item => {
      const key = item.toLowerCase()
      if (!item || seen.has(key) || item.length > 34) return false
      seen.add(key)
      return true
    })
    .slice(0, 6)
}

export default function LinkedInPipeline() {
  const urlDomain = useMemo(() => clean(new URLSearchParams(window.location.search).get('domain')), [])
  const urlBooted = useRef(false)
  const [requirements, setRequirements] = useState([])
  const [selectedReq, setSelectedReq] = useState(null)
  const [newReqDomain, setNewReqDomain] = useState(urlDomain || 'Python trainer')
  const [domain, setDomain] = useState(urlDomain)
  const [query, setQuery] = useState(urlDomain)
  const [status, setStatus] = useState('all')
  const [onlyContactable, setOnlyContactable] = useState(true)
  const [leads, setLeads] = useState([])
  const [loading, setLoading] = useState(false)
  const [working, setWorking] = useState(false)
  const [sendingLeadId, setSendingLeadId] = useState('')
  const [mailContext, setMailContext] = useState({
    domain: '',
    duration: '',
    mode: 'Online',
    participants: '',
    requirement_note: '',
  })
  const [selectedTemplates, setSelectedTemplates] = useState({})

  const loadRequirements = async () => {
    try {
      const res = await api.get('/requirements', { params: { page_size: 100 } })
      setRequirements(res.data.requirements || res.data.items || [])
    } catch (e) {
      toast.error(e.message)
    }
  }

  const load = async (override = {}) => {
    const effectiveDomain = clean(override.domain ?? domain)
    const effectiveQuery = clean(override.query ?? query)
    const effectiveRequirementId = clean(override.requirement_id ?? selectedReq?.requirement_id)
    setLoading(true)
    try {
      const params = { status: BACKEND_STATUSES.has(status) ? status : 'all', q: effectiveQuery || effectiveDomain, limit: 500 }
      const res = await api.get('/trainer-profile-leads', {
        params,
      })
      const rows = (res.data.leads || [])
        .filter(lead => clean(lead.source, 'linkedin').toLowerCase() === 'linkedin' || leadUrl(lead).includes('linkedin.com/in'))
        .filter(lead => {
          if (!effectiveRequirementId) return true
          const leadRequirementId = clean(lead.requirement_id)
          return !leadRequirementId || leadRequirementId === effectiveRequirementId
        })
        .filter(lead => !effectiveDomain || clean(lead.domain).toLowerCase().includes(effectiveDomain.toLowerCase()) || leadText(lead).toLowerCase().includes(effectiveDomain.toLowerCase()))
        .filter(lead => !onlyContactable || hasContact(lead))
        .filter(lead => status === 'all' || clean(lead.status) === status)
      setLeads(rows)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadRequirements() }, [])
  useEffect(() => { load() }, [status, onlyContactable])

  useEffect(() => {
    if (!urlDomain || urlBooted.current || selectedReq) return
    urlBooted.current = true
    const req = {
      requirement_id: `LINKEDIN-${urlDomain.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').toUpperCase() || 'SEARCH'}`,
      technology_needed: urlDomain,
      domain: urlDomain,
      title: `${urlDomain} LinkedIn Pipeline`,
      top_n: 50,
      source: 'linkedin_search',
      metadata: { source: 'linkedin_search', virtual_requirement: true },
    }
    setSelectedReq(req)
    setMailContext(prev => ({ ...prev, domain: urlDomain, requirement_note: `LinkedIn trainer search batch for ${urlDomain}` }))
    load({ domain: urlDomain, query: urlDomain, requirement_id: '' })
  }, [urlDomain, selectedReq])

  const createLinkedInRequirement = async () => {
    const technology = clean(newReqDomain)
    if (!technology) {
      toast.error('Enter what you searched on LinkedIn, like Python trainer')
      return
    }
    setWorking(true)
    try {
      const res = await api.post('/requirements', {
        technology_needed: technology,
        title: `${technology} LinkedIn Pipeline`,
        domain: technology,
        top_n: 20,
        source: 'linkedin_pipeline',
        metadata: { source: 'linkedin_pipeline', search_query: technology },
      })
      const req = res.data.requirement || { requirement_id: res.data.requirement_id, technology_needed: technology, domain: technology, top_n: 20 }
      setRequirements(prev => [req, ...prev.filter(item => item.requirement_id !== req.requirement_id)])
      setSelectedReq(req)
      setDomain(technology)
      setQuery(technology)
      setMailContext(prev => ({ ...prev, domain: technology, requirement_note: `LinkedIn trainer search batch for ${technology}` }))
      setLeads([])
      toast.success(`Created LinkedIn requirement ${req.requirement_id}`)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setWorking(false)
    }
  }

  const openRequirement = async (req) => {
    const nextDomain = reqDomain(req)
    setSelectedReq(req)
    setDomain(nextDomain)
    setQuery(nextDomain)
    setMailContext(prev => ({
      ...prev,
      domain: nextDomain,
      duration: reqDates(req) || prev.duration,
      participants: clean(req.participant_count || req.participants || req.number_of_participants, prev.participants),
      mode: clean(req.mode || req.delivery_mode || req.location_mode, prev.mode || 'Online'),
      requirement_note: clean(req.requirement_note || req.description || req.notes, prev.requirement_note),
    }))
    await load({ domain: nextDomain, query: nextDomain })
  }

  const searchLinkedIn = async () => {
    const searchDomain = clean(domain || mailContext.domain || query)
    if (!searchDomain) {
      toast.error('Enter a domain or search query')
      return
    }
    setWorking(true)
    try {
      const res = await api.post('/trainer-profile-leads/search-public', {
        domain: searchDomain,
        query: query || searchDomain,
        requirement_id: selectedReq?.requirement_id || '',
        source: 'linkedin',
        max_results: 50,
      })
      toast.success(`LinkedIn search saved ${res.data.saved_count || res.data.new_stored || 0} new trainer profile(s)`)
      await load({ requirement_id: selectedReq?.requirement_id || '', domain: searchDomain, query: query || searchDomain })
    } catch (e) {
      toast.error(e.message)
    } finally {
      setWorking(false)
    }
  }

  const enrichVisible = async () => {
    const leadIds = leads.filter(lead => !leadEmail(lead)).map(lead => lead.lead_id).slice(0, 20)
    if (!leadIds.length) {
      toast.success('Visible trainers already have emails, or no trainers are visible')
      return
    }
    setWorking(true)
    try {
      const res = await api.post('/trainer-profile-leads/enrich-public-emails', { lead_ids: leadIds })
      toast.success(`Contact enrichment checked ${res.data.checked || 0}, enriched ${res.data.enriched || 0}`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setWorking(false)
    }
  }

  const sendLead = async (lead, mailType = selectedTemplates[lead.lead_id] || 'mail1') => {
    if (!leadEmail(lead)) {
      toast.error('No email found for this LinkedIn trainer. Run Automation 1: Find Contacts, or add an email before sending.')
      return
    }
    setSendingLeadId(lead.lead_id)
    try {
      const mail = buildMail({ lead, mailContext, mailType })
      await api.post(`/trainer-profile-leads/${lead.lead_id}/send-email`, { lead_ids: [lead.lead_id], ...mail })
      await api.patch(`/trainer-profile-leads/${lead.lead_id}`, { status: MAIL_STATUS[mailType] || 'outreach_sent' })
      toast.success(`${templateLabel(mailType)} sent`)
      await load()
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'LinkedIn manual mail failed')
    } finally {
      setSendingLeadId('')
    }
  }

  const sendVisible = async () => {
    const targets = leads.filter(lead => leadEmail(lead) && !['outreach_sent', 'rejected'].includes(clean(lead.status)))
    if (!targets.length) {
      toast.error('No visible LinkedIn trainers with email are ready for outreach')
      return
    }
    if (!window.confirm(`Send LinkedIn Mail1 outreach to ${targets.length} visible trainer(s)?`)) return
    setWorking(true)
    try {
      let sent = 0
      for (const lead of targets.slice(0, 50)) {
        const mail = buildMail({ lead, mailContext, mailType: 'mail1' })
        await api.post(`/trainer-profile-leads/${lead.lead_id}/send-email`, { lead_ids: [lead.lead_id], ...mail })
        await api.patch(`/trainer-profile-leads/${lead.lead_id}`, { status: 'outreach_sent' })
        sent += 1
      }
      toast.success(`LinkedIn pipeline outreach sent to ${sent} trainer(s)`)
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setWorking(false)
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

  const stats = useMemo(() => ({
    visible: leads.length,
    emails: leads.filter(lead => leadEmail(lead)).length,
    phones: leads.filter(lead => leadPhone(lead)).length,
    skipped: leads.filter(lead => !leadEmail(lead)).length,
    contacted: leads.filter(lead => pipelineStep(clean(lead.status)) >= 1).length,
  }), [leads])

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Globe2 className="h-6 w-6 text-blue-600" /> LinkedIn Pipeline
          </h1>
          <p className="mt-1 text-sm text-slate-500">Create a requirement from a LinkedIn trainer search, load up to 50 trainers, enrich contacts, then mail only email-ready trainers.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={searchLinkedIn} disabled={working} className="btn-secondary text-sm disabled:opacity-50"><Search className="h-4 w-4" /> Fetch LinkedIn Trainers</button>
          <button onClick={enrichVisible} disabled={working} className="btn-secondary text-sm disabled:opacity-50"><Sparkles className="h-4 w-4" /> Automation 1: Find Contacts</button>
          <button onClick={sendVisible} disabled={working} className="btn-primary text-sm disabled:opacity-50"><Send className="h-4 w-4" /> Automation 2: Start Outreach</button>
        </div>
      </div>

      {!selectedReq ? (
        <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-4 grid gap-3 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <h2 className="text-sm font-bold text-slate-900">Create LinkedIn Requirement</h2>
              <p className="mt-1 text-xs text-slate-500">Use the same phrase you searched in LinkedIn, for example Python trainer. This creates a separate pipeline batch.</p>
              <input
                className="input mt-2"
                value={newReqDomain}
                onChange={e => setNewReqDomain(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createLinkedInRequirement()}
                placeholder="Python trainer"
              />
            </div>
            <button onClick={createLinkedInRequirement} disabled={working} className="btn-primary text-sm disabled:opacity-50">
              <Sparkles className="h-4 w-4" /> Create Pipeline
            </button>
          </div>

          <div className="mb-3 flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
            <h2 className="text-sm font-bold text-slate-900">Or Select Existing Requirement</h2>
            <button onClick={loadRequirements} className="btn-secondary text-sm"><RefreshCw className="h-4 w-4" /> Refresh</button>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {requirements.map(req => (
              <button
                key={req.requirement_id}
                onClick={() => openRequirement(req)}
                className="grid grid-cols-[34px_1fr_auto_auto] items-center gap-3 rounded-lg border border-slate-200 bg-white p-4 text-left transition hover:border-blue-200 hover:bg-slate-50"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600"><Star className="h-4 w-4" /></span>
                <span className="min-w-0">
                  <span className="block truncate font-bold text-slate-950">{reqDomain(req)}</span>
                  <span className="mt-1 block truncate text-xs font-semibold text-emerald-600">Client email {req.client_email ? 'saved' : 'pending'}</span>
                  <span className="block truncate text-xs text-slate-600">{reqClient(req)}</span>
                  <span className="block truncate text-xs font-semibold text-amber-600">{reqDates(req) || 'Dates pending'}</span>
                  <span className="block truncate text-xs text-slate-400">{clean(req.requirement_id, 'REQ')} · Top {clean(req.top_n, '10')}</span>
                </span>
                <ChevronRight className="h-4 w-4 text-slate-400" />
                <Trash2 className="h-4 w-4 text-slate-300" />
              </button>
            ))}
          </div>
        </section>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-slate-900">
                LinkedIn requirement: <span className="text-blue-600">{reqDomain(selectedReq)}</span>
              </h2>
              <div className={clsx('mt-1 inline-flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs font-semibold',
                selectedReq.client_email ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'
              )}>
                <Mail className="h-3.5 w-3.5" />
                <span>{selectedReq.client_email ? `Client: ${selectedReq.client_email}` : 'Client email missing'}</span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{selectedReq.requirement_id} · Top {clean(selectedReq.top_n, '10')}</p>
            </div>
            <div className="flex gap-2">
              <button onClick={() => { setSelectedReq(null); setLeads([]) }} className="btn-secondary text-sm"><ChevronLeft className="h-4 w-4" /> Back</button>
              <button onClick={() => load()} disabled={loading} className="btn-secondary text-sm disabled:opacity-50"><RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} /> Refresh</button>
            </div>
          </div>

          <div className="grid gap-2 rounded-lg border border-slate-200 bg-white p-3 text-xs sm:grid-cols-3">
            <div className="rounded-lg bg-blue-50 px-3 py-2 text-blue-700">
              <p className="font-bold">Step 1: LinkedIn search</p>
              <p className="mt-0.5 text-blue-600">Fetch up to 50 trainers for this requirement</p>
            </div>
            <div className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-700">
              <p className="font-bold">Step 2: Contact filter</p>
              <p className="mt-0.5 text-emerald-600">Only real emails are sent through Gmail</p>
            </div>
            <div className="rounded-lg bg-blue-50 px-3 py-2 text-blue-700">
              <p className="font-bold">{leads.length} LinkedIn trainer(s)</p>
              <p className="mt-0.5 text-blue-600">{stats.emails} email-ready, {stats.skipped} need contact enrichment</p>
            </div>
          </div>
        </div>
      )}

      {selectedReq && <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 lg:grid-cols-4">
          <div>
            <label className="mb-1 block text-xs font-bold uppercase text-slate-500">Domain</label>
            <input className="input" value={domain} onChange={e => setDomain(e.target.value)} placeholder="DevOps, Python, SAP" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold uppercase text-slate-500">Search Query</label>
            <input className="input" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && load()} placeholder="Corporate trainer LinkedIn" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold uppercase text-slate-500">Status</label>
            <select className="input" value={status} onChange={e => setStatus(e.target.value)}>
              {STATUSES.map(item => <option key={item} value={item}>{item.replaceAll('_', ' ')}</option>)}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <button onClick={load} disabled={loading} className="btn-secondary w-full text-sm disabled:opacity-50"><RefreshCw className="h-4 w-4" /> Refresh</button>
          </div>
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-4">
          <input className="input" value={mailContext.domain} onChange={e => setMailContext(prev => ({ ...prev, domain: e.target.value }))} placeholder="Mail domain override" />
          <input className="input" value={mailContext.duration} onChange={e => setMailContext(prev => ({ ...prev, duration: e.target.value }))} placeholder="Duration" />
          <input className="input" value={mailContext.participants} onChange={e => setMailContext(prev => ({ ...prev, participants: e.target.value }))} placeholder="Participants" />
          <select className="input" value={mailContext.mode} onChange={e => setMailContext(prev => ({ ...prev, mode: e.target.value }))}>
            <option>Online</option>
            <option>Offline</option>
            <option>Hybrid</option>
          </select>
          <input className="input lg:col-span-4" value={mailContext.requirement_note} onChange={e => setMailContext(prev => ({ ...prev, requirement_note: e.target.value }))} placeholder="Requirement note for LinkedIn trainer outreach" />
        </div>

        <label className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-slate-600">
          <input type="checkbox" checked={onlyContactable} onChange={e => setOnlyContactable(e.target.checked)} className="h-4 w-4 rounded border-slate-300" />
          Show only LinkedIn trainers with email or phone
        </label>
      </section>}

      {selectedReq && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Visible LinkedIn Trainers', stats.visible, Users],
          ['Email Ready to Send', stats.emails, Mail],
          ['With Phone', stats.phones, Phone],
          ['Skipped Until Email Found', stats.skipped, ShieldCheck],
        ].map(([label, value, Icon]) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-500">{label}</p>
              <Icon className="h-4 w-4 text-blue-600" />
            </div>
            <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
          </div>
        ))}
      </div>}

      {selectedReq && (loading ? (
        <div className="py-16 text-center text-sm text-slate-400">Loading LinkedIn pipeline...</div>
      ) : leads.length ? (
        <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="hidden">
            <div>
              <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Requirement Pipeline</p>
              <h2 className="text-sm font-bold text-slate-900">{selectedReq ? reqDomain(selectedReq) : (domain || mailContext.domain || query || 'All LinkedIn trainer domains')}</h2>
              {selectedReq && <p className="mt-0.5 text-xs font-semibold text-slate-500">{selectedReq.requirement_id} · {reqClient(selectedReq)} · {reqDates(selectedReq) || 'Dates pending'}</p>}
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-lg border border-green-200 bg-green-50 px-3 py-1 text-xs font-bold text-green-700">Gmail Ready</span>
              <span className="rounded-lg bg-white px-3 py-1 text-xs font-bold text-slate-600">{leads.length} LinkedIn trainer(s)</span>
            </div>
          </div>

          <div className="divide-y divide-slate-100">
            {leads.map((lead, index) => {
              const leadStatus = clean(lead.status, 'found')
              const step = pipelineStep(leadStatus)
              const percent = Math.max(0, Math.round((step / 7) * 100))
              const nextLabel = step === 0 ? 'Mail 1 is next' : `${templateLabel(selectedTemplates[lead.lead_id] || 'mail2')} is next`
              const skills = leadSkills(lead)
              return (
                <article key={lead.lead_id} className="px-4 py-4">
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-sm font-bold text-amber-700">{index + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="max-w-full truncate text-base font-bold text-slate-950">{leadName(lead)}</h3>
                        <span className={clsx('rounded-lg border px-2 py-0.5 text-xs font-bold capitalize', statusTone(leadStatus))}>
                          Trainer Status: {stageLabel(leadStatus)}
                        </span>
                        <VerificationBadge tier={lead.verification_tier || 'linkedin_signal'} />
                      </div>
                      <p className="mt-0.5 truncate text-xs font-semibold text-slate-500">{clean(lead.domain, 'Domain pending')}</p>

                      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs font-semibold text-slate-500">
                        {leadEmail(lead) && <a href={`mailto:${leadEmail(lead)}`} className="inline-flex items-center gap-1 text-slate-600"><Mail className="h-3 w-3" /> {leadEmail(lead)}</a>}
                        {leadPhone(lead) && <span className="inline-flex items-center gap-1"><Phone className="h-3 w-3" /> {leadPhone(lead)}</span>}
                        {leadUrl(lead) && <a href={leadUrl(lead)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-600"><ExternalLink className="h-3 w-3" /> LinkedIn</a>}
                      </div>

                      {skills.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {skills.slice(0, 5).map(skill => (
                            <span key={skill} className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-xs text-blue-700">{skill}</span>
                          ))}
                          {skills.length > 5 && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">+{skills.length - 5}</span>}
                        </div>
                      )}

                      <PipelineRail status={leadStatus} />

                      <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Pipeline Progress</p>
                            <p className="text-sm font-bold text-slate-950">{nextLabel}</p>
                          </div>
                          <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-bold text-slate-600">{percent}%</span>
                        </div>
                        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200">
                          <div className="h-full rounded-full bg-blue-500" style={{ width: `${percent}%` }} />
                        </div>
                        <div className="mt-3 grid gap-2 md:grid-cols-4">
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <p className="text-[11px] font-bold uppercase text-slate-400">Trainer Mails</p>
                            <p className="text-xs font-bold text-slate-700">{step}/7 complete</p>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <p className="text-[11px] font-bold uppercase text-slate-400">Contact</p>
                            <p className="text-xs font-bold text-slate-700">{leadEmail(lead) ? 'Email saved' : leadPhone(lead) ? 'Phone only' : 'Needs enrichment'}</p>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <p className="text-[11px] font-bold uppercase text-slate-400">Commercial</p>
                            <p className="text-xs font-bold text-slate-700">Not started</p>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <p className="text-[11px] font-bold uppercase text-slate-400">Current Stage</p>
                            <p className="text-xs font-bold text-slate-700">{stageLabel(leadStatus)}</p>
                          </div>
                        </div>
                      </div>

                      <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-semibold text-sky-700">
                        {leadStatus === 'outreach_sent' ? 'Mail 1 sent - waiting for trainer reply' : `${nextLabel} for this LinkedIn trainer`}
                      </div>
                      <div className="mt-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs font-semibold text-orange-600">
                        Auto reminders: 6h - 12h - 24h
                      </div>
                      <div className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-700">
                        Negotiate Rate
                      </div>

                      <div className="mt-4 rounded-xl border border-blue-100 bg-blue-50 p-3">
                        <div className="grid gap-3 lg:grid-cols-[1fr_260px_auto_auto_auto] lg:items-center">
                          <div>
                            <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Manual Mail Templates</p>
                            <p className="text-xs text-blue-600">Use only when you need to override the automation.</p>
                          </div>
                          <select
                            className="input bg-white"
                            value={selectedTemplates[lead.lead_id] || 'mail1'}
                            onChange={e => setSelectedTemplates(prev => ({ ...prev, [lead.lead_id]: e.target.value }))}
                          >
                            {PIPELINE_MAIL_OPTIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
                          </select>
                          <button
                            onClick={() => sendLead(lead)}
                            disabled={!!sendingLeadId}
                            title={leadEmail(lead) ? `Send ${templateLabel(selectedTemplates[lead.lead_id] || 'mail1')}` : 'Email is required before sending'}
                            className={clsx('btn-primary justify-center text-sm disabled:opacity-50', !leadEmail(lead) && 'opacity-70')}
                          >
                            {sendingLeadId === lead.lead_id ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                            {sendingLeadId === lead.lead_id ? 'Sending...' : 'Send'}
                          </button>
                          <button onClick={() => patchLead(lead, { status: 'reviewed' })} className="btn-secondary justify-center text-sm"><CheckCircle2 className="h-4 w-4" /> Reviewed</button>
                          <button onClick={() => patchLead(lead, { status: 'converted' })} className="btn-secondary justify-center text-sm text-emerald-700"><ShieldCheck className="h-4 w-4" /> Converted</button>
                        </div>
                      </div>
                    </div>
                    {leadUrl(lead) && (
                      <a href={leadUrl(lead)} target="_blank" rel="noreferrer" className="shrink-0 rounded-xl bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-200">
                        Thread
                      </a>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white py-16 text-center text-slate-400">
          <Globe2 className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p>No LinkedIn trainers with the selected filters.</p>
        </div>
      ))}
    </div>
  )
}
