import { motion, useSpring } from 'framer-motion'
import type { ReactNode } from 'react'

const SPRING = { stiffness: 180, damping: 18, mass: 0.4 }

/** Pulls its child toward the cursor when the cursor is near. */
export function Magnetic({ children, strength = 0.3, className }: { children: ReactNode; strength?: number; className?: string }) {
  const x = useSpring(0, SPRING)
  const y = useSpring(0, SPRING)

  return (
    <motion.div
      className={className}
      style={{ x, y }}
      onPointerMove={(event) => {
        if (event.pointerType !== 'mouse') return
        const rect = event.currentTarget.getBoundingClientRect()
        x.set((event.clientX - rect.left - rect.width / 2) * strength)
        y.set((event.clientY - rect.top - rect.height / 2) * strength)
      }}
      onPointerLeave={() => {
        x.set(0)
        y.set(0)
      }}
    >
      {children}
    </motion.div>
  )
}
