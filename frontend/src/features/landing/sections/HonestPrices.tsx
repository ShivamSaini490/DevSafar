import { X } from 'lucide-react'
import { useRef } from 'react'
import { PRICE_STATES, WONT_PRETEND } from '../content.ts'
import { FareTicket } from '../FareTicket.tsx'
import { MOTION_OK, SplitText, gsap, useGSAP } from '../motion/gsap.ts'
import { Reveal } from '../motion/Reveal.tsx'

const TICKET_ANGLES = [-1.6, 0.9, -0.7]

export function HonestPrices() {
  const rootRef = useRef<HTMLElement>(null)

  useGSAP(
    () => {
      gsap.matchMedia().add(MOTION_OK, () => {
        const split = SplitText.create('.honest-line', { type: 'words' })
        gsap.fromTo(
          split.words,
          { opacity: 0.18 },
          {
            opacity: 1,
            stagger: 0.1,
            ease: 'none',
            scrollTrigger: { trigger: '.honest-line', start: 'top 80%', end: 'bottom 45%', scrub: 0.5 },
          },
        )
        return () => split.revert()
      })
    },
    { scope: rootRef },
  )

  return (
    <section id="prices" ref={rootRef} className="bg-ink px-4 py-24 text-white sm:px-8 lg:py-32">
      <div className="mx-auto max-w-7xl">
        <p className="eyebrow text-teal-bright">Honest prices</p>
        <p className="honest-line section-title mt-4 max-w-5xl">
          A made-up price is worse than no price. So when we don't know, we say unknown.
        </p>

        <div className="mt-14 grid gap-6 lg:grid-cols-3 lg:gap-5">
          {PRICE_STATES.map((ticket, index) => (
            <Reveal key={ticket.type} delay={index * 0.08} className="h-full">
              <FareTicket ticket={ticket} angle={TICKET_ANGLES[index]} />
            </Reveal>
          ))}
        </div>
        <p className="mt-6 text-sm text-white/55">Sample tickets showing how each price is labelled, not real fares.</p>

        <Reveal className="mt-16">
          <h3 className="font-display text-3xl font-bold tracking-tight">What DevSafar won't pretend</h3>
          <ul className="mt-6 grid gap-x-10 gap-y-4 md:grid-cols-2">
            {WONT_PRETEND.map((line) => (
              <li key={line} className="flex gap-3 border-t border-white/12 pt-4 text-lg text-white/85">
                <X className="mt-1 size-5 shrink-0 text-amber" aria-hidden="true" />
                {line}
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </section>
  )
}
