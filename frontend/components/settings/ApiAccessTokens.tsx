"use client"

import { useEffect, useState } from "react"
import { AlertCircle, Copy, KeyRound, Shield, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getApiBaseUrl, getPublicApiBaseUrl } from "@/lib/api"

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
  mcp_access_only: boolean
  scopes: string[]
}

const MCP_TOKEN_SCOPES = [
  { id: "mcp:jobs:write", label: "Create jobs" },
  { id: "mcp:documents:upload", label: "Upload documents" },
  { id: "mcp:documents:process", label: "Process documents" },
  { id: "mcp:documents:review", label: "Save review data" },
]

type ApiAccessTokensProps = {
  onTokenCreated?: (token: string) => void
}

export function ApiAccessTokens({ onTokenCreated }: ApiAccessTokensProps) {
  const [apiBaseUrl, setApiBaseUrl] = useState("/api/v1")
  const [apiTokens, setApiTokens] = useState<APIAccessToken[]>([])
  const [tokenName, setTokenName] = useState("")
  const [expiresInDays, setExpiresInDays] = useState("90")
  const [mcpAccessOnly, setMcpAccessOnly] = useState(false)
  const [mcpScopes, setMcpScopes] = useState<string[]>(["mcp:read"])
  const [tokenLoading, setTokenLoading] = useState(true)
  const [tokenSaving, setTokenSaving] = useState(false)
  const [tokenError, setTokenError] = useState<string | null>(null)
  const [tokenMessage, setTokenMessage] = useState<string | null>(null)
  const [newlyCreatedToken, setNewlyCreatedToken] = useState<string | null>(null)
  const [newlyCreatedTokenIsMcp, setNewlyCreatedTokenIsMcp] = useState(false)
  const [revokingTokenId, setRevokingTokenId] = useState<string | null>(null)

  const getAuthHeader = (): Record<string, string> => {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  const formatDateTime = (value: string | null) => {
    if (!value) return "Never"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  const fetchApiTokens = async () => {
    setTokenLoading(true)
    setTokenError(null)
    try {
      const res = await fetch(`${getApiBaseUrl()}/users/me/api-tokens/`, { headers: getAuthHeader() })
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
    setApiBaseUrl(getPublicApiBaseUrl())
    fetchApiTokens()
  }, [])

  const handleCreateToken = async (event: React.FormEvent) => {
    event.preventDefault()
    setTokenError(null)
    setTokenMessage(null)
    setNewlyCreatedToken(null)
    setNewlyCreatedTokenIsMcp(false)

    if (!tokenName.trim()) {
      setTokenError("Token name is required")
      return
    }

    const expiresInput = expiresInDays.trim()
    const parsedExpiresInDays = expiresInput ? Number(expiresInput) : null
    if (parsedExpiresInDays !== null && (!Number.isInteger(parsedExpiresInDays) || parsedExpiresInDays < 1 || parsedExpiresInDays > 365)) {
      setTokenError("Expires In must be a whole number from 1 to 365, or blank for no expiry")
      return
    }

    setTokenSaving(true)
    try {
      const payload: Record<string, any> = {
        name: tokenName.trim(),
        mcp_access_only: mcpAccessOnly,
      }
      if (mcpAccessOnly) payload.scopes = mcpScopes
      if (parsedExpiresInDays !== null) payload.expires_in_days = parsedExpiresInDays

      const res = await fetch(`${getApiBaseUrl()}/users/me/api-tokens/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify(payload),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || "Failed to create API token")

      setNewlyCreatedToken(data.token)
      setNewlyCreatedTokenIsMcp(mcpAccessOnly)
      onTokenCreated?.(data.token)
      setTokenMessage("API token created. Copy it now; it will not be shown again.")
      setTokenName("")
      setExpiresInDays("90")
      setMcpAccessOnly(false)
      setMcpScopes(["mcp:read"])
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
    } catch {
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
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <KeyRound className="h-5 w-5 text-slate-600" />
          <CardTitle>API Access Tokens</CardTitle>
        </div>
        <p className="text-sm text-slate-600">Create personal tokens for API access or a scoped MCP connection.</p>
      </CardHeader>
      <CardContent className="space-y-6">
        <form className="grid gap-4 md:grid-cols-[1fr_180px_auto]" onSubmit={handleCreateToken}>
          <div className="space-y-2">
            <label htmlFor="token-name" className="text-sm font-medium">Token Name</label>
            <Input id="token-name" value={tokenName} onChange={(e) => setTokenName(e.target.value)} placeholder="Production agent" />
          </div>
          <div className="space-y-2">
            <label htmlFor="token-expiry" className="text-sm font-medium">Expires In (Days)</label>
            <Input id="token-expiry" type="number" min={1} max={365} step={1} value={expiresInDays} onChange={(e) => setExpiresInDays(e.target.value)} placeholder="90; blank = no expiry" />
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={tokenSaving}>{tokenSaving ? "Creating..." : "Create Token"}</Button>
          </div>
          <div className="flex items-center gap-2 md:col-span-3">
            <input id="mcp-access-only" type="checkbox" checked={mcpAccessOnly} onChange={(event) => setMcpAccessOnly(event.target.checked)} />
            <label htmlFor="mcp-access-only" className="text-sm font-medium">MCP-only token</label>
            <span className="text-xs text-slate-500">Cannot call the standard REST API.</span>
          </div>
          {mcpAccessOnly && (
            <fieldset className="space-y-2 md:col-span-3">
              <legend className="text-sm font-medium">Allowed MCP actions</legend>
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked disabled />Read InsightDOC data</label>
                {MCP_TOKEN_SCOPES.map((scope) => (
                  <label key={scope.id} className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={mcpScopes.includes(scope.id)} onChange={(event) => setMcpScopes((current) => event.target.checked ? [...current, scope.id] : current.filter((item) => item !== scope.id))} />
                    {scope.label}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </form>

        {newlyCreatedToken && (
          <div className="space-y-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-emerald-900">Copy this token now</p>
                <p className="text-xs text-emerald-700">The plain token is shown only once after creation.</p>
              </div>
              <Button type="button" variant="outline" onClick={handleCopyToken}><Copy className="mr-2 h-4 w-4" />Copy</Button>
            </div>
            <pre className="overflow-x-auto rounded-md bg-white/80 p-3 text-xs text-slate-800">{newlyCreatedToken}</pre>
            {newlyCreatedTokenIsMcp ? (
              <pre className="overflow-x-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{`curl -sS -X POST ${apiBaseUrl}/mcp \
  -H "Authorization: Bearer ${newlyCreatedToken}" \
  -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'`}</pre>
            ) : (
              <pre className="overflow-x-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{`curl -sS ${apiBaseUrl}/external/jobs \
  -H "Authorization: Bearer ${newlyCreatedToken}"`}</pre>
            )}
          </div>
        )}

        {tokenError && <div className="flex items-center rounded-md bg-red-50 p-3 text-sm text-red-600"><AlertCircle className="mr-2 h-4 w-4" />{tokenError}</div>}
        {tokenMessage && <div className="rounded-md bg-green-50 p-3 text-sm text-green-700">{tokenMessage}</div>}

        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-700"><Shield className="h-4 w-4" />Active and historical tokens</div>
          {tokenLoading ? (
            <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">Loading API tokens...</div>
          ) : apiTokens.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">No API tokens created yet.</div>
          ) : (
            <div className="space-y-3">
              {apiTokens.map((apiToken) => {
                const statusLabel = apiToken.is_revoked ? "Revoked" : apiToken.is_expired ? "Expired" : "Active"
                const statusClassName = apiToken.is_revoked ? "bg-slate-100 text-slate-700" : apiToken.is_expired ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"
                return (
                  <div key={apiToken.id} className="rounded-lg border border-slate-200 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2"><span className="font-medium text-slate-900">{apiToken.name}</span><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusClassName}`}>{statusLabel}</span></div>
                        <p className="font-mono text-xs text-slate-500">{apiToken.token_prefix}...</p>
                        <div className="grid gap-1 text-xs text-slate-500">
                          <span>Created: {formatDateTime(apiToken.created_at)}</span>
                          <span>Last used: {formatDateTime(apiToken.last_used_at)}</span>
                          <span>Expires: {apiToken.expires_at ? formatDateTime(apiToken.expires_at) : "Never"}</span>
                          <span>{apiToken.mcp_access_only ? `MCP: ${(apiToken.scopes || ["mcp:read"]).join(", ")}` : "General API token"}</span>
                        </div>
                      </div>
                      {!apiToken.is_revoked && <Button type="button" variant="outline" disabled={revokingTokenId === apiToken.id} onClick={() => handleRevokeToken(apiToken.id)}><Trash2 className="mr-2 h-4 w-4" />{revokingTokenId === apiToken.id ? "Revoking..." : "Revoke"}</Button>}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
