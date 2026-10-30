import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../../components/ui/Button.tsx'
import { Input } from '../../../components/ui/Input.tsx'
import { useAuth } from '../../../hooks/useAuth.ts'
import { ApiError } from '../../../services/apiClient.ts'

/** The backend hides validator messages, so name the field it reported instead. */
function describeSignupError(error: Error): string {
  if (error instanceof ApiError && error.code === 'validation_error') {
    const location = error.details?.[0]?.location ?? ''
    if (location.includes('password')) return 'That password is too common. Please choose a stronger one.'
    if (location.includes('email')) return 'Please enter a valid email address.'
  }
  return error.message
}

export function SignUpForm() {
  const navigate = useNavigate()
  const { signup } = useAuth()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showErrors, setShowErrors] = useState(false)

  const passwordError = password.length < 8 ? 'Use at least 8 characters.' : undefined
  const confirmError = password !== confirmPassword ? 'Passwords do not match.' : undefined

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setShowErrors(true)
    if (passwordError || confirmError) return
    signup.mutate(
      { name, email, password, confirm_password: confirmPassword },
      { onSuccess: () => navigate('/') },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <h2 className="mb-2 font-display text-3xl font-bold tracking-tight text-ink-soft">Create account</h2>

      <Input
        label="Full Name"
        autoComplete="name"
        placeholder="Your name"
        required
        maxLength={100}
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <Input
        label="Email"
        type="email"
        autoComplete="email"
        placeholder="you@example.com"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Input
        label="Password"
        type="password"
        autoComplete="new-password"
        placeholder="At least 8 characters"
        required
        maxLength={128}
        value={password}
        error={showErrors ? passwordError : undefined}
        onChange={(event) => setPassword(event.target.value)}
      />
      <Input
        label="Confirm Password"
        type="password"
        autoComplete="new-password"
        required
        maxLength={128}
        value={confirmPassword}
        error={showErrors ? confirmError : undefined}
        onChange={(event) => setConfirmPassword(event.target.value)}
      />

      {signup.error && (
        <p role="alert" className="text-sm text-red-700">
          {describeSignupError(signup.error)}
        </p>
      )}

      <Button type="submit" disabled={signup.isPending}>
        {signup.isPending ? 'Creating account...' : 'Create Account'}
      </Button>

      <p className="text-sm text-muted">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-teal hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  )
}
