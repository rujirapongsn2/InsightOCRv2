"use client"

import { useState } from "react"
// import Image from "next/image" -> Removing unused Image import
import { Logo } from "@/components/logo"
import { useAuth } from "@/components/auth-provider"
import { getApiBaseUrl } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AlertCircle } from "lucide-react"

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
                body: formData
            })

            if (res.ok) {
                const data = await res.json()
                login(data.access_token)
            } else {
                const errData = await res.json()
                setError(errData.detail || "Login failed")
            }
        } catch (err) {
            setError("An error occurred")
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="relative min-h-screen bg-gradient-to-br from-slate-50 via-sky-50/60 to-white text-slate-900 overflow-hidden">
            <div className="absolute inset-0 pointer-events-none">
                <div className="absolute -left-32 -top-32 h-80 w-80 rounded-full bg-sky-200/30 blur-3xl" />
                <div className="absolute bottom-0 right-0 h-96 w-96 rounded-full bg-amber-100/40 blur-3xl" />
            </div>
            <div className="relative z-10 flex items-center justify-center px-4 py-12">
                <div className="w-full max-w-6xl grid grid-cols-1 lg:grid-cols-2 gap-10 lg:gap-12 items-center">
                    <div className="space-y-6">
                        <div className="inline-flex items-center gap-3 rounded-full bg-white/80 px-4 py-2 shadow-sm ring-1 ring-slate-200/60 backdrop-blur">
                            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                            <span className="text-sm font-medium text-slate-700">Intelligence AI Application by Softnix</span>
                        </div>
                        <h1 className="text-4xl font-bold leading-tight text-slate-900">
                            Your Secure Workspace for Intelligent Documents
                        </h1>
                        <p className="text-lg text-slate-600 leading-relaxed">
                            Access your AI-powered document workspace to transform information into trusted, actionable data.
                        </p>
                        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
                            <div className="flex items-center gap-2 px-3 py-2 rounded-full bg-white/80 shadow-sm ring-1 ring-slate-200/60 backdrop-blur">
                                <span className="h-2 w-2 rounded-full bg-sky-500" />
                                Private AI Environment
                            </div>
                            <div className="flex items-center gap-2 px-3 py-2 rounded-full bg-white/80 shadow-sm ring-1 ring-slate-200/60 backdrop-blur">
                                <span className="h-2 w-2 rounded-full bg-amber-500" />
                                Enterprise-Grade Security
                            </div>
                            <div className="flex items-center gap-2 px-3 py-2 rounded-full bg-white/80 shadow-sm ring-1 ring-slate-200/60 backdrop-blur">
                                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                                Agent-Ready Data Platform
                            </div>
                        </div>
                    </div>

                    <div className="bg-white/95 backdrop-blur-xl rounded-2xl shadow-xl ring-1 ring-slate-200/70 p-8 md:p-10 space-y-8 max-w-md w-full mx-auto">
                        <div className="text-center space-y-3">
                            <div className="flex justify-center">
                                <Logo className="text-5xl" />
                            </div>
                            <div>
                                <p className="text-lg font-semibold text-slate-800">Welcome back</p>
                                <p className="text-sm text-slate-600">Sign in to continue</p>
                            </div>
                        </div>

                        <form className="space-y-5" onSubmit={handleSubmit}>
                            <div className="space-y-4">
                                <div className="space-y-1.5">
                                    <label htmlFor="email" className="block text-sm font-medium text-slate-700">Email address</label>
                                    <Input
                                        id="email"
                                        type="email"
                                        required
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        className="mt-0"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <div className="flex items-center justify-between text-sm font-medium text-slate-700">
                                        <label htmlFor="password">Password</label>
                                        <a href="#" className="text-sky-700 hover:text-sky-800">Forgot?</a>
                                    </div>
                                    <Input
                                        id="password"
                                        type="password"
                                        required
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        className="mt-0"
                                    />
                                </div>
                            </div>

                            {error && (
                                <div className="flex items-center text-sm text-red-600 bg-red-50 p-3 rounded-md ring-1 ring-red-100">
                                    <AlertCircle className="h-4 w-4 mr-2" />
                                    {error}
                                </div>
                            )}

                            <Button type="submit" className="w-full h-11 text-base font-semibold" disabled={loading}>
                                {loading ? "Signing in..." : "Sign in"}
                            </Button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    )
}
