def requires_confirmation(tool_name: str, args: dict) -> bool:
    DESTRUCTIVE_TOOLS = {
        "approve_document", "reject_document", "bulk_approve",
        "update_document_field", "delete_file", "forget_memory",
        "delete_skill", "send_to_workflow",
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
    if tool_name == "bulk_approve":
        return f"อนุมัติเอกสารหลายชิ้นใน Job (criteria: {args})"
    if tool_name == "reject_document":
        return f"ปฏิเสธเอกสาร {args.get('doc_id')}"
    if tool_name == "update_document_field":
        return f"แก้ไข field '{args.get('field')}' ของเอกสาร {args.get('doc_id')}"
    if tool_name == "forget_memory":
        return f"ลบ memory key='{args.get('key')}' scope={args.get('scope', 'user')}"
    if tool_name == "delete_skill":
        return f"ลบ skill '{args.get('name')}'"
    if tool_name == "delete_file":
        return f"ลบไฟล์ '{args.get('path')}' จาก job storage"
    if tool_name == "send_to_workflow":
        return f"ส่งข้อมูลไปยัง Workflow '{args.get('integration_name')}'"
    if tool_name == "call_api_integration":
        method = args.get("method", "GET")
        path = args.get("path", "")
        if method != "GET":
            return f"เรียก External API: {method} {path}"
    return f"{tool_name}({args})"
