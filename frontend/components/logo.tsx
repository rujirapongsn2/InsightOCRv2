import { cn } from "@/lib/utils"

interface LogoProps {
    className?: string
}

export function Logo({ className }: LogoProps) {
    return (
        <div className={cn("font-sans font-bold text-3xl text-slate-900 tracking-tight", className)}>
            Insight<span className="text-[#F3903F]">OCR</span>
        </div>
    )
}
