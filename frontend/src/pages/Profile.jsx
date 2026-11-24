import { useCallback, useEffect, useState } from 'react'
import { User, Mail, Phone, MapPin, Building2, Edit2, Save, X, Camera, CheckCircle2, Link2, RefreshCw, Send, Unlink } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../utils/api'
import { normalizeGmailStatus, saveGmailOAuthPkce } from '../utils/gmailOAuth'

export default function Profile() {
  const [gmailStatus, setGmailStatus] = useState({ connected: false, email: '' })
  const [gmailBusy, setGmailBusy] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [profile, setProfile] = useState({
    name: 'Recruiter Name',
    email: 'recruiter@company.com',
    phone: '+91 98765 43210',
    company: 'Your Company',
    location: 'Hyderabad, India',
    designation: 'Talent Acquisition Manager',
    bio: 'Experienced recruiter focused on technical talent acquisition'
  })
  const [editData, setEditData] = useState(profile)

  const loadGmailStatus = useCallback(async () => {
    try {
      const response = await api.get('/gmail/me/auth-status')
      setGmailStatus(normalizeGmailStatus(response.data || {}))
    } catch (error) {
      setGmailStatus(normalizeGmailStatus({ connected: false }))
      if (error?.status && error.status !== 401) toast.error(error.message || 'Could not load your Gmail connection')
    }
  }, [])

  useEffect(() => {
    loadGmailStatus()
    const params = new URLSearchParams(window.location.search)
    if (params.get('gmail_connected') === '1') toast.success('Your Gmail account is connected.')
    if (params.get('gmail_error')) toast.error(`Google rejected the connection: ${params.get('gmail_error')}`)
    if (params.has('gmail_connected') || params.has('gmail_error')) {
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [loadGmailStatus])

  const connectGmail = async () => {
    setGmailBusy(true)
    try {
      const response = await api.get('/gmail/me/oauth-url')
      const data = response.data || {}
      const authUrl = data.auth_url || data.url
      if (!authUrl) throw new Error('Google did not return an authorization link')
      saveGmailOAuthPkce(data)
      window.location.assign(authUrl)
    } catch (error) {
      toast.error(error.message || 'Could not start Google sign-in')
      setGmailBusy(false)
    }
  }

  const sendGmailTest = async () => {
    setGmailBusy(true)
    try {
      const response = await api.post('/gmail/me/test-send')
      toast.success(`Test email sent to ${response.data?.sent_to || gmailStatus.email}`)
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Test email failed')
    } finally {
      setGmailBusy(false)
    }
  }

  const disconnectGmail = async () => {
    setGmailBusy(true)
    try {
      await api.post('/gmail/me/disconnect')
      setGmailStatus({ connected: false, email: '' })
      toast.success('Your Gmail connection was removed.')
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Could not disconnect Gmail')
    } finally {
      setGmailBusy(false)
    }
  }

  const handleEdit = () => {
    setIsEditing(true)
    setEditData(profile)
  }

  const handleSave = () => {
    setProfile(editData)
    setIsEditing(false)
    toast.success('Profile updated successfully!')
  }

  const handleCancel = () => {
    setIsEditing(false)
    setEditData(profile)
  }

  const handleChange = (field, value) => {
    setEditData(prev => ({ ...prev, [field]: value }))
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <User className="w-6 h-6" />
            My Profile
          </h1>
          <p className="text-sm text-slate-500 mt-1">View and manage your account information</p>
        </div>
        {!isEditing && (
          <button
            onClick={handleEdit}
            className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-all duration-200 font-medium"
          >
            <Edit2 className="w-4 h-4" />
            Edit Profile
          </button>
        )}
      </div>

      <section className="card p-6" aria-labelledby="personal-gmail-title">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="rounded-xl bg-blue-50 p-3 text-blue-700"><Mail className="h-5 w-5" /></span>
            <div>
              <h2 id="personal-gmail-title" className="text-lg font-bold text-slate-900">My Gmail connection</h2>
              <p className="mt-1 max-w-2xl text-sm text-slate-600">
                Connect your own Google account to test TrainerSync email delivery. This connection is private to your login and only grants permission to send mail from your account; it does not connect you to the company inbox.
              </p>
            </div>
          </div>
          <span className={`inline-flex w-fit items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold ${gmailStatus.connected ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
            {gmailStatus.connected ? <CheckCircle2 className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
            {gmailStatus.connected ? 'Connected' : 'Not connected'}
          </span>
        </div>
        {gmailStatus.connected && (
          <p className="mt-4 text-sm font-semibold text-slate-800">Connected account: {gmailStatus.email || 'Google account'}</p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {!gmailStatus.connected ? (
            <button type="button" onClick={connectGmail} disabled={gmailBusy} className="btn-primary text-sm disabled:opacity-50">
              <Link2 className="h-4 w-4" /> Connect my Gmail
            </button>
          ) : (
            <>
              <button type="button" onClick={sendGmailTest} disabled={gmailBusy} className="btn-primary text-sm disabled:opacity-50">
                <Send className="h-4 w-4" /> Send test email to myself
              </button>
              <button type="button" onClick={loadGmailStatus} disabled={gmailBusy} className="btn-secondary text-sm disabled:opacity-50">
                <RefreshCw className="h-4 w-4" /> Refresh status
              </button>
              <button type="button" onClick={disconnectGmail} disabled={gmailBusy} className="btn-secondary text-sm text-red-700 disabled:opacity-50">
                <Unlink className="h-4 w-4" /> Disconnect my Gmail
              </button>
            </>
          )}
        </div>
      </section>

      {/* Profile Card */}
      <div className="card p-8">
        <div className="space-y-8">
          {/* Avatar Section */}
          <div className="flex flex-col items-center gap-4">
            <div className="relative group">
              <div className="w-24 h-24 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center text-white text-4xl font-bold shadow-lg">
                {profile.name.charAt(0)}
              </div>
              {isEditing && (
                <button className="absolute bottom-0 right-0 p-2 bg-white rounded-full shadow-lg hover:bg-slate-50 transition-all">
                  <Camera className="w-4 h-4 text-blue-600" />
                </button>
              )}
            </div>
            <div className="text-center">
              <h2 className="text-2xl font-bold text-slate-900">{profile.name}</h2>
              <p className="text-slate-600 text-sm">{profile.designation}</p>
            </div>
          </div>

          {/* Profile Information */}
          <div className="grid md:grid-cols-2 gap-6">
            {/* Name */}
            <div>
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2 block">Name</label>
              {isEditing ? (
                <input
                  type="text"
                  value={editData.name}
                  onChange={(e) => handleChange('name', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              ) : (
                <p className="text-lg font-medium text-slate-900">{profile.name}</p>
              )}
            </div>

            {/* Email */}
            <div>
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2 flex items-center gap-2">
                <Mail className="w-4 h-4" /> Email
              </label>
              {isEditing ? (
                <input
                  type="email"
                  value={editData.email}
                  onChange={(e) => handleChange('email', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              ) : (
                <p className="text-lg font-medium text-slate-900">{profile.email}</p>
              )}
            </div>

            {/* Phone */}
            <div>
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2 flex items-center gap-2">
                <Phone className="w-4 h-4" /> Phone
              </label>
              {isEditing ? (
                <input
                  type="tel"
                  value={editData.phone}
                  onChange={(e) => handleChange('phone', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              ) : (
                <p className="text-lg font-medium text-slate-900">{profile.phone}</p>
              )}
            </div>

            {/* Company */}
            <div>
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2 flex items-center gap-2">
                <Building2 className="w-4 h-4" /> Company
              </label>
              {isEditing ? (
                <input
                  type="text"
                  value={editData.company}
                  onChange={(e) => handleChange('company', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              ) : (
                <p className="text-lg font-medium text-slate-900">{profile.company}</p>
              )}
            </div>

            {/* Location */}
            <div>
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2 flex items-center gap-2">
                <MapPin className="w-4 h-4" /> Location
              </label>
              {isEditing ? (
                <input
                  type="text"
                  value={editData.location}
                  onChange={(e) => handleChange('location', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              ) : (
                <p className="text-lg font-medium text-slate-900">{profile.location}</p>
              )}
            </div>

            {/* Designation */}
            <div>
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2 block">Designation</label>
              {isEditing ? (
                <input
                  type="text"
                  value={editData.designation}
                  onChange={(e) => handleChange('designation', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                />
              ) : (
                <p className="text-lg font-medium text-slate-900">{profile.designation}</p>
              )}
            </div>
          </div>

          {/* Bio */}
          <div>
            <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2 block">Bio</label>
            {isEditing ? (
              <textarea
                value={editData.bio}
                onChange={(e) => handleChange('bio', e.target.value)}
                rows="4"
                className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white resize-none"
              />
            ) : (
              <p className="text-slate-700 leading-relaxed">{profile.bio}</p>
            )}
          </div>

          {/* Action Buttons */}
          {isEditing && (
            <div className="flex gap-3 pt-4 border-t border-slate-200">
              <button
                onClick={handleSave}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-all duration-200 font-medium"
              >
                <Save className="w-4 h-4" />
                Save Changes
              </button>
              <button
                onClick={handleCancel}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200 transition-all duration-200 font-medium"
              >
                <X className="w-4 h-4" />
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Account Stats */}
      <div className="grid md:grid-cols-3 gap-4">
        <div className="card p-6 text-center">
          <div className="text-3xl font-bold text-blue-600 mb-2">256</div>
          <p className="text-sm text-slate-600">Trainers Contacted</p>
        </div>
        <div className="card p-6 text-center">
          <div className="text-3xl font-bold text-emerald-600 mb-2">42</div>
          <p className="text-sm text-slate-600">Active Hires</p>
        </div>
        <div className="card p-6 text-center">
          <div className="text-3xl font-bold text-purple-600 mb-2">89%</div>
          <p className="text-sm text-slate-600">Response Rate</p>
        </div>
      </div>
    </div>
  )
}
