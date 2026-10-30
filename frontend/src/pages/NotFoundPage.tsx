import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center bg-ink px-6 text-center text-white">
      <p className="eyebrow text-teal-bright">404</p>
      <h1 className="mt-4 font-display text-5xl font-bold tracking-tight">This route doesn't exist.</h1>
      <Link to="/" className="mt-8 rounded-xl bg-teal px-5 py-3 font-semibold hover:bg-teal-deep">
        Back to home
      </Link>
    </main>
  )
}
