"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Plus, FileText, Receipt, FileSignature, File, Search, ScrollText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/components/auth-provider"

interface Schema {
    id: string
    name: string
    document_type: string
    description: string
    fields: any[]
    created_by?: string
    created_at?: string
    updated_at: string
}

// Helper function to get icon and color for document type
const getDocumentTypeIcon = (type: string) => {
    switch (type.toLowerCase()) {
        case 'invoice':
            return { Icon: Receipt, color: 'bg-emerald-100 text-emerald-600', badgeColor: 'bg-emerald-50 text-emerald-700' }
        case 'receipt':
            return { Icon: Receipt, color: 'bg-orange-100 text-orange-600', badgeColor: 'bg-orange-50 text-orange-700' }
        case 'contract':
            return { Icon: FileSignature, color: 'bg-blue-100 text-blue-600', badgeColor: 'bg-blue-50 text-blue-700' }
        case 'form':
            return { Icon: ScrollText, color: 'bg-purple-100 text-purple-600', badgeColor: 'bg-purple-50 text-purple-700' }
        default:
            return { Icon: File, color: 'bg-slate-100 text-slate-600', badgeColor: 'bg-slate-50 text-slate-700' }
    }
}

export default function SchemasPage() {
    const router = useRouter()
    const { user, loading: authLoading } = useAuth()
    const [schemas, setSchemas] = useState<Schema[]>([])
    const [loading, setLoading] = useState(true)
    const [searchQuery, setSearchQuery] = useState("")

    const normalizedRole = useMemo(() => {
        if (!user?.role) return "user"
        return user.role === "documents_admin" ? "manager" : user.role
    }, [user?.role])

    // Filter schemas based on search query
    const filteredSchemas = useMemo(() => {
        if (!searchQuery.trim()) return schemas
        const query = searchQuery.toLowerCase()
        return schemas.filter(schema =>
            schema.name.toLowerCase().includes(query) ||
            schema.description?.toLowerCase().includes(query) ||
            schema.document_type.toLowerCase().includes(query)
        )
    }, [schemas, searchQuery])

    useEffect(() => {
        const fetchSchemas = async () => {
            try {
                const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
                const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/schemas/`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                })
                if (res.ok) {
                    const data = await res.json()
                    setSchemas(data)
                }
            } catch (error) {
                console.error("Failed to fetch schemas", error)
            } finally {
                setLoading(false)
            }
        }

        fetchSchemas()
    }, [])

    if (authLoading || loading) return <div>Loading...</div>

    if (normalizedRole === "user") {
        return (
            <div className="bg-white rounded-lg border shadow-sm p-6">
                <h2 className="text-xl font-semibold text-slate-900">Access restricted</h2>
                <p className="text-slate-600 mt-2">Schemas can be managed by Managers or Admins.</p>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Document Schemas</h2>
                    <p className="text-slate-500">Manage extraction schemas for your documents.</p>
                </div>
                {normalizedRole !== "user" && (
                    <Link href="/schemas/new">
                        <Button>
                            <Plus className="mr-2 h-4 w-4" />
                            Create Schema
                        </Button>
                    </Link>
                )}
            </div>

            {/* Search Bar */}
            {schemas.length > 0 && (
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                        type="text"
                        placeholder="Search schemas by name, description, or type..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                </div>
            )}

            {loading ? (
                <div>Loading...</div>
            ) : schemas.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-8 text-center animate-in fade-in-50">
                    <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-slate-100">
                        <FileText className="h-6 w-6 text-slate-600" />
                    </div>
                    <h3 className="mt-4 text-lg font-semibold">No schemas created</h3>
                    <p className="mb-4 mt-2 text-sm text-slate-500 max-w-sm">
                        You haven't created any document schemas yet. Create one to start extracting data.
                    </p>
                    <Link href="/schemas/new">
                        <Button variant="outline">Create your first Schema</Button>
                    </Link>
                </div>
            ) : filteredSchemas.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-8 text-center">
                    <Search className="h-10 w-10 text-slate-400 mb-3" />
                    <h3 className="text-lg font-semibold">No schemas found</h3>
                    <p className="text-sm text-slate-500 mt-1">
                        {searchQuery ? `No results for "${searchQuery}"` : "Try a different search term"}
                    </p>
                </div>
            ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {filteredSchemas.map((schema) => {
                        const canManage = normalizedRole === "admin" || (normalizedRole === "manager" && schema.created_by === user?.id)
                        const { Icon, color, badgeColor } = getDocumentTypeIcon(schema.document_type)

                        return (
                        <div
                            key={schema.id}
                            onClick={() => router.push(`/schemas/${schema.id}`)}
                            className="group relative rounded-lg border bg-white p-4 shadow-sm hover:shadow-md hover:border-slate-300 transition-all cursor-pointer"
                        >
                            {/* Header with Icon and Badge */}
                            <div className="flex items-start justify-between mb-3">
                                <div className={`h-12 w-12 rounded-lg ${color} flex items-center justify-center`}>
                                    <Icon className="h-6 w-6" />
                                </div>
                                <span className={`text-xs font-medium px-2 py-0.5 rounded ${badgeColor}`}>
                                    {schema.document_type}
                                </span>
                            </div>

                            {/* Schema Name */}
                            <h3 className="font-semibold text-base mb-1.5 line-clamp-1 group-hover:text-blue-600 transition-colors">
                                {schema.name}
                            </h3>

                            {/* Description */}
                            <p className="text-xs text-slate-500 mb-3 line-clamp-2 min-h-[2.5rem]">
                                {schema.description || "No description provided."}
                            </p>

                            {/* Metadata */}
                            <div className="flex items-center justify-between text-xs text-slate-500 mb-3 pb-3 border-b">
                                <span className="flex items-center gap-1">
                                    <FileText className="h-3 w-3" />
                                    {schema.fields.length} fields
                                </span>
                                <span>{new Date(schema.updated_at || Date.now()).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}</span>
                            </div>

                            {/* Action Buttons */}
                            {canManage && (
                                <div className="flex gap-2">
                                    <Link
                                        href={`/schemas/${schema.id}/edit`}
                                        className="flex-1"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        <Button size="sm" className="w-full">Edit</Button>
                                    </Link>
                                </div>
                            )}
                        </div>
                    )})}
                </div>
            )}
        </div>
    )
}
