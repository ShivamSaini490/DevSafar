import { useRef, useState } from 'react'
import { LOADER_WORDS } from './content.ts'
import { markLoaderPlayed } from './motion/loaderState.ts'
import { ScrollTrigger, gsap, useGSAP } from './motion/gsap.ts'

const FONT_WAIT_MS = 1200
const SETTLE_MS = 250

/** Word-by-word brand line shown on a fresh page load. Calls onReveal as the curtain starts to lift. */
export function BrandLoader({ onReveal }: { onReveal: () => void }) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [isDone, setIsDone] = useState(false)

  useGSAP(
    () => {
      const root = document.documentElement
      root.style.overflow = 'hidden'
      const unlockScroll = () => {
        root.style.overflow = ''
      }

      const timeline = gsap.timeline({ paused: true })
      timeline
        .from('.loader-word', { y: 32, autoAlpha: 0, filter: 'blur(10px)', duration: 1, stagger: 0.24, ease: 'power3.out' })
        .from('.loader-line', { scaleX: 0, duration: 1.7, ease: 'sine.inOut' }, 0)
        // Refreshing is a heavy layout pass, so it runs here while nothing is moving.
        .add(() => {
          unlockScroll()
          ScrollTrigger.refresh()
        })
        .to({}, { duration: 0.4 })
        .add(onReveal)
        .to('.loader-word', { y: -20, autoAlpha: 0, duration: 0.6, stagger: 0.03, ease: 'power2.inOut' })
        .to('.loader-line', { autoAlpha: 0, duration: 0.5, ease: 'power2.inOut' }, '<')
        .to(rootRef.current, { yPercent: -100, duration: 1.1, ease: 'power3.inOut' }, '<0.15')
        .add(() => {
          markLoaderPlayed()
          setIsDone(true)
        })

      // Start once the display font is in and the page has finished its heavy first render,
      // so the first word never swaps font or stutters.
      let isCancelled = false
      const fontTimeout = new Promise((resolve) => window.setTimeout(resolve, FONT_WAIT_MS))
      void Promise.race([document.fonts.load('800 1em "Bricolage Grotesque Variable"'), fontTimeout]).then(() => {
        window.setTimeout(() => {
          if (!isCancelled) timeline.play()
        }, SETTLE_MS)
      })

      return () => {
        isCancelled = true
        unlockScroll()
      }
    },
    { scope: rootRef },
  )

  if (isDone) return null

  return (
    <div
      ref={rootRef}
      role="status"
      aria-label={LOADER_WORDS.map(({ text }) => text).join(' ')}
      className="fixed inset-0 z-[65] grid place-items-center bg-ink px-4 text-white will-change-transform"
    >
      <div>
        <p
          aria-hidden="true"
          className="flex flex-wrap justify-center gap-x-[0.28em] pb-[0.14em] font-display text-[clamp(2.75rem,7vw,6rem)] font-extrabold leading-[1.1] tracking-[-0.035em]"
        >
          {LOADER_WORDS.map(({ text, isAccent }) => (
            <span key={text} className={`loader-word inline-block will-change-transform ${isAccent ? 'text-teal-bright' : ''}`}>
              {text}
            </span>
          ))}
        </p>
        <div aria-hidden="true" className="loader-line mt-3 h-1 origin-left rounded-full bg-amber" />
      </div>
    </div>
  )
}
