import { ArrowRight, MessageCircle } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { CHAT_ROUTE } from '../../chat/prompts.ts'
import { DotMapCanvas } from '../DotMapCanvas.tsx'
import type { TripRoute } from '../geo.ts'
import { DESKTOP_MOTION, MOTION_OK, ScrollTrigger, SplitText, gsap, useGSAP } from '../motion/gsap.ts'
import { Magnetic } from '../motion/Magnetic.tsx'
import { scrollToSection } from '../motion/scrollToSection.ts'
import { RouteOverlay, type RouteOverlayHandle } from '../RouteOverlay.tsx'

export function Hero({ isRevealed, trip }: { isRevealed: boolean; trip: TripRoute }) {
  const rootRef = useRef<HTMLElement>(null)
  const routeRef = useRef<RouteOverlayHandle>(null)
  const introRef = useRef<gsap.core.Timeline>(null)

  // The intro waits for the brand loader, so it never plays unseen behind it.
  useEffect(() => {
    if (isRevealed) introRef.current?.play()
  }, [isRevealed])

  useGSAP(
    () => {
      const route = { intro: 0, scroll: 0 }
      let drawnProgress = -1
      // One ticker draws the line, so the intro and scroll tweens never fight over it.
      const renderRoute = () => {
        const progress = Math.max(route.intro, route.scroll)
        if (progress === drawnProgress) return
        drawnProgress = progress
        routeRef.current?.setProgress(progress)
      }
      const media = gsap.matchMedia()

      media.add(MOTION_OK, () => {
        const split = SplitText.create('.hero-title', { type: 'lines,chars', mask: 'lines' })
        const glowX = gsap.quickTo('.hero-glow', 'x', { duration: 1.1, ease: 'power3' })
        const glowY = gsap.quickTo('.hero-glow', 'y', { duration: 1.1, ease: 'power3' })
        const mapX = gsap.quickTo('.hero-map-parallax', 'x', { duration: 1.2, ease: 'power3' })
        const mapY = gsap.quickTo('.hero-map-parallax', 'y', { duration: 1.2, ease: 'power3' })

        const onPointerMove = (event: PointerEvent) => {
          glowX(event.clientX)
          glowY(event.clientY)
          mapX((event.clientX / window.innerWidth - 0.5) * -18)
          mapY((event.clientY / window.innerHeight - 0.5) * -14)
        }
        window.addEventListener('pointermove', onPointerMove, { passive: true })
        gsap.ticker.add(renderRoute)

        introRef.current = gsap
          .timeline({ paused: true, defaults: { ease: 'power4.out' } })
          .from(split.chars, { yPercent: 115, duration: 1, stagger: 0.016 })
          .from('.hero-intro', { y: 24, autoAlpha: 0, duration: 0.8, stagger: 0.09 }, 0.45)
          .from('.hero-map', { autoAlpha: 0, scale: 0.96, duration: 1.4 }, 0.1)
          .to(route, { intro: 0.3, duration: 2, ease: 'power2.inOut' }, 1.3)

        return () => {
          gsap.ticker.remove(renderRoute)
          window.removeEventListener('pointermove', onPointerMove)
          split.revert()
        }
      })

      media.add(DESKTOP_MOTION, () => {
        // The map glides to the centre while the rest of the route draws itself.
        const distanceToCentre = () => {
          const rect = rootRef.current!.querySelector('.hero-map')!.getBoundingClientRect()
          return window.innerWidth / 2 - (rect.left + rect.width / 2)
        }
        const timeline = gsap.timeline({
          scrollTrigger: {
            trigger: rootRef.current,
            start: 'top top',
            end: '+=140%',
            pin: true,
            scrub: 0.8,
            anticipatePin: 1,
            invalidateOnRefresh: true,
          },
        })
        timeline
          .to('.hero-copy', { y: -130, autoAlpha: 0, duration: 0.35, ease: 'power2.in' }, 0)
          .to('.hero-map', { x: distanceToCentre, scale: 1.08, duration: 0.6, ease: 'power2.inOut' }, 0.05)
          .to(route, { scroll: 1, duration: 0.8, ease: 'none' }, 0.15)
          .fromTo('.hero-caption', { autoAlpha: 0, y: 30 }, { autoAlpha: 1, y: 0, duration: 0.25 }, 0.6)
          .to({}, { duration: 0.1 })
      })

      media.add('(max-width: 1023.98px), (max-height: 619.98px)', () => {
        // No pin here: the route finishes as the map scrolls through the screen.
        ScrollTrigger.create({
          trigger: '.hero-map',
          start: 'top 80%',
          end: 'bottom 40%',
          scrub: 0.6,
          onUpdate: (self) => {
            route.scroll = self.progress
          },
        })
      })
    },
    { scope: rootRef },
  )

  return (
    <section ref={rootRef} className="relative overflow-hidden bg-ink text-white lg:h-svh lg:min-h-[620px]">
      <div
        aria-hidden="true"
        className="hero-glow pointer-events-none absolute -left-[300px] -top-[300px] size-[600px] rounded-full bg-teal/30 blur-[110px]"
      />

      <div className="relative h-full px-4 sm:px-8">
        <div className="mx-auto grid h-full max-w-7xl items-center gap-8 pb-10 pt-24 lg:grid-cols-2 lg:pb-0 lg:pt-16">
          <div className="hero-copy relative z-10">
            <p className="hero-intro eyebrow text-teal-bright">Safar means journey</p>
            <h1 className="hero-title mt-4 font-display text-[clamp(3rem,5.2vw,5rem)] font-extrabold leading-[1] tracking-[-0.035em] lg:whitespace-nowrap">
              Plan smarter.
              <br />
              <span className="text-teal-bright">Travel further.</span>
            </h1>
            <p className="hero-intro mt-6 max-w-lg text-lg text-white/75">
              Personalized routes, hotels and beautiful itineraries, all in one conversation.
            </p>

            <div className="hero-intro mt-8 flex flex-wrap items-center gap-3">
              <Magnetic>
                <Link
                  to={CHAT_ROUTE}
                  className="inline-flex h-13 items-center gap-2 rounded-xl bg-teal px-4 font-semibold sm:px-6 text-white transition-colors hover:bg-teal-deep"
                >
                  <MessageCircle className="size-5" aria-hidden="true" />
                  Start planning
                </Link>
              </Magnetic>
              <button
                type="button"
                onClick={() => scrollToSection('how-it-works')}
                className="inline-flex h-13 items-center gap-2 rounded-xl border border-white/20 px-4 font-semibold sm:px-6 text-white transition-colors hover:bg-white/10"
              >
                How it works
                <ArrowRight className="size-4" aria-hidden="true" />
              </button>
            </div>
            <p className="hero-intro mt-4 text-sm text-white/55">No account needed. Temporary chats stay out of your history.</p>
          </div>

          <div className="hero-map relative mx-auto aspect-[1000/1086] w-full max-w-md lg:mx-0 lg:max-w-[calc((100svh-6rem)/1.086)] lg:justify-self-end">
            <div className="hero-map-parallax absolute inset-0">
              <DotMapCanvas className="absolute inset-0 size-full" />
              <RouteOverlay ref={routeRef} trip={trip} className="absolute inset-0 size-full" />
            </div>
          </div>
        </div>
      </div>

      <div className="hero-caption pointer-events-none absolute bottom-[12%] left-[max(2rem,calc((100vw-80rem)/2))] hidden max-w-xs lg:block lg:opacity-0">
        <p className="eyebrow text-amber">Sample round trip</p>
        <p className="mt-3 font-display text-4xl font-bold leading-tight tracking-tight">Three stops. Back by Monday, 10 AM.</p>
      </div>
    </section>
  )
}
