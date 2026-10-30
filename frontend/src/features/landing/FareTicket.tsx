import { motion } from 'framer-motion'
import type { PRICE_STATES } from './content.ts'
import { useTilt } from './motion/pointer.ts'
import { PriceTag } from './PriceTag.tsx'

interface FareTicketProps {
  ticket: (typeof PRICE_STATES)[number]
  /** Resting angle in degrees, so a row of tickets looks laid out by hand. */
  angle: number
}

export function FareTicket({ ticket, angle }: FareTicketProps) {
  const tilt = useTilt(5)
  const isUnknown = ticket.type === 'unknown'

  return (
    <motion.article
      {...tilt}
      animate={{ rotate: angle }}
      whileHover={{ rotate: 0, y: -8 }}
      transition={{ type: 'spring', stiffness: 220, damping: 20 }}
      className="relative h-full text-ink-soft drop-shadow-[0_18px_24px_rgb(0_0_0/0.45)] [--tear:70%]"
    >
      {/* Same trick as the boarding pass: the notched mask lives on its own layer. */}
      <div aria-hidden="true" className="ticket-notch absolute inset-0 bg-ticket" style={{ borderRadius: 18 }} />

      <div className="relative grid h-full grid-cols-[70fr_30fr]">
        <div className="flex flex-col p-5">
          <div className="flex items-center justify-between gap-2">
            <p className="eyebrow !text-[10px] text-muted">DevSafar fare</p>
            <p className="eyebrow !text-[10px] text-muted">Sample</p>
          </div>

          <div className="mt-4">
            <PriceTag type={ticket.type} />
          </div>

          <h3 className="mt-4 font-mono text-sm font-medium">{ticket.item}</h3>
          <p className={`font-display font-extrabold leading-tight tracking-tight ${isUnknown ? 'text-3xl text-muted' : 'text-4xl'}`}>{ticket.amount}</p>

          <p className="mt-3 text-sm leading-snug text-muted">{ticket.body}</p>
        </div>

        <div className="flex flex-col border-l-2 border-dashed border-ink-soft/20 p-4">
          <p className="eyebrow !text-[9px] !tracking-[0.1em] text-muted">Source</p>
          <p className="mt-0.5 text-xs font-semibold leading-tight">{ticket.source}</p>
          <p className="eyebrow mt-3 !text-[9px] !tracking-[0.1em] text-muted">Fetched</p>
          <p className="mt-0.5 text-xs font-semibold leading-tight">Date and time</p>
          <div className={`barcode mt-auto h-12 w-full pt-3 ${isUnknown ? 'opacity-20' : ''}`} aria-hidden="true" />
        </div>
      </div>
    </motion.article>
  )
}
