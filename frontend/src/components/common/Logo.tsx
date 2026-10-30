import { Link } from 'react-router-dom'

export function Logo({ className = '' }: { className?: string }) {
  return (
    <Link to="/" className={`inline-flex items-center gap-2.5 font-display text-xl font-bold tracking-tight ${className}`}>
      <svg viewBox="0 0 32 32" className="size-7" fill="none" aria-hidden="true">
        <rect x="0.5" y="0.5" width="31" height="31" rx="9" fill="#14293d" stroke="#3d5468" />
        <path d="M9 23C9 14 23 18 23 9" stroke="#f3ac55" strokeWidth="2.6" strokeLinecap="round" />
        <circle cx="9" cy="23" r="3" fill="#2cc7bd" />
        <circle cx="23" cy="9" r="3" fill="#2cc7bd" />
      </svg>
      DevSafar
    </Link>
  )
}
