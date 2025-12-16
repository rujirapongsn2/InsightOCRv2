"use client"

import { useEffect, useMemo, useState } from "react"
import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Plus, User as UserIcon, Shield, Pencil, Trash2 } from "lucide-react"

interface User {
    id: string
    email: string
    full_name: string
    role: string
    is_active: boolean
}

export default function UsersPage() {
    const { user: currentUser } = useAuth()
    const [users, setUsers] = useState<User[]>([])
    const [loading, setLoading] = useState(true)
    const [showCreate, setShowCreate] = useState(false)
    const [newUser, setNewUser] = useState({ email: "", password: "", full_name: "", role: "user" })
    const [editingUser, setEditingUser] = useState<User | null>(null)
    const [editPassword, setEditPassword] = useState("")

    const normalizedRole = useMemo(() => {
        if (!currentUser?.role) return "user"
        return currentUser.role === "documents_admin" ? "manager" : currentUser.role
    }, [currentUser?.role])

    const fetchUsers = async () => {
        try {
            const token = localStorage.getItem("token")
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/users/`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (res.ok) {
                const data = await res.json()
                setUsers(data)
            }
        } catch (error) {
            console.error("Failed to fetch users", error)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchUsers()
    }, [])

    const handleCreateUser = async (e: React.FormEvent) => {
        e.preventDefault()
        try {
            const token = localStorage.getItem("token")
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/users/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify(newUser)
            })

            if (res.ok) {
                setShowCreate(false)
                setNewUser({ email: "", password: "", full_name: "", role: "user" })
                fetchUsers()
            } else {
                alert("Failed to create user")
            }
        } catch (error) {
            console.error("Error creating user", error)
        }
    }

    const handleUpdateUser = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!editingUser) return
        try {
            const token = localStorage.getItem("token")
            const payload: Record<string, any> = {
                full_name: editingUser.full_name,
                role: editingUser.role,
                is_active: editingUser.is_active,
            }
            if (editPassword) payload.password = editPassword

            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/users/${editingUser.id}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify(payload)
            })

            if (res.ok) {
                setEditingUser(null)
                setEditPassword("")
                fetchUsers()
            } else {
                alert("Failed to update user")
            }
        } catch (error) {
            console.error("Error updating user", error)
        }
    }

    const handleDeleteUser = async (userId: string) => {
        if (!confirm("Delete this user?")) return
        try {
            const token = localStorage.getItem("token")
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/users/${userId}`, {
                method: "DELETE",
                headers: { Authorization: `Bearer ${token}` }
            })
            if (res.ok) {
                fetchUsers()
            } else {
                alert("Failed to delete user")
            }
        } catch (error) {
            console.error("Error deleting user", error)
        }
    }

    if (loading) return <div>Loading...</div>

    if (normalizedRole !== "admin") {
        return (
            <div className="bg-white rounded-lg border shadow-sm p-6">
                <h2 className="text-xl font-semibold text-slate-900">Access restricted</h2>
                <p className="text-slate-600 mt-2">Only Admins can manage users.</p>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Users</h2>
                    <p className="text-slate-500">Manage system users and roles.</p>
                </div>
                <Button onClick={() => setShowCreate(!showCreate)}>
                    <Plus className="mr-2 h-4 w-4" />
                    Add User
                </Button>
            </div>

            {showCreate && (
                <div className="bg-white p-6 rounded-lg border shadow-sm mb-6">
                    <h3 className="text-lg font-semibold mb-4">Create New User</h3>
                    <form onSubmit={handleCreateUser} className="space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Email</label>
                                <Input
                                    type="email"
                                    required
                                    value={newUser.email}
                                    onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Full Name</label>
                                <Input
                                    required
                                    value={newUser.full_name}
                                    onChange={(e) => setNewUser({ ...newUser, full_name: e.target.value })}
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Password</label>
                                <Input
                                    type="password"
                                    required
                                    value={newUser.password}
                                    onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Role</label>
                                <select
                                    className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                    value={newUser.role}
                                    onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}
                                >
                                    <option value="user">User</option>
                                    <option value="manager">Manager</option>
                                    <option value="admin">Admin</option>
                                </select>
                            </div>
                        </div>
                        <div className="flex justify-end gap-2">
                            <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
                            <Button type="submit">Create User</Button>
                        </div>
                    </form>
                </div>
            )}

            {editingUser && (
                <div className="bg-white p-6 rounded-lg border shadow-sm mb-6">
                    <h3 className="text-lg font-semibold mb-4">Edit User</h3>
                    <form onSubmit={handleUpdateUser} className="space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Email</label>
                                <Input value={editingUser.email} disabled />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Full Name</label>
                                <Input
                                    required
                                    value={editingUser.full_name}
                                    onChange={(e) => setEditingUser({ ...editingUser, full_name: e.target.value })}
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">New Password</label>
                                <Input
                                    type="password"
                                    value={editPassword}
                                    onChange={(e) => setEditPassword(e.target.value)}
                                    placeholder="Leave blank to keep current"
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Role</label>
                                <select
                                    className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                    value={editingUser.role}
                                    onChange={(e) => setEditingUser({ ...editingUser, role: e.target.value })}
                                >
                                    <option value="user">User</option>
                                    <option value="manager">Manager</option>
                                    <option value="admin">Admin</option>
                                </select>
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Status</label>
                                <select
                                    className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                                    value={editingUser.is_active ? "active" : "inactive"}
                                    onChange={(e) => setEditingUser({ ...editingUser, is_active: e.target.value === "active" })}
                                >
                                    <option value="active">Active</option>
                                    <option value="inactive">Inactive</option>
                                </select>
                            </div>
                        </div>
                        <div className="flex justify-end gap-2">
                            <Button type="button" variant="outline" onClick={() => { setEditingUser(null); setEditPassword(""); }}>Cancel</Button>
                            <Button type="submit">Save Changes</Button>
                        </div>
                    </form>
                </div>
            )}

            <div className="bg-white rounded-lg border shadow-sm">
                <div className="p-0">
                    <table className="w-full text-sm text-left">
                        <thead className="text-xs text-slate-500 uppercase bg-slate-50 border-b">
                            <tr>
                                <th className="px-6 py-3">User</th>
                                <th className="px-6 py-3">Role</th>
                                <th className="px-6 py-3">Status</th>
                                <th className="px-6 py-3">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {users.map((user) => (
                                <tr key={user.id} className="bg-white border-b hover:bg-slate-50">
                                    <td className="px-6 py-4 font-medium text-slate-900 flex items-center gap-3">
                                        <div className="h-8 w-8 rounded-full bg-slate-100 flex items-center justify-center">
                                            <UserIcon className="h-4 w-4 text-slate-500" />
                                        </div>
                                        <div>
                                            <div>{user.full_name}</div>
                                            <div className="text-xs text-slate-500">{user.email}</div>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex items-center gap-2">
                                            {user.role === 'admin' && <Shield className="h-3 w-3 text-purple-500" />}
                                            <span className="capitalize">
                                                {user.role === "documents_admin" ? "Manager" : user.role.replace('_', ' ')}
                                            </span>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4">
                                        <span className={`px-2 py-1 rounded-full text-xs ${user.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                            {user.is_active ? 'Active' : 'Inactive'}
                                        </span>
                                    </td>
                                    <td className="px-6 py-4 flex gap-2">
                                        <Button variant="ghost" size="sm" onClick={() => { setEditingUser(user); setEditPassword(""); }}>
                                            <Pencil className="h-4 w-4 mr-1" /> Edit
                                        </Button>
                                        <Button variant="ghost" size="sm" className="text-red-600 hover:text-red-700" onClick={() => handleDeleteUser(user.id)}>
                                            <Trash2 className="h-4 w-4 mr-1" /> Delete
                                        </Button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}
