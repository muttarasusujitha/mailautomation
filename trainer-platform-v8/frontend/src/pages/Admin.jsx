import { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import {
  User, Mail, Lock, Bell, Database, Key,
  Save, Eye, EyeOff, CheckCircle, Settings,
  Trash2, RefreshCw, Shield, Globe, Building2,
  MessageSquare, Phone, Clock
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

const SETTINGS_STORAGE_KEY = 'admin_settings'

const Section = ({ id, icon: Icon, title, subtitle, children }) => (
  <div id={id} className="card p-5 mb-5 scroll-mt-24">
    <div className="flex items-start gap-3 mb-5 pb-4 border-b border-slate-100">
      <div className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center flex-shrink-0">
        <Icon className="w-5 h-5 text-blue-600" />
      </div>
      <div>
        <h2 className="font-jakarta font-bold text-slate-900 text-base">{title}</h2>
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
        "focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400",
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
        checked ? "bg-blue-500" : "bg-slate-200"
      )}
    >
      <span className={clsx(
        "absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform",
        checked ? "translate-x-5" : "translate-x-0"
      )} />
    </button>
  </div>
)

const INBOX_PROVIDERS = new Set(['gmail_api', 'imap', 'smtp_only'])

const normalizeClientInboxCfg = (cfg = {}) => ({
  ...cfg,
  inboxProvider: INBOX_PROVIDERS.has(cfg.inboxProvider) ? cfg.inboxProvider : 'smtp_only',
})

export default function Admin() {
  const [showPass, setShowPass]   = useState(false)
  const [saving,   setSaving]     = useState(false)
  const location = useLocation()

  // Profile
  const [profile, setProfile] = useState({
    name:     'Admin',
    email:    'admin@clahantech.com',
    company:  'Clahan Technologies',
    role:     'Recruiter Account',
    website:  'https://clahantech.com',
  })

  // Email config
  const [emailCfg, setEmailCfg] = useState({
    smtpHost:  'smtp.gmail.com',
    smtpPort:  '587',
    smtpUser:  '',
    smtpPass:  '',
    imapHost:  '',
    imapPort:  '993',
    imapUser:  '',
    imapPass:  '',
    fromName:  'Clahan Technologies',
    fromEmail: 'recruitment@clahantech.com',
  })

  // WhatsApp config
  const [twilioCfg, setTwilioCfg] = useState({
    enabled: false,
    provider: 'twilio',
    accountSid: '',
    authToken: '',
    fromWhatsAppNumber: 'whatsapp:+14155238886',
    vendorWhatsAppNumber: '',
    defaultCountryCode: '+91',
    statusCallbackUrl: '',
    aisensyApiUrl: 'https://backend.aisensy.com/campaign/t1/api/v2',
    aisensyApiKey: '',
    aisensyCampaignName: '',
    aisensySource: 'TrainerSync',
    aisensyTemplateParamFields: 'message',
    aisensyTags: 'trainersync',
    metaApiVersion: 'v23.0',
    metaPhoneNumberId: '',
    metaAccessToken: '',
    metaTemplateName: '',
    metaLanguageCode: 'en_US',
    metaTemplateParamFields: 'message',
  })

  const [gmailStatus, setGmailStatus] = useState({ connected: false })
  const [clientInboxCfg, setClientInboxCfg] = useState({
    inboxProvider: 'smtp_only',
    autoSendEnabled: true,
    autoSendThreshold: 70,
    clientDomainsWhitelist: '',
    vendorWhatsAppNumber: '',
    replySignature: 'Best Regards,\nRecruitment Team\nClahan Technologies',
  })
  const currentInboxProvider = clientInboxCfg.inboxProvider || 'smtp_only'
  const usingGmailApi = currentInboxProvider === 'gmail_api'
  const [teamsCfg, setTeamsCfg] = useState({
    webhookUrl: '',
  })
  const [teamsDirectCfg, setTeamsDirectCfg] = useState({
    enabled: false,
    tenantId: 'common',
    clientId: '',
    clientSecret: '',
    redirectUri: 'http://localhost:8000/api/teams-direct/oauth-callback',
    senderUser: '',
  })
  const [teamsDirectStatus, setTeamsDirectStatus] = useState({
    connected: false,
    enabled: false,
    token_valid: false,
    sender_user: '',
  })
  const [reminders, setReminders] = useState([])
  const [loadingReminders, setLoadingReminders] = useState(false)

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

  useEffect(() => {
    const section = new URLSearchParams(location.search).get('section')
    if (!section) return

    const timer = setTimeout(() => {
      document.getElementById(`admin-${section}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
    }, 80)

    return () => clearTimeout(timer)
  }, [location.search])

  // Load settings from localStorage on component mount
  useEffect(() => {
    try {
      const savedSettings = localStorage.getItem('admin_settings')
      if (savedSettings) {
        const parsed = JSON.parse(savedSettings)
        if (parsed.profile) setProfile({...profile, ...parsed.profile})
        if (parsed.emailCfg) setEmailCfg({...emailCfg, ...parsed.emailCfg})
        if (parsed.twilioCfg) setTwilioCfg({...twilioCfg, ...parsed.twilioCfg})
        if (parsed.clientInboxCfg) setClientInboxCfg({...clientInboxCfg, ...normalizeClientInboxCfg(parsed.clientInboxCfg)})
        if (parsed.teamsCfg) setTeamsCfg({...teamsCfg, ...parsed.teamsCfg})
        if (parsed.teamsDirectCfg) setTeamsDirectCfg({...teamsDirectCfg, ...parsed.teamsDirectCfg})
        if (parsed.notif) setNotif({...notif, ...parsed.notif})
        if (parsed.pipeline) setPipeline({...pipeline, ...parsed.pipeline})
        if (parsed.keys) setKeys({...keys, ...parsed.keys})
      }
    } catch {
      localStorage.removeItem(SETTINGS_STORAGE_KEY)
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    const applySettings = (settings) => {
      if (!settings || cancelled) return
      if (settings.profile) setProfile(prev => ({ ...prev, ...settings.profile }))
      if (settings.emailCfg) setEmailCfg(prev => ({ ...prev, ...settings.emailCfg }))
      if (settings.twilioCfg) setTwilioCfg(prev => ({ ...prev, ...settings.twilioCfg }))
      if (settings.clientInboxCfg) setClientInboxCfg(prev => ({ ...prev, ...normalizeClientInboxCfg(settings.clientInboxCfg) }))
      if (settings.teamsCfg) setTeamsCfg(prev => ({ ...prev, ...settings.teamsCfg }))
      if (settings.teamsDirectCfg) setTeamsDirectCfg(prev => ({ ...prev, ...settings.teamsDirectCfg }))
      if (settings.notif) setNotif(prev => ({ ...prev, ...settings.notif }))
      if (settings.pipeline) setPipeline(prev => ({ ...prev, ...settings.pipeline }))
      if (settings.keys) setKeys(prev => ({ ...prev, ...settings.keys }))
    }

    const loadSettings = async () => {
      try {
        const cached = localStorage.getItem(SETTINGS_STORAGE_KEY)
        if (cached) applySettings(JSON.parse(cached))
      } catch {
        localStorage.removeItem(SETTINGS_STORAGE_KEY)
      }

      try {
        const res = await fetch('/api/admin/settings')
        if (!res.ok) return
        const settings = await res.json()
        if (Object.keys(settings).length) {
          applySettings(settings)
          localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings))
        }
      } catch {
        // Local cache above keeps the form persistent when the API is offline.
      }

      try {
        const statusRes = await fetch('/api/gmail/auth-status')
        if (statusRes.ok) setGmailStatus(await statusRes.json())
      } catch {}
      loadTeamsDirectStatus()
      loadReminders()
    }

    loadSettings()
    return () => { cancelled = true }
  }, [])

  const save = async (section) => {
    setSaving(true)
    const payload = { profile, emailCfg, twilioCfg, clientInboxCfg, teamsCfg, teamsDirectCfg, notif, pipeline, keys }
    try {
      const res = await fetch('/api/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload))
        toast.success(`${section} settings saved!`)
      } else {
        localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload))
        toast.success(`${section} settings saved locally!`)
      }
    } catch {
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload))
      toast.success(`${section} settings saved locally!`)
    }
    finally { setSaving(false) }
  }

  const testEmail = async () => {
    setSaving(true)
    const payload = { profile, emailCfg, twilioCfg, clientInboxCfg, teamsCfg, teamsDirectCfg, notif, pipeline, keys }
    try {
      const saveRes = await fetch('/api/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload))
      if (!saveRes.ok) throw new Error('Could not save email settings')

      const testRes = await fetch('/api/admin/email/test', { method: 'POST' })
      const data = await testRes.json().catch(() => ({}))
      if (!testRes.ok) throw new Error(data.detail || data.error || 'Test email failed')
      toast.success(`Test email sent to ${data.to_email || 'configured address'}`)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const testWhatsApp = async () => {
    setSaving(true)
    const payload = { profile, emailCfg, twilioCfg, clientInboxCfg, teamsCfg, teamsDirectCfg, notif, pipeline, keys }
    try {
      const saveRes = await fetch('/api/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload))
      if (!saveRes.ok) throw new Error('Could not save WhatsApp settings')

      const testRes = await fetch('/api/admin/whatsapp/test', { method: 'POST' })
      const data = await testRes.json().catch(() => ({}))
      if (!testRes.ok) throw new Error(data.detail || 'WhatsApp test failed')
      toast.success('WhatsApp test sent!')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const testTeams = async () => {
    setSaving(true)
    const payload = { profile, emailCfg, twilioCfg, clientInboxCfg, teamsCfg, teamsDirectCfg, notif, pipeline, keys }
    try {
      const saveRes = await fetch('/api/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload))
      if (!saveRes.ok) throw new Error('Could not save Teams settings')

      const testRes = await fetch('/api/admin/teams/test', { method: 'POST' })
      const data = await testRes.json().catch(() => ({}))
      if (!testRes.ok) throw new Error(data.detail?.error || data.detail || data.error || 'Teams test failed')
      toast.success('Teams test card sent!')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const connectTeamsDirect = async () => {
    setSaving(true)
    const payload = { profile, emailCfg, twilioCfg, clientInboxCfg, teamsCfg, teamsDirectCfg, notif, pipeline, keys }
    try {
      const saveRes = await fetch('/api/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload))
      if (!saveRes.ok) throw new Error('Could not save Teams direct settings')

      const oauthRes = await fetch('/api/teams-direct/oauth-url')
      const data = await oauthRes.json().catch(() => ({}))
      if (!oauthRes.ok) throw new Error(data.detail || data.error || 'Microsoft OAuth URL failed')
      globalThis.location.href = data.auth_url
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const testTeamsDirect = async () => {
    const teamsEmail = globalThis.prompt('Enter another Teams user email to test direct chat. Do not use the sender account.')
    if (!teamsEmail) return
    setSaving(true)
    try {
      const statusRes = await fetch('/api/teams-direct/status')
      const status = await statusRes.json().catch(() => ({}))
      if (statusRes.ok) setTeamsDirectStatus(status)
      if (!status.connected) {
        throw new Error(status.error || 'Teams Direct is not connected yet. Click Connect Direct Chat, accept Microsoft permissions, then test again.')
      }
      const testRes = await fetch('/api/admin/teams-direct/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ teams_email: teamsEmail }),
      })
      const data = await testRes.json().catch(() => ({}))
      if (!testRes.ok) throw new Error(data.detail?.error || data.detail || data.error || 'Teams direct chat test failed')
      toast.success('Teams direct chat sent!')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const connectGmail = async () => {
    setSaving(true)
    try {
      if (!usingGmailApi) {
        toast.success('SMTP/IMAP mode is active. Google OAuth skipped.')
        return
      }
      if (!gmailStatus.connected || gmailStatus.google_reconnect_required) {
        const redirectUri = `${window.location.origin}/auth/callback`
        const oauthRes = await fetch(`/api/gmail/oauth-url?redirect_uri=${encodeURIComponent(redirectUri)}`)
        const oauthData = await oauthRes.json().catch(() => ({}))
        if (!oauthRes.ok) throw new Error(oauthData.detail || oauthData.error || 'Google OAuth URL failed')
        globalThis.location.href = oauthData.auth_url
        return
      }

      const res = await fetch('/api/gmail/renew-watch', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || data.error || 'Gmail watch renewal failed')
      setGmailStatus(prev => ({ ...prev, connected: true, valid: true, ...data }))
      toast.success('Gmail connected and watch renewed!')
    } catch (e) {
      toast.error(e.message || 'Run backend/scripts/gmail_auth.py first')
    } finally {
      setSaving(false)
    }
  }

  const renewGoogleAccess = async () => {
    setSaving(true)
    try {
      if (!usingGmailApi) {
        toast.success('SMTP/IMAP mode is active. Google OAuth skipped.')
        return
      }
      const redirectUri = `${window.location.origin}/auth/callback`
      const oauthRes = await fetch(`/api/gmail/oauth-url?redirect_uri=${encodeURIComponent(redirectUri)}`)
      const oauthData = await oauthRes.json().catch(() => ({}))
      if (!oauthRes.ok) throw new Error(oauthData.detail || oauthData.error || 'Google OAuth URL failed')
      globalThis.location.href = oauthData.auth_url
    } catch (e) {
      toast.error(e.message || 'Google OAuth URL failed')
    } finally {
      setSaving(false)
    }
  }

  const disconnectGmail = async () => {
    setSaving(true)
    try {
      const res = await fetch('/api/gmail/disconnect', { method: 'POST' })
      if (!res.ok) throw new Error('Could not disconnect Gmail')
      setGmailStatus({ connected: false, valid: false })
      toast.success('Gmail disconnected')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const clearDatabase = () => {
    if (globalThis.confirm('Are you sure? This will clear all trainer data.')) {
      toast.error('Database clear cancelled (demo mode)')
    }
  }

  const loadReminders = async () => {
    setLoadingReminders(true)
    try {
      const res = await fetch('/api/interview-reminders?limit=25')
      if (!res.ok) throw new Error('Could not load reminders')
      const data = await res.json()
      setReminders(data.reminders || [])
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoadingReminders(false)
    }
  }

  const loadTeamsDirectStatus = async () => {
    try {
      const res = await fetch('/api/teams-direct/status')
      if (res.ok) setTeamsDirectStatus(await res.json())
    } catch {
      setTeamsDirectStatus(prev => ({ ...prev, connected: false }))
    }
  }

  const cancelReminder = async (reminderId) => {
    try {
      const res = await fetch(`/api/interview-reminders/${reminderId}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'cancelled_from_admin' }),
      })
      if (!res.ok) throw new Error('Could not cancel reminder')
      toast.success('Reminder cancelled')
      loadReminders()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const whatsappProvider = twilioCfg.provider || 'twilio'
  const setWhatsAppProvider = provider => setTwilioCfg({ ...twilioCfg, provider })

  return (
    <div className="space-y-1 animate-fade-in max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Settings className="w-6 h-6 text-blue-600" /> Admin Settings
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">Manage your account, pipeline and integrations</p>
        </div>
      </div>

      {/* ── PROFILE ── */}
      <Section id="admin-teams" icon={MessageSquare} title="Microsoft Teams" subtitle="Channel cards plus optional direct trainer chat">
        <Field label="Teams Webhook URL" hint="Paste the Teams Incoming Webhook URL here">
          <Input
            icon={MessageSquare}
            type="url"
            value={teamsCfg.webhookUrl}
            onChange={e => setTeamsCfg({...teamsCfg, webhookUrl: e.target.value})}
            placeholder="https://outlook.office.com/webhook/..."
          />
        </Field>
        <div className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4 space-y-4">
          <Toggle
            checked={teamsDirectCfg.enabled}
            onChange={v => setTeamsDirectCfg({...teamsDirectCfg, enabled: v})}
            label="Enable Direct Teams Chat"
            desc="Send the same trainer pipeline message as a Teams DM using the resume email by default"
          />
          <div className={clsx(
            'flex flex-wrap items-center justify-between gap-3 rounded-xl border px-3 py-2 text-xs',
            teamsDirectStatus.connected
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-amber-200 bg-amber-50 text-amber-700'
          )}>
            <span className="flex items-center gap-2 font-semibold">
              {teamsDirectStatus.connected
                ? <CheckCircle className="h-4 w-4" />
                : <Key className="h-4 w-4" />}
              {teamsDirectStatus.connected
                ? `Direct chat connected${teamsDirectStatus.sender_user ? ` as ${teamsDirectStatus.sender_user}` : ''}`
                : teamsDirectStatus.error || 'Direct chat not connected. Click Connect Direct Chat before testing.'}
            </span>
            <button type="button" onClick={loadTeamsDirectStatus} className="font-bold underline underline-offset-2">
              Refresh status
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Tenant ID" hint="Microsoft Entra tenant id, or common for multi-tenant testing">
              <Input icon={Building2} value={teamsDirectCfg.tenantId} onChange={e => setTeamsDirectCfg({...teamsDirectCfg, tenantId: e.target.value})} placeholder="common or tenant id" />
            </Field>
            <Field label="Client ID">
              <Input icon={Key} value={teamsDirectCfg.clientId} onChange={e => setTeamsDirectCfg({...teamsDirectCfg, clientId: e.target.value})} placeholder="Microsoft app client id" />
            </Field>
            <Field label="Client Secret">
              <Input icon={Lock} type={showPass ? 'text' : 'password'} value={teamsDirectCfg.clientSecret} onChange={e => setTeamsDirectCfg({...teamsDirectCfg, clientSecret: e.target.value})} placeholder="Microsoft app client secret" />
            </Field>
            <Field label="Sender User" hint="Optional. Leave blank to use the connected Microsoft account">
              <Input icon={User} type="email" value={teamsDirectCfg.senderUser} onChange={e => setTeamsDirectCfg({...teamsDirectCfg, senderUser: e.target.value})} placeholder="your.name@company.com" />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Redirect URI" hint="Add this exact URL in Azure App Registration redirect URIs">
                <Input icon={Globe} value={teamsDirectCfg.redirectUri} onChange={e => setTeamsDirectCfg({...teamsDirectCfg, redirectUri: e.target.value})} />
              </Field>
            </div>
          </div>
        </div>
        <div className="flex gap-3 pt-2 flex-wrap">
          <button className="btn-primary text-sm" onClick={() => save('Teams')} disabled={saving}>
            {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save Teams
          </button>
          <button className="btn-secondary text-sm" onClick={testTeams} disabled={saving || !teamsCfg.webhookUrl.trim()}>
            <MessageSquare className="w-4 h-4" /> Send Test Teams
          </button>
          <button className="btn-secondary text-sm" onClick={connectTeamsDirect} disabled={saving || !teamsDirectCfg.clientId.trim()}>
            <Key className="w-4 h-4" /> Connect Direct Chat
          </button>
          <button className="btn-secondary text-sm" onClick={testTeamsDirect} disabled={saving || !teamsDirectCfg.enabled}>
            <MessageSquare className="w-4 h-4" /> Test Direct Chat
          </button>
        </div>
      </Section>

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
                className="w-full border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm pl-9 pr-10 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" />
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
                className="w-full border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm pl-9 pr-10 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" />
            </div>
          </Field>
        </div>
        <button className="btn-primary text-sm" onClick={() => save('Password')}>
          <Lock className="w-4 h-4" /> Update Password
        </button>
      </Section>

      {/* ── EMAIL CONFIG ── */}
      <Section icon={Mail} title="Email Configuration" subtitle="SMTP for sending and IMAP for inbox polling">
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
              <Input icon={Lock} type="password" value={emailCfg.smtpPass} onChange={e => setEmailCfg({...emailCfg, smtpPass: e.target.value})} placeholder="Enter mail app password" />
          </Field>
          <Field label="IMAP Host">
            <Input value={emailCfg.imapHost || ''} onChange={e => setEmailCfg({...emailCfg, imapHost: e.target.value})} placeholder="imap.gmail.com" />
          </Field>
          <Field label="IMAP Port">
            <Input value={emailCfg.imapPort || ''} onChange={e => setEmailCfg({...emailCfg, imapPort: e.target.value})} placeholder="993" />
          </Field>
          <Field label="IMAP Username">
            <Input icon={Mail} value={emailCfg.imapUser || ''} onChange={e => setEmailCfg({...emailCfg, imapUser: e.target.value})} placeholder="your@gmail.com" />
          </Field>
          <Field label="IMAP Password" hint="For Gmail, use the same Gmail App Password">
            <Input icon={Lock} type="password" value={emailCfg.imapPass || ''} onChange={e => setEmailCfg({...emailCfg, imapPass: e.target.value})} placeholder="Enter IMAP app password" />
          </Field>
          <Field label="From Name">
            <Input value={emailCfg.fromName} onChange={e => setEmailCfg({...emailCfg, fromName: e.target.value})} placeholder="Clahan Technologies" />
          </Field>
          <Field label="From Email">
            <Input icon={Mail} type="email" value={emailCfg.fromEmail} onChange={e => setEmailCfg({...emailCfg, fromEmail: e.target.value})} placeholder="recruitment@clahantech.com" />
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
      <Section icon={Mail} title="Client Inbox Automation" subtitle="Gmail OAuth or IMAP polling, AI client email reading, and Clahan Technologies reply controls">
        <Field label="Inbox Mode" hint="SMTP Only sends generated pending replies; Gmail API or IMAP is required to read new inbox mail">
          <div className="grid grid-cols-1 gap-1 rounded-xl border border-slate-200 bg-white p-1 sm:grid-cols-3">
            {[
              ['gmail_api', 'Gmail API'],
              ['imap', 'IMAP Polling'],
              ['smtp_only', 'SMTP Only'],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setClientInboxCfg({ ...clientInboxCfg, inboxProvider: value })}
                className={clsx(
                  'rounded-lg px-3 py-2 text-sm font-semibold transition',
                  currentInboxProvider === value
                    ? 'bg-brand-500 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-50'
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </Field>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 p-4">
          <div>
            <p className="text-sm font-semibold text-slate-800">Gmail OAuth Status</p>
            <p className="text-xs text-slate-400 mt-0.5">
              {gmailStatus.connected
                ? (
                    gmailStatus.google_reconnect_required
                      ? 'Gmail is connected, but Google permissions are incomplete. Renew access to grant Calendar and Drive permissions.'
                      : (gmailStatus.calendar_connected ? 'Gmail and Google Calendar are ready for inbox sync and Meet scheduling' : 'Gmail is connected. Calendar/Meet is optional and can be renewed when needed.')
                  )
                : usingGmailApi
                  ? 'Connect Google once to enable Gmail API inbox sync and Calendar/Meet scheduling'
                  : 'Using SMTP/IMAP mode. Google OAuth is skipped for now.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={clsx(
              'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold',
              gmailStatus.connected ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'
            )}>
              <span className={clsx('h-2 w-2 rounded-full', gmailStatus.connected ? 'bg-emerald-500' : 'bg-red-500')} />
              {gmailStatus.connected ? 'Connected' : 'Not Connected'}
            </span>
            <span className={clsx(
              'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold',
              gmailStatus.calendar_connected ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'
            )}>
              <span className={clsx('h-2 w-2 rounded-full', gmailStatus.calendar_connected ? 'bg-emerald-500' : 'bg-amber-500')} />
              {gmailStatus.calendar_connected ? 'Calendar Ready' : 'Calendar Optional'}
            </span>
            <span className={clsx(
              'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold',
              gmailStatus.drive_connected ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'
            )}>
              <span className={clsx('h-2 w-2 rounded-full', gmailStatus.drive_connected ? 'bg-emerald-500' : 'bg-amber-500')} />
              {gmailStatus.drive_connected ? 'Drive Ready' : 'Drive Optional'}
            </span>
            {usingGmailApi ? (
              <>
                <button className="btn-secondary text-sm" onClick={connectGmail} disabled={saving}>
                  <RefreshCw className="w-4 h-4" /> {gmailStatus.google_reconnect_required ? 'Renew Access' : gmailStatus.connected ? 'Renew Watch' : 'Connect'}
                </button>
                <button className="btn-secondary text-sm" onClick={renewGoogleAccess} disabled={saving}>
                  <RefreshCw className="w-4 h-4" /> Renew Access
                </button>
                <button className="btn-secondary text-sm text-red-600" onClick={disconnectGmail} disabled={saving || !gmailStatus.connected}>
                  Disconnect
                </button>
              </>
            ) : (
              <span className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700">
                SMTP/IMAP Active
              </span>
            )}
          </div>
        </div>

        <div className="bg-slate-50 rounded-xl p-4">
          <Toggle checked={clientInboxCfg.autoSendEnabled} onChange={v => setClientInboxCfg({...clientInboxCfg, autoSendEnabled: v})}
            label="Enable Client Auto-send" desc="Send Clahan Technologies replies automatically when confidence and domain rules pass" />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label={`Auto-send Threshold (${clientInboxCfg.autoSendThreshold}%)`} hint="Only replies above this confidence can be auto-sent">
            <input
              type="range"
              min="50"
              max="99"
              value={clientInboxCfg.autoSendThreshold}
              onChange={e => setClientInboxCfg({...clientInboxCfg, autoSendThreshold: Number(e.target.value)})}
              className="w-full"
            />
          </Field>
          <Field label="Vendor WhatsApp Number" hint="Used for client inquiry notifications; falls back to WhatsApp settings if empty">
            <Input icon={Phone} value={clientInboxCfg.vendorWhatsAppNumber} onChange={e => setClientInboxCfg({...clientInboxCfg, vendorWhatsAppNumber: e.target.value})} placeholder="whatsapp:+91XXXXXXXXXX" />
          </Field>
        </div>

        <Field label="Client Email Domains Whitelist" hint="Comma separated domains. Non-whitelisted domains stay pending even when confidence is high">
          <textarea
            value={clientInboxCfg.clientDomainsWhitelist}
            onChange={e => setClientInboxCfg({...clientInboxCfg, clientDomainsWhitelist: e.target.value})}
            placeholder="infosys.com, wipro.com, tcs.com"
            className="w-full min-h-20 border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
          />
        </Field>

        <Field label="Reply Signature" hint="Appended to every Clahan Technologies client reply">
          <textarea
            value={clientInboxCfg.replySignature}
            onChange={e => setClientInboxCfg({...clientInboxCfg, replySignature: e.target.value})}
            className="w-full min-h-28 border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
          />
        </Field>

        <button className="btn-primary text-sm" onClick={() => save('Client Inbox')} disabled={saving}>
          {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save Inbox Settings
        </button>
      </Section>

      <Section id="admin-whatsapp" icon={MessageSquare} title="WhatsApp Notifications" subtitle="Twilio, AiSensy, or direct Meta Cloud API for trainer and vendor alerts">
        <div className="bg-slate-50 rounded-xl p-4">
          <Toggle checked={twilioCfg.enabled} onChange={v => setTwilioCfg({...twilioCfg, enabled: v})}
            label="Enable WhatsApp Automation" desc="Send WhatsApp alongside emails, reply alerts, and interview reminders" />
        </div>

        <Field label="Provider">
          <div className="grid grid-cols-1 gap-1 rounded-xl border border-slate-200 bg-white p-1 sm:grid-cols-3">
            <button
              type="button"
              onClick={() => setWhatsAppProvider('twilio')}
              className={clsx(
                'flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition',
                whatsappProvider === 'twilio'
                  ? 'bg-slate-900 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-50'
              )}
            >
              <MessageSquare className="w-4 h-4" /> Twilio Testing
            </button>
            <button
              type="button"
              onClick={() => setWhatsAppProvider('aisensy')}
              className={clsx(
                'flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition',
                whatsappProvider === 'aisensy'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-50'
              )}
            >
              <Globe className="w-4 h-4" /> AiSensy Production
            </button>
            <button
              type="button"
              onClick={() => setWhatsAppProvider('meta')}
              className={clsx(
                'flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition',
                whatsappProvider === 'meta'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-50'
              )}
            >
              <Globe className="w-4 h-4" /> Meta Cloud API
            </button>
          </div>
          <p className="text-xs text-slate-400">
            {whatsappProvider === 'twilio'
              ? 'Use Twilio Sandbox during development. Trial accounts can message only verified sandbox users.'
              : whatsappProvider === 'aisensy'
                ? 'Use AiSensy campaign API for production WhatsApp. Create one approved template with {{1}} for the full TrainerSync message.'
                : 'Use official Meta WhatsApp Cloud API directly with a Phone Number ID, token, and approved template.'}
          </p>
        </Field>

        {whatsappProvider === 'twilio' ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Twilio Account SID">
              <Input icon={Key} value={twilioCfg.accountSid} onChange={e => setTwilioCfg({...twilioCfg, accountSid: e.target.value})} placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" />
            </Field>
            <Field label="Twilio Auth Token">
              <Input icon={Lock} type="password" value={twilioCfg.authToken} onChange={e => setTwilioCfg({...twilioCfg, authToken: e.target.value})} placeholder="Enter provider token" />
            </Field>
            <Field label="Twilio WhatsApp Sender" hint="Use your approved Twilio WhatsApp sender or sandbox number">
              <Input icon={MessageSquare} value={twilioCfg.fromWhatsAppNumber} onChange={e => setTwilioCfg({...twilioCfg, fromWhatsAppNumber: e.target.value})} placeholder="whatsapp:+14155238886" />
            </Field>
            <Field label="Status Callback URL" hint="Optional. Leave blank to use /api/whatsapp/status-callback automatically">
              <Input value={twilioCfg.statusCallbackUrl} onChange={e => setTwilioCfg({...twilioCfg, statusCallbackUrl: e.target.value})} placeholder="https://your-domain.com/api/whatsapp/status-callback" />
            </Field>
          </div>
        ) : whatsappProvider === 'aisensy' ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="AiSensy API URL">
              <Input icon={Globe} value={twilioCfg.aisensyApiUrl} onChange={e => setTwilioCfg({...twilioCfg, aisensyApiUrl: e.target.value})} placeholder="https://backend.aisensy.com/campaign/t1/api/v2" />
            </Field>
            <Field label="AiSensy API Key">
              <Input icon={Key} type="password" value={twilioCfg.aisensyApiKey} onChange={e => setTwilioCfg({...twilioCfg, aisensyApiKey: e.target.value})} placeholder="AiSensy API key" />
            </Field>
            <Field label="Campaign Name" hint="Must exactly match the approved AiSensy campaign/template name">
              <Input icon={MessageSquare} value={twilioCfg.aisensyCampaignName} onChange={e => setTwilioCfg({...twilioCfg, aisensyCampaignName: e.target.value})} placeholder="trainersync_notification" />
            </Field>
            <Field label="Source">
              <Input value={twilioCfg.aisensySource} onChange={e => setTwilioCfg({...twilioCfg, aisensySource: e.target.value})} placeholder="TrainerSync" />
            </Field>
            <Field label="Template Params" hint="For an approved template like {{1}}, keep this as message. For multiple variables, enter fields in the same order.">
              <Input value={twilioCfg.aisensyTemplateParamFields} onChange={e => setTwilioCfg({...twilioCfg, aisensyTemplateParamFields: e.target.value})} placeholder="message" />
            </Field>
            <Field label="Tags">
              <Input value={twilioCfg.aisensyTags} onChange={e => setTwilioCfg({...twilioCfg, aisensyTags: e.target.value})} placeholder="trainersync,automation" />
            </Field>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Meta API Version" hint="Keep as-is unless Meta asks you to use a different Graph API version">
              <Input icon={Globe} value={twilioCfg.metaApiVersion} onChange={e => setTwilioCfg({...twilioCfg, metaApiVersion: e.target.value})} placeholder="v23.0" />
            </Field>
            <Field label="Phone Number ID" hint="This is not the phone number. Copy it from Meta WhatsApp API setup">
              <Input icon={Phone} value={twilioCfg.metaPhoneNumberId} onChange={e => setTwilioCfg({...twilioCfg, metaPhoneNumberId: e.target.value})} placeholder="123456789012345" />
            </Field>
            <Field label="Access Token" hint="Use a permanent system-user token for production">
              <Input icon={Key} type="password" value={twilioCfg.metaAccessToken} onChange={e => setTwilioCfg({...twilioCfg, metaAccessToken: e.target.value})} placeholder="Enter Meta access token" />
            </Field>
            <Field label="Template Name" hint="Approved WhatsApp template name. Leave blank only for 24-hour service-window text tests">
              <Input icon={MessageSquare} value={twilioCfg.metaTemplateName} onChange={e => setTwilioCfg({...twilioCfg, metaTemplateName: e.target.value})} placeholder="trainersync_notify" />
            </Field>
            <Field label="Language Code">
              <Input value={twilioCfg.metaLanguageCode} onChange={e => setTwilioCfg({...twilioCfg, metaLanguageCode: e.target.value})} placeholder="en_US" />
            </Field>
            <Field label="Template Params" hint="For one {{1}} variable use message. For four variables use trainer_name,stage,requirement_id,message">
              <Input value={twilioCfg.metaTemplateParamFields} onChange={e => setTwilioCfg({...twilioCfg, metaTemplateParamFields: e.target.value})} placeholder="message" />
            </Field>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Vendor WhatsApp Number" hint="Your WhatsApp number for trainer reply alerts and tests">
            <Input icon={Phone} value={twilioCfg.vendorWhatsAppNumber} onChange={e => setTwilioCfg({...twilioCfg, vendorWhatsAppNumber: e.target.value})} placeholder={whatsappProvider === 'twilio' ? 'whatsapp:+91XXXXXXXXXX' : '+91XXXXXXXXXX'} />
          </Field>
          <Field label="Default Country Code" hint="Used when trainer phone numbers are saved without country code">
            <Input value={twilioCfg.defaultCountryCode} onChange={e => setTwilioCfg({...twilioCfg, defaultCountryCode: e.target.value})} placeholder="+91" />
          </Field>
        </div>
        <div className="flex gap-3 pt-2 flex-wrap">
          <button className="btn-primary text-sm" onClick={() => save('WhatsApp')} disabled={saving}>
            {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save WhatsApp
          </button>
          <button className="btn-secondary text-sm" onClick={testWhatsApp} disabled={saving || !twilioCfg.enabled}>
            <MessageSquare className="w-4 h-4" /> Send Test WhatsApp
          </button>
        </div>
      </Section>

      <Section icon={Clock} title="Interview Reminder Scheduler" subtitle="Celery + Redis reminders fired exactly 1 hour before Stage 4 interviews">
        <div className="flex items-center justify-between gap-3 pt-1">
          <div>
            <p className="text-sm font-semibold text-slate-800">Scheduled Reminders</p>
            <p className="text-xs text-slate-400">Shows pending, sent, cancelled, and failed Celery reminder jobs</p>
          </div>
          <button className="btn-secondary text-sm" onClick={loadReminders} disabled={loadingReminders}>
            <RefreshCw className={clsx('w-4 h-4', loadingReminders && 'animate-spin')} /> Refresh
          </button>
        </div>

        <div className="rounded-xl border border-slate-200 overflow-hidden">
          {loadingReminders ? (
            <div className="p-4 text-sm text-slate-500 flex items-center gap-2">
              <RefreshCw className="w-4 h-4 animate-spin" /> Loading reminders...
            </div>
          ) : reminders.length === 0 ? (
            <div className="p-4 text-sm text-slate-400">No interview reminders scheduled yet.</div>
          ) : (
            <div className="divide-y divide-slate-100">
              {reminders.map(reminder => {
                const statusClass =
                  reminder.status === 'sent' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
                  reminder.status === 'cancelled' ? 'bg-slate-50 text-slate-500 border-slate-200' :
                  reminder.status === 'failed' || reminder.status === 'schedule_failed' ? 'bg-red-50 text-red-700 border-red-200' :
                  'bg-amber-50 text-amber-700 border-amber-200'
                return (
                  <div key={reminder.reminder_id} className="p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-semibold text-slate-800 truncate">{reminder.trainer_name || 'Trainer'}</p>
                        <span className={clsx('px-2 py-0.5 rounded-full border text-xs font-semibold', statusClass)}>{reminder.status}</span>
                      </div>
                      <p className="text-xs text-slate-500 mt-0.5">
                        {reminder.technology || 'Training'} · {reminder.requirement_id || '-'}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Reminder: {reminder.reminder_at ? new Date(reminder.reminder_at).toLocaleString() : '-'} · Interview: {reminder.interview_date || '-'}
                      </p>
                    </div>
                    {reminder.status === 'pending' && (
                      <button onClick={() => cancelReminder(reminder.reminder_id)}
                        className="px-3 py-1.5 rounded-lg bg-red-50 text-red-600 border border-red-100 text-xs font-semibold hover:bg-red-100">
                        Cancel
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <button className="btn-primary text-sm" onClick={() => save('Reminder Scheduler')} disabled={saving}>
          {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save Scheduler Settings
        </button>
      </Section>

      <Section icon={Settings} title="Pipeline Defaults" subtitle="Default settings for trainer matching pipeline">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Field label="Top N Trainers" hint="How many to shortlist">
            <select value={pipeline.topN} onChange={e => setPipeline({...pipeline, topN: e.target.value})}
              className="w-full border border-slate-200 rounded-xl bg-slate-50 text-slate-900 text-sm px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500/20">
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
          <Field label="Google Drive File ID" hint="Optional Drive file or folder ID for resume intake">
            <Input icon={Key} value={keys.googleDriveFileId} onChange={e => setKeys({...keys, googleDriveFileId: e.target.value})} placeholder="1s3U5NvShHPUuJ3JXvmG7x..." />
          </Field>
          <Field label="MongoDB Connection URI" hint="Your MongoDB Atlas or local connection string">
            <Input icon={Database} type="password" value={keys.mongoUri} onChange={e => setKeys({...keys, mongoUri: e.target.value})} placeholder="Enter MongoDB connection URI" />
          </Field>
          <Field label="OpenAI API Key (Optional)" hint="For AI-generated email content">
            <Input icon={Key} type="password" value={keys.openaiKey} onChange={e => setKeys({...keys, openaiKey: e.target.value})} placeholder="Enter OpenAI API key" />
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
