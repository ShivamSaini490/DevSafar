import { useEffect, useRef } from 'react'
import { LANDMASSES, isInside, unproject } from './geo.ts'
import { gsap } from './motion/gsap.ts'

const SPACING = 9
const DOT = 2.4
const REACH = 130
const PUSH = 26

interface Dot {
  x: number
  y: number
  alpha: number
  offsetX: number
  offsetY: number
  glow: number
}

function buildDots(width: number, height: number): Dot[] {
  const dots: Dot[] = []
  for (let y = SPACING / 2; y < height; y += SPACING) {
    for (let x = SPACING / 2; x < width; x += SPACING) {
      const point = unproject(x / width, y / height)
      if (!LANDMASSES.some((polygon) => isInside(point, polygon))) continue
      dots.push({ x, y, alpha: 0.72, offsetX: 0, offsetY: 0, glow: 0 })
    }
  }
  return dots
}

/** The land drawn as dots. Dots near the mouse scatter and warm up, then ease back. */
export function DotMapCanvas({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const pointer = { x: -9999, y: -9999, inside: false }
    let dots: Dot[] = []
    let width = 0
    let height = 0
    let isOnScreen = true
    let needsDraw = true

    const resize = () => {
      if (canvas.clientWidth === width && canvas.clientHeight === height) return
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = width * ratio
      canvas.height = height * ratio
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      dots = buildDots(width, height)
      needsDraw = true
    }

    const draw = () => {
      if (!isOnScreen || !needsDraw) return
      needsDraw = false
      context.clearRect(0, 0, width, height)

      for (const dot of dots) {
        let targetX = 0
        let targetY = 0
        let targetGlow = 0
        if (pointer.inside) {
          const dx = dot.x - pointer.x
          const dy = dot.y - pointer.y
          const distance = Math.hypot(dx, dy) || 1
          if (distance < REACH) {
            const strength = 1 - distance / REACH
            targetX = (dx / distance) * strength * PUSH
            targetY = (dy / distance) * strength * PUSH
            targetGlow = strength
          }
        }
        dot.offsetX += (targetX - dot.offsetX) * 0.14
        dot.offsetY += (targetY - dot.offsetY) * 0.14
        dot.glow += (targetGlow - dot.glow) * 0.14
        if (Math.abs(targetX - dot.offsetX) + Math.abs(targetY - dot.offsetY) + Math.abs(targetGlow - dot.glow) > 0.02) {
          needsDraw = true
        }

        context.globalAlpha = Math.min(1, dot.alpha + dot.glow)
        context.fillStyle = dot.glow > 0.08 ? '#f3ac55' : '#2cc7bd'
        const size = DOT + dot.glow * 1.8
        context.fillRect(dot.x + dot.offsetX, dot.y + dot.offsetY, size, size)
      }
    }

    resize()
    draw()

    const resizeObserver = new ResizeObserver(() => {
      resize()
      draw()
    })
    resizeObserver.observe(canvas)
    if (reduceMotion) return () => resizeObserver.disconnect()

    const onPointerMove = (event: PointerEvent) => {
      // getBoundingClientRect includes the scroll zoom, so convert back to canvas pixels.
      const rect = canvas.getBoundingClientRect()
      pointer.x = (event.clientX - rect.left) * (width / rect.width)
      pointer.y = (event.clientY - rect.top) * (height / rect.height)
      pointer.inside = pointer.x > -REACH && pointer.y > -REACH && pointer.x < width + REACH && pointer.y < height + REACH
      needsDraw = true
    }
    const visibility = new IntersectionObserver(([entry]) => {
      isOnScreen = entry.isIntersecting
    })
    visibility.observe(canvas)
    window.addEventListener('pointermove', onPointerMove, { passive: true })
    gsap.ticker.add(draw)

    return () => {
      gsap.ticker.remove(draw)
      window.removeEventListener('pointermove', onPointerMove)
      visibility.disconnect()
      resizeObserver.disconnect()
    }
  }, [])

  return <canvas ref={canvasRef} aria-hidden="true" className={className} />
}
