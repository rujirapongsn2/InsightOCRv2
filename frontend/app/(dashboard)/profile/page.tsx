"use client"

import { useEffect, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertCircle, Save } from "lucide-react"

export default function ProfilePage() {
  const { user, refreshUser } = useAuth()
  const [fullName, setFullName] = useState("")
  const [password, setPassword] = useState("")
  const [passwordConfirm, setPasswordConfirm] = useState("")
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (user?.full_name) {
      setFullName(user.full_name)
    }
  }, [user?.full_name])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setMessage(null)
    setError(null)

    if (password && password !== passwordConfirm) {
      setError("Passwords do not match")
      return
    }

    setSaving(true)
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
      const payload: Record<string, any> = { full_name: fullName }
      if (password) payload.password = password

      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/users/me`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: JSON.stringify(payload)
      })

      if (res.ok) {
        await refreshUser()
        setMessage("Profile updated")
        setPassword("")
        setPasswordConfirm("")
      } else {
        const data = await res.json()
        setError(data.detail || "Failed to update profile")
      }
    } catch (err) {
      console.error("Profile update error", err)
      setError("Failed to update profile")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">Profile</h2>
      <Card>
        <CardHeader>
          <CardTitle>Account Details</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-6" onSubmit={handleSave}>
            <div className="space-y-2">
              <label className="text-sm font-medium">Email</label>
              <Input value={user?.email || ""} disabled />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Full Name</label>
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">New Password</label>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Leave blank to keep current"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Confirm Password</label>
                <Input
                  type="password"
                  value={passwordConfirm}
                  onChange={(e) => setPasswordConfirm(e.target.value)}
                  placeholder="Re-enter new password"
                />
              </div>
            </div>

            {error && (
              <div className="flex items-center text-sm text-red-600 bg-red-50 p-3 rounded-md">
                <AlertCircle className="h-4 w-4 mr-2" />
                {error}
              </div>
            )}
            {message && (
              <div className="text-sm text-green-700 bg-green-50 p-3 rounded-md">
                {message}
              </div>
            )}

            <div className="flex justify-end">
              <Button type="submit" disabled={saving}>
                <Save className="h-4 w-4 mr-2" />
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
