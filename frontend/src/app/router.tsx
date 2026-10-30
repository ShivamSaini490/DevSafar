import { createBrowserRouter } from 'react-router-dom'
import { ChatPage } from '../pages/ChatPage.tsx'
import { ForgotPasswordPage } from '../pages/ForgotPasswordPage.tsx'
import { LandingPage } from '../pages/LandingPage.tsx'
import { NotFoundPage } from '../pages/NotFoundPage.tsx'
import { SignInPage } from '../pages/SignInPage.tsx'
import { SignUpPage } from '../pages/SignUpPage.tsx'

export const router = createBrowserRouter([
  { path: '/', element: <LandingPage /> },
  { path: '/chat', element: <ChatPage /> },
  { path: '/login', element: <SignInPage /> },
  { path: '/signup', element: <SignUpPage /> },
  { path: '/forgot-password', element: <ForgotPasswordPage /> },
  { path: '*', element: <NotFoundPage /> },
])
