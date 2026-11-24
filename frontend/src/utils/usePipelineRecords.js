import { useCallback, useEffect, useRef, useState } from 'react'
import api from './api'
import { createRequestGate } from './requestPolicy'
import { normalizePipelineItem } from './pipelineRecords'

export function usePipelineRecords(query) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const gate = useRef(createRequestGate())
  const currentQuery = useRef(query)
  const active = useRef(false)
  currentQuery.current = query

  // A completion from a long action should refresh the current search, even
  // if the user changed the search while the action was in flight.
  const load = useCallback(async (silent = false) => {
    if (!active.current) return
    const request = gate.current.start()
    setRefreshing(true)
    setError('')
    if (!silent) setLoading(true)
    try {
      const response = await api.get('/client-pipeline', {
        params: { q: currentQuery.current || undefined, limit: 150, include_timeline: false },
        signal: request.signal,
      })
      if (request.isCurrent()) setItems((response.data.pipeline || []).map(normalizePipelineItem))
    } catch (err) {
      if (request.isCurrent()) setError(err.message || 'Could not load records. Try again.')
    } finally {
      if (request.isCurrent()) { setLoading(false); setRefreshing(false) }
      request.finish()
    }
  }, [])

  useEffect(() => {
    active.current = true
    const requestGate = gate.current
    const timer = setTimeout(() => load(), 250)
    return () => {
      active.current = false
      clearTimeout(timer)
      requestGate.cancel()
    }
  }, [query, load])

  return { items, setItems, loading, refreshing, error, load }
}
