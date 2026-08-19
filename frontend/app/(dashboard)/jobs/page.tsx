"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Plus, FileText, Calendar, Trash2, Loader2, LayoutGrid, Table2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { getApiBaseUrl } from "@/lib/api"
import { useAuth } from "@/components/auth-provider"

interface Job {
    id: string
    name: string
    description: string
    status: string
    created_at: string
    user_id?: string
}

type SortOption = "newest" | "oldest" | "name_asc" | "name_desc"
const JOBS_PAGE_SIZE = 10

export default function JobsPage() {
    const { user } = useAuth()
    const [jobs, setJobs] = useState<Job[]>([])
    const [loading, setLoading] = useState(true)
    const [sortOption, setSortOption] = useState<SortOption>("newest")
    const [viewMode, setViewMode] = useState<"table" | "cards">("table")
    const [visibleJobCount, setVisibleJobCount] = useState(JOBS_PAGE_SIZE)
    const [deleteConfirmJob, setDeleteConfirmJob] = useState<Job | null>(null)
    const [deletingJob, setDeletingJob] = useState(false)

    const fetchJobs = async () => {
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const res = await fetch(`${getApiBaseUrl()}/jobs/`, {
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

    useEffect(() => {
        fetchJobs()
    }, [])

    useEffect(() => {
        const savedViewMode = window.localStorage.getItem("jobs-view-mode")
        if (savedViewMode === "cards" || savedViewMode === "table") {
            setViewMode(savedViewMode)
        }
    }, [])

    useEffect(() => {
        setVisibleJobCount(JOBS_PAGE_SIZE)
    }, [sortOption])

    const changeViewMode = (mode: "table" | "cards") => {
        setViewMode(mode)
        window.localStorage.setItem("jobs-view-mode", mode)
    }

    const handleDeleteJob = async () => {
        if (!deleteConfirmJob) return
        try {
            setDeletingJob(true)
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            const response = await fetch(`${getApiBaseUrl()}/jobs/${deleteConfirmJob.id}`, {
                method: "DELETE",
                headers: {
                    Authorization: `Bearer ${token}`,
                },
            })
            if (!response.ok) {
                throw new Error("Failed to delete job")
            }
            setDeleteConfirmJob(null)
            await fetchJobs()
        } catch (error) {
            console.error("Delete job error:", error)
            alert("Failed to delete job. Please try again.")
        } finally {
            setDeletingJob(false)
        }
    }

    const canDeleteJob = (job: Job) =>
        user && (user.is_superuser || user.role === "admin" || user.id === job.user_id)

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
    const visibleJobs = sortedJobs.slice(0, visibleJobCount)
    const hasMoreJobs = visibleJobCount < sortedJobs.length

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Jobs</h2>
                    <p className="text-slate-500">Manage your document processing jobs.</p>
                </div>
                <div className="flex items-center gap-3">
                    <div className="flex items-center rounded-md border border-slate-200 bg-white p-1" role="group" aria-label="Job view">
                        <button
                            type="button"
                            aria-label="Table view"
                            aria-pressed={viewMode === "table"}
                            title="Table view"
                            onClick={() => changeViewMode("table")}
                            className={`inline-flex h-8 items-center gap-2 rounded px-2.5 text-sm transition-colors ${viewMode === "table" ? "bg-slate-100 text-slate-900" : "text-slate-500 hover:text-slate-900"}`}
                        >
                            <Table2 className="h-4 w-4" />
                            <span className="hidden sm:inline">Table</span>
                        </button>
                        <button
                            type="button"
                            aria-label="Card view"
                            aria-pressed={viewMode === "cards"}
                            title="Card view"
                            onClick={() => changeViewMode("cards")}
                            className={`inline-flex h-8 items-center gap-2 rounded px-2.5 text-sm transition-colors ${viewMode === "cards" ? "bg-slate-100 text-slate-900" : "text-slate-500 hover:text-slate-900"}`}
                        >
                            <LayoutGrid className="h-4 w-4" />
                            <span className="hidden sm:inline">Cards</span>
                        </button>
                    </div>
                    <label className="text-sm text-slate-500" htmlFor="sort">
                        Sort by
                    </label>
                    <select
                        id="sort"
                        className="flex h-9 rounded-md border border-slate-200 bg-white px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-200"
                        value={sortOption}
                        onChange={(e) => setSortOption(e.target.value as SortOption)}
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
                viewMode === "table" ? (
                    <div className="overflow-hidden rounded-lg border bg-white shadow-sm">
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[680px] text-sm">
                                <caption className="sr-only">Document processing jobs</caption>
                                <thead className="border-b bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                                    <tr>
                                        <th scope="col" className="px-5 py-3 font-semibold">Job</th>
                                        <th scope="col" className="px-5 py-3 font-semibold">Status</th>
                                        <th scope="col" className="px-5 py-3 font-semibold">Created</th>
                                        <th scope="col" className="px-5 py-3 text-right font-semibold">Actions</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100">
                                    {visibleJobs.map((job) => (
                                        <tr key={job.id} className="transition-colors hover:bg-slate-50">
                                            <td className="max-w-[520px] px-5 py-4">
                                                <Link href={`/jobs/${job.id}`} className="flex min-w-0 items-center gap-3">
                                                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-600">
                                                        <FileText className="h-4 w-4" />
                                                    </span>
                                                    <span className="min-w-0">
                                                        <span className="block truncate font-semibold text-slate-900">{job.name}</span>
                                                        {job.description && <span className="mt-0.5 block truncate text-sm text-slate-500">{job.description}</span>}
                                                    </span>
                                                </Link>
                                            </td>
                                            <td className="whitespace-nowrap px-5 py-4">
                                                <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${job.status === "completed" ? "bg-green-100 text-green-800" :
                                                    job.status === "processing" ? "bg-blue-100 text-blue-800" :
                                                        "bg-slate-100 text-slate-800"
                                                    }`}>
                                                    {job.status.toUpperCase()}
                                                </span>
                                            </td>
                                            <td className="whitespace-nowrap px-5 py-4 text-slate-500">
                                                <span className="inline-flex items-center">
                                                    <Calendar className="mr-2 h-4 w-4" />
                                                    {new Date(job.created_at).toLocaleDateString()}
                                                </span>
                                            </td>
                                            <td className="px-5 py-4 text-right">
                                                {canDeleteJob(job) && (
                                                    <Button
                                                        variant="outline"
                                                        size="icon"
                                                        aria-label={`Delete ${job.name}`}
                                                        title="Delete job"
                                                        className="h-8 w-8 border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700"
                                                        onClick={() => setDeleteConfirmJob(job)}
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                    </Button>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : (
                    <div className="grid gap-4">
                        {visibleJobs.map((job) => (
                            <div key={job.id} className="flex items-center justify-between rounded-lg border bg-white p-6 shadow-sm transition-shadow hover:shadow-md">
                                <Link href={`/jobs/${job.id}`} className="flex flex-1 cursor-pointer items-center gap-4">
                                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-100 text-blue-600">
                                        <FileText className="h-5 w-5" />
                                    </div>
                                    <div>
                                        <h3 className="text-lg font-semibold">{job.name}</h3>
                                        <p className="text-sm text-slate-500">{job.description}</p>
                                    </div>
                                </Link>
                                <div className="flex items-center gap-4">
                                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${job.status === "completed" ? "bg-green-100 text-green-800" :
                                        job.status === "processing" ? "bg-blue-100 text-blue-800" :
                                            "bg-slate-100 text-slate-800"
                                        }`}>
                                        {job.status.toUpperCase()}
                                    </span>
                                    <div className="flex items-center text-sm text-slate-500">
                                        <Calendar className="mr-2 h-4 w-4" />
                                        {new Date(job.created_at).toLocaleDateString()}
                                    </div>
                                    {canDeleteJob(job) && (
                                        <Button
                                            variant="outline"
                                            size="icon"
                                            aria-label={`Delete ${job.name}`}
                                            title="Delete job"
                                            className="h-8 w-8 border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700"
                                            onClick={() => setDeleteConfirmJob(job)}
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )
            )}

            {!loading && sortedJobs.length > 0 && (
                <div className="flex flex-col items-center gap-2 pt-1">
                    {hasMoreJobs && (
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => setVisibleJobCount((count) => Math.min(count + JOBS_PAGE_SIZE, sortedJobs.length))}
                        >
                            Load more
                        </Button>
                    )}
                    <p className="text-sm text-slate-500">
                        Showing {visibleJobs.length} of {sortedJobs.length} jobs
                    </p>
                </div>
            )}

            {/* Delete Job Confirmation Modal */}
            {deleteConfirmJob && (
                <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center">
                    <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
                        <h3 className="text-lg font-semibold mb-4">Delete Job</h3>
                        <p className="text-slate-600 mb-6">
                            Are you sure you want to delete job <strong>{deleteConfirmJob.name}</strong>?
                            All associated documents will also be deleted. This action cannot be undone.
                        </p>
                        <div className="flex justify-end gap-3">
                            <Button
                                onClick={() => setDeleteConfirmJob(null)}
                                variant="outline"
                                disabled={deletingJob}
                            >
                                Cancel
                            </Button>
                            <Button
                                onClick={handleDeleteJob}
                                variant="destructive"
                                disabled={deletingJob}
                            >
                                {deletingJob ? (
                                    <>
                                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                        Deleting...
                                    </>
                                ) : (
                                    "Delete"
                                )}
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
