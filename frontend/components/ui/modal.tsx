import * as React from "react"
import { X } from "lucide-react"
import { Dialog } from "@astryxdesign/core/Dialog"

interface ModalProps {
    isOpen: boolean
    onClose: () => void
    title: string
    children: React.ReactNode
    width?: string
    bodyClassName?: string
}

export function Modal({
    isOpen,
    onClose,
    title,
    children,
    width = "min(42rem, calc(100vw - 2rem))",
    bodyClassName = "p-6",
}: ModalProps) {
    return (
        <Dialog
            isOpen={isOpen}
            onOpenChange={(open) => {
                if (!open) onClose()
            }}
            purpose="info"
            width={width}
            maxHeight="calc(100vh - 4rem)"
            padding={0}
        >
            <div className="max-h-[calc(100vh-4rem)] overflow-y-auto bg-white text-[#0D1B2A]">
                <div className="flex items-start justify-between gap-4 border-b border-[#E2E8F0] px-6 py-5">
                    <h2 className="text-[1.125rem] font-semibold leading-6 text-[#0D1B2A]">{title}</h2>
                    <button
                        type="button"
                        onClick={onClose}
                        className="-mr-2 -mt-1 flex h-9 w-9 items-center justify-center rounded-full text-[#778DA9] transition-colors hover:bg-[#F8F9FA] hover:text-[#0D1B2A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2786C2]"
                        aria-label="Close"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>
                <div className={bodyClassName}>{children}</div>
            </div>
        </Dialog>
    )
}
