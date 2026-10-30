import { ArrowLeft } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../components/common/Logo.tsx'
import { ChatInput } from '../features/chat/components/ChatInput.tsx'
import { ChatMessages } from '../features/chat/components/ChatMessages.tsx'
import { ChatWelcome } from '../features/chat/components/ChatWelcome.tsx'
import { TemporaryChatBanner } from '../features/temporary-chat/TemporaryChatBanner.tsx'
import { useTemporaryChat } from '../features/temporary-chat/useTemporaryChat.ts'
import { useAuth } from '../hooks/useAuth.ts'

/** Temporary chat is the only mode so far. Saved chats and the sidebar arrive with their own module. */
export function ChatPage() {
  const { user } = useAuth()
  const { messages, isSending, error, send } = useTemporaryChat()
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const isEmpty = messages.length === 0 && !error

  return (
    <div className="flex h-svh flex-col bg-white text-ink-soft">
      <header className="flex h-16 shrink-0 items-center justify-between gap-4 border-b border-line px-4 sm:px-8">
        <Logo className="text-ink-soft" />
        <nav aria-label="Chat" className="flex items-center gap-1.5 text-sm font-semibold">
          <Link to="/" className="inline-flex h-10 items-center gap-1.5 rounded-xl px-3 text-muted hover:text-teal">
            <ArrowLeft className="size-4" aria-hidden="true" />
            Home
          </Link>
          {!user && (
            <Link to="/signup" className="inline-flex h-10 items-center rounded-xl bg-teal px-4 text-white hover:bg-teal-deep">
              Sign up
            </Link>
          )}
        </nav>
      </header>

      <TemporaryChatBanner />

      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-6">
          {isEmpty ? (
            <ChatWelcome
              onPick={(prompt) => {
                setDraft(prompt)
                inputRef.current?.focus()
              }}
            />
          ) : (
            <ChatMessages messages={messages} isSending={isSending} error={error} />
          )}
        </div>
      </main>

      <div className="shrink-0 border-t border-line">
        <div className="mx-auto w-full max-w-3xl p-4">
          <ChatInput value={draft} onChange={setDraft} onSubmit={(text) => void send(text)} disabled={isSending} inputRef={inputRef} />
        </div>
      </div>
    </div>
  )
}
