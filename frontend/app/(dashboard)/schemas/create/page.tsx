"use client"

import { useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft, Plus, Trash2, FileJson } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Modal } from "@/components/ui/modal"
import Link from "next/link"
import { useAuth } from "@/components/auth-provider"
import { getApiBaseUrl } from "@/lib/api"

interface SchemaField {
    name: string
    type: string
    description: string
    required: boolean
}

export default function CreateSchemaPage() {
    const router = useRouter()
    const { user, loading: authLoading } = useAuth()
    const normalizedRole = useMemo(() => {
        if (!user?.role) return "user"
        return user.role === "documents_admin" ? "manager" : user.role
    }, [user?.role])
    const [loading, setLoading] = useState(false)
    const [formData, setFormData] = useState({
        name: "",
        description: "",
        document_type: "invoice",
        ocr_engine: "tesseract"
    })
    const [fields, setFields] = useState<SchemaField[]>([
        { name: "invoice_number", type: "text", description: "Invoice number", required: true }
    ])
    const [isImportModalOpen, setIsImportModalOpen] = useState(false)
    const [importJson, setImportJson] = useState("")

    const handleImport = () => {
        try {
            const schema = JSON.parse(importJson)
            if (schema.properties) {
                const newFields: SchemaField[] = Object.entries(schema.properties).map(([key, value]: [string, any]) => {
                    let type = "text"
                    if (value.type === "number" || value.type === "integer") type = "number"
                    if (value.type === "boolean") type = "boolean"

                    return {
                        name: key,
                        type: type,
                        description: value.description || "",
                        required: schema.required ? schema.required.includes(key) : false
                    }
                })
                setFields(newFields)
                setIsImportModalOpen(false)
                setImportJson("")
            } else {
                alert("Invalid JSON Schema: 'properties' field is missing.")
            }
        } catch (error) {
            alert("Invalid JSON format.")
        }
    }

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
        setLoading(true)

        try {
            const payload = {
                ...formData,
                fields: fields
            }

            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${getApiBaseUrl()}/schemas/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify(payload)
            })

            if (res.ok) {
                router.push("/schemas")
            } else {
                alert("Failed to create schema")
            }
        } catch (error) {
            console.error("Error creating schema", error)
        } finally {
            setLoading(false)
        }
    }

    if (authLoading) return <div>Loading...</div>

    if (normalizedRole === "user") {
        return (
            <div className="bg-white rounded-lg border shadow-sm p-6">
                <h2 className="text-xl font-semibold text-slate-900">Access restricted</h2>
                <p className="text-slate-600 mt-2">Schemas can be created by Managers or Admins.</p>
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
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Create New Schema</h2>
                    <p className="text-slate-500">Define the structure for your documents.</p>
                </div>
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
                                value={formData.name}
                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Document Type</label>
                            <select
                                className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                value={formData.document_type}
                                onChange={(e) => setFormData({ ...formData, document_type: e.target.value })}
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
                                value={formData.description}
                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                            />
                        </div>
                    </div>
                </div>

                <div className="grid gap-6 p-6 border rounded-lg bg-white shadow-sm">
                    <div className="flex items-center justify-between">
                        <h3 className="text-lg font-semibold">Extraction Fields</h3>
                        <div className="flex gap-2">
                            <Button type="button" onClick={() => setIsImportModalOpen(true)} variant="outline" size="sm">
                                <FileJson className="mr-2 h-4 w-4" />
                                Import JSON Schema
                            </Button>
                            <Button type="button" onClick={addField} variant="outline" size="sm">
                                <Plus className="mr-2 h-4 w-4" />
                                Add Field
                            </Button>
                        </div>
                    </div>

                    <Modal
                        isOpen={isImportModalOpen}
                        onClose={() => setIsImportModalOpen(false)}
                        title="Import JSON Schema"
                    >
                        <div className="space-y-4">
                            <p className="text-sm text-slate-500">
                                Paste your JSON Schema below. It will replace the current fields.
                            </p>
                            <Textarea
                                placeholder='{"type": "object", "properties": {...}}'
                                className="h-64 font-mono text-xs"
                                value={importJson}
                                onChange={(e) => setImportJson(e.target.value)}
                            />
                            <div className="flex justify-end gap-2">
                                <Button type="button" variant="outline" onClick={() => setIsImportModalOpen(false)}>
                                    Cancel
                                </Button>
                                <Button type="button" onClick={handleImport}>
                                    Import
                                </Button>
                            </div>
                        </div>
                    </Modal>

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
                    <Button type="submit" disabled={loading}>
                        {loading ? "Creating..." : "Create Schema"}
                    </Button>
                </div>
            </form>
        </div>
    )
}
