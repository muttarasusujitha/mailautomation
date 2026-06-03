import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Mail, Phone, Send, MessageSquare, Clock,
  CheckCircle, ArrowRight, Zap, Sparkles,
  Linkedin, Twitter, Instagram
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { randomBetween, randomInt } from '../utils/random'
import PublicFooter from '../components/PublicFooter'
import BrandMark from '../components/BrandMark'

/* ── Keyframes ─────────────────────────────────────────── */
const STYLES = `
@keyframes morphBg1{0%,100%{border-radius:60% 40% 70% 30%/50% 60% 40% 50%;transform:translate(0,0) scale(1)}33%{border-radius:40% 60% 30% 70%/70% 30% 60% 40%;transform:translate(18px,-12px) scale(1.04)}66%{border-radius:70% 30% 50% 50%/30% 70% 50% 50%;transform:translate(-8px,16px) scale(0.97)}}
@keyframes morphBg2{0%,100%{border-radius:40% 60% 30% 70%/60% 40% 70% 30%}50%{border-radius:60% 40% 70% 30%/40% 60% 30% 70%;transform:translate(-16px,12px)}}
@keyframes floatY{0%,100%{transform:translateY(0)}50%{transform:translateY(-18px)}}
@keyframes floatBadge1{0%,100%{transform:translateY(0) rotate(-1.5deg)}50%{transform:translateY(-10px) rotate(1deg)}}
@keyframes floatBadge2{0%,100%{transform:translateY(0) rotate(1deg)}50%{transform:translateY(-14px) rotate(-1deg)}}
@keyframes floatBadge3{0%,100%{transform:translateY(-6px)}50%{transform:translateY(6px)}}
@keyframes floatBadge4{0%,100%{transform:translateY(0) rotate(1deg)}50%{transform:translateY(-8px) rotate(-0.5deg)}}
@keyframes slideLeft{from{opacity:0;transform:translateX(-40px)}to{opacity:1;transform:translateX(0)}}
@keyframes slideRight{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:translateX(0)}}
@keyframes slideUp{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:translateY(0)}}
@keyframes ping2{0%{transform:scale(1);opacity:0.8}100%{transform:scale(2.2);opacity:0}}
@keyframes rotate360{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
@keyframes dash{to{stroke-dashoffset:0}}
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
@keyframes glowPulse{0%,100%{box-shadow:0 0 20px rgba(37,99,235,0.2)}50%{box-shadow:0 0 40px rgba(37,99,235,0.4),0 0 60px rgba(6,182,212,0.2)}}
.ani-left{animation:slideLeft 0.7s cubic-bezier(.22,1,.36,1) both}
.ani-right{animation:slideRight 0.7s cubic-bezier(.22,1,.36,1) both}
.ani-up{animation:slideUp 0.6s cubic-bezier(.22,1,.36,1) both}
.fb1{animation:floatBadge1 5s ease-in-out infinite}
.fb2{animation:floatBadge2 6s ease-in-out infinite}
.fb3{animation:floatBadge3 4s ease-in-out infinite}
.fb4{animation:floatBadge4 5.5s ease-in-out infinite}
.glow{animation:glowPulse 3s ease-in-out infinite}
`

/* ── Particle Canvas ───────────────────────────────────── */
// eslint-disable-next-line no-unused-vars
function ParticleCanvas() {
  const ref = useRef(null)
  useEffect(() => {
    const canvas = ref.current; if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf
    const resize = () => { canvas.width = canvas.offsetWidth; canvas.height = canvas.offsetHeight }
    resize(); window.addEventListener('resize', resize)
    const colors = ['#3b82f6','#06b6d4','#10b981','#8b5cf6']
    const dots = Array.from({ length: 40 }, () => ({
      x: randomBetween(0, canvas.width), y: randomBetween(0, canvas.height),
      vx: randomBetween(-0.15, 0.15), vy: randomBetween(-0.15, 0.15),
      r: randomBetween(0.5, 2.5), pulse: randomBetween(0, Math.PI*2),
      color: colors[randomInt(colors.length)],
    }))
    const draw = () => {
      ctx.clearRect(0,0,canvas.width,canvas.height)
      dots.forEach(d => {
        d.x+=d.vx; d.y+=d.vy; d.pulse+=.012
        if(d.x<0||d.x>canvas.width) d.vx*=-1
        if(d.y<0||d.y>canvas.height) d.vy*=-1
        ctx.beginPath(); ctx.arc(d.x,d.y,d.r+Math.sin(d.pulse)*.3,0,Math.PI*2)
        ctx.fillStyle=d.color+'99'; ctx.fill()
      })
      dots.forEach((a,i)=>dots.slice(i+1).forEach(b=>{
        const dist=Math.hypot(a.x-b.x,a.y-b.y)
        if(dist<100){ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y)
          ctx.strokeStyle=`rgba(59,130,246,${.07*(1-dist/100)})`;ctx.lineWidth=.5;ctx.stroke()}
      }))
      raf=requestAnimationFrame(draw)
    }
    draw()
    return ()=>{cancelAnimationFrame(raf);window.removeEventListener('resize',resize)}
  },[])
  return <canvas ref={ref} className="absolute inset-0 w-full h-full pointer-events-none z-0"/>
}

/* ── Badge component ───────────────────────────────────── */
function Badge({ children, className, style }) {
  return (
    <div className={clsx(
      'absolute z-30 bg-white/95 backdrop-blur-sm rounded-2xl border border-slate-100',
      'flex items-center gap-2.5 px-3.5 py-2.5',
      className
    )} style={{ boxShadow:'0 8px 30px rgba(0,0,0,0.10)', ...style }}>
      {children}
    </div>
  )
}

/* ── Animated photo section ────────────────────────────── */
function PhotoSection() {
  return (
    <div className="relative flex items-center justify-center ani-right" style={{ animationDelay:'.15s', minHeight:580 }}>
      <style>{STYLES}</style>

      {/* Morphing background blobs */}
      <div style={{ position:'absolute', top:'0%', left:'0%', width:380, height:380,
        background:'linear-gradient(135deg,rgba(37,99,235,0.10),rgba(6,182,212,0.07))',
        animation:'morphBg1 10s ease-in-out infinite', pointerEvents:'none', zIndex:0 }}/>
      <div style={{ position:'absolute', bottom:'0%', right:'0%', width:320, height:320,
        background:'linear-gradient(135deg,rgba(16,185,129,0.08),rgba(139,92,246,0.06))',
        animation:'morphBg2 12s ease-in-out infinite', pointerEvents:'none', zIndex:0 }}/>
      <div style={{ position:'absolute', top:'50%', right:'5%', width:180, height:180,
        borderRadius:'50%', background:'rgba(245,158,11,0.06)',
        animation:'floatY 7s ease-in-out infinite', pointerEvents:'none', zIndex:0 }}/>

      {/* Rotating ring */}
      <div style={{ position:'absolute', width:440, height:440, borderRadius:'50%',
        border:'1.5px dashed rgba(37,99,235,0.15)',
        animation:'rotate360 18s linear infinite', pointerEvents:'none', zIndex:1 }}/>
      <div style={{ position:'absolute', width:360, height:360, borderRadius:'50%',
        border:'1px dashed rgba(16,185,129,0.12)',
        animation:'rotate360 12s linear infinite reverse', pointerEvents:'none', zIndex:1 }}/>

      {/* Glow circle behind photo */}
      <div className="glow" style={{ position:'absolute', width:340, height:340, borderRadius:'50%',
        background:'radial-gradient(circle,rgba(37,99,235,0.15),transparent 70%)',
        filter:'blur(20px)', zIndex:1, pointerEvents:'none' }}/>

      {/* Photo card — BIGGER */}
      <div className="relative z-10 rounded-3xl overflow-hidden"
        style={{ width:340, height:460, border:'3px solid rgba(255,255,255,0.95)',
          boxShadow:'0 25px 60px rgba(37,99,235,0.18)',
          background:'linear-gradient(160deg,#e0eaff 0%,#f0f9ff 60%,#e8f5e9 100%)' }}>
        <img src="/images/boy.png" alt="TrainerSync Support"
          style={{ width:'100%', height:'120%', objectFit:'cover', objectPosition:'center top',
            marginTop:-15, filter:'brightness(1.05) contrast(1.05) saturate(1.1)', 
            clipPath:'polygon(0 0, 100% 0, 100% 85%, 90% 100%, 0 100%)' }}/>
        {/* Bottom gradient overlay */}
        <div style={{ position:'absolute', bottom:0, left:0, right:0, height:80,
          background:'linear-gradient(to top,rgba(37,99,235,0.15),transparent)' }}/>
      </div>

      {/* ── Badge 1 — Trusted (top left) ── */}
      <Badge className="fb1" style={{ top:'8%', left:'0%' }}>
        <div style={{ width:34, height:34, borderRadius:10, background:'#d1fae5',
          display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
          <CheckCircle style={{ width:18, height:18, color:'#10b981' }}/>
        </div>
        <div>
          <p style={{ fontSize:10, color:'#94a3b8', marginBottom:1 }}>Trusted</p>
          <p style={{ fontSize:12, fontWeight:700, color:'#0f172a', whiteSpace:'nowrap' }}>Feedback verified</p>
        </div>
      </Badge>

      {/* ── Badge 2 — Rating (top right) ── */}
      <Badge className="fb2" style={{ top:'8%', right:'0%' }}>
        <div style={{ width:36, height:36, borderRadius:10,
          background:'linear-gradient(135deg,#2563eb,#06b6d4)',
          display:'flex', flexDirection:'column', alignItems:'center',
          justifyContent:'center', flexShrink:0 }}>
          <span style={{ fontSize:14 }}>⭐</span>
        </div>
        <div>
          <p style={{ fontSize:10, color:'#94a3b8', marginBottom:1 }}>Platform rating</p>
          <p style={{ fontSize:13, fontWeight:700, color:'#0f172a' }}>4.8 / 5.0</p>
          <p style={{ fontSize:10, color:'#f59e0b', letterSpacing:1 }}>★★★★★</p>
        </div>
      </Badge>

      {/* ── Badge 3 — Reviews (bottom left) ── */}
      <Badge className="fb3" style={{ bottom:'10%', left:'0%' }}>
        <div style={{ width:34, height:34, borderRadius:10, background:'#eff6ff',
          display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
          <MessageSquare style={{ width:16, height:16, color:'#2563eb' }}/>
        </div>
        <div>
          <p style={{ fontSize:10, color:'#94a3b8', marginBottom:1 }}>128 reviews</p>
          <p style={{ fontSize:12, fontWeight:700, color:'#0f172a' }}>Real verified</p>
        </div>
      </Badge>

      {/* ── Badge 4 — Recommend (top right shoulder) ── */}
      <Badge className="fb4" style={{ top:'28%', right:'0%' }}>
        <div style={{ width:34, height:34, borderRadius:'50%', background:'#d1fae5',
          display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0,
          fontSize:11, fontWeight:800, color:'#059669' }}>
          96%
        </div>
        <div>
          <p style={{ fontSize:10, color:'#94a3b8', marginBottom:1 }}>Recommend</p>
          <p style={{ fontSize:12, fontWeight:700, color:'#0f172a' }}>by users</p>
        </div>
      </Badge>

    </div>
  )
}

/* ── Counter ───────────────────────────────────────────── */
function Counter({ target, suffix='' }) {
  const [count, setCount] = useState(0)
  const ref = useRef(null)
  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) {
        let s=0; const step=target/(1400/16)
        const t=setInterval(()=>{ s=Math.min(s+step,target); setCount(Math.floor(s)); if(s>=target)clearInterval(t) },16)
      }
    },{ threshold:.5 })
    if(ref.current) obs.observe(ref.current)
    return ()=>obs.disconnect()
  },[target])
  return <span ref={ref}>{count}{suffix}</span>
}

/* ── Stat box ──────────────────────────────────────────── */
function StatBox({ icon:Icon, value, suffix, label, color, delay }) {
  return (
    <div className="bg-white rounded-2xl p-5 shadow-md border border-slate-100 text-center hover:shadow-xl hover:-translate-y-1.5 transition-all duration-300 group ani-up"
      style={{ animationDelay: delay }}>
      <div className={clsx('w-12 h-12 rounded-xl flex items-center justify-center mx-auto mb-3 group-hover:scale-110 transition-transform duration-300', color)}>
        <Icon className="w-6 h-6 text-white"/>
      </div>
      <div className="text-2xl font-bold text-slate-900 mb-1"><Counter target={value} suffix={suffix}/></div>
      <p className="text-xs text-slate-500 font-medium">{label}</p>
    </div>
  )
}

/* ── Contact form ──────────────────────────────────────── */
// eslint-disable-next-line no-unused-vars
function ContactForm() {
  const [form, setForm] = useState({ name:'', email:'', phone:'', subject:'', message:'' })
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const set = k => e => setForm(f=>({...f,[k]:e.target.value}))

  const handleSubmit = async e => {
    e.preventDefault(); setLoading(true)
    await new Promise(r=>setTimeout(r,1400))
    setLoading(false); setSent(true)
    toast.success("Message sent! We'll reply within 2 hours.")
  }

  const inp = `w-full px-4 py-3 rounded-xl bg-slate-50 border border-slate-200
    focus:outline-none focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100
    text-slate-800 placeholder-slate-400 text-sm transition-all duration-200`

  if (sent) return (
    <div className="flex flex-col items-center justify-center py-14 text-center space-y-4">
      <div className="w-20 h-20 rounded-full flex items-center justify-center shadow-xl"
        style={{ background:'linear-gradient(135deg,#10b981,#059669)' }}>
        <CheckCircle className="w-10 h-10 text-white"/>
      </div>
      <h3 className="text-2xl font-bold text-slate-900">Message Sent! 🎉</h3>
      <p className="text-slate-500 max-w-xs text-sm">We'll get back within 2 hours.</p>
      <button onClick={()=>setSent(false)}
        className="px-6 py-2.5 rounded-xl font-semibold text-sm text-white transition-all hover:scale-105"
        style={{ background:'linear-gradient(90deg,#2563eb,#06b6d4)' }}>
        Send Another
      </button>
    </div>
  )

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1.5">Full Name *</label>
          <input className={inp} placeholder="Your name" required value={form.name} onChange={set('name')}/>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1.5">Email Address *</label>
          <input type="email" className={inp} placeholder="you@company.com" required value={form.email} onChange={set('email')}/>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1.5">Phone Number</label>
          <input className={inp} placeholder="+91 98765 43210" value={form.phone} onChange={set('phone')}/>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1.5">Subject *</label>
          <select className={inp} required value={form.subject} onChange={set('subject')}>
            <option value="">Select topic</option>
            <option>Trainer Matching</option>
            <option>Email Outreach</option>
            <option>Technical Support</option>
            <option>Pricing & Plans</option>
            <option>Other</option>
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs font-semibold text-slate-600 mb-1.5">Message *</label>
        <textarea className={clsx(inp,'resize-none')} rows={5}
          placeholder="Tell us what you need — we respond within 2 hours..."
          required value={form.message} onChange={set('message')}/>
      </div>
      <button type="submit" disabled={loading}
        className="w-full py-3.5 rounded-xl font-bold text-sm flex items-center justify-center gap-2 text-white transition-all duration-200 hover:scale-[1.02] hover:shadow-lg active:scale-[0.98] disabled:opacity-60"
        style={{ background:'linear-gradient(90deg,#2563eb,#06b6d4)', boxShadow:'0 4px 20px rgba(37,99,235,0.25)' }}>
        {loading
          ? <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>
          : <><Send className="w-4 h-4"/> Send Message <ArrowRight className="w-4 h-4"/></>}
      </button>
      <p className="text-center text-xs text-slate-400">
        We reply within <strong className="text-blue-500">2 hours</strong> · Mon–Sat 9AM–7PM IST
      </p>
    </form>
  )
}

/* ── Main ──────────────────────────────────────────────── */
export default function Contact() {
  const navigate = useNavigate()
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setTimeout(() => setMounted(true), 60) }, [])

  const stats = [
    { icon:Clock,         value:2,   suffix:'hr', label:'Avg Reply Time',    color:'bg-gradient-to-br from-blue-500 to-cyan-500',    delay:'0s'   },
    { icon:CheckCircle,   value:98,  suffix:'%',  label:'Satisfaction Rate', color:'bg-gradient-to-br from-green-500 to-emerald-500', delay:'.1s'  },
    { icon:MessageSquare, value:500, suffix:'+',  label:'Trainers Listed',   color:'bg-gradient-to-br from-purple-500 to-pink-500',   delay:'.2s'  },
    { icon:Sparkles,      value:3,   suffix:'x',  label:'Faster Hiring',     color:'bg-gradient-to-br from-orange-500 to-red-500',    delay:'.3s'  },
  ]

  return (
    <div className="min-h-screen relative overflow-hidden"
      style={{ background:'linear-gradient(135deg,#f0f9ff 0%,#ffffff 50%,#f0fdf4 100%)' }}>

      {/* Nav — Logo on left edge, Buttons on right edge */}
      <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-8 py-5">
        <BrandMark size="sm" onClick={() => navigate('/dashboard')} />
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/feedback')} className="text-sm text-slate-600 hover:text-blue-600 transition-colors px-3 py-2">Reviews</button>
          <button onClick={() => navigate('/login')}
            className="text-white px-5 py-2.5 rounded-xl text-sm font-semibold hover:shadow-lg transition-all duration-300 hover:scale-105"
            style={{ background:'linear-gradient(90deg,#2563eb,#06b6d4)' }}>
            Get Started
          </button>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative z-10 max-w-7xl mx-auto px-8 pt-24 pb-6 grid lg:grid-cols-2 gap-12 items-center">

        {/* Left */}
        <div className={clsx('space-y-6 transition-all duration-700 ani-left', mounted && 'opacity-100')}
          style={{ animationDelay:'.05s' }}>

          <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 border border-blue-200"
            style={{ background:'rgba(239,246,255,0.8)' }}>
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"
                style={{ animation:'ping2 1.2s cubic-bezier(0,0,0.2,1) infinite' }}/>
              <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500"/>
            </span>
            <span className="text-blue-700 text-sm font-semibold">We're online — reply in ~2 hrs</span>
          </div>

          <h1 style={{ fontFamily:"'Sora',sans-serif", fontSize:'clamp(2rem,4vw,3.2rem)', fontWeight:800, lineHeight:1.15, color:'#0f172a' }}>
            Let's Build Your<br/>
            <span style={{ background:'linear-gradient(90deg,#2563eb,#06b6d4)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>
              Dream Team
            </span>
          </h1>

          <p className="text-slate-500 text-lg leading-relaxed max-w-lg">
            Have a training requirement? We <strong className="text-slate-700">match</strong>, <strong className="text-slate-700">email</strong>, and <strong className="text-slate-700">track</strong> — so you don't have to chase.
          </p>

          {/* Contact info */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { icon:Mail,  label:'Email Us', value:'hello@trainersync.ai', color:'from-blue-500 to-cyan-500' },
              { icon:Phone, label:'Call Us',  value:'+91 78158 47710',      color:'from-green-500 to-emerald-500' },
            ].map((item,i) => (
              <div key={i} className="flex items-center gap-3 bg-white rounded-2xl p-4 shadow-md border border-slate-100 hover:shadow-xl hover:-translate-y-1 transition-all duration-300 group cursor-pointer">
                <div className={clsx('w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 bg-gradient-to-br group-hover:scale-110 transition-transform duration-300', item.color)}>
                  <item.icon className="w-5 h-5 text-white"/>
                </div>
                <div>
                  <p className="text-xs text-slate-400 font-semibold uppercase tracking-wide">{item.label}</p>
                  <p className="text-sm font-semibold text-slate-800">{item.value}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Social */}
          <div className="flex items-center gap-3 pt-1">
            <span className="text-sm text-slate-500 font-medium">Follow us:</span>
            {[
              { icon:Linkedin,  color:'hover:bg-blue-50 hover:text-blue-600' },
              { icon:Twitter,   color:'hover:bg-sky-50 hover:text-sky-600' },
              { icon:Instagram, color:'hover:bg-pink-50 hover:text-pink-600' },
            ].map((s,i) => (
              <a key={i} href="#"
                className={clsx('w-9 h-9 bg-white border border-slate-200 rounded-xl flex items-center justify-center text-slate-500 transition-all duration-200 hover:scale-110 hover:shadow-md', s.color)}>
                <s.icon className="w-4 h-4"/>
              </a>
            ))}
          </div>
        </div>

        {/* Right — photo with badges */}
        <PhotoSection />
      </section>

      {/* Stats */}
      <section className="relative z-10 max-w-7xl mx-auto px-8 py-12">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {stats.map((s,i) => <StatBox key={i} {...s}/>)}
        </div>
      </section>

      {/* Social Media Cards with Reviews */}
      <section className="relative z-10 max-w-7xl mx-auto px-8 pb-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Instagram Card */}
          <div className="bg-white rounded-2xl shadow-lg border-2 border-pink-300 p-6 hover:shadow-xl transition-all duration-300">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-pink-500 to-rose-500 flex items-center justify-center text-white">
                <Instagram className="w-6 h-6"/>
              </div>
              <div>
                <p className="font-bold text-slate-900">Instagram</p>
                <p className="text-xs text-slate-500">@trainersync</p>
              </div>
            </div>
            <p className="text-sm text-slate-600 leading-relaxed italic">\"Amazing platform! Found my perfect trainer match in just 24 hours. Highly recommended!\"</p>
            <p className="text-xs text-slate-500 mt-3">— Priya Sharma, Training Manager</p>
          </div>

          {/* LinkedIn Card */}
          <div className="bg-white rounded-2xl shadow-lg border-2 border-blue-300 p-6 hover:shadow-xl transition-all duration-300">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-600 to-cyan-600 flex items-center justify-center text-white">
                <Linkedin className="w-6 h-6"/>
              </div>
              <div>
                <p className="font-bold text-slate-900">LinkedIn</p>
                <p className="text-xs text-slate-500">500+ connections</p>
              </div>
            </div>
            <p className="text-sm text-slate-600 leading-relaxed italic">\"Professional platform that connects you with industry-leading trainers. Best investment for corporate training!\"</p>
            <p className="text-xs text-slate-500 mt-3">— Michael Khan, L&D Director</p>
          </div>

          {/* Twitter Card */}
          <div className="bg-white rounded-2xl shadow-lg border-2 border-sky-300 p-6 hover:shadow-xl transition-all duration-300">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-sky-500 to-blue-500 flex items-center justify-center text-white">
                <Twitter className="w-6 h-6"/>
              </div>
              <div>
                <p className="font-bold text-slate-900">Twitter/X</p>
                <p className="text-xs text-slate-500">@trainersync_ai</p>
              </div>
            </div>
            <p className="text-sm text-slate-600 leading-relaxed italic">\"Just hired the perfect trainer through TrainerSync. 4 hours vs 4 weeks. Game changer! 🚀\"</p>
            <p className="text-xs text-slate-500 mt-3">— Ravi Prabhu, HR Head</p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <PublicFooter />
      <footer className="hidden">
        <div className="max-w-6xl mx-auto">
          {/* Main Footer Content */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-8 mb-8">
            {/* Logo & Brand */}
            <div>
              <button onClick={() => navigate('/home')} className="flex items-center gap-2.5 mb-4 hover:opacity-80 transition-opacity duration-200 cursor-pointer">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background:'linear-gradient(135deg,#2563eb,#06b6d4)' }}>
                  <Zap style={{ width:16, height:16, color:'white' }}/>
                </div>
                <span className="font-bold text-lg text-slate-900">TrainerSync</span>
              </button>
              <p className="text-slate-600 text-xs leading-relaxed">AI-powered trainer recruitment platform. Match, email, track, and close — all in one place.</p>
            </div>

            {/* About Us Column */}
            <div>
              <p className="font-semibold text-slate-900 text-sm mb-3">About us</p>
              <ul className="space-y-2">
                {[
                  { label: 'About', path: '/home' },
                  { label: 'Careers', path: '/contact' },
                  { label: 'Employer home', path: '/dashboard' },
                  { label: 'Sitemap', path: '/home' },
                ].map(({ label, path }) => (
                  <li key={label}>
                    <button onClick={() => navigate(path)} className="text-slate-600 hover:text-blue-600 text-xs transition-colors">
                      {label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {/* Help Center Column */}
            <div>
              <p className="font-semibold text-slate-900 text-sm mb-3">Help center</p>
              <ul className="space-y-2">
                {[
                  { label: 'Summons/Notices', path: '/contact' },
                  { label: 'Grievances', path: '/feedback' },
                  { label: 'Report issue', path: '/contact' },
                ].map(({ label, path }) => (
                  <li key={label}>
                    <button onClick={() => navigate(path)} className="text-slate-600 hover:text-blue-600 text-xs transition-colors">
                      {label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {/* Privacy & Policy Column */}
            <div>
              <p className="font-semibold text-slate-900 text-sm mb-3">Privacy policy</p>
              <ul className="space-y-2">
                {[
                  { label: 'Privacy policy', path: '/home' },
                  { label: 'Terms & conditions', path: '/home' },
                  { label: 'Fraud alert', path: '/contact' },
                  { label: 'Trust & safety', path: '/contact' },
                ].map(({ label, path }) => (
                  <li key={label}>
                    <button onClick={() => navigate(path)} className="text-slate-600 hover:text-blue-600 text-xs transition-colors">
                      {label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {/* Connect With Us */}
            <div>
              <p className="font-semibold text-slate-900 text-sm mb-3">Connect with us</p>
              <div className="flex gap-3">
                <a href="https://facebook.com" target="_blank" rel="noreferrer" 
                   className="w-8 h-8 flex items-center justify-center rounded-full bg-slate-100 text-slate-600 hover:bg-blue-100 hover:text-blue-600 transition-colors">
                  <span className="text-sm font-bold">f</span>
                </a>
                <a href="https://instagram.com" target="_blank" rel="noreferrer"
                   className="w-8 h-8 flex items-center justify-center rounded-full bg-slate-100 text-slate-600 hover:bg-pink-100 hover:text-pink-600 transition-colors">
                  <span className="text-xs font-bold">📷</span>
                </a>
                <a href="https://twitter.com" target="_blank" rel="noreferrer"
                   className="w-8 h-8 flex items-center justify-center rounded-full bg-slate-100 text-slate-600 hover:bg-blue-100 hover:text-blue-600 transition-colors">
                  <span className="text-xs font-bold">𝕏</span>
                </a>
                <a href="https://linkedin.com" target="_blank" rel="noreferrer"
                   className="w-8 h-8 flex items-center justify-center rounded-full bg-slate-100 text-slate-600 hover:bg-blue-100 hover:text-blue-600 transition-colors">
                  <span className="text-xs font-bold">in</span>
                </a>
              </div>
            </div>
          </div>

          {/* Footer Bottom */}
          <div className="border-t border-slate-200 pt-6 flex flex-col md:flex-row justify-center items-center gap-2">
            <p className="text-slate-600 text-xs text-center">© 2026 TrainerSync. All rights reserved. | Match. Outreach. Track. Close.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
