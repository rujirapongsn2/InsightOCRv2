"use client"

import { useEffect, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertCircle, Copy, KeyRound, Save, Shield, Trash2 } from "lucide-react"
import { getApiBaseUrl } from "@/lib/api"
import { ApiWorkflowDocs } from "@/components/profile/ApiWorkflowDocs"
import { AgentSkillDownloads } from "@/components/profile/AgentSkillDownloads"

interface APIAccessToken {
  id: string
  name: string
  token_prefix: string
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
  is_revoked: boolean
  is_expired: boolean
}

export default function ProfilePage() {
  const { user, refreshUser } = useAuth()
  const [apiBaseUrl, setApiBaseUrl] = useState("/api/v1")
  const [fullName, setFullName] = useState("")
  const [password, setPassword] = useState("")
  const [passwordConfirm, setPasswordConfirm] = useState("")
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [apiTokens, setApiTokens] = useState<APIAccessToken[]>([])
  const [tokenName, setTokenName] = useState("")
  const [expiresInDays, setExpiresInDays] = useState("90")
  const [tokenLoading, setTokenLoading] = useState(true)
  const [tokenSaving, setTokenSaving] = useState(false)
  const [tokenError, setTokenError] = useState<string | null>(null)
  const [tokenMessage, setTokenMessage] = useState<string | null>(null)
  const [newlyCreatedToken, setNewlyCreatedToken] = useState<string | null>(null)
  const [revokingTokenId, setRevokingTokenId] = useState<string | null>(null)
  const tokenExample = newlyCreatedToken || "YOUR_API_ACCESS_TOKEN"

  const getAuthHeader = (): Record<string, string> => {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
    const headers: Record<string, string> = {}
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
    return headers
  }

  const formatDateTime = (value: string | null) => {
    if (!value) return "Never"
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleString()
  }

  const fetchApiTokens = async () => {
    setTokenLoading(true)
    setTokenError(null)
    try {
      const res = await fetch(`${getApiBaseUrl()}/users/me/api-tokens`, {
        headers: getAuthHeader(),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || "Failed to load API tokens")
      }
      setApiTokens(await res.json())
    } catch (err: any) {
      console.error("API token load error", err)
      setTokenError(err?.message || "Failed to load API tokens")
    } finally {
      setTokenLoading(false)
    }
  }

  useEffect(() => {
    setApiBaseUrl(getApiBaseUrl())
  }, [])

  useEffect(() => {
    if (user?.full_name) {
      setFullName(user.full_name)
    }
  }, [user?.full_name])

  useEffect(() => {
    fetchApiTokens()
  }, [])

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
      const payload: Record<string, any> = { full_name: fullName }
      if (password) payload.password = password

      const res = await fetch(`${getApiBaseUrl()}/users/me`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeader(),
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

  const handleCreateToken = async (e: React.FormEvent) => {
    e.preventDefault()
    setTokenError(null)
    setTokenMessage(null)
    setNewlyCreatedToken(null)

    if (!tokenName.trim()) {
      setTokenError("Token name is required")
      return
    }

    setTokenSaving(true)
    try {
      const payload: Record<string, any> = { name: tokenName.trim() }
      const parsedExpiresInDays = expiresInDays.trim() ? Number(expiresInDays) : null
      if (parsedExpiresInDays) {
        payload.expires_in_days = parsedExpiresInDays
      }

      const res = await fetch(`${getApiBaseUrl()}/users/me/api-tokens`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeader(),
        },
        body: JSON.stringify(payload),
      })

      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data.detail || "Failed to create API token")
      }

      setNewlyCreatedToken(data.token)
      setTokenMessage("API token created. Copy it now; it will not be shown again.")
      setTokenName("")
      setExpiresInDays("90")
      await fetchApiTokens()
    } catch (err: any) {
      console.error("API token create error", err)
      setTokenError(err?.message || "Failed to create API token")
    } finally {
      setTokenSaving(false)
    }
  }

  const handleCopyToken = async () => {
    if (!newlyCreatedToken) return
    try {
      await navigator.clipboard.writeText(newlyCreatedToken)
      setTokenMessage("API token copied to clipboard.")
    } catch (err) {
      console.error("Copy token error", err)
      setTokenError("Failed to copy token")
    }
  }

  const handleRevokeToken = async (tokenId: string) => {
    setRevokingTokenId(tokenId)
    setTokenError(null)
    setTokenMessage(null)
    try {
      const res = await fetch(`${getApiBaseUrl()}/users/me/api-tokens/${tokenId}`, {
        method: "DELETE",
        headers: getAuthHeader(),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || "Failed to revoke API token")
      }
      setTokenMessage("API token revoked.")
      await fetchApiTokens()
    } catch (err: any) {
      console.error("API token revoke error", err)
      setTokenError(err?.message || "Failed to revoke API token")
    } finally {
      setRevokingTokenId(null)
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

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-slate-600" />
            <CardTitle>API Access Tokens</CardTitle>
          </div>
          <p className="text-sm text-slate-600">
            Create personal tokens for API and AI Agent access. Tokens inherit your current permissions.
          </p>
        </CardHeader>
        <CardContent className="space-y-6">
          <form className="grid gap-4 md:grid-cols-[1fr_160px_auto]" onSubmit={handleCreateToken}>
            <div className="space-y-2">
              <label className="text-sm font-medium">Token Name</label>
              <Input
                value={tokenName}
                onChange={(e) => setTokenName(e.target.value)}
                placeholder="Production agent"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Expires In (Days)</label>
              <Input
                type="number"
                min={1}
                max={365}
                value={expiresInDays}
                onChange={(e) => setExpiresInDays(e.target.value)}
                placeholder="90"
              />
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={tokenSaving}>
                {tokenSaving ? "Creating..." : "Create Token"}
              </Button>
            </div>
          </form>

          {newlyCreatedToken && (
            <div className="space-y-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-emerald-900">Copy this token now</p>
                  <p className="text-xs text-emerald-700">The plain token is shown only once after creation.</p>
                </div>
                <Button type="button" variant="outline" onClick={handleCopyToken}>
                  <Copy className="mr-2 h-4 w-4" />
                  Copy
                </Button>
              </div>
              <pre className="overflow-x-auto rounded-md bg-white/80 p-3 text-xs text-slate-800">{newlyCreatedToken}</pre>
              <pre className="overflow-x-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{`curl -sS -H "Authorization: Bearer ${newlyCreatedToken}" \\
  ${apiBaseUrl}/external/jobs`}</pre>
            </div>
          )}

          {tokenError && (
            <div className="flex items-center text-sm text-red-600 bg-red-50 p-3 rounded-md">
              <AlertCircle className="h-4 w-4 mr-2" />
              {tokenError}
            </div>
          )}
          {tokenMessage && (
            <div className="text-sm text-green-700 bg-green-50 p-3 rounded-md">
              {tokenMessage}
            </div>
          )}

          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <Shield className="h-4 w-4" />
              Active and historical tokens
            </div>

            {tokenLoading ? (
              <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
                Loading API tokens...
              </div>
            ) : apiTokens.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
                No API tokens created yet.
              </div>
            ) : (
              <div className="space-y-3">
                {apiTokens.map((apiToken) => {
                  const statusLabel = apiToken.is_revoked
                    ? "Revoked"
                    : apiToken.is_expired
                      ? "Expired"
                      : "Active"

                  const statusClassName = apiToken.is_revoked
                    ? "bg-slate-100 text-slate-700"
                    : apiToken.is_expired
                      ? "bg-amber-100 text-amber-800"
                      : "bg-emerald-100 text-emerald-800"

                  return (
                    <div key={apiToken.id} className="rounded-lg border border-slate-200 p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-slate-900">{apiToken.name}</span>
                            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusClassName}`}>
                              {statusLabel}
                            </span>
                          </div>
                          <p className="font-mono text-xs text-slate-500">{apiToken.token_prefix}...</p>
                          <div className="grid gap-1 text-xs text-slate-500">
                            <span>Created: {formatDateTime(apiToken.created_at)}</span>
                            <span>Last used: {formatDateTime(apiToken.last_used_at)}</span>
                            <span>Expires: {apiToken.expires_at ? formatDateTime(apiToken.expires_at) : "Never"}</span>
                          </div>
                        </div>
                        {!apiToken.is_revoked && (
                          <Button
                            type="button"
                            variant="outline"
                            disabled={revokingTokenId === apiToken.id}
                            onClick={() => handleRevokeToken(apiToken.id)}
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            {revokingTokenId === apiToken.id ? "Revoking..." : "Revoke"}
                          </Button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <ApiWorkflowDocs apiBaseUrl={apiBaseUrl} tokenExample={tokenExample} />
      <AgentSkillDownloads apiBaseUrl={apiBaseUrl} getAuthHeader={getAuthHeader} />
    </div>
  )
}
