import { useEffect } from 'react'
import { getShortlist } from './api'

// Refresh delivery evidence even while the automatic sender is disabled.
export function useLiveShortlist(requirementId, setTrainers, intervalMs, maxTrainers = 3) {
  useEffect(() => {
    if (!requirementId) return
    let cancelled = false
    let pending = false
    const controller = new AbortController()
    const refresh = async () => {
      if (cancelled || pending || document.hidden) return
      pending = true
      try {
        const response = await getShortlist(requirementId, { signal: controller.signal })
        if (!cancelled) {
          const next = (response.data.top_trainers || response.data.trainers || []).slice(0, maxTrainers)
          setTrainers(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next)
        }
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
      controller.abort()
      clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [requirementId, setTrainers, intervalMs, maxTrainers])
}
