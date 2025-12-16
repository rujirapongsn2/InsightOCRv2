/* eslint-disable react-hooks/exhaustive-deps */
"use client"

import Link from "next/link"
// import Image from "next/image" -> Removing unused Image import
import { useEffect, useMemo, useRef, useState } from "react"
import { LayoutDashboard, FileText, Settings, Users, PanelLeftClose, PanelLeftOpen, User as UserIcon, LogOut, Plug } from "lucide-react"
import { useAuth } from "@/components/auth-provider"
import { Logo } from "@/components/logo"

export default function DashboardLayout({
    children,
}: {
    children: React.ReactNode
}) {
    const { user, logout } = useAuth()
    const normalizedRole = useMemo(() => {
        if (!user?.role) return "user"
        return user.role === "documents_admin" ? "manager" : user.role
    }, [user?.role])
    const [collapsed, setCollapsed] = useState(false)
    const [userMenuOpen, setUserMenuOpen] = useState(false)
    const [mobileUserMenuOpen, setMobileUserMenuOpen] = useState(false)
    const userMenuRef = useRef<HTMLDivElement>(null)
    const mobileUserMenuRef = useRef<HTMLDivElement>(null)

    const navItems = [
        { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, roles: ["admin", "manager", "user"] },
        { href: "/jobs", label: "Jobs", icon: FileText, roles: ["admin", "manager", "user"] },
        { href: "/schemas", label: "Schemas", icon: Settings, roles: ["admin", "manager"] },
        { href: "/integrations", label: "Integration", icon: Plug, roles: ["admin", "manager"] },
        { href: "/activity-logs", label: "Activity Logs", icon: FileText, roles: ["admin", "manager", "user"] },
        { href: "/users", label: "Users", icon: Users, roles: ["admin"] },
    ]

    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
                setUserMenuOpen(false)
            }
            if (mobileUserMenuRef.current && !mobileUserMenuRef.current.contains(e.target as Node)) {
                setMobileUserMenuOpen(false)
            }
        }
        document.addEventListener("mousedown", handler)
        return () => document.removeEventListener("mousedown", handler)
    }, [])

    return (
        <div className="flex h-screen bg-slate-50">
            {/* Sidebar */}
            <aside className={`hidden md:flex flex-col bg-white border-r border-slate-200 transition-all duration-200 ${collapsed ? "w-20" : "w-64"}`}>
                <div className="flex items-center justify-between px-4 py-4">
                    <div className={`transition-opacity ${collapsed ? "opacity-0 w-0" : "opacity-100"}`}>
                        <Logo className="text-3xl" />
                    </div>
                    <button
                        className="rounded-md p-2 hover:bg-slate-100 text-slate-600"
                        onClick={() => setCollapsed(!collapsed)}
                        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                    >
                        {collapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
                    </button>
                </div>
                <nav className="px-2 space-y-1 flex-1">
                    {navItems
                        .filter((item) => item.roles.includes(normalizedRole))
                        .map((item) => {
                            const Icon = item.icon
                            return (
                                <Link
                                    key={item.href}
                                    href={item.href}
                                    className="flex items-center gap-3 px-3 py-2 text-slate-600 hover:bg-slate-100 rounded-md"
                                >
                                    <Icon className="h-5 w-5 shrink-0" />
                                    {!collapsed && <span className="truncate">{item.label}</span>}
                                </Link>
                            )
                        })}
                </nav>
                <div className={`px-3 py-6 ${collapsed ? "justify-center flex" : ""}`} ref={userMenuRef}>
                    <button
                        className="flex items-center gap-3 w-full px-3 py-2 rounded-md hover:bg-slate-100 text-slate-700"
                        onClick={() => setUserMenuOpen((v) => !v)}
                        aria-expanded={userMenuOpen}
                        aria-label="User menu"
                    >
                        <UserIcon className="h-5 w-5" />
                        {!collapsed && <span className="truncate">{user?.full_name || user?.email || "Profile"}</span>}
                    </button>
                    {userMenuOpen && (
                        <div className="mt-2 w-full rounded-md border bg-white shadow-sm">
                            {normalizedRole === "admin" && (
                                <Link
                                    href="/settings"
                                    className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 text-slate-700"
                                    onClick={() => setUserMenuOpen(false)}
                                >
                                    <Settings className="h-4 w-4" />
                                    <span>Settings</span>
                                </Link>
                            )}
                            <Link
                                href="/profile"
                                className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 text-slate-700"
                                onClick={() => setUserMenuOpen(false)}
                            >
                                <UserIcon className="h-4 w-4" />
                                <span>Profile</span>
                            </Link>
                            <button
                                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 text-slate-700"
                                onClick={() => {
                                    setUserMenuOpen(false)
                                    logout()
                                }}
                            >
                                <LogOut className="h-4 w-4" />
                                <span>Logout</span>
                            </button>
                        </div>
                    )}
                </div>
            </aside>

            {/* Main Content */}
            <div className="flex-1 flex flex-col">
                <header className="md:hidden flex items-center justify-between px-4 py-3 border-b bg-white">
                    <Logo className="text-2xl" />
                    <div className="flex items-center gap-2">
                        <button
                            className="rounded-md p-2 hover:bg-slate-100 text-slate-600"
                            onClick={() => setCollapsed(!collapsed)}
                            aria-label={collapsed ? "Open menu" : "Close menu"}
                        >
                            {collapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
                        </button>
                        <div className="relative" ref={mobileUserMenuRef}>
                            <button
                                className="rounded-full p-2 hover:bg-slate-100 text-slate-700"
                                onClick={() => setMobileUserMenuOpen((v) => !v)}
                                aria-label="User menu"
                            >
                                <UserIcon className="h-5 w-5" />
                            </button>
                            {mobileUserMenuOpen && (
                                <div className="absolute right-0 mt-2 w-40 rounded-md border bg-white shadow-sm">
                                    {normalizedRole === "admin" && (
                                        <Link
                                            href="/settings"
                                            className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 text-slate-700"
                                            onClick={() => setMobileUserMenuOpen(false)}
                                        >
                                            <Settings className="h-4 w-4" />
                                            <span>Settings</span>
                                        </Link>
                                    )}
                                    <Link
                                        href="/profile"
                                        className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 text-slate-700"
                                        onClick={() => setMobileUserMenuOpen(false)}
                                    >
                                        <UserIcon className="h-4 w-4" />
                                        <span>Profile</span>
                                    </Link>
                                    <button
                                        className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 text-slate-700"
                                        onClick={() => {
                                            setMobileUserMenuOpen(false)
                                            logout()
                                        }}
                                    >
                                        <LogOut className="h-4 w-4" />
                                        <span>Logout</span>
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                </header>
                <main className="flex-1 overflow-y-auto p-8">
                    {children}
                </main>
            </div>
        </div>
    )
}
