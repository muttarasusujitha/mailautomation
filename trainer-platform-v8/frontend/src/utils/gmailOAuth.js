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
