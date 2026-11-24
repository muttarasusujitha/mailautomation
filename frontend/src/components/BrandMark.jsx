import clsx from 'clsx'

const SIZES = {
  sm: { wrap: 'h-8 w-8 rounded-lg', textSize: 'text-[11px]', title: 'text-sm', sub: 'text-[10px]' },
  md: { wrap: 'h-9 w-9 rounded-[9px]', textSize: 'text-xs', title: 'text-[15px]', sub: 'text-[11px]' },
  lg: { wrap: 'h-11 w-11 rounded-xl', textSize: 'text-sm', title: 'text-lg', sub: 'text-xs' },
}

export default function BrandMark({
  size = 'md',
  theme = 'light',
  subtitle = 'Clahan Technologies',
  className = '',
  onClick,
}) {
  const cfg = SIZES[size] || SIZES.md
  const isDark = theme === 'dark'
  const Wrapper = onClick ? 'button' : 'div'

  return (
    <Wrapper
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      className={clsx(
        'flex items-center gap-3 text-left select-none',
        onClick && 'cursor-pointer border-0 bg-transparent p-0 transition-opacity hover:opacity-80',
        className
      )}
    >
      {/* Logo mark — blue square with TS monogram */}
      <span
        className={clsx(
          'flex shrink-0 items-center justify-center font-bold leading-none',
          cfg.wrap
        )}
        style={{
          background: isDark
            ? 'linear-gradient(135deg,#1d4ed8,#2563eb)'
            : 'linear-gradient(135deg,#2563eb,#3b82f6)',
          boxShadow: isDark
            ? '0 0 0 1px rgba(255,255,255,0.12),0 4px 12px -2px rgba(37,99,235,0.5)'
            : '0 2px 8px -2px rgba(37,99,235,0.4)',
          color: 'white',
        }}
      >
        <span className={clsx('tracking-tight', cfg.textSize)} style={{ fontFamily: "'Plus Jakarta Sans',sans-serif", fontWeight: 800 }}>
          TS
        </span>
      </span>

      {/* Text */}
      <span className="min-w-0 leading-none">
        <span
          className={clsx('block truncate font-bold tracking-tight leading-snug', cfg.title)}
          style={{
            fontFamily: "'Plus Jakarta Sans',sans-serif",
            fontWeight: 800,
            letterSpacing: '-0.03em',
            color: isDark ? '#ffffff' : '#0f172a',
          }}
        >
          TrainerSync
        </span>
        <span
          className={clsx('mt-0.5 block truncate font-medium leading-tight', cfg.sub)}
          style={{ color: isDark ? 'rgba(255,255,255,0.55)' : '#64748b' }}
        >
          {subtitle}
        </span>
      </span>
    </Wrapper>
  )
}
