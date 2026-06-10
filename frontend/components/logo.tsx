import { cn } from "@/lib/utils"

interface LogoProps {
    className?: string
}

export function Logo({ className }: LogoProps) {
    return (
        <div className={cn("font-bold tracking-tight select-none text-2xl", className)}>
            <span className="text-[#0D1B2A]">Insight</span>
            {/* Layer 2 Orange — GenAI/document product tier color */}
            <span style={{ color: "#F3903F" }}>DOC</span>
        </div>
    )
}
