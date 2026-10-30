import { useEffect, useState } from 'react'
import { BrandLoader } from '../features/landing/BrandLoader.tsx'
import { pickRoute } from '../features/landing/geo.ts'
import { CursorCompass } from '../features/landing/motion/CursorCompass.tsx'
import { ScrollTrigger } from '../features/landing/motion/gsap.ts'
import { JourneyRail } from '../features/landing/motion/JourneyRail.tsx'
import { shouldShowLoader } from '../features/landing/motion/loaderState.ts'
import { AgentRail } from '../features/landing/sections/AgentRail.tsx'
import { ChatModes } from '../features/landing/sections/ChatModes.tsx'
import { Faq } from '../features/landing/sections/Faq.tsx'
import { FinalCta } from '../features/landing/sections/FinalCta.tsx'
import { Hero } from '../features/landing/sections/Hero.tsx'
import { HonestPrices } from '../features/landing/sections/HonestPrices.tsx'
import { SentenceSection } from '../features/landing/sections/SentenceSection.tsx'
import { TripShowcase } from '../features/landing/sections/TripShowcase.tsx'
import { SiteHeader } from '../features/landing/SiteHeader.tsx'

export function LandingPage() {
  const [trip] = useState(() => pickRoute())
  const [showLoader] = useState(shouldShowLoader)
  const [isRevealed, setIsRevealed] = useState(!showLoader)

  // Web fonts change text heights, which moves every pinned scroll position.
  useEffect(() => {
    document.fonts.ready.then(() => ScrollTrigger.refresh())
  }, [])

  return (
    <>
      {showLoader && <BrandLoader onReveal={() => setIsRevealed(true)} />}
      <CursorCompass />
      <SiteHeader />
      <JourneyRail />

      <main>
        <div id="top">
          <Hero isRevealed={isRevealed} trip={trip} />
        </div>
        <SentenceSection trip={trip} />
        <AgentRail />
        <TripShowcase trip={trip} />
        <HonestPrices />
        <ChatModes />
        <Faq />
      </main>

      <FinalCta />
    </>
  )
}
