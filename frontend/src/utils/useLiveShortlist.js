import { useEffect } from 'react'
import { getShortlist } from './api'

// Refresh delivery evidence even while the automatic sender is disabled.
export function useLiveShortlist(requirementId, setTrainers, intervalMs) {
  useEffect(() => {
    if (!requirementId) return
    let cancelled = false
    let pending = false
    const refresh = async () => {
      if (cancelled || pending) return
      pending = true
      try {
        const response = await getShortlist(requirementId)
        if (!cancelled) setTrainers(response.data.top_trainers || response.data.trainers || [])
      } catch {
        // Keep the last server snapshot on transient network errors.
      } finally {
        pending = false
      }
    }
    const timer = setInterval(refresh, intervalMs)
    window.addEventListener('focus', refresh)
    return () => {
      cancelled = true
      clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [requirementId, setTrainers, intervalMs])
}
