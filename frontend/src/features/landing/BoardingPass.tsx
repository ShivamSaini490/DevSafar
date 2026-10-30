import { motion } from 'framer-motion'
import { buildTicketFields } from './content.ts'
import type { TripRoute } from './geo.ts'
import { useTilt } from './motion/pointer.ts'

export function BoardingPass({ trip }: { trip: TripRoute }) {
  const tilt = useTilt(6)

  return (
    <motion.div {...tilt} className="relative z-10 text-ink-soft [--tear:68%]">
      {/* The notched mask sits on its own layer, so fields can fly in from outside the card. */}
      <div aria-hidden="true" className="ticket-notch absolute inset-0 bg-white shadow-2xl shadow-ink/15" style={{ borderRadius: 24 }} />

      <div className="relative grid grid-cols-[68fr_32fr]">
        <div className="p-6 sm:p-8">
          <div className="flex items-center justify-between">
            <p className="eyebrow text-teal">DevSafar boarding pass</p>
            <p className="eyebrow text-muted">Sample</p>
          </div>

          <dl className="mt-7 grid grid-cols-2 gap-x-6 gap-y-5">
            {buildTicketFields(trip).map((field, index) => (
              <div key={field.label}>
                <dt className="eyebrow !text-[10px] text-muted">{field.label}</dt>
                <dd data-field={index} className="mt-1 inline-block font-display text-[clamp(1rem,1.6vw,1.35rem)] font-bold leading-tight">
                  {field.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="relative flex flex-col justify-between border-l-2 border-dashed border-line p-5 sm:p-6">
          <div>
            <p className="eyebrow !text-[10px] text-muted">Checked by</p>
            <p className="mt-1 font-mono text-sm font-medium">Python, not AI</p>
            <p className="mt-3 text-xs leading-snug text-muted">Dates, budget and the deadline are calculated in code.</p>
          </div>
          <div className="barcode mt-5 h-12 w-full text-ink-soft" aria-hidden="true" />
          <p className="ticket-stamp absolute -right-2 top-1/2 rotate-[-14deg] rounded-md border-2 border-chart-1 bg-white/90 px-2 py-1 font-mono text-xs font-medium tracking-wider text-chart-1">
            UNDERSTOOD
          </p>
        </div>
      </div>
    </motion.div>
  )
}
