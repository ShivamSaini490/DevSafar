import { useCallback, useRef, useState } from 'react'
import { ApiError } from '../../services/apiClient.ts'
import { chatApi } from '../../services/chatApi.ts'
import type { PlannerMessage } from '../../types/chat.ts'

function createTempSessionId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** Temporary chat lives in React memory only. Never move this state to localStorage or a persisted store. */
export function useTemporaryChat() {
  const sessionId = useRef<string | null>(null)
  const token = useRef<string | null>(null)
  const [messages, setMessages] = useState<PlannerMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = useCallback(async (content: string) => {
    sessionId.current ??= createTempSessionId()
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'user', content }])
    setError(null)
    setIsSending(true)

    try {
      const response = await chatApi.sendTemporaryMessage({
        temp_session_id: sessionId.current,
        temp_token: token.current,
        content,
      })
      token.current = response.temp_token ?? token.current
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'assistant', content: response.assistant_message, trip: response.trip },
      ])
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'temporary_chat_not_found') {
        // The short server TTL ran out, so the next message starts a fresh temporary chat.
        sessionId.current = null
        token.current = null
        setError('This temporary chat expired on the server. Send your message again to start a new one.')
      } else {
        setError(caught instanceof Error ? caught.message : 'Something went wrong. Please try again.')
      }
    } finally {
      setIsSending(false)
    }
  }, [])

  return { messages, isSending, error, send }
}
