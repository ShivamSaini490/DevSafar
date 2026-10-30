import { motion } from 'framer-motion'
import { useRef } from 'react'
import { AGENT_STEPS, FAILURE_PATHS } from '../content.ts'
import { DESKTOP_MOTION, gsap, useGSAP } from '../motion/gsap.ts'
import { useTilt } from '../motion/pointer.ts'
import { Reveal } from '../motion/Reveal.tsx'

function StepCard({ step, index }: { step: (typeof AGENT_STEPS)[number]; index: number }) {
  const tilt = useTilt(5)

  return (
    <motion.article {...tilt} className="flex w-full shrink-0 flex-col rounded-3xl bg-white p-7 shadow-lg shadow-teal/5 lg:h-[23rem] lg:w-[23rem]">
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-sm text-muted">0{index + 1}</span>
        <span className="eyebrow !text-[10px] text-teal">{step.name} node</span>
      </div>
      <h3 className="mt-8 font-display text-3xl font-bold leading-tight tracking-tight text-ink-soft">{step.title}</h3>
      <p className="mt-3 text-muted">{step.body}</p>
      <p className="mt-auto pt-6 font-mono text-xs text-ink-soft">
        <span className="text-muted">Done by: </span>
        {step.owner}
      </p>
    </motion.article>
  )
}

export function AgentRail() {
  const rootRef = useRef<HTMLDivElement>(null)

  useGSAP(
    () => {
      const media = gsap.matchMedia()

      media.add(DESKTOP_MOTION, () => {
        const track = rootRef.current!.querySelector<HTMLElement>('.rail-track')!
        const distance = () => Math.max(0, track.scrollWidth - window.innerWidth)

        const timeline = gsap.timeline({
          scrollTrigger: {
            trigger: '.rail-pin',
            start: 'top top',
            end: () => `+=${distance()}`,
            pin: true,
            scrub: 0.8,
            invalidateOnRefresh: true,
          },
        })
        timeline
          .to(track, { x: () => -distance(), ease: 'none', duration: 1 }, 0)
          .fromTo('.rail-fill', { scaleX: 0 }, { scaleX: 1, ease: 'none', duration: 1 }, 0)
      })
    },
    { scope: rootRef },
  )

  return (
    <div id="agents" ref={rootRef}>
      <section className="rail-pin flex flex-col justify-center overflow-hidden bg-mint py-20 lg:min-h-svh lg:py-12">
        <div className="mx-auto w-full max-w-7xl px-4 sm:px-8">
          <Reveal>
            <p className="eyebrow text-teal">Five steps</p>
            <h2 className="section-title mt-3 max-w-3xl text-ink-soft">From your sentence to a trip that holds up.</h2>
          </Reveal>
        </div>

        <div className="rail-track mt-10 flex flex-col gap-5 px-4 sm:px-8 lg:w-max lg:flex-row lg:pl-[max(2rem,calc((100vw-80rem)/2+2rem))] lg:pr-24">
          {AGENT_STEPS.map((step, index) => (
            <StepCard key={step.name} step={step} index={index} />
          ))}

          <article className="flex w-full shrink-0 flex-col rounded-3xl bg-ink p-7 text-white lg:h-[23rem] lg:w-[30rem]">
            <p className="eyebrow !text-[10px] text-amber">When it doesn't work out</p>
            <h3 className="mt-4 font-display text-3xl font-bold tracking-tight">A plan can fail. It won't fail quietly.</h3>
            <dl className="mt-5 flex flex-col gap-2.5 text-sm">
              {FAILURE_PATHS.map((path) => (
                <div key={path.when} className="flex flex-col border-t border-white/12 pt-2.5 sm:flex-row sm:justify-between sm:gap-4">
                  <dt className="text-white/60">{path.when}</dt>
                  <dd className="sm:text-right">{path.then}</dd>
                </div>
              ))}
            </dl>
          </article>
        </div>

        <div className="mx-auto mt-10 hidden w-full max-w-7xl px-8 lg:block" aria-hidden="true">
          <div className="h-1 overflow-hidden rounded-full bg-teal/15">
            <div className="rail-fill h-full origin-left rounded-full bg-teal" />
          </div>
        </div>
      </section>
    </div>
  )
}
