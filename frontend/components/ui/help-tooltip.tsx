import { HelpCircle } from "lucide-react"
import { ReactNode } from "react"

interface HelpTooltipProps {
  content: string | ReactNode
  learnMoreUrl?: string
}

export function HelpTooltip({ content, learnMoreUrl }: HelpTooltipProps) {
  return (
    <div className="group relative inline-block">
      <HelpCircle className="h-4 w-4 text-slate-400 hover:text-slate-600 cursor-help" />
      <div className="invisible group-hover:visible absolute z-50 w-64 p-3 mt-1 text-sm bg-slate-900 text-white rounded-lg shadow-lg -left-28">
        <div className="space-y-2">
          <div>{content}</div>
          {learnMoreUrl && (
            <a
              href={learnMoreUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-300 hover:text-blue-200 underline text-xs"
            >
              Learn more →
            </a>
          )}
        </div>
        {/* Arrow */}
        <div className="absolute -top-1 left-1/2 transform -translate-x-1/2">
          <div className="w-2 h-2 bg-slate-900 rotate-45"></div>
        </div>
      </div>
    </div>
  )
}
