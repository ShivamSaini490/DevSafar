import { Navigate } from 'react-router-dom'
import { SignInForm } from '../features/auth/components/SignInForm.tsx'
import { useAuth } from '../hooks/useAuth.ts'
import { AuthLayout } from '../layouts/AuthLayout.tsx'

const HIGHLIGHTS = ['Route intelligence', 'Budget visualizations', '7-day saved chats']

export function SignInPage() {
  const { user } = useAuth()
  if (user) return <Navigate to="/" replace />

  return (
    <AuthLayout
      headline="Plan smarter."
      accent="Travel further."
      intro={
        <>
          <p>Personalized routes, hotels and beautiful itineraries, all in one conversation.</p>
          <ul className="mt-8 flex max-w-xs flex-col gap-3">
            {HIGHLIGHTS.map((item) => (
              <li key={item} className="rounded-xl bg-white px-5 py-3 text-base text-ink-soft">
                {item}
              </li>
            ))}
          </ul>
        </>
      }
    >
      <SignInForm />
    </AuthLayout>
  )
}
