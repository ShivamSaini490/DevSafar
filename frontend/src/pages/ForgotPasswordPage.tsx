import { Link } from 'react-router-dom'
import { AuthLayout } from '../layouts/AuthLayout.tsx'

/** Placeholder until the password recovery module (email, 6-digit OTP, new password) is built. */
export function ForgotPasswordPage() {
  return (
    <AuthLayout headline="Forgot your" accent="password?" intro={<p>Recovery uses a 6-digit code sent by email.</p>}>
      <h2 className="font-display text-3xl font-bold tracking-tight text-ink-soft">Not available yet</h2>
      <p className="mt-3 text-muted">The password recovery screens are still being built.</p>
      <Link to="/login" className="mt-6 font-medium text-teal hover:underline">
        Back to Sign In
      </Link>
    </AuthLayout>
  )
}
