// Lives in module memory on purpose: a refresh resets it, moving between pages does not.
let hasPlayed = false

export function shouldShowLoader() {
  return !hasPlayed && window.matchMedia('(prefers-reduced-motion: no-preference)').matches
}

export function markLoaderPlayed() {
  hasPlayed = true
}
