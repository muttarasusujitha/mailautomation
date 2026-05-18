import { useState, useEffect } from 'react'
import { User, Mail, Phone, MapPin, Building2, Edit2, Save, X, Camera } from 'lucide-react'
import toast from 'react-hot-toast'

export default function Profile() {
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
