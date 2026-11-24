// Paging, server-side filters and counts for the lead list pages.

export const LEAD_PAGE_SIZE = 50
export const NO_DOMAIN = '__none__'

function text(value) {
  return String(value ?? '').trim()
}

// Query parameters for GET /trainer-profile-leads and GET /client-leads. Empty filters are left out.
export function leadListParams({
  page = 1, pageSize = LEAD_PAGE_SIZE, status, statuses, q, kind, topic, domainExact,
  requirementScope, hasContact, includeCounts = true,
} = {}) {
  const params = { page: Math.max(1, Math.floor(Number(page)) || 1), page_size: pageSize }
  if (includeCounts) params.include_counts = true
  if (status && status !== 'all') params.status = status
  if (Array.isArray(statuses) && statuses.length) params.statuses = statuses.join(',')
  if (text(q)) params.q = text(q)
  if (kind) params.kind = kind
  if (text(topic)) params.topic = text(topic)
  if (domainExact && domainExact !== 'all') params.domain_exact = domainExact
  if (text(requirementScope)) params.requirement_scope = text(requirementScope)
  if (hasContact) params.has_contact = true
  return params
}

// The page fields of a list response, with safe defaults.
export function listPage(data = {}) {
  const total = Number(data.total) || 0
  const pageSize = Number(data.page_size) || LEAD_PAGE_SIZE
  return {
    total,
    page: Math.max(1, Number(data.page) || 1),
    pages: Math.max(1, Number(data.pages) || Math.ceil(total / pageSize) || 1),
    pageSize,
    counts: data.counts || null,
  }
}

// After a delete the current page can be past the last one. Returns the page to load instead, or 0.
export function pageToReload(data = {}, requested = 1) {
  const { total, pages } = listPage(data)
  const rows = Array.isArray(data.leads) ? data.leads.length : 0
  return !rows && total > 0 && requested > pages ? pages : 0
}

export function pageSummary({ page = 1, pageSize = LEAD_PAGE_SIZE, total = 0 } = {}) {
  if (!total) return { first: 0, last: 0 }
  const first = (page - 1) * pageSize + 1
  return { first: Math.min(first, total), last: Math.min(total, first + pageSize - 1) }
}

// All saved leads in counts.by_status, whatever status tab is open.
export function statusTotal(counts) {
  return Object.values(counts?.by_status || {}).reduce((sum, value) => sum + (Number(value) || 0), 0)
}

// Leads with these statuses that the open status tab lists: none when the tab is another status.
export function statusCountInView(counts, statusTab, ...statuses) {
  return statuses.reduce((sum, name) => (
    statusTab === 'all' || statusTab === name ? sum + (Number(counts?.by_status?.[name]) || 0) : sum
  ), 0)
}

// Domain chips from counts.by_domain: value is what domain_exact and delete-by-domain take.
export function domainChips(counts) {
  return (counts?.by_domain || []).map(item => ({
    value: item.value || NO_DOMAIN,
    label: text(item.domain) || 'Other',
    count: Number(item.total) || 0,
    byStatus: item.by_status || {},
  }))
}

export function chunk(items, size = 10) {
  const list = Array.isArray(items) ? items : []
  const parts = []
  for (let index = 0; index < list.length; index += size) parts.push(list.slice(index, index + size))
  return parts
}

export function leadEmail(lead) {
  return text(lead?.contact_email || lead?.email)
}

// Shortlist bulk actions act on the leads of the open page.
export function leadsWithoutEmail(leads) {
  return (leads || []).filter(lead => lead?.lead_id && !leadEmail(lead)).map(lead => lead.lead_id)
}

// Trainers not contacted yet, the same statuses the server moves on after Mail 1. Contacted,
// converted ("Added") and rejected trainers are not sent Mail 1 again.
export const OUTREACH_READY_STATUSES = ['', 'new', 'found', 'reviewed', 'outreach_failed']

export function readyForMail1(lead) {
  return OUTREACH_READY_STATUSES.includes(text(lead?.status))
}

export function outreachReadyLeads(leads) {
  return (leads || []).filter(lead => lead?.lead_id && leadEmail(lead) && readyForMail1(lead))
}

// Adds up the responses of several chunked bulk requests.
export function sumResults(results, fields) {
  const total = Object.fromEntries(fields.map(field => [field, 0]))
  let error = ''
  for (const result of results || []) {
    for (const field of fields) total[field] += Number(result?.[field]) || 0
    error = error || text(result?.error)
  }
  return { ...total, error }
}
