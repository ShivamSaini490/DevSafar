import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../../components/ui/Button.tsx'
import { Input } from '../../../components/ui/Input.tsx'
import { useAuth } from '../../../hooks/useAuth.ts'
import { CHAT_ROUTE } from '../../chat/prompts.ts'

export function SignInForm() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    login.mutate({ email, password }, { onSuccess: () => navigate('/') })
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <h2 className="mb-2 font-display text-3xl font-bold tracking-tight text-ink-soft">Welcome back</h2>

      <Input
        label="Email"
        type="email"
        autoComplete="email"
        placeholder="you@example.com"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <div>
        <Input
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <div className="mt-1.5 text-right">
          <Link to="/forgot-password" className="text-sm text-teal hover:underline">
            Forgot password?
          </Link>
        </div>
      </div>

      {login.error && (
        <p role="alert" className="text-sm text-red-700">
          {login.error.message}
        </p>
      )}

      <Button type="submit" disabled={login.isPending}>
        {login.isPending ? 'Signing in...' : 'Sign In'}
      </Button>

      <p className="text-sm text-muted">
        No account?{' '}
        <Link to="/signup" className="font-medium text-teal hover:underline">
          Sign up
        </Link>
        <span className="mx-3" aria-hidden="true">
          |
        </span>
        <Link to={CHAT_ROUTE} className="font-medium text-teal hover:underline">
          Continue as Guest
        </Link>
      </p>
    </form>
  )
}
