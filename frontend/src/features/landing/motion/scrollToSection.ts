export function scrollToSection(id: string) {
  const target = document.getElementById(id)
  if (!target) return
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  window.scrollTo({
    top: target.getBoundingClientRect().top + window.scrollY,
    behavior: reduceMotion ? 'auto' : 'smooth',
  })
}
