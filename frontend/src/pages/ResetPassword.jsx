import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import api from '../utils/api'

function tokenFromHash() {
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash
  return new URLSearchParams(hash).get('token') || ''
}

export default function ResetPassword() {
  const navigate = useNavigate()
  const token = useMemo(() => tokenFromHash(), [])
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async event => {
    event.preventDefault()
    if (!token) {
      toast.error('This reset link is missing its token.')
      return
    }
    if (password.length < 12) {
      toast.error('Use at least 12 characters.')
      return
    }
    if (password !== confirm) {
      toast.error('Passwords do not match.')
      return
    }
    setSaving(true)
    try {
      const { data } = await api.post('/auth/reset-password', { token, password })
      toast.success(data.message || 'Password changed. Sign in with your new password.')
      navigate('/login', { replace: true })
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Reset link is invalid or expired')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--c-bg)] px-4">
      <form onSubmit={submit} className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">Choose a new password</h1>
        <p className="mt-1 text-sm text-slate-500">Reset links expire after 30 minutes.</p>
        <label className="mt-5 block text-xs font-semibold text-slate-600">
          New password
          <input
            type="password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            autoComplete="new-password"
            className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        <label className="mt-3 block text-xs font-semibold text-slate-600">
          Confirm password
          <input
            type="password"
            value={confirm}
            onChange={event => setConfirm(event.target.value)}
            autoComplete="new-password"
            className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={saving}
          className="mt-5 w-full rounded-2xl bg-blue-600 py-2.5 text-sm font-bold text-white disabled:opacity-60"
        >
          {saving ? 'Saving...' : 'Update password'}
        </button>
      </form>
    </div>
  )
}
