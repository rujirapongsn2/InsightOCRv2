import { AlertCircle, CheckCircle, Info, AlertTriangle, X } from "lucide-react"
import { ReactNode, useState } from "react"

type InfoCardType = "info" | "success" | "warning" | "error" | "tip"

interface InfoCardProps {
  type?: InfoCardType
  title?: string
  children: ReactNode
  dismissible?: boolean
  className?: string
}

const typeStyles: Record<InfoCardType, {
  bg: string
  border: string
  icon: ReactNode
  iconColor: string
}> = {
  info: {
    bg: "bg-blue-50",
    border: "border-blue-200",
    icon: <Info className="h-5 w-5" />,
    iconColor: "text-blue-600"
  },
  success: {
    bg: "bg-green-50",
    border: "border-green-200",
    icon: <CheckCircle className="h-5 w-5" />,
    iconColor: "text-green-600"
  },
  warning: {
    bg: "bg-yellow-50",
    border: "border-yellow-200",
    icon: <AlertTriangle className="h-5 w-5" />,
    iconColor: "text-yellow-600"
  },
  error: {
    bg: "bg-red-50",
    border: "border-red-200",
    icon: <AlertCircle className="h-5 w-5" />,
    iconColor: "text-red-600"
  },
  tip: {
    bg: "bg-purple-50",
    border: "border-purple-200",
    icon: <Info className="h-5 w-5" />,
    iconColor: "text-purple-600"
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
    <div className={`${style.bg} ${style.border} border rounded-lg p-4 ${className}`}>
      <div className="flex items-start gap-3">
        <div className={`${style.iconColor} flex-shrink-0 mt-0.5`}>
          {style.icon}
        </div>
        <div className="flex-1">
          {title && (
            <h3 className="font-medium text-slate-900 mb-1">{title}</h3>
          )}
          <div className="text-sm text-slate-700">
            {children}
          </div>
        </div>
        {dismissible && (
          <button
            onClick={() => setIsVisible(false)}
            className="text-slate-400 hover:text-slate-600 flex-shrink-0"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  )
}
