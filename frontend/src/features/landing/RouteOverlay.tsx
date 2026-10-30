import { forwardRef, useImperativeHandle, useMemo, useRef } from 'react'
import { VIEW_HEIGHT, VIEW_WIDTH, project, roundTripLegs, type TripRoute } from './geo.ts'

const ARABIAN_SEA = project([11.5, 68.2])
const BAY_OF_BENGAL = project([15, 83])

function buildRoute(trip: TripRoute) {
  const stops = trip.map((city) => city.point)
  const points = stops.map(project)
  const centreX = points.reduce((sum, point) => sum + point.x, 0) / points.length

  return {
    legs: roundTripLegs(stops),
    // Each label sits on the side facing away from the route, so the line never crosses it.
    stops: points.map((point, index) => {
      const isLeftOfRoute = point.x < centreX
      return {
        name: trip[index].name,
        point,
        labelX: isLeftOfRoute ? -30 : 30,
        anchor: isLeftOfRoute ? ('end' as const) : ('start' as const),
      }
    }),
  }
}

export interface RouteOverlayHandle {
  /** 0 is nothing drawn, 1 is the full round trip. */
  setProgress: (progress: number) => void
}

interface RouteOverlayProps {
  trip: TripRoute
  className?: string
}

/** Draws the page's round trip. With no calls to setProgress (reduced motion) it simply shows complete. */
export const RouteOverlay = forwardRef<RouteOverlayHandle, RouteOverlayProps>(function RouteOverlay({ trip, className }, ref) {
  const route = useMemo(() => buildRoute(trip), [trip])
  const legRefs = useRef<(SVGPathElement | null)[]>([])
  const stopRefs = useRef<(SVGGElement | null)[]>([])
  const headRef = useRef<SVGCircleElement>(null)

  useImperativeHandle(ref, () => ({
    setProgress(progress) {
      const legs = legRefs.current.filter((leg): leg is SVGPathElement => leg !== null)
      const lengths = legs.map((leg) => leg.getTotalLength())
      const total = lengths.reduce((sum, length) => sum + length, 0)
      let remaining = progress * total
      let headPoint: DOMPoint | null = null

      legs.forEach((leg, index) => {
        const drawn = Math.min(remaining, lengths[index])
        leg.style.strokeDasharray = `${lengths[index]}`
        leg.style.strokeDashoffset = `${lengths[index] - drawn}`
        if (remaining > 0 && drawn > 0) headPoint = leg.getPointAtLength(drawn)
        stopRefs.current[index + 1]?.classList.toggle('is-on', index < 2 && remaining >= lengths[index])
        remaining -= drawn
      })

      stopRefs.current[0]?.classList.toggle('is-on', true)
      const head = headRef.current
      const point = headPoint as DOMPoint | null
      if (head && point) {
        head.setAttribute('cx', `${point.x}`)
        head.setAttribute('cy', `${point.y}`)
        head.style.opacity = progress >= 1 || progress <= 0 ? '0' : '1'
      }
    },
  }))

  return (
    <svg viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`} className={className} role="img" aria-label={`Sample round trip from ${trip[0].name} to ${trip[1].name}, ${trip[2].name} and back to ${trip[0].name}`}>
      <text x={ARABIAN_SEA.x} y={ARABIAN_SEA.y} className="fill-white/25 font-mono text-[18px] italic tracking-[0.2em]">
        Arabian Sea
      </text>
      <text x={BAY_OF_BENGAL.x} y={BAY_OF_BENGAL.y} className="fill-white/25 font-mono text-[18px] italic tracking-[0.2em]">
        Bay of Bengal
      </text>

      {route.legs.map((d, index) => (
        <path
          key={d}
          ref={(element) => {
            legRefs.current[index] = element
          }}
          d={d}
          fill="none"
          stroke="#f3ac55"
          strokeWidth="4"
          style={{ filter: 'drop-shadow(0 0 7px rgb(243 172 85 / 0.75))' }}
        />
      ))}

      {route.stops.map((stop, index) => (
        <g
          key={stop.name}
          ref={(element) => {
            stopRefs.current[index] = element
          }}
          className="city is-on"
        >
          <circle className="city-ring" cx={stop.point.x} cy={stop.point.y} r="22" fill="none" stroke="#f3ac55" strokeWidth="2" />
          <circle cx={stop.point.x} cy={stop.point.y} r="8" fill="#fff" />
          <text
            x={stop.point.x + stop.labelX}
            y={stop.point.y + 8}
            textAnchor={stop.anchor}
            className="fill-white font-mono text-[25px] font-medium"
            style={{ paintOrder: 'stroke', stroke: '#0c1c2c', strokeWidth: 8 }}
          >
            {stop.name}
          </text>
        </g>
      ))}

      <circle ref={headRef} r="10" fill="#f3ac55" style={{ opacity: 0 }} />
    </svg>
  )
})
