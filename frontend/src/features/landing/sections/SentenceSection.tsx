import { useRef } from 'react'
import { BoardingPass } from '../BoardingPass.tsx'
import { buildSentence } from '../content.ts'
import type { TripRoute } from '../geo.ts'
import { DESKTOP_MOTION, gsap, useGSAP } from '../motion/gsap.ts'
import { Reveal } from '../motion/Reveal.tsx'

export function SentenceSection({ trip }: { trip: TripRoute }) {
  const rootRef = useRef<HTMLDivElement>(null)

  useGSAP(
    () => {
      const media = gsap.matchMedia()

      media.add(DESKTOP_MOTION, () => {
        const root = rootRef.current!
        const timeline = gsap.timeline({
          scrollTrigger: {
            trigger: '.sentence-pin',
            start: 'top top',
            end: '+=240%',
            pin: true,
            scrub: 0.7,
            invalidateOnRefresh: true,
          },
        })

        gsap.utils.toArray<HTMLElement>('[data-token]', root).forEach((token, index) => {
          const field = root.querySelector<HTMLElement>(`[data-field="${token.dataset.token}"]`)!
          const start = index * 1.1

          timeline
            .fromTo(
              token,
              { color: '#566a7c', backgroundSize: '0% 3px' },
              { color: '#087f8c', backgroundSize: '100% 3px', duration: 0.5 },
              start,
            )
            .fromTo(field, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.15 }, start + 0.35)
            .from(
              field,
              {
                // The value lifts off the word it was read from and lands in its ticket field.
                x: () => token.getBoundingClientRect().left - field.getBoundingClientRect().left,
                y: () => token.getBoundingClientRect().top - field.getBoundingClientRect().top,
                color: '#087f8c',
                duration: 0.8,
                ease: 'power2.inOut',
              },
              start + 0.35,
            )
        })

        timeline
          .from('.ticket-stamp', { scale: 2.4, autoAlpha: 0, rotate: -34, duration: 0.6, ease: 'back.out(2)' })
          .to({}, { duration: 0.8 })
      })
    },
    { scope: rootRef },
  )

  return (
    <div id="how-it-works" ref={rootRef}>
      <section className="sentence-pin flex items-center overflow-hidden bg-paper px-4 py-20 sm:px-8 lg:min-h-svh lg:py-16">
        <div className="mx-auto grid w-full max-w-7xl items-center gap-10 lg:grid-cols-2 lg:gap-14">
          <div>
            <Reveal>
              <p className="eyebrow text-teal">How it works</p>
              <h2 className="section-title mt-3 text-ink-soft">Say it like you'd tell a friend.</h2>
            </Reveal>
            <p className="mt-7 font-display text-[clamp(1.35rem,2.5vw,2.1rem)] font-medium leading-snug text-muted">
              “
              {buildSentence(trip).map((part) =>
                part.field === undefined ? (
                  <span key={part.text}>{part.text}</span>
                ) : (
                  <span
                    key={part.text}
                    data-token={part.field}
                    className="bg-[linear-gradient(currentColor,currentColor)] bg-[length:100%_3px] bg-left-bottom bg-no-repeat text-teal"
                  >
                    {part.text}
                  </span>
                ),
              )}
              ”
            </p>
          </div>

          <div>
            <BoardingPass trip={trip} />
            <p className="mt-4 text-sm text-muted">
              Illustrative example. A real plan depends on route and schedule evidence, and is never a confirmed offer.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
