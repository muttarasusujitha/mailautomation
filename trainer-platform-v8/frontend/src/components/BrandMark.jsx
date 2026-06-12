import { Zap } from 'lucide-react'
import clsx from 'clsx'

const SIZES = {
  sm: {
    mark: 'h-8 w-8 rounded-lg',
    icon: 'h-4 w-4',
    title: 'text-sm',
    subtitle: 'text-[10px]',
  },
  md: {
    mark: 'h-9 w-9 rounded-lg',
    icon: 'h-5 w-5',
    title: 'text-base',
    subtitle: 'text-xs',
  },
  lg: {
    mark: 'h-11 w-11 rounded-lg',
    icon: 'h-5 w-5',
    title: 'text-xl',
    subtitle: 'text-xs',
  },
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
        'flex items-center gap-3 text-left',
        onClick && 'cursor-pointer border-0 bg-transparent p-0 font-inherit transition hover:opacity-85',
        className
      )}
    >
      <span className={clsx(
        'flex shrink-0 items-center justify-center bg-blue-600 text-white shadow-sm shadow-blue-600/25',
        cfg.mark,
        isDark && 'ring-1 ring-white/15'
      )}>
        <Zap className={cfg.icon} />
      </span>
      <span className="min-w-0">
        <span className={clsx('block truncate font-bold leading-none', cfg.title, isDark ? 'text-white' : 'text-slate-950')}>
          TrainerSync
        </span>
        <span className={clsx('mt-0.5 block truncate font-medium', cfg.subtitle, isDark ? 'text-white/70' : 'text-slate-500')}>
          {subtitle}
        </span>
      </span>
    </Wrapper>
  )
}
