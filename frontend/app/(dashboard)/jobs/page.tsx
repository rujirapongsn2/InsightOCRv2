"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Plus, FileText, Calendar } from "lucide-react"
import { Button } from "@/components/ui/button"

interface Job {
    id: string
    name: string
    description: string
    status: string
    created_at: string
}

export default function JobsPage() {
    const [jobs, setJobs] = useState<Job[]>([])
    const [loading, setLoading] = useState(true)
    const [sortOption, setSortOption] = useState<"newest" | "oldest" | "name_asc" | "name_desc">("newest")

    useEffect(() => {
        const fetchJobs = async () => {
            try {
                const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
                const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/jobs/`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
                })
                if (res.ok) {
                    const data = await res.json()
                    setJobs(data)
                }
            } catch (error) {
                console.error("Failed to fetch jobs", error)
            } finally {
                setLoading(false)
            }
        }

        fetchJobs()
    }, [])

    const sortedJobs = [...jobs].sort((a, b) => {
        if (sortOption === "newest") {
            return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        }
        if (sortOption === "oldest") {
            return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        }
        if (sortOption === "name_asc") {
            return a.name.localeCompare(b.name)
        }
        return b.name.localeCompare(a.name)
    })

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Jobs</h2>
                    <p className="text-slate-500">Manage your document processing jobs.</p>
                </div>
                <div className="flex items-center gap-3">
                    <label className="text-sm text-slate-500" htmlFor="sort">
                        Sort by
                    </label>
                    <select
                        id="sort"
                        className="flex h-9 rounded-md border border-slate-200 bg-white px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-200"
                        value={sortOption}
                        onChange={(e) => setSortOption(e.target.value as any)}
                    >
                        <option value="newest">Newest first</option>
                        <option value="oldest">Oldest first</option>
                        <option value="name_asc">Name A → Z</option>
                        <option value="name_desc">Name Z → A</option>
                    </select>
                    <Link href="/jobs/create">
                        <Button>
                            <Plus className="mr-2 h-4 w-4" />
                            Create Job
                        </Button>
                    </Link>
                </div>
            </div>

            {loading ? (
                <div>Loading...</div>
            ) : jobs.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-8 text-center animate-in fade-in-50">
                    <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-slate-100">
                        <FileText className="h-6 w-6 text-slate-600" />
                    </div>
                    <h3 className="mt-4 text-lg font-semibold">No jobs found</h3>
                    <p className="mb-4 mt-2 text-sm text-slate-500 max-w-sm">
                        Create a job to start processing documents.
                    </p>
                    <Link href="/jobs/create">
                        <Button variant="outline">Create your first Job</Button>
                    </Link>
                </div>
            ) : (
                <div className="grid gap-4">
                    {sortedJobs.map((job) => (
                        <Link key={job.id} href={`/jobs/${job.id}`}>
                            <div className="flex items-center justify-between rounded-lg border bg-white p-6 shadow-sm hover:shadow-md transition-shadow cursor-pointer">
                                <div className="flex items-center gap-4">
                                    <div className="h-10 w-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600">
                                        <FileText className="h-5 w-5" />
                                    </div>
                                    <div>
                                        <h3 className="font-semibold text-lg">{job.name}</h3>
                                        <p className="text-sm text-slate-500">{job.description}</p>
                                    </div>
                                </div>
                                <div className="flex items-center gap-6">
                                    <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${job.status === 'completed' ? 'bg-green-100 text-green-800' :
                                        job.status === 'processing' ? 'bg-blue-100 text-blue-800' :
                                            'bg-slate-100 text-slate-800'
                                        }`}>
                                        {job.status.toUpperCase()}
                                    </span>
                                    <div className="flex items-center text-sm text-slate-500">
                                        <Calendar className="mr-2 h-4 w-4" />
                                        {new Date(job.created_at).toLocaleDateString()}
                                    </div>
                                </div>
                            </div>
                        </Link>
                    ))}
                </div>
            )}
        </div>
    )
}
