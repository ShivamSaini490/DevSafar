import { motion, useAnimationFrame, useMotionValue, useScroll, useSpring, useTransform, useVelocity, wrap } from 'framer-motion'
import { useRef } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../../../components/common/Logo.tsx'
import { useAuth } from '../../../hooks/useAuth.ts'
import { CHAT_ROUTE } from '../../chat/prompts.ts'
import { MARQUEE_STOPS, NAV_LINKS } from '../content.ts'
import { Magnetic } from '../motion/Magnetic.tsx'
import { Reveal } from '../motion/Reveal.tsx'
import { scrollToSection } from '../motion/scrollToSection.ts'

/** Percent of the band per second. The band grows with the stop list, so a longer list needs a lower value. */
const BASE_SPEED = 0.9

function ScrollMarquee() {
  const offset = useMotionValue(0)
  const { scrollY } = useScroll()
  const velocity = useSpring(useVelocity(scrollY), { damping: 50, stiffness: 300 })
  const speedBoost = useTransform(velocity, [-2500, 0, 2500], [-6, 0, 6], { clamp: false })
  const skew = useTransform(velocity, [-2500, 2500], [-7, 7])
  const x = useTransform(offset, (value) => `${wrap(-25, -50, value)}%`)
  const direction = useRef(-1)

  useAnimationFrame((_, delta) => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const boost = speedBoost.get()
    if (boost !== 0) direction.current = boost < 0 ? 1 : -1
    offset.set(offset.get() + direction.current * BASE_SPEED * (1 + Math.abs(boost)) * (delta / 1000))
  })

  return (
    <div aria-hidden="true" className="overflow-hidden whitespace-nowrap">
      <motion.div style={{ x, skewX: skew }} className="inline-flex">
        {Array.from({ length: 4 }, (_, copy) => (
          <span key={copy} className="font-display text-[clamp(3.5rem,11vw,9rem)] font-extrabold leading-none tracking-[-0.03em] text-white/10">
            {MARQUEE_STOPS.map((stop) => (
              <span key={stop}>
                {stop}
                <span className="mx-[0.3em] text-amber/40">→</span>
              </span>
            ))}
          </span>
        ))}
      </motion.div>
    </div>
  )
}

export function FinalCta() {
  const { user } = useAuth()

  return (
    <footer className="overflow-hidden bg-ink text-white">
      <div className="pt-24 lg:pt-32">
        <ScrollMarquee />
      </div>

      <Reveal className="mx-auto mt-12 max-w-4xl px-4 text-center sm:px-8">
        <h2 className="section-title">Where do you want to go?</h2>
        <p className="mt-4 text-lg text-white/70">Tell me your destination, dates and budget.</p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Magnetic>
            <Link to={CHAT_ROUTE} className="inline-flex h-13 items-center rounded-xl bg-teal px-6 font-semibold transition-colors hover:bg-teal-deep">
              {user ? 'Start a temporary chat' : 'Start as a guest'}
            </Link>
          </Magnetic>
          {!user && (
            <Link to="/signup" className="inline-flex h-13 items-center rounded-xl border border-white/20 px-6 font-semibold hover:bg-white/10">
              Create an account
            </Link>
          )}
        </div>
      </Reveal>

      <div className="mx-auto mt-24 flex max-w-7xl flex-col gap-6 border-t border-white/12 px-4 py-8 sm:px-8 lg:flex-row lg:items-center lg:justify-between">
        <Logo className="text-white" />
        <nav aria-label="Footer" className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-white/65">
          {NAV_LINKS.map(({ id, label }) => (
            <button key={id} type="button" onClick={() => scrollToSection(id)} className="hover:text-white">
              {label}
            </button>
          ))}
        </nav>
        <p className="max-w-sm text-xs text-white/50">Figures on this page are samples. Booking happens on provider sites.</p>
      </div>
    </footer>
  )
}
