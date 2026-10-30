export interface User {
  id: string
  name: string
  email: string
  created_at: string
  updated_at: string
}

export interface AuthResponse {
  user: User
}

export interface LoginPayload {
  email: string
  password: string
}

export interface SignupPayload extends LoginPayload {
  name: string
  confirm_password: string
}

export interface MessageResponse {
  message: string
}
