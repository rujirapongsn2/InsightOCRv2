import type { ReactNode } from "react"

/**
 * A soft colour glow around a document while the AI works on it. The centre
 * stays clear so the document remains readable; the glow never takes clicks.
 */
export function ThinkingGlow({ active, label, children }: { active: boolean; label?: string; children: ReactNode }) {
    return (
        <div className="thinking-glow" data-active={active || undefined}>
            {children}
            <div className="thinking-glow-cloud" aria-hidden="true">
                <i /><i /><i /><i /><i />
            </div>
            {active && <span className="thinking-glow-pulse" aria-hidden="true" />}
            {active && label && (
                <span role="status" className="thinking-glow-label">{label}</span>
            )}
        </div>
    )
}
