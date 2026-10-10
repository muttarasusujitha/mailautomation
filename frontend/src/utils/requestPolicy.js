const RETRYABLE_METHODS = new Set(['get', 'head', 'options'])
const RETRYABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504])

export function requestTimeout(config = {}) {
  const explicit = Number(config.timeout)
  if (explicit > 0) return explicit
  const url = String(config.url || '')
  // Profile search reads public results and a signed-in browser session.
  // Keep the five-minute budget so Find Profiles is not aborted mid-search.
  if (url.includes('/linkedin-leads/search')) return 300000
  return 120000
}

export function shouldRetryRequest(err) {
  const config = err?.config || {}
  const method = String(config.method || 'get').toLowerCase()
  const status = err?.response?.status
  if (config.retry === false) return false
  if (err?.code === 'ERR_CANCELED') return false
  if (!RETRYABLE_METHODS.has(method)) return false
  if (config.__retryCount >= 1) return false
  return !status || RETRYABLE_STATUSES.has(status)
}

export function createRequestGate() {
  let generation = 0
  let controller = null

  return {
    start({ supersede = true } = {}) {
      if (!supersede && controller && !controller.signal.aborted) return null
      generation += 1
      const id = generation
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      return {
        signal,
        isCurrent: () => id === generation,
        finish() {
          if (id === generation) controller = null
        },
      }
    },
    cancel() {
      generation += 1
      controller?.abort()
      controller = null
    },
  }
}
