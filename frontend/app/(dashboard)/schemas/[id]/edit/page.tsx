"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter, useParams } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/components/auth-provider"

interface SchemaField {
  name: string
  type: string
  description: string
  required: boolean
}

interface SchemaDetail {
  id: string
  name: string
  description: string
  document_type: string
  ocr_engine: string
  fields: SchemaField[]
  created_by?: string
}

export default function EditSchemaPage() {
  const router = useRouter()
  const params = useParams()
  const schemaId = params.id as string
  const { user, loading: authLoading } = useAuth()
  const normalizedRole = useMemo(() => {
    if (!user?.role) return "user"
    return user.role === "documents_admin" ? "manager" : user.role
  }, [user?.role])

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [schema, setSchema] = useState<SchemaDetail | null>(null)
  const [fields, setFields] = useState<SchemaField[]>([])

  const canEdit = useMemo(() => {
    if (!schema) return false
    if (normalizedRole === "admin") return true
    if (normalizedRole === "manager" && schema.created_by === user?.id) return true
    return false
  }, [normalizedRole, schema, user?.id])

  useEffect(() => {
    const fetchSchema = async () => {
      try {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/schemas/${schemaId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (res.ok) {
          const data = await res.json()
          setSchema(data)
          setFields(data.fields || [])
        }
      } catch (error) {
        console.error("Failed to load schema", error)
      } finally {
        setLoading(false)
      }
    }

    fetchSchema()
  }, [schemaId])

  const addField = () => {
    setFields([...fields, { name: "", type: "text", description: "", required: false }])
  }

  const removeField = (index: number) => {
    setFields(fields.filter((_, i) => i !== index))
  }

  const updateField = (index: number, key: keyof SchemaField, value: any) => {
    const newFields = [...fields]
    newFields[index] = { ...newFields[index], [key]: value }
    setFields(newFields)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!schema) return
    setSaving(true)

    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
      const payload = {
        name: schema.name,
        description: schema.description,
        document_type: schema.document_type,
        ocr_engine: schema.ocr_engine,
        fields,
      }

      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/schemas/${schemaId}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: JSON.stringify(payload)
      })

      if (res.ok) {
        router.push("/schemas")
      } else {
        alert("Failed to update schema")
      }
    } catch (error) {
      console.error("Error updating schema", error)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!schema) return
    if (!confirm("Delete this schema?")) return

    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/schemas/${schemaId}`, {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (res.ok) {
        router.push("/schemas")
      } else {
        alert("Failed to delete schema")
      }
    } catch (error) {
      console.error("Error deleting schema", error)
    }
  }

  if (authLoading || loading) return <div>Loading...</div>
  if (!schema) return <div>Schema not found</div>

  if (!canEdit) {
    return (
      <div className="bg-white rounded-lg border shadow-sm p-6">
        <h2 className="text-xl font-semibold text-slate-900">Access restricted</h2>
        <p className="text-slate-600 mt-2">You do not have permission to edit this schema.</p>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center space-x-4">
        <Link href="/schemas">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div className="flex-1">
          <h2 className="text-2xl font-bold tracking-tight">Edit Schema</h2>
          <p className="text-slate-500">Update fields, description, or delete this schema.</p>
        </div>
        <Button variant="destructive" onClick={handleDelete}>
          Delete
        </Button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-8">
        <div className="grid gap-6 p-6 border rounded-lg bg-white shadow-sm">
          <h3 className="text-lg font-semibold">Basic Information</h3>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">Schema Name</label>
              <Input
                required
                placeholder="e.g. Standard Invoice"
                value={schema.name}
                onChange={(e) => setSchema({ ...schema, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Document Type</label>
              <select
                className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                value={schema.document_type}
                onChange={(e) => setSchema({ ...schema, document_type: e.target.value })}
              >
                <option value="invoice">Invoice</option>
                <option value="receipt">Receipt</option>
                <option value="contract">Contract</option>
                <option value="po">Purchase Order</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium">Description</label>
              <Input
                placeholder="Description of this schema..."
                value={schema.description || ""}
                onChange={(e) => setSchema({ ...schema, description: e.target.value })}
              />
            </div>
          </div>
        </div>

        <div className="grid gap-6 p-6 border rounded-lg bg-white shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Extraction Fields</h3>
            <Button type="button" onClick={addField} variant="outline" size="sm">
              <Plus className="mr-2 h-4 w-4" />
              Add Field
            </Button>
          </div>

          <div className="space-y-4">
            {fields.map((field, index) => (
              <div key={index} className="flex items-start gap-4 p-4 rounded-md bg-slate-50 border">
                <div className="grid gap-4 flex-1 md:grid-cols-4">
                  <div className="space-y-1">
                    <label className="text-xs font-medium">Field Name</label>
                    <Input
                      placeholder="field_name"
                      value={field.name}
                      onChange={(e) => updateField(index, "name", e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs font-medium">Type</label>
                    <select
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                      value={field.type}
                      onChange={(e) => updateField(index, "type", e.target.value)}
                    >
                      <option value="text">Text</option>
                      <option value="number">Number</option>
                      <option value="date">Date</option>
                      <option value="currency">Currency</option>
                      <option value="boolean">Boolean</option>
                    </select>
                  </div>
                  <div className="space-y-1 md:col-span-2">
                    <label className="text-xs font-medium">Description (Prompt)</label>
                    <Input
                      placeholder="Instructions for LLM..."
                      value={field.description}
                      onChange={(e) => updateField(index, "description", e.target.value)}
                    />
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="text-red-500 hover:text-red-600 hover:bg-red-50 mt-6"
                  onClick={() => removeField(index)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-4">
          <Link href="/schemas">
            <Button type="button" variant="outline">Cancel</Button>
          </Link>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving..." : "Save Changes"}
          </Button>
        </div>
      </form>
    </div>
  )
}
