import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { uploadTrainers } from '../utils/api'
import toast from 'react-hot-toast'
import { Upload, FileSpreadsheet, CheckCircle, AlertCircle, X, ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import clsx from 'clsx'

export default function UploadPage() {
  const [file, setFile]       = useState(null)
  const [result, setResult]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const navigate = useNavigate()

  const onDrop = useCallback((accepted) => {
    if (accepted[0]) { setFile(accepted[0]); setResult(null); setError(null) }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
               'application/vnd.ms-excel': ['.xls'] },
    maxFiles: 1,
  })

  const handleUpload = async () => {
    if (!file) return
    setLoading(true); setError(null)
    try {
      const res = await uploadTrainers(file)
      setResult(res.data)
      toast.success(`✅ ${res.data.total} trainers loaded!`)
    } catch (e) {
      setError(e.message)
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="page-title">Upload Trainer Database</h1>
        <p className="text-sm text-slate-500 mt-1">Upload your Excel file (.xlsx) — all sheets will be parsed automatically</p>
      </div>

      {/* Format guide */}
      <div className="card p-5">
        <h2 className="font-display font-semibold text-slate-800 mb-3">Expected Excel Columns</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {['Trainers Name','Technologies','Skills','Experience','Certifications',
            'Contact No','Email','Location','Linkedin Profile','Resumes'].map(col => (
            <div key={col} className="flex items-center gap-2 text-sm">
              <div className="w-1.5 h-1.5 rounded-full bg-brand-500 flex-shrink-0" />
              <span className="text-slate-600 font-mono text-xs">{col}</span>
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-400 mt-3">Multiple sheets supported — duplicates are auto-removed</p>
      </div>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={clsx(
          'border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200',
          isDragActive
            ? 'border-brand-500 bg-brand-50'
            : file
            ? 'border-emerald-400 bg-emerald-50'
            : 'border-slate-200 bg-white hover:border-brand-400 hover:bg-slate-25'
        )}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-3">
          {file ? (
            <>
              <div className="w-14 h-14 rounded-2xl bg-emerald-100 flex items-center justify-center">
                <FileSpreadsheet className="w-7 h-7 text-emerald-600" />
              </div>
              <div>
                <p className="font-semibold text-slate-800">{file.name}</p>
                <p className="text-sm text-slate-500">{(file.size / 1024).toFixed(1)} KB</p>
              </div>
              <button
                type="button"
                onClick={e => { e.stopPropagation(); setFile(null); setResult(null) }}
                className="flex items-center gap-1 text-xs text-red-500 hover:text-red-600"
              >
                <X className="w-3.5 h-3.5" /> Remove file
              </button>
            </>
          ) : (
            <>
              <div className={clsx(
                'w-14 h-14 rounded-2xl flex items-center justify-center transition-colors',
                isDragActive ? 'bg-brand-100' : 'bg-slate-100'
              )}>
                <Upload className={clsx('w-7 h-7', isDragActive ? 'text-brand-500' : 'text-slate-400')} />
              </div>
              <div>
                <p className="font-semibold text-slate-700">
                  {isDragActive ? 'Drop your file here' : 'Drag & drop your Excel file'}
                </p>
                <p className="text-sm text-slate-400 mt-1">or <span className="text-brand-500">browse to upload</span></p>
              </div>
              <p className="text-xs text-slate-400">.xlsx or .xls • All sheets will be parsed</p>
            </>
          )}
        </div>
      </div>

      {/* Upload button */}
      {file && !result && (
        <button
          onClick={handleUpload}
          disabled={loading}
          className="btn-primary w-full justify-center py-3 text-base"
        >
          {loading ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Parsing Excel...
            </>
          ) : (
            <>
              <Upload className="w-4 h-4" />
              Upload & Parse Trainers
            </>
          )}
        </button>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 p-4 bg-red-50 border border-red-100 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Success result */}
      {result && (
        <div className="card p-6 border-emerald-100 bg-emerald-50 animate-slide-up">
          <div className="flex items-center gap-3 mb-4">
            <CheckCircle className="w-6 h-6 text-emerald-600" />
            <h3 className="font-display font-semibold text-emerald-800">Upload Successful!</h3>
          </div>
          <div className="grid grid-cols-3 gap-4 mb-5">
            {[
              { label: 'Total Parsed', value: result.total },
              { label: 'Inserted',     value: result.inserted },
              { label: 'Updated',      value: result.updated },
            ].map(s => (
              <div key={s.label} className="bg-white rounded-xl p-3 text-center border border-emerald-100">
                <p className="font-display text-2xl font-bold text-emerald-700">{s.value}</p>
                <p className="text-xs text-slate-500 mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>
          <div className="mb-5">
            <p className="text-sm text-slate-600 mb-2">Sheets parsed:</p>
            <div className="flex flex-wrap gap-2">
              {(result.sheets_parsed || []).map(s => (
                <span key={s} className="badge-blue">{s}</span>
              ))}
            </div>
          </div>
          <button onClick={() => navigate('/requirements')} className="btn-primary w-full justify-center">
            Find Trainers Now
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}
