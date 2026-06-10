"use client"

import { useState, useEffect, useCallback } from "react"
import { Plus, Loader2, Search, Upload, Download, Globe, User } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"
import SkillCard from "./SkillCard"
import SkillEditor from "./SkillEditor"

interface Skill {
    id: string
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
    success_count: number
    created_by: string
    source: string
    version?: string | null
    file_path?: string | null
    created_at?: string | null
    updated_at?: string | null
}

interface SkillLibraryProps {
    jobId: string
    onClose: () => void
}

export default function SkillLibrary({ jobId, onClose }: SkillLibraryProps) {
    const [skills, setSkills] = useState<Skill[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [filter, setFilter] = useState<"all" | "user" | "system">("all")
    const [search, setSearch] = useState("")
    const [editingSkill, setEditingSkill] = useState<Skill | null>(null)
    const [showCreate, setShowCreate] = useState(false)
    const [showImport, setShowImport] = useState(false)
    const [importPath, setImportPath] = useState("")
    const [importing, setImporting] = useState(false)

    const apiBase = getApiBaseUrl()
    const getToken = () => typeof window !== "undefined" ? localStorage.getItem("token") : null
    const headers = useCallback(() => {
        const token = getToken()
        return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) }
    }, [])

    const loadSkills = useCallback(async () => {
        setLoading(true)
        try {
            const scopeParam = filter === "all" ? "" : `?scope=${filter}`
            const res = await fetch(`${apiBase}/agent/skills${scopeParam}`, { headers: headers() })
            if (res.ok) {
                const data = await res.json()
                setSkills(data.skills || [])
            }
        } catch { } finally { setLoading(false) }
    }, [apiBase, filter, headers])

    useEffect(() => { loadSkills() }, [loadSkills])

    const handleSave = async (data: any) => {
        const isEdit = !!editingSkill?.id
        const url = isEdit
            ? `${apiBase}/agent/skills/${editingSkill.id}`
            : `${apiBase}/agent/skills`
        const method = isEdit ? "PUT" : "POST"

        const res = await fetch(url, {
            method,
            headers: headers(),
            body: JSON.stringify(data),
        })

        if (!res.ok) {
            const err = await res.json()
            throw new Error(err.detail || "Save failed")
        }

        setShowCreate(false)
        setEditingSkill(null)
        loadSkills()
    }

    const handleDelete = async (skill: Skill) => {
        if (!confirm(`Delete skill "${skill.name}"?`)) return
        await fetch(`${apiBase}/agent/skills/${skill.id}`, {
            method: "DELETE",
            headers: headers(),
        })
        loadSkills()
    }

    const handleExport = async (skill: Skill) => {
        try {
            const res = await fetch(`${apiBase}/agent/skills/${skill.id}/export?format=markdown`, {
                headers: headers(),
            })
            if (res.ok) {
                const text = await res.text()
                const blob = new Blob([text], { type: "text/markdown" })
                const url = URL.createObjectURL(blob)
                const a = document.createElement("a")
                a.href = url
                a.download = `${skill.name}.SKILL.md`
                a.click()
                URL.revokeObjectURL(url)
            }
        } catch { }
    }

    const handleImport = async () => {
        if (!importPath.trim()) return
        setImporting(true)
        setError(null)
        try {
            const res = await fetch(`${apiBase}/agent/skills/import`, {
                method: "POST",
                headers: headers(),
                body: JSON.stringify({ file_path: importPath.trim(), overwrite: false }),
            })
            if (!res.ok) {
                const err = await res.json()
                throw new Error(err.detail || "Import failed")
            }
            setShowImport(false)
            setImportPath("")
            loadSkills()
        } catch (e: any) {
            setError(e.message)
        } finally { setImporting(false) }
    }

    const filtered = skills.filter(s => {
        if (search) {
            const q = search.toLowerCase()
            return s.name.includes(q) || s.description.toLowerCase().includes(q)
        }
        return true
    })

    const userSkills = filtered.filter(s => s.scope === "user")
    const systemSkills = filtered.filter(s => s.scope === "system")

    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b">
                    <div>
                        <h2 className="text-lg font-semibold text-ink-navy">Skill Library</h2>
                        <p className="text-xs text-slate-gray mt-0.5">
                            agentskills.io compatible — reusable procedures for AI agents
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setShowImport(true)}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-charcoal border border-hairline rounded-lg hover:bg-off-white"
                        >
                            <Upload className="h-3.5 w-3.5" /> Import
                        </button>
                        <button
                            onClick={() => { setEditingSkill(null); setShowCreate(true) }}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-white bg-softnix-blue rounded-lg hover:bg-softnix-deep"
                        >
                            <Plus className="h-3.5 w-3.5" /> New Skill
                        </button>
                    </div>
                </div>

                {/* Toolbar */}
                <div className="flex items-center gap-3 px-6 py-3 border-b bg-off-white">
                    <div className="flex items-center gap-1 bg-white border border-hairline rounded-lg p-0.5">
                        {(["all", "user", "system"] as const).map(f => (
                            <button
                                key={f}
                                onClick={() => setFilter(f)}
                                className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${
                                    filter === f ? "bg-softnix-blue text-white" : "text-charcoal hover:text-ink-navy"
                                }`}
                            >
                                {f === "all" ? "All" : f === "user" ? "👤 User" : "🌐 System"}
                            </button>
                        ))}
                    </div>
                    <div className="flex-1 relative">
                        <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-mute-gray" />
                        <input
                            type="text"
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            placeholder="Search skills..."
                            className="w-full text-xs border border-hairline rounded-lg pl-8 pr-3 py-1.5 focus:ring-2 focus:ring-softnix-blue"
                        />
                    </div>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
                    {loading && (
                        <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-mute-gray" /></div>
                    )}

                    {error && (
                        <div className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</div>
                    )}

                    {!loading && userSkills.length > 0 && (filter === "all" || filter === "user") && (
                        <div>
                            <h3 className="text-sm font-semibold text-charcoal mb-3 flex items-center gap-2">
                                <User className="h-4 w-4" /> User Skills
                            </h3>
                            <div className="grid grid-cols-1 gap-3">
                                {userSkills.map(skill => (
                                    <SkillCard
                                        key={skill.id}
                                        skill={skill}
                                        onEdit={(s) => { setEditingSkill(s); setShowCreate(true) }}
                                        onDelete={handleDelete}
                                        onExport={handleExport}
                                    />
                                ))}
                            </div>
                        </div>
                    )}

                    {!loading && systemSkills.length > 0 && (filter === "all" || filter === "system") && (
                        <div>
                            <h3 className="text-sm font-semibold text-charcoal mb-3 flex items-center gap-2">
                                <Globe className="h-4 w-4" /> System Skills
                            </h3>
                            <div className="grid grid-cols-1 gap-3">
                                {systemSkills.map(skill => (
                                    <SkillCard
                                        key={skill.id}
                                        skill={skill}
                                        onEdit={(s) => { setEditingSkill(s); setShowCreate(true) }}
                                        onDelete={handleDelete}
                                        onExport={handleExport}
                                    />
                                ))}
                            </div>
                        </div>
                    )}

                    {!loading && filtered.length === 0 && (
                        <div className="text-center py-12 text-mute-gray">
                            <p className="text-sm">No skills found</p>
                            <p className="text-xs mt-1">Create a new skill or import a SKILL.md file</p>
                        </div>
                    )}
                </div>
            </div>

            {/* Create/Edit Modal */}
            {showCreate && (
                <SkillEditor
                    skill={editingSkill}
                    onSave={handleSave}
                    onClose={() => { setShowCreate(false); setEditingSkill(null) }}
                />
            )}

            {/* Import Modal */}
            {showImport && (
                <div className="fixed inset-0 bg-black/40 z-[60] flex items-center justify-center p-4" onClick={() => { setShowImport(false); setError(null) }}>
                    <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-semibold text-ink-navy mb-1">Import SKILL.md</h3>
                        <p className="text-xs text-slate-gray mb-4">
                            Enter the absolute path to a SKILL.md file (agentskills.io format).
                        </p>
                        <input
                            type="text"
                            value={importPath}
                            onChange={e => setImportPath(e.target.value)}
                            placeholder="/path/to/skill-name/SKILL.md"
                            className="w-full text-sm border border-hairline rounded-lg px-3 py-2 mb-4 focus:ring-2 focus:ring-softnix-blue"
                        />
                        {error && (
                            <div className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2 mb-3">{error}</div>
                        )}
                        <div className="flex justify-end gap-2">
                            <button
                                onClick={() => { setShowImport(false); setError(null) }}
                                className="px-4 py-2 text-sm text-charcoal rounded-lg"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleImport}
                                disabled={importing || !importPath.trim()}
                                className="flex items-center gap-2 px-4 py-2 bg-softnix-blue text-white text-sm rounded-lg hover:bg-softnix-deep disabled:opacity-50"
                            >
                                {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                                Import
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
