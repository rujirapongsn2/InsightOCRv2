import json
from enum import Enum


class SSEEventType(str, Enum):
    THINKING = "thinking"
    PLAN = "plan"                    # initial decomposed checklist of sub-goals
    REFLECTION = "reflection"        # final self-review result vs the plan/intent
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_REJECTED = "tool_rejected"
    DELTA = "delta"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DONE = "done"
    ERROR = "error"


def sse_event(event_type: SSEEventType, payload: dict) -> str:
    data = {"type": event_type.value, **payload}
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
