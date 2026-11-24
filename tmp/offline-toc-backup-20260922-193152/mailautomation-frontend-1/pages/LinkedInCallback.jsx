import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Linkedin, AlertTriangle, CheckCircle2, ArrowLeft } from 'lucide-react'
import api from '../utils/api'
import { parseLinkedInCallbackUrl } from '../utils/linkedinOAuth'

export default function LinkedInCallback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState({
    type: 'loading',
    title: 'Connecting LinkedIn...',
    message: 'Waiting for LinkedIn authorization to complete.',
  })

  useEffect(() => {
    const { code, error, errorDescription, state } = parseLinkedInCallbackUrl(window.location.search)
    const storedState = sessionStorage.getItem('ts_linkedin_oauth_state') || ''

    if (error) {
      setStatus({
        type: 'error',
        title: 'LinkedIn authorization failed',
        message: errorDescription || error,
      })
      return
    }

    if (!code) {
      setStatus({
        type: 'error',
        title: 'LinkedIn callback missing code',
        message: 'No authorization code was returned. Try signing in again.',
      })
      return
    }

    if (!state || state !== storedState) {
      setStatus({
        type: 'error',
        title: 'LinkedIn state validation failed',
        message: 'The login request could not be verified. Please retry from the login page.',
      })
      return
    }

    sessionStorage.removeItem('ts_linkedin_oauth_state')

    const finishAuth = async () => {
      try {
        const response = await api.post('/auth/linkedin/oauth-callback', {
          code,
          redirect_uri: `${window.location.origin}/auth/linkedin/callback`,
        })

        sessionStorage.setItem('ts_auth', JSON.stringify({
          name: response.data.name,
          email: response.data.email,
          provider: 'linkedin',
          provider_id: response.data.provider_id,
          loggedIn: true,
        }))

        setStatus({
          type: 'success',
          title: 'LinkedIn login successful',
          message: 'You have been signed in successfully. Redirecting...',
        })

        setTimeout(() => navigate('/dashboard', { replace: true }), 1200)
      } catch (e) {
        setStatus({
          type: 'error',
          title: 'LinkedIn login failed',
          message: e.message || 'Unable to complete LinkedIn sign-in.',
        })
      }
    }

    finishAuth()
  }, [navigate, params])

  const tone = {
    loading: 'text-blue-700 bg-blue-50 border-blue-200',
    success: 'text-emerald-600 bg-emerald-50 border-emerald-200',
    error: 'text-red-700 bg-red-50 border-red-200',
  }[status.type]

  const Icon = {
    loading: Linkedin,
    success: CheckCircle2,
    error: AlertTriangle,
  }[status.type]

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#0A66C2]/10">
            <Linkedin className="h-5 w-5 text-[#0A66C2]" />
          </div>
          <div>
            <h1 className="font-bold text-slate-900">LinkedIn Sign-In</h1>
            <p className="text-sm text-slate-500">Finishing LinkedIn authorization</p>
          </div>
        </div>

        <div className={`mt-5 flex gap-3 rounded-xl border p-4 text-sm ${tone}`}>
          <Icon className={`mt-0.5 h-5 w-5 flex-shrink-0 ${status.type === 'loading' ? 'animate-spin' : ''}`} />
          <div>
            <p className="font-semibold">{status.title}</p>
            <p className="mt-1 text-sm text-slate-700">{status.message}</p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => navigate('/login')}
          className="mt-6 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to login
        </button>
      </div>
    </div>
  )
}
