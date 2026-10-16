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

export function outcomeLine(outcome = {}) {
  const matched = Number(outcome.matched) || 0
  const target = Number(outcome.target)
  if (!(target > 0)) {
    const noun = matched === 1 ? 'post' : 'posts'
    return `${outcome.domain}: ${matched} ${noun} matched.`
  }
  const gap = outcome.target_met
    ? ''
    : matched > 0
      ? ' Partial results; the target is not guaranteed.'
      : ' Target not reached.'
  return `${outcome.domain}: ${matched} found (target: ${target}).${gap}`
}

export function collectionOutcomeLines(outcomes) {
  const rows = Array.isArray(outcomes) ? outcomes : []
  const targeted = rows.filter(item => Number(item?.target) > 0)
  const counted = rows.filter(item => !(Number(item?.target) > 0))
  if (counted.length > 6) {
    const hits = counted.filter(item => Number(item.matched) > 0)
    const misses = counted.length - hits.length
    return [
      ...targeted.map(outcomeLine),
      ...hits.map(outcomeLine),
      misses ? `${misses} domain${misses === 1 ? '' : 's'} had no matching posts.` : '',
    ].filter(Boolean)
  }
  return rows.map(outcomeLine)
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
