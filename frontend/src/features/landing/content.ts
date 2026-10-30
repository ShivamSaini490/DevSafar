/**
 * Landing page copy. Facts come from /docs and the frontend blueprint.
 * Every rupee figure here is the blueprint's sample data, always shown with a sample label.
 */

import { TOURIST_CITIES, type TripRoute } from './geo.ts'

export const SECTIONS = [
  { id: 'top', label: 'Start' },
  { id: 'how-it-works', label: 'One sentence' },
  { id: 'agents', label: 'Five steps' },
  { id: 'trip-view', label: 'Your trip' },
  { id: 'prices', label: 'Honest prices' },
  { id: 'chats', label: 'Your chats' },
  { id: 'faq', label: 'Questions' },
] as const

export const LOADER_WORDS = [
  { text: 'Har', isAccent: false },
  { text: 'safar,', isAccent: false },
  { text: 'smart', isAccent: true },
  { text: 'safar', isAccent: true },
]

export const NAV_LINKS = [
  { id: 'how-it-works', label: 'How it works' },
  { id: 'trip-view', label: 'Trip view' },
  { id: 'prices', label: 'Honest prices' },
  { id: 'chats', label: 'Your chats' },
  { id: 'faq', label: 'FAQ' },
] as const

/** A sample request for this page load, split so each token can fly to its boarding pass field. */
export function buildSentence([from, stopOne, stopTwo]: TripRoute): { text: string; field?: number }[] {
  return [
    { text: 'I want to go from ' },
    { text: from.name, field: 0 },
    { text: ' to ' },
    { text: stopOne.name, field: 1 },
    { text: ' and ' },
    { text: stopTwo.name, field: 2 },
    { text: ' in ' },
    { text: '3 days', field: 3 },
    { text: ' on a ' },
    { text: '₹15,000', field: 4 },
    { text: ' budget, and be back at the office before ' },
    { text: 'Monday 10 AM', field: 5 },
    { text: '.' },
  ]
}

export function buildTicketFields([from, stopOne, stopTwo]: TripRoute) {
  return [
    { label: 'From', value: from.name },
    { label: 'Stop 1', value: stopOne.name },
    { label: 'Stop 2', value: stopTwo.name },
    { label: 'Days', value: '3' },
    { label: 'Budget', value: '₹15,000' },
    { label: 'Back by', value: 'Mon, 10:00' },
  ]
}

export const AGENT_STEPS = [
  {
    name: 'Intent',
    title: 'Understands the ask',
    body: 'Extracts origin, destinations, dates, budget, passengers and your return deadline.',
    owner: 'LLM',
  },
  {
    name: 'Research',
    title: 'Checks what exists',
    body: 'Queries the available maps, transport, hotel and attraction tools, plus curated travel knowledge.',
    owner: 'Providers + RAG',
  },
  {
    name: 'Planning',
    title: 'Builds the options',
    body: 'Compares candidate routes, travel durations, stays and total costs across every order of your cities.',
    owner: 'Python',
  },
  {
    name: 'Validation',
    title: 'Tries to break it',
    body: 'Checks schedule feasibility, your office deadline, the budget and how fresh each source is.',
    owner: 'Python',
  },
  {
    name: 'Response',
    title: 'Hands you the trip',
    body: 'Returns typed data for the itinerary, cards, map, charts and booking links, then explains it plainly.',
    owner: 'LLM + typed JSON',
  },
]

export const FAILURE_PATHS = [
  { when: 'A critical detail is missing', then: 'It asks you one question.' },
  { when: 'Your dates are invalid', then: 'It asks you to clarify.' },
  { when: 'The plan fails a check', then: 'It retries with bounded alternatives.' },
  { when: 'It still cannot work', then: 'It explains why and offers safer choices.' },
]

export function buildSampleDays([, stopOne, stopTwo]: TripRoute) {
  return [
    { day: 'Day 1', place: stopOne.name, plan: 'Arrival / Explore / Stay' },
    { day: 'Day 2', place: stopTwo.name, plan: 'Transfer / Explore / Stay' },
    { day: 'Day 3', place: 'Return journey', plan: 'Travel / Deadline check' },
  ]
}

export const SAMPLE_TRANSPORT = [
  { mode: 'Train', amount: 1200 },
  { mode: 'Bus', amount: 1800 },
  { mode: 'Flight', amount: 5500 },
  { mode: 'Cab', amount: 8500 },
]

export const SAMPLE_BUDGET = [
  { name: 'Transport', amount: 6000, color: 'var(--color-chart-1)' },
  { name: 'Hotels', amount: 4000, color: 'var(--color-chart-2)' },
  { name: 'Food', amount: 2000, color: 'var(--color-chart-3)' },
  { name: 'Attractions', amount: 1500, color: 'var(--color-chart-4)' },
  { name: 'Buffer', amount: 1500, color: 'var(--color-chart-5)' },
]

export function buildSampleHotels([, stopOne, stopTwo]: TripRoute) {
  return [
    { area: `Stay in ${stopOne.name}`, note: 'Name, rating and rate appear once a hotel provider returns them.' },
    { area: `Stay in ${stopTwo.name}`, note: 'Booking opens on the provider site. DevSafar never takes payment.' },
  ]
}

export function buildSamplePlaces([, stopOne, stopTwo]: TripRoute) {
  return [stopOne, stopTwo].flatMap((city) => city.places.map((name) => ({ name, city: city.name })))
}

export const PRICE_STATES = [
  {
    type: 'live_quote' as const,
    item: 'Flight',
    amount: '₹5,500',
    body: 'Returned by a provider API, with the provider and the time it was fetched.',
    source: 'Provider name',
  },
  {
    type: 'estimate' as const,
    item: 'Train',
    amount: '₹1,200',
    body: 'A calculated figure. Useful for planning, never presented as a fare you can book.',
    source: 'Calculation method',
  },
  {
    type: 'unknown' as const,
    item: 'Hotel',
    amount: 'Not known',
    body: 'No trustworthy source. The value stays empty and the budget total says so.',
    source: 'None available',
  },
]

export const WONT_PRETEND = [
  'No fake seats, fares, rooms or crowd counts.',
  'A booking link is a redirect, not a confirmed booking.',
  'Payment and passenger details stay with the provider.',
  'Nothing is called live unless it was actually verified.',
]

export const CHAT_MODES = [
  {
    name: 'Temporary chat',
    who: 'Guest or signed in',
    points: [
      'Never appears in chat history',
      'Clears from the tab when closed',
      'Server processing data expires via TTL',
      'No account needed',
    ],
  },
  {
    name: 'Saved chat',
    who: 'Signed in',
    points: [
      'Shows in your sidebar until expiry',
      'Reopen and keep planning',
      'Stored against your account only',
      'Fixed 7 days from creation',
    ],
  },
]

export const FAQS = [
  {
    q: 'Do I need an account?',
    a: 'No. Open DevSafar and start a temporary chat as a guest. An account only adds saved chats you can reopen for up to seven days.',
  },
  {
    q: 'Are the prices live?',
    a: 'Only where a provider API supplies them. Every price is labelled live quote, estimate or unknown, with its source and fetch time. If there is no source, it stays unknown.',
  },
  {
    q: 'Does DevSafar book tickets for me?',
    a: 'No. It sends you to the provider’s booking page. Booking, payment and passenger details happen there, and a redirect is not a confirmed booking.',
  },
  {
    q: 'What if my trip isn’t possible?',
    a: 'You get a clear warning and alternatives instead of a pretty plan that fails. Dates, budgets and deadlines are checked in code, not guessed by the AI.',
  },
  {
    q: 'Can I change the plan after it’s made?',
    a: 'Yes, just keep talking. Ask something like “Make it cheaper” and the plan updates in the same conversation.',
  },
  {
    q: 'How long are my chats kept?',
    a: 'Saved chats expire seven days after they were created, and new messages don’t extend that. Temporary chats never enter your history and clear when you close the tab.',
  },
  {
    q: 'Can I share a chat?',
    a: 'No. DevSafar has no share-chat feature.',
  },
  {
    q: 'What if I forget my password?',
    a: 'You enter your email and receive a 6-digit code. It expires after five minutes, attempts are limited, and there are no reset links.',
  },
]

export const MARQUEE_STOPS = TOURIST_CITIES.map((city) => city.name)
