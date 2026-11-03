import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { acceptSession, forgotPassword } from '../utils/api'
import {
  Mail, Lock, User, Eye, EyeOff,
  CheckCircle, ShieldCheck, GraduationCap,
  Building2, Phone, Sparkles, Linkedin,
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
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
/* ─── Role definitions ─────────────────────────────────────── */
const ROLES = [
  {
    id: 'admin', label: 'Administrator', icon: ShieldCheck,
    tagline: 'Manage the TrainerSync workspace',
    features: [
      'Review trainer applications and resumes',
      'Manage client requests and matching',
      'Coordinate interviews and handoffs',
      'Access staff dashboards and tools',
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
    id: 'client', label: 'Client', icon: Building2,
    tagline: 'Find and choose a trainer',
    features: [
      'Describe your training requirement',
      'Work with the TrainerSync matching team',
      'Keep trainer details private until handoff',
      'Track your request in your client portal',
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
export default function Login({ onLogin, initialRole = 'admin', allowSignup = true }) {
  const [mode, setMode]           = useState('login')
  const [role, setRole]           = useState(initialRole)
  const [showPass, setShowPass]   = useState(false)
  const [loading, setLoading]     = useState(false)
  const [resetting, setResetting] = useState(false)
  const [mounted, setMounted]     = useState(false)
  const [remember, setRemember]   = useState(false)
  const [step, setStep]           = useState(1)
  const [googleReady, setGoogleReady] = useState(false)
  const googleInitAttemptedRef = useRef(false)
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''
  const googleEnabled = Boolean(googleClientId)
  const linkedInClientId = import.meta.env.VITE_LINKEDIN_CLIENT_ID || ''
  const linkedInRedirectUri = import.meta.env.VITE_LINKEDIN_REDIRECT_URI || ''
  const linkedInEnabled = Boolean(linkedInClientId && linkedInRedirectUri)
  const navigate = useNavigate()

  const [form, setForm] = useState({
    name: '', email: '', password: '', confirm: '',
    phone: '', company: '', domain: '', department: '',
  })
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  const finalizeLogin = async data => {
    acceptSession(data)
    const account = onLogin ? await onLogin() : data.user
    toast.success(`Signed in as ${data.user.email}`)
    const role = (account || data.user)?.role
    navigate(role === 'trainer' ? '/trainer-portal' : role === 'client' ? '/client-portal' : '/dashboard')
  }

  const handleGoogleCredentialResponse = async response => {
    if (!response?.credential) { toast.error('Google login failed.'); return }
    try {
      const { data } = await api.post('/auth/google', { credential: response.credential, desired_role: role })
      await finalizeLogin(data)
    } catch (error) { toast.error(error.message) }
  }

  const handleGoogleButtonClick = () => {
    if (!window.google?.accounts?.id) {
      toast.error('Google login is not ready yet.')
      return
    }

    try {
      window.google.accounts.id.prompt()
    } catch (error) {
      console.error('Google prompt failed', error)
      toast.error('Google sign-in failed. Please try again.')
    }
  }

  const handleLinkedInButtonClick = async () => {
    try {
      const { data } = await api.post('/auth/linkedin/start', { desired_role: role })
      window.location.assign(data.url)
    } catch (error) { toast.error(error.message) }
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
          return
        }

        // Prevent duplicate initialization across StrictMode double-mounts
        if (window.__gsi_initialized) {
          setGoogleReady(true)
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
      } catch (error) {
        console.error('Google login initialization failed', error)
        setGoogleReady(false)
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
  const loginTheme = role === 'admin'
    ? { accent: 'bg-slate-900 hover:bg-slate-800' }
    : role === 'client'
      ? { accent: 'bg-emerald-700 hover:bg-emerald-800' }
      : { accent: 'bg-blue-700 hover:bg-blue-800' }
  const roleOptions = initialRole ? ROLES.filter(item => item.id === initialRole) : ROLES
  const signupOptions = roleOptions.filter(item => item.id !== 'admin')

  const handleForgotPassword = async () => {
    if (!form.email.trim()) { toast.error('Enter your email address first'); return }
    setResetting(true)
    try { const { data } = await forgotPassword(form.email.trim()); toast.success(data.message || "If this account supports password recovery, you will receive instructions.") }
    catch (e) { toast.error(e.message || 'Could not send reset email') }
    finally { setResetting(false) }
  }

  const handleSubmit = async e => {
    e.preventDefault()
    if (mode === 'signup' && step === 1) { setStep(2); return }
    if (mode === 'signup' && form.password !== form.confirm) { toast.error('Passwords do not match'); return }
    setLoading(true)
    try {
      const { data } = await api.post(mode === 'signup' ? '/auth/register' : '/auth/login', {
        email: form.email.trim(), password: form.password,
        ...(mode === 'login' ? { desired_role: role } : {}),
        ...(mode === 'signup' ? { name: form.name, role, domain: form.domain, company: form.company, phone: form.phone } : {}),
      })
      if (mode === 'signup') {
        if (data.user && data.csrf_token) {
          await finalizeLogin(data)
          return
        }
        toast.success(data.message, { duration: 8000 })
        setMode('login')
        setStep(1)
        setForm(value => ({ ...value, password: '', confirm: '' }))
      } else await finalizeLogin(data)
    } catch (error) { toast.error(error.message) }
    finally { setLoading(false) }
  }

  return (
    <div className="relative min-h-screen flex overflow-hidden bg-[#f7f7f5]">
      <nav aria-label="Login navigation" className="absolute inset-x-0 top-0 z-20 flex h-16 items-center justify-between border-b border-slate-200/80 bg-[#f7f7f5]/90 px-5 backdrop-blur sm:px-8 lg:bg-transparent lg:border-0">
        <a href="/home" className="text-sm font-semibold text-slate-700 hover:text-blue-700">Home</a>
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{selectedRole.label} access</span>
      </nav>

      <div className={clsx('hidden lg:flex w-[55%] min-h-screen flex-col bg-[#111114] p-5 pt-[76px] transition-opacity duration-700', mounted ? 'opacity-100' : 'opacity-0')}>
        <div className="relative flex-1 overflow-hidden rounded-[26px] bg-[#171719]">
          <img src="/images/office-girl.png" alt="TrainerSync professional using a laptop" className="absolute inset-0 h-full w-full object-cover object-[center_20%] opacity-80" />
          <div className="absolute inset-0 bg-gradient-to-b from-black/85 via-black/35 to-black/5" />
          <div className="absolute left-8 top-7 z-20 xl:left-10"><BrandMark size="lg" theme="dark" /></div>
          <div className="absolute left-8 right-8 top-28 z-20 max-w-lg xl:left-10 xl:top-32">
            <p className="text-xs font-bold uppercase tracking-[.22em] text-blue-200">TrainerSync / {selectedRole.label}</p>
            <h1 className="mt-3 text-3xl font-bold leading-[1.08] tracking-tight text-white xl:text-5xl">
              {role === 'admin' && <>Training talent,<br />better connected.</>}
              {role === 'trainer' && <>Your experience<br />opens new doors.</>}
              {role === 'client' && <>Make learning<br />work for your team.</>}
            </h1>
            <p className="mt-4 max-w-sm text-sm leading-6 text-white/80 xl:text-base">{selectedRole.tagline}</p>
          </div>

          <div className="absolute -bottom-2 left-[8%] z-10 w-[88%] rotate-[-4deg] rounded-t-[20px] border border-slate-300/80 bg-[#fbfbfa] p-3 shadow-[0_30px_80px_rgba(0,0,0,.45)] sm:p-5 xl:left-[9%] xl:w-[82%]">
            <div className="flex items-center justify-between border-b border-slate-200 pb-2.5">
              <div className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#e38c83]"/><span className="h-2 w-2 rounded-full bg-[#e7bd6f]"/><span className="h-2 w-2 rounded-full bg-[#79b88c]"/></div>
              <div className="hidden h-5 w-1/2 rounded-full bg-slate-100 sm:block" />
              <span className="rounded-md bg-blue-700 px-2 py-1 text-[9px] font-bold text-white">TrainerSync</span>
            </div>
            <div className="grid min-h-[170px] grid-cols-[1.1fr_.9fr] items-center gap-3 pt-3 sm:min-h-[220px] sm:gap-5 sm:pt-5">
              <div className="pl-1 sm:pl-3"><p className="text-[9px] font-bold uppercase tracking-[.18em] text-blue-700 sm:text-[11px]">{role === 'client' ? 'Training, thoughtfully matched' : 'People. Skills. Opportunity.'}</p><h2 className="mt-2 font-serif text-xl font-semibold leading-tight text-slate-950 sm:text-3xl xl:text-4xl">{role === 'client' ? 'Find the right person to move your team forward.' : 'A smarter space for your next chapter.'}</h2><p className="mt-2 max-w-xs text-[9px] leading-4 text-slate-500 sm:mt-3 sm:text-xs sm:leading-5">{selectedRole.features[0]}</p><div className="mt-3 inline-flex rounded-md bg-[#17213a] px-2.5 py-1.5 text-[9px] font-semibold text-white sm:mt-5 sm:px-3 sm:py-2 sm:text-[11px]">Explore your workspace</div></div>
              <div className="relative h-full min-h-[150px] overflow-hidden rounded-xl bg-slate-200 sm:min-h-[195px]"><img src="/images/office-girl.png" alt="" className="absolute inset-0 h-full w-full object-cover object-[center_22%]"/><div className="absolute inset-0 bg-gradient-to-t from-slate-950/35 to-transparent"/><div className="absolute bottom-2 left-2 rounded-full bg-white/90 px-2 py-1 text-[8px] font-semibold text-slate-700 sm:bottom-3 sm:left-3 sm:text-[10px]">{selectedRole.label} portal</div></div>
            </div>
          </div>
        </div>
      </div>

      {/* Right panel - form */}
      <div className="flex-1 flex items-center justify-center px-5 pb-8 pt-20 bg-[#f7f7f5] sm:px-8">
        <div className={clsx(
          'w-full max-w-[440px] transition-all duration-700',
          mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6'
        )}>
          {/* Mobile logo */}
          <div className="relative mb-5 h-36 overflow-hidden rounded-2xl bg-slate-900 lg:hidden"><img src="/images/office-girl.png" alt="" className="absolute inset-0 h-full w-full object-cover object-[center_20%]"/><div className="absolute inset-0 bg-gradient-to-r from-black/75 via-black/20 to-transparent"/><div className="absolute left-4 top-3"><BrandMark size="sm" theme="dark" /></div><div className="absolute bottom-3 left-4 right-4"><p className="text-[10px] font-bold uppercase tracking-[.17em] text-blue-100">TrainerSync / {selectedRole.label}</p><p className="mt-1 text-lg font-bold leading-tight text-white">{role === 'client' ? 'Find the right trainer for your team.' : role === 'trainer' ? 'Your expertise opens new doors.' : 'Training talent, better connected.'}</p></div></div>

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
          <div className="bg-white rounded-[24px] border border-slate-200/80 shadow-[0_24px_70px_-40px_rgba(15,23,42,.45)] p-6 space-y-4 sm:p-8">

            {/* Role selector */}
            <div>
              <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                {mode === 'login' ? 'Sign in as' : 'I am a'}
              </p>
              <div className="flex gap-2">
                {(mode === 'signup' ? signupOptions : roleOptions).map(r => {
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
            {allowSignup && role !== 'admin' && <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
              {['login', 'signup'].map(m => (
                <button key={m} type="button" onClick={() => { setMode(m); setStep(1) }}
                  className={clsx(
                    'flex-1 py-1.5 rounded-md text-sm font-semibold transition-all duration-200',
                    mode === m ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  )}>
                  {m === 'login' ? 'Sign In' : 'Sign Up'}
                </button>
              ))}
            </div>}

            {/* Social login */}
            {mode === 'login' && <div className="grid grid-cols-1 gap-2">
              <button
                type="button"
                onClick={handleGoogleButtonClick}
                disabled={!googleEnabled}
                className={clsx(
                  'flex w-full items-center justify-center gap-3 rounded-full border px-4 py-3 text-sm font-semibold shadow-sm transition',
                  googleEnabled
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

              {!googleReady && googleEnabled && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
                  <p className="font-semibold">Google login is not fully initialized yet.</p>
                  <p className="mt-1 text-xs text-amber-600">Click the button to continue with your Google account or use the email/password form.</p>
                </div>
              )}
            </div>}

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
                  {role === 'client'    && <Field icon={Building2} placeholder="Company / organization" value={form.company} onChange={set('company')} />}
                  {role === 'trainer'   && <Field icon={GraduationCap} placeholder="Domain (e.g. Python, AWS)" value={form.domain} onChange={set('domain')} required={false} />}
                </>
              )}

              {mode === 'signup' && step === 2 && (
                <>
                  <Field icon={Phone} type="tel" placeholder="Phone number" value={form.phone} onChange={set('phone')} required={role === 'client'} />
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
                className={`w-full py-2.5 rounded-2xl ${loginTheme.accent} font-bold text-sm text-white
                           flex items-center justify-center gap-2 transition-all duration-150
                           hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-60 disabled:cursor-not-allowed disabled:translate-y-0`}>
                {loading
                  ? <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  : <>
                      <Sparkles className="h-4 w-4" />
                      {mode === 'login' ? 'Sign In' : step === 1 ? 'Continue →' : 'Create Account'}
                    </>
                }
              </button>
            </form>

            {allowSignup && role !== 'admin' && <p className="text-center text-slate-500 text-xs">
              {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
              <button onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setStep(1) }}
                className="font-semibold text-blue-600 hover:text-blue-800">
                {mode === 'login' ? 'Sign up free' : 'Sign in'}
              </button>
            </p>}
            <div className="flex justify-center gap-4 border-t border-slate-100 pt-3 text-xs font-semibold">
              {role !== 'trainer' && <a className="text-blue-700 hover:underline" href="/trainer-login">Trainer login</a>}
              {role !== 'client' && <a className="text-emerald-700 hover:underline" href="/client-login">Client login</a>}
              {role !== 'admin' && <a className="text-slate-700 hover:underline" href="/admin-login">Administrator</a>}
            </div>
          </div>

          <p className="text-center text-slate-400 text-[11px] mt-4">
            Secured by TrainerSync · Clahan Technologies
          </p>
        </div>
      </div>
    </div>
  )
}
