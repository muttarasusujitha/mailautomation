import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Star, ThumbsUp, MapPin, Users, CheckCircle, ArrowRight,
  Sparkles, TrendingUp, Clock, Shield, MessageSquare, Zap
} from 'lucide-react'
import clsx from 'clsx'

/* ─── Animated Background Elements ─────────────────────────────── */
function FloatingElements() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {/* Floating geometric shapes */}
      <div className="absolute top-20 left-20 w-32 h-32 bg-gradient-to-br from-blue-100 to-cyan-100 rounded-full opacity-60 animate-float-slow"></div>
      <div className="absolute top-40 right-32 w-24 h-24 bg-gradient-to-br from-purple-100 to-pink-100 rounded-lg rotate-45 opacity-50 animate-float-medium"></div>
      <div className="absolute bottom-32 left-1/4 w-20 h-20 bg-gradient-to-br from-green-100 to-emerald-100 rounded-full opacity-40 animate-float-fast"></div>
      <div className="absolute top-1/3 right-20 w-16 h-16 bg-gradient-to-br from-yellow-100 to-orange-100 rounded-lg opacity-50 animate-float-slow"></div>
      <div className="absolute bottom-20 right-1/3 w-28 h-28 bg-gradient-to-br from-indigo-100 to-blue-100 rounded-full opacity-30 animate-float-medium"></div>

      {/* Animated lines */}
      <div className="absolute top-0 left-0 w-full h-full">
        <svg className="w-full h-full" viewBox="0 0 1000 1000">
          <path d="M0,500 Q250,300 500,500 T1000,500" stroke="rgba(59,130,246,0.1)" strokeWidth="2" fill="none" className="animate-wave">
            <animate attributeName="stroke-dasharray" values="0,1000;1000,0" dur="4s" repeatCount="indefinite" />
          </path>
          <path d="M0,600 Q300,400 600,600 T1000,600" stroke="rgba(16,185,129,0.1)" strokeWidth="2" fill="none" className="animate-wave-delayed">
            <animate attributeName="stroke-dasharray" values="0,1000;1000,0" dur="4s" repeatCount="indefinite" begin="1s" />
          </path>
        </svg>
      </div>
    </div>
  )
}

/* ─── Animated Particle Canvas ─────────────────────────────── */
function ParticleCanvas() {
  const canvasRef = useRef(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let animId
    let W = (canvas.width = window.innerWidth / 2)
    let H = (canvas.height = window.innerHeight)
    const onResize = () => {
      W = canvas.width = window.innerWidth / 2
      H = canvas.height = window.innerHeight
    }
    window.addEventListener('resize', onResize)

    const dots = Array.from({ length: 50 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
      r: Math.random() * 2 + 1,
      a: Math.random() * 0.4 + 0.2,
      pulse: Math.random() * Math.PI * 2,
      color: ['#3b82f6', '#06b6d4', '#10b981', '#8b5cf6'][Math.floor(Math.random() * 4)]
    }))

    const draw = () => {
      ctx.clearRect(0, 0, W, H)
      dots.forEach(d => {
        d.x += d.vx; d.y += d.vy; d.pulse += 0.01
        if (d.x < 0 || d.x > W) d.vx *= -1
        if (d.y < 0 || d.y > H) d.vy *= -1
        const r = d.r + Math.sin(d.pulse) * 0.3
        ctx.beginPath()
        ctx.arc(d.x, d.y, r, 0, Math.PI * 2)
        ctx.fillStyle = d.color + Math.floor(d.a * 255).toString(16).padStart(2, '0')
        ctx.fill()
      })
      dots.forEach((a, i) => dots.slice(i + 1).forEach(b => {
        const dist = Math.hypot(a.x - b.x, a.y - b.y)
        if (dist < 120) {
          ctx.beginPath()
          ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y)
          ctx.strokeStyle = `rgba(59,130,246,${0.08 * (1 - dist / 120)})`
          ctx.lineWidth = 0.5
          ctx.stroke()
        }
      }))
      animId = requestAnimationFrame(draw)
    }
    draw()
    return () => { cancelAnimationFrame(animId); window.removeEventListener('resize', onResize) }
  }, [])
  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />
}

/* ─── Review Card Component (Compact) ─────────────────────────────────── */
function ReviewCard({ review, delay = 0 }) {
  const [helpfulCount, setHelpfulCount] = useState(review.helpful)
  const [isHelpful, setIsHelpful] = useState(false)

  const handleHelpful = () => {
    if (!isHelpful) {
      setHelpfulCount(prev => prev + 1)
      setIsHelpful(true)
    }
  }

  const renderStars = (rating) => {
    return Array.from({ length: 5 }, (_, i) => (
      <Star
        key={i}
        className={clsx(
          "w-3.5 h-3.5",
          i < rating ? "text-yellow-400 fill-current" : "text-slate-300"
        )}
      />
    ))
  }

  return (
    <div className={clsx(
      "bg-white rounded-2xl shadow-md border border-slate-100 overflow-hidden hover:shadow-lg transition-all duration-300 p-5",
      "animate-fade-in-up flex flex-col h-full"
    )} style={{ animationDelay: `${delay}ms` }}>
      {/* Header - Avatar + Name + Rating */}
      <div className="flex items-start gap-3.5 mb-3">
        <div
          className="w-12 h-12 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0 border-2 border-slate-100"
          style={{
            backgroundColor: review.avatarBg,
            color: review.avatarFg
          }}
        >
          {review.initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-slate-900 text-sm truncate">{review.name}</h3>
            {review.verified && (
              <CheckCircle className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
            )}
          </div>
          <p className="text-xs text-slate-500 truncate">{review.role} · {review.company}</p>
          <div className="flex items-center gap-1 mt-1">
            {renderStars(review.stars)}
            <span className="text-xs text-slate-500 ml-1">{review.stars}.0</span>
          </div>
        </div>
      </div>

      {/* Quote */}
      <p className="text-sm text-slate-700 mb-3 line-clamp-3 flex-grow leading-relaxed">
        "{review.quote}"
      </p>

      {/* Tags */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {review.tags.slice(0, 2).map((tag, i) => (
          <span
            key={i}
            className="px-2.5 py-1 bg-slate-100 text-slate-600 text-xs rounded-full border border-slate-200"
          >
            {tag}
          </span>
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-2.5 border-t border-slate-100">
        <div className="flex items-center gap-1 text-xs text-slate-500">
          <ThumbsUp className="w-3 h-3" />
          <span>{helpfulCount}</span>
        </div>
        <button
          onClick={handleHelpful}
          disabled={isHelpful}
          className={clsx(
            "flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg transition-all duration-200",
            isHelpful
              ? "bg-blue-50 text-blue-600 border border-blue-200"
              : "border border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"
          )}
        >
          <ThumbsUp className="w-3 h-3" />
          Helpful
        </button>
      </div>
    </div>
  )
}

/* ─── Write Review Modal ─────────────────────────────────── */
function WriteReviewModal({ isOpen, onClose, onSubmit }) {
  const [form, setForm] = useState({
    name: '',
    role: '',
    company: '',
    rating: 5,
    quote: '',
    tags: ''
  })

  const handleChange = (e) => {
    const { name, value } = e.target
    setForm(prev => ({ ...prev, [name]: value }))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (form.name && form.role && form.company && form.quote) {
      onSubmit(form)
      setForm({ name: '', role: '', company: '', rating: 5, quote: '', tags: '' })
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-slate-900">Share Your Experience</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 transition-colors p-1 hover:bg-slate-100 rounded-lg"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Full Name *</label>
              <input
                type="text"
                name="name"
                value={form.name}
                onChange={handleChange}
                placeholder="Your name"
                className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Company *</label>
              <input
                type="text"
                name="company"
                value={form.company}
                onChange={handleChange}
                placeholder="Your company"
                className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Role *</label>
              <input
                type="text"
                name="role"
                value={form.role}
                onChange={handleChange}
                placeholder="Your role"
                className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Rating *</label>
              <select
                name="rating"
                value={form.rating}
                onChange={handleChange}
                className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              >
                <option value="5">★★★★★ (5 Stars)</option>
                <option value="4">★★★★ (4 Stars)</option>
                <option value="3">★★★ (3 Stars)</option>
                <option value="2">★★ (2 Stars)</option>
                <option value="1">★ (1 Star)</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Your Review *</label>
            <textarea
              name="quote"
              value={form.quote}
              onChange={handleChange}
              placeholder="Share your experience with TrainerSync..."
              rows={4}
              className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm resize-none"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Tags (comma separated)</label>
            <input
              type="text"
              name="tags"
              value={form.tags}
              onChange={handleChange}
              placeholder="e.g. Python, Quick hire, Great match"
              className="w-full px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            />
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2.5 rounded-lg border border-slate-300 text-slate-700 font-medium hover:bg-slate-50 transition-all"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 px-4 py-2.5 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-medium hover:shadow-lg transition-all hover:scale-105"
            >
              Post Review
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

/* ─── Stat Card ────────────────────────────────────────────── */
function StatCard({ value, label, subtitle, icon: Icon, color }) {
  return (
    <div className="bg-white rounded-2xl p-6 shadow-lg border border-slate-100 text-center hover:shadow-xl transition-all duration-300 animate-fade-in-up">
      <div className={clsx("w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4", color)}>
        <Icon className="w-8 h-8 text-white" />
      </div>
      <div className="text-3xl font-bold text-slate-900 mb-1">{value}</div>
      <div className="text-slate-600 text-sm font-medium mb-1">{label}</div>
      {subtitle && <div className="text-slate-500 text-xs">{subtitle}</div>}
    </div>
  )
}

/* ─── Main Feedback Component ───────────────────────────────── */
export default function Feedback() {
  const navigate = useNavigate()
  const [mounted, setMounted] = useState(false)
  const [filter, setFilter] = useState(0)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [reviews, setReviews] = useState([])

  useEffect(() => {
    setMounted(true)
  }, [])

  const handleWriteReview = () => {
    setIsModalOpen(true)
  }

  const handleCloseModal = () => {
    setIsModalOpen(false)
  }

  const handleSubmitReview = (form) => {
    const newReview = {
      name: form.name,
      role: form.role,
      company: form.company,
      initials: form.name.split(' ').map(n => n[0]).join('').toUpperCase(),
      avatarBg: `hsl(${Math.random() * 360}, 70%, 80%)`,
      avatarFg: `hsl(${Math.random() * 360}, 100%, 20%)`,
      stars: parseInt(form.rating),
      date: new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }),
      helpful: 0,
      verified: false,
      quote: form.quote,
      tags: form.tags ? form.tags.split(',').map(t => t.trim()) : []
    }
    setReviews(prev => [newReview, ...prev])
    setIsModalOpen(false)
  }

  const defaultReviews = [
    {
      name: "Priya Sharma",
      role: "Senior Recruiter",
      company: "MindTree",
      loc: "Bengaluru",
      initials: "PS",
      cover: "#185FA5",
      avatarBg: "#B5D4F4",
      avatarFg: "#042C53",
      stars: 5,
      date: "12 May 2026",
      helpful: 18,
      verified: true,
      connections: "500+",
      quote: "The AI-matched trainer for our React batch had exactly the depth we needed. 94% match score — and it showed on day one of training.",
      tags: ["React", "Frontend", "Quick hire"]
    },
    {
      name: "Rahul Mehta",
      role: "L&D Manager",
      company: "Infosys",
      loc: "Pune",
      initials: "RM",
      cover: "#3B6D11",
      avatarBg: "#C0DD97",
      avatarFg: "#173404",
      stars: 5,
      date: "8 May 2026",
      helpful: 24,
      verified: true,
      connections: "1.2k",
      quote: "Three weeks of manual search — TrainerSync matched our Python ML trainer in 4 hours. The shortlist ranked by score made the decision a 10-minute call, not a 3-day committee.",
      tags: ["Python", "Machine Learning", "Matched fast"]
    },
    {
      name: "Sneha Iyer",
      role: "Technical Lead",
      company: "Wipro",
      loc: "Hyderabad",
      initials: "SI",
      cover: "#534AB7",
      avatarBg: "#CEC9F6",
      avatarFg: "#26215C",
      stars: 4,
      date: "2 May 2026",
      helpful: 9,
      verified: false,
      connections: "340",
      quote: "Solid experience. Node.js trainer was well prepared. The email thread view showing full conversation history saved our team hours of inbox archaeology.",
      tags: ["Node.js", "Backend", "Email tracking"]
    },
    {
      name: "Karan Patel",
      role: "HR Director",
      company: "TCS",
      loc: "Mumbai",
      initials: "KP",
      cover: "#854F0B",
      avatarBg: "#FAC775",
      avatarFg: "#412402",
      stars: 5,
      date: "28 Apr 2026",
      helpful: 31,
      verified: true,
      connections: "2.4k",
      quote: "Placed 3 trainers this month through TrainerSync. The reply tracking and auto follow-up removed the most painful part of recruitment — chasing unresponsive candidates.",
      tags: ["Multiple placements", "Auto follow-up", "Dashboard"]
    },
    {
      name: "Ananya Roy",
      role: "Project Manager",
      company: "HCL",
      loc: "Chennai",
      initials: "AR",
      cover: "#993556",
      avatarBg: "#F4C0D1",
      avatarFg: "#4B1528",
      stars: 5,
      date: "20 Apr 2026",
      helpful: 14,
      verified: true,
      connections: "780",
      quote: "Needed a DevOps trainer urgently for an on-site batch. Confirmed within 48 hours. The platform shortlists, emails, tracks — I just approved. That is how recruitment should feel.",
      tags: ["DevOps", "Urgent", "On-site"]
    },
    {
      name: "Vikram Nair",
      role: "Talent Acquisition",
      company: "Cognizant",
      loc: "Kochi",
      initials: "VN",
      cover: "#0F6E56",
      avatarBg: "#9FE1CB",
      avatarFg: "#04342C",
      stars: 3,
      date: "14 Apr 2026",
      helpful: 6,
      verified: false,
      connections: "210",
      quote: "Good match quality for our Java requirement. One thing to improve: trainer availability wasn't synced in real time and we needed an extra confirmation round. Platform itself is genuinely impressive.",
      tags: ["Java", "Availability", "Feedback"]
    }
  ]

  const allReviews = [...reviews, ...defaultReviews]
  const filteredReviews = filter === 0 ? allReviews : allReviews.filter(r => r.stars === filter)

  const stats = [
    { value: "4.8", label: "Average rating", subtitle: "★★★★★", icon: Star, color: "bg-gradient-to-br from-yellow-400 to-orange-400" },
    { value: "128", label: "Total reviews", subtitle: "from verified users", icon: MessageSquare, color: "bg-gradient-to-br from-blue-500 to-cyan-500" },
    { value: "96%", label: "Would recommend", subtitle: "to a colleague", icon: CheckCircle, color: "bg-gradient-to-br from-green-500 to-emerald-500" }
  ]

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50 relative overflow-hidden">
      {/* Animated Background */}
      <FloatingElements />
      <ParticleCanvas />

      {/* Navigation — Logo on left edge, Get Started on right edge */}
      <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 py-4 lg:px-8 bg-white/80 backdrop-blur-sm">
        <button onClick={() => navigate('/dashboard')} className="flex items-center gap-2.5 hover:opacity-80 transition-opacity flex-shrink-0 group">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-md group-hover:shadow-lg group-hover:scale-110 transition-all duration-300">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <span className="font-bold text-slate-900 text-base cursor-pointer hover:text-blue-600 transition-colors" style={{ fontFamily:"'Sora',sans-serif" }}>TrainerSync</span>
        </button>
        <div className="flex items-center gap-6">
          <button onClick={() => navigate('/contact')} className="text-slate-600 hover:text-slate-900 transition-colors">
            Contact
          </button>
          <button onClick={() => navigate('/login')}
            className="bg-gradient-to-r from-blue-500 to-cyan-500 text-white px-6 py-2 rounded-xl font-medium hover:shadow-lg transition-all duration-300 hover:scale-105">
            Get Started
          </button>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative z-10 px-6 py-24 lg:px-8 lg:py-32 pt-24">
        <div className="max-w-7xl mx-auto grid gap-8 lg:grid-cols-[1.1fr_0.9fr] items-center">
          <div className="space-y-6">
            <h1 className="text-4xl lg:text-6xl font-bold text-slate-900 leading-tight animate-fade-in-up" style={{ animationDelay: '200ms' }}>
              What Our
              <span className="bg-gradient-to-r from-blue-500 to-cyan-500 bg-clip-text text-transparent"> Recruiters</span>
              <br />Are Saying
            </h1>

            <p className="text-lg text-slate-600 max-w-2xl animate-fade-in-up" style={{ animationDelay: '400ms' }}>
              Trusted by 200+ recruiters across India's top IT firms. Read real experiences from professionals who have transformed their hiring process.
            </p>

            <div className="flex flex-col sm:flex-row gap-4 animate-fade-in-up" style={{ animationDelay: '600ms' }}>
              <button onClick={handleWriteReview}
                className="bg-gradient-to-r from-blue-500 to-cyan-500 text-white px-8 py-4 rounded-xl font-semibold text-lg hover:shadow-xl transition-all duration-300 hover:scale-105 flex items-center justify-center gap-2">
                Share Your Experience
                <ArrowRight className="w-5 h-5" />
              </button>
            </div>
          </div>

          <div className="relative animate-slide-in-left lg:mt-0 mt-8 flex justify-center items-center" style={{ animationDelay: '300ms' }}>
            {/* Main image container - with gradient border matching website colors */}
            <div className="relative rounded-[2rem] overflow-visible shadow-2xl bg-gradient-to-br from-blue-100 via-cyan-50 to-blue-50 w-full max-w-sm" style={{ aspectRatio: '3/4' }}>
              {/* Top stat badge - Trusted Feedback Verified */}
              <div className="absolute -top-6 left-6 z-30 animate-bounce-in" style={{ animationDelay: '600ms' }}>
                <div className="bg-white rounded-2xl shadow-xl border-2 border-blue-300 p-3 flex items-center gap-2 backdrop-blur-sm">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-green-400 to-emerald-500 flex items-center justify-center text-white font-bold text-xs">✓</div>
                  <div>
                    <p className="text-xs text-slate-500">Trusted</p>
                    <p className="text-xs font-semibold text-slate-900">Feedback verified</p>
                  </div>
                </div>
              </div>

              {/* Rating badge - Top right corner like message */}
              <div className="absolute -top-4 -right-4 z-30 animate-bounce-in" style={{ animationDelay: '700ms' }}>
                <div className="bg-gradient-to-br from-blue-500 to-cyan-500 text-white rounded-2xl shadow-xl border-2 border-white p-3 flex flex-col items-center backdrop-blur-sm">
                  <Star className="w-5 h-5 text-yellow-300 fill-yellow-300 mb-1" />
                  <p className="text-lg font-bold">4.8</p>
                  <p className="text-xs font-medium">★★★★★</p>
                </div>
              </div>

              {/* Main image */}
              <img
                src="/images/office-girl.png"
                alt="Professional recruiter feedback"
                className="w-full h-full object-cover rounded-[2rem]"
              />

              {/* Bottom left stat - Real feedback */}
              <div className="absolute -bottom-6 left-8 z-20 animate-bounce-in" style={{ animationDelay: '800ms' }}>
                <div className="bg-white rounded-2xl shadow-xl border-2 border-blue-300 px-4 py-3 flex items-center gap-2 backdrop-blur-sm">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-cyan-500 flex items-center justify-center text-white font-bold text-xs">📊</div>
                  <div className="text-left">
                    <p className="text-xs text-slate-500">128 reviews</p>
                    <p className="text-xs font-semibold text-slate-900">Real verified</p>
                  </div>
                </div>
              </div>

              {/* Bottom right stat - Recommend */}
              <div className="absolute -bottom-6 -right-4 z-20 animate-bounce-in" style={{ animationDelay: '900ms' }}>
                <div className="bg-white rounded-2xl shadow-xl border-2 border-emerald-300 px-4 py-3 flex items-center gap-2 backdrop-blur-sm">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-400 to-green-500 flex items-center justify-center text-white font-bold text-xs">96%</div>
                  <div className="text-left">
                    <p className="text-xs text-slate-500">Recommend</p>
                    <p className="text-xs font-semibold text-slate-900">by users</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Animated cutout office girl - floating with animation */}
            <div className="absolute -bottom-16 -right-20 w-64 h-auto animate-float-slow" style={{ animationDelay: '200ms' }}>
              <img
                src="/images/office-girl.png"
                alt="Office girl cutout"
                className="w-full h-full object-contain drop-shadow-2xl filter brightness-110 hover:scale-110 transition-transform duration-300"
                style={{
                  filter: 'drop-shadow(0 20px 30px rgba(0,0,0,0.3))'
                }}
              />
            </div>

            {/* Decorative animated elements around cutout */}
            <div className="absolute -bottom-20 right-12 w-32 h-32 bg-gradient-to-br from-blue-300 to-cyan-300 rounded-full opacity-20 blur-3xl animate-pulse"></div>
            <div className="absolute -bottom-24 right-20 w-24 h-24 bg-gradient-to-br from-purple-300 to-pink-300 rounded-full opacity-15 blur-2xl animate-bounce" style={{ animationDelay: '500ms' }}></div>
          </div>
        </div>
      </section>

      {/* Reviews Section */}
      <section className="relative z-10 px-6 py-20 lg:px-8 bg-white/50 backdrop-blur-sm">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl lg:text-4xl font-bold text-slate-900 mb-4">
              Recruiter Reviews
            </h2>
            <p className="text-lg text-slate-600 max-w-2xl mx-auto">
              Real feedback from verified recruiters who have successfully hired trainers through our platform.
            </p>
          </div>

          <div className="flex flex-wrap justify-center gap-3 mb-12">
            <button
              onClick={() => setFilter(0)}
              className={clsx(
                "px-6 py-3 rounded-full font-medium transition-all duration-200",
                filter === 0
                  ? "bg-blue-500 text-white shadow-lg"
                  : "bg-white text-slate-600 border border-slate-200 hover:border-slate-300 hover:bg-slate-50"
              )}
            >
              All Reviews
            </button>
            {[5, 4, 3].map(rating => (
              <button
                key={rating}
                onClick={() => setFilter(rating)}
                className={clsx(
                  "px-6 py-3 rounded-full font-medium transition-all duration-200 flex items-center gap-2",
                  filter === rating
                    ? "bg-blue-500 text-white shadow-lg"
                    : "bg-white text-slate-600 border border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                )}
              >
                {rating} Star{rating > 1 ? 's' : ''}
                <div className="flex">
                  {Array.from({ length: rating }, (_, i) => (
                    <Star key={i} className="w-4 h-4 fill-current" />
                  ))}
                </div>
              </button>
            ))}
          </div>

          {/* Reviews Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-12">
            {filteredReviews.map((review, i) => (
              <ReviewCard key={i} review={review} delay={i * 100} />
            ))}
          </div>

          {/* Write Review CTA */}
          <div className="bg-white rounded-2xl p-8 shadow-lg border border-slate-100 text-center">
            <div className="flex flex-col md:flex-row items-center justify-between gap-6">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-cyan-500 rounded-full flex items-center justify-center text-white font-semibold">
                  YO
                </div>
                <div className="text-left">
                  <div className="font-semibold text-slate-900">Share your experience</div>
                  <div className="text-sm text-slate-600">Help others make better hiring decisions</div>
                </div>
              </div>
              <button
                onClick={handleWriteReview}
                className="bg-gradient-to-r from-blue-500 to-cyan-500 text-white px-6 py-3 rounded-xl font-semibold hover:shadow-xl transition-all duration-300 hover:scale-105 flex items-center gap-2"
              >
                Write a Review
                <ArrowRight className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 bg-white border-t border-slate-200 px-6 py-12 lg:px-8">
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

      {/* Write Review Modal */}
      <WriteReviewModal 
        isOpen={isModalOpen}
        onClose={handleCloseModal}
        onSubmit={handleSubmitReview}
      />
    </div>
  )
}