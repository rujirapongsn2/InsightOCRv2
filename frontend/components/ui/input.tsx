import * as React from "react"
import { cn } from "@/lib/utils"

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
    error?: boolean
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, type, error, ...props }, ref) => {
        return (
            <input
                type={type}
                className={cn(
                    // Base — Softnix text input style
                    "flex h-10 w-full rounded-lg border bg-white px-4 py-2",
                    "text-sm text-[#0D1B2A] font-medium",
                    "placeholder:text-[#9BA8B4] placeholder:font-normal",
                    "transition-colors",
                    // Normal border
                    "border-[#E2E8F0]",
                    // Focus — Ink Navy border + 2px outer ring
                    "focus-visible:outline-none focus-visible:border-[#0D1B2A] focus-visible:ring-2 focus-visible:ring-[#0D1B2A]/20",
                    // Error state
                    error && "border-[#E53935] focus-visible:ring-[#E53935]/20",
                    // Disabled
                    "disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-[#F8F9FA]",
                    className
                )}
                ref={ref}
                {...props}
            />
        )
    }
)
Input.displayName = "Input"

export { Input }
