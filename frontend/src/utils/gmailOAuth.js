const GMAIL_OAUTH_PKCE_KEY = 'gmail_oauth_pkce'
const GMAIL_OAUTH_PKCE_MAX_AGE_MS = 20 * 60 * 1000

export function getGmailOAuthRedirectUri() {
  return `${globalThis.location.origin}/auth/callback`
}

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

  const state = data.state || ''
  const key = state ? `${GMAIL_OAUTH_PKCE_KEY}:${state}` : GMAIL_OAUTH_PKCE_KEY
  storage.setItem(key, JSON.stringify({
    state,
    code_verifier: codeVerifier,
    redirect_uri: data.redirect_uri || '',
    created_at: Date.now(),
  }))
}

export function consumeGmailOAuthPkce(state = '') {
  const storage = getSessionStorage()
  if (!storage) return {}

  const keys = state
    ? [`${GMAIL_OAUTH_PKCE_KEY}:${state}`, GMAIL_OAUTH_PKCE_KEY]
    : [GMAIL_OAUTH_PKCE_KEY]
  for (const key of keys) {
    try {
      const raw = storage.getItem(key)
      if (!raw) continue

      const saved = JSON.parse(raw)
      if (state && saved.state && saved.state !== state) continue
      storage.removeItem(key)

      if (Date.now() - Number(saved.created_at || 0) > GMAIL_OAUTH_PKCE_MAX_AGE_MS) {
        return {}
      }
      return {
        code_verifier: saved.code_verifier || '',
        redirect_uri: saved.redirect_uri || '',
      }
    } catch {
      storage.removeItem(key)
    }
  }
  return {}
}

export function clearGmailOAuthPkce() {
  const storage = getSessionStorage()
  if (!storage) return
  for (let index = storage.length - 1; index >= 0; index -= 1) {
    const key = storage.key(index)
    if (key?.startsWith(GMAIL_OAUTH_PKCE_KEY)) storage.removeItem(key)
  }
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
