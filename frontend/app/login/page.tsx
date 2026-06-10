"use client"

import { useState } from "react"
import { Logo } from "@/components/logo"
import { useAuth } from "@/components/auth-provider"
import { getApiBaseUrl } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AlertCircle, ShieldCheck, Cpu, Zap } from "lucide-react"

export default function LoginPage() {
    const { login } = useAuth()
    const [email, setEmail] = useState("")
    const [password, setPassword] = useState("")
    const [error, setError] = useState("")
    const [loading, setLoading] = useState(false)

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError("")
        setLoading(true)

        try {
            const formData = new URLSearchParams()
            formData.append("username", email)
            formData.append("password", password)

            const res = await fetch(`${getApiBaseUrl()}/login/access-token`, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: formData,
            })

            if (res.ok) {
                const data = await res.json()
                login(data.access_token)
            } else {
                const errData = await res.json()
                setError(errData.detail || "Login failed")
            }
        } catch {
            setError("An error occurred. Please try again.")
        } finally {
            setLoading(false)
        }
    }

    const features = [
        { icon: ShieldCheck, label: "Private AI Environment",   color: "bg-[#EBF4FB] text-[#2786C2]" },
        { icon: Zap,         label: "Enterprise-Grade Security", color: "bg-[#FFF4EC] text-[#F3903F]" },
        { icon: Cpu,         label: "Agent-Ready Data Platform", color: "bg-[#F4FAE8] text-[#7DAF1A]" },
    ]

    return (
        <div className="min-h-screen bg-[#F8F9FA] flex">

            {/* ── Left panel — Brand hero ──────────────────────────── */}
            <div className="hidden lg:flex lg:w-1/2 xl:w-3/5 flex-col justify-between p-12 bg-white border-r border-[#E2E8F0]">
                {/* Top wordmark */}
                <Logo className="text-4xl" />

                {/* Center copy */}
                <div className="space-y-8 max-w-lg">
                    {/* Tier badge */}
                    <div className="inline-flex items-center gap-2 rounded-full border border-[#E2E8F0] bg-[#F8F9FA] px-4 py-1.5">
                        <span className="h-2 w-2 rounded-full bg-[#A9CB2E]" />
                        <span className="text-sm font-medium text-[#778DA9]">
                            Intelligence AI Application by Softnix
                        </span>
                    </div>

                    <h1 className="text-4xl font-bold leading-tight text-[#0D1B2A]">
                        Your Secure Workspace for{" "}
                        <span className="text-[#2786C2]">Intelligent Documents</span>
                    </h1>

                    <p className="text-base text-[#778DA9] leading-relaxed">
                        Transform raw documents into trusted, structured data with an
                        AI-powered extraction pipeline built for enterprise teams.
                    </p>

                    {/* Feature pills */}
                    <div className="flex flex-wrap gap-3">
                        {features.map(({ icon: Icon, label, color }) => (
                            <div
                                key={label}
                                className="flex items-center gap-2 rounded-full border border-[#E2E8F0] bg-white px-4 py-2"
                            >
                                <span className={`flex h-6 w-6 items-center justify-center rounded-full ${color}`}>
                                    <Icon className="h-3.5 w-3.5" />
                                </span>
                                <span className="text-sm font-medium text-[#0D1B2A]">{label}</span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Bottom brand stripe */}
                <div className="h-1 w-24 rounded-full"
                    style={{ background: "linear-gradient(135deg, #F3903F 0%, #FDC70C 50%, #A9CB2E 100%)" }}
                />
            </div>

            {/* ── Right panel — Login form ─────────────────────────── */}
            <div className="flex-1 flex items-center justify-center p-8">
                <div className="w-full max-w-sm space-y-8">

                    {/* Mobile-only logo */}
                    <div className="lg:hidden">
                        <Logo className="text-3xl" />
                    </div>

                    <div className="space-y-1">
                        <h2 className="text-2xl font-bold text-[#0D1B2A]">Welcome back</h2>
                        <p className="text-sm text-[#778DA9]">Sign in to your workspace</p>
                    </div>

                    <form className="space-y-5" onSubmit={handleSubmit}>
                        <div className="space-y-4">
                            <div className="space-y-1.5">
                                <label htmlFor="email" className="block text-sm font-semibold text-[#0D1B2A]">
                                    Email address
                                </label>
                                <Input
                                    id="email"
                                    type="email"
                                    required
                                    placeholder="you@company.com"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    error={!!error}
                                />
                            </div>

                            <div className="space-y-1.5">
                                <div className="flex items-center justify-between">
                                    <label htmlFor="password" className="text-sm font-semibold text-[#0D1B2A]">
                                        Password
                                    </label>
                                    <a href="#" className="text-sm text-[#2786C2] hover:text-[#1A5A8A] transition-colors">
                                        Forgot password?
                                    </a>
                                </div>
                                <Input
                                    id="password"
                                    type="password"
                                    required
                                    placeholder="••••••••"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    error={!!error}
                                />
                            </div>
                        </div>

                        {error && (
                            <div className="flex items-center gap-2 rounded-lg border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-sm text-[#E53935]">
                                <AlertCircle className="h-4 w-4 shrink-0" />
                                {error}
                            </div>
                        )}

                        <Button type="submit" size="lg" className="w-full" disabled={loading}>
                            {loading ? "Signing in…" : "Sign in"}
                        </Button>
                    </form>

                    <p className="text-center text-xs text-[#9BA8B4]">
                        By signing in you agree to the Softnix{" "}
                        <a href="#" className="text-[#5EADD6] hover:underline">Terms of Service</a>
                        {" "}and{" "}
                        <a href="#" className="text-[#5EADD6] hover:underline">Privacy Policy</a>.
                    </p>
                </div>
            </div>
        </div>
    )
}
