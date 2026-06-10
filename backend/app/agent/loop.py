"""
Agent Loop — multi-turn tool calling with streaming.

Optimizations (Phase 6):
  - System prompt sent only once (saves tokens across iterations)
  - Parallel tool execution via asyncio.gather when no confirmation needed
"""
import json
import asyncio
from typing import AsyncGenerator
from uuid import UUID
from sqlalchemy.orm import Session
from openai import AsyncOpenAI

from app.agent.context import AgentContext, build_system_prompt
from app.agent.events import sse_event, SSEEventType
from app.agent.confirmations import requires_confirmation, describe_action
from app.agent.tools.registry import tool_registry
from app.agent.tools import document_tools, integration_tools, memory_tools, code_tools, skill_tools, filesystem_tools  # noqa: F401 — side-effect: registers tools
from app.crud.crud_agent_message import agent_message as crud_msg
from app.crud.crud_agent_pending import agent_pending as crud_pending
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.utils.activity_logger import log_activity


def _tool_calls_data(msg) -> list[dict]:
    """Build OpenAI-format tool_calls array from an assistant message."""
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        }
        for tc in msg.tool_calls
    ]


async def _exec_single(tool_name: str, args: dict, context) -> dict:
    """Execute one tool and return its result."""
    return await tool_registry.execute(tool_name, args, context)


class AgentLoop:
    """One agent run for one user message."""

    def __init__(self, db: Session, conversation_id: UUID, user_id: UUID, job_id: UUID, llm_config: dict, max_iterations: int = 15):
        self.db = db
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.job_id = job_id
        self.llm_config = llm_config
        self.max_iterations = max_iterations
        self.context = AgentContext(db=db, user_id=user_id, job_id=job_id, conversation_id=conversation_id)

    async def run(self, user_message: str) -> AsyncGenerator[str, None]:
        crud_msg.add(self.db, conversation_id=self.conversation_id, role="user", content=user_message, iteration=0)
        crud_conv.update_title(self.db, self.conversation_id, user_message[:60])

        client = AsyncOpenAI(
            api_key=self.llm_config.get("apiKey"),
            base_url=self.llm_config.get("baseUrl") or None,
        )
        model = self.llm_config.get("model", "gpt-4o")
        system_prompt = build_system_prompt(self.context, user_message)
        tools_schema = tool_registry.get_openai_schemas()

        history = await self.context.load_history()

        # System prompt only once in messages[0] — subsequent iterations append to messages directly
        messages: list[dict] = [{"role": "system", "content": system_prompt}] + history

        for iteration in range(1, self.max_iterations + 1):
            yield sse_event(SSEEventType.THINKING, {"iteration": iteration})

            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools_schema,
                    tool_choice="auto",
                    stream=False,
                )
            except Exception as e:
                yield sse_event(SSEEventType.ERROR, {"message": f"LLM error: {str(e)}"})
                return

            choice = response.choices[0]
            msg = choice.message

            if msg.tool_calls:
                tcd = _tool_calls_data(msg)
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=msg.content, tool_calls=tcd,
                             iteration=iteration, model_used=model)
                messages.append({"role": "assistant", "content": msg.content, "tool_calls": tcd})

                # Parse all tool calls
                parsed: list[tuple] = []
                for tc in msg.tool_calls:
                    try:
                        parsed.append((tc, tc.function.name, json.loads(tc.function.arguments)))
                    except Exception:
                        parsed.append((tc, tc.function.name, {}))

                # Emit TOOL_CALL events
                for tc, name, args in parsed:
                    yield sse_event(SSEEventType.TOOL_CALL, {"id": tc.id, "name": name, "arguments": args})

                # Determine execution strategy
                needs_confirmation = any(requires_confirmation(name, args) for _, name, args in parsed)

                if needs_confirmation:
                    # Sequential — confirmation gates require per-tool user interaction
                    for tc, tool_name, tool_args in parsed:
                        if requires_confirmation(tool_name, tool_args):
                            pending = crud_pending.create(
                                self.db, conversation_id=self.conversation_id, user_id=self.user_id,
                                tool_name=tool_name, tool_arguments=tool_args,
                                description=describe_action(tool_name, tool_args),
                            )
                            yield sse_event(SSEEventType.CONFIRMATION_REQUIRED, {
                                "pending_action_id": str(pending.id),
                                "tool_name": tool_name,
                                "description": pending.description,
                                "arguments": tool_args,
                            })
                            approved = await self._wait_for_confirmation(pending.id)
                            if not approved:
                                result = {"error": "User rejected action", "tool_name": tool_name}
                                yield sse_event(SSEEventType.TOOL_REJECTED, {"id": tc.id, "name": tool_name})
                            else:
                                result = await tool_registry.execute(tool_name, tool_args, self.context)
                                log_activity(
                                    self.db, user_id=self.user_id,
                                    action=f"agent_tool_{tool_name}",
                                    resource_type="agent_conversation",
                                    resource_id=self.conversation_id,
                                    details={"tool_name": tool_name, "arguments": tool_args, "agent_initiated": True},
                                )
                        else:
                            result = await tool_registry.execute(tool_name, tool_args, self.context)

                        yield sse_event(SSEEventType.TOOL_RESULT, {"id": tc.id, "name": tool_name, "result": result})
                        crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                                     tool_call_id=tc.id, tool_name=tool_name,
                                     tool_result=result, iteration=iteration)
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })
                else:
                    # Parallel — all read-only tools, execute concurrently
                    tasks = [_exec_single(name, args, self.context) for _, name, args in parsed]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for (tc, tool_name, _), result in zip(parsed, results):
                        if isinstance(result, Exception):
                            result = {"error": str(result)}
                        yield sse_event(SSEEventType.TOOL_RESULT, {"id": tc.id, "name": tool_name, "result": result})
                        crud_msg.add(self.db, conversation_id=self.conversation_id, role="tool",
                                     tool_call_id=tc.id, tool_name=tool_name,
                                     tool_result=result, iteration=iteration)
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })

            else:
                final_text = msg.content or ""
                crud_msg.add(self.db, conversation_id=self.conversation_id, role="assistant",
                             content=final_text, iteration=iteration, model_used=model)

                for chunk in (final_text[i:i+50] for i in range(0, len(final_text), 50)):
                    yield sse_event(SSEEventType.DELTA, {"text": chunk})

                yield sse_event(SSEEventType.DONE, {"iterations": iteration})
                return

        yield sse_event(SSEEventType.DONE, {"iterations": self.max_iterations, "stopped": "max_iterations"})

    async def _wait_for_confirmation(self, pending_id: UUID, timeout_s: int = 300) -> bool:
        for _ in range(timeout_s):
            await asyncio.sleep(1)
            self.db.expire_all()
            action = crud_pending.get(self.db, pending_id)
            if action and action.status == "confirmed":
                return True
            if action and action.status == "rejected":
                return False
        crud_pending.resolve(self.db, pending_id, "rejected")
        return False
