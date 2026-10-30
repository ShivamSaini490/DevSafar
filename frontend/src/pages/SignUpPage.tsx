import { Navigate } from 'react-router-dom'
import { SignUpForm } from '../features/auth/components/SignUpForm.tsx'
import { useAuth } from '../hooks/useAuth.ts'
import { AuthLayout } from '../layouts/AuthLayout.tsx'

export function SignUpPage() {
  const { user } = useAuth()
  if (user) return <Navigate to="/" replace />

  return (
    <AuthLayout
      headline="Your next adventure"
      accent="starts here."
      intro={
        <>
          <p>No account is needed for temporary chats.</p>
          <p className="mt-2">An account unlocks 7-day chat history.</p>
        </>
      }
    >
      <SignUpForm />
    </AuthLayout>
  )
}
