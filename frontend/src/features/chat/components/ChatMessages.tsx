import { motion } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { PlannerMessage, TripSummary } from '../../../types/chat.ts'

function tripStatusLabel(trip: TripSummary): string {
  if (trip.status === 'needs_clarification') return 'Needs a detail from you'
  if (trip.status === 'failed') return 'Could not finish this plan'
  if (trip.feasible === true) return 'Passed the feasibility checks'
  if (trip.feasible === false) return 'Not feasible as requested'
  return 'Feasibility not confirmed'
}

function Message({ message }: { message: PlannerMessage }) {
  if (message.role === 'user') {
    return <p className="ml-10 self-end whitespace-pre-wrap rounded-2xl rounded-br-md bg-teal px-4 py-2.5 text-white">{message.content}</p>
  }

  return (
    <div className="mr-6 flex flex-col gap-2">
      <p className="whitespace-pre-wrap rounded-2xl rounded-bl-md bg-paper px-4 py-2.5 text-ink-soft">{message.content}</p>
      {message.trip && (
        <>
          <p className="eyebrow !text-[11px] text-teal">{tripStatusLabel(message.trip)}</p>
          {message.trip.warnings.map((warning) => (
            <p key={warning} className="flex gap-2 rounded-xl bg-amber/20 px-3 py-2 text-sm text-ink-soft">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {warning}
            </p>
          ))}
        </>
      )}
    </div>
  )
}

interface ChatMessagesProps {
  messages: PlannerMessage[]
  isSending: boolean
  error: string | null
}

export function ChatMessages({ messages, isSending, error }: ChatMessagesProps) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, isSending, error])

  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      {messages.map((message) => (
        <Message key={message.id} message={message} />
      ))}

      {isSending && (
        <div className="mr-6 rounded-2xl rounded-bl-md bg-paper px-4 py-3">
          <div className="h-1 overflow-hidden rounded-full bg-line">
            <motion.div
              className="h-full w-1/3 rounded-full bg-teal"
              animate={{ x: ['-100%', '320%'] }}
              transition={{ duration: 1.4, repeat: Infinity, ease: 'easeInOut' }}
            />
          </div>
          <p className="mt-2 text-sm text-muted">Researching, planning and validating your trip. This can take up to a minute.</p>
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
        </p>
      )}
      <div ref={endRef} />
    </div>
  )
}
