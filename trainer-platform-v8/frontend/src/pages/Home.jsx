// Home.jsx – TrainerSync · Clahan Technologies
// Professional SaaS Operations Home Page
// Uses: lucide-react, react-router-dom, inline styles only (Tailwind-free for portability)

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import BrandMark from '../components/BrandMark'
import {
  ArrowRight, CheckCircle, Play,
  Brain, Mail, MessageSquare, Users,
  TrendingUp, Shield, ChevronRight, BarChart2,
  Filter, Send, Calendar, Sparkles,
  Inbox, FileText, UserCheck, PhoneCall,
  Bell, Search,
  RefreshCw, Layers, Database,
  AlertCircle,
  Cpu,
  MailCheck, MailOpen, Reply,
  Award, Target, Repeat2,
  BotMessageSquare,
  SquareKanban, Webhook, CloudCog,
  LayoutDashboard
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
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #D1D5DB; border-radius: 3px; }

  /* animations */
  @keyframes fadeUp   { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }
  @keyframes fadeIn   { from { opacity:0; } to { opacity:1; } }
  @keyframes slideLeft{ from { opacity:0; transform:translateX(-20px); } to { opacity:1; transform:translateX(0); } }
  @keyframes slideRight{from { opacity:0; transform:translateX(20px); } to { opacity:1; transform:translateX(0); } }
  @keyframes scaleIn  { from { opacity:0; transform:scale(0.95); } to { opacity:1; transform:scale(1); } }
  @keyframes ping     { 0%{transform:scale(1);opacity:0.7} 100%{transform:scale(2);opacity:0} }
  @keyframes ticker   { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }
  @keyframes featureScroll { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }
  @keyframes pulse2   { 0%,100%{opacity:1} 50%{opacity:0.5} }
  @keyframes shimmer  { 0%{background-position:-400px 0} 100%{background-position:400px 0} }
  @keyframes floatUp  { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
  @keyframes barFill  { from{width:0} to{width:var(--w)} }
  @keyframes countUp  { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
  @keyframes borderAnim { 0%{border-color:${T.brand}40} 50%{border-color:${T.brand}} 100%{border-color:${T.brand}40} }
  @keyframes dotBlink { 0%,100%{opacity:1} 50%{opacity:0.2} }
  @keyframes workflowCardRun {
    0%, 11% {
      border-color: var(--workflow-color);
      box-shadow: 0 14px 34px rgba(15,23,42,0.10), 0 0 0 4px var(--workflow-soft);
      transform: translateY(-6px);
    }
    18%, 100% {
      border-color: ${T.border};
      box-shadow: ${T.shadow};
      transform: translateY(0);
    }
  }
  @keyframes workflowIconRun {
    0%, 11% { background: var(--workflow-soft); transform: scale(1.08); }
    18%, 100% { background: ${T.surface}; transform: scale(1); }
  }
  @keyframes workflowNumberRun {
    0%, 11% { transform: translateX(-50%) scale(1.1); }
    18%, 100% { transform: translateX(-50%) scale(1); }
  }
  @keyframes workflowLineRun {
    0% { transform: scaleX(0); opacity: 0; }
    8%, 14% { transform: scaleX(1); opacity: 1; }
    22%, 100% { transform: scaleX(1); opacity: 0.18; }
  }
  @keyframes workflowArrowRun {
    0%, 11% { color: var(--workflow-color); border-color: var(--workflow-color); transform: translateY(-50%) scale(1.08); }
    18%, 100% { color: ${T.textMuted}; border-color: ${T.border}; transform: translateY(-50%) scale(1); }
  }
  @keyframes workflowMessageIn {
    0% { opacity: 0; transform: translateY(12px); }
    12%, 72% { opacity: 1; transform: translateY(0); }
    100% { opacity: 0.64; transform: translateY(0); }
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
    font-family: 'DM Sans', sans-serif; font-size: 14px; font-weight: 600;
    padding: 10px 20px; border-radius: 8px;
    box-shadow: 0 1px 2px rgba(26,86,219,0.18), inset 0 1px 0 rgba(255,255,255,0.12);
    transition: all 0.18s;
  }
  .btn-primary:hover { background: ${T.brandDark}; box-shadow: 0 4px 16px rgba(26,86,219,0.28); transform: translateY(-1px); }
  .btn-primary:active { transform: translateY(0); }

  .btn-secondary {
    display: inline-flex; align-items: center; gap: 7px;
    background: ${T.surface}; color: ${T.textPrimary}; border: 1.5px solid ${T.border};
    cursor: pointer; font-family: 'DM Sans', sans-serif; font-size: 14px; font-weight: 600;
    padding: 10px 20px; border-radius: 8px;
    transition: all 0.18s;
  }
  .btn-secondary:hover { border-color: ${T.brand}; color: ${T.brand}; background: ${T.brandLight}; transform: translateY(-1px); }

  .nav-link {
    font-size: 13.5px; font-weight: 500; color: ${T.textSecondary};
    text-decoration: none; padding: 5px 10px; border-radius: 6px;
    transition: all 0.15s;
  }
  .nav-link:hover { color: ${T.textPrimary}; background: ${T.borderLight}; }

  .badge {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 11px; font-weight: 600; padding: 2px 8px;
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

  /* Ticker */
  .ticker-wrap { overflow: hidden; }
  .ticker-track { display:flex; width:max-content; animation: ticker 30s linear infinite; }
  .ticker-track:hover { animation-play-state:paused; }

  /* Feature scroller */
  .feature-scroll-shell {
    position: relative;
    overflow: hidden;
    padding: 4px 0 14px;
  }
  .feature-scroll-shell::before,
  .feature-scroll-shell::after {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    width: 82px;
    z-index: 2;
    pointer-events: none;
  }
  .feature-scroll-shell::before {
    left: 0;
    background: linear-gradient(90deg, ${T.surface} 0%, rgba(255,255,255,0) 100%);
  }
  .feature-scroll-shell::after {
    right: 0;
    background: linear-gradient(270deg, ${T.surface} 0%, rgba(255,255,255,0) 100%);
  }
  .feature-scroll-track {
    display: flex;
    align-items: stretch;
    gap: 16px;
    width: max-content;
    animation: featureScroll 38s linear infinite;
    will-change: transform;
  }
  .feature-scroll-shell:hover .feature-scroll-track { animation-play-state: paused; }
  .feature-scroll-card {
    flex: 0 0 360px;
    width: 360px;
    max-width: 82vw;
  }

  /* Workflow step connector */
  .workflow-connector {
    position:absolute; right:-24px; top:50%; transform:translateY(-50%);
    width:24px; height:2px; background: linear-gradient(90deg, ${T.border}, ${T.brand}30);
    z-index:1;
  }
  .workflow-grid {
    display: grid;
    grid-template-columns: repeat(7, minmax(142px, 1fr));
    gap: 14px;
    overflow-x: auto;
    padding: 20px 4px 18px;
    scrollbar-gutter: stable;
  }
  .workflow-step {
    position: relative;
    min-width: 142px;
    display: flex;
    --workflow-soft: rgba(26,86,219,0.10);
  }
  .workflow-step::after {
    content: '';
    position: absolute;
    left: calc(100% - 2px);
    top: 50%;
    width: 18px;
    height: 2px;
    background: linear-gradient(90deg, var(--workflow-color), rgba(26,86,219,0.08));
    transform: scaleX(0);
    transform-origin: left center;
    animation: workflowLineRun 8.4s ease-in-out infinite;
    animation-delay: var(--workflow-delay);
    z-index: 1;
  }
  .workflow-step:last-child::after { display: none; }
  .workflow-card {
    width: 100%;
    min-height: 172px;
    background: linear-gradient(180deg, ${T.surface} 0%, ${T.bg} 100%);
    border: 1.5px solid ${T.border};
    border-radius: 12px;
    padding: 20px 12px 16px;
    text-align: center;
    position: relative;
    cursor: default;
    display: flex;
    flex-direction: column;
    align-items: center;
    box-shadow: ${T.shadow};
    animation: workflowCardRun 8.4s ease-in-out infinite;
    animation-delay: var(--workflow-delay);
    will-change: transform, box-shadow;
  }
  .workflow-number {
    position: absolute;
    top: -10px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--workflow-color);
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 8px 18px var(--workflow-soft);
    animation: workflowNumberRun 8.4s ease-in-out infinite;
    animation-delay: var(--workflow-delay);
  }
  .workflow-icon {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    background: ${T.surface};
    border: 1px solid var(--workflow-soft);
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 4px auto 12px;
    flex-shrink: 0;
    animation: workflowIconRun 8.4s ease-in-out infinite;
    animation-delay: var(--workflow-delay);
  }
  .workflow-title {
    min-height: 34px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .workflow-desc {
    min-height: 48px;
    display: flex;
    align-items: flex-start;
  }
  .workflow-arrow {
    position: absolute;
    right: -15px;
    top: 50%;
    transform: translateY(-50%);
    width: 28px;
    height: 28px;
    border-radius: 999px;
    background: ${T.surface};
    border: 1px solid ${T.border};
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2;
    box-shadow: ${T.shadow};
    pointer-events: none;
    color: ${T.textMuted};
    animation: workflowArrowRun 8.4s ease-in-out infinite;
    animation-delay: var(--workflow-delay);
  }
  .workflow-conversation {
    margin-top: 20px;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }
  .workflow-message-card {
    background: ${T.surface};
    border: 1px solid ${T.border};
    border-radius: 12px;
    padding: 14px;
    min-height: 150px;
    box-shadow: ${T.shadow};
    animation: workflowMessageIn 7.2s ease-in-out infinite;
    animation-delay: var(--message-delay);
  }
  .workflow-message-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 10px;
  }
  .workflow-message-person {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .workflow-message-avatar {
    width: 30px;
    height: 30px;
    border-radius: 10px;
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
    font-size: 12.5px;
    line-height: 1.55;
    color: ${T.textSecondary};
    margin: 0;
  }
  .workflow-message-action {
    margin-top: 11px;
    display: flex;
    align-items: center;
    gap: 7px;
    color: var(--message-color);
    font-size: 11.5px;
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

  @keyframes integrationMarquee { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }

  .integration-showcase {
    border: 1px solid ${T.border};
    border-radius: 18px;
    background: ${T.surface};
    box-shadow: ${T.shadowLg};
    overflow: hidden;
  }
  .integration-marquee-shell {
    position: relative;
    overflow: hidden;
    padding: 18px 0;
    border-bottom: 1px solid ${T.borderLight};
    background: linear-gradient(180deg, #fff, ${T.bg});
  }
  .integration-marquee-shell::before,
  .integration-marquee-shell::after {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    width: 90px;
    z-index: 2;
    pointer-events: none;
  }
  .integration-marquee-shell::before { left: 0; background: linear-gradient(90deg, #fff, rgba(255,255,255,0)); }
  .integration-marquee-shell::after { right: 0; background: linear-gradient(270deg, #fff, rgba(255,255,255,0)); }
  .integration-marquee-track {
    display: flex;
    gap: 14px;
    width: max-content;
    padding-inline: 18px;
    animation: integrationMarquee 28s linear infinite;
  }
  .integration-marquee-shell:hover .integration-marquee-track { animation-play-state: paused; }
  .integration-logo-pill {
    width: 188px;
    min-height: 72px;
    border-radius: 14px;
    border: 1px solid ${T.border};
    background: #fff;
    display: grid;
    grid-template-columns: 44px 1fr;
    align-items: center;
    gap: 11px;
    padding: 12px;
    box-shadow: ${T.shadow};
  }
  .integration-logo-icon {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .integration-pipeline-panel {
    padding: 24px;
    display: grid;
    gap: 18px;
  }
  .integration-pipeline-row {
    position: relative;
    display: grid;
    grid-template-columns: repeat(6, minmax(120px, 1fr));
    gap: 12px;
    align-items: stretch;
  }
  .integration-pipeline-row::before {
    content: '';
    position: absolute;
    left: 6%;
    right: 6%;
    top: 27px;
    height: 2px;
    background: linear-gradient(90deg, ${T.orange}, ${T.amber}, ${T.teal}, ${T.brand}, ${T.green}, ${T.sky});
    opacity: 0.28;
  }
  .integration-pipeline-step {
    position: relative;
    z-index: 1;
    min-height: 132px;
    border-radius: 14px;
    border: 1px solid ${T.border};
    background: #fff;
    padding: 13px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-shadow: ${T.shadow};
  }
  .integration-pipeline-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .integration-pipeline-icon {
    width: 36px;
    height: 36px;
    border-radius: 11px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .integration-event-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }
  .integration-event-card {
    border: 1px solid ${T.border};
    border-radius: 14px;
    background: ${T.bg};
    padding: 14px;
    display: grid;
    grid-template-columns: 38px 1fr;
    gap: 11px;
    align-items: start;
  }

  /* Pipeline step */
  .pipe-step-active { animation: borderAnim 2s ease-in-out infinite; }

  /* Responsive */
  @media(max-width:768px){
    .hide-mobile { display:none !important; }
    .cols-mobile-1 { grid-template-columns: 1fr !important; }
    .cols-mobile-2 { grid-template-columns: repeat(2,1fr) !important; }
    .feature-scroll-card { flex-basis: 300px; width: 300px; }
    .feature-scroll-track { animation-duration: 44s; }
    .feature-scroll-shell::before,
    .feature-scroll-shell::after { width: 34px; }
    .workflow-grid { grid-template-columns: repeat(7, 170px); gap: 12px; padding-inline: 2px; }
    .workflow-step { min-width: 170px; }
    .workflow-card { min-height: 168px; }
    .workflow-arrow { right: -14px; }
    .workflow-step::after { width: 14px; }
    .workflow-conversation { grid-template-columns: 1fr; }
    .ai-signal-row { grid-template-columns: 1fr; }
    .integration-layout { min-height: 420px; }
    .integration-cycle { height: 420px; }
    .integration-logo-node { width: 104px; height: 76px; border-radius: 20px; }
    .integration-logo-label { font-size: 11.5px; }
    .integration-core-node { width: 86px; height: 86px; border-radius: 26px; }
    .integration-pipeline-panel { padding: 18px; }
    .integration-pipeline-row { grid-template-columns: repeat(6, 168px); overflow-x: auto; padding-bottom: 4px; }
    .integration-pipeline-row::before { left: 36px; right: auto; width: 920px; }
    .integration-event-grid { grid-template-columns: 1fr; }
    .integration-marquee-shell::before,
    .integration-marquee-shell::after { width: 34px; }
  }
  @media(max-width:480px){
    .cols-mobile-2 { grid-template-columns: 1fr !important; }
  }
  @media(prefers-reduced-motion: reduce){
    .feature-scroll-track { animation: none; overflow-x: auto; }
    .integration-marquee-track { animation: none; overflow-x: auto; }
    .workflow-card,
    .workflow-icon,
    .workflow-number,
    .workflow-arrow,
    .workflow-step::after,
    .workflow-message-card,
    .ai-mini-panel::before,
    .ai-signal,
    .ai-match-bar span { animation: none; }
  }
`

// ─── Utility Components ───────────────────────────────────────
function Card({ children, style, className = '', onClick }) {
  return (
    <div
      onClick={onClick}
      className={`card-hover ${className}`}
      style={{
        background: T.surface, border: `1px solid ${T.border}`,
        borderRadius: 12, overflow: 'hidden',
        boxShadow: T.shadow, ...style
      }}
    >
      {children}
    </div>
  )
}

function Badge({ children, color = T.brand, bg, style }) {
  return (
    <span className="badge" style={{ color, background: bg || `${color}15`, ...style }}>
      {children}
    </span>
  )
}

function SectionLabel({ icon: Icon, children }) {
  return (
    <div className="section-label">
      {Icon && <Icon size={12} />}
      {children}
    </div>
  )
}

function SectionHeader({ label, labelIcon, title, sub, center }) {
  return (
    <div style={{ textAlign: center ? 'center' : 'left', marginBottom: 48 }}>
      {label && <div style={{ marginBottom: 12, display: 'flex', justifyContent: center ? 'center' : 'flex-start' }}>
        <SectionLabel icon={labelIcon}>{label}</SectionLabel>
      </div>}
      <h2 style={{ fontSize: 'clamp(1.5rem,3vw,2rem)', fontWeight: 700, color: T.textPrimary, lineHeight: 1.2, marginBottom: 10 }}>
        {title}
      </h2>
      {sub && <p style={{ fontSize: 15.5, color: T.textSecondary, maxWidth: center ? 560 : '100%', margin: center ? '0 auto' : 0, lineHeight: 1.65 }}>
        {sub}
      </p>}
    </div>
  )
}

// ─── Animated Counter ─────────────────────────────────────────
function StatusBadge({ status }) {
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '3px 9px', borderRadius: 100, background: T.brandLight, color: T.brand }}>
      {status}
    </span>
  )
}

function useCounter(target, duration = 1600) {
  const [val, setVal] = useState(0)
  const ref = useRef(null)
  const started = useRef(false)
  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !started.current) {
        started.current = true
        const t0 = performance.now()
        const tick = now => {
          const p = Math.min((now - t0) / duration, 1)
          setVal(Math.floor((1 - Math.pow(1 - p, 3)) * target))
          if (p < 1) requestAnimationFrame(tick)
          else setVal(target)
        }
        requestAnimationFrame(tick)
      }
    }, { threshold: 0.3 })
    if (ref.current) obs.observe(ref.current)
    return () => obs.disconnect()
  }, [target, duration])
  return { val, ref }
}

// ─── Live Activity Feed ───────────────────────────────────────
// ─── Stat Card ────────────────────────────────────────────────
function StatCard({ icon: Icon, color, label, target, suffix = '', trend, delay = '0s' }) {
  const { val, ref } = useCounter(target)
  return (
    <div ref={ref} className="card-hover fade-up" style={{ animationDelay: delay, background: T.surface, border: `1px solid ${T.border}`, borderRadius: 12, padding: '20px', boxShadow: T.shadow }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
        <div style={{ width: 38, height: 38, borderRadius: 10, background: `${color}12`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon size={18} color={color} />
        </div>
        {trend && <Badge color={T.green} bg={T.greenLight}><TrendingUp size={9}/> {trend}</Badge>}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: T.textPrimary, lineHeight: 1, marginBottom: 4 }} className="mono">
        {val}{suffix}
      </div>
      <div style={{ fontSize: 13, color: T.textSecondary, fontWeight: 500 }}>{label}</div>
    </div>
  )
}

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
          return (
            <button key={i} onClick={() => { setActive(i); setRunning(false) }}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', zIndex: 1 }}>
              <div style={{
                width: 38, height: 38, borderRadius: '50%',
                background: curr ? st.color : done ? `${st.color}20` : T.surface,
                border: `2px solid ${curr || done ? st.color : T.border}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transform: curr ? 'scale(1.18)' : 'scale(1)',
                boxShadow: curr ? `0 0 0 5px ${st.color}18, 0 4px 16px ${st.color}30` : 'none',
                transition: 'all 0.35s cubic-bezier(0.34,1.56,0.64,1)'
              }}>
                <st.icon size={curr || done ? 15 : 14} color={curr ? '#fff' : done ? st.color : T.textMuted} />
              </div>
              <span style={{ fontSize: 10, fontWeight: 600, color: curr ? st.color : done ? st.color : T.textMuted, textAlign: 'center', lineHeight: 1.2 }} className="hide-mobile">
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

const SCROLLING_FEATURES = [...FEATURES, ...FEATURES]

function FeatureCard({ feature, delay }) {
  const [hov, setHov] = useState(false)
  return (
    <div
      className="card-hover fade-up"
      style={{ height: '100%', animationDelay: delay, background: T.surface, border: `1.5px solid ${hov ? feature.color + '30' : T.border}`, borderRadius: 14, padding: '24px', boxShadow: hov ? T.shadowMd : T.shadow, transition: 'all 0.2s', cursor: 'default' }}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ width: 44, height: 44, borderRadius: 12, background: feature.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'transform 0.2s', transform: hov ? 'scale(1.08)' : 'scale(1)' }}>
          <feature.icon size={20} color={feature.color} />
        </div>
        <Badge color={feature.color} bg={feature.bg}>{feature.tag}</Badge>
      </div>
      <h3 style={{ fontSize: 15, fontWeight: 700, color: T.textPrimary, margin: '0 0 8px' }}>{feature.title}</h3>
      <p style={{ fontSize: 13.5, color: T.textSecondary, lineHeight: 1.6, margin: '0 0 14px' }}>{feature.desc}</p>
      <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 5 }}>
        {feature.points.map((p, i) => (
          <li key={i} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12.5, color: T.textSecondary }}>
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
            ].map(([label, value, itemDelay]) => (
              <div key={label} className="ai-signal" style={{ '--ai-delay': itemDelay }}>
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
    </div>
  )
}

// ─── Integration logos ────────────────────────────────────────
const INTEGRATIONS = [
  { icon: Mail,          name: 'Gmail',             shortName: 'Gmail',       desc: 'Two inboxes for client requests and trainer outreach, with reply sync into threads.',             status: 'Connected', metric: 'SMTP + inbox watch', color: T.brand,  bg: T.brandLight },
  { icon: MessageSquare, name: 'Twilio WhatsApp',   shortName: 'WhatsApp',    desc: 'Parallel trainer messages, delivery tracking, sandbox testing, and reply capture.',               status: 'Live',      metric: 'Email + WhatsApp', color: T.green,  bg: T.greenLight },
  { icon: Bell,          name: 'Microsoft Teams',   shortName: 'Teams',       desc: 'Webhook alerts for trainer replies, failed sends, pipeline movement, and ops attention.',          status: 'Alerts',    metric: 'Channel alerts', color: T.violet, bg: T.violetLight },
  { icon: Brain,         name: 'Gemini AI',         shortName: 'Gemini AI',   desc: 'Resume parsing, smart email text, incomplete reply checks, and requirement extraction.',          status: 'AI Core',   metric: 'Text generation', color: T.amber,  bg: T.amberLight },
  { icon: Calendar,      name: 'Google Calendar',   shortName: 'Calendar',    desc: 'Interview slot booking, schedule confirmation, reminders, and meeting context.',                  status: 'Ready',     metric: 'Interview flow', color: T.sky,    bg: T.skyLight },
  { icon: CloudCog,      name: 'Google Cloud',      shortName: 'Cloud',       desc: 'Gmail Pub/Sub watch, storage, background services, and monthly cost visibility.',                  status: 'Synced',    metric: 'Pub/Sub + costs', color: T.teal,   bg: T.tealLight },
]

const SCROLLING_INTEGRATIONS = [...INTEGRATIONS, ...INTEGRATIONS]

const INTEGRATION_PIPELINE = [
  { icon: Inbox,         label: 'Client Mail',     meta: 'Gmail inbox',       color: T.orange, bg: T.orangeLight },
  { icon: Brain,         label: 'AI Parse',        meta: 'Requirement card',  color: T.amber,  bg: T.amberLight },
  { icon: Database,      label: 'Trainer Match',   meta: 'Profile database',  color: T.teal,   bg: T.tealLight },
  { icon: Mail,          label: 'Email',           meta: 'Gmail SMTP',        color: T.brand,  bg: T.brandLight },
  { icon: MessageSquare, label: 'WhatsApp',        meta: 'Delivery status',   color: T.green,  bg: T.greenLight },
  { icon: Calendar,      label: 'Schedule',        meta: 'Calendar + Teams',  color: T.sky,    bg: T.skyLight },
]

const INTEGRATION_EVENTS = [
  { icon: MailCheck, label: 'Inbox Sync', detail: 'Client request and trainer replies enter the right thread.', color: T.brand, bg: T.brandLight },
  { icon: BotMessageSquare, label: 'AI Decision', detail: 'Incomplete replies trigger the next correct message.', color: T.amber, bg: T.amberLight },
  { icon: Bell, label: 'Ops Alert', detail: 'WhatsApp, Teams, and dashboard status update together.', color: T.violet, bg: T.violetLight },
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

// ─── Ticker items ─────────────────────────────────────────────
const TICK = [
  'Gmail Integration', 'WhatsApp Outreach', 'AI Matching', 'Teams Alerts',
  'Resume Parsing', 'Reply Tracking', 'Client Inbox', 'Auto Follow-up',
  'Interview Scheduling', 'Gemini AI', 'Cost Tracking', 'Smart Retry',
  'Trainer Pipeline', 'Sentiment Analysis', 'Profile Sharing',
]

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

function _DashboardPreview() {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 16, overflow: 'hidden', boxShadow: T.shadowXl }}>
      {/* Title bar */}
      <div style={{ padding: '11px 16px', background: T.bg, borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 5 }}>
          {['#FF5F57','#FFBD2E','#28C840'].map((c,i) => <div key={i} style={{ width:10,height:10,borderRadius:'50%',background:c }} />)}
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
        <div key={t.name} style={{ minWidth: 620, display: 'grid', gridTemplateColumns: '1fr 90px 70px 90px 60px 60px', gap: 0, padding: '9px 16px', borderBottom: `1px solid ${T.borderLight}`, transition: 'background 0.12s', cursor: 'default', alignItems: 'center' }}
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
            <span style={{ fontSize: 13, fontWeight: 700, color: t.score >= 90 ? T.green : t.score >= 80 ? T.brand : T.amber }} className="mono">{t.score}%</span>
          </div>
          <div style={{ textAlign: 'center' }}><StatusBadge status={t.status} /></div>
          <div style={{ textAlign: 'center' }}>
            <span style={{ fontSize: 13 }}>{t.email ? '✅' : '—'}</span>
          </div>
          <div style={{ textAlign: 'center' }}>
            <span style={{ fontSize: 13 }}>{t.wa ? '✅' : '—'}</span>
          </div>
        </div>
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
    <div style={{
      position: 'relative',
      minHeight: 520,
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
        {cards.map((card, i) => (
          <div
            key={card.label}
            className="fade-up"
            style={{
              animationDelay: `${0.14 + i * 0.06}s`,
              width: i === 1 ? '88%' : i === 2 ? '76%' : '82%',
              marginLeft: i === 1 ? 'auto' : 0,
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
        ))}
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
      {CLIENT_EMAILS.map((e, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 16px', borderBottom: i < CLIENT_EMAILS.length - 1 ? `1px solid ${T.borderLight}` : 'none', transition: 'background 0.12s', cursor: 'pointer' }}
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
          <Badge color={e.badge === 'New' ? T.orange : e.badge === 'Parsed' ? T.brand : T.green}
                 bg={e.badge === 'New' ? T.orangeLight : e.badge === 'Parsed' ? T.brandLight : T.greenLight}>
            {e.badge}
          </Badge>
        </div>
      ))}
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
        {msgs.map((m, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: m.dir === 'out' ? 'row-reverse' : 'row', gap: 8, alignItems: 'flex-end' }}>
            <div style={{
              maxWidth: '72%', padding: '8px 12px', borderRadius: m.dir === 'out' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
              background: m.dir === 'out' ? T.brand : m.dir === 'client' ? T.orangeLight : T.bg,
              border: m.dir === 'in' ? `1px solid ${T.border}` : 'none',
              boxShadow: T.shadow
            }}>
              {m.auto && <div style={{ fontSize: 10, color: m.dir === 'out' ? 'rgba(255,255,255,0.7)' : T.textMuted, marginBottom: 2, display: 'flex', alignItems: 'center', gap: 3 }}>
                <Cpu size={8}/> Auto-sent
              </div>}
              <p style={{ fontSize: 12, color: m.dir === 'out' ? '#fff' : T.textPrimary, margin: 0, lineHeight: 1.5 }}>{m.text}</p>
              <div style={{ fontSize: 10, color: m.dir === 'out' ? 'rgba(255,255,255,0.6)' : T.textMuted, marginTop: 3, textAlign: 'right' }}>{m.time}</div>
            </div>
          </div>
        ))}
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

  useEffect(() => {
    const fn = () => setNavScrolled(window.scrollY > 30)
    window.addEventListener('scroll', fn)
    return () => window.removeEventListener('scroll', fn)
  }, [])

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
      <section style={{ padding: '96px 28px 64px', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.1fr', gap: 56, alignItems: 'center' }} className="cols-mobile-1">

          {/* Left copy */}
          <div>
            {/* Eyebrow */}
            <div className="fade-up" style={{ animationDelay: '0s', marginBottom: 20 }}>
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
            <h1 className="fade-up" style={{ animationDelay: '0.07s', fontSize: 'clamp(2rem, 4.5vw, 3rem)', fontWeight: 800, lineHeight: 1.1, letterSpacing: '-0.04em', color: T.textPrimary, marginBottom: 18 }}>
              Trainer Matching &<br />
              <span style={{ color: T.brand }}>Operations Platform</span><br />
              <span style={{ color: T.textSecondary, fontSize: '0.82em', fontWeight: 600 }}>for Clahan Technologies</span>
            </h1>

            <p className="fade-up" style={{ animationDelay: '0.14s', fontSize: 16, color: T.textSecondary, lineHeight: 1.7, marginBottom: 28, maxWidth: 480 }}>
              From client email to trainer confirmation — fully automated.
              AI matches trainers, sends outreach via email & WhatsApp, tracks replies, detects incomplete responses, and manages the full 7-stage pipeline.
            </p>

            {/* Checklist */}
            <ul className="fade-up" style={{ animationDelay: '0.18s', listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 28 }}>
              {[
                { text: 'Resume upload → AI parsing → ranked matching', icon: Brain, color: T.brand },
                { text: 'Email + WhatsApp outreach with auto follow-up', icon: Send, color: T.sky },
                { text: 'Smart reply detection for missing trainer details', icon: Repeat2, color: T.violet },
                { text: 'Client inbox + auto-generated requirement cards', icon: Inbox, color: T.orange },
              ].map((item, i) => (
                <li key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 22, height: 22, borderRadius: 6, background: `${item.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <item.icon size={12} color={item.color} />
                  </div>
                  <span style={{ fontSize: 13.5, color: T.textSecondary, fontWeight: 500 }}>{item.text}</span>
                </li>
              ))}
            </ul>

            {/* CTAs */}
            <div className="fade-up" style={{ animationDelay: '0.24s', display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 28 }}>
              <button onClick={() => navigate('/dashboard')} className="btn-primary" style={{ padding: '11px 22px', fontSize: 14.5 }}>
                <LayoutDashboard size={15} /> Open Dashboard
              </button>
              <a href="#workflow" className="btn-secondary" style={{ padding: '11px 20px', fontSize: 14.5, textDecoration: 'none' }}>
                <Play size={14} /> See Workflow
              </a>
            </div>

            {/* Social proof */}
            <div className="fade-up" style={{ animationDelay: '0.3s', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {[T.brand, T.green, T.violet, T.orange, T.teal].map((c, i) => (
                  <div key={i} style={{ width: 28, height: 28, borderRadius: '50%', border: '2px solid white', background: `${c}22`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: c, marginLeft: i ? -6 : 0, boxShadow: T.shadow }}>
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
            {import.meta.env.VITE_SHOW_LEGACY_DASHBOARD === 'true' ? <_DashboardPreview /> : <HeroImagePanel />}

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

      {/* ══════════════════════════════════════════════
          TRUST TICKER
      ══════════════════════════════════════════════ */}
      <div style={{ borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`, background: T.surface, overflow: 'hidden', padding: '12px 0' }}>
        <div className="ticker-wrap">
          <div className="ticker-track">
            {[...TICK, ...TICK].map((t, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 24px', flexShrink: 0, whiteSpace: 'nowrap' }}>
                <div style={{ width: 4, height: 4, borderRadius: '50%', background: T.brand, opacity: 0.5 }} />
                <span style={{ fontSize: 12.5, fontWeight: 500, color: T.textSecondary }}>{t}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════
          STATS ROW
      ══════════════════════════════════════════════ */}
      <section style={{ maxWidth: 1200, margin: '0 auto', padding: '56px 28px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 16 }} className="cols-mobile-2">
          <StatCard icon={Users}       color={T.brand}  label="Trainer Profiles"   target={500}  suffix="+" trend="+12 this week" delay="0s" />
          <StatCard icon={Target}      color={T.green}  label="Match Accuracy"     target={98}   suffix="%" trend="↑ 2% vs last month" delay="0.06s" />
          <StatCard icon={TrendingUp}  color={T.violet} label="Faster Hiring"      target={3}    suffix="×" delay="0.12s" />
          <StatCard icon={BarChart2}   color={T.amber}  label="Active Pipelines"   target={24}   suffix="" delay="0.18s" />
        </div>
      </section>

      {/* ══════════════════════════════════════════════
          WORKFLOW (end-to-end)
      ══════════════════════════════════════════════ */}
      <section id="workflow" style={{ background: T.surface, borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`, padding: '72px 28px' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <SectionHeader
            label="End-to-End Workflow"
            labelIcon={Layers}
            title="From Client Email to Training Confirmation"
            sub="Every step automated — AI handles matching, outreach, reply detection, interview scheduling, and final confirmation."
            center
          />

          {/* Workflow steps */}
          <div className="workflow-grid">
            {WORKFLOW.map((w, i) => (
              <div
                key={w.label}
                className="workflow-step"
                style={{
                  '--workflow-color': w.color,
                  '--workflow-soft': `${w.color}1A`,
                  '--workflow-delay': `${i * 1.05}s`,
                }}
              >
                <div className="card-hover workflow-card">
                  <div className="workflow-number">{i + 1}</div>
                  <div className="workflow-icon">
                    <w.icon size={20} color={w.color} />
                  </div>
                  <div className="workflow-title" style={{ fontSize: 12.5, fontWeight: 700, color: T.textPrimary, marginBottom: 6, lineHeight: 1.25 }}>{w.label}</div>
                  <div className="workflow-desc" style={{ fontSize: 11, color: T.textMuted, lineHeight: 1.45 }}>{w.desc}</div>
                </div>
                {i < WORKFLOW.length - 1 && (
                  <div className="workflow-arrow">
                    <ArrowRight size={14} />
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="workflow-conversation">
            {WORKFLOW_CONVERSATIONS.map((item, i) => (
              <div
                key={item.from}
                className="workflow-message-card"
                style={{
                  '--message-color': item.color,
                  '--message-delay': `${i * 0.55}s`,
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
            sub="Six core modules covering every step — from client requirement to trainer confirmation."
            center
          />
          <div className="feature-scroll-shell" aria-label="TrainerSync platform features">
            <div className="feature-scroll-track">
              {SCROLLING_FEATURES.map((feature, i) => {
                const cycle = i < FEATURES.length ? 'first' : 'second'
                return (
                  <div className="feature-scroll-card" key={`${feature.title}-${cycle}`}>
                    <FeatureCard feature={feature} delay={`${(i % FEATURES.length) * 0.07}s`} />
                  </div>
                )
              })}
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
                ].map((r, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 12px', borderRadius: 8, background: T.bg, border: `1px solid ${T.borderLight}` }}>
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
          title="Connected Tool Pipeline"
          sub="Every channel sits in the same operational flow: client mail, AI parsing, trainer outreach, WhatsApp delivery, Teams alerts, and calendar scheduling."
          center
        />
        <div className="integration-showcase fade-up">
          <div className="integration-marquee-shell" aria-label="Connected TrainerSync tools">
            <div className="integration-marquee-track">
              {SCROLLING_INTEGRATIONS.map((integration, i) => (
                <div className="integration-logo-pill" key={`${integration.name}-${i}`}>
                  <span className="integration-logo-icon" style={{ background: integration.bg }}>
                    <integration.icon size={22} color={integration.color} strokeWidth={2.2} />
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <strong style={{ display: 'block', fontSize: 13, color: T.textPrimary, lineHeight: 1.2 }}>{integration.shortName}</strong>
                    <small style={{ display: 'block', marginTop: 4, fontSize: 11.3, color: T.textMuted, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{integration.metric}</small>
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="integration-pipeline-panel">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 800, color: T.textPrimary }}>Live Signal Route</div>
                <div style={{ fontSize: 12, color: T.textMuted, marginTop: 3 }}>One clean path from client request to confirmed trainer</div>
              </div>
              <Badge color={T.green} bg={T.greenLight}>All systems connected</Badge>
            </div>

            <div className="integration-pipeline-row">
              {INTEGRATION_PIPELINE.map((step, i) => (
                <div className="integration-pipeline-step" key={step.label}>
                  <div className="integration-pipeline-head">
                    <span className="mono" style={{ fontSize: 10.5, color: T.textMuted, fontWeight: 800 }}>0{i + 1}</span>
                    <CheckCircle size={14} color={T.green} />
                  </div>
                  <div className="integration-pipeline-icon" style={{ background: step.bg }}>
                    <step.icon size={18} color={step.color} />
                  </div>
                  <div>
                    <div style={{ fontSize: 13, color: T.textPrimary, fontWeight: 800, marginBottom: 4 }}>{step.label}</div>
                    <div style={{ fontSize: 11.5, color: T.textMuted, lineHeight: 1.4 }}>{step.meta}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="integration-event-grid">
              {INTEGRATION_EVENTS.map(event => (
                <div className="integration-event-card" key={event.label}>
                  <span className="integration-pipeline-icon" style={{ background: event.bg }}>
                    <event.icon size={17} color={event.color} />
                  </span>
                  <span>
                    <strong style={{ display: 'block', fontSize: 12.8, color: T.textPrimary, marginBottom: 4 }}>{event.label}</strong>
                    <small style={{ display: 'block', fontSize: 11.4, color: T.textSecondary, lineHeight: 1.55 }}>{event.detail}</small>
                  </span>
                </div>
              ))}
            </div>
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
              {INTEGRATION_FLOW.map((item, i) => (
                <div className="integration-route-step" key={item.label}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
                    <span className="mono" style={{ color: '#727A8A', fontSize: 10, fontWeight: 800 }}>0{i + 1}</span>
                    <item.icon size={15} color="#EEF0F4" />
                  </div>
                  <div style={{ color: '#D8DBE2', fontSize: 12, fontWeight: 700, lineHeight: 1.35 }}>{item.label}</div>
                </div>
              ))}
            </div>

            <div style={{ padding: '13px 16px 0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <div>
                <div style={{ color: '#EEF0F4', fontSize: 13.5, fontWeight: 800 }}>Live Integration Logs</div>
                <div style={{ color: '#8B93A4', fontSize: 11.5, marginTop: 2 }}>Clean event stream across mail, WhatsApp, AI, Teams, calendar, and cloud</div>
              </div>
              <div className="mono" style={{ color: '#8B93A4', fontSize: 11 }}>latency 1.2s</div>
            </div>

            <div className="integration-log-list">
              {INTEGRATION_LOGS.map(log => (
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
              ))}
            </div>
          </div>
        </div>

        {/* CTA Banner */}
        <div style={{ background: T.brand, borderRadius: 16, padding: '40px 40px', textAlign: 'center', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', inset: 0, backgroundImage: `radial-gradient(circle at 20% 50%, rgba(255,255,255,0.06) 0%, transparent 50%), radial-gradient(circle at 80% 50%, rgba(255,255,255,0.04) 0%, transparent 50%)`, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', inset: 0, backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.04) 1px, transparent 1px)', backgroundSize: '28px 28px', pointerEvents: 'none' }} />
          <div style={{ position: 'relative', zIndex: 1 }}>
            <h2 style={{ fontSize: 'clamp(1.4rem,2.5vw,1.9rem)', fontWeight: 700, color: '#fff', margin: '0 0 10px', letterSpacing: '-0.03em' }}>
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
                      <span style={{ fontSize: 13, color: '#6B7280', cursor: 'pointer', transition: 'color 0.15s' }}
                        onMouseEnter={e => e.target.style.color = '#fff'}
                        onMouseLeave={e => e.target.style.color = '#6B7280'}>{l}</span>
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
