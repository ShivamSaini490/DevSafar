import { AnimatePresence, motion } from 'framer-motion'
import { ExternalLink } from 'lucide-react'
import { useRef, useState } from 'react'
import { BudgetDonut } from '../BudgetDonut.tsx'
import { buildSampleDays, buildSampleHotels, buildSamplePlaces } from '../content.ts'
import type { TripRoute } from '../geo.ts'
import { DESKTOP_MOTION, gsap, useGSAP } from '../motion/gsap.ts'
import { Reveal } from '../motion/Reveal.tsx'
import { TransportBars } from '../TransportBars.tsx'

const TABS = ['Itinerary', 'Transport', 'Hotels', 'Places', 'Budget'] as const
type Tab = (typeof TABS)[number]

function UnknownNote({ label }: { label: string }) {
  return <p className="mt-3 font-mono text-xs text-muted">{label}: unknown until a source confirms it</p>
}

function TabPanel({ tab, trip }: { tab: Tab; trip: TripRoute }) {
  if (tab === 'Itinerary') {
    return (
      <ol className="flex flex-col gap-3">
        {buildSampleDays(trip).map((day) => (
          <li key={day.day} className="flex items-center gap-5 rounded-2xl border border-line bg-paper p-4 sm:p-5">
            <span className="grid h-14 w-16 shrink-0 place-items-center rounded-xl bg-mint font-mono text-sm font-medium text-teal">{day.day}</span>
            <div>
              <h4 className="font-display text-xl font-bold text-ink-soft">{day.place}</h4>
              <p className="text-muted">{day.plan}</p>
            </div>
          </li>
        ))}
      </ol>
    )
  }

  if (tab === 'Transport') {
    return (
      <div>
        <p className="mb-5 text-sm text-muted">Demo estimates only, not live fares.</p>
        <TransportBars />
      </div>
    )
  }

  if (tab === 'Hotels') {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {buildSampleHotels(trip).map((hotel) => (
          <article key={hotel.area} className="rounded-2xl border border-line bg-paper p-5">
            <h4 className="font-display text-xl font-bold text-ink-soft">{hotel.area}</h4>
            <p className="mt-2 text-muted">{hotel.note}</p>
            <UnknownNote label="Rate" />
            <p className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-teal">
              View on provider
              <ExternalLink className="size-3.5" aria-hidden="true" />
            </p>
          </article>
        ))}
      </div>
    )
  }

  if (tab === 'Places') {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {buildSamplePlaces(trip).map((place) => (
          <article key={place.name} className="rounded-2xl border border-line bg-paper p-5">
            <p className="eyebrow !text-[10px] text-teal">{place.city}</p>
            <h4 className="mt-1 font-display text-xl font-bold text-ink-soft">{place.name}</h4>
            <UnknownNote label="Fee and timings" />
          </article>
        ))}
      </div>
    )
  }

  return (
    <div>
      <p className="mb-4 text-sm text-muted">Example budget, not a quote. Hover a slice to see its share.</p>
      <BudgetDonut />
    </div>
  )
}

export function TripShowcase({ trip }: { trip: TripRoute }) {
  const rootRef = useRef<HTMLElement>(null)
  const [activeTab, setActiveTab] = useState<Tab>('Itinerary')

  useGSAP(
    () => {
      gsap.matchMedia().add(DESKTOP_MOTION, () => {
        gsap.fromTo(
          '.trip-frame',
          { rotateX: 16, scale: 0.9, transformPerspective: 1400, transformOrigin: 'center top' },
          {
            rotateX: 0,
            scale: 1,
            ease: 'none',
            scrollTrigger: { trigger: '.trip-frame', start: 'top 95%', end: 'top 25%', scrub: 0.6 },
          },
        )
      })
    },
    { scope: rootRef },
  )

  return (
    <section id="trip-view" ref={rootRef} className="bg-paper px-4 py-20 sm:px-8 lg:py-28">
      <div className="mx-auto max-w-5xl">
        <Reveal className="text-center">
          <p className="eyebrow text-teal">Trip view</p>
          <h2 className="section-title mt-3 text-ink-soft">Not a wall of text. A trip you can read.</h2>
          <p className="mx-auto mt-4 max-w-xl text-lg text-muted">
            Your plan arrives inside the chat as itinerary, transport, hotels, places and budget, and every follow-up updates it.
          </p>
        </Reveal>

        <div className="trip-frame mt-12 rounded-3xl border border-line bg-white p-5 shadow-2xl shadow-ink/10 sm:p-8">
          <h3 className="font-display text-2xl font-bold tracking-tight text-ink-soft sm:text-3xl">{trip.map((city) => city.name).join(' > ')}</h3>
          <p className="mt-1 text-muted">3-day trip | Sample trip, illustrative dates and costs</p>

          <div role="tablist" aria-label="Sample trip sections" className="mt-5 flex gap-2 overflow-x-auto pb-1">
            {TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={tab === activeTab}
                onClick={() => setActiveTab(tab)}
                className={`relative shrink-0 rounded-xl border border-line px-4 py-2 text-sm font-medium transition-colors sm:flex-1 ${
                  tab === activeTab ? 'text-teal-deep' : 'text-ink-soft hover:border-teal/40'
                }`}
              >
                {tab === activeTab && (
                  <motion.span layoutId="trip-tab" className="absolute inset-0 rounded-xl bg-mint" transition={{ type: 'spring', stiffness: 320, damping: 30 }} />
                )}
                <span className="relative">{tab}</span>
              </button>
            ))}
          </div>

          <div className="mt-5 min-h-[20rem]" role="tabpanel" aria-label={activeTab}>
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.22 }}
              >
                <TabPanel tab={activeTab} trip={trip} />
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  )
}
