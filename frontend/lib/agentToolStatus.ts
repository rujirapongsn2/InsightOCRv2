/** What the chat shows for one agent tool call, derived from its stored result. */
export type ToolCallState = "running" | "complete" | "error" | "stopped" | "rejected" | "expired"

/** Ended without effect and not a failure: shown neutral, with this label. */
export const QUIET_STATE_LABEL: Partial<Record<ToolCallState, string>> = {
    stopped: "หยุดแล้ว",
    rejected: "ผู้ใช้ไม่ยืนยัน",
    expired: "หมดเวลายืนยัน",
}

type JsonRecord = Record<string, unknown>

function isRecord(value: unknown): value is JsonRecord {
    return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function toolCallMessage(result: unknown): string | null {
    if (!isRecord(result) || !result.error) return null
    const error = result.error
    if (typeof error === "string") return error
    if (isRecord(error)) {
        if (error.message || error.type) return String(error.message || error.type)
        try {
            return JSON.stringify(error, null, 2)
        } catch {
            return String(error)
        }
    }
    return String(error)
}

/**
 * runActive: a run of the conversation is still working. A call without a
 * result is running only then; otherwise its run ended before the server
 * stored the result that says so (backend app.agent.unfinished).
 */
export function toolCallState(result: unknown, runActive: boolean): ToolCallState {
    if (result === undefined) return runActive ? "running" : "stopped"
    if (isRecord(result)) {
        if (result.unfinished === true) return "stopped"
        if (result.declined === "rejected" || result.declined === "expired") return result.declined
    }
    return toolCallMessage(result) ? "error" : "complete"
}

/** A group of calls is running while any of its calls runs; otherwise it shows its latest call. */
export function toolCallGroupState(states: ToolCallState[]): ToolCallState {
    if (states.includes("running")) return "running"
    return states[states.length - 1] ?? "complete"
}
