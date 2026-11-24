const RETRYABLE_METHODS = new Set(['get', 'head', 'options'])
const RETRYABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504])

export function requestTimeout(config = {}) {
  if (config.timeout) return config.timeout
  // Profile search reads public results and a signed-in browser session.
  // Keep the five-minute budget so Find Profiles is not aborted mid-search.
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
  let generation = 0
  let current = null
  return {
    start({ supersede = true } = {}) {
      if (current && !current.done && !supersede) return null
      if (current && !current.done) current.controller.abort()
      const id = ++generation
      const controller = new AbortController()
      const request = {
        signal: controller.signal,
        controller,
        done: false,
        isCurrent() {
          return generation === id && !controller.signal.aborted
        },
        finish() {
          this.done = true
          if (current === request) current = null
        },
      }
      current = request
      return request
    },
    cancel() {
      generation += 1
      if (current && !current.done) current.controller.abort()
      current = null
    },
  }
}
