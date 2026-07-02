import { AlertCircle, CheckCircle, Info, AlertTriangle, X } from "lucide-react"
import { ReactNode, useState } from "react"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type InfoCardType = "info" | "success" | "warning" | "error" | "tip"

interface InfoCardProps {
  type?: InfoCardType
  title?: string
  children: ReactNode
  dismissible?: boolean
  className?: string
}

const typeStyles: Record<InfoCardType, {
  card: string
  badgeVariant: React.ComponentProps<typeof Badge>["variant"]
  badgeLabel: string
  icon: ReactNode
  iconColor: string
}> = {
  info: {
    card: "border-[#B8DCEB] bg-[#F4FBFE]",
    badgeVariant: "info",
    badgeLabel: "Info",
    icon: <Info className="h-5 w-5" />,
    iconColor: "text-[#2786C2]"
  },
  success: {
    card: "border-emerald-200 bg-emerald-50",
    badgeVariant: "success",
    badgeLabel: "Success",
    icon: <CheckCircle className="h-5 w-5" />,
    iconColor: "text-emerald-600"
  },
  warning: {
    card: "border-amber-200 bg-amber-50",
    badgeVariant: "warning",
    badgeLabel: "Warning",
    icon: <AlertTriangle className="h-5 w-5" />,
    iconColor: "text-amber-600"
  },
  error: {
    card: "border-red-200 bg-red-50",
    badgeVariant: "destructive",
    badgeLabel: "Error",
    icon: <AlertCircle className="h-5 w-5" />,
    iconColor: "text-red-600"
  },
  tip: {
    card: "border-violet-200 bg-violet-50",
    badgeVariant: "info",
    badgeLabel: "Tip",
    icon: <Info className="h-5 w-5" />,
    iconColor: "text-violet-600"
  }
}

export function InfoCard({
  type = "info",
  title,
  children,
  dismissible = false,
  className = ""
}: InfoCardProps) {
  const [isVisible, setIsVisible] = useState(true)
  const style = typeStyles[type]

  if (!isVisible) return null

  return (
    <Card className={cn("border p-4", style.card, className)}>
      <div className="flex items-start gap-3">
        <div className={`${style.iconColor} flex-shrink-0 mt-0.5`}>
          {style.icon}
        </div>
        <div className="flex-1">
          {title && (
            <div className="mb-2 flex items-center gap-2">
              <Badge variant={style.badgeVariant}>{style.badgeLabel}</Badge>
              <h3 className="font-medium text-[#0D1B2A]">{title}</h3>
            </div>
          )}
          <div className="text-sm text-[#415A77]">
            {children}
          </div>
        </div>
        {dismissible && (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsVisible(false)}
            className="h-8 w-8 flex-shrink-0"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>
    </Card>
  )
}
