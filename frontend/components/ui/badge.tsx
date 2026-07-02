import * as React from "react"
import {
    Badge as AstryxBadge,
    type BadgeVariant,
} from "@astryxdesign/core/Badge"
import { cn } from "@/lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
    variant?: "default" | "secondary" | "success" | "warning" | "destructive" | "info"
    children?: React.ReactNode
}

const variantMap = {
    default: "neutral",
    secondary: "neutral",
    success: "success",
    warning: "warning",
    destructive: "error",
    info: "info",
} as const satisfies Record<NonNullable<BadgeProps["variant"]>, BadgeVariant>

function getTextContent(node: React.ReactNode): string {
    if (typeof node === "string" || typeof node === "number") return String(node)
    if (Array.isArray(node)) return node.map(getTextContent).join(" ").trim()
    if (React.isValidElement<{ children?: React.ReactNode }>(node)) {
        return getTextContent(node.props.children)
    }
    return ""
}

const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
    ({ className, variant = "default", children, ...props }, ref) => (
        <AstryxBadge
            ref={ref}
            variant={variantMap[variant]}
            label={children ?? (getTextContent(children) || "Badge")}
            className={cn("align-middle", className)}
            {...props}
        />
    )
)
Badge.displayName = "Badge"

export { Badge }
