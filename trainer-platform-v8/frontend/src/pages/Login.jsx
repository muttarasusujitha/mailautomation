import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { forgotPassword } from '../utils/api'
import {
  Mail, Lock, User, Eye, EyeOff, ArrowRight,
  CheckCircle, Sparkles, Chrome, Github, Briefcase,
  Users, GraduationCap, Building2, Phone
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { randomBetween, randomInt } from '../utils/random'
import BrandMark from '../components/BrandMark'

/* ─── Particle Canvas ──────────────────────────────────────── */
function ParticleCanvas() {
  const ref = useRef(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf
    const resize = () => {
      canvas.width  = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
    }
    resize()
    window.addEventListener('resize', resize)
    const colors = ['#3b82f6','#06b6d4','#10b981','#8b5cf6']
    const dots = Array.from({ length: 55 }, () => ({
      x: randomBetween(0, canvas.width),
      y: randomBetween(0, canvas.height),
      vx: randomBetween(-0.2, 0.2),
      vy: randomBetween(-0.2, 0.2),
      r: randomBetween(0.8, 2.8),
      pulse: randomBetween(0, Math.PI * 2),
      color: colors[randomInt(colors.length)],
    }))
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      dots.forEach(d => {
        d.x += d.vx; d.y += d.vy; d.pulse += 0.012
        if (d.x < 0 || d.x > canvas.width)  d.vx *= -1
        if (d.y < 0 || d.y > canvas.height) d.vy *= -1
        const r = d.r + Math.sin(d.pulse) * 0.4
        ctx.beginPath(); ctx.arc(d.x, d.y, r, 0, Math.PI*2)
        ctx.fillStyle = d.color + 'bb'; ctx.fill()
      })
      dots.forEach((a, i) => dots.slice(i+1).forEach(b => {
        const dist = Math.hypot(a.x-b.x, a.y-b.y)
        if (dist < 120) {
          ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y)
          ctx.strokeStyle = `rgba(59,130,246,${0.07*(1-dist/120)})`
          ctx.lineWidth = 0.6; ctx.stroke()
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
    id:       'recruiter',
    label:    'Recruiter',
    icon:     Briefcase,
    emoji:    '🎯',
    tagline:  'Find & hire the best trainers',
    desc:     'Manage requirements, shortlist trainers, send emails',
    gradient: 'from-blue-500 to-cyan-500',
    bg:       'bg-blue-50',
    border:   'border-blue-300',
    ring:     'ring-blue-400',
    text:     'text-blue-700',
    badge:    'bg-blue-100 text-blue-700',
    extra:    ['company', 'phone'],
  },
  {
    id:       'trainer',
    label:    'Trainer',
    icon:     GraduationCap,
    emoji:    '🧑‍🏫',
    tagline:  'Get matched to training opportunities',
    desc:     'Receive requirements, manage availability, get hired',
    gradient: 'from-emerald-500 to-teal-500',
    bg:       'bg-emerald-50',
    border:   'border-emerald-300',
    ring:     'ring-emerald-400',
    text:     'text-emerald-700',
    badge:    'bg-emerald-100 text-emerald-700',
    extra:    ['phone', 'domain'],
  },
  {
    id:       'employee',
    label:    'Employee',
    icon:     Building2,
    emoji:    '👔',
    tagline:  'Track your team\'s training progress',
    desc:     'View schedules, access training materials, manage teams',
    gradient: 'from-violet-500 to-purple-500',
    bg:       'bg-violet-50',
    border:   'border-violet-300',
    ring:     'ring-violet-400',
    text:     'text-violet-700',
    badge:    'bg-violet-100 text-violet-700',
    extra:    ['company', 'department'],
  },
]

/* ─── Role Selector Card ───────────────────────────────────── */
function RoleCard({ role, selected, onClick }) {
  const Icon = role.icon
  return (
    <button type="button" onClick={onClick}
      className={clsx(
        'relative flex-1 flex flex-col items-center gap-1.5 p-3 rounded-2xl border-2 transition-all duration-300 group overflow-hidden',
        selected
          ? `${role.border} ${role.bg} shadow-lg scale-[1.03]`
          : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-md hover:scale-[1.01]'
      )}>
      {/* Glow bg on selected */}
      {selected && (
        <div className={clsx('absolute inset-0 opacity-10 bg-gradient-to-br', role.gradient)} />
      )}
      {/* Icon */}
      <div className={clsx(
        'relative w-10 h-10 rounded-2xl flex items-center justify-center transition-all duration-300',
        selected
          ? `bg-gradient-to-br ${role.gradient} shadow-lg shadow-${role.id === 'recruiter' ? 'blue' : role.id === 'trainer' ? 'emerald' : 'violet'}-300`
          : 'bg-slate-100 group-hover:bg-slate-200'
      )}>
        <Icon className={clsx('w-5 h-5 transition-colors', selected ? 'text-white' : 'text-slate-500')} />
        {selected && (
          <div className="absolute -top-1 -right-1 w-4 h-4 bg-white rounded-full flex items-center justify-center shadow">
            <CheckCircle className={clsx('w-3 h-3', role.text)} />
          </div>
        )}
      </div>
      <span className={clsx('text-xs font-bold transition-colors', selected ? role.text : 'text-slate-600')}>
        {role.label}
      </span>
      <span className="text-[10px] text-slate-400 text-center leading-tight hidden sm:block">
        {role.tagline}
      </span>
    </button>
  )
}

/* ─── Input Field ──────────────────────────────────────────── */
function Field({ icon: Icon, type = 'text', placeholder, value, onChange, right, required = true }) {
  return (
    <div className="relative group">
      <Icon className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
      <input type={type} placeholder={placeholder} value={value} onChange={onChange} required={required}
        className="w-full bg-white border border-slate-200 rounded-xl pl-10 pr-10 py-2.5 text-slate-800 text-sm
                   placeholder-slate-400 focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100
                   hover:border-slate-300 transition-all duration-200 shadow-sm" />
      {right && <div className="absolute right-3.5 top-1/2 -translate-y-1/2">{right}</div>}
    </div>
  )
}

/* ─── Main Component ───────────────────────────────────────── */
export default function Login({ onLogin }) {
  const [mode, setMode]         = useState('login')   // 'login' | 'signup'
  const [role, setRole]         = useState('recruiter')
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading]   = useState(false)
  const [resetting, setResetting] = useState(false)
  const [mounted, setMounted]   = useState(false)
  const [remember, setRemember] = useState(false)
  const [step, setStep]         = useState(1)         // signup step 1 or 2
  const navigate = useNavigate()

  const [form, setForm] = useState({
    name: '', email: '', password: '', confirm: '',
    phone: '', company: '', domain: '', department: '',
  })
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  useEffect(() => { setTimeout(() => setMounted(true), 60) }, [])

  const selectedRole = ROLES.find(r => r.id === role)

  const handleForgotPassword = async () => {
    const email = form.email.trim()
    if (!email) {
      toast.error('Enter your email address first')
      return
    }

    setResetting(true)
    try {
      await forgotPassword(email)
      toast.success(`Reset email sent to ${email}`)
    } catch (e) {
      toast.error(e.message || 'Could not send reset email')
    } finally {
      setResetting(false)
    }
  }

  const handleSubmit = async e => {
    e.preventDefault()
    if (mode === 'signup' && step === 1) { setStep(2); return }
    if (mode === 'signup' && form.password !== form.confirm) {
      toast.error('Passwords do not match'); return
    }
    setLoading(true)
    await new Promise(r => setTimeout(r, 1300))
    localStorage.setItem('ts_auth', JSON.stringify({
      name:     form.name || 'User',
      email:    form.email,
      role:     role,
      loggedIn: true,
    }))
    toast.success(mode === 'login'
      ? `👋 Welcome back, ${role}!`
      : `🎉 Account created as ${selectedRole.label}!`)
    setLoading(false)
    if (onLogin) onLogin()
    navigate('/dashboard')
  }

  return (
    <div className="min-h-screen flex overflow-hidden relative bg-gradient-to-br from-slate-50 via-white to-blue-50">

      <style>{`
        @keyframes float-slow   { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-12px)} }
        @keyframes float-medium { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-8px)} }
        @keyframes slideUp   { from{opacity:0;transform:translateY(20px)} to{opacity:1;transform:translateY(0)} }
        @keyframes slideLeft { from{opacity:0;transform:translateX(-20px)} to{opacity:1;transform:translateX(0)} }
        @keyframes slideRight{ from{opacity:0;transform:translateX(20px)} to{opacity:1;transform:translateX(0)} }
        @keyframes ping-slow { 0%{transform:scale(1);opacity:.6} 100%{transform:scale(2);opacity:0} }
        .anim-up    { animation: slideUp   0.6s ease forwards; }
        .anim-left  { animation: slideLeft 0.6s ease forwards; }
        .anim-right { animation: slideRight 0.6s ease forwards; }
        .float-slow   { animation: float-slow   4s ease-in-out infinite; }
        .float-medium { animation: float-medium 3s ease-in-out infinite; }
        .ping-slow    { animation: ping-slow 2.5s ease-out infinite; }
      `}</style>

      {/* ── Floating shapes ──────────────────────────────────── */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
        <div className="absolute top-16 left-12 w-32 h-32 bg-gradient-to-br from-blue-100 to-cyan-100 rounded-full opacity-50 float-slow" />
        <div className="absolute top-1/3 right-16 w-20 h-20 bg-gradient-to-br from-violet-100 to-pink-100 rounded-xl rotate-12 opacity-40 float-medium" />
        <div className="absolute bottom-32 left-1/4 w-24 h-24 bg-gradient-to-br from-emerald-100 to-teal-100 rounded-full opacity-35 float-slow" />
        <div className="absolute bottom-16 right-1/3 w-16 h-16 bg-gradient-to-br from-amber-100 to-orange-100 rounded-xl opacity-40 float-medium" />
      </div>

      {/* ── LEFT PANEL ───────────────────────────────────────── */}
      <div className={clsx(
        'hidden lg:flex flex-col w-[48%] relative overflow-hidden transition-all duration-700',
        mounted ? 'opacity-100' : 'opacity-0'
      )}>
        {/* Gradient bg */}
        <div className={clsx('absolute inset-0 bg-gradient-to-br transition-all duration-700',
          role === 'recruiter' ? 'from-blue-600 via-blue-700 to-indigo-800' :
          role === 'trainer'   ? 'from-emerald-600 via-teal-600 to-cyan-800' :
          'from-violet-600 via-purple-700 to-indigo-800'
        )} />
        <div className="absolute inset-0 bg-gradient-to-t from-black/30 to-transparent" />
        <ParticleCanvas />

        {/* Glow orbs */}
        <div className="absolute top-20 right-20 w-72 h-72 bg-white/10 rounded-full blur-3xl" />
        <div className="absolute bottom-20 left-16 w-56 h-56 bg-white/8 rounded-full blur-3xl" />

        {/* Content */}
        <div className="relative z-10 flex flex-col h-full p-12">
          {/* Logo */}
          <BrandMark size="lg" theme="dark" className="anim-left" />

          {/* Role showcase */}
          <div className="flex-1 flex flex-col justify-center space-y-8">
            {/* Active role spotlight */}
            <div className="anim-left" style={{ animationDelay: '0.1s' }}>
              <div className="inline-flex items-center gap-2 bg-white/15 border border-white/20 rounded-full px-3 py-1.5 mb-5">
                <span className="text-lg">{selectedRole.emoji}</span>
                <span className="text-white text-sm font-semibold">For {selectedRole.label}s</span>
              </div>
              <h1 className="text-5xl font-bold text-white leading-tight">
                {role === 'recruiter' && <>Find the right<br /><span className="text-cyan-300">trainer, fast.</span></>}
                {role === 'trainer'   && <>Get matched to<br /><span className="text-emerald-300">opportunities.</span></>}
                {role === 'employee'  && <>Track your team's<br /><span className="text-violet-300">training journey.</span></>}
              </h1>
              <p className="text-white/80 text-lg mt-4 leading-relaxed max-w-sm">
                {selectedRole.desc}
              </p>
            </div>

            {/* Role features */}
            <ul className="space-y-3">
              {(role === 'recruiter' ? [
                'AI-powered trainer matching in seconds',
                'Automated 7-stage email pipeline',
                'Reply tracking & shortlist management',
                'Interview scheduling with Zoom/Teams/Meet',
              ] : role === 'trainer' ? [
                'Get matched to relevant training requirements',
                'Receive structured requirement details',
                'Schedule interviews at your convenience',
                'Manage your availability and profile',
              ] : [
                'View your team\'s training schedule',
                'Access training materials & resources',
                'Track completion and progress metrics',
                'Communicate with assigned trainers',
              ]).map((f, i) => (
                <li key={i} className={clsx('flex items-center gap-3 text-white/90 anim-left')}
                  style={{ animationDelay: `${0.2 + i * 0.07}s` }}>
                  <div className="w-6 h-6 bg-white/20 rounded-lg flex items-center justify-center flex-shrink-0">
                    <CheckCircle className="w-3.5 h-3.5 text-white" />
                  </div>
                  <span className="text-sm">{f}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Stats */}
          <div className="flex gap-8 pt-6 border-t border-white/15 anim-left" style={{ animationDelay: '0.5s' }}>
            {[['500+','Trainers'],['98%','Match Rate'],['3x','Faster']].map(([v,l]) => (
              <div key={l}>
                <p className="text-2xl font-bold text-white">{v}</p>
                <p className="text-xs text-white/60 mt-0.5">{l}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── RIGHT PANEL — Form ────────────────────────────────── */}
      <div className="flex-1 flex items-center justify-center px-6 py-4 relative z-10 bg-white/50 backdrop-blur-sm">
        <div className={clsx(
          'w-full max-w-[470px] transition-all duration-700',
          mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'
        )}>

          {/* Mobile logo */}
          <BrandMark className="mb-6 lg:hidden" />

          {/* Heading */}
          <div className="mb-3">
            <h2 className="text-xl font-bold text-slate-900">
              {mode === 'login' ? 'Welcome back 👋' : step === 1 ? 'Create account ✨' : 'Almost done! 🚀'}
            </h2>
            <p className="text-slate-500 text-xs mt-1">
              {mode === 'login' ? 'Sign in to TrainerSync' :
               step === 1 ? 'Choose your role & details' : 'Set up your profile'}
            </p>
          </div>

          {/* Card */}
          <div className="bg-white rounded-3xl border border-slate-200 shadow-xl px-6 py-5 space-y-4">

            {/* Role selector — show always */}
            <div>
              <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
                {mode === 'login' ? 'Sign in as' : 'I am a'}
              </p>
              <div className="flex gap-2">
                {ROLES.map(r => (
                  <RoleCard key={r.id} role={r} selected={role === r.id} onClick={() => { setRole(r.id); setStep(1) }} />
                ))}
              </div>
            </div>

            {/* Role badge */}
            <div className={clsx('flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold', selectedRole.badge)}>
              <selectedRole.icon className="w-3.5 h-3.5" />
              {selectedRole.label} — {selectedRole.tagline}
            </div>

            {/* Sign In / Sign Up tabs */}
            <div className="flex bg-slate-100 rounded-xl p-1 gap-1">
              {['login','signup'].map(m => (
                <button key={m} type="button" onClick={() => { setMode(m); setStep(1) }}
                  className={clsx(
                    'flex-1 py-1.5 rounded-lg text-sm font-semibold transition-all duration-200',
                    mode === m
                      ? `bg-gradient-to-r ${selectedRole.gradient} text-white shadow-md`
                      : 'text-slate-500 hover:text-slate-700'
                  )}>
                  {m === 'login' ? 'Sign In' : 'Sign Up'}
                </button>
              ))}
            </div>

            {/* Social */}
            <div className="grid grid-cols-2 gap-2">
              {[{icon: Chrome, label:'Google'},{icon: Github, label:'GitHub'}].map(s => (
                <button key={s.label} type="button" onClick={() => toast('Social login coming soon!')}
                  className="flex items-center justify-center gap-2 py-2 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-xl text-slate-600 text-xs font-semibold transition-all hover:shadow-sm">
                  <s.icon className="w-4 h-4" />{s.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-slate-200" />
              <span className="text-xs text-slate-400">or email</span>
              <div className="flex-1 h-px bg-slate-200" />
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-2.5">

              {/* SIGN IN FORM */}
              {mode === 'login' && (
                <>
                  <Field icon={Mail} type="email" placeholder="Email address" value={form.email} onChange={set('email')} />
                  <Field icon={Lock} type={showPass ? 'text' : 'password'} placeholder="Password"
                    value={form.password} onChange={set('password')}
                    right={
                      <button type="button" onClick={() => setShowPass(!showPass)} className="text-slate-400 hover:text-slate-600">
                        {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    } />
                  <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={remember}
                        onChange={() => setRemember(!remember)}
                        className="sr-only"
                      />
                      <div
                        aria-hidden="true"
                        className={clsx('w-4 h-4 rounded border flex items-center justify-center transition-all',
                          remember ? `bg-gradient-to-br ${selectedRole.gradient} border-transparent` : 'border-slate-300'
                        )}>
                        {remember && <CheckCircle className="w-3 h-3 text-white" />}
                      </div>
                      <span className="text-xs text-slate-500">Remember me</span>
                    </label>
                    <button type="button" onClick={handleForgotPassword} disabled={resetting}
                      className="text-xs text-blue-500 hover:text-blue-700 font-medium disabled:opacity-60">
                      {resetting ? 'Sending...' : 'Forgot password?'}
                    </button>
                  </div>
                </>
              )}

              {/* SIGN UP STEP 1 */}
              {mode === 'signup' && step === 1 && (
                <>
                  <Field icon={User} type="text" placeholder="Full name" value={form.name} onChange={set('name')} />
                  <Field icon={Mail} type="email" placeholder="Email address" value={form.email} onChange={set('email')} />
                  {/* Role-specific step-1 field */}
                  {role === 'recruiter' && (
                    <Field icon={Building2} type="text" placeholder="Company name" value={form.company} onChange={set('company')} required={false} />
                  )}
                  {role === 'trainer' && (
                    <Field icon={GraduationCap} type="text" placeholder="Domain / Technology (e.g. Python, AWS)" value={form.domain} onChange={set('domain')} required={false} />
                  )}
                  {role === 'employee' && (
                    <Field icon={Building2} type="text" placeholder="Company / Organization" value={form.company} onChange={set('company')} required={false} />
                  )}
                </>
              )}

              {/* SIGN UP STEP 2 */}
              {mode === 'signup' && step === 2 && (
                <>
                  <Field icon={Phone} type="tel" placeholder="Phone number" value={form.phone} onChange={set('phone')} required={false} />
                  {role === 'employee' && (
                    <Field icon={Users} type="text" placeholder="Department (e.g. Engineering)" value={form.department} onChange={set('department')} required={false} />
                  )}
                  <Field icon={Lock} type={showPass ? 'text' : 'password'} placeholder="Create password"
                    value={form.password} onChange={set('password')}
                    right={<button type="button" onClick={() => setShowPass(!showPass)} className="text-slate-400 hover:text-slate-600">{showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}</button>} />
                  <Field icon={Lock} type={showPass ? 'text' : 'password'} placeholder="Confirm password" value={form.confirm} onChange={set('confirm')} />
                </>
              )}

              {/* Step indicator for signup */}
              {mode === 'signup' && (
                <div className="flex items-center gap-2 py-1">
                  {[1,2].map(s => (
                    <div key={s} className={clsx('h-1.5 rounded-full transition-all duration-300',
                      s === step
                        ? `flex-1 bg-gradient-to-r ${selectedRole.gradient}`
                        : s < step ? 'flex-1 bg-slate-300' : 'w-6 bg-slate-200'
                    )} />
                  ))}
                  <span className="text-xs text-slate-400 ml-1">Step {step}/2</span>
                </div>
              )}

              {/* Back button for step 2 */}
              {mode === 'signup' && step === 2 && (
                <button type="button" onClick={() => setStep(1)}
                  className="w-full py-2 rounded-xl border border-slate-200 text-slate-600 text-sm font-medium hover:bg-slate-50 transition-all">
                  ← Back
                </button>
              )}

              {/* Submit */}
              <button type="submit" disabled={loading}
                  className={clsx(
                  'w-full py-2.5 rounded-xl font-bold text-sm text-white flex items-center justify-center gap-2',
                  'transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg active:scale-[0.98]',
                  'disabled:opacity-60 disabled:cursor-not-allowed',
                  `bg-gradient-to-r ${selectedRole.gradient}`
                )}>
                {loading
                  ? <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  : <>
                      <Sparkles className="w-4 h-4" />
                      {mode === 'login' ? `Sign In as ${selectedRole.label}` :
                       step === 1 ? 'Continue →' : `Create ${selectedRole.label} Account`}
                      {mode === 'login' && <ArrowRight className="w-4 h-4" />}
                    </>
                }
              </button>
            </form>

            <p className="text-center text-slate-500 text-xs">
              {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
              <button onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setStep(1) }}
                className={clsx('font-semibold transition-colors', selectedRole.text)}>
                {mode === 'login' ? 'Sign up free' : 'Sign in'}
              </button>
            </p>
          </div>

          <p className="text-center text-slate-400 text-[10px] mt-4">
            Secured by TrainerSync · Your data is protected
          </p>
        </div>
      </div>
    </div>
  )
}
