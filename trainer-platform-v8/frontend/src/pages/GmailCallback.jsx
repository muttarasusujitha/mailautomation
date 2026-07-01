import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, Mail, AlertTriangle, CheckCircle2 } from 'lucide-react'
import api from '../utils/api'
import { clearGmailOAuthPkce, consumeGmailOAuthPkce } from '../utils/gmailOAuth'

export default function GmailCallback() {
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
        const codeVerifier = consumeGmailOAuthPkce(state || '')
        await api.post('/gmail/oauth-callback', {
          code,
          state,
          code_verifier: codeVerifier,
          redirect_uri: `${window.location.origin}/auth/callback`,
        })

        try {
          await api.post('/gmail/renew-watch')
          setStatus({ type: 'success', message: 'Gmail and Google Calendar connected. Inbox watch renewed.' })
        } catch (watchError) {
          setStatus({
            type: 'warning',
            message: `Gmail connected. Watch renewal still needs setup: ${watchError.message}`,
          })
        }

        localStorage.setItem('ts_auth', JSON.stringify({ loggedIn: true }))
        setTimeout(() => navigate('/admin', { replace: true }), 2200)
      } catch (e) {
        setStatus({ type: 'error', message: e.message })
      }
    }

    finishAuth()
  }, [navigate, params])

  const Icon =
    status.type === 'success' ? CheckCircle2 :
    status.type === 'warning' ? AlertTriangle :
    status.type === 'error' ? AlertTriangle :
    Loader2

  const tone =
    status.type === 'success' ? 'text-emerald-600 bg-emerald-50 border-emerald-200' :
    status.type === 'warning' ? 'text-amber-700 bg-amber-50 border-amber-200' :
    status.type === 'error' ? 'text-red-700 bg-red-50 border-red-200' :
    'text-blue-700 bg-blue-50 border-blue-200'

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
