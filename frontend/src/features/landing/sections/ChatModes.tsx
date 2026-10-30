import { motion } from 'framer-motion'
import { Check } from 'lucide-react'
import { useRef } from 'react'
import { CHAT_MODES } from '../content.ts'
import { MOTION_OK, gsap, useGSAP } from '../motion/gsap.ts'
import { useTilt } from '../motion/pointer.ts'
import { Reveal } from '../motion/Reveal.tsx'

const DAYS = Array.from({ length: 8 }, (_, day) => day)

function ModeCard({ mode }: { mode: (typeof CHAT_MODES)[number] }) {
  const tilt = useTilt(4)

  return (
    <motion.article {...tilt} className="rounded-3xl border border-line bg-white p-7">
      <p className="eyebrow !text-[10px] text-teal">{mode.who}</p>
      <h3 className="mt-2 font-display text-3xl font-bold tracking-tight text-ink-soft">{mode.name}</h3>
      <ul className="mt-5 flex flex-col gap-2.5">
        {mode.points.map((point) => (
          <li key={point} className="flex gap-2.5 text-ink-soft">
            <Check className="mt-0.5 size-5 shrink-0 text-teal" aria-hidden="true" />
            {point}
          </li>
        ))}
      </ul>
    </motion.article>
  )
}

export function ChatModes() {
  const rootRef = useRef<HTMLElement>(null)

  useGSAP(
    () => {
      gsap.matchMedia().add(MOTION_OK, () => {
        const scrollTrigger = { trigger: '.expiry-bar', start: 'top 85%', end: 'top 35%', scrub: 0.6 }
        gsap.fromTo('.expiry-fill', { scaleX: 0 }, { scaleX: 1, ease: 'none', scrollTrigger })
        gsap.fromTo(
          '.expiry-tick',
          { color: '#8ea0b0' },
          { color: '#14293d', stagger: 0.14, ease: 'none', scrollTrigger },
        )
      })
    },
    { scope: rootRef },
  )

  return (
    <section id="chats" ref={rootRef} className="bg-paper px-4 py-20 sm:px-8 lg:py-28">
      <div className="mx-auto max-w-5xl">
        <Reveal>
          <p className="eyebrow text-teal">Your chats</p>
          <h2 className="section-title mt-3 text-ink-soft">Two kinds of chat. No grey areas.</h2>
        </Reveal>

        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {CHAT_MODES.map((mode, index) => (
            <Reveal key={mode.name} delay={index * 0.08}>
              <ModeCard mode={mode} />
            </Reveal>
          ))}
        </div>

        <Reveal className="mt-14">
          <h3 className="font-display text-2xl font-bold tracking-tight text-ink-soft">Seven days from creation. Not from your last message.</h3>
          <div className="expiry-bar mt-6">
            <div className="h-2 overflow-hidden rounded-full bg-line">
              <div className="expiry-fill h-full origin-left rounded-full bg-teal" />
            </div>
            <ol className="mt-2.5 flex justify-between font-mono text-xs">
              {DAYS.map((day) => (
                <li key={day} className="expiry-tick text-ink-soft">
                  {day === 0 ? 'Created' : day === 7 ? 'Expired' : `Day ${day}`}
                </li>
              ))}
            </ol>
          </div>
          <p className="mt-5 text-muted">
            After day seven, access is denied and a cleanup job removes the chat, its itinerary versions and agent checkpoints.
            Closing a browser can't guarantee instant server deletion, which is why temporary server data expires on a short timer.
          </p>
        </Reveal>
      </div>
    </section>
  )
}
