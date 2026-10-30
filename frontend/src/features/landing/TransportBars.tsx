import { motion } from 'framer-motion'
import { SAMPLE_TRANSPORT } from './content.ts'

const MAX = Math.max(...SAMPLE_TRANSPORT.map((item) => item.amount))

export function TransportBars() {
  return (
    <ul className="flex flex-col gap-3" aria-label="Sample transport estimates">
      {SAMPLE_TRANSPORT.map((item, index) => (
        <li key={item.mode} className="group grid grid-cols-[3.5rem_1fr_4.5rem] items-center gap-3 text-sm text-ink-soft">
          <span>{item.mode}</span>
          <span className="relative h-7">
            <motion.span
              className="block h-full rounded-r-[4px] bg-chart-1 transition-opacity group-hover:opacity-80"
              initial={{ width: 0 }}
              whileInView={{ width: `${(item.amount / MAX) * 100}%` }}
              viewport={{ once: true }}
              transition={{ duration: 0.8, delay: index * 0.08, ease: [0.2, 0.8, 0.2, 1] }}
            />
            <span className="pointer-events-none absolute -top-7 left-0 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
              {item.mode}: sample estimate, not a live fare
            </span>
          </span>
          <span className="text-right font-mono">₹{item.amount.toLocaleString('en-IN')}</span>
        </li>
      ))}
    </ul>
  )
}
