import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Zap, ArrowRight, CheckCircle, Star, Play,
  Upload, Brain, Mail, MessageSquare, Users,
  TrendingUp, Clock, Shield, ChevronRight,
  BarChart2, Filter, Send, Search, FileText, Calendar
} from 'lucide-react'
import clsx from 'clsx'

/* ── Global keyframes ──────────────────────────────── */
const CSS = `
@keyframes blob1{0%,100%{border-radius:60% 40% 70% 30%/50% 60% 40% 50%;transform:translate(0,0)}33%{border-radius:40% 60% 30% 70%/70% 30% 60% 40%;transform:translate(20px,-15px)}66%{border-radius:70% 30% 50% 50%/30% 70% 50% 50%;transform:translate(-10px,20px)}}
@keyframes blob2{0%,100%{border-radius:40% 60% 30% 70%/60% 40% 70% 30%}50%{border-radius:60% 40% 70% 30%/40% 60% 30% 70%;transform:translate(-18px,14px)}}
@keyframes floatY{0%,100%{transform:translateY(0)}50%{transform:translateY(-20px)}}
@keyframes fc1{0%,100%{transform:translateY(0) rotate(-1deg)}50%{transform:translateY(-12px) rotate(1deg)}}
@keyframes fc2{0%,100%{transform:translateY(0)}50%{transform:translateY(-16px)}}
@keyframes fc3{0%,100%{transform:translateY(-6px)}50%{transform:translateY(6px)}}
@keyframes slideL{from{opacity:0;transform:translateX(-40px)}to{opacity:1;transform:translateX(0)}}
@keyframes slideR{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:translateX(0)}}
@keyframes slideU{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:translateY(0)}}
@keyframes scaleIn{from{opacity:0;transform:scale(0.93)}to{opacity:1;transform:scale(1)}}
@keyframes ping2{0%{transform:scale(1);opacity:0.8}100%{transform:scale(2.2);opacity:0}}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
@keyframes pipeFlow{0%{stroke-dashoffset:200}100%{stroke-dashoffset:0}}
@keyframes stepPop{0%{transform:scale(0.8);opacity:0}100%{transform:scale(1);opacity:1}}
@keyframes counterUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}
@keyframes rotate{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
@keyframes glowPulse{0%,100%{box-shadow:0 0 20px rgba(37,99,235,0.3),inset 0 0 20px rgba(37,99,235,0.1)}50%{box-shadow:0 0 40px rgba(37,99,235,0.5),inset 0 0 30px rgba(37,99,235,0.2)}}
@keyframes floatCircle{0%{transform:translate(0,0) rotate(0deg)}25%{transform:translate(30px,30px) rotate(90deg)}50%{transform:translate(0,60px) rotate(180deg)}75%{transform:translate(-30px,30px) rotate(270deg)}100%{transform:translate(0,0) rotate(360deg)}}
@keyframes gradientShift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes shimmerWave{0%{background-position:-1000px 0}100%{background-position:1000px 0}}
@keyframes orbitSpin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
@keyframes glowBorder{0%,100%{box-shadow:0 0 10px rgba(37,99,235,0.4),0 0 20px rgba(6,182,212,0.2)}50%{box-shadow:0 0 20px rgba(37,99,235,0.6),0 0 40px rgba(6,182,212,0.4)}}
@keyframes flowLine{0%{stroke-dashoffset:1000}100%{stroke-dashoffset:0}}
.al{animation:slideL 0.7s cubic-bezier(.22,1,.36,1) both}
.ar{animation:slideR 0.7s cubic-bezier(.22,1,.36,1) both}
.au{animation:slideU 0.6s cubic-bezier(.22,1,.36,1) both}
.asc{animation:scaleIn 0.7s cubic-bezier(.22,1,.36,1) both}
.f1{animation:fc1 5s ease-in-out infinite}
.f2{animation:fc2 6s ease-in-out infinite}
.f3{animation:fc3 4s ease-in-out infinite}
.cursor::after{content:'|';animation:blink 0.9s step-end infinite}
.glow-pulse{animation:glowPulse 3s ease-in-out infinite}
.orbit-spin{animation:orbitSpin 20s linear infinite}
.float-circle{animation:floatCircle 8s ease-in-out infinite}
.gradient-shift{animation:gradientShift 8s ease infinite;background-size:200% 200%}
.shimmer-wave{animation:shimmerWave 3s linear infinite}
`

/* ── Typewriter ──────────────────────────────────── */
function useTypewriter(words, speed=75, pause=1800) {
  const [display, setDisplay] = useState('')
  const [wi, setWi] = useState(0)
  const [ci, setCi] = useState(0)
  const [del, setDel] = useState(false)
  useEffect(() => {
    const w = words[wi]; let t
    if (!del && ci < w.length) t = setTimeout(() => setCi(c=>c+1), speed)
    else if (!del && ci === w.length) t = setTimeout(() => setDel(true), pause)
    else if (del && ci > 0) t = setTimeout(() => setCi(c=>c-1), speed/2)
    else { setDel(false); setWi(i=>(i+1)%words.length) }
    setDisplay(w.slice(0, ci))
    return () => clearTimeout(t)
  }, [ci, del, wi, words, speed, pause])
  return display
}

/* ── Counter ─────────────────────────────────────── */
function useCounter(target, duration=1600) {
  const [val, setVal] = useState(0)
  const started = useRef(false)
  const ref = useRef(null)
  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !started.current) {
        started.current = true
        const start = performance.now()
        const tick = now => {
          const p = Math.min((now-start)/duration, 1)
          setVal(Math.floor((1-Math.pow(1-p,3))*target))
          if (p < 1) requestAnimationFrame(tick)
          else setVal(target)
        }
        requestAnimationFrame(tick)
      }
    }, { threshold: 0.4 })
    if (ref.current) obs.observe(ref.current)
    return () => obs.disconnect()
  }, [target, duration])
  return { val, ref }
}

/* ── Animated Pipeline ───────────────────────────── */
const STAGES = [
  { icon: Upload,      label: 'Upload',        desc: 'Upload requirements CSV or enter manually', color: '#2563eb', bg: '#eff6ff', num: '01' },
  { icon: Brain,       label: 'AI Match',      desc: 'AI scores trainers against your requirement', color: '#7c3aed', bg: '#ede9fe', num: '02' },
  { icon: Filter,      label: 'Filter',        desc: 'Smart filtering by skill, location, score',  color: '#0891b2', bg: '#e0f2fe', num: '03' },
  { icon: FileText,    label: 'Shortlist',     desc: 'Pick top-N trainers and review profiles',    color: '#059669', bg: '#d1fae5', num: '04' },
  { icon: Send,        label: 'Stage 1 Email', desc: 'Send initial training opportunity inquiry',  color: '#d97706', bg: '#fef3c7', num: '05' },
  { icon: Mail,        label: 'Stage 2 Email', desc: 'Request ToC/Agenda and trainer details',      color: '#e11d48', bg: '#ffe4e6', num: '06' },
  { icon: MessageSquare, label: 'Stage 3 Email', desc: 'Confirm proposal & schedule interview',     color: '#7c3aed', bg: '#ede9fe', num: '07' },
]

function AnimatedPipeline() {
  const [active, setActive] = useState(0)
  const [running, setRunning] = useState(true)
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setActive(a => (a+1) % STAGES.length), 1800)
    return () => clearInterval(t)
  }, [running])

  return (
    <div className="au" style={{ animationDelay:'.1s' }}>
      {/* Step row */}
      <div className="flex items-center justify-between relative mb-8">
        {/* Connecting line */}
        <div className="absolute left-0 right-0 top-7 h-0.5 bg-slate-100 z-0" style={{ margin:'0 28px' }}>
          <div className="h-full rounded-full transition-all duration-500"
            style={{ width:`${(active/(STAGES.length-1))*100}%`, background:'linear-gradient(90deg,#2563eb,#7c3aed,#059669)' }}/>
        </div>

        {STAGES.map((s, i) => {
          const done = i < active
          const curr = i === active
          return (
            <button key={i} onClick={() => { setActive(i); setRunning(false) }}
              className="relative z-10 flex flex-col items-center gap-2 group"
              style={{ animation:`stepPop 0.4s cubic-bezier(.22,1,.36,1) ${i*80}ms both` }}>
              <div className="w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-300 shadow-md"
                style={{
                  background: curr ? s.color : done ? s.color : 'white',
                  border: curr ? `2px solid ${s.color}` : done ? `2px solid ${s.color}` : '2px solid #e2e8f0',
                  transform: curr ? 'scale(1.15)' : 'scale(1)',
                  boxShadow: curr ? `0 8px 24px ${s.color}40` : done ? `0 2px 8px ${s.color}30` : '0 2px 8px rgba(0,0,0,0.06)',
                }}>
                <s.icon style={{ width:22, height:22, color: curr||done ? 'white' : '#94a3b8' }}/>
              </div>
              <span className="text-xs font-bold transition-colors duration-200"
                style={{ color: curr ? s.color : done ? s.color : '#94a3b8' }}>
                {s.label}
              </span>
              <span className="text-xs text-slate-300 font-mono">{s.num}</span>
            </button>
          )
        })}
      </div>

      {/* Active stage detail card */}
      <div className="rounded-2xl p-5 border transition-all duration-300"
        style={{ background: STAGES[active].bg, borderColor: STAGES[active].color+'30' }}>
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{ background: STAGES[active].color }}>
            {(() => { const Icon = STAGES[active].icon; return <Icon style={{ width:22, height:22, color:'white' }}/> })()}
          </div>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-bold text-slate-900" style={{ fontFamily:"'Sora',sans-serif", fontSize:15 }}>
                Stage {STAGES[active].num} — {STAGES[active].label}
              </span>
              <span className="text-xs px-2 py-0.5 rounded-full font-semibold"
                style={{ background: STAGES[active].color+'20', color: STAGES[active].color }}>
                Active
              </span>
            </div>
            <p className="text-sm text-slate-600">{STAGES[active].desc}</p>
          </div>
        </div>

        {/* Mini progress bar */}
        <div className="mt-3 h-1.5 bg-white/60 rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-1800"
            style={{ width:`${(active+1)*20}%`, background: STAGES[active].color }}/>
        </div>
        <div className="flex justify-between mt-1">
          <span className="text-xs text-slate-400">Pipeline progress</span>
          <span className="text-xs font-semibold" style={{ color: STAGES[active].color }}>{(active+1)*20}%</span>
        </div>
      </div>

      <button onClick={() => { setActive(0); setRunning(true) }}
        className="mt-3 text-xs text-slate-400 hover:text-blue-500 transition-colors flex items-center gap-1">
        <Play style={{ width:12, height:12 }}/> Replay animation
      </button>
    </div>
  )
}

/* ── Feature section card ────────────────────────── */
function PageCard({ icon: Icon, title, desc, tag, color, bg, onClick }) {
  return (
    <div onClick={onClick}
      className="bg-white rounded-2xl p-6 border border-slate-100 shadow-md hover:shadow-2xl hover:-translate-y-2 transition-all duration-300 cursor-pointer group relative overflow-hidden"
      style={{ position:'relative' }}>
      {/* Animated glow background */}
      <div style={{ position:'absolute', inset:0, borderRadius:'1rem', background:`linear-gradient(135deg,${color}08,${color}04)`, opacity:0, groupHover:'opacity-100', transition:'opacity 0.3s', pointerEvents:'none' }}/>
      
      {/* Shine effect */}
      <div style={{ position:'absolute', inset:0, background:'linear-gradient(90deg,transparent,rgba(255,255,255,0.4),transparent)', transform:'translateX(-100%)', animation:'none', pointerEvents:'none', borderRadius:'1rem', animationPlayState:'running' }} className="group-hover:shimmer-wave"/>
      
      <div className="relative z-10">
        <div className="w-12 h-12 rounded-2xl flex items-center justify-center mb-4 group-hover:scale-125 transition-transform duration-300 shadow-lg"
          style={{ background: bg, boxShadow:`0 0 20px ${color}40` }}>
          <Icon style={{ width:22, height:22, color }}/>
        </div>
        <div className="flex items-center gap-2 mb-2">
          <h3 className="font-bold text-slate-900">{title}</h3>
          <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ background: bg, color }}>
            {tag}
          </span>
        </div>
        <p className="text-slate-500 text-sm leading-relaxed mb-3">{desc}</p>
        <span className="text-sm font-semibold flex items-center gap-1 group-hover:gap-2 transition-all duration-200" style={{ color }}>
          Explore <ChevronRight style={{ width:14, height:14 }}/>
        </span>
      </div>
    </div>
  )
}

/* ── Stat card ───────────────────────────────────── */
function StatCard({ target, suffix, label, color, icon: Icon, delay }) {
  const { val, ref } = useCounter(target)
  return (
    <div ref={ref} className="bg-white rounded-2xl p-5 shadow-md border border-slate-100 text-center au hover:-translate-y-2 hover:shadow-lg transition-all duration-300 group relative overflow-hidden"
      style={{ animationDelay: delay, boxShadow:`0 0 0 1px ${color}10` }}>
      {/* Animated glow on hover */}
      <div style={{ position:'absolute', inset:0, background:`radial-gradient(circle at 50% 50%,${color}15,transparent 70%)`, opacity:0, pointerEvents:'none', borderRadius:'1rem' }} className="group-hover:glow-pulse"/>
      
      <div className="relative z-10">
        <div className="w-12 h-12 rounded-xl flex items-center justify-center mx-auto mb-3 group-hover:scale-110 transition-transform duration-300 shadow-md" style={{ background: color, boxShadow:`0 0 20px ${color}30` }}>
          <Icon style={{ width:22, height:22, color:'white' }}/>
        </div>
        <div className="text-3xl font-bold text-slate-900 tabular-nums group-hover:scale-105 transition-transform duration-300" style={{ fontFamily:"'Sora',sans-serif" }}>
          {val}{suffix}
        </div>
        <div className="text-sm text-slate-500 mt-1">{label}</div>
      </div>
    </div>
  )
}

/* ── Review strip ────────────────────────────────── */
const REVIEWS = [
  { name:'Priya S.', role:'MindTree', stars:5, text:'Matched our React trainer in 4 hours. 94% score was spot on.', color:'#2563eb' },
  { name:'Rahul M.', role:'Infosys',  stars:5, text:'3 weeks of manual search done in minutes. Incredible.', color:'#10b981' },
  { name:'Karan P.', role:'TCS',      stars:5, text:'Auto follow-up saved us from chasing 30 trainers manually.', color:'#7c3aed' },
]

/* ── Main ─────────────────────────────────────── */
export default function Home() {
  const navigate = useNavigate()
  const typed = useTypewriter(['React Developers','ML Engineers','DevOps Experts','Python Trainers','Cloud Architects'], 70, 1600)
  const [ready, setReady] = useState(false)
  useEffect(() => { setTimeout(() => setReady(true), 80) }, [])

  const pages = [
    { icon:Brain,        title:'AI Matching',     tag:'Core',       desc:'Upload a requirement and our AI scores every trainer in your database by skill match, experience, and availability.', color:'#2563eb', bg:'#eff6ff', path:'/dashboard' },
    { icon:Filter,       title:'Smart Shortlist', tag:'New',        desc:'Filter shortlisted trainers by score, location, and tech. One click to email all of them at once.', color:'#7c3aed', bg:'#ede9fe', path:'/shortlist' },
    { icon:Mail,         title:'Mail Automation', tag:'Automated',  desc:'Personalised emails sent automatically. Replies tracked. Follow-ups scheduled. Zero manual chasing.', color:'#0891b2', bg:'#e0f2fe', path:'/emails' },
    { icon:MessageSquare,title:'Reply Tracking',  tag:'Live',       desc:'See full conversation threads per trainer. Dashboard shows total replies, interested count, and sentiments.', color:'#059669', bg:'#d1fae5', path:'/dashboard' },
    { icon:BarChart2,    title:'Analytics',       tag:'Insights',   desc:'Track response rates, match accuracy, interview counts, and hiring speed on your live dashboard.', color:'#d97706', bg:'#fef3c7', path:'/dashboard' },
    { icon:Star,         title:'Reviews',         tag:'Trusted',    desc:'128+ verified recruiter reviews. 4.8 rating. 96% would recommend TrainerSync to a colleague.', color:'#e11d48', bg:'#fff1f2', path:'/feedback' },
  ]

  return (
    <div className="min-h-screen relative overflow-hidden"
      style={{ background:'linear-gradient(135deg,#f0f9ff 0%,#ffffff 45%,#f0fdf4 100%)' }}>
      <style>{CSS}</style>

      {/* Background blobs with enhanced effects */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {/* Primary glow blob */}
        <div style={{ position:'absolute', top:'4%', left:'6%', width:340, height:340, background:'linear-gradient(135deg,rgba(37,99,235,0.08),rgba(6,182,212,0.05))', animation:'blob1 11s ease-in-out infinite', filter:'blur(40px)' }}/>
        {/* Secondary glow blob */}
        <div style={{ position:'absolute', bottom:'8%', right:'5%', width:280, height:280, background:'linear-gradient(135deg,rgba(16,185,129,0.07),rgba(139,92,246,0.05))', animation:'blob2 13s ease-in-out infinite', filter:'blur(40px)' }}/>
        {/* Floating accent circle */}
        <div style={{ position:'absolute', top:'35%', right:'20%', width:180, height:180, borderRadius:'50%', background:'rgba(245,158,11,0.05)', animation:'floatY 8s ease-in-out infinite', filter:'blur(50px)' }}/>
        
        {/* Enhanced shimmer effect background */}
        <div style={{ position:'absolute', top:0, left:0, right:0, bottom:0, background:'radial-gradient(circle at 20% 50%,rgba(37,99,235,0.05),transparent 50%),radial-gradient(circle at 80% 80%,rgba(16,185,129,0.04),transparent 50%)', pointerEvents:'none' }}/>
        
        {/* Animated grid pattern */}
        <svg style={{ position:'absolute', top:0, left:0, width:'100%', height:'100%', opacity:0.03 }} className="orbit-spin">
          <defs>
            <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
              <path d="M 50 0 L 0 0 0 50" fill="none" stroke="currentColor" strokeWidth="1"/>
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>

        {/* Floating particles */}
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} style={{
            position: 'absolute',
            width: Math.random() * 100 + 50,
            height: Math.random() * 100 + 50,
            borderRadius: '50%',
            background: ['rgba(37,99,235,0.02)', 'rgba(6,182,212,0.02)', 'rgba(16,185,129,0.02)', 'rgba(139,92,246,0.02)'][i % 4],
            top: `${Math.random() * 100}%`,
            left: `${Math.random() * 100}%`,
            animation: `floatCircle ${8 + i * 2}s ease-in-out infinite`,
            filter: 'blur(60px)',
            pointerEvents: 'none'
          }} />
        ))}
      </div>

      {/* ── NAVBAR ── */}
      <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 py-3">
        {/* Logo */}
        <button onClick={() => navigate('/dashboard')} className="flex items-center gap-2 hover:opacity-80 transition-opacity duration-200 cursor-pointer">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shadow-md" style={{ background:'linear-gradient(135deg,#2563eb,#06b6d4)' }}>
            <Zap style={{ width:16, height:16, color:'white' }}/>
          </div>
          <span className="font-bold text-slate-900 text-base" style={{ fontFamily:"'Sora',sans-serif" }}>TrainerSync</span>
        </button>

        {/* Nav Links */}
        <div className="flex items-center gap-6">
          <button onClick={() => document.getElementById('features')?.scrollIntoView({ behavior:'smooth' })}
            className="text-xs font-semibold text-slate-700 hover:text-slate-900 transition-colors duration-200">
            Features
          </button>
          <button onClick={() => document.getElementById('pipeline')?.scrollIntoView({ behavior:'smooth' })}
            className="text-xs font-semibold text-slate-700 hover:text-slate-900 transition-colors duration-200">
            Pipeline
          </button>
          <button onClick={() => document.getElementById('reviews')?.scrollIntoView({ behavior:'smooth' })}
            className="text-xs font-semibold text-slate-700 hover:text-slate-900 transition-colors duration-200">
            Reviews
          </button>
          <button onClick={() => navigate('/login')}
            className="text-white px-4 py-2 rounded-lg text-xs font-semibold hover:shadow-lg transition-all duration-300 hover:scale-105"
            style={{ background:'linear-gradient(90deg,#2563eb,#06b6d4)', boxShadow:'0 4px 16px rgba(37,99,235,0.25)' }}>
            Get Started
          </button>
        </div>
      </nav>

      {/* ── HERO ── */}
      <section className="relative z-10 max-w-7xl mx-auto px-8 pt-28 pb-16 grid lg:grid-cols-2 gap-14 items-center" style={{ minHeight:'90vh' }}>

        {/* Left */}
        <div className="space-y-7 al" style={{ animationDelay:'.05s' }}>
          {/* Live badge */}
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/90 border border-blue-100 shadow-sm">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" style={{ animation:'ping2 1.2s cubic-bezier(0,0,0.2,1) infinite' }}/>
              <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500"/>
            </span>
            <span className="text-sm font-medium text-blue-600">7-Stage AI Recruitment Pipeline</span>
          </div>

          {/* Headline */}
          <div>
            <h1 style={{ fontFamily:"'Sora',sans-serif", fontSize:'clamp(2rem,4.5vw,3.5rem)', fontWeight:800, lineHeight:1.12, color:'#0f172a' }}>
              Find & Hire<br/>
              <span style={{ background:'linear-gradient(90deg,#2563eb,#06b6d4)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>
                {typed || '\u00A0'}
              </span>
              <span className="cursor" style={{ color:'#2563eb' }}/>
              <br/>
              <span style={{ color:'#0f172a' }}>in Hours, Not Weeks</span>
            </h1>
          </div>

          <p className="text-slate-500 text-lg leading-relaxed max-w-lg">
            Upload a requirement → AI matches trainers → Auto-email shortlist → Track replies → Close faster.
            <strong className="text-slate-700"> All automated.</strong>
          </p>

          {/* Checklist */}
          <ul className="space-y-2.5">
            {[
              'AI match score up to 98% accuracy',
              'Automated emails with reply & sentiment tracking',
              'Smart retry follow-ups on your schedule',
              '500+ verified trainers across India',
            ].map((t, i) => (
              <li key={i} className="flex items-center gap-3 au" style={{ animationDelay:`${0.25+i*0.08}s` }}>
                <CheckCircle style={{ width:17, height:17, color:'#10b981', flexShrink:0 }}/>
                <span className="text-slate-700 text-sm font-medium">{t}</span>
              </li>
            ))}
          </ul>

          {/* CTAs */}
          <div className="flex flex-wrap gap-4 pt-1">
            <button onClick={() => navigate('/login')}
              className="flex items-center gap-2 text-white px-7 py-3.5 rounded-xl font-semibold text-base hover:scale-105 transition-all duration-300"
              style={{ background:'linear-gradient(90deg,#2563eb,#06b6d4)', boxShadow:'0 4px 20px rgba(37,99,235,0.3)' }}>
              Start Free <ArrowRight style={{ width:18, height:18 }}/>
            </button>
            <a href="#pipeline"
              className="flex items-center gap-2 border-2 border-slate-200 text-slate-700 px-7 py-3.5 rounded-xl font-semibold text-base hover:border-blue-200 hover:bg-blue-50 transition-all duration-300">
              <Play style={{ width:16, height:16 }}/> See Pipeline
            </a>
          </div>

          {/* Trust */}
          <div className="flex items-center gap-3 au" style={{ animationDelay:'.6s' }}>
            <div className="flex -space-x-2">
              {['#2563eb','#10b981','#f59e0b','#8b5cf6','#e11d48'].map((c,i) => (
                <div key={i} className="w-8 h-8 rounded-full border-2 border-white flex items-center justify-center text-xs font-bold text-white"
                  style={{ background:c }}>
                  {['P','R','K','S','A'][i]}
                </div>
              ))}
            </div>
            <p className="text-sm text-slate-500">
              <span className="font-semibold text-slate-700">200+</span> recruiters · <span className="text-yellow-500">★</span> 4.8 rating
            </p>
          </div>
        </div>

        {/* Right — Dashboard preview */}
        <div className="relative flex items-center justify-center asc" style={{ animationDelay:'.15s', minHeight:520 }}>
          {/* Glow */}
          <div style={{ position:'absolute', inset:0, margin:'auto', width:380, height:380, borderRadius:'50%', background:'radial-gradient(circle,rgba(37,99,235,0.12),transparent 70%)', filter:'blur(32px)', pointerEvents:'none' }}/>

          {/* Main dashboard card */}
          <div className="relative z-10 w-full max-w-sm rounded-3xl bg-white shadow-2xl border border-slate-100 overflow-hidden"
            style={{ boxShadow:'0 25px 60px rgba(37,99,235,0.15)' }}>
            {/* Header */}
            <div className="px-5 py-4 flex items-center justify-between" style={{ background:'linear-gradient(90deg,#1e3a8a,#2563eb)' }}>
              <div className="flex items-center gap-2">
                <Zap style={{ width:16, height:16, color:'white' }}/>
                <span className="text-white font-bold text-sm">TrainerSync</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"/>
                <span className="text-xs text-blue-200">Live</span>
              </div>
            </div>

            <div className="p-4 space-y-3">
              {/* Stats row */}
              <div className="grid grid-cols-3 gap-2">
                {[['12','Matched','#2563eb','#eff6ff'],['5','Replied','#10b981','#d1fae5'],['96%','Score','#7c3aed','#ede9fe']].map(([v,l,c,bg]) => (
                  <div key={l} className="rounded-xl p-3 text-center" style={{ background:bg }}>
                    <div className="font-bold text-lg" style={{ color:c, fontFamily:"'Sora',sans-serif" }}>{v}</div>
                    <div className="text-xs text-slate-500">{l}</div>
                  </div>
                ))}
              </div>

              {/* Trainer rows */}
              {[
                { name:'Arjun Singh', skill:'React.js', score:96, status:'Interested', sc:'#d1fae5', st:'#059669' },
                { name:'Priya Menon', skill:'Python ML', score:92, status:'Replied', sc:'#dbeafe', st:'#2563eb' },
                { name:'Rahul Dev',   skill:'DevOps',   score:88, status:'Pending',  sc:'#fef3c7', st:'#d97706' },
              ].map(t => (
                <div key={t.name} className="flex items-center gap-3 p-3 rounded-xl bg-slate-50 hover:bg-slate-100 transition-colors">
                  <div className="w-9 h-9 rounded-xl flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
                    style={{ background:`linear-gradient(135deg,#2563eb,#06b6d4)` }}>
                    {t.name[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-slate-800 truncate">{t.name}</div>
                    <div className="text-xs text-slate-400">{t.skill}</div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="text-sm font-bold" style={{ color:'#2563eb' }}>{t.score}%</div>
                    <div className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ background:t.sc, color:t.st }}>{t.status}</div>
                  </div>
                </div>
              ))}

              {/* Pipeline mini bar */}
              <div className="pt-1">
                <div className="flex justify-between text-xs text-slate-400 mb-1.5">
                  <span>Pipeline progress</span><span className="font-semibold text-blue-600">Step 4/5</span>
                </div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width:'80%', background:'linear-gradient(90deg,#2563eb,#06b6d4,#10b981)' }}/>
                </div>
              </div>
            </div>
          </div>

          {/* Float cards */}
          <div className="f1 absolute z-20 bg-white rounded-2xl shadow-xl border border-slate-100 px-3.5 py-2.5 flex items-center gap-2" style={{ top:'5%', right:'-2%', minWidth:145 }}>
            <div className="w-8 h-8 rounded-xl bg-blue-50 flex items-center justify-center flex-shrink-0">
              <Brain style={{ width:15, height:15, color:'#2563eb' }}/>
            </div>
            <div>
              <div className="text-xs text-slate-400">AI Match Score</div>
              <div className="font-bold text-slate-900 text-lg leading-none" style={{ fontFamily:"'Sora',sans-serif" }}>96%</div>
            </div>
          </div>

          <div className="f2 absolute z-20 bg-white rounded-2xl shadow-xl border border-slate-100 px-3.5 py-2.5 flex items-center gap-2" style={{ bottom:'22%', left:'-4%', minWidth:165 }}>
            <div className="w-8 h-8 rounded-full bg-emerald-50 flex items-center justify-center flex-shrink-0">
              <Mail style={{ width:14, height:14, color:'#10b981' }}/>
            </div>
            <div>
              <div className="text-xs text-slate-400">Auto email sent</div>
              <div className="text-sm font-semibold text-slate-800">Arjun replied 🎉</div>
            </div>
          </div>

          <div className="f3 absolute z-20 rounded-2xl shadow-xl px-3.5 py-2.5 flex items-center gap-2" style={{ bottom:'5%', right:'-2%', background:'linear-gradient(90deg,#10b981,#059669)' }}>
            <CheckCircle style={{ width:15, height:15, color:'white' }}/>
            <span className="text-white text-sm font-semibold">Verified Match</span>
          </div>
        </div>
      </section>

      {/* ── PIPELINE ── */}
      <section id="pipeline" className="relative z-10 py-20 px-8" style={{ background:'linear-gradient(135deg,#1e3a8a,#1d4ed8,#0284c7)' }}>
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12 au">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full mb-4" style={{ background:'rgba(255,255,255,0.1)', border:'1px solid rgba(255,255,255,0.2)' }}>
              <Zap style={{ width:14, height:14, color:'#93c5fd' }}/>
              <span className="text-xs font-semibold text-blue-200">How It Works</span>
            </div>
            <h2 style={{ fontFamily:"'Sora',sans-serif", fontSize:'2rem', fontWeight:800, color:'white' }}>
              7-Stage AI Pipeline
            </h2>
            <p className="text-blue-200 mt-2 text-lg max-w-xl mx-auto">From requirement to confirmed trainer — fully automated</p>
          </div>
          <div className="bg-white/10 backdrop-blur-sm rounded-3xl p-8 border border-white/20">
            <AnimatedPipeline />
          </div>
        </div>
      </section>

      {/* ── STATS ── */}
      <section className="relative z-10 max-w-6xl mx-auto px-8 py-16">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
          <StatCard target={500} suffix="+" label="Expert Trainers"   color="linear-gradient(135deg,#2563eb,#06b6d4)"   icon={Users}         delay="0s"/>
          <StatCard target={98}  suffix="%" label="Match Accuracy"    color="linear-gradient(135deg,#10b981,#059669)"   icon={CheckCircle}   delay=".1s"/>
          <StatCard target={3}   suffix="×" label="Faster Hiring"     color="linear-gradient(135deg,#7c3aed,#8b5cf6)"  icon={TrendingUp}    delay=".2s"/>
          <StatCard target={128} suffix="+" label="Verified Reviews"  color="linear-gradient(135deg,#d97706,#f59e0b)"  icon={Star}          delay=".3s"/>
        </div>
      </section>

      {/* ── FEATURES / PAGES ── */}
      <section id="features" className="relative z-10 bg-white/60 backdrop-blur-sm py-20 px-8">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12 au">
            <h2 style={{ fontFamily:"'Sora',sans-serif", fontSize:'2rem', fontWeight:800, color:'#0f172a' }}>Everything in One Platform</h2>
            <p className="text-slate-500 mt-2 text-lg max-w-xl mx-auto">Six powerful modules covering every step of trainer recruitment</p>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {pages.map((p, i) => (
              <PageCard key={i} {...p} onClick={() => navigate(p.path)}/>
            ))}
          </div>
        </div>
      </section>

      {/* ── HOW TO SUBMIT / DEMO ── */}
      <section className="relative z-10 max-w-6xl mx-auto px-8 py-20">
        <div className="text-center mb-12 au">
          <h2 style={{ fontFamily:"'Sora',sans-serif", fontSize:'2rem', fontWeight:800, color:'#0f172a' }}>How to Use TrainerSync</h2>
          <p className="text-slate-500 mt-2 max-w-xl mx-auto">From signup to confirmed trainer in 7 simple steps</p>
        </div>
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Steps */}
          <div className="space-y-4">
            {[
              { n:'01', icon:Upload,      title:'Upload Requirement',    desc:'Go to Requirements page → Add requirement with tech, location, dates. Or upload CSV.',   color:'#2563eb' },
              { n:'02', icon:Brain,       title:'Run AI Match',          desc:'Click "Run AI Match" — system scores all trainers. Top matches appear in Shortlist.',   color:'#7c3aed' },
              { n:'03', icon:Filter,      title:'Review Shortlist',      desc:'Filter by score, check profiles, view thread history per trainer.',                     color:'#0891b2' },
              { n:'04', icon:Send,        title:'Send Emails',           desc:'Click "Send Emails" — personalised emails go out instantly to all shortlisted trainers.', color:'#059669' },
              { n:'05', icon:MessageSquare, title:'Track & Close',       desc:'Dashboard shows replies, sentiment, and thread. Schedule interviews from Interviews page.', color:'#d97706' },
              { n:'06', icon:Calendar,    title:'Schedule Interview',    desc:'Go to Interviews page → Confirm date/time, add meeting link. Send automated confirmation email.', color:'#8b5cf6' },
              { n:'07', icon:CheckCircle, title:'Confirm & Finalize',    desc:'Mark trainer as Selected/Rejected. Handle ToC requests and training confirmations.',        color:'#10b981' },
            ].map((s, i) => (
              <div key={i} className="flex gap-4 p-4 bg-white rounded-2xl border border-slate-100 shadow-sm hover:shadow-md hover:-translate-x-1 transition-all duration-200 au group"
                style={{ animationDelay:`${i*0.08}s` }}>
                <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform duration-200"
                  style={{ background: s.color }}>
                  <s.icon style={{ width:18, height:18, color:'white' }}/>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-slate-400">{s.n}</span>
                    <span className="font-bold text-slate-900 text-sm">{s.title}</span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Video placeholder */}
          <div className="relative rounded-3xl overflow-hidden shadow-2xl asc" style={{ animationDelay:'.2s' }}>
            <div className="aspect-video flex items-center justify-center relative"
              style={{ background:'linear-gradient(135deg,#1e3a8a,#1d4ed8,#0284c7)' }}>
              {/* Animated dots */}
              <div className="absolute inset-0 overflow-hidden opacity-20">
                {Array.from({ length: 12 }).map((_, i) => (
                  <div key={i} className="absolute rounded-full bg-white"
                    style={{ width: Math.random()*6+3, height: Math.random()*6+3, left:`${Math.random()*100}%`, top:`${Math.random()*100}%`, animation:`floatY ${4+Math.random()*4}s ease-in-out ${Math.random()*3}s infinite` }}/>
                ))}
              </div>
              <div className="text-center z-10 relative">
                <button className="w-20 h-20 rounded-full flex items-center justify-center shadow-2xl mb-4 mx-auto hover:scale-110 transition-transform duration-300"
                  style={{ background:'rgba(255,255,255,0.2)', border:'3px solid rgba(255,255,255,0.4)', backdropFilter:'blur(8px)' }}>
                  <Play style={{ width:28, height:28, color:'white', marginLeft:4 }}/>
                </button>
                <p className="text-white font-bold text-lg" style={{ fontFamily:"'Sora',sans-serif" }}>Watch Demo</p>
                <p className="text-blue-200 text-sm mt-1">See the full 7-stage pipeline in action</p>
              </div>
              {/* Corner badges */}
              <div className="absolute top-4 left-4 bg-white/20 backdrop-blur-sm rounded-xl px-3 py-1.5 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-red-400 animate-pulse"/>
                <span className="text-white text-xs font-semibold">LIVE DEMO</span>
              </div>
              <div className="absolute bottom-4 right-4 bg-white/20 backdrop-blur-sm rounded-xl px-3 py-1.5">
                <span className="text-white text-xs">2:34 min</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── REVIEWS ── */}
      <section id="reviews" className="relative z-10 py-20 px-8" style={{ background:'linear-gradient(135deg,#f8fafc,#eff6ff)' }}>
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12 au">
            <h2 style={{ fontFamily:"'Sora',sans-serif", fontSize:'2rem', fontWeight:800, color:'#0f172a' }}>What Recruiters Say</h2>
            <p className="text-slate-500 mt-2">128 verified reviews · 4.8 average rating</p>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            {REVIEWS.map((r, i) => (
              <div key={i} className="bg-white rounded-2xl p-6 shadow-md border border-slate-100 au" style={{ animationDelay:`${i*0.1}s` }}>
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-11 h-11 rounded-full flex items-center justify-center font-bold text-white text-sm" style={{ background: r.color }}>{r.name[0]}</div>
                  <div>
                    <div className="font-bold text-slate-900 text-sm">{r.name}</div>
                    <div className="text-xs text-slate-400">{r.role}</div>
                  </div>
                  <div className="ml-auto text-yellow-400 text-sm">{'★'.repeat(r.stars)}</div>
                </div>
                <p className="text-slate-600 text-sm leading-relaxed italic">"{r.text}"</p>
              </div>
            ))}
          </div>
          <div className="text-center mt-8">
            <button onClick={() => navigate('/feedback')}
              className="flex items-center gap-2 mx-auto text-blue-600 font-semibold hover:gap-3 transition-all duration-200">
              Read all 128 reviews <ChevronRight style={{ width:16, height:16 }}/>
            </button>
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="relative z-10 max-w-4xl mx-auto px-8 py-20">
        <div className="rounded-3xl p-12 text-center text-white relative overflow-hidden"
          style={{ background:'linear-gradient(135deg,#1d4ed8,#2563eb,#0284c7)' }}>
          <div style={{ position:'absolute', inset:0, backgroundImage:'radial-gradient(circle at 20% 50%,rgba(255,255,255,0.08),transparent 60%)' }}/>
          <h2 className="relative text-3xl font-bold mb-3" style={{ fontFamily:"'Sora',sans-serif" }}>Ready to Automate Your Trainer Hiring?</h2>
          <p className="relative text-blue-200 text-lg mb-8 max-w-xl mx-auto">Upload your first requirement and watch the AI find your trainer in minutes.</p>
          <div className="relative flex flex-wrap gap-4 justify-center">
            <button onClick={() => navigate('/login')} className="bg-white text-blue-600 px-8 py-4 rounded-xl font-bold text-lg hover:shadow-2xl hover:scale-105 transition-all duration-300">
              Start Free Now →
            </button>
            <button onClick={() => navigate('/contact')} className="border-2 border-white/40 text-white px-8 py-4 rounded-xl font-bold text-lg hover:bg-white/10 transition-all duration-300">
              Contact Sales
            </button>
          </div>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer className="relative z-10 bg-white border-t border-slate-200 px-8 py-12">
        <div className="max-w-6xl mx-auto">
          {/* Main Footer Content */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-8 mb-8">
            {/* Logo & Brand */}
            <div>
              <button onClick={() => navigate('/dashboard')} className="flex items-center gap-2.5 mb-4 hover:opacity-80 transition-opacity duration-200 cursor-pointer">
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