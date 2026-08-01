import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { forgotPassword } from '../utils/api'
import {
  Mail, Lock, User, Eye, EyeOff,
  CheckCircle, Briefcase, Users, GraduationCap,
  Building2, Phone, Sparkles, Chrome, Linkedin,
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { randomBetween } from '../utils/random'
import BrandMark from '../components/BrandMark'

const GoogleLogo = () => (
  <svg viewBox="0 0 46 46" className="h-4 w-4" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M23 9.4c3.5 0 6.1 1.2 7.5 2.3l5.5-5.5C33.8 3 28.9 1.5 23 1.5 14 1.5 6.3 6.8 3.2 14.7l6.5 5.1C11.7 15 16.8 9.4 23 9.4z" fill="#EA4335"/>
    <path d="M41.8 23.5c0-1.2-.1-2.2-.3-3.2H23v6.1h10.7c-.5 2.6-2.1 4.8-4.5 6.2l6.8 5.3c4-3.7 6.3-9.2 6.3-14.4z" fill="#4285F4"/>
    <path d="M9.7 27.8c-.4-1.2-.6-2.4-.6-3.8s.2-2.6.6-3.8L3.2 15.1C1.1 18.2 0 21.8 0 25.5c0 3.7 1.1 7.3 3.2 10.4l6.5-5.1z" fill="#FBBC05"/>
    <path d="M23 44.5c6.1 0 11.3-2 15.1-5.4l-7.3-5.7c-2 1.4-4.5 2.3-7.8 2.3-6.2 0-11.3-4.6-12.4-10.8l-6.5 5.1C6.3 39.2 14 44.5 23 44.5z" fill="#34A853"/>
  </svg>
)

/* ─── Particle canvas ──────────────────────────────────────── */
function ParticleCanvas() {
  const ref = useRef(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf
    const resize = () => { canvas.width = canvas.offsetWidth; canvas.height = canvas.offsetHeight }
    resize()
    window.addEventListener('resize', resize)
    const dots = Array.from({ length: 40 }, () => ({
      x: randomBetween(0, canvas.width), y: randomBetween(0, canvas.height),
      vx: randomBetween(-0.15, 0.15), vy: randomBetween(-0.15, 0.15),
      r: randomBetween(1, 2.5), pulse: randomBetween(0, Math.PI * 2),
    }))
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      dots.forEach(d => {
        d.x += d.vx; d.y += d.vy; d.pulse += 0.01
        if (d.x < 0 || d.x > canvas.width) d.vx *= -1
        if (d.y < 0 || d.y > canvas.height) d.vy *= -1
        const r = d.r + Math.sin(d.pulse) * 0.3
        ctx.beginPath(); ctx.arc(d.x, d.y, r, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(255,255,255,0.5)'; ctx.fill()
      })
      dots.forEach((a, i) => dots.slice(i + 1).forEach(b => {
        const dist = Math.hypot(a.x - b.x, a.y - b.y)
        if (dist < 100) {
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y)
          ctx.strokeStyle = `rgba(255,255,255,${0.08 * (1 - dist / 100)})`
          ctx.lineWidth = 0.5; ctx.stroke()
        }
      }))
      raf = requestAnimationFrame(draw)
    }
    draw()
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize) }
  }, [])
  return <canvas ref={ref} className="absolute inset-0 w-full h-full pointer-events-none" />
}

/* ─── Role definitions ─────────────────────────────────────── */
const ROLES = [
  {
    id: 'recruiter', label: 'Recruiter', icon: Briefcase,
    tagline: 'Find & hire the best trainers',
    features: [
      'AI-powered trainer matching in seconds',
      'Automated 7-stage email pipeline',
      'Reply tracking & shortlist management',
      'Interview scheduling with Zoom/Teams/Meet',
    ],
  },
  {
    id: 'trainer', label: 'Trainer', icon: GraduationCap,
    tagline: 'Get matched to opportunities',
    features: [
      'Get matched to relevant training requirements',
      'Receive structured requirement details',
      'Schedule interviews at your convenience',
      'Manage your availability and profile',
    ],
  },
  {
    id: 'employee', label: 'Employee', icon: Building2,
    tagline: "Track your team's training",
    features: [
      "View your team's training schedule",
      'Access training materials & resources',
      'Track completion and progress metrics',
      'Communicate with assigned trainers',
    ],
  },
]

/* ─── Input field ──────────────────────────────────────────── */
function Field({ icon: Icon, type = 'text', placeholder, value, onChange, right, required = true }) {
  return (
    <div className="relative">
      <Icon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
      <input
        type={type} placeholder={placeholder} value={value}
        onChange={onChange} required={required}
        className="w-full rounded-2xl border border-slate-200 bg-white pl-10 pr-10 py-2.5 text-sm
                   text-slate-800 placeholder-slate-400 outline-none
                   focus:border-blue-500 focus:ring-2 focus:ring-blue-100
                   transition-all duration-150"
      />
      {right && <div className="absolute right-3 top-1/2 -translate-y-1/2">{right}</div>}
    </div>
  )
}


/* ─── Main component ───────────────────────────────────────── */
export default function Login({ onLogin }) {
  const [mode, setMode]           = useState('login')
  const [role, setRole]           = useState('recruiter')
  const [showPass, setShowPass]   = useState(false)
  const [loading, setLoading]     = useState(false)
  const [resetting, setResetting] = useState(false)
  const [mounted, setMounted]     = useState(false)
  const [remember, setRemember]   = useState(false)
  const [step, setStep]           = useState(1)
  const [googleReady, setGoogleReady] = useState(false)
  const [googleInitError, setGoogleInitError] = useState('')
  const googleInitAttemptedRef = useRef(false)
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''
  const googleEnabled = Boolean(googleClientId)
  const linkedInClientId = import.meta.env.VITE_LINKEDIN_CLIENT_ID || ''
  const linkedInRedirectUri = import.meta.env.VITE_LINKEDIN_REDIRECT_URI || ''
  const linkedInScopes = import.meta.env.VITE_LINKEDIN_SCOPES || 'r_liteprofile r_emailaddress'
  const linkedInEnabled = Boolean(linkedInClientId && linkedInRedirectUri)
  const navigate = useNavigate()

  const [form, setForm] = useState({
    name: '', email: '', password: '', confirm: '',
    phone: '', company: '', domain: '', department: '',
  })
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  const decodeJwt = token => {
    try {
      const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
      const jsonPayload = decodeURIComponent(atob(base64).split('').map(c =>
        `%${('00' + c.codePointAt(0).toString(16)).slice(-2)}`
      ).join(''))
      return JSON.parse(jsonPayload)
    } catch {
      return null
    }
  }

  const finalizeLogin = authData => {
    sessionStorage.setItem('ts_auth', JSON.stringify(authData))
    toast.success(`Signed in as ${authData.email}`)
    if (onLogin) onLogin()
    navigate('/dashboard')
  }

  const handleGoogleCredentialResponse = response => {
    if (!response?.credential) {
      toast.error('Google login failed.')
      return
    }
    const payload = decodeJwt(response.credential)
    if (!payload?.email) {
      toast.error('Google login failed.')
      return
    }

    finalizeLogin({
      name: payload.name || payload.email.split('@')[0],
      email: payload.email,
      picture: payload.picture || '',
      provider: 'google',
      loggedIn: true,
    })
  }

  const handleGoogleButtonClick = () => {
    if (!window.google?.accounts?.id) {
      toast.error('Google login is not ready yet. Please use email/password instead.')
      return
    }

    try {
      window.google.accounts.id.prompt()
    } catch (error) {
      console.error('Google prompt failed', error)
      setGoogleInitError('Google sign-in is blocked by the OAuth client configuration. Please use email/password instead.')
      toast.error('Google sign-in is blocked. Please use email/password instead.')
    }
  }

  const handleLinkedInButtonClick = () => {
    if (!linkedInEnabled) {
      toast.error('LinkedIn login is not configured.')
      return
    }

    const state = `ts_li_${Date.now()}_${Math.random().toString(36).slice(2)}`
    sessionStorage.setItem('ts_linkedin_oauth_state', state)

    const authUrl = new URL('https://www.linkedin.com/oauth/v2/authorization')
    authUrl.searchParams.set('response_type', 'code')
    authUrl.searchParams.set('client_id', linkedInClientId)
    authUrl.searchParams.set('redirect_uri', linkedInRedirectUri)
    authUrl.searchParams.set('state', state)
    authUrl.searchParams.set('scope', linkedInScopes)

    window.location.assign(authUrl.toString())
  }

  useEffect(() => { setTimeout(() => setMounted(true), 60) }, [])

  useEffect(() => {
    if (!googleClientId) {
      setGoogleReady(false)
      googleInitAttemptedRef.current = false
      return
    }

    if (googleInitAttemptedRef.current) {
      return
    }

    const initGoogle = () => {
      try {
        if (!window.google?.accounts?.id) {
          setGoogleReady(false)
          setGoogleInitError('Google sign-in script is not available yet.')
          return
        }

        // Prevent duplicate initialization across StrictMode double-mounts
        if (window.__gsi_initialized) {
          setGoogleReady(true)
          setGoogleInitError('')
          googleInitAttemptedRef.current = true
          return
        }

        googleInitAttemptedRef.current = true
        window.google.accounts.id.initialize({
          client_id: googleClientId,
          callback: handleGoogleCredentialResponse,
          cancel_on_tap_outside: true,
        })
        // mark globally to avoid re-initialization in dev StrictMode
        try { window.__gsi_initialized = true } catch {}
        setGoogleReady(true)
        setGoogleInitError('')
      } catch (error) {
        console.error('Google login initialization failed', error)
        setGoogleReady(false)
        setGoogleInitError('Google sign-in is blocked by the OAuth client configuration. Please use email/password instead.')
      }
    }

    if (window.google?.accounts?.id) {
      initGoogle()
      return
    }

    const script = document.createElement('script')
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.defer = true
    script.onload = initGoogle
    script.onerror = () => setGoogleReady(false)
    document.head.appendChild(script)

    return () => {
      script.remove()
    }
  }, [googleClientId])

  const selectedRole = ROLES.find(r => r.id === role)

  const handleForgotPassword = async () => {
    if (!form.email.trim()) { toast.error('Enter your email address first'); return }
    setResetting(true)
    try { await forgotPassword(form.email.trim()); toast.success(`Reset email sent to ${form.email}`) }
    catch (e) { toast.error(e.message || 'Could not send reset email') }
    finally { setResetting(false) }
  }

  const handleSubmit = async e => {
    e.preventDefault()
    if (mode === 'signup' && step === 1) { setStep(2); return }
    if (mode === 'signup' && form.password !== form.confirm) { toast.error('Passwords do not match'); return }
    setLoading(true)
    await new Promise(r => setTimeout(r, 1200))
    // SEC-009: sessionStorage clears on tab/browser close — safer than localStorage for auth tokens
    sessionStorage.setItem('ts_auth', JSON.stringify({ name: form.name || 'User', email: form.email, role, loggedIn: true }))
    toast.success(mode === 'login' ? `Welcome back!` : `Account created!`)
    setLoading(false)
    if (onLogin) onLogin()
    navigate('/dashboard')
  }

  return (
    <div className="min-h-screen flex overflow-hidden bg-white">

      {/* ── Left panel ─────────────────────────────────── */}
      <div className={clsx(
        'hidden lg:flex flex-col w-[46%] relative overflow-hidden transition-all duration-700',
        'bg-gradient-to-br from-blue-700 via-blue-600 to-blue-500',
        mounted ? 'opacity-100' : 'opacity-0'
      )}>
        <div className="absolute inset-0 bg-gradient-to-b from-black/10 to-transparent" />
        <ParticleCanvas />

        {/* Decorative circles */}
        <div className="absolute -top-20 -right-20 h-64 w-64 rounded-full bg-white/5" />
        <div className="absolute bottom-20 -left-16 h-48 w-48 rounded-full bg-white/5" />

        <div className="relative z-10 flex flex-col h-full p-12">
          <BrandMark size="lg" theme="dark" />

          <div className="flex-1 flex flex-col justify-center space-y-8 mt-12">
            {/* Role badge */}
            <div className="inline-flex items-center gap-2 bg-white/15 border border-white/20 rounded-lg px-3 py-1.5 w-fit">
              <span className="h-1.5 w-1.5 rounded-full bg-white/80" />
              <span className="text-white/90 text-sm font-semibold">For {selectedRole.label}s</span>
            </div>

            {/* Headline */}
            <div>
              <h1 className="text-4xl font-bold text-white leading-tight tracking-tight">
                {role === 'recruiter' && <>Find the right trainer,<br /><span className="text-blue-200">close faster.</span></>}
                {role === 'trainer'   && <>Get matched to<br /><span className="text-blue-200">opportunities.</span></>}
                {role === 'employee'  && <>Track your team's<br /><span className="text-blue-200">training journey.</span></>}
              </h1>
              <p className="text-white/70 text-base mt-4 leading-relaxed max-w-xs">
                {selectedRole.tagline}
              </p>
            </div>

            {/* Feature list */}
            <ul className="space-y-3">
              {selectedRole.features.map((f, i) => (
                <li key={i} className="flex items-start gap-3 text-white/85 text-sm">
                  <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-white/20">
                    <CheckCircle className="h-3 w-3 text-white" />
                  </div>
                  {f}
                </li>
              ))}
            </ul>
          </div>

          {/* Stats row */}
          <div className="flex gap-8 pt-6 border-t border-white/15">
            {[['500+', 'Trainers'], ['98%', 'Match Rate'], ['3×', 'Faster']].map(([v, l]) => (
              <div key={l}>
                <p className="text-2xl font-bold text-white tracking-tight">{v}</p>
                <p className="text-xs text-white/55 mt-0.5 font-medium">{l}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Right panel — form ──────────────────────────── */}
      <div className="flex-1 flex items-center justify-center px-6 py-8 bg-slate-50">
        <div className={clsx(
          'w-full max-w-[440px] transition-all duration-700',
          mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6'
        )}>
          {/* Mobile logo */}
          <BrandMark className="mb-6 lg:hidden" />

          {/* Heading */}
          <div className="mb-5">
            <h2 className="text-xl font-bold text-slate-900 tracking-tight" style={{ fontFamily: "'Plus Jakarta Sans',sans-serif" }}>
              {mode === 'login' ? 'Welcome back' : step === 1 ? 'Create account' : 'Almost done'}
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              {mode === 'login' ? 'Sign in to TrainerSync' : step === 1 ? 'Choose your role to get started' : 'Set up your profile'}
            </p>
          </div>

          {/* Card */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-lg p-6 space-y-4">

            {/* Role selector */}
            <div>
              <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                {mode === 'login' ? 'Sign in as' : 'I am a'}
              </p>
              <div className="flex gap-2">
                {ROLES.map(r => {
                  const Icon = r.icon
                  const active = role === r.id
                  return (
                    <button key={r.id} type="button" onClick={() => { setRole(r.id); setStep(1) }}
                      className={clsx(
                        'flex-1 flex flex-col items-center gap-1.5 p-3 rounded-xl border-2 transition-all duration-200',
                        active
                          ? 'border-blue-500 bg-blue-50 shadow-sm'
                          : 'border-slate-200 bg-white hover:border-slate-300'
                      )}>
                      <div className={clsx(
                        'h-9 w-9 flex items-center justify-center rounded-lg transition-all',
                        active ? 'bg-blue-600' : 'bg-slate-100'
                      )}>
                        <Icon className={clsx('h-4 w-4', active ? 'text-white' : 'text-slate-500')} />
                      </div>
                      <span className={clsx('text-[11px] font-bold', active ? 'text-blue-700' : 'text-slate-500')}>
                        {r.label}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Mode tabs */}
            <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
              {['login', 'signup'].map(m => (
                <button key={m} type="button" onClick={() => { setMode(m); setStep(1) }}
                  className={clsx(
                    'flex-1 py-1.5 rounded-md text-sm font-semibold transition-all duration-200',
                    mode === m ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  )}>
                  {m === 'login' ? 'Sign In' : 'Sign Up'}
                </button>
              ))}
            </div>

            {/* Social login */}
            <div className="grid grid-cols-1 gap-2">
              <button
                type="button"
                onClick={handleGoogleButtonClick}
                disabled={!googleEnabled || !!googleInitError}
                className={clsx(
                  'flex w-full items-center justify-center gap-3 rounded-full border px-4 py-3 text-sm font-semibold shadow-sm transition',
                  googleEnabled && !googleInitError
                    ? 'border-blue-500 bg-white text-slate-900 hover:bg-blue-50'
                    : 'border-slate-200 bg-slate-100 text-slate-400 cursor-not-allowed'
                )}
              >
                <GoogleLogo />
                Sign in with Google
              </button>

              {linkedInEnabled && (
                <button
                  type="button"
                  onClick={handleLinkedInButtonClick}
                  className="flex w-full items-center justify-center gap-3 rounded-full border border-[#0A66C2] bg-white px-4 py-3 text-sm font-semibold text-slate-900 shadow-sm transition hover:bg-blue-50"
                >
                  <Linkedin className="h-4 w-4 text-[#0A66C2]" />
                  Sign in with LinkedIn
                </button>
              )}

              {(googleInitError || (!googleReady && googleEnabled)) && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
                  <p className="font-semibold">Google login is not currently available.</p>
                  <p className="mt-1 text-xs text-amber-600">{googleInitError || 'Please continue with the email/password form for now.'}</p>
                </div>
              )}
            </div>

            <div className="divider-label">or email</div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-2.5">
              {mode === 'login' && (
                <>
                  <Field icon={Mail} type="email" placeholder="Email address" value={form.email} onChange={set('email')} />
                  <Field icon={Lock} type={showPass ? 'text' : 'password'} placeholder="Password"
                    value={form.password} onChange={set('password')}
                    right={
                      <button type="button" onClick={() => setShowPass(!showPass)} className="text-slate-400 hover:text-slate-600">
                        {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    } />
                  <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={remember}
                        onChange={event => setRemember(event.target.checked)}
                        className="sr-only"
                      />
                      <span
                        className={clsx('h-4 w-4 rounded border flex items-center justify-center cursor-pointer transition-all',
                          remember ? 'bg-blue-600 border-blue-600' : 'border-slate-300 bg-white')}
                        aria-hidden="true"
                      >
                        {remember && <CheckCircle className="h-3 w-3 text-white" />}
                      </span>
                      <span className="text-xs text-slate-500">Remember me</span>
                    </label>
                    <button type="button" onClick={handleForgotPassword} disabled={resetting}
                      className="text-xs text-blue-600 hover:text-blue-800 font-semibold disabled:opacity-60">
                      {resetting ? 'Sending...' : 'Forgot password?'}
                    </button>
                  </div>
                </>
              )}

              {mode === 'signup' && step === 1 && (
                <>
                  <Field icon={User} placeholder="Full name" value={form.name} onChange={set('name')} />
                  <Field icon={Mail} type="email" placeholder="Email address" value={form.email} onChange={set('email')} />
                  {role === 'recruiter' && <Field icon={Building2} placeholder="Company name" value={form.company} onChange={set('company')} required={false} />}
                  {role === 'trainer'   && <Field icon={GraduationCap} placeholder="Domain (e.g. Python, AWS)" value={form.domain} onChange={set('domain')} required={false} />}
                  {role === 'employee'  && <Field icon={Building2} placeholder="Company / Organization" value={form.company} onChange={set('company')} required={false} />}
                </>
              )}

              {mode === 'signup' && step === 2 && (
                <>
                  <Field icon={Phone} type="tel" placeholder="Phone number" value={form.phone} onChange={set('phone')} required={false} />
                  {role === 'employee' && <Field icon={Users} placeholder="Department (e.g. Engineering)" value={form.department} onChange={set('department')} required={false} />}
                  <Field icon={Lock} type={showPass ? 'text' : 'password'} placeholder="Create password"
                    value={form.password} onChange={set('password')}
                    right={<button type="button" onClick={() => setShowPass(!showPass)} className="text-slate-400 hover:text-slate-600">{showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button>} />
                  <Field icon={Lock} type={showPass ? 'text' : 'password'} placeholder="Confirm password" value={form.confirm} onChange={set('confirm')} />
                </>
              )}

              {/* Step indicator */}
              {mode === 'signup' && (
                <div className="flex items-center gap-2 py-0.5">
                  {[1, 2].map(s => (
                    <div key={s} className={clsx('h-1.5 rounded-full transition-all duration-300',
                      s === step ? 'flex-1 bg-blue-600' : s < step ? 'flex-1 bg-blue-300' : 'w-6 bg-slate-200'
                    )} />
                  ))}
                  <span className="text-xs text-slate-400">Step {step}/2</span>
                </div>
              )}

              {mode === 'signup' && step === 2 && (
                <button type="button" onClick={() => setStep(1)}
                  className="w-full py-2 rounded-2xl border border-slate-200 text-slate-600 text-sm font-medium hover:bg-slate-50 transition-all">
                  ← Back
                </button>
              )}

              <button type="submit" disabled={loading}
                className="w-full py-2.5 rounded-2xl bg-blue-600 hover:bg-blue-700 font-bold text-sm text-white
                           flex items-center justify-center gap-2 transition-all duration-150
                           hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-60 disabled:cursor-not-allowed disabled:translate-y-0">
                {loading
                  ? <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  : <>
                      <Sparkles className="h-4 w-4" />
                      {mode === 'login' ? 'Sign In' : step === 1 ? 'Continue →' : 'Create Account'}
                    </>
                }
              </button>
            </form>

            <p className="text-center text-slate-500 text-xs">
              {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
              <button onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setStep(1) }}
                className="font-semibold text-blue-600 hover:text-blue-800">
                {mode === 'login' ? 'Sign up free' : 'Sign in'}
              </button>
            </p>
          </div>

          <p className="text-center text-slate-400 text-[11px] mt-4">
            Secured by TrainerSync · Clahan Technologies
          </p>
        </div>
      </div>
    </div>
  )
}
