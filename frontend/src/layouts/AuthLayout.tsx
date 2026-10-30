import { motion } from 'framer-motion'
import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../components/common/Logo.tsx'

interface AuthLayoutProps {
  headline: string
  accent: string
  intro: ReactNode
  children: ReactNode
}

export function AuthLayout({ headline, accent, intro, children }: AuthLayoutProps) {
  return (
    <main className="flex min-h-svh flex-col bg-paper px-4 py-6 sm:px-8">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between">
        <Logo className="text-ink-soft" />
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-teal">
          <ArrowLeft className="size-4" aria-hidden="true" />
          Back to home
        </Link>
      </div>

      <div className="mx-auto mt-6 grid w-full max-w-6xl flex-1 gap-6 lg:grid-cols-2 lg:items-stretch">
        <motion.section
          initial={{ opacity: 0, x: -24 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6, ease: [0.2, 0.8, 0.2, 1] }}
          className="hidden flex-col justify-center rounded-3xl bg-mint p-12 lg:flex"
        >
          <h1 className="font-display text-5xl font-bold leading-tight tracking-tight text-ink-soft">
            {headline}
            <br />
            <span className="text-teal">{accent}</span>
          </h1>
          <div className="mt-6 text-lg text-muted">{intro}</div>
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1, ease: [0.2, 0.8, 0.2, 1] }}
          className="flex flex-col justify-center rounded-3xl bg-white p-6 sm:p-12"
        >
          {children}
        </motion.section>
      </div>
    </main>
  )
}
