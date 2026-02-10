import * as React from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"

interface ModalProps {
    isOpen: boolean
    onClose: () => void
    title: string
    children: React.ReactNode
}

export function Modal({ isOpen, onClose, title, children }: ModalProps) {
    if (!isOpen) return null

    return (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm overflow-y-auto">
            <div className="relative w-full max-w-2xl rounded-lg border bg-white p-6 shadow-lg sm:rounded-xl my-8 max-h-[calc(100vh-4rem)] overflow-y-auto">
                <div className="sticky top-0 flex items-center justify-between mb-4 bg-white">
                    <h3 className="text-lg font-semibold leading-none tracking-tight">
                        {title}
                    </h3>
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 rounded-full p-0"
                        onClick={onClose}
                    >
                        <X className="h-4 w-4" />
                        <span className="sr-only">Close</span>
                    </Button>
                </div>
                <div>{children}</div>
            </div>
        </div>
    )
}
