EXPLICIT_CONFIRMATION_TOOLS = frozenset({"create_skill", "web_search"})
# How long the loop waits for an answer before the request expires.
CONFIRMATION_TIMEOUT_S = 300


def declined_result(tool_name: str, answer: str) -> dict:
    """The tool result for a request the user rejected or never answered.

    declined ("rejected" | "expired") marks the user's decision: nothing was
    done, and nothing failed (app.agent.loop._tool_failed).
    """
    if answer == "expired":
        return {"error": "The confirmation request expired: the user did not answer in time, so nothing was done.",
                "declined": "expired", "tool_name": tool_name}
    return {"error": "User rejected action", "declined": "rejected", "tool_name": tool_name}


def requires_explicit_confirmation(tool_name: str) -> bool:
    """Return whether an approved action must come from the manual UI."""
    return tool_name in EXPLICIT_CONFIRMATION_TOOLS


def requires_confirmation(tool_name: str, args: dict) -> bool:
    DESTRUCTIVE_TOOLS = {
        "approve_document", "reject_document", "bulk_approve", "bulk_reject",
        "update_document_field", "delete_file", "forget_memory",
        "create_skill", "delete_skill", "send_to_workflow",
        "save_workflow",  # final commit of an AI-designed workflow
        "web_search",  # external context must never be mixed in silently
    }
    if tool_name in DESTRUCTIVE_TOOLS:
        return True
    if tool_name == "call_api_integration":
        method = args.get("method", "GET").upper()
        return method in ("POST", "PUT", "PATCH", "DELETE")
    return False


def describe_action(tool_name: str, args: dict) -> str:
    if tool_name == "approve_document":
        return f"อนุมัติเอกสาร {args.get('doc_id')}"
    if tool_name in ("bulk_approve", "bulk_reject"):
        # The loop freezes args["doc_ids"] to the eligible documents before asking.
        verb = "อนุมัติ" if tool_name == "bulk_approve" else "ปฏิเสธ"
        doc_ids = args.get("doc_ids")
        count = f"{len(doc_ids)} รายการ" if isinstance(doc_ids, list) else "ทั้งหมด"
        threshold = f" (ความมั่นใจ ≥ {args['min_confidence']})" if args.get("min_confidence") else ""
        return f"{verb}เอกสารที่รอตรวจ {count}{threshold}"
    if tool_name == "reject_document":
        return f"ปฏิเสธเอกสาร {args.get('doc_id')}"
    if tool_name == "update_document_field":
        return f"แก้ไข field '{args.get('field')}' ของเอกสาร {args.get('doc_id')}"
    if tool_name == "forget_memory":
        return f"ลบ memory key='{args.get('key')}' scope={args.get('scope', 'user')}"
    if tool_name == "delete_skill":
        return f"ลบ skill '{args.get('name')}'"
    if tool_name == "create_skill":
        return f"บันทึก Personal Skill '{args.get('name')}'"
    if tool_name == "delete_file":
        return f"ลบไฟล์ '{args.get('path')}' จาก job storage"
    if tool_name == "send_to_workflow":
        return f"ส่งข้อมูลไปยัง Workflow '{args.get('integration_name')}'"
    if tool_name == "save_workflow":
        return f"บันทึก workflow '{args.get('name') or '(ใช้ draft ล่าสุด)'}'"
    if tool_name == "call_api_integration":
        method = args.get("method", "GET")
        path = args.get("path", "")
        if method != "GET":
            return f"เรียก External API: {method} {path}"
    if tool_name == "web_search":
        return f"ค้นหาข้อมูลภายนอกจากเว็บ: {args.get('query', '')}"
    return f"{tool_name}({args})"
