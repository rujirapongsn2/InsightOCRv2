"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import Link from "next/link"

interface Schema {
    id: string
    name: string
}

export default function CreateJobPage() {
    const router = useRouter()
    const [loading, setLoading] = useState(false)
    const [formData, setFormData] = useState({
        name: "",
        description: ""
    })



    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setLoading(true)

        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/jobs/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify(formData)
            })

            if (res.ok) {
                const job = await res.json()
                router.push(`/jobs/${job.id}`)
            } else {
                alert("Failed to create job")
            }
        } catch (error) {
            console.error("Error creating job", error)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="max-w-2xl mx-auto space-y-6">
            <div className="flex items-center space-x-4">
                <Link href="/jobs">
                    <Button variant="ghost" size="icon">
                        <ArrowLeft className="h-4 w-4" />
                    </Button>
                </Link>
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Create New Job</h2>
                    <p className="text-slate-500">Start a new document processing job.</p>
                </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-8">
                <div className="grid gap-6 p-6 border rounded-lg bg-white shadow-sm">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Job Name</label>
                        <Input
                            required
                            placeholder="e.g. January Invoices"
                            value={formData.name}
                            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                        />
                    </div>



                    <div className="space-y-2">
                        <label className="text-sm font-medium">Description</label>
                        <Input
                            placeholder="Optional description..."
                            value={formData.description}
                            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                        />
                    </div>
                </div>

                <div className="flex justify-end gap-4">
                    <Link href="/jobs">
                        <Button type="button" variant="outline">Cancel</Button>
                    </Link>
                    <Button type="submit" disabled={loading}>
                        {loading ? "Creating..." : "Create Job"}
                    </Button>
                </div>
            </form>
        </div>
    )
}
