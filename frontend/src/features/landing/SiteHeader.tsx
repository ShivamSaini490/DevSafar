import { AnimatePresence, motion, useMotionValueEvent, useScroll } from 'framer-motion'
import { LogOut, Menu, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../../components/common/Logo.tsx'
import { useAuth } from '../../hooks/useAuth.ts'
import { NAV_LINKS } from './content.ts'
import { Magnetic } from './motion/Magnetic.tsx'
import { scrollToSection } from './motion/scrollToSection.ts'

export function SiteHeader() {
  const { user, logout } = useAuth()
  const { scrollY } = useScroll()
  const [isScrolled, setIsScrolled] = useState(false)
  const [isMenuOpen, setIsMenuOpen] = useState(false)

  useMotionValueEvent(scrollY, 'change', (y) => setIsScrolled(y > 40))

  function goTo(id: string) {
    setIsMenuOpen(false)
    scrollToSection(id)
  }

  const account = user ? (
    <>
      <span className="max-w-36 truncate text-sm text-white/80">{user.name}</span>
      <button
        type="button"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
        className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-white/20 px-3.5 text-sm font-semibold text-white hover:bg-white/10"
      >
        <LogOut className="size-4" aria-hidden="true" />
        Log out
      </button>
    </>
  ) : (
    <>
      <Link to="/login" className="inline-flex h-10 items-center rounded-xl px-3.5 text-sm font-semibold text-white hover:bg-white/10">
        Log in
      </Link>
      <Magnetic>
        <Link to="/signup" className="inline-flex h-10 items-center rounded-xl bg-teal px-4 text-sm font-semibold text-white hover:bg-teal-deep">
          Sign up
        </Link>
      </Magnetic>
    </>
  )

  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-40 flex justify-center px-4 pt-3 sm:px-8">
      <motion.div
        layout
        transition={{ type: 'spring', stiffness: 240, damping: 30 }}
        className={`pointer-events-auto w-full rounded-2xl border transition-colors duration-300 ${
          isScrolled ? 'max-w-5xl border-white/12 bg-ink/95 px-4 shadow-xl shadow-ink/20 backdrop-blur-xl' : 'max-w-7xl border-transparent'
        }`}
      >
        <div className="flex h-14 items-center justify-between gap-4">
          <Logo className="text-white" />

          <nav aria-label="Main" className="hidden items-center gap-1 lg:flex">
            {NAV_LINKS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => goTo(id)}
                className="rounded-lg px-3 py-2 text-sm font-medium text-white/75 transition-colors hover:text-white"
              >
                {label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-1.5">
            <div className="hidden items-center gap-1.5 sm:flex">{account}</div>
            <button
              type="button"
              onClick={() => setIsMenuOpen((open) => !open)}
              aria-label={isMenuOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={isMenuOpen}
              className="rounded-lg p-2 text-white lg:hidden"
            >
              {isMenuOpen ? <X className="size-5" aria-hidden="true" /> : <Menu className="size-5" aria-hidden="true" />}
            </button>
          </div>
        </div>

        <AnimatePresence>
          {isMenuOpen && (
            <motion.nav
              aria-label="Mobile"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden lg:hidden"
            >
              <div className="flex flex-col gap-1 border-t border-white/12 py-3">
                {NAV_LINKS.map(({ id, label }) => (
                  <button key={id} type="button" onClick={() => goTo(id)} className="rounded-lg px-2 py-2.5 text-left font-medium text-white/85">
                    {label}
                  </button>
                ))}
                <div className="mt-2 flex items-center gap-1.5 sm:hidden">{account}</div>
              </div>
            </motion.nav>
          )}
        </AnimatePresence>
      </motion.div>
    </header>
  )
}
