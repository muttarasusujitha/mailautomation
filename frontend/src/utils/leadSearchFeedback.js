function warningText(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.trim()
  return String(value.error || value.message || '').trim()
}

export function leadSearchWarnings(data) {
  const messages = []
  const push = (value) => {
    const text = warningText(value)
    if (text && !messages.includes(text)) messages.push(text)
  }
  if (!data) return messages
  push(data.search_error)
  for (const item of data.search_errors || []) push(item)
  for (const outcome of data.domain_outcomes || []) {
    push(outcome?.primary_error)
    for (const warning of outcome?.warnings || []) push(warning)
  }
  return messages
}

export const AUTOMATIC_LINKEDIN_DOMAINS = ['Python', 'AWS']

export function linkedInSearchDomains(domainText) {
  const entered = String(domainText || '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean)
    .slice(0, 4)
  return entered.length ? entered : AUTOMATIC_LINKEDIN_DOMAINS
}

export function linkedInSearchPayload(mode, domainText) {
  const trainerSearch = mode === 'trainer'
  return {
    search_provider: 'auto',
    source: 'linkedin',
    mode: trainerSearch ? 'trainer' : 'client',
    domains: linkedInSearchDomains(domainText),
    max_results: trainerSearch ? 60 : 50,
    save: true,
    max_queries: trainerSearch ? 8 : 2,
    max_domains: 4,
    concurrency: 3,
    deep_search: false,
  }
}

export function mergeSearchLeads(saved, results) {
  const merged = []
  const seen = new Set()
  for (const lead of [...(results || []), ...(saved || [])]) {
    const key = lead?.lead_id || lead?.source_url || lead?.linkedin_url
    if (!key || seen.has(key)) continue
    seen.add(key)
    merged.push(lead)
  }
  return merged
}

export function visibleSearchLeads(saved, results, showSearchMatches) {
  const fetched = (results || []).filter(lead => lead?.source_url || lead?.linkedin_url || lead?.lead_id)
  if (showSearchMatches && fetched.length) return mergeSearchLeads([], fetched)
  return saved || []
}

export function matchingSavedLeads(leads, results) {
  const urls = new Set()
  for (const item of results || []) {
    for (const key of ['source_url', 'url', 'linkedin_url']) {
      if (item?.[key]) urls.add(item[key])
    }
  }
  if (!urls.size) return []
  return (leads || []).filter(lead => urls.has(lead?.source_url) || urls.has(lead?.linkedin_url))
}
