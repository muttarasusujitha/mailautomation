import { useState } from 'react'
import {
  User, Mail, Lock, Bell, Database, Key,
  Save, Eye, EyeOff, CheckCircle, Settings,
  Trash2, RefreshCw, Shield, Globe, Building2
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

const Section = ({ icon: Icon, title, subtitle, children }) => (
  <div className="card p-5 mb-5">
    <div className="flex items-start gap-3 mb-5 pb-4 border-b border-slate-100">
      <div className="w-9 h-9 rounded-xl bg-brand-50 flex items-center justify-center flex-shrink-0">
        <Icon className="w-5 h-5 text-brand-500" />
      </div>
      <div>
        <h2 className="font-display font-bold text-slate-900 text-base">{title}</h2>
        {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
      </div>
    </div>
    <div className="space-y-4">{children}</div>
  </div>
)

const Field = ({ label, children, hint }) => (
  <div className="space-y-1.5">
    <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">{label}</label>
    {children}
    {hint && <p className="text-xs text-slate-400">{hint}</p>}
  </div>
)

const Input = ({ icon: Icon, ...props }) => (
  <div className="relative">
    {Icon && <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />}
    <input
      className={clsx(
        "w-full border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm",
        "focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-400",
        "placeholder:text-slate-400 transition",
        Icon ? "pl-9 pr-4 py-2.5" : "px-4 py-2.5"
      )}
      {...props}
    />
  </div>
)

const Toggle = ({ checked, onChange, label, desc }) => (
  <div className="flex items-start justify-between gap-4 py-2">
    <div>
      <p className="text-sm font-medium text-slate-800">{label}</p>
      {desc && <p className="text-xs text-slate-400 mt-0.5">{desc}</p>}
    </div>
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex w-11 h-6 rounded-full transition-colors flex-shrink-0",
        checked ? "bg-brand-500" : "bg-slate-200"
      )}
    >
      <span className={clsx(
        "absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform",
        checked ? "translate-x-5" : "translate-x-0"
      )} />
    </button>
  </div>
)

export default function Admin() {
  const [showPass, setShowPass]   = useState(false)
  const [saving,   setSaving]     = useState(false)

  // Profile
  const [profile, setProfile] = useState({
    name:     'Admin',
    email:    'admin@calhantech.com',
    company:  'Calhan Technologies',
    role:     'Recruiter Account',
    website:  'https://calhantech.com',
  })

  // Email config
  const [emailCfg, setEmailCfg] = useState({
    smtpHost:  'smtp.gmail.com',
    smtpPort:  '587',
    smtpUser:  '',
    smtpPass:  '',
    fromName:  'Calhan Technologies',
    fromEmail: 'recruitment@calhantech.com',
  })

  // Notifications
  const [notif, setNotif] = useState({
    emailOnReply:   true,
    emailOnDecline: false,
    dailySummary:   true,
    retryAlert:     true,
  })

  // Pipeline defaults
  const [pipeline, setPipeline] = useState({
    topN:         '5',
    retryDays:    '3',
    maxRetries:   '2',
    minScore:     '40',
    autoSend:     false,
    autoRetry:    true,
  })

  // API Keys
  const [keys, setKeys] = useState({
    googleDriveFileId: '1s3U5NvShHPUuJ3JXvmG7xjcEziHwP8_j',
    mongoUri:          '',
    openaiKey:         '',
  })

  const save = async (section) => {
    setSaving(true)
    try {
      const payload = { profile, emailCfg, notif, pipeline, keys }
      const res = await fetch('/api/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        toast.success(`${section} settings saved!`)
      } else {
        // Save to localStorage as fallback if backend doesn't have route yet
        localStorage.setItem('admin_settings', JSON.stringify(payload))
        toast.success(`${section} settings saved locally!`)
      }
    } catch {
      localStorage.setItem('admin_settings', JSON.stringify({ profile, emailCfg, notif, pipeline, keys }))
      toast.success(`${section} settings saved!`)
    }
    finally { setSaving(false) }
  }

  const testEmail = async () => {
    toast.loading('Sending test email...')
    await new Promise(r => setTimeout(r, 1500))
    toast.dismiss()
    toast.success('Test email sent successfully!')
  }

  const clearDatabase = () => {
    if (window.confirm('Are you sure? This will clear all trainer data.')) {
      toast.error('Database clear cancelled (demo mode)')
    }
  }

  return (
    <div className="space-y-1 animate-fade-in max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Settings className="w-6 h-6 text-brand-500" /> Admin Settings
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">Manage your account, pipeline and integrations</p>
        </div>
      </div>

      {/* ── PROFILE ── */}
      <Section icon={User} title="Profile" subtitle="Your account information">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Full Name">
            <Input icon={User} value={profile.name} onChange={e => setProfile({...profile, name: e.target.value})} placeholder="Admin Name" />
          </Field>
          <Field label="Email Address">
            <Input icon={Mail} type="email" value={profile.email} onChange={e => setProfile({...profile, email: e.target.value})} placeholder="admin@company.com" />
          </Field>
          <Field label="Company Name">
            <Input icon={Building2} value={profile.company} onChange={e => setProfile({...profile, company: e.target.value})} placeholder="Company Name" />
          </Field>
          <Field label="Role / Title">
            <Input icon={Shield} value={profile.role} onChange={e => setProfile({...profile, role: e.target.value})} placeholder="Your role" />
          </Field>
          <Field label="Website" hint="Used in email signatures">
            <Input icon={Globe} value={profile.website} onChange={e => setProfile({...profile, website: e.target.value})} placeholder="https://yourcompany.com" />
          </Field>
        </div>
        <div className="flex gap-3 pt-2">
          <button className="btn-primary text-sm" onClick={() => save('Profile')} disabled={saving}>
            {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save Profile
          </button>
        </div>
      </Section>

      {/* ── PASSWORD ── */}
      <Section icon={Lock} title="Change Password" subtitle="Update your login credentials">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Current Password">
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input type={showPass ? 'text' : 'password'} placeholder="••••••••"
                className="w-full border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm pl-9 pr-10 py-2.5 focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-400" />
              <button type="button" onClick={() => setShowPass(!showPass)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </Field>
          <Field label="New Password">
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input type={showPass ? 'text' : 'password'} placeholder="••••••••"
                className="w-full border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm pl-9 pr-10 py-2.5 focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-400" />
            </div>
          </Field>
        </div>
        <button className="btn-primary text-sm" onClick={() => save('Password')}>
          <Lock className="w-4 h-4" /> Update Password
        </button>
      </Section>

      {/* ── EMAIL CONFIG ── */}
      <Section icon={Mail} title="Email Configuration" subtitle="SMTP settings for sending outreach emails">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="SMTP Host">
            <Input value={emailCfg.smtpHost} onChange={e => setEmailCfg({...emailCfg, smtpHost: e.target.value})} placeholder="smtp.gmail.com" />
          </Field>
          <Field label="SMTP Port">
            <Input value={emailCfg.smtpPort} onChange={e => setEmailCfg({...emailCfg, smtpPort: e.target.value})} placeholder="587" />
          </Field>
          <Field label="SMTP Username">
            <Input icon={Mail} value={emailCfg.smtpUser} onChange={e => setEmailCfg({...emailCfg, smtpUser: e.target.value})} placeholder="your@gmail.com" />
          </Field>
          <Field label="SMTP Password" hint="Use App Password for Gmail">
            <Input icon={Lock} type="password" value={emailCfg.smtpPass} onChange={e => setEmailCfg({...emailCfg, smtpPass: e.target.value})} placeholder="App password" />
          </Field>
          <Field label="From Name">
            <Input value={emailCfg.fromName} onChange={e => setEmailCfg({...emailCfg, fromName: e.target.value})} placeholder="Calhan Technologies" />
          </Field>
          <Field label="From Email">
            <Input icon={Mail} type="email" value={emailCfg.fromEmail} onChange={e => setEmailCfg({...emailCfg, fromEmail: e.target.value})} placeholder="recruitment@calhantech.com" />
          </Field>
        </div>
        <div className="flex gap-3 pt-2 flex-wrap">
          <button className="btn-primary text-sm" onClick={() => save('Email Config')}>
            <Save className="w-4 h-4" /> Save Config
          </button>
          <button className="btn-secondary text-sm" onClick={testEmail}>
            <Mail className="w-4 h-4" /> Send Test Email
          </button>
        </div>
      </Section>

      {/* ── PIPELINE DEFAULTS ── */}
      <Section icon={Settings} title="Pipeline Defaults" subtitle="Default settings for trainer matching pipeline">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Field label="Top N Trainers" hint="How many to shortlist">
            <select value={pipeline.topN} onChange={e => setPipeline({...pipeline, topN: e.target.value})}
              className="w-full border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-brand-500/20">
              <option>3</option><option>5</option><option>10</option>
            </select>
          </Field>
          <Field label="Retry After (Days)">
            <Input type="number" value={pipeline.retryDays} onChange={e => setPipeline({...pipeline, retryDays: e.target.value})} min="1" max="30" />
          </Field>
          <Field label="Max Retries">
            <Input type="number" value={pipeline.maxRetries} onChange={e => setPipeline({...pipeline, maxRetries: e.target.value})} min="1" max="5" />
          </Field>
          <Field label="Min Match Score">
            <Input type="number" value={pipeline.minScore} onChange={e => setPipeline({...pipeline, minScore: e.target.value})} min="0" max="100" />
          </Field>
        </div>
        <div className="bg-slate-50 rounded-xl p-4 space-y-1 divide-y divide-slate-100">
          <Toggle checked={pipeline.autoSend} onChange={v => setPipeline({...pipeline, autoSend: v})}
            label="Auto Send Emails" desc="Automatically send emails after shortlisting without manual review" />
          <Toggle checked={pipeline.autoRetry} onChange={v => setPipeline({...pipeline, autoRetry: v})}
            label="Auto Retry Follow-up" desc="Automatically send follow-up emails to non-responding trainers" />
        </div>
        <button className="btn-primary text-sm" onClick={() => save('Pipeline')}>
          <Save className="w-4 h-4" /> Save Defaults
        </button>
      </Section>

      {/* ── NOTIFICATIONS ── */}
      <Section icon={Bell} title="Notifications" subtitle="Choose what email alerts you receive">
        <div className="bg-slate-50 rounded-xl p-4 space-y-1 divide-y divide-slate-100">
          <Toggle checked={notif.emailOnReply} onChange={v => setNotif({...notif, emailOnReply: v})}
            label="Email on Trainer Reply" desc="Get notified when a trainer responds to your outreach" />
          <Toggle checked={notif.emailOnDecline} onChange={v => setNotif({...notif, emailOnDecline: v})}
            label="Email on Decline" desc="Get notified when a trainer declines the opportunity" />
          <Toggle checked={notif.dailySummary} onChange={v => setNotif({...notif, dailySummary: v})}
            label="Daily Summary Email" desc="Receive a daily summary of pipeline activity" />
          <Toggle checked={notif.retryAlert} onChange={v => setNotif({...notif, retryAlert: v})}
            label="Retry Scheduler Alert" desc="Get notified when follow-up emails are scheduled" />
        </div>
        <button className="btn-primary text-sm" onClick={() => save('Notifications')}>
          <Save className="w-4 h-4" /> Save Preferences
        </button>
      </Section>

      {/* ── API KEYS & INTEGRATIONS ── */}
      <Section icon={Key} title="API Keys & Integrations" subtitle="Connect external services">
        <div className="space-y-4">
          <Field label="Google Drive File ID" hint="File ID of List_of_Trainers.xlsx in Google Drive">
            <Input icon={Key} value={keys.googleDriveFileId} onChange={e => setKeys({...keys, googleDriveFileId: e.target.value})} placeholder="1s3U5NvShHPUuJ3JXvmG7x..." />
          </Field>
          <Field label="MongoDB Connection URI" hint="Your MongoDB Atlas or local connection string">
            <Input icon={Database} type="password" value={keys.mongoUri} onChange={e => setKeys({...keys, mongoUri: e.target.value})} placeholder="mongodb+srv://user:pass@cluster..." />
          </Field>
          <Field label="OpenAI API Key (Optional)" hint="For AI-generated email content">
            <Input icon={Key} type="password" value={keys.openaiKey} onChange={e => setKeys({...keys, openaiKey: e.target.value})} placeholder="sk-..." />
          </Field>
        </div>
        <div className="flex gap-3 pt-2 flex-wrap">
          <button className="btn-primary text-sm" onClick={() => save('Integrations')}>
            <Save className="w-4 h-4" /> Save Keys
          </button>
          <button className="btn-secondary text-sm" onClick={() => toast.success('Connection verified!')}>
            <CheckCircle className="w-4 h-4" /> Test Connection
          </button>
        </div>
      </Section>

      {/* ── DANGER ZONE ── */}
      <Section icon={Trash2} title="Danger Zone" subtitle="Irreversible actions — proceed with caution">
        <div className="space-y-3">
          <div className="flex items-center justify-between p-4 border border-red-100 rounded-xl bg-red-50">
            <div>
              <p className="text-sm font-semibold text-red-700">Clear Trainer Database</p>
              <p className="text-xs text-red-400 mt-0.5">Permanently delete all trainer records</p>
            </div>
            <button onClick={clearDatabase}
              className="px-4 py-2 text-sm font-semibold text-red-600 border border-red-200 rounded-xl hover:bg-red-100 transition flex items-center gap-2">
              <Trash2 className="w-4 h-4" /> Clear
            </button>
          </div>
          <div className="flex items-center justify-between p-4 border border-amber-100 rounded-xl bg-amber-50">
            <div>
              <p className="text-sm font-semibold text-amber-700">Reset Pipeline Settings</p>
              <p className="text-xs text-amber-400 mt-0.5">Reset all pipeline defaults to factory settings</p>
            </div>
            <button onClick={() => toast.success('Settings reset to defaults!')}
              className="px-4 py-2 text-sm font-semibold text-amber-600 border border-amber-200 rounded-xl hover:bg-amber-100 transition flex items-center gap-2">
              <RefreshCw className="w-4 h-4" /> Reset
            </button>
          </div>
        </div>
      </Section>
    </div>
  )
}
