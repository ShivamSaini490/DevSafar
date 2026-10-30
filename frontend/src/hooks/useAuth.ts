import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, hasSessionHint } from '../services/apiClient.ts'
import { authApi } from '../services/authApi.ts'
import type { LoginPayload, SignupPayload, User } from '../types/auth.ts'

const ME_KEY = ['me']

async function fetchMe(): Promise<User | null> {
  try {
    return await authApi.me()
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null
    }
    throw error
  }
}

export function useAuth() {
  const queryClient = useQueryClient()

  // Guests have no CSRF cookie, so they never trigger a 401 on the landing page.
  const me = useQuery({ queryKey: ME_KEY, queryFn: fetchMe, enabled: hasSessionHint(), staleTime: 60_000 })

  const login = useMutation({
    mutationFn: (payload: LoginPayload) => authApi.login(payload),
    onSuccess: ({ user }) => queryClient.setQueryData(ME_KEY, user),
  })

  // Signup sets no cookie on the backend, so a new account signs in straight after.
  const signup = useMutation({
    mutationFn: async (payload: SignupPayload) => {
      await authApi.signup(payload)
      return authApi.login({ email: payload.email, password: payload.password })
    },
    onSuccess: ({ user }) => queryClient.setQueryData(ME_KEY, user),
  })

  const logout = useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => queryClient.setQueryData(ME_KEY, null),
  })

  return { user: me.data ?? null, login, signup, logout }
}
