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

function canonicalLeadUrl(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  try {
    const url = new URL(text)
    const host = url.hostname.replace(/^www\./, '').toLowerCase()
    return `${host}${url.pathname.replace(/\/$/, '')}`
  } catch {
    return text.toLowerCase()
  }
}

export function matchingSavedLeads(leads, results) {
  const urls = new Set()
  for (const item of results || []) {
    for (const key of ['source_url', 'url', 'linkedin_url']) {
      const canonical = canonicalLeadUrl(item?.[key])
      if (canonical) urls.add(canonical)
    }
  }
  if (!urls.size) return []
  return (leads || []).filter(lead => (
    urls.has(canonicalLeadUrl(lead?.source_url)) || urls.has(canonicalLeadUrl(lead?.linkedin_url))
  ))
}
