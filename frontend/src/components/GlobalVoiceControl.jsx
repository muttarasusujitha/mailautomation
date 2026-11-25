import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Mic, MicOff, X } from 'lucide-react'
import { resolveNavigationRoute } from '../utils/navigation'

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
const VOICE_SEARCH_STATE = 'trainersync_voice_search'

function visibleSearchInput() {
  return [...document.querySelectorAll('.page-content input:not([type="hidden"]):not([disabled])')]
    .find(input => {
      const label = `${input.getAttribute('aria-label') || ''} ${input.placeholder || ''}`
      return input.getClientRects().length > 0 && /search|find/i.test(label)
    })
}

function applySearch(query, onMissing) {
  const started = Date.now()
  const attempt = () => {
    const input = visibleSearchInput()
    if (input) {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      setter?.call(input, query)
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.dispatchEvent(new Event('change', { bubbles: true }))
      const form = input.closest('form')
      if (form) form.requestSubmit()
      return true
    }
    if (Date.now() - started > 8000) onMissing()
    return false
  }

  if (attempt()) return () => {}
  const interval = window.setInterval(() => {
    if (attempt()) window.clearInterval(interval)
    else if (Date.now() - started > 8000) window.clearInterval(interval)
  }, 250)
  return () => window.clearInterval(interval)
}

export default function GlobalVoiceControl({ groups }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [listening, setListening] = useState(false)
  const [command, setCommand] = useState('')
  const [message, setMessage] = useState('')
  const recognitionRef = useRef(null)
  const transcriptRef = useRef('')
  const stopSearchRef = useRef(null)

  const searchOnPage = useCallback((query) => {
    const clean = query.trim()
    if (!clean) return
    setMessage(`Searching this page for "${clean}"`)
    stopSearchRef.current?.()
    stopSearchRef.current = applySearch(clean, () => {
      setMessage('This page has no searchable field. Say "open [page name]" to navigate.')
    })
  }, [])

  const runCommand = useCallback((spoken) => {
    const clean = String(spoken || '').trim()
    if (!clean) return
    setCommand(clean)
    setMessage('')

    if (/^(go )?back$/i.test(clean)) {
      navigate(-1)
      setMessage('Going back')
      return
    }

    const openMatch = clean.match(/^(?:(?:please\s+)?(?:go to|open|navigate to|take me to|show me))\s+(.+)$/i)
    if (openMatch) {
      const route = resolveNavigationRoute(openMatch[1], groups)
      if (route) {
        navigate(route)
        setMessage(`Opening ${openMatch[1].trim()}`)
        return
      }
      setMessage(`I could not find a page called "${openMatch[1].trim()}".`)
      return
    }

    const searchMatch = clean.match(/^(?:search(?: for)?|find|look for)\s+(.+)$/i)
    if (searchMatch) {
      const query = searchMatch[1].trim()
      const pageTarget = query.match(/\s+(?:in|on)\s+(.+)$/i)
      const targetRoute = pageTarget ? resolveNavigationRoute(pageTarget[1], groups) : null
      const searchText = targetRoute ? query.slice(0, pageTarget.index).trim() : query
      if (targetRoute && targetRoute !== location.pathname) {
        sessionStorage.setItem(VOICE_SEARCH_STATE, JSON.stringify({ query: searchText, route: targetRoute }))
        navigate(targetRoute)
        setMessage(`Opening the page and searching for "${searchText}"`)
      } else {
        searchOnPage(searchText)
      }
      return
    }

    const route = resolveNavigationRoute(clean, groups)
    if (route) {
      navigate(route)
      setMessage(`Opening ${clean}`)
      return
    }
    setMessage('Try "open invoices", "go to trainer database", or "search for AWS".')
  }, [groups, location.pathname, navigate, searchOnPage])

  useEffect(() => {
    let pending
    try { pending = JSON.parse(sessionStorage.getItem(VOICE_SEARCH_STATE) || 'null') } catch { pending = null }
    if (!pending || pending.route !== location.pathname) return
    sessionStorage.removeItem(VOICE_SEARCH_STATE)
    stopSearchRef.current?.()
    stopSearchRef.current = applySearch(pending.query, () => {
      setMessage('Opened the page, but it has no searchable field.')
    })
  }, [location.pathname])

  useEffect(() => () => {
    recognitionRef.current?.abort()
    stopSearchRef.current?.()
  }, [])

  const startListening = () => {
    if (!SpeechRecognition) {
      setMessage('Voice recognition is not supported here. Type a command instead.')
      setOpen(true)
      return
    }
    const recognition = new SpeechRecognition()
    recognition.lang = 'en-IN'
    recognition.continuous = false
    recognition.interimResults = false
    transcriptRef.current = ''
    recognition.onresult = event => {
      transcriptRef.current = Array.from(event.results).map(result => result[0]?.transcript || '').join(' ').trim()
      setCommand(transcriptRef.current)
    }
    recognition.onerror = event => {
      setListening(false)
      setMessage(event.error === 'not-allowed' ? 'Allow microphone access to use voice commands.' : `Voice command failed: ${event.error || 'unknown error'}`)
    }
    recognition.onend = () => {
      setListening(false)
      if (transcriptRef.current) runCommand(transcriptRef.current)
    }
    recognitionRef.current = recognition
    setListening(true)
    setMessage('Listening...')
    try { recognition.start() } catch (error) {
      setListening(false)
      setMessage(error.message || 'Could not start voice recognition.')
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        className="rounded-lg border border-blue-200 bg-blue-50 p-2 text-blue-700 shadow-xs hover:bg-blue-100"
        aria-label="Open voice app control"
        title="Voice app control"
      >
        <Mic className="h-4 w-4" />
      </button>
      {open && (
        <div className="fixed right-4 top-16 z-[90] w-[min(24rem,calc(100vw-2rem))] rounded-2xl border border-slate-200 bg-white p-4 shadow-2xl">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-bold text-slate-900">Voice app control</h2>
              <p className="text-xs text-slate-500">Navigate or search from any page.</p>
            </div>
            <button type="button" onClick={() => { recognitionRef.current?.stop(); setListening(false); setOpen(false) }} aria-label="Close voice control" className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100">
              <X className="h-4 w-4" />
            </button>
          </div>
          <form className="mt-3 flex gap-2" onSubmit={event => { event.preventDefault(); runCommand(command) }}>
            <input
              value={command}
              onChange={event => setCommand(event.target.value)}
              placeholder="Open invoices or search for AWS"
              aria-label="Voice command"
              className="input min-w-0 flex-1"
            />
            <button type="button" onClick={listening ? () => recognitionRef.current?.stop() : startListening} className={listening ? 'btn-danger px-3' : 'btn-primary px-3'} aria-label={listening ? 'Stop listening' : 'Start listening'}>
              {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </button>
          </form>
          {message && <p role="status" className="mt-2 text-xs text-slate-600">{message}</p>}
          <p className="mt-3 text-[11px] leading-5 text-slate-400">Examples: "go to trainer database", "open client requests", "search for Kubernetes in trainer database".</p>
          <p className="mt-2 text-[11px] leading-5 text-amber-700">Voice control only navigates and runs searches. Review and submit emails, approvals, deletions, and other changes in their page.</p>
        </div>
      )}
    </div>
  )
}
