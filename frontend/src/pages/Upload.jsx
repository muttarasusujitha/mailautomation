import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import {
  AlertCircle,
  Archive,
  CheckCircle2,
  Database,
  FileText,
  Loader2,
  Mail,
  MapPin,
  Phone,
  RefreshCw,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react'
import {
  confirmResumePreviews,
  deleteResumeDataByEmail,
  deleteResumeDataByDomain,
  getResumeDomainSummary,
  previewResumeDataByDomain,
  uploadResumes,
} from '../utils/api'

const CATEGORY_STYLES = {
  DevOps: 'bg-slate-100 text-slate-600 border-slate-200',
  'Gen AI': 'bg-slate-100 text-slate-600 border-slate-200',
  'Data Engineering': 'bg-slate-100 text-slate-600 border-slate-200',
  'Agentic AI': 'bg-slate-100 text-slate-600 border-slate-200',
  'Full Stack': 'bg-slate-100 text-slate-600 border-slate-200',
}

function formatSize(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function categoryClass(category) {
  return CATEGORY_STYLES[category] || 'bg-slate-100 text-slate-600 border-slate-200'
}

function FileList({ files, progress, onRemove }) {
  if (!files.length) return null

  return (
    <div className="mt-4 divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200 bg-white">
      {files.map(file => (
        <div key={`${file.name}-${file.lastModified}`} className="p-3 transition-colors hover:bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
              <FileText className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-800 truncate">{file.name}</p>
              <p className="text-xs text-slate-400">{formatSize(file.size)}</p>
            </div>
            <button
              type="button"
              onClick={() => onRemove(file)}
              className="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          {progress[file.name] != null && (
            <div className="mt-2 h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div className="h-full rounded-full bg-slate-500 transition-all" style={{ width: `${progress[file.name]}%` }} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function DropArea({ title, hint, icon: Icon, accept, files, onDrop, progress, onRemove }) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept,
    multiple: true,
    onDrop,
  })

  return (
    <section className="overflow-hidden rounded-xl border border-blue-100 bg-white shadow-sm">
      <div className="flex items-start justify-between gap-3 border-b border-blue-100 bg-blue-50/70 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="section-title">{title}</h2>
            <p className="text-xs text-slate-500">{hint}</p>
          </div>
        </div>
        <span className="rounded-full border border-blue-200 bg-white px-2.5 py-1 text-xs font-bold text-blue-700">{files.length} selected</span>
      </div>

      <div
        {...getRootProps()}
        className={clsx(
          'm-4 flex min-h-[190px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors',
          isDragActive ? 'border-blue-500 bg-blue-50' : 'border-blue-200 bg-blue-50/40 hover:border-blue-500 hover:bg-blue-50'
        )}
      >
        <input {...getInputProps()} />
        <UploadCloud className="mb-3 h-8 w-8 text-blue-600" />
        <p className="text-base font-semibold text-slate-800">{isDragActive ? 'Drop files to add them' : 'Drag files here or browse'}</p>
        <p className="mt-1 max-w-sm text-sm text-slate-500">Upload resumes and review the extracted profile data before saving.</p>
      </div>

      <div className="px-4 pb-4">
        <FileList files={files} progress={progress} onRemove={onRemove} />
      </div>
    </section>
  )
}

function PreviewCard({ item }) {
  if (!item.success) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4">
        <div className="flex gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
          <div>
            <p className="font-semibold text-red-800">{item.filename}</p>
            <p className="text-sm text-red-700 mt-1">{item.error || 'Extraction failed'}</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 transition-colors hover:border-slate-300">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-slate-400 truncate">{item.filename}</p>
          <h3 className="font-semibold text-slate-900 text-lg">{item.name || 'Unnamed trainer'}</h3>
        </div>
        <span className={clsx('px-2.5 py-1 rounded-full border text-xs font-semibold whitespace-nowrap', categoryClass(item.technology_category))}>
          {item.technology_category || 'Multi-Skillset'}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm text-slate-700">
        {item.email && <span className="flex items-center gap-2 font-semibold text-black"><Mail className="w-4 h-4 text-black" />{item.email}</span>}
        {item.phone && <span className="flex items-center gap-2"><Phone className="w-4 h-4 text-slate-400" />{item.phone}</span>}
        <span>{item.experience_years || 0} yrs experience</span>
        <span className="flex items-center gap-1"><MapPin className="w-4 h-4 text-slate-400" />{item.location || 'Location not found'}</span>
      </div>

      {item.skills?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {item.skills.slice(0, 10).map(skill => (
            <span key={skill} className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-xs">{skill}</span>
          ))}
          {item.skills.length > 10 && <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 text-xs">+{item.skills.length - 10}</span>}
        </div>
      )}

      {item.summary && <p className="mt-3 text-sm text-slate-600 leading-relaxed">{item.summary}</p>}
      {item.extraction_source === 'local_fallback' && (
        <div className="mt-3 flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          <span>AI extraction was unavailable, so a local preview was generated. Please review before saving.</span>
        </div>
      )}
      <div className="mt-4 flex items-center gap-2 border-t border-slate-100 pt-3">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.round((item.confidence_score || 0) * 100)}%` }} />
        </div>
        <span className="text-xs font-semibold text-slate-500">{Math.round((item.confidence_score || 0) * 100)}%</span>
      </div>
    </div>
  )
}

function DomainDatabase({ summary, loading, deletingEmail, onRefresh, onSelectDomain, onDeleteTrainer }) {
  const domains = summary?.domains || []

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-col gap-3 border-b border-slate-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-100">
            <Database className="h-5 w-5 text-emerald-600" />
          </div>
          <div>
            <h2 className="section-title">Uploaded Resume Database</h2>
            <p className="text-xs text-slate-500">
              Domain-wise saved trainers and uploaded resume records.
            </p>
          </div>
        </div>
        <button onClick={onRefresh} disabled={loading} className="btn-secondary justify-center">
          <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      <div className="p-4">
      {loading ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="h-32 animate-pulse rounded-xl border border-slate-100 bg-slate-50" />
          ))}
        </div>
      ) : domains.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 p-8 text-center text-sm text-slate-400">
          No uploaded resume database records yet.
        </div>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-600">
              {summary.total_domains || 0} domains
            </span>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">
              {summary.total_trainers || 0} trainers
            </span>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">
              {summary.total_uploads || 0} uploads
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {domains.map(domain => {
              const sampleItems = [
                ...(domain.trainers || []).map(item => ({ ...item, sampleType: 'trainer' })),
                ...(domain.uploads || []).map(item => ({ ...item, sampleType: 'upload' })),
              ].slice(0, 5)
              return (
                <div key={domain.domain} className="rounded-lg border border-slate-200 bg-slate-50 p-3 transition-all hover:border-blue-200 hover:bg-white hover:shadow-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-900">{domain.domain}</p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {domain.trainers_count} trainers · {domain.uploads_count} uploaded resumes
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => onSelectDomain(domain.domain)}
                      className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 ring-1 ring-slate-200 hover:bg-slate-200"
                    >
                      Review Delete
                    </button>
                  </div>
                  {sampleItems.length > 0 && (
                    <div className="mt-3 space-y-1.5">
                      {sampleItems.map((item, index) => (
                        <div key={`${item.sampleType}-${item.trainer_id || item.upload_id || item.email || item.filename || index}`} className="rounded-lg bg-white px-3 py-2">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2 text-xs">
                                <span className="truncate font-semibold text-slate-700">
                                  {item.name || item.filename || 'Unnamed resume'}
                                </span>
                                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase text-slate-500">
                                  {item.type || item.sampleType}
                                </span>
                              </div>
                              <p className="mt-0.5 truncate text-[11px] font-semibold text-black">
                                {item.email || item.filename || item.trainer_id || item.upload_id}
                              </p>
                            </div>
                            {item.sampleType === 'trainer' && item.email && (
                              <button
                                type="button"
                                title={`Delete ${item.name || item.email}`}
                                aria-label={`Delete ${item.name || item.email}`}
                                onClick={() => onDeleteTrainer(item)}
                                disabled={deletingEmail === item.email}
                                className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-wait disabled:opacity-70"
                              >
                                {deletingEmail === item.email ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Trash2 className="h-4 w-4" />
                                )}
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
      </div>
    </section>
  )
}

export default function UploadPage() {
  const [resumeFiles, setResumeFiles] = useState([])
  const [zipFiles, setZipFiles] = useState([])
  const [progress, setProgress] = useState({})
  const [preview, setPreview] = useState(null)
  const [saveSummary, setSaveSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [cleanupDomain, setCleanupDomain] = useState('')
  const [cleanupPreview, setCleanupPreview] = useState(null)
  const [cleanupLoading, setCleanupLoading] = useState(false)
  const [cleanupDeleting, setCleanupDeleting] = useState(false)
  const [cleanupIncludeLogs, setCleanupIncludeLogs] = useState(false)
  const [domainSummary, setDomainSummary] = useState(null)
  const [domainSummaryLoading, setDomainSummaryLoading] = useState(false)
  const [deletingResumeEmail, setDeletingResumeEmail] = useState('')
  const cleanupSectionRef = useRef(null)

  const allFiles = useMemo(() => [...resumeFiles, ...zipFiles], [resumeFiles, zipFiles])
  const successfulPreviewCount = preview?.results?.filter(item => item.success).length || 0
  const previewUploadIds = useMemo(
    () => preview?.results?.filter(item => item.success && item.upload_id).map(item => item.upload_id) || [],
    [preview]
  )

  const addUniqueFiles = (current, incoming) => {
    const seen = new Set(current.map(file => `${file.name}-${file.size}`))
    return [...current, ...incoming.filter(file => !seen.has(`${file.name}-${file.size}`))]
  }

  const onDropResumes = useCallback(files => {
    setResumeFiles(current => addUniqueFiles(current, files))
    setPreview(null)
    setSaveSummary(null)
  }, [])

  const onDropZip = useCallback(files => {
    setZipFiles(current => addUniqueFiles(current, files))
    setPreview(null)
    setSaveSummary(null)
  }, [])

  const removeFile = file => {
    setResumeFiles(current => current.filter(item => item !== file))
    setZipFiles(current => current.filter(item => item !== file))
    setPreview(null)
    setSaveSummary(null)
  }

  const setAllProgress = percent => {
    setProgress(Object.fromEntries(allFiles.map(file => [file.name, percent])))
  }

  const loadDomainSummary = useCallback(async () => {
    setDomainSummaryLoading(true)
    try {
      const res = await getResumeDomainSummary()
      setDomainSummary(res.data)
    } catch (e) {
      toast.error(e.message || 'Could not load uploaded resume database')
    } finally {
      setDomainSummaryLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDomainSummary()
  }, [loadDomainSummary])

  const handleUpload = async confirm => {
    if (!allFiles.length) {
      toast.error('Select PDF, DOCX, or ZIP files first')
      return
    }

    confirm ? setSaving(true) : setLoading(true)
    setSaveSummary(null)
    setAllProgress(0)

    try {
      if (confirm && previewUploadIds.length) {
        setAllProgress(35)
        const res = await confirmResumePreviews(previewUploadIds)
        setSaveSummary(res.data)
        setAllProgress(100)
        toast.success(`${res.data.saved_count || 0} trainer profiles saved`)
        loadDomainSummary()
        return
      }

      const res = await uploadResumes(allFiles, confirm, event => {
        const percent = event.total ? Math.round((event.loaded * 100) / event.total) : 0
        setAllProgress(percent)
      })
      if (confirm) {
        setSaveSummary(res.data)
        toast.success(`${res.data.saved_count || 0} trainer profiles saved`)
        loadDomainSummary()
      } else {
        setPreview(res.data)
        toast.success(`${res.data.success_count || 0} resume previews extracted`)
      }
      setAllProgress(100)
    } catch (e) {
      toast.error(e.message)
    } finally {
      confirm ? setSaving(false) : setLoading(false)
    }
  }

  const previewCleanupForDomain = async (domainValue, scrollToPanel = false) => {
    const domain = domainValue.trim()
    if (domain.length < 2) {
      toast.error('Enter a domain or technology, for example Data Science or Python')
      return
    }
    setCleanupDomain(domain)
    setCleanupLoading(true)
    try {
      if (scrollToPanel) {
        cleanupSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      const res = await previewResumeDataByDomain(domain)
      setCleanupPreview(res.data)
      const total = (res.data.counts?.trainers || 0) + (res.data.counts?.resume_uploads || 0)
      toast.success(total ? `${domain} resume data ready to review before delete` : 'No resume data found for this domain')
    } catch (e) {
      toast.error(e.message)
      setCleanupPreview(null)
    } finally {
      setCleanupLoading(false)
    }
  }

  const previewCleanup = () => previewCleanupForDomain(cleanupDomain)

  const deleteCleanup = async () => {
    if (!cleanupPreview?.domain || cleanupDeleting) return
    const counts = cleanupPreview.counts || {}
    const total = (counts.trainers || 0) + (counts.resume_uploads || 0)
    if (!total) {
      toast.error('No matching trainer or resume upload to delete')
      return
    }
    if (!globalThis.confirm(`Delete uploaded resume database records for "${cleanupPreview.domain}"?`)) return
    setCleanupDeleting(true)
    try {
      const res = await deleteResumeDataByDomain(cleanupPreview.domain, cleanupIncludeLogs)
      const deleted = res.data.deleted || {}
      toast.success(`Deleted ${deleted.trainers || 0} trainer and ${deleted.resume_uploads || 0} resume upload record(s)`)
      setCleanupPreview(null)
      setCleanupDomain('')
      loadDomainSummary()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setCleanupDeleting(false)
    }
  }

  const deleteTrainerResume = async trainer => {
    const email = trainer.email || ''
    if (!email || deletingResumeEmail) return
    const label = trainer.name || email
    if (!globalThis.confirm(`Delete resume record for "${label}"?`)) return

    setDeletingResumeEmail(email)
    try {
      await deleteResumeDataByEmail(email)
      toast.success(`${label} deleted`)
      loadDomainSummary()
      if (cleanupPreview?.trainers?.some(item => item.email === email)) {
        previewCleanupForDomain(cleanupPreview.domain)
      }
    } catch (e) {
      toast.error(e.message || 'Could not delete resume record')
    } finally {
      setDeletingResumeEmail('')
    }
  }

  return (
    <div className="-m-4 min-h-full space-y-5 bg-gradient-to-br from-blue-500 via-blue-400 to-blue-300 p-4 animate-fade-in sm:-m-6 sm:p-6">
      <div className="rounded-xl border border-white/40 bg-white/25 p-5 text-white shadow-lg backdrop-blur-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Upload Trainer Resumes</h1>
          <p className="mt-2 max-w-2xl text-sm font-medium text-white">Upload resume files, review extracted trainer profiles, and save only the records you want.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-bold text-blue-900">
          <span className="rounded-lg border border-white/60 bg-white/80 px-2.5 py-1">{allFiles.length} queued</span>
          <span className="rounded-lg border border-white/60 bg-white/80 px-2.5 py-1">{successfulPreviewCount} ready</span>
          <span className="rounded-lg border border-white/60 bg-white/80 px-2.5 py-1">{domainSummary?.total_trainers || 0} saved trainers</span>
        </div>
        </div>
      </div>

      <section ref={cleanupSectionRef} className="rounded-lg border border-slate-200 bg-slate-50/70 p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-100">
                <Trash2 className="h-4 w-4 text-slate-500" />
              </div>
              <div>
                <h2 className="font-semibold text-slate-900">Manage Resume Database</h2>
                <p className="text-xs text-slate-500">Remove old uploaded trainer profiles by domain or technology, like Data Science, Python, AWS.</p>
              </div>
            </div>
          </div>
          <div className="w-full lg:max-w-xl">
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="relative flex-1">
                <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-black" />
                <input
                  type="text"
                  value={cleanupDomain}
                  onChange={e => { setCleanupDomain(e.target.value); setCleanupPreview(null) }}
                  onKeyDown={e => { if (e.key === 'Enter') previewCleanup() }}
                  placeholder="Data Science / Python / AWS"
                  className="w-full rounded-md border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm text-slate-900 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-500/10"
                />
              </div>
              <button onClick={previewCleanup} disabled={cleanupLoading || cleanupDeleting} className="inline-flex min-h-[38px] items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50">
                {cleanupLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}
                Check
              </button>
            </div>

            {cleanupPreview && (
              <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/90 p-3">
                <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
                  <div><p className="text-slate-400">Trainers</p><p className="font-bold text-slate-900">{cleanupPreview.counts?.trainers || 0}</p></div>
                  <div><p className="text-slate-400">Uploads</p><p className="font-bold text-slate-900">{cleanupPreview.counts?.resume_uploads || 0}</p></div>
                  <div><p className="text-slate-400">Shortlists</p><p className="font-bold text-slate-900">{cleanupPreview.counts?.shortlists_with_trainer || 0}</p></div>
                  <div><p className="text-slate-400">Emails</p><p className="font-bold text-slate-900">{cleanupPreview.counts?.email_logs || 0}</p></div>
                  <div><p className="text-slate-400">Threads</p><p className="font-bold text-slate-900">{cleanupPreview.counts?.conversations || 0}</p></div>
                </div>
                {cleanupPreview.trainers?.length > 0 && (
                  <div className="mt-3 space-y-1">
                    {cleanupPreview.trainers.map(trainer => (
                      <div key={trainer.trainer_id} className="flex items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 text-xs">
                        <span className="font-semibold text-slate-700">{trainer.name || 'Unnamed trainer'}</span>
                        <span className="text-slate-400">{trainer.trainer_id}</span>
                      </div>
                    ))}
                  </div>
                )}
                <label className="mt-3 flex items-start gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={cleanupIncludeLogs}
                    onChange={e => setCleanupIncludeLogs(e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-slate-300"
                  />
                  Also delete related email logs and conversation threads for this trainer.
                </label>
                <button onClick={deleteCleanup} disabled={cleanupDeleting} className="mt-3 inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-200 disabled:opacity-50">
                  {cleanupDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  Delete Domain Data
                </button>
              </div>
            )}
          </div>
        </div>
      </section>

      <div className="rounded-xl border border-blue-100 bg-white p-4 shadow-lg">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <span className="mr-auto text-sm font-semibold text-slate-700">{allFiles.length ? `${allFiles.length} file${allFiles.length === 1 ? '' : 's'} selected` : 'Add files to enable extraction'}</span>
          <button onClick={() => handleUpload(false)} disabled={loading || saving || !allFiles.length} className="inline-flex min-h-[38px] items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
            Extract Preview
          </button>
          <button
            onClick={() => handleUpload(true)}
            disabled={saving || loading || !successfulPreviewCount}
            className="inline-flex min-h-[38px] items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
            Confirm and Save
          </button>
          {!!allFiles.length && (
            <button
              onClick={() => { setResumeFiles([]); setZipFiles([]); setPreview(null); setSaveSummary(null); setProgress({}) }}
              className="inline-flex min-h-[38px] items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-bold text-blue-700 transition hover:bg-blue-100"
            >
              <Trash2 className="w-4 h-4" /> Clear
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <DropArea
          title="Resume Files"
          hint="PDF and DOCX files only"
          icon={FileText}
          accept={{
            'application/pdf': ['.pdf'],
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
          }}
          files={resumeFiles}
          progress={progress}
          onDrop={onDropResumes}
          onRemove={removeFile}
        />
        <DropArea
          title="Bulk Upload"
          hint="ZIP files containing PDF or DOCX resumes"
          icon={Archive}
          accept={{
            'application/zip': ['.zip'],
            'application/x-zip-compressed': ['.zip'],
          }}
          files={zipFiles}
          progress={progress}
          onDrop={onDropZip}
          onRemove={removeFile}
        />
        </div>
      </div>

      <DomainDatabase
        summary={domainSummary}
        loading={domainSummaryLoading}
        deletingEmail={deletingResumeEmail}
        onRefresh={loadDomainSummary}
        onSelectDomain={(domain) => previewCleanupForDomain(domain, true)}
        onDeleteTrainer={deleteTrainerResume}
      />

      {preview && (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3 flex-wrap rounded-lg border border-slate-200 bg-white p-4">
            <div>
              <h2 className="section-title">Extracted Preview</h2>
            <p className="text-sm text-slate-500">{preview.success_count} success · {preview.error_count} errors</p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">Review before save</span>
          </div>
          {!!preview.archive_resume_count && (
            <p className="text-xs text-slate-500">
              Found {preview.archive_resume_count} resume file{preview.archive_resume_count === 1 ? '' : 's'} inside {preview.archive_count || 1} ZIP archive{preview.archive_count === 1 ? '' : 's'}.
            </p>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {preview.results.map((item, index) => <PreviewCard key={`${item.filename}-${index}`} item={item} />)}
          </div>
        </section>
      )}

      {saveSummary && (
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 text-slate-700 mt-0.5" />
            <div>
              <h2 className="font-semibold text-slate-900">Save complete</h2>
              <p className="text-sm text-slate-600 mt-1">
                {saveSummary.saved_count} saved · {saveSummary.inserted} inserted · {saveSummary.updated} updated · {saveSummary.error_count} errors
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
