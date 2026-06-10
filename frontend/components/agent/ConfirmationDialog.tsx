"use client"

import { AlertTriangle, Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"

interface PendingAction {
    pending_action_id: string
    tool_name: string
    description: string
    arguments: any
}

interface ConfirmationDialogProps {
    action: PendingAction
    onConfirm: () => void
    onReject: () => void
}

export default function ConfirmationDialog({ action, onConfirm, onReject }: ConfirmationDialogProps) {
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
            <details className="mb-3">
                <summary className="text-xs text-amber-600 cursor-pointer">Show arguments</summary>
                <pre className="text-[11px] bg-white rounded p-2 mt-1 overflow-auto">{JSON.stringify(action.arguments, null, 2)}</pre>
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
