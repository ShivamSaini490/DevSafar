import { ArrowUp } from 'lucide-react'
import { useEffect, useState, type FormEvent, type KeyboardEvent, type RefObject } from 'react'
import { PROMPT_EXAMPLES } from '../prompts.ts'

const MAX_LENGTH = 4000

function useTypedPlaceholder(active: boolean) {
  const [state, setState] = useState({ example: 0, length: PROMPT_EXAMPLES[0].length, deleting: false })

  useEffect(() => {
    if (!active || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const text = PROMPT_EXAMPLES[state.example]
    const finished = !state.deleting && state.length === text.length
    const timer = window.setTimeout(
      () => {
        setState((current) => {
          if (finished) return { ...current, deleting: true }
          if (current.deleting && current.length === 0) {
            return { example: (current.example + 1) % PROMPT_EXAMPLES.length, length: 0, deleting: false }
          }
          return { ...current, length: current.length + (current.deleting ? -1 : 1) }
        })
      },
      finished ? 2400 : state.deleting ? 18 : 42,
    )
    return () => window.clearTimeout(timer)
  }, [active, state])

  return PROMPT_EXAMPLES[state.example].slice(0, state.length)
}

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: (value: string) => void
  disabled?: boolean
  inputRef?: RefObject<HTMLTextAreaElement | null>
}

export function ChatInput({ value, onChange, onSubmit, disabled, inputRef }: ChatInputProps) {
  const placeholder = useTypedPlaceholder(value.length === 0)
  const canSend = value.trim().length > 0 && !disabled

  function submit() {
    if (!canSend) return
    onSubmit(value.trim())
    onChange('')
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    submit()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-end gap-2 rounded-2xl border border-line bg-paper p-2.5 text-ink-soft transition-colors focus-within:border-teal"
    >
      <textarea
        ref={inputRef}
        aria-label="Describe your trip"
        rows={2}
        maxLength={MAX_LENGTH}
        value={value}
        autoFocus
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        className="min-w-0 flex-1 resize-none bg-transparent px-2.5 py-1.5 text-base leading-snug outline-none placeholder:text-muted"
      />
      <button
        type="submit"
        disabled={!canSend}
        className="inline-flex h-11 shrink-0 items-center gap-1.5 rounded-xl bg-teal px-4 font-semibold text-white transition-colors hover:bg-teal-deep disabled:opacity-50"
      >
        Send
        <ArrowUp className="size-4" aria-hidden="true" />
      </button>
    </form>
  )
}
