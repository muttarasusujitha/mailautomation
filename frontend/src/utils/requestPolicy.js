const RETRYABLE_METHODS = new Set(['get', 'head', 'options'])
const RETRYABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504])

export function requestTimeout(config = {}) {
  const explicit = Number(config.timeout)
  if (explicit > 0) return explicit
  // Profile search reads public results and a signed-in browser session.
  return 300000
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
  let current = 0
  let controller = null
  return {
    start({ supersede = true } = {}) {
      if (!supersede && controller && !controller.signal.aborted) return null
      if (controller) controller.abort()
      controller = new AbortController()
      const id = ++current
      const signal = controller.signal
      return {
        signal,
        isCurrent: () => id === current && !signal.aborted,
        finish: () => {
          if (id === current) controller = null
        },
      }
    },
    cancel() {
      current += 1
      if (controller) controller.abort()
      controller = null
    },
  }
}
