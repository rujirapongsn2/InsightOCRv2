"use client"

import { useState, useEffect } from "react"
import { X, Save, Loader2 } from "lucide-react"

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

interface SkillEditorProps {
    skill?: Skill | null       // null = create mode
    onSave: (data: Skill) => Promise<void>
    onClose: () => void
}

export default function SkillEditor({ skill, onSave, onClose }: SkillEditorProps) {
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [procedure, setProcedure] = useState("")
    const [scope, setScope] = useState<"user" | "system">("user")
    const [triggerHint, setTriggerHint] = useState("")
    const [toolsUsed, setToolsUsed] = useState("")
    const [allowedTools, setAllowedTools] = useState("")
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
            setScope((skill.scope as "user" | "system") || "user")
            setTriggerHint(skill.trigger_hint || "")
            setToolsUsed((skill.tools_used || []).join(", "))
            setAllowedTools(skill.allowed_tools || "")
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
        if (nameSanitized !== name.trim().toLowerCase()) {
            setError(`Name will be normalized to: ${nameSanitized}`)
        }

        setSaving(true)
        try {
            await onSave({
                name: nameSanitized,
                scope,
                description: description.trim(),
                procedure: procedure.trim(),
                trigger_hint: triggerHint.trim() || null,
                tools_used: toolsUsed ? toolsUsed.split(",").map(s => s.trim()).filter(Boolean) : null,
                allowed_tools: allowedTools.trim() || null,
                license: license.trim() || null,
                compatibility: compatibility.trim() || null,
            })
        } catch (e: any) {
            setError(e.message || "Save failed")
        } finally {
            setSaving(false)
        }
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
                    {/* Name + Scope */}
                    <div className="grid grid-cols-3 gap-3">
                        <div className="col-span-2">
                            <label className="block text-xs font-medium text-charcoal mb-1">Name *</label>
                            <input
                                type="text"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                placeholder="my-workflow-skill"
                                disabled={isEdit}
                                className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue focus:border-softnix-blue disabled:bg-off-white disabled:text-mute-gray"
                            />
                            <p className="text-[10px] text-mute-gray mt-0.5">lowercase, hyphens only (agentskills.io format)</p>
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-charcoal mb-1">Scope</label>
                            <select
                                value={scope}
                                onChange={e => setScope(e.target.value as "user" | "system")}
                                className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue"
                            >
                                <option value="user">User</option>
                                <option value="system">System</option>
                            </select>
                        </div>
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

                    {/* Tools */}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-xs font-medium text-charcoal mb-1">Tools Used</label>
                            <input
                                type="text"
                                value={toolsUsed}
                                onChange={e => setToolsUsed(e.target.value)}
                                placeholder="list_documents, approve_document"
                                className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue"
                            />
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-charcoal mb-1">Allowed Tools</label>
                            <input
                                type="text"
                                value={allowedTools}
                                onChange={e => setAllowedTools(e.target.value)}
                                placeholder="Bash(git:*) Read"
                                className="w-full text-sm border border-hairline rounded-lg px-3 py-2 focus:ring-2 focus:ring-softnix-blue"
                            />
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
