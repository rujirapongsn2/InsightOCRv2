"use client"

import { Loader2, Cpu } from "lucide-react"

interface ThinkingIndicatorProps {
    iteration?: number | null
    /** Show in compact mode (e.g. inside header) */
    compact?: boolean
}

export default function ThinkingIndicator({ iteration, compact = false }: ThinkingIndicatorProps) {
    if (compact) {
        return (
            <span className="text-xs text-[#AED6F1] flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                Thinking{iteration ? ` (${iteration})` : ""}...
            </span>
        )
    }

    return (
        <div className="flex items-start gap-3 px-3 py-2 animate-in fade-in slide-in-from-bottom-2">
            <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[#D6EAF8] flex items-center justify-center mt-0.5">
                <Cpu className="h-3.5 w-3.5 text-[#5EADD6] animate-pulse" />
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xs font-medium text-softnix-blue">Agent is thinking</span>
                    {iteration && (
                        <span className="text-[10px] text-[#5EADD6] bg-[#EBF4FB] rounded-full px-2 py-0.5 font-mono">
                            iteration {iteration}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-1.5">
                    <span
                        className="w-2 h-2 rounded-full bg-[#5EADD6] animate-bounce"
                        style={{ animationDelay: "0ms" }}
                    />
                    <span
                        className="w-2 h-2 rounded-full bg-[#5EADD6] animate-bounce"
                        style={{ animationDelay: "150ms" }}
                    />
                    <span
                        className="w-2 h-2 rounded-full bg-[#5EADD6] animate-bounce"
                        style={{ animationDelay: "300ms" }}
                    />
                    <span className="text-[11px] text-[#5EADD6] ml-1">analyzing context, planning actions...</span>
                </div>
            </div>
        </div>
    )
}
