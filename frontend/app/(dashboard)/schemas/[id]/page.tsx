"use client"

import { useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, FileText, Shield, Trash2, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/components/auth-provider"
import { getApiBaseUrl } from "@/lib/api"

interface SchemaField {
  name: string
  type: string
  description?: string
  required?: boolean
}

interface SchemaDetail {
  id: string
  name: string
  description: string
  document_type: string
  ocr_engine: string
  fields: SchemaField[]
  created_at?: string
  updated_at?: string
  created_by?: string
  created_by_email?: string
  created_by_name?: string
}

export default function SchemaDetailPage() {
  const params = useParams()
  const router = useRouter()
  const schemaId = params.id as string
  const { user, loading: authLoading } = useAuth()

  const [schema, setSchema] = useState<SchemaDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<"fields" | "json">("fields")

  const normalizedRole = useMemo(() => {
    if (!user?.role) return "user"
    return user.role === "documents_admin" ? "manager" : user.role
  }, [user?.role])

  const canManage = useMemo(() => {
    if (!schema) return false
    if (normalizedRole === "admin") return true
    if (normalizedRole === "manager" && schema.created_by === user?.id) return true
    return false
  }, [normalizedRole, schema, user?.id])

  // Convert fields to JSON Schema format
  const jsonSchema = useMemo(() => {
    if (!schema?.fields) return null

    const properties: Record<string, any> = {}
    const required: string[] = []

    schema.fields.forEach(field => {
      let jsonType = "string"
      if (field.type === "number") jsonType = "number"
      if (field.type === "boolean") jsonType = "boolean"
      if (field.type === "date") jsonType = "string"

      properties[field.name] = {
        type: jsonType,
        description: field.description || ""
      }

      if (field.required) {
        required.push(field.name)
      }
    })

    return {
      type: "object",
      properties,
      required: required.length > 0 ? required : undefined
    }
  }, [schema])

  useEffect(() => {
    const fetchSchema = async () => {
      try {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        const res = await fetch(`${getApiBaseUrl()}/schemas/${schemaId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (res.ok) {
          const data = await res.json()
          setSchema(data)
        }
      } catch (error) {
        console.error("Failed to load schema", error)
      } finally {
        setLoading(false)
      }
    }

    fetchSchema()
  }, [schemaId])

  const handleCopyJson = () => {
    if (jsonSchema) {
      navigator.clipboard.writeText(JSON.stringify(jsonSchema, null, 2))
      alert("JSON Schema copied to clipboard!")
    }
  }

  if (authLoading || loading) return <div>Loading...</div>
  if (!schema) return <div>Schema not found</div>

  const createdDate = schema.created_at ? new Date(schema.created_at).toLocaleDateString() : ""
  const updatedDate = schema.updated_at ? new Date(schema.updated_at).toLocaleDateString() : ""
  const ownerLabel = schema.created_by_email || schema.created_by_name || (schema.created_by === user?.id ? "You" : schema.created_by || "Unknown")

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/schemas">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <FileText className="h-5 w-5 text-blue-600" />
              <h2 className="text-2xl font-bold tracking-tight">{schema.name}</h2>
            </div>
            <p className="text-slate-500">{schema.description || "No description"}</p>
            <div className="text-xs text-slate-500 mt-1 space-x-2">
              <span>Type: {schema.document_type}</span>
              {createdDate && <span>Created: {createdDate}</span>}
              {updatedDate && <span>Updated: {updatedDate}</span>}
              <span>Owner: {ownerLabel}</span>
            </div>
          </div>
        </div>
        {canManage && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => router.push(`/schemas/${schema.id}/edit`)}>
              <Pencil className="h-4 w-4 mr-2" />
              Edit
            </Button>
            <Button variant="destructive" onClick={() => router.push(`/schemas/${schema.id}/edit`)}>
              <Trash2 className="h-4 w-4 mr-2" />
              Delete
            </Button>
          </div>
        )}
      </div>

      <div className="rounded-lg border bg-white shadow-sm">
        {/* Tabs */}
        <div className="border-b">
          <div className="flex">
            <button
              onClick={() => setActiveTab("fields")}
              className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${activeTab === "fields"
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-slate-500 hover:text-slate-700"
                }`}
            >
              Extraction Fields
            </button>
            <button
              onClick={() => setActiveTab("json")}
              className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${activeTab === "json"
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-slate-500 hover:text-slate-700"
                }`}
            >
              JSON Schema
            </button>
          </div>
        </div>

        {/* Tab Content */}
        <div className="p-6">
          {activeTab === "fields" && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">Extraction Fields</h3>
                <span className="text-sm text-slate-500">{schema.fields?.length || 0} fields</span>
              </div>
              {schema.fields && schema.fields.length > 0 ? (
                <div className="divide-y">
                  {schema.fields.map((field, idx) => (
                    <div key={idx} className="py-3 flex justify-between items-start">
                      <div>
                        <div className="font-medium flex items-center gap-2">
                          {field.name}
                          {field.required && (
                            <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded">Required</span>
                          )}
                        </div>
                        <div className="text-xs text-slate-500">{field.description || "No description"}</div>
                      </div>
                      <div className="text-sm text-slate-600 capitalize">{field.type}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-slate-500 text-sm">No fields defined.</div>
              )}
            </div>
          )}

          {activeTab === "json" && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">JSON Schema</h3>
                <Button onClick={handleCopyJson} variant="outline" size="sm">
                  Copy to Clipboard
                </Button>
              </div>
              <pre className="bg-slate-50 p-4 rounded-lg overflow-x-auto text-sm border">
                <code>{JSON.stringify(jsonSchema, null, 2)}</code>
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
