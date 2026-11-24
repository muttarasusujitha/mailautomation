import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import api from '../utils/api'
import { leadSearchWarnings, searchReportGroups } from '../utils/leadSearchFeedback'

function warningsOf(report) {
  const messages = leadSearchWarnings(report)
  for (const message of Array.isArray(report?.warnings) ? report.warnings : []) {
    if (message && !messages.includes(message)) messages.push(message)
  }
  return messages
}

// What the last search found, per domain and per search source (worked, blocked, not answering...).
// When the request itself failed, report.searchRef lets the user load the report the server saved
// for that same search, once it finishes.
export default function SearchSourceReport({ report, noun = 'results', children = null }) {
  const [savedRun, setSavedRun] = useState(null)
  const [checking, setChecking] = useState(false)
  useEffect(() => { setSavedRun(null) }, [report])
  if (!report) return null

  const shown = savedRun || report
  const groups = searchReportGroups(shown)
  const warnings = warningsOf(shown)
  const found = Number(shown.found) || 0
  const saved = Number(shown.saved_count) || 0

  const checkSavedRun = async () => {
    setChecking(true)
    try {
      const res = await api.get('/linkedin-leads/search-runs', { params: { search_ref: report.searchRef, limit: 1 } })
      const run = res.data.runs?.[0]
      if (run) setSavedRun(run)
      else toast('No saved report for this search yet. It may still be running; check again in a minute.')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <section role="status" aria-live="polite" className="space-y-2 rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-sm font-semibold text-slate-800">
        {shown.requestFailed
          ? 'The search request did not complete.'
          : `${savedRun ? 'Saved report of this search' : 'Last search'}: ${found} found; ${saved} new ${noun} saved.`}
      </p>
      {groups.map(group => (
        <div key={group.key} className="space-y-1">
          {group.heading && <p className="text-sm text-slate-600">{group.heading}</p>}
          {group.lines.length > 0 && (
            <ul className="ml-4 list-disc text-xs text-slate-500">
              {group.lines.map(line => <li key={line.key} className={line.ok ? 'text-emerald-700' : undefined}>{line.text}</li>)}
            </ul>
          )}
        </div>
      ))}
      {warnings.map(message => <p key={message} className="text-sm text-amber-800">{message}</p>)}
      {shown.requestFailed && report.searchRef && (
        <button type="button" onClick={checkSavedRun} disabled={checking} className="btn-secondary text-sm disabled:opacity-50">
          {checking ? 'Checking…' : 'Check the saved search report'}
        </button>
      )}
      {children}
    </section>
  )
}
