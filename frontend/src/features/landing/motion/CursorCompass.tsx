import { motion, useMotionValue, useSpring } from 'framer-motion'
import { useEffect, useState } from 'react'

const SPRING = { stiffness: 420, damping: 34, mass: 0.35 }

/** A soft ring trailing the mouse. It never replaces the system cursor. */
export function CursorCompass() {
  const [enabled] = useState(() => window.matchMedia('(pointer: fine) and (prefers-reduced-motion: no-preference)').matches)
  const [isOverAction, setIsOverAction] = useState(false)
  const [isVisible, setIsVisible] = useState(false)
  const pointerX = useMotionValue(-100)
  const pointerY = useMotionValue(-100)
  const x = useSpring(pointerX, SPRING)
  const y = useSpring(pointerY, SPRING)

  useEffect(() => {
    if (!enabled) return
    const onMove = (event: PointerEvent) => {
      pointerX.set(event.clientX)
      pointerY.set(event.clientY)
      setIsVisible(true)
      setIsOverAction(event.target instanceof Element && event.target.closest('a, button, input, textarea') !== null)
    }
    const onLeave = () => setIsVisible(false)
    window.addEventListener('pointermove', onMove, { passive: true })
    document.documentElement.addEventListener('pointerleave', onLeave)
    return () => {
      window.removeEventListener('pointermove', onMove)
      document.documentElement.removeEventListener('pointerleave', onLeave)
    }
  }, [enabled, pointerX, pointerY])

  if (!enabled) return null

  return (
    <motion.div
      aria-hidden="true"
      className="pointer-events-none fixed left-0 top-0 z-[70] -ml-5 -mt-5 size-10 rounded-full border border-white mix-blend-difference"
      style={{ x, y }}
      animate={{ scale: isOverAction ? 1.6 : 1, opacity: isVisible ? 1 : 0 }}
      transition={{ duration: 0.2 }}
    />
  )
}
