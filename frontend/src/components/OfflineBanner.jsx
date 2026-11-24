import { useEffect, useState } from 'react'

export default function OfflineBanner() {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine)

  useEffect(() => {
    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  if (isOnline) return null

  return (
    <div className="fixed inset-x-0 top-0 z-[70] border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm font-semibold text-amber-800 shadow-sm">
      Network connection lost. Changes may not sync until you are back online.
    </div>
  )
}
