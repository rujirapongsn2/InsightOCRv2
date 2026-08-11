"use client"

import { useState, useEffect } from "react"
import { X, Save, Loader2, Wrench } from "lucide-react"

interface Skill {
    id?: string
    name: string
    scope: string
    description: string
    procedure: string
    trigger_hint?: string | null
    tools_used?: string[] | null
    allowed_tools?: string | null
    license?: string | null
    compatibility?: string | null
    metadata?: Record<string, string> | null
}

export interface SkillTool {
    name: string
    category: string
    description: string
    requires_confirmation: boolean
}

export type SkillDraft = Omit<Skill, "id" | "scope"> & { scope?: string }

interface SkillEditorProps {
    skill?: Skill | null       // null = create mode
    tools: SkillTool[]
    onSave: (data: SkillDraft) => Promise<void>
    onClose: () => void
}

export default function SkillEditor({ skill, tools, onSave, onClose }: SkillEditorProps) {
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [procedure, setProcedure] = useState("")
    const [triggerHint, setTriggerHint] = useState("")
    const [selectedTools, setSelectedTools] = useState<string[]>([])
    const [license, setLicense] = useState("")
    const [compatibility, setCompatibility] = useState("")
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const isEdit = !!skill

    useEffect(() => {
        if (skill) {
            setName(skill.name)
            setDescription(skill.description)
            setProcedure(skill.procedure)
            setTriggerHint(skill.trigger_hint || "")
            setSelectedTools((skill.allowed_tools || "").split(/[\s,]+/).filter(Boolean))
            setLicense(skill.license || "")
            setCompatibility(skill.compatibility || "")
        }
    }, [skill])

    const handleSave = async () => {
        setError(null)

        if (!name.trim()) { setError("Name is required"); return }
        if (!description.trim()) { setError("Description is required"); return }
        if (!procedure.trim()) { setError("Procedure is required"); return }

        const nameSanitized = name.trim().toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/--+/g, "-")
        if (!nameSanitized || nameSanitized.startsWith("-") || nameSanitized.endsWith("-")) {
            setError("Use lowercase letters, numbers, and hyphens for the name")
            return
        }

        setSaving(true)
        try {
            await onSave({
                name: nameSanitized,
                description: description.trim(),
                procedure: procedure.trim(),
                trigger_hint: triggerHint.trim() || null,
                tools_used: selectedTools,
                allowed_tools: selectedTools.join(" "),
                license: license.trim() || null,
                compatibility: compatibility.trim() || null,
            })
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Save failed")
        } finally {
            setSaving(false)
        }
    }

    const toggleTool = (toolName: string) => {
        setSelectedTools(current => current.includes(toolName)
            ? current.filter(name => name !== toolName)
            : [...current, toolName])
    }

    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b">
                    <h2 className="text-lg font-semibold text-ink-navy">
                        {isEdit ? `Edit: ${skill?.name}` : "Create Skill"}
                    </h2>
                    <button onClick={onClose} className="p-1 text-mute-gray hover:text-charcoal rounded">
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Form */}
                <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                    <div>
                            <label className="block text-xs font-medium text-charcoal mb-1">Name *</label>
                            <input
                                type="text"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                placeholder="my-workflow-skill"
                                disabled={isEdit}
                                className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue focus:border-softnix-blue disabled:bg-off-white disabled:text-mute-gray"
                            />
                    </div>

                    {/* Description */}
                    <div>
                        <label className="block text-xs font-medium text-charcoal mb-1">Description *</label>
                        <textarea
                            value={description}
                            onChange={e => setDescription(e.target.value)}
                            placeholder="What this skill does and when to use it"
                            rows={2}
                            maxLength={1024}
                            className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue"
                        />
                        <p className="text-[10px] text-mute-gray">{description.length}/1024</p>
                    </div>

                    {/* Procedure */}
                    <div>
                        <label className="block text-xs font-medium text-charcoal mb-1">Procedure * (markdown)</label>
                        <textarea
                            value={procedure}
                            onChange={e => setProcedure(e.target.value)}
                            placeholder="# Steps\n1. First step\n2. Second step"
                            rows={10}
                            className="w-full text-sm font-mono border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue"
                        />
                    </div>

                    {/* Trigger Hint */}
                    <div>
                        <label className="block text-xs font-medium text-charcoal mb-1">Trigger Hint</label>
                        <input
                            type="text"
                            value={triggerHint}
                            onChange={e => setTriggerHint(e.target.value)}
                            placeholder="when user wants to bulk approve invoices"
                            className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue"
                        />
                    </div>

                    <div>
                        <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-charcoal">
                            <Wrench className="h-3.5 w-3.5" /> Allowed tools
                        </div>
                        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                            {tools.map(tool => {
                                const selected = selectedTools.includes(tool.name)
                                return (
                                    <label key={tool.name} className={`flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-2 text-xs ${selected ? "border-softnix-blue bg-[#F0F8FD]" : "border-hairline hover:bg-off-white"}`}>
                                        <input
                                            type="checkbox"
                                            checked={selected}
                                            onChange={() => toggleTool(tool.name)}
                                            className="mt-0.5 accent-softnix-blue"
                                        />
                                        <span className="min-w-0">
                                            <span className="block font-medium text-charcoal">{tool.name}</span>
                                            <span
                                                className="block truncate text-[10px] text-mute-gray"
                                                title={tool.description}
                                            >
                                                {tool.category}{tool.requires_confirmation ? " · confirmation" : ""}
                                            </span>
                                        </span>
                                    </label>
                                )
                            })}
                        </div>
                    </div>

                    {/* License + Compatibility */}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-xs font-medium text-charcoal mb-1">License</label>
                            <input
                                type="text"
                                value={license}
                                onChange={e => setLicense(e.target.value)}
                                placeholder="MIT"
                                className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue"
                            />
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-charcoal mb-1">Compatibility</label>
                            <input
                                type="text"
                                value={compatibility}
                                onChange={e => setCompatibility(e.target.value)}
                                placeholder="Requires Python 3.12+"
                                className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue"
                            />
                        </div>
                    </div>

                    {/* Error */}
                    {error && (
                        <div className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</div>
                    )}
                </div>

                {/* Footer */}
                <div className="flex items-center justify-end gap-2 px-6 py-4 border-t bg-off-white rounded-b-2xl">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-sm text-charcoal hover:text-ink-navy rounded-lg"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex items-center gap-2 px-5 py-2 bg-softnix-blue text-white text-sm font-medium rounded-lg hover:bg-softnix-deep disabled:opacity-50"
                    >
                        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                        {isEdit ? "Update" : "Create"}
                    </button>
                </div>
            </div>
        </div>
    )
}
