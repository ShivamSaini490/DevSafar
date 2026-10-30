import type { AuthResponse, LoginPayload, MessageResponse, SignupPayload, User } from '../types/auth.ts'
import { apiRequest } from './apiClient.ts'

export const authApi = {
  signup: (payload: SignupPayload) => apiRequest<User>('/api/v1/auth/signup', { method: 'POST', body: payload }),
  login: (payload: LoginPayload) => apiRequest<AuthResponse>('/api/v1/auth/login', { method: 'POST', body: payload }),
  logout: () => apiRequest<MessageResponse>('/api/v1/auth/logout', { method: 'POST' }),
  me: () => apiRequest<User>('/api/v1/users/me'),
}
