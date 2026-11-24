// Keep frontend trainer-identity handling aligned with shared/trainer_identity.py.
// Only accept a supplied personal LinkedIn profile URL; never construct one.
export function linkedinProfileUrl(value = '') {
  const matches = String(value || '').match(/https?:\/\/[^\s<>"')]+/gi) || []

  for (const raw of matches) {
    const candidate = raw.replace(/[.,;:]+$/, '')
    try {
      const parsed = new URL(candidate)
      const host = parsed.hostname.toLowerCase()
      if (host !== 'linkedin.com' && !/^(?:www|[a-z]{2,3})\.linkedin\.com$/.test(host)) continue
      if (parsed.username || parsed.password || parsed.port) continue
      if (/^\/(?:in|pub)\/[^/?#]+(?:\/[^?#]*)?$/.test(parsed.pathname)) return candidate
    } catch {
      // Ignore malformed URLs.
    }
  }
  return ''
}

// Details generated/owned by the platform should not be requested from trainers.
export function trainerOwnedDetails(items = []) {
  const platformOwned = new Set(['toc', 'lab'])
  return (Array.isArray(items) ? items : []).filter(item => !platformOwned.has(String(item?.key || '').toLowerCase()))
}
