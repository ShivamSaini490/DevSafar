import { motion } from 'framer-motion'
import { useState } from 'react'
import { SAMPLE_BUDGET } from './content.ts'

const TOTAL = SAMPLE_BUDGET.reduce((sum, item) => sum + item.amount, 0)
const GAP = 0.8

const rupees = (amount: number) => `₹${amount.toLocaleString('en-IN')}`

const SEGMENTS = SAMPLE_BUDGET.reduce<(typeof SAMPLE_BUDGET[number] & { share: number; start: number })[]>((segments, item) => {
  const previous = segments.at(-1)
  const start = previous ? previous.start + previous.share : 0
  return [...segments, { ...item, share: (item.amount / TOTAL) * 100, start }]
}, [])

export function BudgetDonut() {
  const [activeName, setActiveName] = useState<string | null>(null)
  const active = SAMPLE_BUDGET.find((item) => item.name === activeName)

  return (
    <div className="grid items-center gap-6 sm:grid-cols-[minmax(0,15rem)_1fr]">
      <div className="relative mx-auto w-full max-w-60">
        <svg viewBox="0 0 240 240" className="-rotate-90" role="img" aria-label={`Sample budget of ${rupees(TOTAL)} by category`}>
          {SEGMENTS.map((segment, index) => (
            <motion.circle
              key={segment.name}
              cx="120"
              cy="120"
              r="92"
              fill="none"
              stroke={segment.color}
              strokeWidth={activeName === segment.name ? 34 : 28}
              pathLength={100}
              strokeDashoffset={-segment.start}
              initial={{ strokeDasharray: '0 100' }}
              whileInView={{ strokeDasharray: `${segment.share - GAP} ${100 - segment.share + GAP}` }}
              viewport={{ once: true }}
              transition={{ duration: 0.9, delay: index * 0.08, ease: 'easeOut' }}
              className="cursor-pointer transition-[stroke-width]"
              onPointerEnter={() => setActiveName(segment.name)}
              onPointerLeave={() => setActiveName(null)}
            />
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="font-mono text-[11px] uppercase tracking-wider text-muted">{active?.name ?? 'Sample total'}</span>
          <span className="font-display text-2xl font-bold text-ink-soft">{rupees(active?.amount ?? TOTAL)}</span>
        </div>
      </div>

      <ul className="flex flex-col gap-1">
        {SAMPLE_BUDGET.map((item) => (
          <li
            key={item.name}
            onPointerEnter={() => setActiveName(item.name)}
            onPointerLeave={() => setActiveName(null)}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-ink-soft transition-colors ${
              activeName === item.name ? 'bg-paper' : ''
            }`}
          >
            <span className="size-3 rounded-[4px]" style={{ background: item.color }} aria-hidden="true" />
            {item.name}
            <span className="ml-auto font-mono">{rupees(item.amount)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
