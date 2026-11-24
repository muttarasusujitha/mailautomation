import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, Mail, AlertTriangle, CheckCircle2 } from 'lucide-react'
import api from '../utils/api'
import { clearGmailOAuthPkce, consumeGmailOAuthPkce, normalizeGmailStatus } from '../utils/gmailOAuth'

export default function GmailCallback({ onLogin }) {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState({ type: 'loading', message: 'Connecting Gmail...' })
  const handledRef = useRef(false)

  useEffect(() => {
    if (handledRef.current) return
    handledRef.current = true

    const finishAuth = async () => {
      const error = params.get('error')
      const code = params.get('code')
      const state = params.get('state')
      const oauthSession = consumeGmailOAuthPkce(state || '')
      const personalConnection = oauthSession.account_scope === 'personal'

      if (error) {
        clearGmailOAuthPkce()
        setStatus({ type: 'error', message: `Google rejected the connection: ${error}` })
        return
      }
      if (!code) {
        clearGmailOAuthPkce()
        setStatus({ type: 'error', message: 'Missing Google authorization code.' })
        return
      }

      try {
        const codeVerifier = oauthSession.code_verifier || ''
        const redirectUri = oauthSession.redirect_uri || `${window.location.origin}/auth/callback`
        const callbackPath = personalConnection ? '/gmail/me/oauth-callback' : '/gmail/oauth-callback'
        await api.post(callbackPath, {
          code,
          state,
          code_verifier: codeVerifier,
          redirect_uri: redirectUri,
        })

        if (personalConnection) {
          const statusRes = await api.get('/gmail/me/auth-status')
          const email = statusRes.data?.email || ''
          setStatus({
            type: 'success',
            message: email ? `Your Gmail account (${email}) is connected and ready for a test send.` : 'Your personal Gmail account is connected.',
          })
        } else {
          try {
            await api.post('/gmail/renew-watch')
            const statusRes = await api.get('/gmail/auth-status')
            const normalized = normalizeGmailStatus(statusRes.data || {})
            const calendarReady = Boolean(normalized.calendar_connected)
            setStatus({
              type: calendarReady ? 'success' : 'warning',
              message: calendarReady
                ? 'Gmail and Google Calendar connected. Inbox watch renewed.'
                : 'Gmail connected. Google Calendar scope is still being confirmed.',
            })
          } catch (watchError) {
            setStatus({
              type: 'warning',
              message: `Gmail connected. Watch renewal still needs setup: ${watchError.message}`,
            })
          }
        }

        // Connecting a mailbox never creates an application identity.
        if (personalConnection) {
          setTimeout(() => navigate('/profile', { replace: true }), 1400)
        } else if (typeof onLogin === 'function') {
          await onLogin()
          navigate('/admin', { replace: true })
        } else {
          setTimeout(() => window.location.assign('/admin'), 2200)
        }
      } catch (e) {
        setStatus({ type: 'error', message: e.message })
      }
    }

    finishAuth()
  }, [navigate, params])

  let Icon = Loader2
  let tone = 'text-blue-700 bg-blue-50 border-blue-200'

  if (status.type === 'success') {
    Icon = CheckCircle2
    tone = 'text-emerald-600 bg-emerald-50 border-emerald-200'
  } else if (status.type === 'warning') {
    Icon = AlertTriangle
    tone = 'text-amber-700 bg-amber-50 border-amber-200'
  } else if (status.type === 'error') {
    Icon = AlertTriangle
    tone = 'text-red-700 bg-red-50 border-red-200'
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50">
            <Mail className="h-5 w-5 text-blue-600" />
          </div>
          <div>
            <h1 className="font-bold text-slate-900">Gmail Connection</h1>
            <p className="text-sm text-slate-500">Finishing Google authorization</p>
          </div>
        </div>

        <div className={`mt-5 flex gap-3 rounded-xl border p-4 text-sm ${tone}`}>
          <Icon className={`mt-0.5 h-5 w-5 flex-shrink-0 ${status.type === 'loading' ? 'animate-spin' : ''}`} />
          <p>{status.message}</p>
        </div>
      </div>
    </div>
  )
}
