import { ChevronLeft, ChevronRight } from 'lucide-react'
import { pageSummary } from '../utils/leadPaging'

// Previous / next paging for a server list. Shows nothing when there is nothing to page.
export default function Pager({ page, pages, total, pageSize, loading = false, onPage, noun = 'results' }) {
  if (!total) return null
  const { first, last } = pageSummary({ page, pageSize, total })
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm">
      <span className="text-slate-500">{first}–{last} of {total} {noun}</span>
      {pages > 1 && (
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => onPage(page - 1)} disabled={loading || page <= 1} className="btn-secondary text-sm disabled:opacity-50">
            <ChevronLeft className="h-4 w-4" /> Previous
          </button>
          <span className="text-slate-600">Page {page} of {pages}</span>
          <button type="button" onClick={() => onPage(page + 1)} disabled={loading || page >= pages} className="btn-secondary text-sm disabled:opacity-50">
            Next <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}
    </nav>
  )
}
