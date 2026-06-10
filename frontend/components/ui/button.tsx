import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps
    extends React.ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link"
    size?: "default" | "sm" | "lg" | "icon"
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant = "default", size = "default", ...props }, ref) => {
        return (
            <button
                ref={ref}
                className={cn(
                    // Base — Softnix Cereal 500-weight, no all-caps
                    "inline-flex items-center justify-center whitespace-nowrap rounded-lg font-medium transition-all",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0D1B2A] focus-visible:ring-offset-2",
                    "disabled:pointer-events-none disabled:opacity-50",
                    "active:scale-[0.92]",
                    {
                        // Primary CTA — Softnix Blue
                        "bg-[#2786C2] text-white hover:bg-[#1A5A8A]": variant === "default",

                        // Destructive — Error Red
                        "bg-[#E53935] text-white hover:bg-[#B91C1C]": variant === "destructive",

                        // Outline / Secondary — white bg, Hairline Gray border
                        "border border-[#E2E8F0] bg-white text-[#0D1B2A] hover:bg-[#F8F9FA] hover:border-[#CBD5E1]": variant === "outline",

                        // Secondary pill — Off White bg
                        "bg-[#F8F9FA] text-[#0D1B2A] hover:bg-[#E2E8F0]": variant === "secondary",

                        // Ghost — no border
                        "text-[#0D1B2A] hover:bg-[#F8F9FA]": variant === "ghost",

                        // Link
                        "text-[#2786C2] underline-offset-4 hover:underline": variant === "link",

                        // Sizes
                        "h-10 px-6 py-2 text-sm":   size === "default",
                        "h-9 px-4 text-sm":          size === "sm",
                        "h-11 px-8 text-base":       size === "lg",
                        "h-10 w-10 rounded-full p-0": size === "icon",
                    },
                    className
                )}
                {...props}
            />
        )
    }
)
Button.displayName = "Button"

export { Button }
