/* eslint-disable react-hooks/exhaustive-deps */
"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useMemo, useRef, useState } from "react"
import {
    LayoutDashboard, FileText, Settings, Users,
    PanelLeftClose, PanelLeftOpen, User as UserIcon, LogOut, Plug, Workflow as WorkflowIcon,
} from "lucide-react"
import { useAuth } from "@/components/auth-provider"
import { Logo } from "@/components/logo"

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
    const { user, logout } = useAuth()
    const pathname = usePathname()

    const normalizedRole = useMemo(() => {
        if (!user?.role) return "user"
        return user.role === "documents_admin" ? "manager" : user.role
    }, [user?.role])

    const [collapsed, setCollapsed] = useState(false)
    const [userMenuOpen, setUserMenuOpen] = useState(false)
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
    const [mobileUserMenuOpen, setMobileUserMenuOpen] = useState(false)
    const userMenuRef = useRef<HTMLDivElement>(null)
    const mobileUserMenuRef = useRef<HTMLDivElement>(null)

    const navItems = [
        { href: "/dashboard",     label: "Dashboard",     icon: LayoutDashboard, roles: ["admin", "manager", "user"] },
        { href: "/jobs",          label: "Jobs",           icon: FileText,        roles: ["admin", "manager", "user"] },
        { href: "/schemas",       label: "Schemas",        icon: Settings,        roles: ["admin", "manager"] },
        { href: "/integrations",  label: "Integration",    icon: Plug,            roles: ["admin", "manager"] },
        { href: "/workflows",     label: "Workflow",       icon: WorkflowIcon,    roles: ["admin", "manager", "user"] },
        { href: "/activity-logs", label: "Activity Logs",  icon: FileText,        roles: ["admin", "manager", "user"] },
        { href: "/users",         label: "Users",          icon: Users,           roles: ["admin"] },
    ]

    const isActive = (href: string) =>
        href === "/dashboard" ? pathname === href : pathname.startsWith(href)

    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node))
                setUserMenuOpen(false)
            if (mobileUserMenuRef.current && !mobileUserMenuRef.current.contains(e.target as Node))
                setMobileUserMenuOpen(false)
        }
        document.addEventListener("mousedown", handler)
        return () => document.removeEventListener("mousedown", handler)
    }, [])

    const visibleNav = navItems.filter((item) => item.roles.includes(normalizedRole))

    return (
        <div className="flex h-screen bg-[#F8F9FA]">

            {/* ── Desktop Sidebar ────────────────────────────────────── */}
            <aside
                className={`hidden md:flex flex-col bg-white border-r border-[#E2E8F0] transition-all duration-200 ${
                    collapsed ? "w-[72px]" : "w-60"
                }`}
            >
                {/* Logo row */}
                <div className="flex items-center justify-between px-4 py-4 border-b border-[#E2E8F0]">
                    {!collapsed && (
                        <Link href="/dashboard" className="shrink-0">
                            <Logo />
                        </Link>
                    )}
                    <button
                        className="rounded-full p-2 hover:bg-[#F8F9FA] text-[#778DA9] transition-colors"
                        onClick={() => setCollapsed(!collapsed)}
                        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                    >
                        {collapsed
                            ? <PanelLeftOpen className="h-5 w-5" />
                            : <PanelLeftClose className="h-5 w-5" />}
                    </button>
                </div>

                {/* Nav items */}
                <nav className="flex-1 px-3 py-4 space-y-0.5">
                    {visibleNav.map((item) => {
                        const Icon = item.icon
                        const active = isActive(item.href)
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                                    active
                                        ? "bg-[#EBF4FB] text-[#2786C2] font-semibold"
                                        : "text-[#778DA9] hover:bg-[#F8F9FA] hover:text-[#0D1B2A]"
                                }`}
                            >
                                <Icon className={`h-5 w-5 shrink-0 ${active ? "text-[#2786C2]" : ""}`} />
                                {!collapsed && <span className="truncate">{item.label}</span>}
                                {/* Active left-bar indicator */}
                                {active && !collapsed && (
                                    <span className="ml-auto h-1.5 w-1.5 rounded-full bg-[#2786C2]" />
                                )}
                            </Link>
                        )
                    })}
                </nav>

                {/* User menu */}
                <div className="px-3 py-4 border-t border-[#E2E8F0]" ref={userMenuRef}>
                    <button
                        className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm transition-colors hover:bg-[#F8F9FA] ${
                            collapsed ? "justify-center" : ""
                        }`}
                        onClick={() => setUserMenuOpen((v) => !v)}
                        aria-expanded={userMenuOpen}
                    >
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#EBF4FB] text-[#2786C2]">
                            <UserIcon className="h-4 w-4" />
                        </span>
                        {!collapsed && (
                            <span className="truncate text-[#0D1B2A] font-medium">
                                {user?.full_name || user?.email || "Profile"}
                            </span>
                        )}
                    </button>

                    {userMenuOpen && (
                        <div className="mt-2 rounded-xl border border-[#E2E8F0] bg-white overflow-hidden"
                            style={{ boxShadow: "rgba(0,0,0,0.02) 0 0 0 1px, rgba(0,0,0,0.04) 0 2px 6px 0, rgba(0,0,0,0.10) 0 4px 8px 0" }}>
                            {normalizedRole === "admin" && (
                                <Link
                                    href="/settings"
                                    className="flex items-center gap-2 px-4 py-2.5 text-sm text-[#0D1B2A] hover:bg-[#F8F9FA] transition-colors"
                                    onClick={() => setUserMenuOpen(false)}
                                >
                                    <Settings className="h-4 w-4 text-[#778DA9]" />
                                    <span>Settings</span>
                                </Link>
                            )}
                            <Link
                                href="/profile"
                                className="flex items-center gap-2 px-4 py-2.5 text-sm text-[#0D1B2A] hover:bg-[#F8F9FA] transition-colors"
                                onClick={() => setUserMenuOpen(false)}
                            >
                                <UserIcon className="h-4 w-4 text-[#778DA9]" />
                                <span>Profile</span>
                            </Link>
                            <button
                                className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-[#E53935] hover:bg-red-50 transition-colors"
                                onClick={() => { setUserMenuOpen(false); logout() }}
                            >
                                <LogOut className="h-4 w-4" />
                                <span>Logout</span>
                            </button>
                        </div>
                    )}
                </div>
            </aside>

            {/* ── Main Content ──────────────────────────────────────── */}
            <div className="flex-1 flex flex-col min-w-0">

                {/* Mobile top nav */}
                <header className="md:hidden flex items-center justify-between px-4 py-3 border-b border-[#E2E8F0] bg-white">
                    <Link href="/dashboard">
                        <Logo />
                    </Link>
                    <div className="flex items-center gap-2">
                        <button
                            className="rounded-full p-2 hover:bg-[#F8F9FA] text-[#778DA9]"
                            onClick={() => setMobileMenuOpen((v) => !v)}
                            aria-label="Toggle menu"
                        >
                            {mobileMenuOpen
                                ? <PanelLeftClose className="h-5 w-5" />
                                : <PanelLeftOpen className="h-5 w-5" />}
                        </button>
                        <div className="relative" ref={mobileUserMenuRef}>
                            <button
                                className="flex h-9 w-9 items-center justify-center rounded-full bg-[#EBF4FB] text-[#2786C2]"
                                onClick={() => setMobileUserMenuOpen((v) => !v)}
                                aria-label="User menu"
                            >
                                <UserIcon className="h-4 w-4" />
                            </button>
                            {mobileUserMenuOpen && (
                                <div className="absolute right-0 mt-2 w-44 rounded-xl border border-[#E2E8F0] bg-white overflow-hidden z-50"
                                    style={{ boxShadow: "rgba(0,0,0,0.02) 0 0 0 1px, rgba(0,0,0,0.04) 0 2px 6px 0, rgba(0,0,0,0.10) 0 4px 8px 0" }}>
                                    {normalizedRole === "admin" && (
                                        <Link href="/settings" className="flex items-center gap-2 px-4 py-2.5 text-sm text-[#0D1B2A] hover:bg-[#F8F9FA]"
                                            onClick={() => setMobileUserMenuOpen(false)}>
                                            <Settings className="h-4 w-4 text-[#778DA9]" />
                                            Settings
                                        </Link>
                                    )}
                                    <Link href="/profile" className="flex items-center gap-2 px-4 py-2.5 text-sm text-[#0D1B2A] hover:bg-[#F8F9FA]"
                                        onClick={() => setMobileUserMenuOpen(false)}>
                                        <UserIcon className="h-4 w-4 text-[#778DA9]" />
                                        Profile
                                    </Link>
                                    <button className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-[#E53935] hover:bg-red-50"
                                        onClick={() => { setMobileUserMenuOpen(false); logout() }}>
                                        <LogOut className="h-4 w-4" />
                                        Logout
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                </header>

                {/* Mobile slide-down nav */}
                {mobileMenuOpen && (
                    <nav className="md:hidden bg-white border-b border-[#E2E8F0] px-4 py-3 space-y-0.5">
                        {visibleNav.map((item) => {
                            const Icon = item.icon
                            const active = isActive(item.href)
                            return (
                                <Link
                                    key={item.href}
                                    href={item.href}
                                    className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                                        active
                                            ? "bg-[#EBF4FB] text-[#2786C2] font-semibold"
                                            : "text-[#778DA9] hover:bg-[#F8F9FA] hover:text-[#0D1B2A]"
                                    }`}
                                    onClick={() => setMobileMenuOpen(false)}
                                >
                                    <Icon className="h-5 w-5 shrink-0" />
                                    <span>{item.label}</span>
                                </Link>
                            )
                        })}
                    </nav>
                )}

                <main className={
                    /^\/workflows\/[^/]+/.test(pathname)
                        ? "flex-1 overflow-hidden" // workflow builder is full-bleed
                        : "flex-1 overflow-y-auto p-6 md:p-8"
                }>
                    {children}
                </main>
            </div>
        </div>
    )
}
