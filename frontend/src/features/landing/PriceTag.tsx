import { CircleHelp, Radio, SquareFunction } from 'lucide-react'

const TAGS = {
  live_quote: { label: 'Live quote', icon: Radio, tone: 'border-teal text-teal-deep' },
  estimate: { label: 'Estimate', icon: SquareFunction, tone: 'border-chart-2 text-[#8a5210]' },
  unknown: { label: 'Unknown', icon: CircleHelp, tone: 'border-muted text-muted' },
}

export function PriceTag({ type }: { type: keyof typeof TAGS }) {
  const { label, icon: Icon, tone } = TAGS[type]
  return (
    <span className={`eyebrow inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 !text-[10px] ${tone}`}>
      <Icon className="size-3.5" aria-hidden="true" />
      {label}
    </span>
  )
}
