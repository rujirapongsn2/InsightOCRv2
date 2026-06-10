"use client"

import { Bot, User, Globe, Trash2, Download, Edit3, Zap, FileCode } from "lucide-react"

interface Skill {
    id: string
    name: string
    scope: string
    description: string
    procedure: string
    trigger_hint?: string | null
    tools_used?: string[] | null
    allowed_tools?: string | null
    success_count: number
    created_by: string
    source: string
    version?: string | null
    file_path?: string | null
    created_at?: string | null
    updated_at?: string | null
}

interface SkillCardProps {
    skill: Skill
    onEdit: (skill: Skill) => void
    onDelete: (skill: Skill) => void
    onExport: (skill: Skill) => void
    compact?: boolean
}

const SCOPE_ICONS: Record<string, string> = {
    user: "👤",
    system: "🌐",
}

export default function SkillCard({ skill, onEdit, onDelete, onExport, compact }: SkillCardProps) {
    const scopeIcon = SCOPE_ICONS[skill.scope] || "📦"
    const isSystem = skill.scope === "system"

    if (compact) {
        return (
            <div className="rounded-lg border border-hairline bg-white p-2.5 hover:border-softnix-blue transition-colors">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                        <span className="text-sm">{scopeIcon}</span>
                        <code className="text-xs font-mono text-softnix-deep truncate">{skill.name}</code>
                        <span className="text-[10px] text-mute-gray bg-off-white rounded px-1.5 py-0.5">
                            {skill.success_count || 0} uses
                        </span>
                    </div>
                </div>
                <p className="text-xs text-slate-gray mt-1 line-clamp-1">{skill.description}</p>
            </div>
        )
    }

    return (
        <div className="rounded-xl border border-hairline bg-white p-4 hover:shadow-md transition-shadow">
            {/* Header */}
            <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="text-lg">{scopeIcon}</span>
                    <code className="text-sm font-mono font-semibold text-softnix-deep truncate">{skill.name}</code>
                    {isSystem && (
                        <span className="text-[10px] bg-[#D6EAF8] text-softnix-blue rounded-full px-2 py-0.5 font-medium">
                            System
                        </span>
                    )}
                    {skill.source === "imported" && (
                        <span className="text-[10px] bg-amber-100 text-amber-700 rounded-full px-2 py-0.5 font-medium">
                            Imported
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                    <button
                        onClick={() => onEdit(skill)}
                        className="p-1 text-mute-gray hover:text-softnix-blue rounded"
                        title="Edit"
                    >
                        <Edit3 className="h-3.5 w-3.5" />
                    </button>
                    <button
                        onClick={() => onExport(skill)}
                        className="p-1 text-mute-gray hover:text-emerald-600 rounded"
                        title="Export SKILL.md"
                    >
                        <Download className="h-3.5 w-3.5" />
                    </button>
                    {!isSystem && (
                        <button
                            onClick={() => onDelete(skill)}
                            className="p-1 text-mute-gray hover:text-red-500 rounded"
                            title="Delete"
                        >
                            <Trash2 className="h-3.5 w-3.5" />
                        </button>
                    )}
                </div>
            </div>

            {/* Description */}
            <p className="text-sm text-charcoal mb-3">{skill.description}</p>

            {/* Metadata */}
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-mute-gray mb-3">
                {skill.trigger_hint && (
                    <span className="bg-purple-50 text-purple-600 rounded-full px-2 py-0.5">
                        🎯 {skill.trigger_hint}
                    </span>
                )}
                {skill.tools_used && skill.tools_used.length > 0 && (
                    <span className="bg-off-white text-slate-gray rounded-full px-2 py-0.5">
                        🔧 {skill.tools_used.length} tools
                    </span>
                )}
                <span className="bg-emerald-50 text-emerald-600 rounded-full px-2 py-0.5">
                    ✅ {skill.success_count || 0} uses
                </span>
                {skill.version && (
                    <span className="text-mute-gray">v{skill.version}</span>
                )}
            </div>

            {/* Procedure preview */}
            <details className="group">
                <summary className="text-xs text-mute-gray cursor-pointer hover:text-charcoal">
                    Show procedure ({skill.procedure.length} chars)
                </summary>
                <pre className="bg-off-white rounded-lg p-3 mt-2 text-[11px] text-charcoal font-mono whitespace-pre-wrap max-h-48 overflow-y-auto border border-hairline">
                    {skill.procedure}
                </pre>
            </details>
        </div>
    )
}
