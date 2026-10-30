import { useMotionValue, useSpring, useTransform } from 'framer-motion'
import type { PointerEvent } from 'react'

const SPRING = { stiffness: 180, damping: 18, mass: 0.4 }

/** Pointer-driven 3D tilt. Spread the result on a motion element. */
export function useTilt(maxDegrees = 7) {
  const pointerX = useMotionValue(0)
  const pointerY = useMotionValue(0)
  const rotateY = useSpring(useTransform(pointerX, [-0.5, 0.5], [-maxDegrees, maxDegrees]), SPRING)
  const rotateX = useSpring(useTransform(pointerY, [-0.5, 0.5], [maxDegrees, -maxDegrees]), SPRING)

  return {
    style: { rotateX, rotateY, transformPerspective: 1100 },
    onPointerMove(event: PointerEvent<HTMLElement>) {
      if (event.pointerType !== 'mouse') return
      const rect = event.currentTarget.getBoundingClientRect()
      pointerX.set((event.clientX - rect.left) / rect.width - 0.5)
      pointerY.set((event.clientY - rect.top) / rect.height - 0.5)
    },
    onPointerLeave() {
      pointerX.set(0)
      pointerY.set(0)
    },
  }
}
