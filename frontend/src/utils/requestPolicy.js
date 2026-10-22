const RETRYABLE_METHODS = new Set(['get', 'head', 'options'])
const RETRYABLE_STATUSES = new Set([500, 502, 503, 504])
const RETRYABLE_NETWORK_CODES = new Set(['ERR_NETWORK', 'ECONNRESET', 'ECONNREFUSED', 'EAI_AGAIN', 'ENOTFOUND'])

export function requestTimeout(config = {}) {
  const explicit = Number(config.timeout)
  if (explicit > 0) return explicit
  const url = String(config.url || '')
  // Profile search uses the signed-in LinkedIn browser session.
  // Keep the ten-minute budget so Find Profiles is not aborted mid-search.
  if (url.includes('/linkedin-leads/search')) return 600000
  const method = String(config.method || 'get').toLowerCase()
  return method === 'get' || method === 'head' || method === 'options' ? 20000 : 300000
}

export function shouldRetryRequest(err) {
  const config = err?.config || {}
  const method = String(config.method || '').toLowerCase()
  const status = err?.response?.status
  if (config.retry === false) return false
  if (config.signal?.aborted) return false
  if (['ERR_CANCELED', 'ECONNABORTED', 'ETIMEDOUT'].includes(err?.code)) return false
  if (!RETRYABLE_METHODS.has(method)) return false
  if (config.__retryCount >= 1) return false
  if (status !== undefined) return RETRYABLE_STATUSES.has(status)
  return RETRYABLE_NETWORK_CODES.has(err?.code)
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
