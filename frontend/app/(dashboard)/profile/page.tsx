"use client"

import { useEffect, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertCircle, Save } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"

export default function ProfilePage() {
  const { user, refreshUser } = useAuth()
  const [fullName, setFullName] = useState("")
  const [password, setPassword] = useState("")
  const [passwordConfirm, setPasswordConfirm] = useState("")
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const getAuthHeader = (): Record<string, string> => {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  useEffect(() => {
    if (user?.full_name) setFullName(user.full_name)
  }, [user?.full_name])

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault()
    setMessage(null)
    setError(null)

    if (password && password !== passwordConfirm) {
      setError("Passwords do not match")
      return
    }

    setSaving(true)
    try {
      const payload: Record<string, string> = { full_name: fullName }
      if (password) payload.password = password

      const response = await fetch(`${getApiBaseUrl()}/users/me`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        setError(data.detail || "Failed to update profile")
        return
      }

      await refreshUser()
      setMessage("Profile updated")
      setPassword("")
      setPasswordConfirm("")
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
              <Input value={fullName} onChange={(event) => setFullName(event.target.value)} />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium">New Password</label>
                <Input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Leave blank to keep current"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Confirm Password</label>
                <Input
                  type="password"
                  value={passwordConfirm}
                  onChange={(event) => setPasswordConfirm(event.target.value)}
                  placeholder="Re-enter new password"
                />
              </div>
            </div>

            {error && (
              <div className="flex items-center rounded-md bg-red-50 p-3 text-sm text-red-600">
                <AlertCircle className="mr-2 h-4 w-4" />
                {error}
              </div>
            )}
            {message && <div className="rounded-md bg-green-50 p-3 text-sm text-green-700">{message}</div>}

            <div className="flex justify-end">
              <Button type="submit" disabled={saving}>
                <Save className="mr-2 h-4 w-4" />
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
