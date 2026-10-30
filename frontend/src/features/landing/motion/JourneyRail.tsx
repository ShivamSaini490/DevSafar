import { motion, useMotionValueEvent, useScroll } from 'framer-motion'
import { useState } from 'react'
import { SECTIONS } from '../content.ts'
import { scrollToSection } from './scrollToSection.ts'

/** Fixed right-edge progress rail: the page itself is the journey. */
export function JourneyRail() {
  const { scrollY } = useScroll()
  const [activeIndex, setActiveIndex] = useState(0)

  useMotionValueEvent(scrollY, 'change', () => {
    const line = window.innerHeight * 0.5
    let next = 0
    SECTIONS.forEach(({ id }, index) => {
      const section = document.getElementById(id)
      if (section && section.getBoundingClientRect().top <= line) next = index
    })
    setActiveIndex(next)
  })

  return (
    <nav aria-label="Page sections" className="fixed right-4 top-1/2 z-40 hidden -translate-y-1/2 xl:block">
      <div className="relative flex flex-col gap-5 rounded-full bg-ink/70 px-2 py-3 backdrop-blur-md">
        <span aria-hidden="true" className="absolute inset-y-4 left-1/2 w-px -translate-x-1/2 bg-white/20" />
        <motion.span
          aria-hidden="true"
          className="absolute left-1/2 top-4 w-px -translate-x-1/2 bg-amber"
          animate={{ height: `calc(${(activeIndex / (SECTIONS.length - 1)) * 100}% - ${(activeIndex / (SECTIONS.length - 1)) * 32}px)` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
        {SECTIONS.map(({ id, label }, index) => (
          <button
            key={id}
            type="button"
            onClick={() => scrollToSection(id)}
            aria-label={label}
            aria-current={index === activeIndex ? 'step' : undefined}
            className="group relative grid size-4 place-items-center"
          >
            <span
              className={`block size-2 rounded-full transition-all ${
                index <= activeIndex ? 'bg-amber' : 'bg-white/40 group-hover:bg-white'
              } ${index === activeIndex ? 'scale-150' : ''}`}
            />
            <span className="eyebrow pointer-events-none absolute right-7 whitespace-nowrap rounded-md bg-ink px-2 py-1 !text-[10px] text-white opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
              {label}
            </span>
          </button>
        ))}
      </div>
    </nav>
  )
}
