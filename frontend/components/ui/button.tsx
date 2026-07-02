import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps
    extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
    variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link"
    size?: "default" | "sm" | "lg" | "icon"
    children?: React.ReactNode
}

const variantMap = {
    default: "bg-[#2786C2] text-white hover:bg-[#1A5A8A] shadow-sm",
    destructive: "bg-[#E53935] text-white hover:bg-[#B91C1C] shadow-sm",
    outline: "border border-[#E2E8F0] bg-white text-[#0D1B2A] hover:bg-[#F8F9FA]",
    secondary: "bg-[#F8F9FA] text-[#0D1B2A] hover:bg-[#E8EDF2]",
    ghost: "text-[#415A77] hover:bg-[#F8F9FA] hover:text-[#0D1B2A]",
    link: "h-auto px-0 py-0 text-[#2786C2] underline-offset-4 hover:underline",
} as const

const sizeMap = {
    default: "h-10 px-4 py-2 text-sm",
    sm: "h-8 px-3 text-xs",
    lg: "h-11 px-6 text-base",
    icon: "h-9 w-9 p-0",
} as const

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant = "default", size = "default", type = "button", ...props }, ref) => (
        <button
            ref={ref}
            type={type}
            className={cn(
                "inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-semibold transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2786C2] focus-visible:ring-offset-2",
                "disabled:pointer-events-none disabled:opacity-50",
                variantMap[variant],
                sizeMap[size],
                className
            )}
            {...props}
        />
    )
)
Button.displayName = "Button"

export { Button }
