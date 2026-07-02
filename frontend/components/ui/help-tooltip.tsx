import { HelpCircle } from "lucide-react"
import { ReactNode } from "react"
import { Tooltip } from "@astryxdesign/core/Tooltip"
import { Button } from "@/components/ui/button"

interface HelpTooltipProps {
  content: string | ReactNode
  learnMoreUrl?: string
}

export function HelpTooltip({ content, learnMoreUrl }: HelpTooltipProps) {
  const tooltipContent = (
    <div className="max-w-64 space-y-2 text-sm">
      <div>{content}</div>
      {learnMoreUrl && (
        <a
          href={learnMoreUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[#B8DCEB] underline underline-offset-2"
        >
          Learn more
        </a>
      )}
    </div>
  )

  return (
    <Tooltip content={tooltipContent} placement="above" alignment="center" hasHoverIndication={false}>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-6 w-6 text-[#778DA9]"
        aria-label="Help"
      >
        <HelpCircle className="h-4 w-4" />
      </Button>
    </Tooltip>
  )
}
