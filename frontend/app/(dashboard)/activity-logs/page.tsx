"use client"

import { useState, useEffect } from "react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { ChevronLeft, ChevronRight, RefreshCw, LogIn, LogOut, FileText, Users, Settings, Folder, Eye, Edit, Trash2, Plus, Send, Download, Database } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

interface ActivityLog {
    id: string
    user_id: string
    user_email: string | null
    user_name: string | null
    action: string
    resource_type: string | null
    resource_id: string | null
    details: Record<string, any> | null
    ip_address: string | null
    created_at: string
}

const actionIcons: Record<string, any> = {
    // Auth
    login: LogIn,
    logout: LogOut,
    login_failed: LogIn,

    // CREATE
    create_job: Plus,
    create_user: Plus,
    create_schema: Plus,
    create_integration: Plus,
    upload_document: FileText,

    // READ
    view_document: Eye,
    view_job: Eye,
    view_schema: Eye,
    view_integration: Eye,
    view_settings: Eye,

    // UPDATE
    update_job: Edit,
    update_document: Edit,
    update_schema: Edit,
    update_integration: Edit,
    update_user: Edit,
    update_settings: Edit,
    review_document: Edit,
    process_document: Settings,

    // DELETE
    delete_document: Trash2,
    delete_job: Trash2,
    delete_schema: Trash2,
    delete_integration: Trash2,
    delete_user: Trash2,

    // OTHER
    send_to_integration: Send,
    export_data: Download,
}

const actionColors: Record<string, string> = {
    // Auth
    login: "bg-green-100 text-green-800 border-green-200",
    logout: "bg-slate-100 text-slate-800 border-slate-200",
    login_failed: "bg-red-100 text-red-800 border-red-200",

    // CREATE
    create_job: "bg-blue-100 text-blue-800 border-blue-200",
    create_user: "bg-indigo-100 text-indigo-800 border-indigo-200",
    create_schema: "bg-cyan-100 text-cyan-800 border-cyan-200",
    create_integration: "bg-violet-100 text-violet-800 border-violet-200",
    upload_document: "bg-blue-100 text-blue-800 border-blue-200",

    // READ
    view_document: "bg-slate-100 text-slate-700 border-slate-200",
    view_job: "bg-slate-100 text-slate-700 border-slate-200",
    view_schema: "bg-slate-100 text-slate-700 border-slate-200",
    view_integration: "bg-slate-100 text-slate-700 border-slate-200",
    view_settings: "bg-slate-100 text-slate-700 border-slate-200",

    // UPDATE
    update_job: "bg-amber-100 text-amber-800 border-amber-200",
    update_document: "bg-amber-100 text-amber-800 border-amber-200",
    update_schema: "bg-amber-100 text-amber-800 border-amber-200",
    update_integration: "bg-amber-100 text-amber-800 border-amber-200",
    update_user: "bg-amber-100 text-amber-800 border-amber-200",
    update_settings: "bg-amber-100 text-amber-800 border-amber-200",
    review_document: "bg-teal-100 text-teal-800 border-teal-200",
    process_document: "bg-purple-100 text-purple-800 border-purple-200",

    // DELETE
    delete_document: "bg-red-100 text-red-800 border-red-200",
    delete_job: "bg-red-100 text-red-800 border-red-200",
    delete_schema: "bg-red-100 text-red-800 border-red-200",
    delete_integration: "bg-red-100 text-red-800 border-red-200",
    delete_user: "bg-red-100 text-red-800 border-red-200",

    // OTHER
    send_to_integration: "bg-emerald-100 text-emerald-800 border-emerald-200",
    export_data: "bg-sky-100 text-sky-800 border-sky-200",
}

export default function ActivityLogsPage() {
    const { user } = useAuth()
    const apiBase = getApiBaseUrl()
    const [logs, setLogs] = useState<ActivityLog[]>([])
    const [loading, setLoading] = useState(true)
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(0)
    const [actionFilter, setActionFilter] = useState<string>("")
    const [actionTypes, setActionTypes] = useState<string[]>([])
    const limit = 20

    const isAdmin = user?.role === "admin"

    const fetchLogs = async () => {
        setLoading(true)
        try {
            const token = localStorage.getItem("token")
            const params = new URLSearchParams({
                skip: String(page * limit),
                limit: String(limit),
            })
            if (actionFilter) params.set("action", actionFilter)

            const res = await fetch(`${apiBase}/activity-logs?${params}`, {
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            })
            if (res.ok) {
                const data = await res.json()
                setLogs(data.items)
                setTotal(data.total)
            }
        } catch (error) {
            console.error("Failed to fetch activity logs", error)
        } finally {
            setLoading(false)
        }
    }

    const fetchActionTypes = async () => {
        try {
            const token = localStorage.getItem("token")
            const res = await fetch(`${apiBase}/activity-logs/actions`, {
                headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            })
            if (res.ok) {
                const data = await res.json()
                setActionTypes(data)
            }
        } catch (error) {
            console.error("Failed to fetch action types", error)
        }
    }

    useEffect(() => {
        fetchLogs()
        fetchActionTypes()
    }, [page, actionFilter])

    const formatDate = (dateString: string) => {
        const date = new Date(dateString)
        return date.toLocaleString("th-TH", {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        })
    }

    const formatAction = (action: string) => {
        return action.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())
    }

    const totalPages = Math.ceil(total / limit)

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-slate-800">Activity Logs</h1>
                    <p className="text-slate-500 text-sm mt-1">
                        {isAdmin ? "View all user activities" : "View your activity history"}
                    </p>
                </div>
                <Button onClick={fetchLogs} variant="outline" disabled={loading}>
                    <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
                    Refresh
                </Button>
            </div>

            {/* Filters */}
            <div className="flex gap-4 items-center">
                <div className="flex items-center gap-2">
                    <label className="text-sm text-slate-600">Filter by Action:</label>
                    <select
                        className="h-9 rounded-md border border-slate-200 bg-white px-3 py-1 text-sm"
                        value={actionFilter}
                        onChange={(e) => {
                            setActionFilter(e.target.value)
                            setPage(0)
                        }}
                    >
                        <option value="">All Actions</option>
                        {actionTypes.map(action => (
                            <option key={action} value={action}>{formatAction(action)}</option>
                        ))}
                    </select>
                </div>
                <span className="text-sm text-slate-500">
                    Showing {logs.length} of {total} logs
                </span>
            </div>

            {/* Table */}
            <div className="rounded-lg border bg-white shadow-sm overflow-hidden">
                <table className="w-full text-sm">
                    <thead className="bg-slate-50 border-b">
                        <tr>
                            <th className="text-left px-4 py-3 font-medium text-slate-600">Timestamp</th>
                            {isAdmin && <th className="text-left px-4 py-3 font-medium text-slate-600">User</th>}
                            <th className="text-left px-4 py-3 font-medium text-slate-600">Action</th>
                            <th className="text-left px-4 py-3 font-medium text-slate-600">Resource</th>
                            <th className="text-left px-4 py-3 font-medium text-slate-600">Details</th>
                            <th className="text-left px-4 py-3 font-medium text-slate-600">IP Address</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr>
                                <td colSpan={isAdmin ? 6 : 5} className="text-center py-8 text-slate-500">
                                    Loading...
                                </td>
                            </tr>
                        ) : logs.length === 0 ? (
                            <tr>
                                <td colSpan={isAdmin ? 6 : 5} className="text-center py-8 text-slate-500">
                                    No activity logs found
                                </td>
                            </tr>
                        ) : (
                            logs.map((log) => {
                                const IconComponent = actionIcons[log.action] || FileText
                                const colorClass = actionColors[log.action] || "bg-slate-100 text-slate-800 border-slate-200"
                                return (
                                    <tr key={log.id} className="border-b hover:bg-slate-50">
                                        <td className="px-4 py-3 text-slate-600">{formatDate(log.created_at)}</td>
                                        {isAdmin && (
                                            <td className="px-4 py-3">
                                                <div className="font-medium">{log.user_name || "Unknown"}</div>
                                                <div className="text-xs text-slate-500">{log.user_email}</div>
                                            </td>
                                        )}
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${colorClass}`}>
                                                <IconComponent className="h-3.5 w-3.5" />
                                                {formatAction(log.action)}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-slate-600">
                                            {log.resource_type ? (
                                                <span className="capitalize">{log.resource_type}</span>
                                            ) : (
                                                <span className="text-slate-400">-</span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-slate-600 max-w-[200px] truncate">
                                            {log.details ? (
                                                <span title={JSON.stringify(log.details)}>
                                                    {Object.entries(log.details).map(([k, v]) => `${k}: ${v}`).join(", ")}
                                                </span>
                                            ) : (
                                                <span className="text-slate-400">-</span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-slate-500 font-mono text-xs">
                                            {log.ip_address || "-"}
                                        </td>
                                    </tr>
                                )
                            })
                        )}
                    </tbody>
                </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex justify-between items-center">
                    <span className="text-sm text-slate-500">
                        Page {page + 1} of {totalPages}
                    </span>
                    <div className="flex gap-2">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPage(p => Math.max(0, p - 1))}
                            disabled={page === 0}
                        >
                            <ChevronLeft className="h-4 w-4 mr-1" />
                            Previous
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPage(p => p + 1)}
                            disabled={page >= totalPages - 1}
                        >
                            Next
                            <ChevronRight className="h-4 w-4 ml-1" />
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}
