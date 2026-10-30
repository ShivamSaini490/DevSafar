import { motion } from 'framer-motion'
import { PROMPT_CHIPS } from '../prompts.ts'

export function ChatWelcome({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
      className="m-auto w-full text-center"
    >
      <h1 className="font-display text-[clamp(2rem,4vw,3rem)] font-bold tracking-tight text-ink-soft">Where do you want to go?</h1>
      <p className="mt-2 text-lg text-muted">Tell me your destination, dates and budget.</p>

      <div className="mt-8 grid gap-3 sm:grid-cols-3">
        {PROMPT_CHIPS.map((chip) => (
          <button
            key={chip.label}
            type="button"
            onClick={() => onPick(chip.prompt)}
            className="rounded-xl border border-line bg-paper px-4 py-3.5 text-left text-sm font-medium text-ink-soft transition-colors hover:border-teal"
          >
            {chip.label}
          </button>
        ))}
      </div>
    </motion.div>
  )
}
