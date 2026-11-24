// Home.jsx – TrainerSync · Clahan Technologies
// Professional SaaS Operations Home Page
// Uses: lucide-react, react-router-dom, inline styles only (Tailwind-free for portability)

import { useState, useEffect, useRef, useCallback } from 'react'
import PropTypes from 'prop-types'
import { useNavigate } from 'react-router-dom'
import BrandMark from '../components/BrandMark'
import {
  ArrowRight, CheckCircle, Play,
  Brain, Mail, MessageSquare,
  Shield, ChevronRight,
  Filter, Send, Calendar, Sparkles,
  Inbox, FileText, UserCheck, PhoneCall,
  Bell, Search,
  RefreshCw, Layers,
  AlertCircle,
  Cpu,
  MailCheck, MailOpen, Reply,
  Award, Repeat2,
  BotMessageSquare,
  SquareKanban, Webhook, CloudCog,
  LayoutDashboard, Linkedin, Video
} from 'lucide-react'

// ─── Design Tokens ───────────────────────────────────────────
const T = {
  // Neutrals
  bg: '#F7F8FA',
  surface: '#FFFFFF',
  border: '#E5E8EE',
  borderLight: '#F0F2F5',
  // Text
  textPrimary: '#0D1117',
  textSecondary: '#5A6478',
  textMuted: '#9CA3B4',
  // Brand
  brand: '#1A56DB',
  brandDark: '#1042B8',
  brandLight: '#EEF3FD',
  brandMid: '#3B74F5',
  // Accents
  sky: '#0EA5E9',
  skyLight: '#E0F2FE',
  teal: '#0D9488',
  tealLight: '#CCFBF1',
  violet: '#7C3AED',
  violetLight: '#EDE9FE',
  pink: '#DB2777',
  pinkLight: '#FCE7F3',
  amber: '#D97706',
  amberLight: '#FEF3C7',
  green: '#059669',
  greenLight: '#D1FAE5',
  red: '#DC2626',
  redLight: '#FEE2E2',
  orange: '#EA580C',
  orangeLight: '#FFEDD5',
  // Shadows
  shadow: '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
  shadowMd: '0 4px 12px rgba(0,0,0,0.07), 0 1px 3px rgba(0,0,0,0.04)',
  shadowLg: '0 12px 32px rgba(0,0,0,0.09), 0 2px 6px rgba(0,0,0,0.04)',
  shadowXl: '0 24px 56px rgba(0,0,0,0.1), 0 4px 12px rgba(0,0,0,0.05)',
}

// ─── Inline CSS ───────────────────────────────────────────────
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body { font-family: 'DM Sans', sans-serif; background: ${T.bg}; color: ${T.textPrimary}; overflow-x: hidden; }

  ::selection { background: ${T.brandLight}; color: ${T.brand}; }

  /* scrollbar */
  html { scrollbar-width: thin; scrollbar-color: #94A3B8 #EDF2F7; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: #EDF2F7; }
  ::-webkit-scrollbar-thumb { background: #94A3B8; border: 2px solid #EDF2F7; border-radius: 999px; }
  ::-webkit-scrollbar-thumb:hover { background: #64748B; }

  /* animations */
  @keyframes fadeUp   { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }
  @keyframes fadeIn   { from { opacity:0; } to { opacity:1; } }
  @keyframes slideLeft{ from { opacity:0; transform:translateX(-20px); } to { opacity:1; transform:translateX(0); } }
  @keyframes slideRight{from { opacity:0; transform:translateX(20px); } to { opacity:1; transform:translateX(0); } }
  @keyframes scaleIn  { from { opacity:0; transform:scale(0.95); } to { opacity:1; transform:scale(1); } }
  @keyframes ping     { 0%{transform:scale(1);opacity:0.7} 100%{transform:scale(2);opacity:0} }
  /* Ticker animation removed */
  @keyframes workflowAccent {
    0%, 12% { transform: scaleX(1); opacity: 1; }
    18%, 100% { transform: scaleX(0.16); opacity: 0.28; }
  }
  @keyframes pulse2   { 0%,100%{opacity:1} 50%{opacity:0.5} }
  @keyframes shimmer  { 0%{background-position:-400px 0} 100%{background-position:400px 0} }
  @keyframes floatUp  { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
  @keyframes barFill  { from{width:0} to{width:var(--w)} }
  @keyframes countUp  { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
  @keyframes borderAnim { 0%{border-color:${T.brand}40} 50%{border-color:${T.brand}} 100%{border-color:${T.brand}40} }
  @keyframes dotBlink { 0%,100%{opacity:1} 50%{opacity:0.2} }
  @keyframes workflowCardRun {
    0%, 12% {
      border-color: var(--workflow-color);
      background-color: rgba(255,255,255,0.98);
      box-shadow: 0 0 0 4px var(--workflow-glow), 0 0 0 7px var(--workflow-color);
      transform: scale(1.015);
    }
    18%, 100% {
      border-color: var(--workflow-ring);
      background-color: rgba(255,255,255,0.94);
      box-shadow: 0 0 0 4px var(--workflow-soft), 0 0 0 7px var(--workflow-ring);
      transform: scale(1);
    }
  }
  @keyframes workflowIconRun {
    0%, 12% { background: var(--workflow-soft); box-shadow: 0 8px 20px var(--workflow-soft); transform: scale(1.06); }
    18%, 100% { background: ${T.surface}; box-shadow: none; transform: scale(1); }
  }
  @keyframes workflowNumberRun {
    0%, 12% { box-shadow: 0 0 0 6px var(--workflow-soft), 0 8px 18px var(--workflow-soft); transform: scale(1.1); }
    18%, 100% { box-shadow: 0 8px 18px var(--workflow-soft); transform: scale(1); }
  }
  @keyframes workflowConnectorRun {
    0%, 12% { opacity: 1; transform: translateY(-50%) scaleX(1); }
    18%, 100% { opacity: 0.25; transform: translateY(-50%) scaleX(0.35); }
  }
  @keyframes workflowStateRun {
    0%, 12% { box-shadow: 0 6px 16px var(--workflow-soft); transform: translateY(-1px); }
    18%, 100% { box-shadow: none; transform: translateY(0); }
  }
  @keyframes workflowStatusDot {
    0%, 12% { box-shadow: 0 0 0 6px var(--workflow-soft); transform: scale(1.28); }
    18%, 100% { box-shadow: 0 0 0 4px var(--workflow-soft); transform: scale(1); }
  }
  @keyframes workflowMessageIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes aiScanLine {
    0% { transform: translateX(-22%); opacity: 0; }
    12% { opacity: 1; }
    50% { opacity: 1; }
    100% { transform: translateX(122%); opacity: 0; }
  }
  @keyframes aiSignalPulse {
    0%, 100% { transform: scale(1); opacity: 0.62; }
    50% { transform: scale(1.08); opacity: 1; }
  }
  @keyframes aiMatchFill {
    0% { width: 18%; }
    42% { width: 76%; }
    100% { width: var(--ai-width); }
  }

  .fade-up   { animation: fadeUp  0.6s cubic-bezier(0.22,1,0.36,1) both; }
  .fade-in   { animation: fadeIn  0.5s ease both; }
  .slide-l   { animation: slideLeft  0.6s cubic-bezier(0.22,1,0.36,1) both; }
  .slide-r   { animation: slideRight 0.6s cubic-bezier(0.22,1,0.36,1) both; }
  .scale-in  { animation: scaleIn 0.5s cubic-bezier(0.22,1,0.36,1) both; }
  .float-up  { animation: floatUp 3s ease-in-out infinite; }
  .pulse2    { animation: pulse2 2s ease-in-out infinite; }

  /* Hover states */
  .card-hover { transition: box-shadow 0.2s, transform 0.2s, border-color 0.2s; }
  .card-hover:hover { box-shadow: ${T.shadowLg}; transform: translateY(-2px); border-color: ${T.brand}30; }

  .btn-primary {
    display: inline-flex; align-items: center; gap: 7px;
    background: ${T.brand}; color: #fff; border: none; cursor: pointer;
    font-family: 'DM Sans', sans-serif; font-size: 16px; font-weight: 600;
    padding: 10px 20px; border-radius: 8px;
    box-shadow: 0 1px 2px rgba(26,86,219,0.18), inset 0 1px 0 rgba(255,255,255,0.12);
    transition: all 0.18s;
  }
  .btn-primary:hover { background: ${T.brandDark}; box-shadow: 0 4px 16px rgba(26,86,219,0.28); transform: translateY(-1px); }
  .btn-primary:active { transform: translateY(0); }

  .btn-secondary {
    display: inline-flex; align-items: center; gap: 7px;
    background: ${T.surface}; color: ${T.textPrimary}; border: 1.5px solid ${T.border};
    cursor: pointer; font-family: 'DM Sans', sans-serif; font-size: 16px; font-weight: 600;
    padding: 10px 20px; border-radius: 8px;
    transition: all 0.18s;
  }
  .btn-secondary:hover { border-color: ${T.brand}; color: ${T.brand}; background: ${T.brandLight}; transform: translateY(-1px); }

  .nav-link {
    font-size: 14.5px; font-weight: 500; color: ${T.textSecondary};
    text-decoration: none; padding: 5px 10px; border-radius: 6px;
    transition: all 0.15s;
  }
  .nav-link:hover { color: ${T.textPrimary}; background: ${T.borderLight}; }

  .badge {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 12.5px; font-weight: 600; padding: 2px 8px;
    border-radius: 100px; letter-spacing: 0.01em;
  }

  /* Status dots */
  .dot-green { width:7px; height:7px; border-radius:50%; background:#22C55E; display:inline-block; flex-shrink:0; }
  .dot-amber { width:7px; height:7px; border-radius:50%; background:#F59E0B; display:inline-block; flex-shrink:0; }
  .dot-blue  { width:7px; height:7px; border-radius:50%; background:${T.brand}; display:inline-block; flex-shrink:0; }
  .dot-red   { width:7px; height:7px; border-radius:50%; background:#EF4444; display:inline-block; flex-shrink:0; }
  .dot-gray  { width:7px; height:7px; border-radius:50%; background:#9CA3AF; display:inline-block; flex-shrink:0; }

  /* Live ping */
  .live-ping { position:relative; display:inline-flex; }
  .live-ping::before {
    content:''; position:absolute; inset:-2px; border-radius:50%;
    background:#22C55E; animation: ping 1.5s ease-out infinite; opacity:0.4;
  }

  /* Ticker CSS removed for reduced bundle size */

  /* First screen: navigation + hero */
  .hero-stage {
    height: 100svh;
    min-height: 640px;
    padding-top: 56px;
    display: grid;
    grid-template-rows: minmax(0, 1fr) auto;
    overflow: hidden;
    background:
      radial-gradient(circle at 76% 32%, rgba(26,86,219,0.10), transparent 32%),
      ${T.bg};
  }
  .hero-main {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px 28px 18px;
    display: flex;
    align-items: center;
    min-height: 0;
  }
  .hero-grid {
    width: 100%;
    display: grid;
    grid-template-columns: minmax(0, 0.95fr) minmax(420px, 1.05fr);
    gap: clamp(28px, 4vw, 56px);
    align-items: center;
  }
  .hero-image-panel { min-height: clamp(480px, 70vh, 600px); }

  /* Feature scroller */
  .feature-scroll-shell {
    position: relative;
    overflow-x: auto;
    overflow-y: hidden;
    scroll-snap-type: x mandatory;
    scrollbar-width: none;
    scrollbar-color: ${T.brand}35 ${T.borderLight};
    overscroll-behavior-inline: contain;
    touch-action: pan-x;
    cursor: grab;
    padding: 6px 2px 18px;
    -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 22px, #000 calc(100% - 22px), transparent 100%);
    mask-image: linear-gradient(90deg, transparent 0, #000 22px, #000 calc(100% - 22px), transparent 100%);
  }
  .feature-scroll-shell::-webkit-scrollbar { display: none; }
  .feature-scroll-shell:active { cursor: grabbing; }
  .feature-scroll-shell:focus-visible { outline: 2px solid ${T.brand}55; outline-offset: 4px; border-radius: 8px; }
  .feature-scroll-track {
    display: flex;
    align-items: stretch;
    gap: 14px;
    width: max-content;
    padding: 0 22px;
  }
  .feature-scroll-card {
    flex: 0 0 288px;
    width: 288px;
    max-width: 78vw;
    height: 375px;
    scroll-snap-align: start;
    scroll-snap-stop: always;
  }
  .feature-card-inner {
    height: 100%;
    overflow: hidden;
  }

  /* Workflow command center */
  .workflow-shell {
    position: relative;
    display: grid;
    gap: 10px;
    margin-top: 8px;
  }
  .workflow-heading > div { margin-bottom: 22px !important; }
  .workflow-heading h2 { font-size: clamp(1.65rem, 3.2vw, 2.3rem) !important; margin-bottom: 7px !important; }
  .workflow-heading p { font-size: 15px !important; line-height: 1.45 !important; }
  .workflow-panel {
    position: relative;
    min-width: 0;
    border: 0;
    background: transparent;
    box-shadow: none;
    overflow: visible;
  }
  .workflow-panel::before {
    display: none;
  }
  .workflow-panel-head {
    position: relative;
    z-index: 1;
    padding: 8px 18px 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .workflow-panel-kicker {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: ${T.textSecondary};
    font-size: 12px;
    font-weight: 800;
  }
  .workflow-live {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    min-height: 24px;
    padding: 3px 9px;
    border-radius: 999px;
    border: 1px solid rgba(5,150,105,0.18);
    background: ${T.greenLight};
    color: ${T.green};
    font-size: 11px;
    font-weight: 800;
    white-space: nowrap;
  }
  .workflow-live span {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: ${T.green};
    box-shadow: 0 0 0 5px rgba(5,150,105,0.12);
    animation: dotBlink 1.4s ease-in-out infinite;
  }
  .workflow-flow-scroll {
    min-width: 0;
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
  }
  .workflow-flow-scroll::-webkit-scrollbar { display: none; }
  .workflow-grid {
    position: relative;
    z-index: 1;
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 30px;
    padding: 18px 24px 22px;
    overflow: visible;
  }
  .workflow-step {
    position: relative;
    min-width: 0;
    display: flex;
    --workflow-soft: rgba(26,86,219,0.10);
    --workflow-duration: 11.9s;
  }
  .workflow-step::after {
    content: '';
    position: absolute;
    left: 100%;
    top: 50%;
    width: 30px;
    height: 2px;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--workflow-color), ${T.brand}55);
    transform: translateY(-50%) scaleX(0.35);
    transform-origin: left center;
    animation: workflowConnectorRun var(--workflow-duration) ease-in-out infinite;
    animation-delay: var(--workflow-delay);
  }
  .workflow-step:last-child::after { display: none; }
  .workflow-card {
    width: 100%;
    height: 166px;
    background: rgba(255,255,255,0.92);
    border: 3px solid var(--workflow-ring);
    border-radius: 8px;
    padding: 17px 8px 10px;
    position: relative;
    cursor: default;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    overflow: visible;
    box-shadow: 0 0 0 4px var(--workflow-soft), 0 0 0 7px var(--workflow-ring);
    animation: workflowCardRun var(--workflow-duration) cubic-bezier(0.22,1,0.36,1) infinite;
    animation-delay: var(--workflow-delay);
    will-change: background-color, border-color, box-shadow, transform;
  }
  .workflow-card::before {
    content: '';
    position: absolute;
    left: 12px;
    right: 12px;
    top: 0;
    height: 3px;
    border-radius: 0 0 999px 999px;
    background: var(--workflow-color);
    transform-origin: center;
    animation: workflowAccent var(--workflow-duration) ease-in-out infinite;
    animation-delay: var(--workflow-delay);
    z-index: 2;
  }
  .workflow-number {
    position: absolute;
    left: 9px;
    top: 9px;
    transform: scale(1);
    background: var(--workflow-color);
    color: #fff;
    font-size: 11px;
    font-weight: 800;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 8px 18px var(--workflow-soft);
    animation: workflowNumberRun var(--workflow-duration) ease-in-out infinite;
    animation-delay: var(--workflow-delay);
    z-index: 2;
  }
  .workflow-icon {
    width: 34px;
    height: 34px;
    border-radius: 9px;
    background: ${T.surface};
    border: 1px solid var(--workflow-soft);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    animation: workflowIconRun var(--workflow-duration) ease-in-out infinite;
    animation-delay: var(--workflow-delay);
  }
  .workflow-copy {
    min-width: 0;
    width: 100%;
    display: flex;
    flex: 1;
    flex-direction: column;
    align-items: center;
    position: relative;
    z-index: 1;
  }
  .workflow-title {
    min-height: 27px;
    margin-top: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13.5px;
    font-weight: 800;
    color: ${T.textPrimary};
    line-height: 1.22;
  }
  .workflow-desc {
    min-height: 36px;
    font-size: 11px;
    color: ${T.textMuted};
    line-height: 1.3;
    overflow-wrap: anywhere;
  }
  .workflow-step-state {
    margin-top: auto;
    min-height: 22px;
    padding: 4px 6px;
    border-radius: 999px;
    background: var(--workflow-soft);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    color: var(--workflow-color);
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    white-space: nowrap;
    position: relative;
    z-index: 1;
    animation: workflowStateRun var(--workflow-duration) ease-in-out infinite;
    animation-delay: var(--workflow-delay);
  }
  .workflow-step-state span {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--workflow-color);
    box-shadow: 0 0 0 4px var(--workflow-soft);
    animation: workflowStatusDot var(--workflow-duration) ease-in-out infinite;
    animation-delay: var(--workflow-delay);
  }
  .workflow-conversation {
    position: relative;
    z-index: 1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
    padding: 10px 18px 4px;
  }
  .workflow-message-card {
    background: rgba(255,255,255,0.94);
    border: 1px solid ${T.border};
    border-left: 4px solid var(--message-color);
    border-radius: 8px;
    padding: 10px;
    min-height: 122px;
    box-shadow: ${T.shadow};
    animation: workflowMessageIn 0.6s cubic-bezier(0.22,1,0.36,1) both;
    animation-delay: var(--message-delay);
    display: flex;
    flex-direction: column;
  }
  .workflow-message-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 6px;
  }
  .workflow-message-person {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .workflow-message-avatar {
    width: 26px;
    height: 26px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-size: 11px;
    font-weight: 800;
    flex-shrink: 0;
    background: var(--message-color);
  }
  .workflow-message-text {
    font-size: 11px;
    line-height: 1.4;
    color: ${T.textSecondary};
    margin: 0;
  }
  .workflow-message-action {
    margin-top: auto;
    padding-top: 7px;
    display: flex;
    align-items: center;
    gap: 7px;
    color: var(--message-color);
    font-size: 10px;
    font-weight: 700;
  }
  .ai-mini-panel {
    margin-top: 15px;
    border-radius: 12px;
    border: 1px solid rgba(37,99,235,0.14);
    background: linear-gradient(180deg, rgba(238,243,253,0.78), rgba(255,255,255,0.92));
    padding: 12px;
    overflow: hidden;
    position: relative;
  }
  .ai-mini-panel::before {
    content: '';
    position: absolute;
    inset: 0;
    width: 42%;
    background: linear-gradient(90deg, transparent, rgba(26,86,219,0.12), transparent);
    animation: aiScanLine 3.4s ease-in-out infinite;
    pointer-events: none;
  }
  .ai-signal-row {
    position: relative;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 7px;
  }
  .ai-signal {
    border-radius: 10px;
    background: rgba(255,255,255,0.84);
    border: 1px solid rgba(226,232,240,0.92);
    padding: 8px;
    animation: aiSignalPulse 2.8s ease-in-out infinite;
    animation-delay: var(--ai-delay);
  }
  .ai-signal-label {
    display: block;
    font-size: 10px;
    font-weight: 800;
    color: ${T.textMuted};
    text-transform: uppercase;
  }
  .ai-signal-value {
    display: block;
    margin-top: 2px;
    font-size: 12px;
    font-weight: 800;
    color: ${T.textPrimary};
  }
  .ai-match-bar {
    position: relative;
    margin-top: 10px;
    height: 6px;
    overflow: hidden;
    border-radius: 999px;
    background: rgba(148,163,184,0.22);
  }
  .ai-match-bar span {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, ${T.brand}, ${T.teal});
    animation: aiMatchFill 3.4s ease-in-out infinite;
  }

  /* Mono font */
  .mono { font-family:'Geist Mono',monospace; }

  /* Section label */
  .section-label {
    display:inline-flex; align-items:center; gap:6px;
    background:${T.brandLight}; color:${T.brand};
    font-size:11.5px; font-weight:700; letter-spacing:0.06em; text-transform:uppercase;
    padding:5px 12px; border-radius:100px;
    border: 1px solid ${T.brand}20;
  }

  /* Integration icon card */
  .int-card {
    width:52px; height:52px; border-radius:14px;
    background:white; border:1.5px solid ${T.border};
    display:flex; align-items:center; justify-content:center;
    box-shadow:${T.shadow}; transition: all 0.2s;
    font-size:22px;
  }
  .int-card:hover { border-color:${T.brand}40; box-shadow:${T.shadowMd}; transform:translateY(-2px); }

  .integration-layout {
    min-height: 520px;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    perspective: 1100px;
    overflow: hidden;
  }
  .integration-cycle {
    width: min(920px, 94vw);
    height: min(560px, 66vw);
    min-height: 430px;
    position: relative;
    transform-style: preserve-3d;
    animation: floatUp 5s ease-in-out infinite;
  }
  .integration-cycle-svg {
    position: absolute;
    inset: 4%;
    width: 92%;
    height: 92%;
    overflow: visible;
    transform: rotateX(58deg) rotateZ(-8deg);
    filter: drop-shadow(0 22px 28px rgba(13,17,23,0.14));
  }
  .integration-cycle-svg ellipse {
    fill: none;
    stroke: rgba(26,86,219,0.26);
    stroke-width: 2.5;
    stroke-linecap: round;
  }
  .integration-cycle-svg .chain-dash {
    stroke: rgba(13,148,136,0.42);
    stroke-width: 7;
    stroke-dasharray: 10 18;
    animation: chainDash 16s linear infinite;
  }
  .integration-logo-node {
    position: absolute;
    left: var(--x);
    top: var(--y);
    width: 132px;
    height: 88px;
    border-radius: 24px;
    transform: translate(-50%, -50%) translateZ(var(--z)) scale(var(--scale));
    background: rgba(255,255,255,0.9);
    border: 1px solid rgba(229,232,238,0.95);
    box-shadow: 0 18px 42px rgba(13,17,23,0.16), inset 0 1px 0 rgba(255,255,255,0.9);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    transition: transform 0.25s, box-shadow 0.25s;
  }
  .integration-logo-node:hover {
    transform: translate(-50%, -50%) translateZ(calc(var(--z) + 34px)) scale(calc(var(--scale) + 0.08));
    box-shadow: 0 28px 60px rgba(13,17,23,0.22), inset 0 1px 0 rgba(255,255,255,0.95);
  }
  .integration-logo-node::after {
    content: '';
    position: absolute;
    inset: 8px;
    border-radius: 18px;
    background: var(--bg);
    z-index: -1;
  }
  .integration-logo-label {
    color: ${T.textPrimary};
    font-size: 12.5px;
    font-weight: 800;
    line-height: 1;
    white-space: nowrap;
  }
  .integration-core-node {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 104px;
    height: 104px;
    border-radius: 32px;
    transform: translate(-50%, -50%) translateZ(90px);
    background: ${T.brand};
    box-shadow: 0 28px 70px rgba(26,86,219,0.34), inset 0 1px 0 rgba(255,255,255,0.22);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .integration-spoke {
    position: absolute;
    left: 50%;
    top: 50%;
    width: var(--len);
    height: 2px;
    background: linear-gradient(90deg, rgba(26,86,219,0.38), rgba(26,86,219,0));
    transform-origin: left center;
    transform: rotate(var(--angle)) translateZ(20px);
    border-radius: 999px;
  }
  @keyframes chainDash {
    from { stroke-dashoffset: 0; }
    to { stroke-dashoffset: -220; }
  }

  .tools-zigzag-scroll {
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
  }
  .tools-zigzag-scroll::-webkit-scrollbar { display: none; }
  .tools-zigzag {
    position: relative;
    min-width: 1200px;
    height: 270px;
    display: grid;
    grid-template-columns: repeat(8, minmax(0, 1fr));
    gap: 20px;
    padding: 0 34px;
  }
  .tools-zigzag-lines {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    z-index: 0;
  }
  .tools-zigzag-path-base {
    fill: none;
    stroke: ${T.border};
    stroke-width: 4;
    stroke-linecap: round;
    stroke-linejoin: round;
    vector-effect: non-scaling-stroke;
  }
  .tools-zigzag-path-active {
    fill: none;
    stroke: url(#tools-zigzag-gradient);
    stroke-width: 3;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-dasharray: 10 11;
    vector-effect: non-scaling-stroke;
    filter: drop-shadow(0 0 5px rgba(26,86,219,0.26));
    animation: chainDash 5s linear infinite;
  }
  .tools-zigzag-node {
    position: relative;
    z-index: 1;
    height: 112px;
    transform: translateY(var(--zig-y));
    border: 1.5px solid var(--tool-color);
    border-radius: 18px;
    background: rgba(255,255,255,0.97);
    box-shadow: 0 0 0 5px #fff, 0 10px 28px rgba(15,23,42,0.08), 0 0 22px var(--tool-soft);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 14px;
    transition: transform 0.22s ease, box-shadow 0.22s ease;
  }
  .tools-zigzag-node:hover {
    transform: translateY(calc(var(--zig-y) - 5px));
    box-shadow: 0 0 0 5px #fff, 0 16px 34px rgba(15,23,42,0.12), 0 0 30px var(--tool-soft);
  }
  .tools-zigzag-icon {
    width: 48px;
    height: 48px;
    border-radius: 15px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .tools-zigzag-name {
    color: ${T.textPrimary};
    font-size: 13px;
    font-weight: 800;
    line-height: 1.15;
    text-align: center;
  }

  /* Pipeline step */
  .pipe-step-active { animation: borderAnim 2s ease-in-out infinite; }

  /* Responsive */
  @media(max-width:1100px){
    .hero-grid { grid-template-columns: minmax(0, 0.95fr) minmax(380px, 1.05fr); gap: 30px; }
    .workflow-grid { gap: 22px; padding-inline: 18px; }
    .workflow-card { padding-inline: 8px; }
    .workflow-step-state { padding-inline: 7px; font-size: 9px; }
  }
  @media(max-width:900px){
    .hero-stage { height: auto; min-height: auto; overflow: visible; }
    .hero-main { padding-top: 42px; padding-bottom: 42px; }
    .hero-grid { grid-template-columns: 1fr; }
    .hero-image-panel { min-height: 480px; }
    .workflow-grid { min-width: 1120px; gap: 30px; padding-inline: 24px; }
    .workflow-card { padding-inline: 11px; }
    .workflow-step-state { padding-inline: 9px; font-size: 10px; }
  }
  @media(max-width:768px){
    .hide-mobile { display:none !important; }
    .cols-mobile-1 { grid-template-columns: 1fr !important; }
    .cols-mobile-2 { grid-template-columns: repeat(2,1fr) !important; }
    .hero-main { padding: 34px 20px; }
    .hero-image-panel { min-height: 430px; border-radius: 22px !important; }
    .feature-scroll-card { flex-basis: min(270px, 80vw); width: min(270px, 80vw); height: 385px; }
    .workflow-shell { gap: 16px; }
    .workflow-panel-head { padding: 15px 15px 0; }
    .workflow-conversation { padding: 10px; }
    .integration-layout { min-height: 420px; }
    .integration-cycle { height: 420px; }
    .integration-logo-node { width: 104px; height: 76px; border-radius: 20px; }
    .integration-logo-label { font-size: 11.5px; }
    .integration-core-node { width: 86px; height: 86px; border-radius: 26px; }
  }
  @media(max-width:480px){
    .cols-mobile-2 { grid-template-columns: 1fr !important; }
    .hero-main { padding-inline: 16px; }
    .hero-image-panel { min-height: 390px; }
    .workflow-panel-head { align-items: flex-start; flex-direction: column; }
    .feature-scroll-card { height: 395px; }
  }
  @media(max-width:600px){
    .workflow-conversation { grid-template-columns: 1fr; }
    .workflow-message-card { min-height: 0; }
  }
  @media(prefers-reduced-motion: reduce){
    .tools-zigzag-path-active { animation: none; }
    .workflow-card,
    .workflow-icon,
    .workflow-number,
    .workflow-step::after,
    .workflow-message-card,
    .workflow-card::before,
    .workflow-step-state,
    .workflow-step-state span,
    .ai-mini-panel::before,
    .ai-signal,
    .ai-match-bar span { animation: none; }
  }
`

// ─── Utility Components ───────────────────────────────────────
function Card({ children, style, className = '', onClick }) {
  return (
    <button
      onClick={onClick}
      className={`card-hover ${className}`}
      style={{
        background: T.surface, border: `1px solid ${T.border}`,
        borderRadius: 12, overflow: 'hidden',
        boxShadow: T.shadow, ...style, cursor: 'pointer'
      }}
    >
      {children}
    </button>
  )
}

Card.propTypes = {
  children: PropTypes.node.isRequired,
  style: PropTypes.object,
  className: PropTypes.string,
  onClick: PropTypes.func,
}

function Badge({ children, color = T.brand, bg, style }) {
  return (
    <span className="badge" style={{ color, background: bg || `${color}15`, ...style }}>
      {children}
    </span>
  )
}

Badge.propTypes = {
  children: PropTypes.node.isRequired,
  color: PropTypes.string,
  bg: PropTypes.string,
  style: PropTypes.object,
}

function SectionLabel({ icon: Icon, children }) {
  return (
    <div className="section-label">
      {Icon && <Icon size={12} />}
      {children}
    </div>
  )
}

SectionLabel.propTypes = {
  icon: PropTypes.elementType,
  children: PropTypes.node.isRequired,
}

function SectionHeader({ label, labelIcon, title, sub, center }) {
  const textAlign = center ? 'center' : 'left'
  const justify = center ? 'center' : 'flex-start'
  const maxWidth = center ? 560 : '100%'
  const margin = center ? '0 auto' : 0
  
  return (
    <div style={{ textAlign, marginBottom: 48 }}>
      {label && <div style={{ marginBottom: 12, display: 'flex', justifyContent: justify }}>
        <SectionLabel icon={labelIcon}>{label}</SectionLabel>
      </div>}
      <h2 style={{ fontSize: 'clamp(1.9rem,3.8vw,2.6rem)', fontWeight: 700, color: T.textPrimary, lineHeight: 1.2, marginBottom: 10 }}>
        {title}
      </h2>
      {sub && <p style={{ fontSize: 15.5, color: T.textSecondary, maxWidth, margin, lineHeight: 1.65 }}>
        {sub}
      </p>}
    </div>
  )
}

SectionHeader.propTypes = {
  label: PropTypes.string,
  labelIcon: PropTypes.elementType,
  title: PropTypes.string.isRequired,
  sub: PropTypes.string,
  center: PropTypes.bool,
}

// ─── Animated Counter ─────────────────────────────────────────
function StatusBadge({ status }) {
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '3px 9px', borderRadius: 100, background: T.brandLight, color: T.brand }}>
      {status}
    </span>
  )
}

StatusBadge.propTypes = {
  status: PropTypes.string.isRequired,
}

// ─── Live Activity Feed ───────────────────────────────────────
// ─── Stat Card ────────────────────────────────────────────────
// ─── Pipeline Stages ─────────────────────────────────────────
const PIPELINE_STAGES = [
  { n: '01', label: 'First Contact',       icon: Send,        color: T.brand,  desc: 'Initial email + WhatsApp outreach to matched trainers' },
  { n: '02', label: 'Details Request',     icon: FileText,    color: T.sky,    desc: 'Request profile, rate, availability & domain details' },
  { n: '03', label: 'Slot Booking',        icon: Calendar,    color: T.violet, desc: 'Send slot options and collect interview availability' },
  { n: '04', label: 'Interview',           icon: PhoneCall,   color: T.teal,   desc: 'Conduct interview via Google Meet or Microsoft Teams' },
  { n: '05', label: 'Selection',           icon: UserCheck,   color: T.green,  desc: 'Select or reject trainer and notify via email' },
  { n: '06', label: 'ToC / Agenda',        icon: Award,       color: T.amber,  desc: 'Request terms of contract and training agenda' },
  { n: '07', label: 'Confirmation',        icon: CheckCircle, color: T.green,  desc: 'Final training confirmation and calendar sync' },
]

function PipelineSection() {
  const [active, setActive] = useState(0)
  const [running, setRunning] = useState(true)
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setActive(a => (a + 1) % PIPELINE_STAGES.length), 2400)
    return () => clearInterval(t)
  }, [running])

  const s = PIPELINE_STAGES[active]
  return (
    <div>
      {/* Stage dots */}
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${PIPELINE_STAGES.length}, 1fr)`, gap: 4, marginBottom: 24, position: 'relative' }}>
        {/* Track line */}
        <div style={{ position: 'absolute', top: 19, left: '6%', right: '6%', height: 2, background: T.borderLight, zIndex: 0 }} />
        <div style={{ position: 'absolute', top: 19, left: '6%', height: 2, background: `linear-gradient(90deg, ${T.brand}, ${s.color})`, zIndex: 0, width: `${(active / (PIPELINE_STAGES.length - 1)) * 88}%`, transition: 'width 0.5s ease' }} />

        {PIPELINE_STAGES.map((st, i) => {
          const done = i < active, curr = i === active
          let bgColor, iconColor, textColor
          if (curr) {
            bgColor = st.color
            iconColor = '#fff'
            textColor = st.color
          } else if (done) {
            bgColor = `${st.color}20`
            iconColor = st.color
            textColor = st.color
          } else {
            bgColor = T.surface
            iconColor = T.textMuted
            textColor = T.textMuted
          }
          const iconSize = curr || done ? 15 : 14
          return (
            <button key={`stage-${i}-${st.label}`} onClick={() => { setActive(i); setRunning(false) }}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', zIndex: 1 }}>
              <div style={{
                width: 38, height: 38, borderRadius: '50%',
                background: bgColor,
                border: `2px solid ${curr || done ? st.color : T.border}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transform: curr ? 'scale(1.18)' : 'scale(1)',
                boxShadow: curr ? `0 0 0 5px ${st.color}18, 0 4px 16px ${st.color}30` : 'none',
                transition: 'all 0.35s cubic-bezier(0.34,1.56,0.64,1)'
              }}>
                <st.icon size={iconSize} color={iconColor} />
              </div>
              <span style={{ fontSize: 10, fontWeight: 600, color: textColor, textAlign: 'center', lineHeight: 1.2 }} className="hide-mobile">
                {st.label}
              </span>
            </button>
          )
        })}
      </div>

      {/* Active stage detail */}
      <div style={{ background: `${s.color}08`, border: `1.5px solid ${s.color}25`, borderRadius: 12, padding: '18px 20px', transition: 'all 0.3s ease' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 10 }}>
          <div style={{ width: 44, height: 44, borderRadius: 12, background: s.color, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 6px 18px ${s.color}35`, flexShrink: 0 }}>
            <s.icon size={20} color="#fff" />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: T.textMuted }} className="mono">STAGE {s.n}</span>
              <span style={{ width: 4, height: 4, borderRadius: '50%', background: T.textMuted, display: 'inline-block' }} />
              <span style={{ fontSize: 14.5, fontWeight: 700, color: T.textPrimary }}>{s.label}</span>
              <span style={{ marginLeft: 4, fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 100, background: s.color, color: '#fff' }}>ACTIVE</span>
            </div>
            <p style={{ fontSize: 13, color: T.textSecondary, margin: '3px 0 0' }}>{s.desc}</p>
          </div>
        </div>
        {/* Progress bar */}
        <div style={{ height: 4, background: `${s.color}15`, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${((active + 1) / PIPELINE_STAGES.length) * 100}%`, background: s.color, borderRadius: 4, transition: 'width 0.5s ease' }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 5 }}>
          <span style={{ fontSize: 11, color: T.textMuted }}>Pipeline completion</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: s.color }} className="mono">{Math.round(((active + 1) / PIPELINE_STAGES.length) * 100)}%</span>
        </div>
      </div>

      <button onClick={() => { setActive(0); setRunning(true) }}
        style={{ marginTop: 10, background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: T.textMuted, display: 'flex', alignItems: 'center', gap: 4, fontFamily: 'DM Sans, sans-serif', transition: 'color 0.15s' }}
        onMouseEnter={e => e.currentTarget.style.color = T.brand}
        onMouseLeave={e => e.currentTarget.style.color = T.textMuted}>
        <RefreshCw size={11} /> Replay
      </button>
    </div>
  )
}

// ─── Feature Cards ────────────────────────────────────────────
const FEATURES = [
  {
    icon: Brain, color: T.brand, bg: T.brandLight, tag: 'AI Core',
    title: 'Intelligent Trainer Matching',
    desc: 'Upload trainer resumes — AI extracts skills, domain, location, and rate. Match to any client requirement instantly with ranked scores.',
    points: ['Resume parsing & profile extraction', 'Skill + domain + location scoring', 'Availability & rate filtering'],
  },
  {
    icon: Inbox, color: T.orange, bg: T.orangeLight, tag: 'Client Ops',
    title: 'Client Inbox & Request Management',
    desc: 'Gmail integration reads incoming client emails. Auto-generates structured requirement cards. All requests in one unified view.',
    points: ['Gmail read integration', 'Auto-parse requirement from email', 'Client request dashboard'],
  },
  {
    icon: MailCheck, color: T.sky, bg: T.skyLight, tag: 'Outreach',
    title: 'Email + WhatsApp Automation',
    desc: 'Send personalised emails and parallel WhatsApp messages to shortlisted trainers. Track opens, replies, and sentiment in real time.',
    points: ['Personalised email sequences', 'WhatsApp outreach in parallel', 'Reply & sentiment tracking'],
  },
  {
    icon: Repeat2, color: T.violet, bg: T.violetLight, tag: 'Smart Retry',
    title: 'Incomplete Reply Detection',
    desc: 'AI detects when a trainer reply is missing required details. Automatically sends a targeted follow-up asking only for what\'s missing.',
    points: ['AI gap detection in replies', 'Targeted auto follow-up', 'Conversation thread per trainer'],
  },
  {
    icon: SquareKanban, color: T.teal, bg: T.tealLight, tag: 'Pipeline',
    title: '7-Stage Trainer Pipeline',
    desc: 'Move trainers through a structured pipeline from first contact to training confirmation. Full status visibility at every stage.',
    points: ['Kanban-style stage management', 'Interview slot booking', 'Selection & ToC workflow'],
  },
]

const LOOPING_FEATURES = [...FEATURES, ...FEATURES]

function FeatureCard({ feature, delay, tabIndex = 0 }) {
  const [hov, setHov] = useState(false)
  const borderColor = hov ? feature.color + '30' : T.border
  const boxShadow = hov ? T.shadowMd : T.shadow
  
  return (
    <button
      className="card-hover fade-up feature-card-inner"
      tabIndex={tabIndex}
      style={{ height: '100%', animationDelay: delay, background: T.surface, border: `1.5px solid ${borderColor}`, borderRadius: 12, padding: '17px', boxShadow, transition: 'all 0.2s', cursor: 'pointer', display: 'block', width: '100%', textAlign: 'left' }}
      onMouseEnter={() => setHov(true)} 
      onMouseLeave={() => setHov(false)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setHov(!hov) }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: feature.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'transform 0.2s', transform: hov ? 'scale(1.06)' : 'scale(1)' }}>
          <feature.icon size={20} color={feature.color} />
        </div>
        <Badge color={feature.color} bg={feature.bg}>{feature.tag}</Badge>
      </div>
      <h3 style={{ fontSize: 16.5, fontWeight: 700, color: T.textPrimary, margin: '0 0 7px' }}>{feature.title}</h3>
      <p style={{ fontSize: 12.5, color: T.textSecondary, lineHeight: 1.5, margin: '0 0 12px' }}>{feature.desc}</p>
      <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 5 }}>
        {feature.points.map((p) => (
          <li key={p} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 11.5, color: T.textSecondary }}>
            <CheckCircle size={12} color={feature.color} /> {p}
          </li>
        ))}
      </ul>
      {feature.tag === 'AI Core' && (
        <div className="ai-mini-panel">
          <div className="ai-signal-row">
            {[
              ['Resume', 'Parsed', '0s'],
              ['Skills', '92%', '0.25s'],
              ['Match', 'Ranked', '0.5s'],
            ].map(([label, value, itemDelay], idx) => (
              <div key={`signal-${idx}-${label}`} className="ai-signal" style={{ '--ai-delay': itemDelay }}>
                <span className="ai-signal-label">{label}</span>
                <span className="ai-signal-value">{value}</span>
              </div>
            ))}
          </div>
          <div className="ai-match-bar">
            <span style={{ '--ai-width': '88%' }} />
          </div>
        </div>
      )}
    </button>
  )
}

FeatureCard.propTypes = {
  feature: PropTypes.shape({
    icon: PropTypes.elementType.isRequired,
    color: PropTypes.string.isRequired,
    bg: PropTypes.string.isRequired,
    tag: PropTypes.string.isRequired,
    title: PropTypes.string.isRequired,
    desc: PropTypes.string.isRequired,
    points: PropTypes.arrayOf(PropTypes.string).isRequired,
  }).isRequired,
  delay: PropTypes.string,
  tabIndex: PropTypes.number,
}

// ─── Integration logos ────────────────────────────────────────
const INTEGRATIONS = [
  { icon: Linkedin,      name: 'LinkedIn',          shortName: 'LinkedIn',    desc: 'Professional network search and trainer sourcing.',                                                  status: 'Connected', metric: 'Trainer sourcing', color: '#0A66C2', bg: '#E8F3FC' },
  { icon: Mail,          name: 'Gmail',             shortName: 'Gmail',       desc: 'Two inboxes for client requests and trainer outreach, with reply sync into threads.',             status: 'Connected', metric: 'SMTP + inbox watch', color: T.brand,  bg: T.brandLight },
  { icon: MessageSquare, name: 'Twilio WhatsApp',   shortName: 'WhatsApp',    desc: 'Parallel trainer messages, delivery tracking, sandbox testing, and reply capture.',               status: 'Live',      metric: 'Email + WhatsApp', color: T.green,  bg: T.greenLight },
  { icon: Bell,          name: 'Microsoft Teams',   shortName: 'Teams',       desc: 'Webhook alerts for trainer replies, failed sends, pipeline movement, and ops attention.',          status: 'Alerts',    metric: 'Channel alerts', color: T.violet, bg: T.violetLight },
  { icon: Brain,         name: 'Gemini AI',         shortName: 'Gemini AI',   desc: 'Resume parsing, smart email text, incomplete reply checks, and requirement extraction.',          status: 'AI Core',   metric: 'Text generation', color: T.amber,  bg: T.amberLight },
  { icon: Calendar,      name: 'Google Calendar',   shortName: 'Calendar',    desc: 'Interview slot booking, schedule confirmation, reminders, and meeting context.',                  status: 'Ready',     metric: 'Interview flow', color: T.sky,    bg: T.skyLight },
  { icon: Video,         name: 'Google Meet',       shortName: 'Google Meet', desc: 'Automatic interview meeting links and trainer invitations.',                                          status: 'Ready',     metric: 'Video interviews', color: '#00897B', bg: '#E0F7F4' },
  { icon: CloudCog,      name: 'Google Cloud',      shortName: 'Cloud',       desc: 'Gmail Pub/Sub watch, storage, background services, and monthly cost visibility.',                  status: 'Synced',    metric: 'Pub/Sub + costs', color: T.teal,   bg: T.tealLight },
]

const INTEGRATION_FLOW = []
const INTEGRATION_LOGS = []

const _INTEGRATION_NODE_POSITIONS = [
  { x: '50%', y: '10%', z: '82px', scale: '1', angle: '-90deg', len: '205px' },
  { x: '83%', y: '28%', z: '58px', scale: '1', angle: '-30deg', len: '255px' },
  { x: '83%', y: '72%', z: '28px', scale: '1', angle: '32deg',  len: '245px' },
  { x: '50%', y: '90%', z: '10px', scale: '1', angle: '90deg',  len: '210px' },
  { x: '17%', y: '72%', z: '28px', scale: '1', angle: '148deg', len: '245px' },
  { x: '17%', y: '28%', z: '58px', scale: '1', angle: '210deg', len: '255px' },
]

// Live automation flow ticker removed for reduced UI

// ─── Workflow Flow ────────────────────────────────────────────
const WORKFLOW = [
  { icon: Inbox,       label: 'Client Request', color: T.orange, desc: 'Email parsed automatically' },
  { icon: Brain,       label: 'AI Match',       color: T.brand,  desc: 'Score all trainer profiles' },
  { icon: Filter,      label: 'Shortlist',      color: T.violet, desc: 'Filter by skill & rate' },
  { icon: Send,        label: 'Outreach',       color: T.sky,    desc: 'Email + WhatsApp sent' },
  { icon: Reply,       label: 'Reply Track',    color: T.teal,   desc: 'Real-time conversation threads' },
  { icon: Calendar,    label: 'Interview',      color: T.amber,  desc: 'Slot booking & scheduling' },
  { icon: CheckCircle, label: 'Confirmed',      color: T.green,  desc: 'Training confirmation' },
]

const WORKFLOW_CONVERSATIONS = [
  {
    from: 'Client',
    badge: 'Email parsed',
    avatar: 'CL',
    color: T.orange,
    text: 'Need a Data Engineering trainer for 3 days. Mode: hybrid. Please share profiles with availability and commercials.',
    action: 'Requirement created in AI Pipeline',
  },
  {
    from: 'Trainer',
    badge: 'Reply detected',
    avatar: 'TR',
    color: T.teal,
    text: 'I am interested. Available slots: 05-06-2026 11:00 AM, 10-06-2026 4:00 PM, 15-06-2026 10:00 AM IST.',
    action: 'Slots extracted and sent to client',
  },
  {
    from: 'TrainerSync AI',
    badge: 'Auto action',
    avatar: 'AI',
    color: T.brand,
    text: 'Client selected the first slot. Calendar invite, interview link, trainer mail, and client confirmation are prepared.',
    action: 'Interview scheduled, status updated',
  },
]

// ─── Mock Dashboard Preview ───────────────────────────────────
const TRAINER_ROWS = [
  { name: 'Arjun Singh',  skill: 'React.js / Node',  loc: 'Bangalore', score: 96, status: 'Interested',  email: true,  wa: true  },
  { name: 'Priya Menon',  skill: 'SAP FICO',          loc: 'Hyderabad', score: 91, status: 'Interview',   email: true,  wa: true  },
  { name: 'Rahul Dev',    skill: 'DevOps / AWS',      loc: 'Pune',      score: 88, status: 'Replied',     email: true,  wa: false },
  { name: 'Sneha Iyer',   skill: 'Python / ML',       loc: 'Chennai',   score: 85, status: 'Pending',     email: true,  wa: true  },
  { name: 'Vikram Nair',  skill: 'Java Spring Boot',  loc: 'Mumbai',    score: 82, status: 'No Reply',    email: false, wa: false },
]

function DashboardPreview() {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 16, overflow: 'hidden', boxShadow: T.shadowXl }}>
      {/* Title bar */}
      <div style={{ padding: '11px 16px', background: T.bg, borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 5 }}>
          {['#FF5F57','#FFBD2E','#28C840'].map((c) => <div key={c} style={{ width:10,height:10,borderRadius:'50%',background:c }} />)}
        </div>
        <span style={{ fontSize: 12, fontWeight: 600, color: T.textMuted }} className="mono">trainersync — shortlist view</span>
        <div style={{ width: 10 }} />
      </div>

      {/* Toolbar */}
      <div style={{ padding: '10px 16px', borderBottom: `1px solid ${T.borderLight}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: T.bg, border: `1px solid ${T.border}`, borderRadius: 6, padding: '5px 10px', flex: 1, maxWidth: 200 }}>
          <Search size={12} color={T.textMuted} />
          <span style={{ fontSize: 12, color: T.textMuted }}>Search trainers...</span>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button style={{ fontSize: 11, fontWeight: 600, color: T.brand, background: T.brandLight, border: `1px solid ${T.brand}20`, borderRadius: 6, padding: '5px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
            <Brain size={11}/> Run AI Match
          </button>
          <button style={{ fontSize: 11, fontWeight: 600, color: T.textSecondary, background: T.surface, border: `1px solid ${T.border}`, borderRadius: 6, padding: '5px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
            <Send size={11}/> Send Emails
          </button>
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
      {/* Table header */}
      <div style={{ minWidth: 620, display: 'grid', gridTemplateColumns: '1fr 90px 70px 90px 60px 60px', gap: 0, padding: '7px 16px', borderBottom: `1px solid ${T.borderLight}` }}>
        {['Trainer', 'Location', 'Score', 'Status', 'Email', 'WA'].map((h, i) => (
          <span key={h} style={{ fontSize: 11, fontWeight: 700, color: T.textMuted, textTransform: 'uppercase', letterSpacing: '0.04em', textAlign: i > 1 ? 'center' : 'left' }}>{h}</span>
        ))}
      </div>

      {/* Rows */}
      {TRAINER_ROWS.map(t => (
        <button key={`trainer-${t.name}`} style={{ minWidth: 620, display: 'grid', gridTemplateColumns: '1fr 90px 70px 90px 60px 60px', gap: 0, padding: '9px 16px', borderBottom: `1px solid ${T.borderLight}`, transition: 'background 0.12s', cursor: 'pointer', alignItems: 'center', background: 'transparent', border: 'none', width: '100%', textAlign: 'left' }}
          onMouseEnter={e => e.currentTarget.style.background = T.bg}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 28, height: 28, borderRadius: 8, background: `${T.brand}18`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: T.brand, flexShrink: 0 }}>{t.name[0]}</div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: T.textPrimary, whiteSpace: 'nowrap' }}>{t.name}</div>
                <div style={{ fontSize: 10.5, color: T.textMuted, whiteSpace: 'nowrap' }}>{t.skill}</div>
              </div>
            </div>
          </div>
          <div style={{ fontSize: 11.5, color: T.textSecondary, textAlign: 'center' }}>{t.loc}</div>
          <div style={{ textAlign: 'center' }}>
            {(() => {
              let scoreColor
              if (t.score >= 90) {
                scoreColor = T.green
              } else if (t.score >= 80) {
                scoreColor = T.brand
              } else {
                scoreColor = T.amber
              }
              return <span style={{ fontSize: 13, fontWeight: 700, color: scoreColor }} className="mono">{t.score}%</span>
            })()}
          </div>
          <div style={{ textAlign: 'center' }}><StatusBadge status={t.status} /></div>
          <div style={{ textAlign: 'center' }}>
            <span style={{ fontSize: 13 }}>{t.email ? '✅' : '—'}</span>
          </div>
          <div style={{ textAlign: 'center' }}>
            <span style={{ fontSize: 13 }}>{t.wa ? '✅' : '—'}</span>
          </div>
        </button>
      ))}
      </div>

      {/* Footer */}
      <div style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: T.bg }}>
        <span style={{ fontSize: 11, color: T.textMuted }}>Showing 5 of 14 matched trainers</span>
        <button style={{ fontSize: 11, fontWeight: 600, color: T.brand, background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 3 }}>
          View all <ChevronRight size={11} />
        </button>
      </div>
    </div>
  )
}

// ─── Client Inbox Preview ─────────────────────────────────────
function HeroImagePanel() {
  const cards = [
    { icon: Inbox, label: 'Client request parsed', value: 'AWS - 3 days', color: T.orange, bg: T.orangeLight },
    { icon: Brain, label: 'AI shortlist ready', value: '14 trainer matches', color: T.brand, bg: T.brandLight },
    { icon: CheckCircle, label: 'Pipeline active', value: 'Email + WhatsApp', color: T.green, bg: T.greenLight },
  ]

  return (
    <div className="hero-image-panel" style={{
      position: 'relative',
      borderRadius: 28,
      overflow: 'hidden',
      border: `1px solid ${T.border}`,
      boxShadow: T.shadowXl,
      background: 'linear-gradient(135deg, #F8FBFF 0%, #EAF3FF 48%, #FFFFFF 100%)',
    }}>
      <img
        src="/images/office-girl.png"
        alt="Recruitment operations workspace"
        style={{
          position: 'absolute',
          inset: 0,
          width: '112%',
          height: '112%',
          objectFit: 'contain',
          objectPosition: 'center top',
          transform: 'translate(-5%, 0)',
          filter: 'saturate(1.04) brightness(1.13)',
          mixBlendMode: 'multiply',
        }}
      />
      <div style={{
        position: 'absolute',
        inset: 0,
        background: 'linear-gradient(90deg, rgba(255,255,255,0.58), rgba(235,244,255,0.12) 44%, rgba(226,239,255,0.62)), linear-gradient(0deg, rgba(255,255,255,0.82), rgba(255,255,255,0.02) 48%, rgba(219,234,254,0.38))',
      }} />

      <div style={{
        position: 'absolute',
        left: 22,
        right: 22,
        bottom: 22,
        display: 'grid',
        gap: 10,
      }}>
        {cards.map((card, i) => {
          let widthPercent, marginLeftVal
          if (i === 1) {
            widthPercent = '88%'
            marginLeftVal = 'auto'
          } else if (i === 2) {
            widthPercent = '76%'
            marginLeftVal = 0
          } else {
            widthPercent = '82%'
            marginLeftVal = 0
          }
          return (
          <div
            key={card.label}
            className="fade-up"
            style={{
              animationDelay: `${0.14 + i * 0.06}s`,
              width: widthPercent,
              marginLeft: marginLeftVal,
              borderRadius: 16,
              border: '1px solid rgba(255,255,255,0.22)',
              background: 'rgba(255,255,255,0.9)',
              boxShadow: '0 18px 48px rgba(0,0,0,0.22)',
              backdropFilter: 'blur(14px)',
              padding: '13px 15px',
              display: 'grid',
              gridTemplateColumns: '42px 1fr',
              gap: 11,
              alignItems: 'center',
            }}
          >
            <span style={{
              width: 42,
              height: 42,
              borderRadius: 13,
              background: card.bg,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}>
              <card.icon size={19} color={card.color} />
            </span>
            <span style={{ minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: 12, fontWeight: 800, color: T.textPrimary }}>{card.label}</span>
              <span style={{ display: 'block', marginTop: 2, fontSize: 11.5, fontWeight: 600, color: T.textSecondary }}>{card.value}</span>
            </span>
          </div>
        )
        })}
      </div>

      <div style={{
        position: 'absolute',
        top: 22,
        right: 22,
        borderRadius: 999,
        border: '1px solid rgba(37,99,235,0.18)',
        background: 'rgba(255,255,255,0.84)',
        color: T.textPrimary,
        padding: '8px 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        backdropFilter: 'blur(12px)',
        boxShadow: '0 12px 34px rgba(37,99,235,0.16)',
      }}>
        <span className="live-ping">
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: T.green, position: 'relative', zIndex: 1, display: 'block' }} />
        </span>
        <span style={{ fontSize: 12, fontWeight: 800 }}>Live hiring ops</span>
      </div>
    </div>
  )
}

const CLIENT_EMAILS = [
  { from: 'hr@infosys.com',   subject: 'Training Requirement — React.js, Bangalore', time: '9:04 AM',  unread: true,  badge: 'New' },
  { from: 'l&d@tcs.com',      subject: 'SAP FICO trainer needed — 3 days, Pune',     time: 'Yesterday', unread: false, badge: 'Parsed' },
  { from: 'ops@wipro.com',    subject: 'DevOps workshop — 15 pax, Hyderabad',         time: 'Mon',      unread: false, badge: 'Shortlisted' },
]

function ClientInboxPreview() {
  return (
    <Card style={{ overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', borderBottom: `1px solid ${T.borderLight}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Inbox size={15} color={T.orange} />
          <span style={{ fontSize: 13.5, fontWeight: 700, color: T.textPrimary }}>Client Inbox</span>
          <Badge color={T.orange} bg={T.orangeLight}>3 new</Badge>
        </div>
        <button style={{ fontSize: 11, color: T.brand, background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'DM Sans,sans-serif' }}>View all →</button>
      </div>
      {CLIENT_EMAILS.map((e, i) => {
        const borderBottom = i < CLIENT_EMAILS.length - 1 ? `1px solid ${T.borderLight}` : 'none'
        return (
        <button key={`email-${e.from}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 16px', borderBottom, transition: 'background 0.12s', cursor: 'pointer', background: 'transparent', border: 'none', width: '100%', textAlign: 'left' }}
          onMouseEnter={ev => ev.currentTarget.style.background = T.bg}
          onMouseLeave={ev => ev.currentTarget.style.background = 'transparent'}>
          {e.unread && <div className="dot-blue" />}
          {!e.unread && <div style={{ width: 7, height: 7, flexShrink: 0 }} />}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
              <span style={{ fontSize: 12, fontWeight: e.unread ? 700 : 500, color: T.textSecondary }}>{e.from}</span>
              <span style={{ fontSize: 11, color: T.textMuted }}>{e.time}</span>
            </div>
            <p style={{ fontSize: 12.5, fontWeight: e.unread ? 600 : 400, color: e.unread ? T.textPrimary : T.textSecondary, margin: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{e.subject}</p>
          </div>
          {(() => {
            let badgeColor, badgeBg
            if (e.badge === 'New') {
              badgeColor = T.orange
              badgeBg = T.orangeLight
            } else if (e.badge === 'Parsed') {
              badgeColor = T.brand
              badgeBg = T.brandLight
            } else {
              badgeColor = T.green
              badgeBg = T.greenLight
            }
            return (
              <Badge color={badgeColor} bg={badgeBg}>
                {e.badge}
              </Badge>
            )
          })()}
        </button>
        )
      })}
    </Card>
  )
}

// ─── Conversation Thread Preview ──────────────────────────────
function ConversationThread() {
  const msgs = [
    { from: 'TrainerSync', text: 'Hi Arjun, we have a React.js training requirement in Bangalore for 2 days. Would you be available?', time: '10:00 AM', dir: 'out' },
    { from: 'Arjun Singh', text: 'Yes, I am available. Can you share the client details and the rate?', time: '10:42 AM', dir: 'in' },
    { from: 'TrainerSync', text: 'Thanks Arjun. The client is looking for React.js with Node basics, 2 days, hybrid mode. Please share your latest profile and expected rate.', time: '10:44 AM', dir: 'out', auto: true },
    { from: 'Arjun Singh', text: 'Sure, attaching now. My rate is ₹15,000/day.', time: '11:15 AM', dir: 'in' },
    { from: 'TrainerSync', text: 'Profile received. Could you please share 3 interview slots with exact date, time, and AM/PM?', time: '11:17 AM', dir: 'out', auto: true },
    { from: 'Arjun Singh', text: '05-06-2026 11:00 AM IST, 10-06-2026 4:00 PM IST, 15-06-2026 10:00 AM IST.', time: '11:31 AM', dir: 'in' },
    { from: 'TrainerSync', text: 'Thanks. I have shared these slots with the client for selection.', time: '11:32 AM', dir: 'out', auto: true },
    { from: 'Client', text: 'We confirm the first available slot: 05-06-2026 at 11:00 AM IST. Please proceed with scheduling.', time: '12:05 PM', dir: 'client' },
    { from: 'TrainerSync', text: 'Interview scheduled for 05-06-2026 at 11:00 AM IST. Meeting link has been shared with both sides.', time: '12:08 PM', dir: 'out', auto: true },
    { from: 'Client', text: 'Arjun is selected. Please proceed with ToC and final confirmation.', time: '3:40 PM', dir: 'client' },
    { from: 'TrainerSync', text: 'Congratulations Arjun, the client has selected you. Please share the ToC / agenda for the confirmed training.', time: '3:42 PM', dir: 'out', auto: true },
    { from: 'Arjun Singh', text: 'Thank you. ToC attached. I am good to proceed with the training.', time: '4:05 PM', dir: 'in' },
    { from: 'TrainerSync', text: 'Training confirmed. Final details and contact points have been shared.', time: '4:12 PM', dir: 'out', auto: true },
  ]
  return (
    <Card style={{ overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', borderBottom: `1px solid ${T.borderLight}`, display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ width: 28, height: 28, borderRadius: '50%', background: T.brandLight, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: T.brand }}>AS</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: T.textPrimary }}>Arjun Singh</div>
          <div style={{ fontSize: 11, color: T.textMuted, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="dot-green" style={{ width: 5, height: 5 }} /> Active thread · {msgs.length} messages
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <Badge color={T.green} bg={T.greenLight}><MailOpen size={9}/> Replied</Badge>
          <Badge color={T.teal} bg={T.tealLight}>ToC received</Badge>
        </div>
      </div>
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8, height: 280, overflowY: 'auto', scrollbarGutter: 'stable' }}>
        {msgs.map((m, i) => {
          const flexDir = m.dir === 'out' ? 'row-reverse' : 'row'
          const borderRadius = m.dir === 'out' ? '12px 12px 2px 12px' : '12px 12px 12px 2px'
          let bgColor
          if (m.dir === 'out') {
            bgColor = T.brand
          } else if (m.dir === 'client') {
            bgColor = T.orangeLight
          } else {
            bgColor = T.bg
          }
          const border = m.dir === 'in' ? `1px solid ${T.border}` : 'none'
          return (
          <div key={`msg-${i}-${m.from}`} style={{ display: 'flex', flexDirection: flexDir, gap: 8, alignItems: 'flex-end' }}>
            <div style={{
              maxWidth: '72%', padding: '8px 12px', borderRadius,
              background: bgColor,
              border,
              boxShadow: T.shadow
            }}>
              {m.auto && <div style={{ fontSize: 10, color: m.dir === 'out' ? 'rgba(255,255,255,0.7)' : T.textMuted, marginBottom: 2, display: 'flex', alignItems: 'center', gap: 3 }}>
                <Cpu size={8}/> Auto-sent
              </div>}
              <p style={{ fontSize: 12, color: m.dir === 'out' ? '#fff' : T.textPrimary, margin: 0, lineHeight: 1.5 }}>{m.text}</p>
              <div style={{ fontSize: 10, color: m.dir === 'out' ? 'rgba(255,255,255,0.6)' : T.textMuted, marginTop: 3, textAlign: 'right' }}>{m.time}</div>
            </div>
          </div>
        )
        })}
      </div>
      <div style={{ padding: '10px 14px', borderTop: `1px solid ${T.borderLight}`, display: 'flex', gap: 6 }}>
        <div style={{ flex: 1, background: T.bg, border: `1px solid ${T.border}`, borderRadius: 8, padding: '7px 10px', fontSize: 12, color: T.textMuted }}>Reply to Arjun...</div>
        <button style={{ width: 32, height: 32, borderRadius: 8, background: T.brand, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Send size={13} color="#fff" />
        </button>
      </div>
    </Card>
  )
}

// ─── MAIN HOME ────────────────────────────────────────────────
export default function Home() {
  const navigate = useNavigate()
  const [navScrolled, setNavScrolled] = useState(false)
  const [featurePaused, setFeaturePaused] = useState(false)
  const featureScrollRef = useRef(null)

  useEffect(() => {
    const fn = () => setNavScrolled(window.scrollY > 30)
    window.addEventListener('scroll', fn)
    return () => window.removeEventListener('scroll', fn)
  }, [])

  const moveFeatureRail = useCallback((direction = 1) => {
    const rail = featureScrollRef.current
    const firstCard = rail?.querySelector('.feature-scroll-card')
    if (!rail || !firstCard) return

    const step = firstCard.getBoundingClientRect().width + 14
    const loopWidth = step * FEATURES.length
    let currentLeft = rail.scrollLeft

    if (direction > 0 && currentLeft >= loopWidth - (step * 0.25)) {
      currentLeft -= loopWidth
      rail.scrollTo({ left: currentLeft, behavior: 'auto' })
    } else if (direction < 0 && currentLeft <= step * 0.25) {
      currentLeft += loopWidth
      rail.scrollTo({ left: currentLeft, behavior: 'auto' })
    }

    const nextLeft = Math.max(0, currentLeft + (step * direction))

    rail.scrollTo({ left: nextLeft, behavior: 'smooth' })
  }, [])

  useEffect(() => {
    if (featurePaused) return undefined
    const timer = globalThis.setInterval(() => moveFeatureRail(1), 2400)
    return () => globalThis.clearInterval(timer)
  }, [featurePaused, moveFeatureRail])

  const NAV_LINKS = [
    ['Workflow', '#workflow'],
    ['Features', '#features'],
    ['Pipeline', '#pipeline'],
    ['Integrations', '#integrations'],
  ]

  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.textPrimary, overflowX: 'hidden' }}>
      <style>{CSS}</style>

      {/* ══════════════════════════════════════════════
          NAVBAR
      ══════════════════════════════════════════════ */}
      <nav style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 1000, height: 56,
        background: navScrolled ? 'rgba(247,248,250,0.95)' : T.bg,
        backdropFilter: navScrolled ? 'blur(16px)' : 'none',
        borderBottom: `1px solid ${navScrolled ? T.border : 'transparent'}`,
        boxShadow: navScrolled ? T.shadow : 'none',
        transition: 'all 0.25s ease',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 28px',
      }}>
        {/* Logo */}
        <BrandMark size="sm" onClick={() => navigate('/dashboard')} />

        {/* Desktop nav */}
        <div className="hide-mobile" style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          {NAV_LINKS.map(([label, href]) => (
            <a key={label} href={href} className="nav-link">{label}</a>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Live indicator */}
          <div className="hide-mobile" style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: T.greenLight, borderRadius: 100, border: `1px solid ${T.green}20` }}>
            <div className="live-ping">
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: T.green, display: 'block', position: 'relative', zIndex: 1 }} />
            </div>
            <span style={{ fontSize: 11, fontWeight: 600, color: T.green }}>System Live</span>
          </div>
          <button onClick={() => navigate('/dashboard')} className="btn-primary" style={{ padding: '7px 16px', fontSize: 13 }}>
            Dashboard <ArrowRight size={13} />
          </button>
          <button onClick={() => navigate('/login')} className="hide-mobile btn-secondary" style={{ padding: '7px 14px', fontSize: 13 }}>
            Sign in
          </button>
        </div>
      </nav>

      {/* ══════════════════════════════════════════════
          HERO
      ══════════════════════════════════════════════ */}
      <div className="hero-stage">
      <section className="hero-main">
        <div className="hero-grid">

          {/* Left copy */}
          <div>
            {/* Eyebrow */}
            <div className="fade-up" style={{ animationDelay: '0s', marginBottom: 14 }}>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: T.surface, border: `1px solid ${T.border}`, borderRadius: 100, padding: '5px 14px', boxShadow: T.shadow }}>
                <div className="live-ping">
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: T.green, position: 'relative', zIndex: 1, display: 'block' }} />
                </div>
                <span style={{ fontSize: 12.5, fontWeight: 600, color: T.textSecondary }}>
                  AI-powered · 7-stage pipeline · Real-time tracking
                </span>
              </div>
            </div>

            {/* Headline */}
            <h1 className="fade-up" style={{ animationDelay: '0.07s', fontSize: 'clamp(2.2rem, 4.6vw, 3.5rem)', fontWeight: 800, lineHeight: 1.06, letterSpacing: '-0.04em', color: T.textPrimary, marginBottom: 14 }}>
              Trainer Matching &<br />
              <span style={{ color: T.brand, fontSize: '0.88em' }}>Operations Platform</span><br />
              <span style={{ color: T.textSecondary, fontSize: '0.82em', fontWeight: 600 }}>for Clahan Technologies</span>
            </h1>

            <p className="fade-up" style={{ animationDelay: '0.14s', fontSize: 17, color: T.textSecondary, lineHeight: 1.55, marginBottom: 20, maxWidth: 500 }}>
              From client email to trainer confirmation — fully automated.
              AI matches trainers, sends outreach via email & WhatsApp, tracks replies, detects incomplete responses, and manages the full 7-stage pipeline.
            </p>

            {/* Checklist */}
            <ul className="fade-up" style={{ animationDelay: '0.18s', listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 20 }}>
              {[
                { text: 'Resume upload → AI parsing → ranked matching', icon: Brain, color: T.brand },
                { text: 'Email + WhatsApp outreach with auto follow-up', icon: Send, color: T.sky },
                { text: 'Smart reply detection for missing trainer details', icon: Repeat2, color: T.violet },
                { text: 'Client inbox + auto-generated requirement cards', icon: Inbox, color: T.orange },
              ].map((item) => (
                <li key={item.text} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 20, height: 20, borderRadius: 6, background: `${item.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <item.icon size={11} color={item.color} />
                  </div>
                  <span style={{ fontSize: 12.5, lineHeight: 1.35, color: T.textSecondary, fontWeight: 500 }}>{item.text}</span>
                </li>
              ))}
            </ul>

            {/* CTAs */}
            <div className="fade-up" style={{ animationDelay: '0.24s', display: 'flex', gap: 9, flexWrap: 'wrap', marginBottom: 20 }}>
              <button onClick={() => navigate('/dashboard')} className="btn-primary" style={{ padding: '9px 18px', fontSize: 13.5 }}>
                <LayoutDashboard size={14} /> Open Dashboard
              </button>
              <a href="#workflow" className="btn-secondary" style={{ padding: '9px 17px', fontSize: 13.5, textDecoration: 'none' }}>
                <Play size={13} /> See Workflow
              </a>
            </div>

            {/* Social proof */}
            <div className="fade-up" style={{ animationDelay: '0.3s', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0 }} aria-label="Trainer community">
                {[T.brand, T.green, T.violet, T.orange, T.teal].map((c, i) => (
                  <div key={`trainer-avatar-${c}`} style={{ width: 28, height: 28, borderRadius: '50%', border: `1px solid ${c}35`, background: `${c}14`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: 10, lineHeight: 1, fontWeight: 800, color: c, boxShadow: T.shadow }}>
                    {['A','P','R','S','K'][i]}
                  </div>
                ))}
              </div>
              <div>
                <p style={{ fontSize: 13, color: T.textSecondary, margin: 0, fontWeight: 500 }}>
                  <strong style={{ color: T.textPrimary }}>500+ trainers</strong> in the database
                </p>
                <p style={{ fontSize: 11.5, color: T.textMuted, margin: 0 }}>
                  ★★★★★ <span style={{ color: T.textMuted }}>98% match accuracy · 3× faster hiring</span>
                </p>
              </div>
            </div>
          </div>

          {/* Right — Dashboard preview */}
          <div className="slide-r" style={{ animationDelay: '0.1s' }}>
            {import.meta.env.VITE_SHOW_LEGACY_DASHBOARD === 'true' ? <DashboardPreview /> : <HeroImagePanel />}

            {/* Floating cards */}
            <div className="float-up" style={{ display: 'none' }}>
              {/* WhatsApp badge */}
              <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, padding: '8px 13px', display: 'flex', alignItems: 'center', gap: 8, boxShadow: T.shadowMd }}>
                <div style={{ width: 26, height: 26, borderRadius: 8, background: '#25D36615', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <MessageSquare size={13} color="#25D366" />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: T.textMuted }}>WhatsApp</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: T.textPrimary }}>6 sent ✓</div>
                </div>
              </div>
              {/* AI score badge */}
              <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, padding: '8px 13px', display: 'flex', alignItems: 'center', gap: 8, boxShadow: T.shadowMd }}>
                <div style={{ width: 26, height: 26, borderRadius: 8, background: T.brandLight, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <Brain size={13} color={T.brand} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: T.textMuted }}>Top match</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: T.textPrimary }}>96% score</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      </div>

      {/* ══════════════════════════════════════════════
          WORKFLOW (end-to-end)
      ══════════════════════════════════════════════ */}
      <section id="workflow" style={{ background: T.surface, borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`, padding: '32px 24px' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <div className="workflow-heading">
            <SectionHeader
              label="End-to-End Workflow"
              labelIcon={Layers}
              title="From Client Email to Training Confirmation"
              sub="Every step automated — AI handles matching, outreach, reply detection, interview scheduling, and final confirmation."
              center
            />
          </div>

          <div className="workflow-shell">
            <div className="workflow-panel">
              <div className="workflow-panel-head">
                <div className="workflow-panel-kicker">
                  <SquareKanban size={16} color={T.brand} />
                  Automated pipeline
                </div>
                <div className="workflow-live"><span /> 7 stages active</div>
              </div>

              <div className="workflow-flow-scroll">
                {/* Horizontal workflow steps */}
                <div className="workflow-grid">
                  {WORKFLOW.map((w, i) => (
                    <div
                      key={w.label}
                      className="workflow-step"
                      style={{
                        '--workflow-color': w.color,
                        '--workflow-soft': `${w.color}1A`,
                        '--workflow-glow': `${w.color}42`,
                        '--workflow-ring': `${w.color}66`,
                        '--workflow-delay': `${i * 1.7}s`,
                      }}
                    >
                      <div className="card-hover workflow-card">
                        <div className="workflow-number">{i + 1}</div>
                        <div className="workflow-copy">
                          <div className="workflow-icon">
                            <w.icon size={20} color={w.color} />
                          </div>
                          <div>
                            <div className="workflow-title">{w.label}</div>
                            <div className="workflow-desc">{w.desc}</div>
                          </div>
                        </div>
                        <div className="workflow-step-state"><span /> Automated</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="workflow-panel">
              <div className="workflow-panel-head">
                <div className="workflow-panel-kicker">
                  <BotMessageSquare size={16} color={T.teal} />
                  Live conversation activity
                </div>
                <div className="workflow-live"><span /> Synced</div>
              </div>

              <div className="workflow-conversation">
                {WORKFLOW_CONVERSATIONS.map((item, i) => (
                  <div
                    key={item.from}
                    className="workflow-message-card"
                    style={{
                      '--message-color': item.color,
                      '--message-delay': `${i * 0.14}s`,
                    }}
                  >
                    <div className="workflow-message-head">
                      <div className="workflow-message-person">
                        <div className="workflow-message-avatar">{item.avatar}</div>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 13, fontWeight: 800, color: T.textPrimary, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.from}</div>
                          <div style={{ fontSize: 11, color: T.textMuted }}>Conversation thread</div>
                        </div>
                      </div>
                      <Badge color={item.color} bg={`${item.color}14`}>{item.badge}</Badge>
                    </div>
                    <p className="workflow-message-text">{item.text}</p>
                    <div className="workflow-message-action">
                      <CheckCircle size={13} />
                      {item.action}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════
          PIPELINE SECTION
      ══════════════════════════════════════════════ */}
      <section id="pipeline" style={{ padding: '72px 28px', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, alignItems: 'start' }} className="cols-mobile-1">
          <div>
            <SectionHeader
              label="7-Stage Pipeline"
              labelIcon={SquareKanban}
              title="Full Trainer Pipeline Management"
              sub="Move trainers through structured stages from first contact to final confirmation. Auto-actions at every step."
            />
            <PipelineSection />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <ConversationThread />
            <ClientInboxPreview />
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════
          FEATURES GRID
      ══════════════════════════════════════════════ */}
      <section id="features" style={{ background: T.surface, borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`, padding: '72px 28px' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <SectionHeader
            label="Platform Features"
            labelIcon={Sparkles}
            title="Everything Ops Needs in One Platform"
            sub="Five connected modules covering every step — from client requirement to trainer confirmation."
            center
          />
          <div
            ref={featureScrollRef}
            className="feature-scroll-shell"
            role="region"
            tabIndex={0}
            dir="ltr"
            aria-label="TrainerSync platform features carousel - automatically scrolls from left to right"
            onTouchStart={() => setFeaturePaused(true)}
            onTouchEnd={() => setFeaturePaused(false)}
            onTouchCancel={() => setFeaturePaused(false)}
            onFocus={() => setFeaturePaused(true)}
            onBlur={() => setFeaturePaused(false)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight') { moveFeatureRail(1); e.preventDefault() }
              if (e.key === 'ArrowLeft') { moveFeatureRail(-1); e.preventDefault() }
            }}
            style={{ display: 'block', width: '100%', border: 'none', background: 'transparent' }}
          >
            <div className="feature-scroll-track">
              {LOOPING_FEATURES.map((feature, i) => (
                <div
                  className="feature-scroll-card"
                  key={`${i}-${feature.title}`}
                  aria-hidden={i >= FEATURES.length ? true : undefined}
                >
                  <FeatureCard
                    feature={feature}
                    delay={`${(i % FEATURES.length) * 0.07}s`}
                    tabIndex={i >= FEATURES.length ? -1 : 0}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════
          CLIENT OPS: Inbox + Smart Reply
      ══════════════════════════════════════════════ */}
      <section style={{ padding: '72px 28px', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, alignItems: 'start' }} className="cols-mobile-1">
          {/* Smart Reply Detection */}
          <div>
            <SectionHeader
              label="Smart Reply Handling"
              labelIcon={BotMessageSquare}
              title="AI Detects Incomplete Replies"
              sub="When a trainer replies but misses key details — rate, availability, profile — the system automatically sends a targeted follow-up asking only for what's missing."
            />
            <Card style={{ padding: '20px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[
                  { field: 'Availability',  status: 'received', color: T.green  },
                  { field: 'Training Rate', status: 'received', color: T.green  },
                  { field: 'Profile / CV',  status: 'missing',  color: T.red    },
                  { field: 'ToC Document',  status: 'missing',  color: T.red    },
                  { field: 'Domain Topics', status: 'received', color: T.green  },
                ].map((r) => (
                  <div key={`field-${r.field}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 12px', borderRadius: 8, background: T.bg, border: `1px solid ${T.borderLight}` }}>
                    <span style={{ fontSize: 13, fontWeight: 500, color: T.textPrimary }}>{r.field}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {r.status === 'received'
                        ? <><CheckCircle size={13} color={T.green} /><span style={{ fontSize: 11.5, color: T.green, fontWeight: 600 }}>Received</span></>
                        : <><AlertCircle size={13} color={T.red} /><span style={{ fontSize: 11.5, color: T.red, fontWeight: 600 }}>Missing</span></>
                      }
                    </div>
                  </div>
                ))}
                <div style={{ padding: '10px 12px', borderRadius: 8, background: T.brandLight, border: `1px solid ${T.brand}20`, display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                  <Cpu size={14} color={T.brand} style={{ marginTop: 1, flexShrink: 0 }} />
                  <p style={{ fontSize: 12.5, color: T.brand, margin: 0, lineHeight: 1.5 }}>
                    <strong>Auto follow-up sent:</strong> "Hi Rahul, could you share your Profile/CV and ToC document? We have everything else, thank you!"
                  </p>
                </div>
              </div>
            </Card>
          </div>

          {/* Outreach channels */}
          <div>
            <SectionHeader
              label="Outreach Automation"
              labelIcon={Send}
              title="Email + WhatsApp in Parallel"
              sub="Send personalised emails via Gmail and WhatsApp messages simultaneously to every shortlisted trainer. Track opens, replies, and sentiment on the live dashboard."
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Email preview */}
              <Card style={{ padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                  <div style={{ width: 32, height: 32, borderRadius: 9, background: T.brandLight, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Mail size={15} color={T.brand} />
                  </div>
                  <div>
                    <div style={{ fontSize: 12.5, fontWeight: 700, color: T.textPrimary }}>Gmail Outreach</div>
                    <div style={{ fontSize: 11, color: T.textMuted }}>Personalised · Tracked · Auto follow-up</div>
                  </div>
                  <Badge color={T.green} bg={T.greenLight} style={{ marginLeft: 'auto' }}>14 sent</Badge>
                </div>
                <div style={{ background: T.bg, border: `1px solid ${T.border}`, borderRadius: 8, padding: '10px 12px', fontSize: 12, color: T.textSecondary, lineHeight: 1.6 }}>
                  <strong style={{ color: T.textPrimary }}>To:</strong> arjun.singh@email.com<br />
                  <strong style={{ color: T.textPrimary }}>Subject:</strong> React.js Training — Bangalore, July 2026<br /><br />
                  Hi Arjun, we have a 2-day React.js training requirement in Bangalore...{' '}
                  <span style={{ color: T.brand }}>personalised with AI ✨</span>
                </div>
              </Card>

              {/* WhatsApp preview */}
              <Card style={{ padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                  <div style={{ width: 32, height: 32, borderRadius: 9, background: '#25D36615', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <MessageSquare size={15} color="#25D366" />
                  </div>
                  <div>
                    <div style={{ fontSize: 12.5, fontWeight: 700, color: T.textPrimary }}>WhatsApp API</div>
                    <div style={{ fontSize: 11, color: T.textMuted }}>Sent simultaneously with email</div>
                  </div>
                  <Badge color="#25D366" bg="#25D36615" style={{ marginLeft: 'auto' }}>6 delivered</Badge>
                </div>
                <div style={{ background: '#25D36608', border: '1px solid #25D36620', borderRadius: 8, padding: '10px 12px', fontSize: 12, color: T.textSecondary, lineHeight: 1.6 }}>
                  Hi Arjun 👋 We have a React.js training opportunity in Bangalore. Interested? Reply YES to get details.
                </div>
              </Card>

              {/* Teams notification */}
              <Card style={{ padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 32, height: 32, borderRadius: 9, background: T.violetLight, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <Bell size={15} color={T.violet} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: T.textPrimary }}>Microsoft Teams Alert</div>
                  <div style={{ fontSize: 11.5, color: T.textMuted }}>Arjun Singh replied — marked Interested</div>
                </div>
                <Badge color={T.violet} bg={T.violetLight}>Teams</Badge>
              </Card>
            </div>
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════
          INTEGRATIONS
      ══════════════════════════════════════════════ */}
      <section id="integrations" style={{ padding: '72px 28px', maxWidth: 1200, margin: '0 auto' }}>
        <SectionHeader
          label="Integrations"
          labelIcon={Webhook}
          title="Connected Tools"
          sub="Eight tools linked together in one automation network."
          center
        />
        <div className="tools-zigzag-scroll fade-up">
          <div className="tools-zigzag" role="list" aria-label="Connected TrainerSync tools">
            <svg className="tools-zigzag-lines" viewBox="0 0 1000 270" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <linearGradient id="tools-zigzag-gradient" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor={T.brand} />
                  <stop offset="22%" stopColor={T.green} />
                  <stop offset="44%" stopColor={T.violet} />
                  <stop offset="66%" stopColor={T.amber} />
                  <stop offset="84%" stopColor={T.sky} />
                  <stop offset="100%" stopColor={T.teal} />
                </linearGradient>
              </defs>
              <polyline className="tools-zigzag-path-base" points="80,78 200,186 320,78 440,186 560,78 680,186 800,78 920,186" />
              <polyline className="tools-zigzag-path-active" points="80,78 200,186 320,78 440,186 560,78 680,186 800,78 920,186" />
            </svg>

            {INTEGRATIONS.map((integration, i) => (
              <div
                className="tools-zigzag-node"
                role="listitem"
                key={integration.name}
                style={{
                  '--zig-y': i % 2 === 0 ? '22px' : '130px',
                  '--tool-color': integration.color,
                  '--tool-soft': `${integration.color}22`,
                }}
              >
                <span className="tools-zigzag-icon" style={{ background: integration.bg }}>
                  <integration.icon size={23} color={integration.color} strokeWidth={2.2} />
                </span>
                <span className="tools-zigzag-name">{integration.shortName}</span>
              </div>
            ))}
          </div>
        </div>

        {import.meta.env.VITE_SHOW_LEGACY_INTEGRATIONS === 'true' && (
          <>
        <div className="integration-layout" style={{ marginBottom: 34 }}>
          <aside className="integration-rail fade-up">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 800, color: T.textPrimary }}>Connected Channels</div>
                <div style={{ fontSize: 12, color: T.textMuted, marginTop: 3 }}>Production-ready service map</div>
              </div>
              <div className="live-ping">
                <div style={{ width: 7, height: 7, borderRadius: '50%', background: T.green, position: 'relative', zIndex: 1 }} />
              </div>
            </div>

            {INTEGRATIONS.map(integration => (
              <div className="integration-channel" key={integration.name}>
                <div className="integration-channel-icon" style={{ background: integration.bg }}>
                  <integration.icon size={17} color={integration.color} />
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12.8, fontWeight: 800, color: T.textPrimary }}>{integration.name}</div>
                  <div style={{ fontSize: 11.2, color: T.textMuted, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{integration.metric}</div>
                </div>
                <Badge color={integration.color} bg={integration.bg}>{integration.status}</Badge>
              </div>
            ))}

            <div style={{ marginTop: 14, borderRadius: 12, background: T.bg, border: `1px solid ${T.borderLight}`, padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <Shield size={14} color={T.green} />
                <span style={{ fontSize: 12.5, fontWeight: 800, color: T.textPrimary }}>Health Check</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {['OAuth OK', 'Webhook OK', 'Pub/Sub OK', 'Queue OK'].map(item => (
                  <span key={item} style={{ fontSize: 11.2, color: T.textSecondary, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 5 }}>
                    <CheckCircle size={11} color={T.green} /> {item}
                  </span>
                ))}
              </div>
            </div>
          </aside>

          <div className="integration-console fade-up" style={{ animationDelay: '0.08s' }}>
            <div className="integration-console-top">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ display: 'flex', gap: 5 }}>
                  {['#FF5F57', '#FFBD2E', '#28C840'].map(color => (
                    <span key={color} style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'block' }} />
                  ))}
                </div>
                <span className="mono" style={{ color: '#EEF0F4', fontSize: 12, fontWeight: 700 }}>integration-monitor/live</span>
              </div>
              <span style={{ color: '#8BE7B1', background: 'rgba(5,150,105,0.16)', border: '1px solid rgba(5,150,105,0.28)', borderRadius: 999, padding: '4px 9px', fontSize: 11, fontWeight: 800 }}>STREAMING</span>
            </div>

            <div className="integration-route">
              {INTEGRATION_FLOW && INTEGRATION_FLOW.length > 0 ? (
                INTEGRATION_FLOW.map((item, i) => (
                  <div className="integration-route-step" key={item.label}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
                      <span className="mono" style={{ color: '#727A8A', fontSize: 10, fontWeight: 800 }}>0{i + 1}</span>
                      <item.icon size={15} color="#EEF0F4" />
                    </div>
                    <div style={{ color: '#D8DBE2', fontSize: 12, fontWeight: 700, lineHeight: 1.35 }}>{item.label}</div>
                  </div>
                ))
              ) : (
                <div style={{ color: '#727A8A', fontSize: 12, padding: '12px 0' }}>No integration flow data</div>
              )}
            </div>

            <div style={{ padding: '13px 16px 0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <div>
                <div style={{ color: '#EEF0F4', fontSize: 13.5, fontWeight: 800 }}>Live Integration Logs</div>
                <div style={{ color: '#8B93A4', fontSize: 11.5, marginTop: 2 }}>Clean event stream across mail, WhatsApp, AI, Teams, calendar, and cloud</div>
              </div>
              <div className="mono" style={{ color: '#8B93A4', fontSize: 11 }}>latency 1.2s</div>
            </div>

            <div className="integration-log-list">
              {INTEGRATION_LOGS && INTEGRATION_LOGS.length > 0 ? (
                INTEGRATION_LOGS.map(log => (
                  <div className="integration-log-row" key={`${log.time}-${log.source}`}>
                    <span className="mono" style={{ color: '#A6ADBB', fontSize: 11.5 }}>{log.time}</span>
                    <div style={{ width: 34, height: 34, borderRadius: 10, background: `${log.color}22`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <log.icon size={15} color={log.color} />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div className="integration-log-message">{log.source}: {log.message}</div>
                      <div className="integration-log-meta">{log.meta}</div>
                    </div>
                    <span className="integration-log-status" style={{ justifySelf: 'end', color: log.color, background: `${log.color}18`, border: `1px solid ${log.color}33`, borderRadius: 999, padding: '4px 8px', fontSize: 10.5, fontWeight: 800 }}>{log.status}</span>
                  </div>
                ))
              ) : (
                <div style={{ color: '#727A8A', fontSize: 12, padding: '12px 0' }}>No integration logs available</div>
              )}
            </div>
          </div>
        </div>

        {/* CTA Banner */}
        <div style={{ background: T.brand, borderRadius: 16, padding: '40px 40px', textAlign: 'center', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', inset: 0, backgroundImage: `radial-gradient(circle at 20% 50%, rgba(255,255,255,0.06) 0%, transparent 50%), radial-gradient(circle at 80% 50%, rgba(255,255,255,0.04) 0%, transparent 50%)`, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', inset: 0, backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.04) 1px, transparent 1px)', backgroundSize: '28px 28px', pointerEvents: 'none' }} />
          <div style={{ position: 'relative', zIndex: 1 }}>
            <h2 style={{ fontSize: 'clamp(1.8rem,3.3vw,2.4rem)', fontWeight: 700, color: '#fff', margin: '0 0 10px', letterSpacing: '-0.03em' }}>
              Ready to Automate Trainer Operations?
            </h2>
            <p style={{ fontSize: 15, color: 'rgba(255,255,255,0.78)', margin: '0 auto 28px', maxWidth: 460, lineHeight: 1.65 }}>
              Upload a client requirement and watch the full pipeline — matching, outreach, replies, and confirmation — run on its own.
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
              <button onClick={() => navigate('/dashboard')}
                style={{ background: '#fff', color: T.brand, padding: '11px 24px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 14.5, fontWeight: 700, fontFamily: 'DM Sans,sans-serif', boxShadow: '0 4px 16px rgba(0,0,0,0.14)', transition: 'all 0.18s' }}
                onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 8px 24px rgba(0,0,0,0.2)' }}
                onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.14)' }}>
                Open Dashboard →
              </button>
              <button onClick={() => navigate('/shortlist1')}
                style={{ background: 'rgba(255,255,255,0.12)', color: '#fff', padding: '11px 22px', borderRadius: 8, border: '1.5px solid rgba(255,255,255,0.3)', cursor: 'pointer', fontSize: 14.5, fontWeight: 600, fontFamily: 'DM Sans,sans-serif', transition: 'all 0.18s' }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.2)'}
                onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.12)'}>
                View Pipeline
              </button>
            </div>
          </div>
        </div>
          </>
        )}
      </section>

      {/* ══════════════════════════════════════════════
          FOOTER
      ══════════════════════════════════════════════ */}
      <footer style={{ background: T.textPrimary, padding: '44px 28px 28px' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1.8fr 1fr 1fr 1fr', gap: 40, marginBottom: 36 }} className="cols-mobile-2">
            {/* Brand */}
            <div>
              <BrandMark size="sm" theme="dark" className="mb-3" onClick={() => navigate('/home')} />
              <p style={{ fontSize: 13, color: '#6B7280', lineHeight: 1.7, maxWidth: 240 }}>
                AI-powered trainer matching and operations platform. Match, outreach, track, and confirm — fully automated.
              </p>
            </div>

            {[
              { title: 'Platform', links: ['Dashboard', 'AI Matching', 'Pipeline', 'Analytics', 'Client Inbox'] },
              { title: 'Integrations', links: ['Gmail', 'WhatsApp API', 'Microsoft Teams', 'Google Calendar', 'Gemini AI'] },
              { title: 'Company', links: ['About', 'Contact', 'Privacy Policy', 'Terms', 'Support'] },
            ].map(({ title, links }) => (
              <div key={title}>
                <p style={{ fontSize: 12, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 14 }}>{title}</p>
                <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {links.map(l => (
                    <li key={l}>
                      <button style={{ fontSize: 13, color: '#6B7280', cursor: 'pointer', transition: 'color 0.15s', background: 'none', border: 'none', padding: 0, font: 'inherit' }}
                        onMouseEnter={e => e.target.style.color = '#fff'}
                        onMouseLeave={e => e.target.style.color = '#6B7280'}>{l}</button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div style={{ borderTop: '1px solid #1F2937', paddingTop: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
            <p style={{ fontSize: 12.5, color: '#4B5563', margin: 0 }}>© 2026 TrainerSync · Clahan Technologies. All rights reserved.</p>
            <p style={{ fontSize: 12, color: '#374151', margin: 0 }}>Match · Outreach · Track · Confirm</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
