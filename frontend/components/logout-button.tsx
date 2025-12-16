"use client"

import { LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/components/auth-provider"

export function LogoutButton() {
  const { logout } = useAuth()

  return (
    <Button variant="ghost" className="w-full justify-start" onClick={logout}>
      <LogOut className="mr-3 h-5 w-5" />
      Logout
    </Button>
  )
}
