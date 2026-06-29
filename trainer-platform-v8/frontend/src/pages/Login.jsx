import { useCallback, useState, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { forgotPassword, getGoogleClientId, googleLogin, resetPassword } from '../utils/api'
import {
  Mail, Lock, User, Eye, EyeOff,
  CheckCircle, Briefcase, Users, GraduationCap,
  Building2, Phone, Sparkles, Chrome, Github,
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { randomBetween } from '../utils/random'
import BrandMark from '../components/BrandMark'

const GOOGLE_IDENTITY_SCRIPT = 'https://accounts.google.com/gsi/client'

function loadGoogleIdentityScript() {
  if (window.google?.accounts?.oauth2) return Promise.resolve()

  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${GOOGLE_IDENTITY_SCRIPT}"]`)
    if (existing) {
      existing.addEventListener('load', resolve, { once: true })
      existing.addEventListener('error', () => reject(new Error('Google sign-in script failed to load')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = GOOGLE_IDENTITY_SCRIPT
    script.async = true
    script.defer = true
    script.onload = resolve
    script.onerror = () => reject(new Error('Google sign-in script failed to load'))
    document.head.appendChild(script)
  })
}

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
        className="w-full rounded-lg border border-slate-200 bg-white pl-10 pr-10 py-2.5 text-sm
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
  const [googleLoading, setGoogleLoading] = useState(false)
  const [googleReady, setGoogleReady] = useState(false)
  const [googleError, setGoogleError] = useState('')
  const [mounted, setMounted]     = useState(false)
  const [remember, setRemember]   = useState(false)
  const [step, setStep]           = useState(1)
  const navigate = useNavigate()
  const googleTokenClientRef = useRef(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const resetToken = searchParams.get('reset_token') || searchParams.get('token') || ''
  const resetEmail = searchParams.get('email') || ''

  const [form, setForm] = useState({
    name: '', email: '', password: '', confirm: '',
    phone: '', company: '', domain: '', department: '',
  })
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  useEffect(() => { setTimeout(() => setMounted(true), 60) }, [])
  useEffect(() => {
    if (!resetToken) return
    setMode('reset')
    setStep(1)
    setForm(f => ({
      ...f,
      email: resetEmail || f.email,
      password: '',
      confirm: '',
    }))
  }, [resetToken, resetEmail])

  const selectedRole = ROLES.find(r => r.id === role)

  const switchMode = nextMode => {
    setMode(nextMode)
    setStep(1)
    if (resetToken) setSearchParams({})
    if (nextMode !== 'reset') {
      setForm(f => ({ ...f, password: '', confirm: '' }))
    }
  }

  const handleGoogleAccessToken = useCallback(async accessToken => {
    if (!accessToken) {
      toast.error('Google did not return a sign-in token')
      setGoogleLoading(false)
      return
    }

    try {
      const res = await googleLogin({ access_token: accessToken, role })
      const user = res.data?.user || {}
      sessionStorage.setItem('ts_auth', JSON.stringify({
        name: user.name || user.email || 'Google User',
        email: user.email || '',
        picture: user.picture || '',
        role: user.role || role,
        provider: 'google',
        loggedIn: true,
      }))
      toast.success(`Welcome ${user.name || user.email || 'back'}!`)
      if (onLogin) onLogin()
      navigate('/dashboard')
    } catch (e) {
      toast.error(e.message || 'Google login failed')
    } finally {
      setGoogleLoading(false)
    }
  }, [navigate, onLogin, role])

  useEffect(() => {
    let active = true

    const setupGoogleLogin = async () => {
      if (mode === 'reset') return
      setGoogleReady(false)
      setGoogleError('')
      try {
        const clientRes = await getGoogleClientId()
        const clientId = clientRes.data?.client_id
        if (!clientId) throw new Error('Google client ID is not configured')
        await loadGoogleIdentityScript()
        if (!active) return
        googleTokenClientRef.current = window.google.accounts.oauth2.initTokenClient({
          client_id: clientId,
          scope: 'openid email profile',
          callback: response => {
            if (response?.error) {
              toast.error(response.error_description || response.error || 'Google login was cancelled')
              setGoogleLoading(false)
              return
            }
            handleGoogleAccessToken(response?.access_token)
          },
        })
        setGoogleReady(true)
      } catch (e) {
        if (!active) return
        setGoogleError(e.message || 'Google login is not available')
        setGoogleReady(false)
      }
    }

    setupGoogleLogin()
    return () => { active = false }
  }, [handleGoogleAccessToken, mode])

  const handleGoogleLogin = () => {
    if (!googleReady || !googleTokenClientRef.current) {
      toast.error(googleError || 'Google login is still loading')
      return
    }
    setGoogleLoading(true)
    try {
      googleTokenClientRef.current.requestAccessToken({ prompt: 'select_account' })
    } catch (e) {
      setGoogleLoading(false)
      toast.error(e.message || 'Google login failed to start')
    }
  }

  const handleForgotPassword = async () => {
    if (!form.email.trim()) { toast.error('Enter your email address first'); return }
    setResetting(true)
    try { await forgotPassword(form.email.trim()); toast.success(`Reset email sent to ${form.email}`) }
    catch (e) { toast.error(e.message || 'Could not send reset email') }
    finally { setResetting(false) }
  }

  const handleResetPasswordSubmit = async () => {
    if (!resetToken) { toast.error('Reset link is missing or expired'); return }
    if (!form.email.trim()) { toast.error('Enter your email address'); return }
    if (form.password.length < 8) { toast.error('Password must be at least 8 characters'); return }
    if (form.password !== form.confirm) { toast.error('Passwords do not match'); return }

    setResetting(true)
    try {
      await resetPassword({
        email: form.email.trim(),
        token: resetToken,
        password: form.password,
      })
      toast.success('Password reset successfully')
      setSearchParams({})
      setMode('login')
      setForm(f => ({ ...f, password: '', confirm: '' }))
    } catch (e) {
      toast.error(e.message || 'Could not reset password')
    } finally {
      setResetting(false)
    }
  }

  const handleSubmit = async e => {
    e.preventDefault()
    if (mode === 'reset') { await handleResetPasswordSubmit(); return }
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
              {mode === 'reset' ? 'Reset password' : mode === 'login' ? 'Welcome back' : step === 1 ? 'Create account' : 'Almost done'}
            </h2>
            <p className="text-sm text-slate-500 mt-1">
              {mode === 'reset' ? 'Choose a new TrainerSync password' : mode === 'login' ? 'Sign in to TrainerSync' : step === 1 ? 'Choose your role to get started' : 'Set up your profile'}
            </p>
          </div>

          {/* Card */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-lg p-6 space-y-4">

            {/* Role selector */}
            {mode !== 'reset' && <div>
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
            </div>}

            {/* Mode tabs */}
            {mode !== 'reset' && <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
              {['login', 'signup'].map(m => (
                <button key={m} type="button" onClick={() => switchMode(m)}
                  className={clsx(
                    'flex-1 py-1.5 rounded-md text-sm font-semibold transition-all duration-200',
                    mode === m ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  )}>
                  {m === 'login' ? 'Sign In' : 'Sign Up'}
                </button>
              ))}
            </div>}

            {/* Social login */}
            {mode !== 'reset' && <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={handleGoogleLogin}
                disabled={googleLoading || !googleReady}
                title={googleError || (googleReady ? 'Sign in with Google' : 'Google login is loading')}
                className="flex items-center justify-center gap-2 py-2 bg-white hover:bg-slate-50
                           border border-slate-200 rounded-lg text-slate-600 text-xs font-semibold
                           transition-all hover:shadow-sm disabled:opacity-60 disabled:cursor-not-allowed">
                {googleLoading
                  ? <span className="h-4 w-4 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
                  : <Chrome className="h-4 w-4" />}
                {googleLoading ? 'Signing in...' : googleError ? 'Google unavailable' : 'Google'}
              </button>
              <button type="button" onClick={() => toast('GitHub login coming soon!')}
                className="flex items-center justify-center gap-2 py-2 bg-white hover:bg-slate-50
                           border border-slate-200 rounded-lg text-slate-600 text-xs font-semibold
                           transition-all hover:shadow-sm">
                <Github className="h-4 w-4" />GitHub
              </button>
            </div>}

            {mode !== 'reset' && <div className="divider-label">or email</div>}

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-2.5">
              {mode === 'reset' && (
                <>
                  <Field icon={Mail} type="email" placeholder="Email address" value={form.email} onChange={set('email')} />
                  <Field icon={Lock} type={showPass ? 'text' : 'password'} placeholder="New password"
                    value={form.password} onChange={set('password')}
                    right={
                      <button type="button" onClick={() => setShowPass(!showPass)} className="text-slate-400 hover:text-slate-600">
                        {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    } />
                  <Field icon={Lock} type={showPass ? 'text' : 'password'} placeholder="Confirm new password" value={form.confirm} onChange={set('confirm')} />
                </>
              )}

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
                      <div onClick={() => setRemember(!remember)}
                        className={clsx('h-4 w-4 rounded border flex items-center justify-center cursor-pointer transition-all',
                          remember ? 'bg-blue-600 border-blue-600' : 'border-slate-300 bg-white')}>
                        {remember && <CheckCircle className="h-3 w-3 text-white" />}
                      </div>
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
                  className="w-full py-2 rounded-lg border border-slate-200 text-slate-600 text-sm font-medium hover:bg-slate-50 transition-all">
                  ← Back
                </button>
              )}

              <button type="submit" disabled={loading || resetting}
                className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 font-bold text-sm text-white
                           flex items-center justify-center gap-2 transition-all duration-150
                           hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-60 disabled:cursor-not-allowed disabled:translate-y-0">
                {loading || (mode === 'reset' && resetting)
                  ? <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  : <>
                      <Sparkles className="h-4 w-4" />
                      {mode === 'reset' ? 'Reset Password' : mode === 'login' ? 'Sign In' : step === 1 ? 'Continue →' : 'Create Account'}
                    </>
                }
              </button>
            </form>

            <p className="text-center text-slate-500 text-xs">
              {mode === 'reset' ? 'Remembered your password? ' : mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
              <button type="button" onClick={() => switchMode(mode === 'login' ? 'signup' : 'login')}
                className="font-semibold text-blue-600 hover:text-blue-800">
                {mode === 'reset' ? 'Sign in' : mode === 'login' ? 'Sign up free' : 'Sign in'}
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
