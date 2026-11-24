export default function PageLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--c-bg)]" role="status" aria-live="polite">
      <div className="flex items-center gap-3 text-sm font-medium text-slate-500">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-200 border-t-blue-600" />
        Loading TrainerSync
      </div>
    </div>
  )
}
