export type LatLon = readonly [lat: number, lon: number]

export const VIEW_WIDTH = 1000
export const VIEW_HEIGHT = 1086

const WEST = 67
const EAST = 98
const NORTH = 37.6
const SOUTH = 6.4

/**
 * Stylised outline of India for a dot map, following India's official boundaries
 * (all of Jammu and Kashmir, Ladakh and Arunachal Pradesh). It runs clockwise from
 * the Gujarat coast. It is not a survey-grade map.
 */
const MAINLAND: LatLon[] = [
  // Pakistan border
  [23.7, 68.2], [24.3, 68.8], [24.3, 70.9], [24.7, 71.05], [25.2, 70.6], [25.7, 70.2], [26.6, 70.1], [27.1, 69.6],
  [27.9, 70.4], [28.0, 71.4], [28.4, 72.2], [29.0, 73.0], [29.6, 73.3], [30.1, 73.4], [30.4, 74.0], [31.1, 74.6],
  [31.7, 74.5], [32.5, 74.7],
  // Jammu and Kashmir, Ladakh
  [33.0, 73.8], [33.7, 73.4], [34.3, 73.2], [34.9, 73.6], [35.5, 72.6], [36.0, 71.8], [36.5, 71.6], [36.9, 72.9],
  [37.0, 74.0], [37.1, 75.0], [36.5, 76.0], [35.8, 77.8], [35.5, 78.5], [35.6, 80.3], [34.3, 78.9], [33.3, 79.4],
  [32.6, 79.1], [31.9, 78.9],
  // Himachal, Uttarakhand, then under Nepal
  [31.5, 78.8], [31.0, 79.2], [30.4, 80.2], [30.2, 81.0], [29.0, 80.2], [28.7, 80.1], [28.4, 81.0], [27.9, 81.9],
  [27.4, 83.3], [27.4, 84.6], [26.9, 85.3], [26.6, 86.3], [26.4, 87.3], [26.4, 88.1],
  // Sikkim, then under Bhutan
  [27.2, 88.0], [27.9, 88.1], [28.1, 88.6], [27.4, 88.9], [26.9, 88.9], [26.85, 90.0], [26.8, 91.5], [26.9, 92.1],
  // Arunachal Pradesh
  [27.5, 91.7], [27.8, 91.6], [28.0, 92.5], [28.2, 93.4], [29.0, 94.3], [29.3, 95.5], [29.4, 96.3], [28.4, 97.4],
  [27.7, 97.3],
  // Myanmar border
  [27.2, 96.9], [26.4, 96.0], [25.2, 95.0], [24.0, 94.1], [23.3, 93.4], [22.0, 93.2], [21.95, 92.6],
  // Around Bangladesh: Mizoram, Tripura, Meghalaya, the Siliguri corridor, West Bengal
  [22.6, 92.3], [23.7, 92.25], [23.6, 91.95], [23.0, 91.85], [23.0, 91.4], [23.5, 91.1], [24.1, 91.25], [24.25, 91.9],
  [24.9, 92.4], [25.15, 92.0], [25.2, 90.5], [25.2, 89.9], [25.9, 89.85], [26.3, 89.6], [26.0, 89.3], [26.25, 88.6],
  [26.45, 88.4], [25.9, 88.2], [25.3, 88.8], [24.9, 88.2], [24.4, 88.6], [24.0, 88.7], [23.2, 88.8], [22.4, 89.0],
  [21.6, 89.1],
  // East coast, south to Kanyakumari
  [21.6, 87.5], [21.45, 87.05], [20.25, 86.7], [19.8, 85.85], [19.25, 84.9], [18.25, 84.05], [17.7, 83.3], [16.95, 82.3],
  [16.3, 81.75], [16.15, 81.15], [15.85, 80.5], [15.5, 80.1], [14.4, 80.15], [13.08, 80.3], [11.93, 79.84], [10.9, 79.85],
  [10.3, 79.85], [9.74, 79.02], [9.5, 78.9], [9.2, 79.4], [8.8, 78.15], [8.08, 77.55],
  // West coast, north to Gujarat
  [8.5, 76.95], [8.9, 76.55], [9.95, 76.25], [11.25, 75.75], [11.85, 75.35], [12.9, 74.8], [14, 74.5], [14.8, 74.1],
  [15.4, 73.8], [16.05, 73.45], [17, 73.3], [19, 72.8], [20.4, 72.85], [21.1, 72.7], [21.7, 72.8], [22.3, 72.6],
  [21.8, 72.2], [20.7, 71.0], [20.9, 70.4], [21.6, 69.6], [22.2, 68.95], [22.5, 70.0], [22.8, 69.2], [23.2, 68.6],
]

const ANDAMAN: LatLon[] = [[13.7, 92.8], [13.6, 93.2], [12.0, 93.2], [10.5, 92.8], [10.5, 92.3], [12.0, 92.5]]
const NICOBAR: LatLon[] = [[9.3, 92.7], [9.2, 93.2], [7.9, 94.0], [6.8, 94.0], [6.8, 93.6], [8.0, 93.3]]

export const LANDMASSES = [MAINLAND, ANDAMAN, NICOBAR]

export interface TouristCity {
  name: string
  point: LatLon
  places: readonly [string, string]
}

export type TripRoute = readonly [TouristCity, TouristCity, TouristCity]

/** Popular tourist cities. The marquee lists them and every random route is built from them. */
export const TOURIST_CITIES: TouristCity[] = [
  { name: 'Jaipur', point: [26.91, 75.79], places: ['Amber Fort', 'Hawa Mahal'] },
  { name: 'Agra', point: [27.18, 78.01], places: ['Taj Mahal', 'Agra Fort'] },
  { name: 'Goa', point: [15.4, 74.0], places: ['Baga Beach', 'Basilica of Bom Jesus'] },
  { name: 'Varanasi', point: [25.32, 83.0], places: ['Dashashwamedh Ghat', 'Sarnath'] },
  { name: 'Udaipur', point: [24.59, 73.71], places: ['City Palace', 'Lake Pichola'] },
  { name: 'Rishikesh', point: [30.09, 78.27], places: ['Laxman Jhula', 'Triveni Ghat'] },
  { name: 'Kochi', point: [9.93, 76.27], places: ['Fort Kochi', 'Mattancherry Palace'] },
  { name: 'Manali', point: [32.24, 77.19], places: ['Hadimba Temple', 'Solang Valley'] },
  { name: 'Leh', point: [34.16, 77.58], places: ['Leh Palace', 'Shanti Stupa'] },
  { name: 'Mysuru', point: [12.3, 76.64], places: ['Mysore Palace', 'Chamundi Hill'] },
]

const MIN_STOP_DISTANCE = 230
const MIN_ROUTE_AREA = 45000

export function project([lat, lon]: LatLon) {
  return {
    x: ((lon - WEST) / (EAST - WEST)) * VIEW_WIDTH,
    y: ((NORTH - lat) / (NORTH - SOUTH)) * VIEW_HEIGHT,
  }
}

/** Inverse of project, taking 0 to 1 fractions of the map area. */
export function unproject(fractionX: number, fractionY: number): LatLon {
  return [NORTH - fractionY * (NORTH - SOUTH), WEST + fractionX * (EAST - WEST)]
}

export function isInside(point: LatLon, polygon: readonly LatLon[]): boolean {
  const [lat, lon] = point
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [latI, lonI] = polygon[i]
    const [latJ, lonJ] = polygon[j]
    const crosses = latI > lat !== latJ > lat && lon < ((lonJ - lonI) * (lat - latI)) / (latJ - latI) + lonI
    if (crosses) inside = !inside
  }
  return inside
}

function distance(a: LatLon, b: LatLon) {
  const from = project(a)
  const to = project(b)
  return Math.hypot(to.x - from.x, to.y - from.y)
}

export function triangleArea(a: LatLon, b: LatLon, c: LatLon) {
  const [p, q, r] = [a, b, c].map(project)
  return Math.abs((q.x - p.x) * (r.y - p.y) - (r.x - p.x) * (q.y - p.y)) / 2
}

/** Picks three well-separated cities that form an open loop, not a thin line. */
export function pickRoute(random: () => number = Math.random): TripRoute {
  const shuffled = TOURIST_CITIES.map((city) => ({ city, order: random() }))
    .sort((a, b) => a.order - b.order)
    .map(({ city }) => city)

  for (const first of shuffled) {
    for (const second of shuffled) {
      if (distance(first.point, second.point) < MIN_STOP_DISTANCE) continue
      for (const third of shuffled) {
        const isFarEnough = distance(first.point, third.point) >= MIN_STOP_DISTANCE && distance(second.point, third.point) >= MIN_STOP_DISTANCE
        if (isFarEnough && triangleArea(first.point, second.point, third.point) >= MIN_ROUTE_AREA) {
          return [first, second, third]
        }
      }
    }
  }
  return [TOURIST_CITIES[0], TOURIST_CITIES[2], TOURIST_CITIES[3]]
}

/** Curved legs for a closed loop through the stops, each one bowing away from the middle of the route. */
export function roundTripLegs(stops: readonly LatLon[]): string[] {
  const points = stops.map(project)
  const centreX = points.reduce((sum, point) => sum + point.x, 0) / points.length
  const centreY = points.reduce((sum, point) => sum + point.y, 0) / points.length

  return points.map((from, index) => {
    const to = points[(index + 1) % points.length]
    const midX = (from.x + to.x) / 2
    const midY = (from.y + to.y) / 2
    const normalX = to.y - from.y
    const normalY = from.x - to.x
    const outward = normalX * (midX - centreX) + normalY * (midY - centreY) >= 0 ? 1 : -1
    const controlX = midX + normalX * 0.16 * outward
    const controlY = midY + normalY * 0.16 * outward
    return `M${from.x.toFixed(1)} ${from.y.toFixed(1)} Q${controlX.toFixed(1)} ${controlY.toFixed(1)} ${to.x.toFixed(1)} ${to.y.toFixed(1)}`
  })
}
