"""
Level 2 E2E: Agent Loop — Mock LLM Integration

Tests the full AgentLoop with a mocked LLM that returns predetermined tool calls
and final text. Verifies SSE streaming, confirmation flow, and message persistence.

Run: python -m pytest test/e2e/test_agent_loop_e2e.py -v
"""
import uuid
import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, ANY

import pytest

from app.agent.loop import AgentLoop
from app.agent.events import SSEEventType

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════════════════════
# Mock LLM Response Builder
# ═══════════════════════════════════════════════════════════════════════════════

def _tool_call(id_: str, name: str, arguments: dict) -> MagicMock:
    """Build a mock OpenAI tool_call object."""
    tc = MagicMock()
    tc.id = id_
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _assistant_msg(content: str = None, tool_calls: list = None) -> MagicMock:
    """Build a mock OpenAI chat completion message."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    return msg


def _completion_response(message: MagicMock, prompt_tokens: int = 100, completion_tokens: int = 50) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    choice = MagicMock()
    choice.message = message

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Quotation Workflow Mock Responses
# ═══════════════════════════════════════════════════════════════════════════════

def build_quotation_workflow_responses(doc_id: str, erp_name: str = "ERP Stock", crm_name: str = "CRM System"):
    """Build a sequence of mock LLM responses for the Quotation Workflow.

    Returns an async generator that yields responses in sequence.
    The agent loop calls the LLM once per iteration. Each call gets the next response.
    """
    responses = [
        # Iteration 1: list_documents
        _completion_response(_assistant_msg(tool_calls=[
            _tool_call("call_1", "list_documents", {"status_filter": "all"}),
        ])),
        # Iteration 2: get_document_detail
        _completion_response(_assistant_msg(tool_calls=[
            _tool_call("call_2", "get_document_detail", {"doc_id": doc_id}),
        ])),
        # Iteration 3: list_integrations
        _completion_response(_assistant_msg(tool_calls=[
            _tool_call("call_3", "list_integrations", {}),
        ])),
        # Iteration 4: Check stock for 3 SKUs (parallel tool calls)
        _completion_response(_assistant_msg(tool_calls=[
            _tool_call("call_4a", "call_api_integration", {
                "integration_name": erp_name, "method": "GET", "path": "/api/stock/PRD-001",
            }),
            _tool_call("call_4b", "call_api_integration", {
                "integration_name": erp_name, "method": "GET", "path": "/api/stock/PRD-002",
            }),
            _tool_call("call_4c", "call_api_integration", {
                "integration_name": erp_name, "method": "GET", "path": "/api/stock/PRD-003",
            }),
        ])),
        # Iteration 5: execute_python to filter
        _completion_response(_assistant_msg(tool_calls=[
            _tool_call("call_5", "execute_python", {
                "code": "result = {'in_stock': [i for i in inputs['items'] if inputs['stock'][i['sku']]['available_qty'] >= i['qty']], 'out_of_stock': [i for i in inputs['items'] if inputs['stock'][i['sku']]['available_qty'] < i['qty']]}",
                "inputs": {},
            }),
        ])),
        # Iteration 6: POST quotation to CRM (will trigger confirmation)
        _completion_response(_assistant_msg(tool_calls=[
            _tool_call("call_6", "call_api_integration", {
                "integration_name": crm_name,
                "method": "POST",
                "path": "/api/quotations",
                "body": {"customer_name": "Test Co", "items": [], "total": 11400.0},
            }),
        ])),
        # Iteration 7: execute_python to generate report
        _completion_response(_assistant_msg(tool_calls=[
            _tool_call("call_7", "execute_python", {
                "code": "result = {'report': 'Report generated'}",
                "inputs": {},
            }),
        ])),
        # Iteration 8: write_file
        _completion_response(_assistant_msg(tool_calls=[
            _tool_call("call_8", "write_file", {
                "path": "outputs/quotation_report.txt",
                "content": "Report content here",
            }),
        ])),
        # Iteration 9: Final text response (no tool calls)
        _completion_response(_assistant_msg(
            content="สรุปผลการสร้าง Quotation:\n\n✅ สร้างสำเร็จ 1 รายการ: Q-0001\n❌ สินค้า PRD-002 stock หมด",
            tool_calls=None,
        )),
    ]
    return responses


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentLoopWithMockLLM:
    """Verify AgentLoop works correctly with a mock LLM."""

    async def test_agent_loop_streams_thinking_events(self, test_ids):
        """Agent loop emits THINKING events for each iteration."""
        ids = test_ids
        db = MagicMock()
        db.query().filter().first.return_value = None

        # Mock LLM to return one final text response
        final_response = _completion_response(_assistant_msg(content="Hello!", tool_calls=None))

        with patch("app.agent.loop.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=final_response)
            mock_openai.return_value = mock_client

            # Mock CRUD operations
            with patch("app.agent.loop.crud_msg") as mock_msg, \
                 patch("app.agent.loop.crud_conv") as mock_conv, \
                 patch("app.agent.loop.crud_pending") as mock_pending:

                loop = AgentLoop(
                    db=db,
                    conversation_id=ids["conv_id"],
                    user_id=ids["user_id"],
                    job_id=ids["job_id"],
                    llm_config={"apiKey": "sk-test", "model": "gpt-4o"},
                    max_iterations=5,
                )

                events = []
                async for sse_str in loop.run("Hello agent"):
                    events.append(sse_str)

        # Parse SSE events
        parsed = []
        for evt in events:
            if evt.startswith("data: "):
                parsed.append(json.loads(evt[6:]))

        types = [e["type"] for e in parsed]
        assert "thinking" in types, f"Expected thinking event, got: {types}"
        assert "delta" in types or "done" in types, f"Expected delta/done, got: {types}"

        # Final event should be "done"
        assert parsed[-1]["type"] == "done"

    async def test_agent_loop_emits_tool_calls(self, test_ids):
        """Agent loop emits TOOL_CALL and TOOL_RESULT events."""
        ids = test_ids
        db = MagicMock()

        # Response: one tool call
        tool_response = _completion_response(_assistant_msg(tool_calls=[
            _tool_call("t1", "list_documents", {"status_filter": "all"}),
        ]))

        with patch("app.agent.loop.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=tool_response)
            mock_openai.return_value = mock_client

            with patch("app.agent.loop.crud_msg"), \
                 patch("app.agent.loop.crud_conv"), \
                 patch("app.agent.loop.crud_pending"):
                # Mock list_documents to return data
                with patch("app.agent.loop.tool_registry.execute") as mock_exec:
                    mock_exec.return_value = {"count": 1, "documents": [{"id": str(ids["doc_id"]), "filename": "test.pdf"}]}

                    loop = AgentLoop(
                        db=db, conversation_id=ids["conv_id"],
                        user_id=ids["user_id"], job_id=ids["job_id"],
                        llm_config={"apiKey": "sk-test", "model": "gpt-4o"},
                        max_iterations=5,
                    )

                    events = []
                    async for sse_str in loop.run("List documents"):
                        events.append(sse_str)

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: ")]
        types = [e["type"] for e in parsed]

        assert "tool_call" in types, f"Expected tool_call, got: {types}"
        assert "tool_result" in types, f"Expected tool_result, got: {types}"

    async def test_agent_loop_confirmation_flow(self, test_ids):
        """Agent loop emits CONFIRMATION_REQUIRED for destructive tools."""
        ids = test_ids
        db = MagicMock()

        # Response: call_api_integration POST (triggers confirmation)
        tool_response = _completion_response(_assistant_msg(tool_calls=[
            _tool_call("c1", "call_api_integration", {
                "integration_name": "CRM System",
                "method": "POST",
                "path": "/api/quotations",
                "body": {"customer_name": "Test", "items": [], "total": 100},
            }),
        ]))

        # Mock pending action
        fake_pending = MagicMock()
        fake_pending.id = uuid.uuid4()
        fake_pending.description = "เรียก External API: POST /api/quotations"

        with patch("app.agent.loop.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=tool_response)
            mock_openai.return_value = mock_client

            with patch("app.agent.loop.crud_msg"), \
                 patch("app.agent.loop.crud_conv"):

                with patch("app.agent.loop.crud_pending") as mock_pending, \
                     patch.object(AgentLoop, "_wait_for_confirmation") as mock_wait:

                    mock_pending.create.return_value = fake_pending
                    mock_wait.return_value = True  # User confirmed

                    with patch("app.agent.loop.tool_registry.execute") as mock_exec:
                        mock_exec.return_value = {"ok": True, "data": {"quotation_id": "Q-0001"}}

                        loop = AgentLoop(
                            db=db, conversation_id=ids["conv_id"],
                            user_id=ids["user_id"], job_id=ids["job_id"],
                            llm_config={"apiKey": "sk-test", "model": "gpt-4o"},
                            max_iterations=5,
                        )

                        events = []
                        async for sse_str in loop.run("Create quotation"):
                            events.append(sse_str)

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: ")]
        types = [e["type"] for e in parsed]

        assert "confirmation_required" in types, \
            f"Expected confirmation_required for POST, got: {types}"
        assert "tool_result" in types, \
            f"Expected tool_result after confirmation, got: {types}"

    async def test_agent_loop_rejects_on_user_deny(self, test_ids):
        """Agent loop emits TOOL_REJECTED when user denies confirmation."""
        ids = test_ids
        db = MagicMock()

        tool_response = _completion_response(_assistant_msg(tool_calls=[
            _tool_call("c1", "approve_document", {"doc_id": str(ids["doc_id"])}),
        ]))

        fake_pending = MagicMock()
        fake_pending.id = uuid.uuid4()
        fake_pending.description = "อนุมัติเอกสาร"

        with patch("app.agent.loop.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=tool_response)
            mock_openai.return_value = mock_client

            with patch("app.agent.loop.crud_msg"), \
                 patch("app.agent.loop.crud_conv"), \
                 patch("app.agent.loop.crud_pending") as mock_pending, \
                 patch.object(AgentLoop, "_wait_for_confirmation") as mock_wait:

                mock_pending.create.return_value = fake_pending
                mock_wait.return_value = False  # User rejected

                loop = AgentLoop(
                    db=db, conversation_id=ids["conv_id"],
                    user_id=ids["user_id"], job_id=ids["job_id"],
                    llm_config={"apiKey": "sk-test", "model": "gpt-4o"},
                    max_iterations=5,
                )

                events = []
                async for sse_str in loop.run("Approve document"):
                    events.append(sse_str)

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: ")]
        types = [e["type"] for e in parsed]

        assert "tool_rejected" in types, \
            f"Expected tool_rejected when user denies, got: {types}"

    async def test_agent_loop_hits_max_iterations(self, test_ids):
        """Agent loop stops after max_iterations with error."""
        ids = test_ids
        db = MagicMock()

        # Response that always returns tool calls (never final text)
        tool_response = _completion_response(_assistant_msg(tool_calls=[
            _tool_call("loop", "list_documents", {}),
        ]))

        with patch("app.agent.loop.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=tool_response)
            mock_openai.return_value = mock_client

            with patch("app.agent.loop.crud_msg"), \
                 patch("app.agent.loop.crud_conv"), \
                 patch("app.agent.loop.crud_pending"), \
                 patch("app.agent.loop.tool_registry.execute") as mock_exec:
                mock_exec.return_value = {"count": 1, "documents": []}

                loop = AgentLoop(
                    db=db, conversation_id=ids["conv_id"],
                    user_id=ids["user_id"], job_id=ids["job_id"],
                    llm_config={"apiKey": "sk-test", "model": "gpt-4o"},
                    max_iterations=3,
                )

                events = []
                async for sse_str in loop.run("Loop forever"):
                    events.append(sse_str)

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: ")]
        last = parsed[-1]

        assert last["type"] == "done"
        assert last.get("stopped") == "max_iterations"

    async def test_agent_loop_llm_error_handling(self, test_ids):
        """Agent loop handles LLM errors gracefully."""
        ids = test_ids
        db = MagicMock()

        with patch("app.agent.loop.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API key invalid"))
            mock_openai.return_value = mock_client

            with patch("app.agent.loop.crud_msg"), \
                 patch("app.agent.loop.crud_conv"):

                loop = AgentLoop(
                    db=db, conversation_id=ids["conv_id"],
                    user_id=ids["user_id"], job_id=ids["job_id"],
                    llm_config={"apiKey": "sk-bad", "model": "gpt-4o"},
                    max_iterations=5,
                )

                events = []
                async for sse_str in loop.run("Hello"):
                    events.append(sse_str)

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: ")]
        error_events = [e for e in parsed if e["type"] == "error"]
        assert len(error_events) > 0, f"Expected error event, got: {[e['type'] for e in parsed]}"
        assert "API key invalid" in error_events[0]["message"]

    async def test_messages_persisted_to_db(self, test_ids):
        """Agent loop saves user and assistant messages to DB."""
        ids = test_ids
        db = MagicMock()

        final_response = _completion_response(_assistant_msg(
            content="Task completed successfully.",
            tool_calls=None,
        ))

        with patch("app.agent.loop.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=final_response)
            mock_openai.return_value = mock_client

            with patch("app.agent.loop.crud_msg") as mock_msg, \
                 patch("app.agent.loop.crud_conv") as mock_conv:

                loop = AgentLoop(
                    db=db, conversation_id=ids["conv_id"],
                    user_id=ids["user_id"], job_id=ids["job_id"],
                    llm_config={"apiKey": "sk-test", "model": "gpt-4o"},
                    max_iterations=5,
                )

                async for _ in loop.run("Do something"):
                    pass

        # Verify user message saved
        user_msg_calls = [
            c for c in mock_msg.add.call_args_list
            if c.kwargs.get("role") == "user"
        ]
        assert len(user_msg_calls) == 1

        # Verify assistant message saved
        asst_msg_calls = [
            c for c in mock_msg.add.call_args_list
            if c.kwargs.get("role") == "assistant"
        ]
        assert len(asst_msg_calls) == 1

        # Verify conversation title was updated
        mock_conv.update_title.assert_called_once()
