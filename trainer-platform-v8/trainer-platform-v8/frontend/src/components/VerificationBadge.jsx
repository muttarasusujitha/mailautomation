import { ShieldCheck, ShieldAlert, Shield, FileText, User } from 'lucide-react'
import clsx from 'clsx'

const TIER_CONFIG = {
  resume_verified: {
    label: 'Resume verified',
    icon: ShieldCheck,
    classes: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    dot: 'bg-emerald-500',
    weight: 1,
  },
  ai_extracted: {
    label: 'AI verified',
    icon: ShieldCheck,
    classes: 'bg-blue-50 text-blue-700 border-blue-200',
    dot: 'bg-blue-500',
    weight: 0.85,
  },
  local_fallback: {
    label: 'Extracted',
    icon: Shield,
    classes: 'bg-violet-50 text-violet-700 border-violet-200',
    dot: 'bg-violet-400',
    weight: 0.65,
  },
  linkedin_signal: {
    label: 'Unverified',
    icon: ShieldAlert,
    classes: 'bg-amber-50 text-amber-700 border-amber-200',
    dot: 'bg-amber-400',
    weight: 0.3,
  },
  manual_entry: {
    label: 'Manual entry',
    icon: User,
    classes: 'bg-teal-50 text-teal-700 border-teal-200',
    dot: 'bg-teal-500',
    weight: 0.90,
  },
  unknown: {
    label: 'Unknown',
    icon: Shield,
    classes: 'bg-slate-50 text-slate-500 border-slate-200',
    dot: 'bg-slate-300',
    weight: 0.5,
  },
}

function getTierConfig(tier) {
  return TIER_CONFIG[tier] || TIER_CONFIG.unknown
}

export function VerificationBadge({ tier, showLabel = true, size = 'sm' }) {
  const config = getTierConfig(tier)
  const Icon = config.icon
  const textSize = size === 'xs' ? 'text-[11px]' : 'text-xs'

  return (
    <span className={clsx(
      'inline-flex items-center gap-1 rounded-lg border px-2 py-0.5 font-semibold',
      textSize,
      config.classes,
    )}>
      <Icon className="h-3 w-3" aria-hidden="true" />
      {showLabel && config.label}
    </span>
  )
}

export function ContactTrustRow({ label, value, tier }) {
  if (!value) return null

  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="min-w-[72px] text-xs font-medium text-slate-500">{label}</span>
      <span className="flex-1 truncate text-sm text-slate-800">{value}</span>
      <VerificationBadge tier={tier} />
    </div>
  )
}

export function TrustSummaryCard({ trainer, onRequestResume }) {
  const trust = trainer?.contact_trust || {}
  const summary = trainer?.verification_summary || {}
  const tier = trainer?.verification_tier || 'unknown'

  const contactFields = [
    { key: 'name', label: 'Name', value: trainer?.name },
    { key: 'email', label: 'Email', value: trainer?.email },
    { key: 'phone', label: 'Phone', value: trainer?.phone },
    { key: 'location', label: 'Location', value: trainer?.location },
    { key: 'linkedin', label: 'LinkedIn', value: trainer?.linkedin },
  ]

  const isLinkedInOnly = tier === 'linkedin_signal' || summary?.is_linkedin_only
  const needsResume = summary?.needs_resume_upload

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">Contact Details</h3>
        <VerificationBadge tier={tier} />
      </div>

      {isLinkedInOnly && (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <div className="flex items-start gap-2">
            <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden="true" />
            <span>Contact details found via public LinkedIn search. Upload this trainer's resume to verify.</span>
          </div>
        </div>
      )}

      <div className="divide-y divide-slate-100">
        {contactFields.map(({ key, label, value }) => (
          <ContactTrustRow
            key={key}
            label={label}
            value={value}
            tier={trust[key]?.tier || 'unknown'}
          />
        ))}
      </div>

      {needsResume && onRequestResume && (
        <button
          type="button"
          onClick={onRequestResume}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
        >
          <FileText className="h-3.5 w-3.5" aria-hidden="true" />
          Upload Resume to Verify
        </button>
      )}
    </div>
  )
}

export function TrainerCardTrustPill({ trainer }) {
  const config = getTierConfig(trainer?.verification_tier || 'unknown')

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold',
        config.classes,
      )}
      title={`Contact source: ${config.label}`}
    >
      <span className={clsx('h-1.5 w-1.5 rounded-full', config.dot)} aria-hidden="true" />
      {config.label}
    </span>
  )
}

export function LinkedInLeadVerifyButton({ lead, onVerify, loading }) {
  const tier = lead?.verification_tier || 'linkedin_signal'
  const isLinkedInOnly = tier === 'linkedin_signal'

  if (!isLinkedInOnly) {
    return (
      <span className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
        <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
        Verified
      </span>
    )
  }

  return (
    <button
      type="button"
      onClick={() => onVerify?.(lead)}
      disabled={loading}
      className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700 transition hover:bg-amber-100 disabled:opacity-50"
    >
      <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />
      {loading ? 'Verifying...' : 'Verify'}
    </button>
  )
}

export function TrustLegend() {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 px-4 py-2 text-xs text-slate-500">
      <span className="font-semibold text-slate-700">Contact trust:</span>
      {Object.entries(TIER_CONFIG).map(([key, cfg]) => {
        const Icon = cfg.icon
        return (
          <span key={key} className={clsx('inline-flex items-center gap-1 rounded-lg border px-2 py-0.5 font-semibold', cfg.classes)}>
            <Icon className="h-3 w-3" aria-hidden="true" />
            {cfg.label}
          </span>
        )
      })}
    </div>
  )
}

export function useVerificationSummary(trainer) {
  if (!trainer) return null

  const trust = trainer.contact_trust || {}
  const tier = trainer.verification_tier || 'unknown'
  const config = getTierConfig(tier)

  const verifiedFields = Object.entries(trust)
    .filter(([, t]) => ['resume_verified', 'ai_extracted', 'manual_entry'].includes(t?.tier))
    .map(([key]) => key)

  const unverifiedFields = Object.entries(trust)
    .filter(([, t]) => t?.tier === 'linkedin_signal')
    .map(([key]) => key)

  return {
    tier,
    config,
    verifiedFields,
    unverifiedFields,
    isFullyVerified: verifiedFields.length >= 3,
    isLinkedInOnly: unverifiedFields.length >= 2 && verifiedFields.length === 0,
    needsResume: tier === 'linkedin_signal' || verifiedFields.length < 2,
  }
}
