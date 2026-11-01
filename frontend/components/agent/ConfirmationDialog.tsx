"use client"

import { AlertTriangle, Check, Clock, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { documentStatusLabel } from "@/lib/a2ui"
import type { PendingAction } from "@/lib/agentConversation"

interface ConfirmationDialogProps {
    /** A request the server still waits on ("pending") or gave up on ("expired"). */
    action: Pick<PendingAction, "status" | "tool_name" | "description" | "arguments" | "documents">
    onConfirm: () => void
    onReject: () => void
}

export default function ConfirmationDialog({ action, onConfirm, onReject }: ConfirmationDialogProps) {
    if (action.status === "expired") {
        return (
            <div role="status" className="mx-3 mb-3 flex items-start gap-2 rounded-xl border border-hairline bg-off-white p-3">
                <Clock className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-gray" />
                <div className="min-w-0">
                    <p className="text-sm font-semibold text-ink-navy">คำขอยืนยันหมดเวลา</p>
                    <p className="mt-0.5 text-xs text-slate-gray">{action.description}</p>
                    <p className="mt-0.5 text-xs text-slate-gray">ไม่มีการเปลี่ยนแปลงใดๆ ขอให้ Agent ถามใหม่ได้</p>
                </div>
            </div>
        )
    }
    return (
        <div className="mx-3 mb-3 rounded-xl border-2 border-amber-300 bg-amber-50 p-4">
            <div className="flex items-start gap-2 mb-3">
                <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                <div>
                    <p className="text-sm font-semibold text-amber-800">Confirmation Required</p>
                    <p className="text-xs text-amber-700 mt-0.5">{action.description}</p>
                    <code className="text-xs text-amber-600 font-mono mt-1 block">{action.tool_name}</code>
                </div>
            </div>
            {action.documents && action.documents.length > 0 && (
                <div className="mb-3">
                    <p className="mb-1 text-xs font-medium text-amber-800">เอกสาร {action.documents.length} รายการ</p>
                    <ul className="max-h-48 divide-y divide-amber-100 overflow-y-auto rounded border border-amber-200 bg-white">
                        {action.documents.map(doc => (
                            <li key={doc.id} className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs">
                                <span className="truncate text-ink-navy" title={doc.filename}>{doc.filename}</span>
                                <span className="shrink-0 rounded-full border border-hairline px-2 py-0.5 text-slate-gray">
                                    {documentStatusLabel(doc.status)}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            <details className="mb-3">
                <summary className="text-xs text-amber-600 cursor-pointer">Show arguments</summary>
                <pre className="text-xs bg-white rounded p-2 mt-1 overflow-auto">{JSON.stringify(action.arguments, null, 2)}</pre>
            </details>
            <div className="flex gap-2">
                <Button size="sm" onClick={onConfirm} className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white">
                    <Check className="h-3.5 w-3.5 mr-1" /> Confirm
                </Button>
                <Button size="sm" variant="outline" onClick={onReject} className="flex-1 text-red-600 border-red-300 hover:bg-red-50">
                    <X className="h-3.5 w-3.5 mr-1" /> Reject
                </Button>
            </div>
        </div>
    )
}
