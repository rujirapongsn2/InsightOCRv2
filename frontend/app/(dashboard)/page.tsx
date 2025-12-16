"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useAuth } from "@/components/auth-provider"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ArrowRight, FileText, LayoutDashboard, Plug, Settings } from "lucide-react"

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
            const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"
            try {
                const res = await fetch(`${apiUrl}/dashboard/stats`, {
                    headers: { Authorization: `Bearer ${token}` },
                })

                if (!res.ok) {
                    throw new Error("Failed to load dashboard data")
                }

                const data = await res.json()
                setStats(data)
            } catch (err) {
                console.error(err)
                setError("Unable to load dashboard data")
            } finally {
                setLoading(false)
            }
        }

        fetchData()
    }, [])

    const quickLinks = [
        {
            title: "Jobs",
            description: "View and manage OCR processing jobs",
            href: "/jobs",
            icon: FileText,
        },
        {
            title: "Schemas",
            description: "Manage extraction schemas for different document types",
            href: "/schemas",
            icon: Settings,
        },
        {
            title: "Integration",
            description: "Connect workflows, APIs, and LLM destinations",
            href: "/integrations",
            icon: Plug,
        },
    ]

    const statusBadge = (status: string) => {
        const map: Record<string, string> = {
            processing: "bg-blue-100 text-blue-800",
            extraction_completed: "bg-emerald-100 text-emerald-800",
            reviewed: "bg-purple-100 text-purple-800",
        }
        return map[status] || "bg-slate-100 text-slate-800"
    }

    const usageDisplay = useMemo(() => {
        if (!stats?.daily_usage) return []
        return stats.daily_usage.map((d) => ({
            label: d.day.slice(5).replace("-", "/"),
            count: d.count,
        }))
    }, [stats])

    const maxUsage = useMemo(() => (usageDisplay.length ? Math.max(...usageDisplay.map((d) => d.count)) : 1), [usageDisplay])
    const maxSchema = useMemo(() => (stats?.schema_usage?.length ? Math.max(...stats.schema_usage.map((s) => s.count)) : 1), [stats])

    return (
        <div className="space-y-8">
            <div className="flex flex-col gap-2">
                <h1 className="text-3xl font-bold text-slate-900 flex items-center gap-2">
                    <LayoutDashboard className="h-7 w-7 text-slate-700" />
                    Dashboard
                </h1>
                <p className="text-slate-600">
                    Usage snapshot and recent activity for your OCR pipeline{user?.full_name ? `, ${user.full_name}` : ""}.
                </p>
            </div>

            {error && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 px-4 py-3">
                    {error}
                </div>
            )}

            <div>
                <h2 className="text-xl font-semibold text-slate-900 mb-4">Quick Access</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {quickLinks.map((link) => {
                        const Icon = link.icon
                        return (
                            <Card key={link.href} className="hover:shadow-lg transition-shadow">
                                <CardHeader>
                                    <div className="flex items-center space-x-3">
                                        <div className="p-2 bg-slate-100 rounded-lg">
                                            <Icon className="h-6 w-6 text-slate-700" />
                                        </div>
                                        <CardTitle>{link.title}</CardTitle>
                                    </div>
                                    <CardDescription>{link.description}</CardDescription>
                                </CardHeader>
                                <CardContent>
                                    <Link href={link.href}>
                                        <Button variant="outline" className="w-full">
                                            Go to {link.title}
                                            <ArrowRight className="ml-2 h-4 w-4" />
                                        </Button>
                                    </Link>
                                </CardContent>
                            </Card>
                        )
                    })}
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <Card className="lg:col-span-2">
                    <CardHeader>
                        <CardTitle>Daily Usage</CardTitle>
                        <CardDescription>Number of document runs per day (last 7 days)</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="grid grid-cols-7 gap-3">
                            {usageDisplay.map((item) => {
                                const height = maxUsage === 0 ? 0 : (item.count / maxUsage) * 180
                                return (
                                    <div key={item.label} className="flex flex-col items-center gap-2">
                                        <div className="h-44 w-full bg-slate-100 rounded-lg flex items-end justify-center">
                                            <div
                                                className="w-full rounded-md"
                                                style={{
                                                    height: `${height}px`,
                                                    minHeight: "4px",
                                                    background: "linear-gradient(135deg, #F3903F 0%, #FDC70C 33%, #A9CB2E 66%, #2786C2 100%)"
                                                }}
                                                aria-label={`${item.label} usage ${item.count}`}
                                            />
                                        </div>
                                        <div className="text-xs text-slate-600">{item.label}</div>
                                        <div className="text-sm font-semibold text-slate-800">{item.count}</div>
                                    </div>
                                )
                            })}
                            {usageDisplay.length === 0 && !loading && (
                                <div className="col-span-7 text-sm text-slate-500">No usage data yet</div>
                            )}
                        </div>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader>
                        <CardTitle>Schema Usage</CardTitle>
                        <CardDescription>Most used schemas this week</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        {(!stats?.schema_usage || stats.schema_usage.length === 0) && !loading && <div className="text-sm text-slate-500">No schema usage yet</div>}
                        {stats?.schema_usage?.map((schema) => {
                            const percent = Math.round((schema.count / maxSchema) * 100)
                            return (
                                <div key={schema.name} className="space-y-1">
                                    <div className="flex items-center justify-between text-sm">
                                        <span className="font-medium text-slate-800">{schema.name}</span>
                                        <span className="text-slate-500">{schema.count}</span>
                                    </div>
                                    <div className="h-2 rounded-full bg-slate-100">
                                        <div
                                            className="h-2 rounded-full"
                                            style={{
                                                width: `${percent}%`,
                                                background: "linear-gradient(135deg, #F3903F 0%, #FDC70C 33%, #A9CB2E 66%, #2786C2 100%)"
                                            }}
                                        />
                                    </div>
                                </div>
                            )
                        })}
                    </CardContent>
                </Card>
            </div>

            <Card>
                <CardHeader>
                    <CardTitle>Recent Jobs</CardTitle>
                    <CardDescription>Latest job runs and their status</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                    {(!stats?.recent_jobs || stats.recent_jobs.length === 0) && !loading && <div className="text-sm text-slate-500">No jobs yet</div>}
                    {stats?.recent_jobs?.map((job) => (
                        <div key={job.id} className="flex flex-col md:flex-row md:items-center md:justify-between gap-2 border rounded-lg px-4 py-3">
                            <div>
                                <div className="font-semibold text-slate-900">{job.name || "Untitled Job"}</div>
                                <div className="text-xs text-slate-500">{formatDateTime(job.updated_at || job.created_at)}</div>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className={`px-3 py-1 rounded-full text-xs font-medium ${statusBadge(job.status)}`}>
                                    {job.status.replace("_", " ")}
                                </span>
                                <Link href={`/jobs/${job.id}`}>
                                    <Button variant="outline" size="sm">
                                        View
                                    </Button>
                                </Link>
                            </div>
                        </div>
                    ))}
                </CardContent>
            </Card>

            {loading && (
                <div className="fixed bottom-4 right-4 rounded-md bg-white/90 shadow px-3 py-2 text-sm text-slate-600 border">
                    Loading dashboard data...
                </div>
            )}
        </div>
    )
}
