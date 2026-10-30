import { describe, expect, it } from 'vitest'
import { LANDMASSES, TOURIST_CITIES, VIEW_HEIGHT, VIEW_WIDTH, isInside, pickRoute, project, roundTripLegs, triangleArea, unproject, type LatLon } from './geo.ts'

const onLand = (point: LatLon) => LANDMASSES.some((polygon) => isInside(point, polygon))

function seededRandom(seed: number) {
  let state = seed
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296
    return state / 4294967296
  }
}

describe('map geometry', () => {
  it('keeps every route city inside the visible map and on land', () => {
    for (const { point } of TOURIST_CITIES) {
      const { x, y } = project(point)
      expect(x).toBeGreaterThan(0)
      expect(x).toBeLessThan(VIEW_WIDTH)
      expect(y).toBeGreaterThan(0)
      expect(y).toBeLessThan(VIEW_HEIGHT)
      expect(onLand(point)).toBe(true)
    }
  })

  it('round-trips through project and unproject', () => {
    const { x, y } = project([17.385, 78.487])
    const [lat, lon] = unproject(x / VIEW_WIDTH, y / VIEW_HEIGHT)
    expect(lat).toBeCloseTo(17.385, 6)
    expect(lon).toBeCloseTo(78.487, 6)
  })

  it.each([
    ['Delhi', 28.61, 77.21],
    ['Mumbai', 19.08, 72.95],
    ['Bengaluru', 12.97, 77.59],
    ['Kolkata', 22.57, 88.36],
    ['Srinagar', 34.08, 74.8],
    ['Leh', 34.16, 77.58],
    ['Muzaffarabad', 34.37, 73.47],
    ['Gilgit', 35.92, 74.31],
    ['Gangtok', 27.33, 88.6],
    ['Itanagar', 27.08, 93.61],
    ['Guwahati', 26.14, 91.74],
    ['Shillong', 25.57, 91.88],
    ['Imphal', 24.82, 93.94],
    ['Aizawl', 23.73, 92.72],
    ['Agartala', 23.83, 91.28],
    ['Port Blair', 11.62, 92.73],
  ])('includes %s', (_name, lat, lon) => {
    expect(onLand([lat, lon])).toBe(true)
  })

  it.each([
    ['Kathmandu', 27.7, 85.3],
    ['Thimphu', 27.47, 89.64],
    ['Dhaka', 23.81, 90.41],
    ['Lahore', 31.55, 74.2],
    ['Karachi', 24.86, 67.01],
    ['Colombo', 6.93, 79.86],
    ['Arabian Sea', 15, 70],
    ['Bay of Bengal', 14, 84],
  ])('excludes %s', (_name, lat, lon) => {
    expect(onLand([lat, lon])).toBe(false)
  })
})

describe('random routes', () => {
  it('always picks three different, well-separated cities', () => {
    for (let seed = 1; seed <= 500; seed++) {
      const route = pickRoute(seededRandom(seed))
      const points = route.map((city) => city.point)
      expect(new Set(route).size).toBe(3)
      expect(triangleArea(points[0], points[1], points[2])).toBeGreaterThanOrEqual(45000)
      points.forEach((point, index) => {
        const a = project(point)
        const b = project(points[(index + 1) % 3])
        expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(230)
      })
    }
  })

  it('uses nearly every tourist city across loads', () => {
    const used = new Set(Array.from({ length: 300 }, (_, seed) => pickRoute(seededRandom(seed + 1)).map((city) => city.name)).flat())
    expect(used.size).toBeGreaterThanOrEqual(9)
  })

  it('gives different routes on different loads', () => {
    const routes = Array.from({ length: 100 }, (_, seed) => pickRoute(seededRandom(seed + 1)).map((city) => city.name).join())
    expect(new Set(routes).size).toBeGreaterThan(40)
  })

  it('draws a closed loop that returns to the first stop', () => {
    const route = pickRoute(seededRandom(7)).map((city) => city.point)
    const legs = roundTripLegs(route)
    const start = project(route[0])

    expect(legs).toHaveLength(3)
    expect(legs[0].startsWith(`M${start.x.toFixed(1)} ${start.y.toFixed(1)}`)).toBe(true)
    expect(legs[2].endsWith(`${start.x.toFixed(1)} ${start.y.toFixed(1)}`)).toBe(true)
  })
})
