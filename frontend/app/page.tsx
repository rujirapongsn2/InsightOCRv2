"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { useAuth } from "@/components/auth-provider"

export default function Home() {
  const router = useRouter()
  const { user, loading } = useAuth()

  useEffect(() => {
    if (!loading) {
      if (user) {
        // ถ้า login แล้ว -> ไปหน้า dashboard
        router.push("/dashboard")
      } else {
        // ถ้ายังไม่ login -> ไปหน้า login
        router.push("/login")
      }
    }
  }, [user, loading, router])

  // แสดง loading state ระหว่างตรวจสอบ auth
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <div className="text-slate-600">Loading...</div>
    </div>
  )
}
