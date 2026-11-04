import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowUpRight, CalendarCheck, CheckCircle2, Clock3, FileText,
  MessageSquare, MoreHorizontal, Star, Users, XCircle,
} from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import api from '../utils/api'

const CLIENT_STAGES = [
  { label: 'New requests', value: 8, color: '#2563eb' },
  { label: 'Matching', value: 5, color: '#06b6d4' },
  { label: 'Shortlisted', value: 12, color: '#8b5cf6' },
  { label: 'Interview', value: 4, color: '#f59e0b' },
  { label: 'Selected', value: 7, color: '#10b981' },
]

const TRAINER_STAGES = [
  { label: 'New opportunities', value: 6, color: '#2563eb' },
  { label: 'Under review', value: 3, color: '#8b5cf6' },
  { label: 'Interview', value: 2, color: '#f59e0b' },
  { label: 'Selected', value: 4, color: '#10b981' },
  { label: 'Rejected', value: 1, color: '#ef4444' },
]

function Card({ children, className = '' }) {
  return <section className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>{children}</section>
}

function MiniStat({ icon: Icon, label, value, note, tone }) {
  return (
    <Card className="relative overflow-hidden">
      <div className={`absolute right-0 top-0 h-20 w-20 rounded-bl-full ${tone}`} />
      <div className="relative">
        <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600"><Icon className="h-5 w-5" /></div>
        <p className="text-xs font-bold uppercase tracking-wide text-slate-400">{label}</p>
        <p className="mt-1 text-3xl font-extrabold tracking-tight text-slate-900">{value}</p>
        <p className="mt-1 text-xs font-medium text-slate-500">{note}</p>
      </div>
    </Card>
  )
}

function PipelineCard({ stages, trainer }) {
  const total = stages.reduce((sum, stage) => sum + stage.value, 0)
  return (
    <Card className="xl:col-span-2">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div><p className="text-xs font-bold uppercase tracking-widest text-blue-600">Workflow overview</p><h2 className="mt-1 text-lg font-extrabold text-slate-900">Pipeline status</h2></div>
        <button type="button" className="rounded-lg p-2 text-slate-400 hover:bg-slate-50"><MoreHorizontal className="h-5 w-5" /></button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {stages.map((stage, index) => (
          <div key={stage.label} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
            <div className="mb-4 flex items-center justify-between"><span className="h-2.5 w-2.5 rounded-full" style={{ background: stage.color }} /><span className="text-[10px] font-bold text-slate-400">0{index + 1}</span></div>
            <p className="text-2xl font-extrabold text-slate-900">{stage.value}</p>
            <p className="mt-1 min-h-8 text-xs font-semibold text-slate-500">{stage.label}</p>
            <div className="mt-3 h-1.5 rounded-full bg-slate-200"><div className="h-full rounded-full" style={{ background: stage.color, width: `${Math.max(14, (stage.value / total) * 100)}%` }} /></div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-slate-500">{trainer ? 'Your opportunities are moving through review, interviews, and selection.' : 'Track every client request from first message to confirmed trainer.'}</p>
    </Card>
  )
}

export default function Portal({ type }) {
  const navigate = useNavigate()
  const trainer = type === 'trainer'
  const stages = trainer ? TRAINER_STAGES : CLIENT_STAGES
  const [profile, setProfile] = useState(null)
  useEffect(() => {
    let active = true
    api.get('/auth/me').then(({ data }) => { if (active) setProfile(data.user) }).catch(() => {})
    return () => { active = false }
  }, [])
  const chartData = useMemo(() => trainer
    ? [{ name: 'Selected', value: 4, color: '#10b981' }, { name: 'In review', value: 3, color: '#8b5cf6' }, { name: 'Rejected', value: 1, color: '#ef4444' }]
    : [{ name: 'Selected', value: 7, color: '#10b981' }, { name: 'Active', value: 17, color: '#2563eb' }, { name: 'Waiting', value: 5, color: '#f59e0b' }], [trainer])
  const name = profile?.name || (trainer ? 'Trainer' : 'Client')

  return (
    <div className="min-h-full space-y-5 animate-fade-in">
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-[#173bba] via-[#2563eb] to-[#38bdf8] p-6 text-white shadow-xl shadow-blue-200/50 lg:p-8">
        <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-white/10" />
        <div className="relative z-10 flex flex-wrap items-end justify-between gap-6">
          <div><p className="text-xs font-bold uppercase tracking-[.2em] text-blue-100">{trainer ? 'Trainer portal' : 'Client portal'}</p><h1 className="mt-2 text-3xl font-extrabold tracking-tight">Good morning, {name}</h1><p className="mt-2 max-w-xl text-sm text-blue-100">{trainer ? 'Discover opportunities, manage interviews, and keep your profile ready for the next great assignment.' : 'Your complete training delivery workspace — requests, trainer matches, and selections in one view.'}</p></div>
          <button type="button" onClick={() => navigate(trainer ? '/profile' : '/client-requests')} className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-bold text-blue-700 shadow-lg hover:bg-blue-50">{trainer ? 'Update profile' : 'Create request'} <ArrowUpRight className="h-4 w-4" /></button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {trainer ? <><MiniStat icon={FileText} label="Opportunities" value="06" note="3 new this week" tone="bg-cyan-100" /><MiniStat icon={CalendarCheck} label="Interviews" value="02" note="Next one tomorrow" tone="bg-amber-100" /><MiniStat icon={CheckCircle2} label="Selected" value="04" note="2 active assignments" tone="bg-emerald-100" /><MiniStat icon={Star} label="Profile score" value="92%" note="Top 10% of trainers" tone="bg-violet-100" /></>
          : <><MiniStat icon={FileText} label="Requests" value="08" note="2 need attention" tone="bg-cyan-100" /><MiniStat icon={Users} label="Shortlisted" value="12" note="Across 4 requirements" tone="bg-violet-100" /><MiniStat icon={CalendarCheck} label="Interviews" value="04" note="Next one on Friday" tone="bg-amber-100" /><MiniStat icon={CheckCircle2} label="Selected" value="07" note="Ready to schedule" tone="bg-emerald-100" /></>}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <PipelineCard stages={stages} trainer={trainer} />
        <Card>
          <p className="text-xs font-bold uppercase tracking-widest text-blue-600">Portfolio mix</p><h2 className="mt-1 text-lg font-extrabold text-slate-900">{trainer ? 'Application outcomes' : 'Request health'}</h2>
          <div className="relative mx-auto mt-3 h-48 w-48"><ResponsiveContainer><PieChart><Pie data={chartData} dataKey="value" innerRadius={56} outerRadius={78} paddingAngle={4} stroke="none">{chartData.map(item => <Cell key={item.name} fill={item.color} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer><div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"><span className="text-3xl font-extrabold text-slate-900">{trainer ? '08' : '29'}</span><span className="text-xs font-semibold text-slate-400">total</span></div></div>
          <div className="space-y-2">{chartData.map(item => <div key={item.name} className="flex items-center justify-between text-xs"><span className="flex items-center gap-2 font-semibold text-slate-600"><i className="h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />{item.name}</span><span className="font-bold text-slate-900">{item.value}</span></div>)}</div>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card><div className="mb-4 flex items-center justify-between"><div><p className="text-xs font-bold uppercase tracking-widest text-blue-600">{trainer ? 'Your shortlist' : 'Trainer shortlist'}</p><h2 className="mt-1 text-lg font-extrabold text-slate-900">{trainer ? 'Selected opportunities' : 'Selected & rejected'}</h2></div><button type="button" onClick={() => navigate(trainer ? '/profile' : '/shortlist')} className="text-xs font-bold text-blue-600">View all</button></div>
          <div className="space-y-3">{(trainer ? [['AWS Cloud Trainer', 'Selected for interview', CheckCircle2, 'text-emerald-500'], ['Python Bootcamp', 'Profile under review', Clock3, 'text-amber-500'], ['DevOps Workshop', 'Selected assignment', CheckCircle2, 'text-emerald-500']] : [['Priya Sharma', 'Selected · Cloud Architecture', CheckCircle2, 'text-emerald-500'], ['Arun Kumar', 'Selected · Python Training', CheckCircle2, 'text-emerald-500'], ['Meera Nair', 'Rejected · Schedule mismatch', XCircle, 'text-red-500']]).map(([title, sub, Icon, color]) => <div key={title} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3"><span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100"><Icon className={`h-4 w-4 ${color}`} /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-bold text-slate-800">{title}</span><span className="block truncate text-xs text-slate-500">{sub}</span></span><ArrowUpRight className="h-4 w-4 text-slate-300" /></div>)}</div>
        </Card>
        <Card><div className="mb-4 flex items-center justify-between"><div><p className="text-xs font-bold uppercase tracking-widest text-blue-600">Recent activity</p><h2 className="mt-1 text-lg font-extrabold text-slate-900">What needs your attention</h2></div><MessageSquare className="h-5 w-5 text-blue-500" /></div><div className="space-y-3">{[['Today', trainer ? 'A client viewed your trainer profile' : 'New trainer matches are ready to review'], ['Yesterday', trainer ? 'Interview invitation received for AWS Cloud' : 'Interview confirmed for Python requirement'], ['Mon', trainer ? 'Your profile score increased to 92%' : 'Purchase order approved for selected trainers']].map(([time, text]) => <div key={time} className="flex gap-3 border-b border-slate-100 pb-3 last:border-0 last:pb-0"><span className="mt-1 h-2 w-2 rounded-full bg-blue-500" /><div><p className="text-sm font-semibold text-slate-700">{text}</p><p className="mt-1 text-xs text-slate-400">{time}</p></div></div>)}</div></Card>
      </div>
    </div>
  )
}
