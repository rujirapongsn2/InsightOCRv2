"use client"

import { useRef, useEffect, KeyboardEvent } from "react"
import { Send, Loader2 } from "lucide-react"

interface ChatInputProps {
    value: string
    onChange: (value: string) => void
    onSend: () => void
    disabled?: boolean
    streaming?: boolean
}

export default function ChatInput({ value, onChange, onSend, disabled, streaming }: ChatInputProps) {
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = "auto"
            textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + "px"
        }
    }, [value])

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            if (value.trim() && !disabled && !streaming) {
                onSend()
            }
        }
    }

    return (
        <div className="border-t bg-white px-3 py-3">
            <div className="flex items-end gap-2">
                <textarea
                    ref={textareaRef}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask about your documents..."
                    disabled={disabled || streaming}
                    maxLength={10000}
                    rows={1}
                    className="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 min-h-[40px] max-h-[120px]"
                />
                <button
                    onClick={onSend}
                    disabled={!value.trim() || disabled || streaming}
                    className="flex-shrink-0 w-9 h-9 rounded-full bg-blue-600 text-white flex items-center justify-center hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                    {streaming ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                        <Send className="h-4 w-4" />
                    )}
                </button>
            </div>
            {value.length > 9000 && (
                <p className="text-[10px] text-amber-600 mt-1 text-right">{value.length}/10,000</p>
            )}
        </div>
    )
}
