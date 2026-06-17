// Home.jsx — TrainerSync · Professional Landing Page
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import BrandMark from '../components/BrandMark'
import {
  ArrowRight, CheckCircle, Brain, Mail, MessageSquare, Users,
  TrendingUp, Shield, BarChart2, Send, Calendar, Sparkles,
  Inbox, FileText, UserCheck, PhoneCall, Search, Database,
  MailCheck, Award, Target, Repeat2, LayoutDashboard,
  Zap, Globe2, BriefcaseBusiness, BookOpen, ChevronRight,
  Star, PlayCircle, Layers, Settings,
} from 'lucide-react'

/* ─── Static data ──────────────────────────────────────────── */
const STATS = [
  { value: '500+', label: 'Trainer Profiles', icon: Users },
  { value: '7-Stage', label: 'Email Pipeline', icon: Mail },
  { value: '98%', label: 'Match Accuracy', icon: Target },
  { value: '3×', label: 'Faster Hiring', icon: TrendingUp },
]

const FEATURES = [
  {
    icon: Brain,
    color: '#2563eb',
    bg: '#eff6ff',
    title: 'AI Trainer Matching',
    desc: 'Automatically match client requirements to the best trainer profiles using skill, experience, certification, and location scoring.',
  },
  {
    icon: Mail,
    color: '#7c3aed',
    bg: '#faf5ff',
    title: '7-Stage Email Pipeline',
    desc: 'Automated outreach: first contact → details request → interview slots → selection → ToC → confirmation. All tracked.',
  },
  {
    icon: Inbox,
    color: '#0891b2',
    bg: '#ecfeff',
    title: 'Client Inbox Automation',
    desc: 'Sync client Gmail, detect training requests, auto-classify, and notify recruiters with one-click approval workflows.',
  },
  {
    icon: FileText,
    color: '#059669',
    bg: '#ecfdf5',
    title: 'Resume Intelligence',
    desc: 'Upload PDFs and let AI extract trainer name, email, skills, certifications, experience, rates, and past clients instantly.',
  },
  {
    icon: MessageSquare,
    color: '#ea580c',
    bg: '#fff7ed',
    title: 'WhatsApp & Teams',
    desc: 'Send interview invites and follow-ups via WhatsApp (Twilio/Meta) and Microsoft Teams alongside email automation.',
  },
  {
    icon: BarChart2,
    color: '#d97706',
    bg: '#fffbeb',
    title: 'Analytics Dashboard',
    desc: 'Track trainer inventory, email delivery rates, reply rates, pipeline health, and PO/invoice status in real time.',
  },
  {
    icon: Award,
    color: '#db2777',
    bg: '#fdf2f8',
    title: 'LinkedIn & Naukri Search',
    desc: 'Search public trainer profiles on LinkedIn and Naukri, extract contact details, and auto-add to your shortlist.',
  },
  {
    icon: BookOpen,
    color: '#0d9488',
    bg: '#f0fdfa',
    title: 'ToC Knowledge Engine',
    desc: 'Generate training Table of Contents, store domain knowledge, and send structured TOC PDFs to clients automatically.',
  },
]

const PIPELINE_STEPS = [
  { num: '01', title: 'Client Requirement', desc: 'Capture technology, skills, duration, budget and location from client request' },
  { num: '02', title: 'AI Shortlisting', desc: 'Score and rank trainers from database against requirement in seconds' },
  { num: '03', title: 'Mail 1 — Outreach', desc: 'First contact email sent automatically to shortlisted trainers' },
  { num: '04', title: 'Mail 2 — Details', desc: 'Request trainer profile, availability and day rate details' },
  { num: '05', title: 'Interview Scheduling', desc: 'Collect slots from trainer and forward to client for confirmation' },
  { num: '06', title: 'Selection & ToC', desc: 'Confirm selection, request Table of Contents / training agenda' },
  { num: '07', title: 'PO & Invoice', desc: 'Generate purchase order and invoice, close the requirement' },
]

const MODULES = [
  { icon: LayoutDashboard, label: 'Dashboard', to: '/dashboard' },
  { icon: Users,           label: 'Trainers',  to: '/trainers' },
  { icon: Search,          label: 'Find',       to: '/requirements' },
  { icon: Zap,             label: 'AI Pipeline', to: '/shortlist1' },
  { icon: Globe2,          label: 'LinkedIn',   to: '/linkedin-search' },
  { icon: BriefcaseBusiness, label: 'Naukri',   to: '/naukri-search' },
  { icon: Mail,            label: 'Emails',     to: '/emails' },
  { icon: Inbox,           label: 'Client Inbox', to: '/client-requests' },
  { icon: Calendar,        label: 'Interviews', to: '/interview-scheduled' },
  { icon: FileText,        label: 'Invoices',   to: '/invoices' },
  { icon: BookOpen,        label: 'ToC',        to: '/toc-knowledge' },
  { icon: Settings,        label: 'Settings',   to: '/admin' },
]


/* ─── Hero Section ─────────────────────────────────────────── */
function Hero({ onGetStarted }) {
  return (
    <section style={{
      background: 'linear-gradient(160deg,#f0f7ff 0%,#ffffff 45%,#f8faff 100%)',
      borderBottom: '1px solid #e2e8f0',
      paddingTop: 72, paddingBottom: 80,
    }}>
      <div style={{ maxWidth: 1160, margin: '0 auto', padding: '0 28px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 28 }}>

          {/* Eyebrow pill */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            background: '#eff6ff', border: '1px solid #bfdbfe',
            borderRadius: 999, padding: '6px 16px',
            fontSize: 12, fontWeight: 700, color: '#1d4ed8',
            letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#2563eb', display: 'inline-block' }} />
            AI-Powered Trainer Matching Platform
          </div>

          {/* Headline */}
          <div>
            <h1 style={{
              fontFamily: "'Plus Jakarta Sans',sans-serif",
              fontSize: 'clamp(34px,5vw,62px)',
              fontWeight: 800, letterSpacing: '-0.04em', lineHeight: 1.08,
              color: '#0f172a', margin: 0,
            }}>
              Find the right trainer,
              <br />
              <span style={{ color: '#2563eb' }}>close faster.</span>
            </h1>
            <p style={{
              marginTop: 20, fontSize: 18, lineHeight: 1.65,
              color: '#475569', maxWidth: 560, marginLeft: 'auto', marginRight: 'auto',
            }}>
              TrainerSync connects clients, trainers, and your team in one intelligent platform — from requirement to invoice, fully automated.
            </p>
          </div>

          {/* CTA buttons */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'center' }}>
            <button
              onClick={onGetStarted}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                background: '#2563eb', color: 'white',
                padding: '13px 26px', borderRadius: 10, border: 'none',
                fontFamily: "'Plus Jakarta Sans',sans-serif",
                fontSize: 15, fontWeight: 700, cursor: 'pointer',
                boxShadow: '0 4px 16px -4px rgba(37,99,235,0.5)',
                transition: 'all 0.15s',
              }}
              onMouseOver={e => { e.currentTarget.style.background = '#1d4ed8'; e.currentTarget.style.transform = 'translateY(-1px)' }}
              onMouseOut={e => { e.currentTarget.style.background = '#2563eb'; e.currentTarget.style.transform = 'translateY(0)' }}
            >
              Open Dashboard <ArrowRight size={16} />
            </button>
            <button
              onClick={onGetStarted}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                background: 'white', color: '#0f172a',
                padding: '13px 26px', borderRadius: 10,
                border: '1px solid #e2e8f0',
                fontFamily: "'Plus Jakarta Sans',sans-serif",
                fontSize: 15, fontWeight: 600, cursor: 'pointer',
                boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                transition: 'all 0.15s',
              }}
              onMouseOver={e => { e.currentTarget.style.borderColor = '#bfdbfe'; e.currentTarget.style.transform = 'translateY(-1px)' }}
              onMouseOut={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.transform = 'translateY(0)' }}
            >
              <PlayCircle size={16} /> Watch Overview
            </button>
          </div>

          {/* Trust row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap', justifyContent: 'center' }}>
            {['No credit card required', 'Live AI matching', 'WhatsApp + Email + Teams'].map(t => (
              <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', fontWeight: 500 }}>
                <CheckCircle size={14} color="#22c55e" />
                {t}
              </div>
            ))}
          </div>
        </div>

        {/* Stats row */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 16,
          marginTop: 64, maxWidth: 900, margin: '64px auto 0',
        }}>
          {STATS.map(s => {
            const Icon = s.icon
            return (
              <div key={s.label} style={{
                background: 'white', border: '1px solid #e2e8f0',
                borderRadius: 14, padding: '22px 20px', textAlign: 'center',
                boxShadow: '0 2px 8px -2px rgba(0,0,0,0.06)',
              }}>
                <div style={{
                  width: 40, height: 40, borderRadius: 10,
                  background: '#eff6ff', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', margin: '0 auto 10px',
                }}>
                  <Icon size={18} color="#2563eb" />
                </div>
                <div style={{
                  fontFamily: "'Plus Jakarta Sans',sans-serif",
                  fontSize: 28, fontWeight: 800, color: '#0f172a',
                  letterSpacing: '-0.04em',
                }}>{s.value}</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginTop: 4 }}>{s.label}</div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}


/* ─── Features Grid ────────────────────────────────────────── */
function FeaturesSection() {
  return (
    <section style={{ padding: '80px 28px', background: '#f8faff' }}>
      <div style={{ maxWidth: 1160, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 52 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: '#eff6ff', border: '1px solid #bfdbfe',
            borderRadius: 999, padding: '5px 14px',
            fontSize: 11, fontWeight: 700, color: '#1d4ed8',
            textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 16,
          }}>
            <Sparkles size={11} /> Platform Capabilities
          </div>
          <h2 style={{
            fontFamily: "'Plus Jakarta Sans',sans-serif",
            fontSize: 'clamp(26px,3.5vw,40px)', fontWeight: 800,
            letterSpacing: '-0.035em', color: '#0f172a', margin: '0 0 14px',
          }}>Everything you need to scale trainer operations</h2>
          <p style={{ fontSize: 16, color: '#64748b', maxWidth: 560, margin: '0 auto', lineHeight: 1.65 }}>
            End-to-end automation from client requirement to confirmed trainer — no manual steps needed.
          </p>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit,minmax(270px,1fr))',
          gap: 20,
        }}>
          {FEATURES.map(f => {
            const Icon = f.icon
            return (
              <div key={f.title} style={{
                background: 'white', border: '1px solid #e2e8f0',
                borderRadius: 16, padding: '24px',
                boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
                transition: 'all 0.2s',
                cursor: 'default',
              }}
              onMouseOver={e => {
                e.currentTarget.style.boxShadow = '0 8px 24px -4px rgba(37,99,235,0.12)'
                e.currentTarget.style.borderColor = '#bfdbfe'
                e.currentTarget.style.transform = 'translateY(-2px)'
              }}
              onMouseOut={e => {
                e.currentTarget.style.boxShadow = '0 1px 4px rgba(0,0,0,0.05)'
                e.currentTarget.style.borderColor = '#e2e8f0'
                e.currentTarget.style.transform = 'translateY(0)'
              }}>
                <div style={{
                  width: 44, height: 44, borderRadius: 11,
                  background: f.bg, display: 'flex',
                  alignItems: 'center', justifyContent: 'center',
                  marginBottom: 16,
                }}>
                  <Icon size={20} color={f.color} />
                </div>
                <h3 style={{
                  fontFamily: "'Plus Jakarta Sans',sans-serif",
                  fontSize: 15, fontWeight: 700, color: '#0f172a',
                  margin: '0 0 8px', letterSpacing: '-0.02em',
                }}>{f.title}</h3>
                <p style={{ fontSize: 13.5, color: '#64748b', lineHeight: 1.6, margin: 0 }}>{f.desc}</p>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

/* ─── Pipeline Steps ───────────────────────────────────────── */
function PipelineSection() {
  return (
    <section style={{ padding: '80px 28px', background: 'white' }}>
      <div style={{ maxWidth: 1000, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 52 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: '#eff6ff', border: '1px solid #bfdbfe',
            borderRadius: 999, padding: '5px 14px', marginBottom: 16,
            fontSize: 11, fontWeight: 700, color: '#1d4ed8',
            textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>
            <Repeat2 size={11} /> 7-Stage Automation
          </div>
          <h2 style={{
            fontFamily: "'Plus Jakarta Sans',sans-serif",
            fontSize: 'clamp(26px,3.5vw,38px)', fontWeight: 800,
            letterSpacing: '-0.035em', color: '#0f172a', margin: '0 0 14px',
          }}>From requirement to invoice — automated</h2>
          <p style={{ fontSize: 16, color: '#64748b', maxWidth: 480, margin: '0 auto', lineHeight: 1.65 }}>
            Every stage tracked, every email automated, every step visible.
          </p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {PIPELINE_STEPS.map((step, i) => (
            <div key={step.num} style={{
              display: 'flex', alignItems: 'flex-start', gap: 20,
              background: '#f8faff', border: '1px solid #e2e8f0',
              borderRadius: 14, padding: '18px 22px',
              transition: 'all 0.15s',
            }}
            onMouseOver={e => { e.currentTarget.style.background='white'; e.currentTarget.style.borderColor='#bfdbfe'; e.currentTarget.style.boxShadow='0 4px 12px -2px rgba(37,99,235,0.10)' }}
            onMouseOut={e => { e.currentTarget.style.background='#f8faff'; e.currentTarget.style.borderColor='#e2e8f0'; e.currentTarget.style.boxShadow='none' }}>
              {/* Step number */}
              <div style={{
                width: 40, height: 40, borderRadius: 10,
                background: i === 0 ? '#2563eb' : '#eff6ff',
                color: i === 0 ? 'white' : '#2563eb',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontFamily: "'Plus Jakarta Sans',sans-serif",
                fontWeight: 800, fontSize: 13, flexShrink: 0,
              }}>{step.num}</div>
              <div>
                <div style={{
                  fontFamily: "'Plus Jakarta Sans',sans-serif",
                  fontSize: 15, fontWeight: 700, color: '#0f172a',
                  marginBottom: 4,
                }}>{step.title}</div>
                <div style={{ fontSize: 13.5, color: '#64748b', lineHeight: 1.55 }}>{step.desc}</div>
              </div>
              {i < PIPELINE_STEPS.length - 1 && (
                <div style={{ marginLeft: 'auto', flexShrink: 0 }}>
                  <ChevronRight size={16} color="#94a3b8" />
                </div>
              )}
              {i === PIPELINE_STEPS.length - 1 && (
                <div style={{ marginLeft: 'auto', flexShrink: 0 }}>
                  <CheckCircle size={16} color="#22c55e" />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}


/* ─── Quick Launch Modules ─────────────────────────────────── */
function ModulesSection({ onNavigate }) {
  return (
    <section style={{ padding: '80px 28px', background: '#f8faff' }}>
      <div style={{ maxWidth: 1000, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 44 }}>
          <h2 style={{
            fontFamily: "'Plus Jakarta Sans',sans-serif",
            fontSize: 'clamp(24px,3vw,34px)', fontWeight: 800,
            letterSpacing: '-0.035em', color: '#0f172a', margin: '0 0 12px',
          }}>Quick Access</h2>
          <p style={{ fontSize: 15, color: '#64748b' }}>Jump directly to any module</p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(130px,1fr))', gap: 14 }}>
          {MODULES.map(m => {
            const Icon = m.icon
            return (
              <button
                key={m.label}
                onClick={() => onNavigate(m.to)}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center',
                  gap: 10, padding: '20px 12px',
                  background: 'white', border: '1px solid #e2e8f0',
                  borderRadius: 14, cursor: 'pointer',
                  transition: 'all 0.15s', boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                }}
                onMouseOver={e => {
                  e.currentTarget.style.background = '#eff6ff'
                  e.currentTarget.style.borderColor = '#bfdbfe'
                  e.currentTarget.style.transform = 'translateY(-2px)'
                  e.currentTarget.style.boxShadow = '0 6px 16px -4px rgba(37,99,235,0.18)'
                }}
                onMouseOut={e => {
                  e.currentTarget.style.background = 'white'
                  e.currentTarget.style.borderColor = '#e2e8f0'
                  e.currentTarget.style.transform = 'translateY(0)'
                  e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.05)'
                }}
              >
                <div style={{
                  width: 44, height: 44, borderRadius: 11,
                  background: '#eff6ff', display: 'flex',
                  alignItems: 'center', justifyContent: 'center',
                }}>
                  <Icon size={20} color="#2563eb" />
                </div>
                <span style={{
                  fontFamily: "'Plus Jakarta Sans',sans-serif",
                  fontSize: 12, fontWeight: 700, color: '#0f172a',
                  textAlign: 'center', lineHeight: 1.3,
                }}>{m.label}</span>
              </button>
            )
          })}
        </div>
      </div>
    </section>
  )
}

/* ─── CTA Banner ───────────────────────────────────────────── */
function CTASection({ onGetStarted }) {
  return (
    <section style={{
      background: 'linear-gradient(135deg,#1d4ed8 0%,#2563eb 50%,#3b82f6 100%)',
      padding: '72px 28px',
    }}>
      <div style={{ maxWidth: 700, margin: '0 auto', textAlign: 'center' }}>
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          background: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.25)',
          borderRadius: 999, padding: '5px 14px', marginBottom: 22,
          fontSize: 11, fontWeight: 700, color: 'white',
          textTransform: 'uppercase', letterSpacing: '0.06em',
        }}>
          <Star size={11} /> Get Started Today
        </div>
        <h2 style={{
          fontFamily: "'Plus Jakarta Sans',sans-serif",
          fontSize: 'clamp(26px,4vw,44px)', fontWeight: 800,
          letterSpacing: '-0.04em', color: 'white', margin: '0 0 16px',
        }}>
          Ready to automate your<br />trainer operations?
        </h2>
        <p style={{ fontSize: 17, color: 'rgba(255,255,255,0.8)', margin: '0 0 36px', lineHeight: 1.6 }}>
          Start using TrainerSync today. AI matching, automated emails, and complete pipeline management from one dashboard.
        </p>
        <button
          onClick={onGetStarted}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 10,
            background: 'white', color: '#1d4ed8',
            padding: '14px 30px', borderRadius: 10, border: 'none',
            fontFamily: "'Plus Jakarta Sans',sans-serif",
            fontSize: 16, fontWeight: 800, cursor: 'pointer',
            boxShadow: '0 8px 28px -6px rgba(0,0,0,0.3)',
            transition: 'all 0.15s',
          }}
          onMouseOver={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 12px 36px -8px rgba(0,0,0,0.35)' }}
          onMouseOut={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 8px 28px -6px rgba(0,0,0,0.3)' }}
        >
          Open TrainerSync <ArrowRight size={18} />
        </button>
      </div>
    </section>
  )
}

/* ─── Footer ───────────────────────────────────────────────── */
function Footer() {
  return (
    <footer style={{
      background: '#0f172a', color: '#94a3b8',
      padding: '40px 28px',
    }}>
      <div style={{ maxWidth: 1160, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <BrandMark theme="dark" size="md" subtitle="Clahan Technologies" />
        <div style={{ fontSize: 13, color: '#475569', textAlign: 'right' }}>
          <div style={{ fontWeight: 600, color: '#64748b', marginBottom: 2 }}>TrainerSync Platform</div>
          <div>© {new Date().getFullYear()} Clahan Technologies. All rights reserved.</div>
        </div>
      </div>
    </footer>
  )
}

/* ─── Main Export ──────────────────────────────────────────── */
export default function Home() {
  const navigate = useNavigate()
  const goToDashboard = () => navigate('/dashboard')

  return (
    <div style={{ fontFamily: "'Inter',system-ui,sans-serif", background: '#f8faff' }}>
      {/* Navbar */}
      <nav style={{
        position: 'sticky', top: 0, zIndex: 100,
        background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(14px)',
        borderBottom: '1px solid #e2e8f0',
        boxShadow: '0 1px 8px rgba(0,0,0,0.04)',
      }}>
        <div style={{
          maxWidth: 1160, margin: '0 auto',
          padding: '0 28px', height: 62,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20,
        }}>
          <BrandMark size="md" />
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={goToDashboard}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                background: '#2563eb', color: 'white',
                padding: '8px 18px', borderRadius: 8, border: 'none',
                fontFamily: "'Plus Jakarta Sans',sans-serif",
                fontSize: 13.5, fontWeight: 700, cursor: 'pointer',
                boxShadow: '0 2px 8px -2px rgba(37,99,235,0.4)',
                transition: 'all 0.15s',
              }}
              onMouseOver={e => { e.currentTarget.style.background = '#1d4ed8' }}
              onMouseOut={e => { e.currentTarget.style.background = '#2563eb' }}
            >
              Open App <ArrowRight size={14} />
            </button>
          </div>
        </div>
      </nav>

      <Hero onGetStarted={goToDashboard} />
      <FeaturesSection />
      <PipelineSection />
      <ModulesSection onNavigate={navigate} />
      <CTASection onGetStarted={goToDashboard} />
      <Footer />
    </div>
  )
}
