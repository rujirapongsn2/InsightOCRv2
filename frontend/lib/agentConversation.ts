// Conversation state the Jobs agent panel renders from server responses, kept
// out of React so it is decided in one place and testable without a browser.

/** A document the action will change, as the server froze it when asking. */
export interface ConfirmationDocument {
    id: string
    filename: string
    status: string
}

export type PendingStatus = "pending" | "confirmed" | "rejected" | "expired"

/** The run's latest confirmation request, in whatever state the server holds it now. */
export interface PendingAction {
    pending_action_id: string
    status: PendingStatus
    tool_name: string
    /** Sensitive actions are always confirmed by the user's own click, even with auto-confirm on. */
    requires_explicit_confirmation: boolean
    description: string
    arguments: unknown
    documents?: ConfirmationDocument[]
    expires_at?: string | null
}

/**
 * Whether the confirmation area shows the request: while the server still waits
 * for an answer, and after it expired (so the user learns why nothing happened).
 * An answered request shows nothing. Derived on every poll, never remembered.
 */
export function shownConfirmation(action: PendingAction | null | undefined): PendingAction | null {
    return action && (action.status === "pending" || action.status === "expired") ? action : null
}

/**
 * The moments the conversation list can change: a run is accepted (the server
 * titles the conversation after its user turn) and a run ends. The list is
 * reloaded whenever this key changes; null while no run is known.
 */
export function conversationListKey(run: { id: string; status: string } | null | undefined): string | null {
    if (!run) return null
    return `${run.id}:${run.status === "queued" || run.status === "running" ? "active" : "ended"}`
}

/**
 * Put a freshly loaded newest page in place. It replaces the messages it
 * overlaps; older pages the user loaded stay in front of it while it connects
 * to them. Otherwise the page stands alone and its own has_more applies.
 */
export function mergeNewestPage<T extends { id: string }>(
    loaded: readonly T[], loadedHasMore: boolean, page: readonly T[], pageHasMore: boolean,
): { messages: T[]; hasMore: boolean } {
    const cut = page.length > 0 ? loaded.findIndex(message => message.id === page[0].id) : -1
    return cut >= 0
        ? { messages: [...loaded.slice(0, cut), ...page], hasMore: loadedHasMore }
        : { messages: [...page], hasMore: pageHasMore }
}
