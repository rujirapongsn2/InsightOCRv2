"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useAuth } from "@/components/auth-provider"
import { getApiBaseUrl } from "@/lib/api"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ArrowUpRight, FileText, Plug, Settings } from "lucide-react"

type DailyUsage = { day: string; count: number }
type SchemaUsage = { name: string; count: number }
type JobItem = { id: string; name: string; status: string; updated_at: string; created_at: string; schema_id?: string | null }

type DashboardStats = {
    daily_usage: DailyUsage[]
    schema_usage: SchemaUsage[]
    recent_jobs: JobItem[]
}

const dateFormatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
})

const formatDateTime = (value: string) => dateFormatter.format(new Date(value))

const quickLinks = [
    { title: "Jobs", href: "/jobs", icon: FileText },
    { title: "Schemas", href: "/schemas", icon: Settings },
    { title: "Integration", href: "/integrations", icon: Plug },
]

// Job status vocabulary matches the review flow: amber = waiting for a human.
const jobStatusBadge: Record<string, string> = {
    processing: "bg-blue-50 text-blue-700 border-blue-200",
    queued: "bg-slate-50 text-slate-600 border-slate-200",
    extraction_completed: "bg-amber-50 text-amber-800 border-amber-200",
    review: "bg-amber-50 text-amber-800 border-amber-200",
    reviewed: "bg-emerald-50 text-emerald-800 border-emerald-200",
}

export default function DashboardPage() {
    const { user } = useAuth()
    const [stats, setStats] = useState<DashboardStats | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        const fetchData = async () => {
            setError(null)
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
            if (!token) {
                setLoading(false)
                return
            }
            const apiUrl = getApiBaseUrl()
            try {
                const res = await fetch(`${apiUrl}/dashboard/stats`, {
                    headers: { Authorization: `Bearer ${token}` },
                })
                if (!res.ok) {
                    throw new Error("Failed to load dashboard data")
                }
                setStats(await res.json())
            } catch (err) {
                console.error(err)
                setError("Unable to load dashboard data. Check that the API is reachable, then reload this page.")
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [])

    const usageDisplay = useMemo(() => {
        if (!stats?.daily_usage) return []
        return stats.daily_usage.map((d) => ({
            label: d.day.slice(5).replace("-", "/"),
            count: d.count,
            isToday: d.day === new Date().toISOString().slice(0, 10),
        }))
    }, [stats])

    const weekTotal = useMemo(() => usageDisplay.reduce((sum, d) => sum + d.count, 0), [usageDisplay])
    const maxUsage = useMemo(() => (usageDisplay.length ? Math.max(...usageDisplay.map((d) => d.count)) : 1), [usageDisplay])
    const maxSchema = useMemo(() => (stats?.schema_usage?.length ? Math.max(...stats.schema_usage.map((s) => s.count)) : 1), [stats])

    return (
        <div className="space-y-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                    <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
                    <p className="mt-1 text-sm text-slate-500">
                        {weekTotal} document{weekTotal === 1 ? "" : "s"} processed in the last 7 days
                        {user?.full_name ? ` · ${user.full_name}` : ""}
                    </p>
                </div>
                <nav aria-label="Quick links" className="flex items-center gap-1">
                    {quickLinks.map((link) => {
                        const Icon = link.icon
                        return (
                            <Link key={link.href} href={link.href}
                                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 px-2.5 text-xs font-medium text-slate-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700">
                                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                                {link.title}
                                <ArrowUpRight className="h-3 w-3 opacity-50" aria-hidden="true" />
                            </Link>
                        )
                    })}
                </nav>
            </div>

            {error && (
                <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                    {error}
                </div>
            )}

            {loading ? (
                <div aria-busy="true" aria-label="Loading dashboard" className="space-y-6">
                    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
                        <div className="lg:col-span-2">
                            <div className="h-5 w-32 animate-pulse rounded bg-slate-100" />
                            <div className="mt-4 flex h-48 items-end gap-3">
                                {Array.from({ length: 7 }).map((_, i) => (
                                    <div key={i} className="h-full flex-1 animate-pulse rounded-t bg-slate-100" style={{ animationDelay: `${i * 60}ms` }} />
                                ))}
                            </div>
                        </div>
                        <div className="space-y-3">
                            {Array.from({ length: 5 }).map((_, i) => (
                                <div key={i} className="h-8 animate-pulse rounded bg-slate-100" style={{ animationDelay: `${i * 60}ms` }} />
                            ))}
                        </div>
                    </div>
                    <div className="h-16 animate-pulse rounded-lg bg-slate-100" />
                </div>
            ) : (
                <>
                    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
                        <Card className="lg:col-span-2">
                            <CardHeader>
                                <CardTitle>Daily usage</CardTitle>
                                <CardDescription>Documents processed per day</CardDescription>
                            </CardHeader>
                            <CardContent>
                                {usageDisplay.length === 0 || weekTotal === 0 ? (
                                    <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 text-sm text-slate-500">
                                        <span>No documents processed this week</span>
                                        <Link href="/jobs/create" className="text-blue-700 underline-offset-4 hover:underline">Create a job to get started</Link>
                                    </div>
                                ) : (
                                    <div className="flex h-48 items-end gap-3" role="img" aria-label="Documents processed per day over the last 7 days">
                                        {usageDisplay.map((item) => {
                                            const height = item.count === 0 ? 2 : Math.max((item.count / maxUsage) * 100, 6)
                                            return (
                                                <div key={item.label} className="flex h-full flex-1 flex-col items-center justify-end gap-1.5">
                                                    <span className="text-xs font-medium tabular-nums text-slate-600">{item.count}</span>
                                                    <div
                                                        className={`w-full max-w-10 rounded-t-sm ${item.isToday ? "bg-blue-600" : item.count === 0 ? "bg-slate-200" : "bg-blue-300"}`}
                                                        style={{ height: `${height}%` }}
                                                        aria-label={`${item.label}: ${item.count}`}
                                                    />
                                                    <span className={`text-xs ${item.isToday ? "font-semibold text-slate-800" : "text-slate-500"}`}>{item.label}</span>
                                                </div>
                                            )
                                        })}
                                    </div>
                                )}
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader>
                                <CardTitle>Schema usage</CardTitle>
                                <CardDescription>Most used schemas this week</CardDescription>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                {(!stats?.schema_usage || stats.schema_usage.length === 0) && (
                                    <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-slate-200 text-sm text-slate-500">
                                        No schema usage yet
                                    </div>
                                )}
                                {(stats?.schema_usage || []).slice(0, 6).map((schema) => {
                                    const percent = Math.round((schema.count / maxSchema) * 100)
                                    return (
                                        <div key={schema.name} className="space-y-1.5">
                                            <div className="flex items-baseline justify-between gap-3 text-sm">
                                                <span className="truncate font-medium text-slate-800" title={schema.name}>{schema.name}</span>
                                                <span className="shrink-0 text-xs tabular-nums text-slate-500">{schema.count} · {percent}%</span>
                                            </div>
                                            <div className="h-1.5 rounded-full bg-slate-100">
                                                <div className="h-1.5 rounded-full bg-blue-600" style={{ width: `${percent}%` }} />
                                            </div>
                                        </div>
                                    )
                                })}
                                {(stats?.schema_usage?.length || 0) > 6 && (
                                    <Link href="/schemas" className="inline-block pt-1 text-xs text-blue-700 underline-offset-4 hover:underline">
                                        View all schemas →
                                    </Link>
                                )}
                            </CardContent>
                        </Card>
                    </div>

                    <Card>
                        <CardHeader>
                            <CardTitle>Recent jobs</CardTitle>
                            <CardDescription>Latest runs and their status</CardDescription>
                        </CardHeader>
                        <CardContent className="divide-y divide-slate-100">
                            {(!stats?.recent_jobs || stats.recent_jobs.length === 0) && (
                                <div className="flex h-24 items-center justify-center text-sm text-slate-500">No jobs yet</div>
                            )}
                            {stats?.recent_jobs?.map((job) => (
                                <Link key={job.id} href={`/jobs/${job.id}`}
                                    className="-mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-3 transition-colors hover:bg-slate-50">
                                    <div className="min-w-0">
                                        <div className="truncate font-medium text-slate-900">{job.name || "Untitled job"}</div>
                                        <div className="mt-0.5 text-xs tabular-nums text-slate-500">{formatDateTime(job.updated_at || job.created_at)}</div>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-3">
                                        <span className={`rounded-md border px-2 py-0.5 text-xs font-medium ${jobStatusBadge[job.status] || "bg-slate-50 text-slate-600 border-slate-200"}`}>
                                            {job.status.replace(/_/g, " ")}
                                        </span>
                                        <ArrowUpRight className="h-4 w-4 text-slate-400" aria-hidden="true" />
                                    </div>
                                </Link>
                            ))}
                        </CardContent>
                    </Card>
                </>
            )}
        </div>
    )
}
