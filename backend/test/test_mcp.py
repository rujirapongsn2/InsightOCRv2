from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.mcp import (
    MCP_TOOLS,
    _save_document_review,
    _validate_request_size,
    _validate_upload_content,
    handle_mcp_message,
)
from app.services.api_token_scopes import MCP_JOB_WRITE_SCOPE


def _request(method, params=None, request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def test_mcp_initialize_negotiates_a_supported_protocol_version():
    response = handle_mcp_message(
        _request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}}),
        None,
        None,
    )

    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert response["result"]["capabilities"] == {"tools": {"listChanged": False}}


def test_mcp_initialize_falls_back_to_the_server_protocol_version():
    response = handle_mcp_message(
        _request("initialize", {"protocolVersion": "2099-01-01", "capabilities": {}, "clientInfo": {}}),
        None,
        None,
    )

    assert response["result"]["protocolVersion"] == "2025-06-18"


def test_mcp_tools_list_marks_the_controlled_actions_as_non_read_only():
    response = handle_mcp_message(_request("tools/list"), None, None)

    tool_names = {tool["name"] for tool in response["result"]["tools"]}
    assert tool_names == {tool["name"] for tool in MCP_TOOLS}
    assert response["result"]["tools"][-1]["name"] == "insightdoc_save_document_review"
    assert all(
        tool.get("annotations", {}).get("readOnlyHint") is False
        for tool in response["result"]["tools"]
        if tool["name"] in {
            "insightdoc_create_job",
            "insightdoc_upload_document",
            "insightdoc_process_document",
            "insightdoc_save_document_review",
        }
    )


def test_mcp_unknown_tool_returns_a_tool_error_without_executing_anything():
    response = handle_mcp_message(
        _request("tools/call", {"name": "insightdoc_delete_job", "arguments": {}}),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    result = response["result"]
    assert result["isError"] is True
    assert "Unknown MCP tool" in result["structuredContent"]["error"]


def test_mcp_rejects_invalid_jsonrpc_messages():
    response = handle_mcp_message({"id": 1, "method": "tools/list"}, None, None)

    assert response["error"]["code"] == -32600


def test_mcp_rejects_unsupported_tool_arguments_before_execution():
    response = handle_mcp_message(
        _request(
            "tools/call",
            {"name": "insightdoc_list_jobs", "arguments": {"include_deleted": True}},
        ),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "Unsupported argument(s): include_deleted"


def test_mcp_rejects_action_when_token_lacks_its_scope(monkeypatch):
    from app.api.v1.endpoints import mcp

    monkeypatch.setitem(mcp.MCP_TOOL_HANDLERS, "insightdoc_create_job", lambda *_args: {"unexpected": True})
    principal = SimpleNamespace(api_token=SimpleNamespace(mcp_access_only=True, scopes=["mcp:read"]))
    response = handle_mcp_message(
        _request("tools/call", {"name": "insightdoc_create_job", "arguments": {"name": "MCP test", "confirmed": True}}),
        SimpleNamespace(),
        principal,
    )

    assert response["result"]["isError"] is True
    assert MCP_JOB_WRITE_SCOPE in response["result"]["structuredContent"]["error"]


def test_mcp_dispatches_action_when_token_has_its_scope(monkeypatch):
    from app.api.v1.endpoints import mcp

    monkeypatch.setitem(
        mcp.MCP_TOOL_HANDLERS,
        "insightdoc_create_job",
        lambda arguments, _db, _user: {"id": "created", "name": arguments["name"]},
    )
    principal = SimpleNamespace(api_token=SimpleNamespace(mcp_access_only=True, scopes=["mcp:read", MCP_JOB_WRITE_SCOPE]))
    response = handle_mcp_message(
        _request("tools/call", {"name": "insightdoc_create_job", "arguments": {"name": "MCP test", "confirmed": True}}),
        SimpleNamespace(),
        principal,
    )

    assert response["result"]["structuredContent"] == {"id": "created", "name": "MCP test"}


def test_mcp_rejects_controlled_action_for_a_general_api_token(monkeypatch):
    from app.api.v1.endpoints import mcp

    monkeypatch.setitem(mcp.MCP_TOOL_HANDLERS, "insightdoc_create_job", lambda *_args: {"unexpected": True})
    principal = SimpleNamespace(api_token=SimpleNamespace(mcp_access_only=False, scopes=["mcp:read", MCP_JOB_WRITE_SCOPE]))
    response = handle_mcp_message(
        _request("tools/call", {"name": "insightdoc_create_job", "arguments": {"name": "MCP test", "confirmed": True}}),
        SimpleNamespace(),
        principal,
    )

    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["error"] == "Controlled MCP actions require a dedicated MCP-only token"


def test_mcp_requires_explicit_confirmation_for_controlled_actions(monkeypatch):
    from app.api.v1.endpoints import mcp

    monkeypatch.setitem(mcp.MCP_TOOL_HANDLERS, "insightdoc_create_job", lambda *_args: {"unexpected": True})
    principal = SimpleNamespace(api_token=SimpleNamespace(mcp_access_only=True, scopes=[MCP_JOB_WRITE_SCOPE]))
    response = handle_mcp_message(
        _request("tools/call", {"name": "insightdoc_create_job", "arguments": {"name": "MCP test", "confirmed": False}}),
        SimpleNamespace(),
        principal,
    )

    assert response["result"]["isError"] is True
    assert "confirmed=true" in response["result"]["structuredContent"]["error"]


def test_mcp_rejects_action_without_confirmation_before_scope_check():
    principal = SimpleNamespace(api_token=SimpleNamespace(mcp_access_only=True, scopes=["mcp:read"]))
    response = handle_mcp_message(
        _request("tools/call", {"name": "insightdoc_create_job", "arguments": {"name": "MCP test"}}),
        SimpleNamespace(),
        principal,
    )

    assert response["result"]["isError"] is True
    assert "Missing required argument: confirmed" in response["result"]["structuredContent"]["error"]


def test_mcp_tools_list_hides_actions_without_the_required_scope():
    from app.api.v1.endpoints.mcp import _visible_mcp_tools

    read_only = SimpleNamespace(api_token=SimpleNamespace(mcp_access_only=False, scopes=["mcp:read"]))
    scoped = SimpleNamespace(api_token=SimpleNamespace(mcp_access_only=True, scopes=["mcp:read", MCP_JOB_WRITE_SCOPE]))

    read_names = {tool["name"] for tool in _visible_mcp_tools(read_only)}
    scoped_names = {tool["name"] for tool in _visible_mcp_tools(scoped)}
    assert "insightdoc_create_job" not in read_names
    assert "insightdoc_create_job" in scoped_names
    assert "insightdoc_upload_document" not in scoped_names


def test_mcp_review_save_rejects_documents_that_were_already_decided(monkeypatch):
    from app.api.v1.endpoints import mcp

    document = SimpleNamespace(status="reviewed", review_decision="confirmed")
    monkeypatch.setattr(mcp, "_get_document", lambda *_args: document)

    with pytest.raises(HTTPException) as exc_info:
        _save_document_review({"document_id": "doc-1", "reviewed_data": {"total": 100}}, SimpleNamespace(), SimpleNamespace())

    assert exc_info.value.status_code == 409


def test_mcp_rejects_requests_over_the_encoded_upload_limit():
    request = SimpleNamespace(headers={"content-length": str(20 * 1024 * 1024)})

    with pytest.raises(HTTPException) as exc_info:
        _validate_request_size(request)

    assert exc_info.value.status_code == 413


def test_mcp_get_document_text_bounds_the_requested_segment(monkeypatch):
    from app.api.v1.endpoints import mcp

    document = SimpleNamespace(id="doc-1", ocr_text="abc" * 10_000)
    monkeypatch.setattr(mcp, "_get_document", lambda *_args: document)

    response = handle_mcp_message(
        _request(
            "tools/call",
            {"name": "insightdoc_get_document_text", "arguments": {"document_id": "doc-1", "max_chars": 20_000}},
        ),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    content = response["result"]["structuredContent"]
    assert len(content["text"]) == 20_000
    assert content["has_more"] is True


@pytest.mark.parametrize(
    ("file_ext", "content"),
    [
        (".pdf", b"not a pdf"),
        (".png", b"%PDF-1.7"),
        (".jpg", b"BMnot-jpeg"),
    ],
)
def test_mcp_upload_rejects_extension_content_mismatch(file_ext, content):
    with pytest.raises(ValueError, match="does not match"):
        _validate_upload_content(file_ext, content)


def test_mcp_upload_accepts_pdf_signature():
    _validate_upload_content(".pdf", b"%PDF-1.7\nminimal")
