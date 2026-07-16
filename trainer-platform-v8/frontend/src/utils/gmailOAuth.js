const GMAIL_OAUTH_PKCE_KEY = 'gmail_oauth_pkce'
const GMAIL_OAUTH_PKCE_MAX_AGE_MS = 20 * 60 * 1000

function getSessionStorage() {
  try {
    return globalThis.sessionStorage
  } catch {
    return null
  }
}

export function saveGmailOAuthPkce(data = {}) {
  const codeVerifier = data.code_verifier || data.codeVerifier
  if (!codeVerifier) return

  const storage = getSessionStorage()
  if (!storage) return

  storage.setItem(GMAIL_OAUTH_PKCE_KEY, JSON.stringify({
    state: data.state || '',
    code_verifier: codeVerifier,
    created_at: Date.now(),
  }))
}

export function consumeGmailOAuthPkce(state = '') {
  const storage = getSessionStorage()
  if (!storage) return ''

  try {
    const raw = storage.getItem(GMAIL_OAUTH_PKCE_KEY)
    if (!raw) return ''

    const saved = JSON.parse(raw)
    storage.removeItem(GMAIL_OAUTH_PKCE_KEY)

    if (Date.now() - Number(saved.created_at || 0) > GMAIL_OAUTH_PKCE_MAX_AGE_MS) {
      return ''
    }
    if (state && saved.state && saved.state !== state) {
      return ''
    }
    return saved.code_verifier || ''
  } catch {
    storage.removeItem(GMAIL_OAUTH_PKCE_KEY)
    return ''
  }
}

export function clearGmailOAuthPkce() {
  getSessionStorage()?.removeItem(GMAIL_OAUTH_PKCE_KEY)
}

export function normalizeGmailStatus(status = {}) {
  const scopes = Array.isArray(status.scopes) ? status.scopes : []
  const email = status.email || status.gmail_user || status.configured_user || status.user_email || ''
  const calendarConnected = Boolean(
    status.calendar_connected ||
    status.calendar_ready ||
    scopes.some(scope => String(scope).includes('/auth/calendar'))
  )

  return {
    ...status,
    connected: Boolean(status.connected || status.valid || status.token_valid),
    valid: Boolean(status.valid ?? status.connected ?? status.token_valid),
    token_valid: Boolean(status.token_valid ?? status.valid ?? status.connected),
    email,
    gmail_user: email,
    configured_user: email,
    calendar_connected: calendarConnected,
  }
}
