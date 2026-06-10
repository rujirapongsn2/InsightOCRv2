# Agentic Document Processing — Development Plan

> **Document Owner:** InsightDOC Team
> **Target Implementer:** AI Agent Coder
> **Status:** Ready for Development
> **Repository:** InsightOCRv2 (Softnix InsightDOC)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architectural Decision](#2-architectural-decision)
3. [Target Architecture](#3-target-architecture)
4. [Database Schema](#4-database-schema)
5. [Backend Project Structure](#5-backend-project-structure)
6. [Agent Loop Implementation](#6-agent-loop-implementation)
7. [Tool Registry — Full Specification](#7-tool-registry--full-specification)
8. [API Endpoints (SSE Streaming)](#8-api-endpoints-sse-streaming)
9. [Code Execution Sandbox](#9-code-execution-sandbox)
10. [Memory System](#10-memory-system)
11. [Skills System](#11-skills-system)
12. [Frontend Implementation](#12-frontend-implementation)
13. [End-to-End Test Case — Quotation Workflow](#13-end-to-end-test-case--quotation-workflow)
14. [Development Phases & Task Breakdown](#14-development-phases--task-breakdown)
15. [Security & Multi-tenancy](#15-security--multi-tenancy)
16. [Migration from ChatDOC](#16-migration-from-chatdoc)
17. [Testing Strategy](#17-testing-strategy)
18. [Acceptance Criteria](#18-acceptance-criteria)
19. [Glossary](#19-glossary)

---

## 1. Executive Summary

### 1.1 Goal

แทนที่ ChatDOC (read-only Q&A) ด้วย **Agentic Document Processing Engine** ที่สามารถ:

1. **อ่าน** ข้อมูลเอกสาร (OCR text, structured data)
2. **ลงมือทำ** action ต่างๆ (update, approve, trigger reprocess)
3. **เรียก External Systems** (ERP, CRM, Webhook ผ่าน API Integration)
4. **เขียน/รัน Code** ใน sandbox สำหรับการประมวลผลข้อมูล
5. **จดจำ** preferences/context ข้าม session
6. **เรียนรู้ Skills** จาก workflow ที่ใช้บ่อย

### 1.2 Non-Goals

- ❌ ไม่สร้าง agent runtime ของตัวเอง (ใช้ existing LLM Integration)
- ❌ ไม่รวม browser automation / web search
- ❌ ไม่รวม voice interface
- ❌ ไม่ทดแทน OCR/Extraction pipeline ที่มีอยู่ (เป็น tools ของ agent)

### 1.3 Success Metrics

- ✅ Agent ผ่าน end-to-end test case (Quotation Workflow) ใน [Section 13](#13-end-to-end-test-case--quotation-workflow)
- ✅ Multi-tenancy: agent เข้าถึงเฉพาะ resource ของ user ที่ login
- ✅ Streaming: ทุก tool call/result ต้อง stream ให้ user เห็นแบบ real-time
- ✅ Audit: action ทุกครั้งที่เปลี่ยนแปลงข้อมูลถูกบันทึกใน activity_log
- ✅ Latency: first-token < 3 sec, tool execution < 10 sec ต่อครั้ง

---

## 2. Architectural Decision

### 2.1 Chosen Approach: **Option B — Agent Loop in FastAPI**

```
User → FastAPI Agent Endpoint (SSE)
            │
            ▼
       Agent Loop (Python, in-process)
            │
   ┌────────┼────────┐
   ▼        ▼        ▼
LLM Call  Tool      Stream
(via      Execution Events
existing  (direct   to User
LLM       DB/MinIO/
Integration) httpx)
```

### 2.2 ทำไมไม่ใช้ Hermes / OpenAI Agents SDK / LangGraph

| ตัวเลือก | เหตุผลที่ไม่ใช้ |
|---|---|
| **Hermes (full)** | Multi-tenancy ไม่ปลอดภัย, tool callbacks ผ่าน HTTP เพิ่มชั้น, extra service |
| **OpenAI Agents SDK** | Vendor lock-in, ใช้ได้แค่ OpenAI/Compatible |
| **LangGraph / LangChain** | Dependency หนัก, abstraction มากเกินจำเป็น |

### 2.3 LLM Backend

ใช้ **LLM Integration ที่มีอยู่แล้ว** ใน InsightDOC — รองรับ OpenAI-compatible API ทุกเจ้า (GPT, Claude via proxy, Gemini, Ollama, ฯลฯ)

User เลือก LLM Integration ตอนสร้าง Agent Conversation เหมือน ChatDOC ปัจจุบัน

---

## 3. Target Architecture

### 3.1 High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  AgentPanel.tsx                                          │   │
│  │  ├─ Conversation list                                    │   │
│  │  ├─ Message stream (text + tool_call + tool_result)      │   │
│  │  ├─ Tool call cards (collapsible, with status)           │   │
│  │  └─ Confirmation dialog (for destructive actions)        │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────────────────┘
                       │ POST /api/v1/agent/run (SSE)
┌──────────────────────▼──────────────────────────────────────────┐
│                    Backend (FastAPI)                             │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  app/api/v1/endpoints/agent.py                         │    │
│  │  ├─ POST /agent/conversations                          │    │
│  │  ├─ GET  /agent/conversations                          │    │
│  │  ├─ POST /agent/conversations/{id}/messages   (SSE)    │    │
│  │  └─ POST /agent/confirm/{action_id}                    │    │
│  └────────────────────┬───────────────────────────────────┘    │
│                       │                                          │
│  ┌────────────────────▼───────────────────────────────────┐    │
│  │  app/agent/loop.py                                      │    │
│  │  ├─ AgentLoop class                                     │    │
│  │  ├─ Multi-turn tool calling                             │    │
│  │  ├─ MAX_ITERATIONS = 15                                 │    │
│  │  ├─ Streaming SSE events                                │    │
│  │  └─ Confirmation gates                                  │    │
│  └────────────────────┬───────────────────────────────────┘    │
│                       │                                          │
│  ┌────────────────────▼───────────────────────────────────┐    │
│  │  app/agent/tools/                                       │    │
│  │  ├─ registry.py        (auto-discovery)                 │    │
│  │  ├─ document_tools.py  (12 tools)                       │    │
│  │  ├─ integration_tools.py (3 tools — call External API)  │    │
│  │  ├─ code_tools.py      (execute_python — Docker)        │    │
│  │  ├─ filesystem_tools.py (MinIO read/write)              │    │
│  │  ├─ memory_tools.py    (save/recall/forget)             │    │
│  │  └─ skill_tools.py     (create/list/execute)            │    │
│  └────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
       │                  │                    │
       ▼                  ▼                    ▼
   PostgreSQL          MinIO              Docker Sandbox
   ├─ documents        ├─ jobs/...        (python:3.12-slim,
   ├─ jobs             └─ workspace/...    no network,
   ├─ integrations                         memory limit)
   ├─ agent_conversations
   ├─ agent_messages
   ├─ agent_memories      ←  ← External Calls (via gateway)
   └─ agent_skills          ├─ LLM (existing Integration)
                            └─ ERP/CRM (API Integration)
```

### 3.2 Component Responsibilities

| Component | Responsibility |
|---|---|
| `agent.py` (endpoint) | HTTP/SSE interface, auth, conversation CRUD |
| `loop.py` | Multi-turn LLM call → tool exec → stream events |
| `registry.py` | Tool discovery, OpenAI-format schema generation |
| `*_tools.py` | Implementation of each tool category |
| `context.py` | Build system prompt + inject memory/skills |
| Frontend `AgentPanel` | Render messages, tool calls, confirmations |

---

## 4. Database Schema

### 4.1 New Tables

#### `agent_conversations`

```sql
CREATE TABLE agent_conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    integration_id  UUID REFERENCES integrations(id) ON DELETE SET NULL,
    title           VARCHAR(255),
    system_prompt   TEXT,            -- override default if set
    max_iterations  INTEGER DEFAULT 15,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_conv_job  ON agent_conversations(job_id);
CREATE INDEX idx_agent_conv_user ON agent_conversations(user_id);
```

#### `agent_messages`

```sql
CREATE TABLE agent_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,  -- "user" | "assistant" | "tool"
    content         TEXT,                  -- text content (for user/assistant)
    tool_calls      JSONB,                 -- [{id, name, arguments}, ...]
    tool_call_id    VARCHAR(100),          -- for role="tool" linking back
    tool_name       VARCHAR(100),          -- for role="tool"
    tool_result     JSONB,                 -- for role="tool"
    iteration       INTEGER,               -- which agent loop iteration
    model_used      VARCHAR(100),
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_msg_conv ON agent_messages(conversation_id, created_at);
```

#### `agent_memories`

```sql
CREATE TABLE agent_memories (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id        UUID REFERENCES jobs(id) ON DELETE CASCADE,    -- nullable for user-level
    scope         VARCHAR(20) NOT NULL,  -- "user" | "job"
    memory_type   VARCHAR(30) NOT NULL,  -- "fact" | "preference" | "observation"
    key           VARCHAR(200) NOT NULL,
    content       TEXT NOT NULL,
    importance    REAL DEFAULT 1.0,
    access_count  INTEGER DEFAULT 0,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, scope, key, job_id)
);

CREATE INDEX idx_agent_mem_user_scope ON agent_memories(user_id, scope);
CREATE INDEX idx_agent_mem_job ON agent_memories(job_id);
```

> **Note:** Phase 2 ใช้ keyword search ก่อน — Phase 6+ พิจารณา pgvector สำหรับ semantic search

#### `agent_skills`

```sql
CREATE TABLE agent_skills (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    description     TEXT NOT NULL,
    trigger_hint    TEXT,                -- "when user wants to bulk approve invoices"
    procedure       TEXT NOT NULL,       -- step-by-step in natural language
    tools_used      JSONB,               -- ["approve_document", ...]
    success_count   INTEGER DEFAULT 0,
    created_by      VARCHAR(20) DEFAULT 'user',  -- "user" | "agent"
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, name)
);
```

#### `agent_pending_actions`

ใช้สำหรับ confirmation gate — ก่อน execute destructive action ต้อง user confirm ผ่าน UI

```sql
CREATE TABLE agent_pending_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool_name       VARCHAR(100) NOT NULL,
    tool_arguments  JSONB NOT NULL,
    description     TEXT,                 -- human-readable summary
    status          VARCHAR(20) DEFAULT 'pending',  -- "pending"|"confirmed"|"rejected"|"expired"
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ DEFAULT NOW() + INTERVAL '5 minutes'
);
```

### 4.2 Schema Modifications

#### Integration config — เพิ่ม `baseUrl` field สำหรับ API type

ไม่ต้อง migrate DB (เพราะ config เป็น JSONB) — แค่ update UI/code:

```jsonc
// ก่อน (ใช้ได้ทั้งสองรูปแบบเพื่อ backward compat)
{ "endpoint": "https://erp.example.com/api/documents", "method": "POST", ... }

// หลัง (รูปแบบใหม่ที่ agent ใช้)
{ "baseUrl": "https://erp.example.com", "method": "POST", "authHeader": "...", ... }
```

Logic ใน `call_api_integration()`:
```python
base = config.get("baseUrl") or config.get("endpoint", "").rstrip("/")
```

### 4.3 Alembic Migration

สร้างไฟล์ใหม่: `backend/alembic/versions/XXXX_add_agent_tables.py`

```python
"""add agent tables

Revision ID: XXXX
Revises: <previous>
Create Date: 2025-...

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'XXXX_add_agent_tables'
down_revision = '<previous>'

def upgrade():
    # agent_conversations
    op.create_table('agent_conversations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('integration_id', UUID(as_uuid=True), sa.ForeignKey('integrations.id', ondelete='SET NULL')),
        sa.Column('title', sa.String(255)),
        sa.Column('system_prompt', sa.Text),
        sa.Column('max_iterations', sa.Integer, default=15),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_agent_conv_job', 'agent_conversations', ['job_id'])
    op.create_index('idx_agent_conv_user', 'agent_conversations', ['user_id'])

    # agent_messages, agent_memories, agent_skills, agent_pending_actions
    # ... (เขียนทั้งหมดตาม schema ด้านบน)

def downgrade():
    op.drop_table('agent_pending_actions')
    op.drop_table('agent_skills')
    op.drop_table('agent_memories')
    op.drop_table('agent_messages')
    op.drop_table('agent_conversations')
```

---

## 5. Backend Project Structure

```
backend/app/
├── agent/                        ← ✨ ใหม่ทั้งโฟลเดอร์
│   ├── __init__.py
│   ├── loop.py                   ← Agent loop core
│   ├── context.py                ← Build system prompt + inject memory/skills
│   ├── llm_client.py             ← Wrapper รอบ OpenAI client (use Integration config)
│   ├── prompts.py                ← System prompt templates
│   ├── events.py                 ← SSE event types/serialization
│   ├── confirmations.py          ← Pending action handling
│   └── tools/
│       ├── __init__.py
│       ├── registry.py           ← Tool registration + OpenAI schema generation
│       ├── base.py               ← BaseTool class + decorators
│       ├── document_tools.py     ← 8 tools
│       ├── integration_tools.py  ← 3 tools (Phase 1!)
│       ├── code_tools.py         ← 1 tool (Phase 3)
│       ├── filesystem_tools.py   ← 4 tools (Phase 5)
│       ├── memory_tools.py       ← 4 tools (Phase 2)
│       └── skill_tools.py        ← 4 tools (Phase 4)
│
├── api/v1/endpoints/
│   ├── agent.py                  ← ✨ ใหม่ (replace chat.py)
│   └── chat.py                   ← เก็บไว้ก่อน, deprecate ใน Phase 6
│
├── models/
│   ├── agent_conversation.py     ← ✨ ใหม่
│   ├── agent_message.py          ← ✨ ใหม่
│   ├── agent_memory.py           ← ✨ ใหม่
│   ├── agent_skill.py            ← ✨ ใหม่
│   └── agent_pending_action.py   ← ✨ ใหม่
│
├── schemas/
│   └── agent.py                  ← ✨ ใหม่ (Pydantic schemas)
│
├── crud/
│   ├── crud_agent_conversation.py
│   ├── crud_agent_message.py
│   ├── crud_agent_memory.py
│   ├── crud_agent_skill.py
│   └── crud_agent_pending.py
│
└── services/
    └── code_sandbox.py           ← ✨ ใหม่ (Docker exec wrapper, Phase 3)
```

---

## 6. Agent Loop Implementation

### 6.1 File: `app/agent/loop.py`

```python
"""
Agent Loop — multi-turn tool calling with streaming.

Core algorithm:
  1. Build initial messages = [system_prompt, user_message]
  2. While iteration < MAX_ITER:
     a. Call LLM with tools → get response (text or tool_calls)
     b. If tool_calls → execute each tool, append tool_results to messages, loop
     c. If text only → final answer, break
  3. Stream every step as SSE events to user
"""
import json
import asyncio
from typing import AsyncGenerator, Optional
from uuid import UUID
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.agent.tools.registry import tool_registry
from app.agent.context import build_system_prompt, AgentContext
from app.agent.events import sse_event, SSEEventType
from app.agent.confirmations import requires_confirmation, create_pending_action
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.crud.crud_agent_message import agent_message as crud_msg


class AgentLoop:
    """One agent run for one user message."""

    def __init__(
        self,
        db: Session,
        conversation_id: UUID,
        user_id: UUID,
        job_id: UUID,
        llm_config: dict,        # apiKey, baseUrl, model
        max_iterations: int = 15,
    ):
        self.db = db
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.job_id = job_id
        self.llm_config = llm_config
        self.max_iterations = max_iterations

        self.client = AsyncOpenAI(
            api_key=llm_config["apiKey"],
            base_url=llm_config.get("baseUrl"),
        )

    async def run(self, user_message: str) -> AsyncGenerator[str, None]:
        """Main loop. Yields SSE-formatted strings."""

        # 1. Build context (memories, skills, history)
        context = AgentContext(
            db=self.db,
            user_id=self.user_id,
            job_id=self.job_id,
            conversation_id=self.conversation_id,
        )
        system_prompt = build_system_prompt(context, user_message)

        # 2. Load conversation history
        history = await context.load_history(limit=20)

        # 3. Build messages array (OpenAI format)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        # Save user message
        crud_msg.add(
            self.db,
            conversation_id=self.conversation_id,
            role="user",
            content=user_message,
            iteration=0,
        )

        # 4. Get tool definitions (OpenAI tool schema format)
        tools = tool_registry.get_openai_schemas(
            categories=["document", "integration", "code", "filesystem", "memory", "skill"]
        )

        # 5. Loop
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1

            # ── Stream "thinking" event ───────────────────────────
            yield sse_event(SSEEventType.THINKING, {"iteration": iteration})

            # ── Call LLM ──────────────────────────────────────────
            try:
                response = await self.client.chat.completions.create(
                    model=self.llm_config["model"],
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    stream=False,  # Phase 1: no streaming inside iteration; stream just events
                    temperature=0.2,
                )
            except Exception as e:
                yield sse_event(SSEEventType.ERROR, {"message": f"LLM call failed: {e}"})
                return

            assistant_msg = response.choices[0].message

            # ── No tool calls → final answer ──────────────────────
            if not assistant_msg.tool_calls:
                final_text = assistant_msg.content or ""

                # Stream final text
                yield sse_event(SSEEventType.DELTA, {"text": final_text})

                # Save assistant message
                crud_msg.add(
                    self.db,
                    conversation_id=self.conversation_id,
                    role="assistant",
                    content=final_text,
                    iteration=iteration,
                    model_used=self.llm_config["model"],
                    tokens_in=response.usage.prompt_tokens,
                    tokens_out=response.usage.completion_tokens,
                )

                yield sse_event(SSEEventType.DONE, {
                    "iterations": iteration,
                    "final_text": final_text,
                })
                return

            # ── Tool calls present → execute each ─────────────────
            messages.append({
                "role": "assistant",
                "content": assistant_msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in assistant_msg.tool_calls
                ],
            })
            crud_msg.add(
                self.db,
                conversation_id=self.conversation_id,
                role="assistant",
                content=assistant_msg.content,
                tool_calls=[tc.model_dump() for tc in assistant_msg.tool_calls],
                iteration=iteration,
                model_used=self.llm_config["model"],
            )

            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                # ── Stream "tool_call" event ──────────────────────
                yield sse_event(SSEEventType.TOOL_CALL, {
                    "id": tool_call.id,
                    "name": tool_name,
                    "arguments": args,
                })

                # ── Confirmation gate for destructive actions ─────
                if requires_confirmation(tool_name, args):
                    pending_id = create_pending_action(
                        self.db,
                        conversation_id=self.conversation_id,
                        user_id=self.user_id,
                        tool_name=tool_name,
                        tool_arguments=args,
                    )
                    yield sse_event(SSEEventType.CONFIRMATION_REQUIRED, {
                        "pending_action_id": str(pending_id),
                        "tool_name": tool_name,
                        "summary": _describe_action(tool_name, args),
                    })

                    # Wait for user confirmation (poll DB up to 5 min)
                    confirmed = await _wait_for_confirmation(self.db, pending_id, timeout=300)
                    if not confirmed:
                        result = {"error": "User rejected or timeout"}
                        yield sse_event(SSEEventType.TOOL_REJECTED, {"id": tool_call.id})
                    else:
                        result = await tool_registry.execute(
                            tool_name, args,
                            context=context,
                        )
                else:
                    # ── Execute tool ──────────────────────────────
                    try:
                        result = await tool_registry.execute(
                            tool_name, args,
                            context=context,
                        )
                    except Exception as e:
                        result = {"error": str(e)}

                # ── Stream "tool_result" event ────────────────────
                yield sse_event(SSEEventType.TOOL_RESULT, {
                    "id": tool_call.id,
                    "name": tool_name,
                    "result": _summarize_result(result),
                })

                # Save tool message
                crud_msg.add(
                    self.db,
                    conversation_id=self.conversation_id,
                    role="tool",
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    tool_result=result,
                    iteration=iteration,
                )

                # Append to messages for next LLM iteration
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            # ── End of iteration → loop back ──────────────────────

        # Reached max iterations
        yield sse_event(SSEEventType.ERROR, {
            "message": f"Reached max iterations ({self.max_iterations})",
        })


def _describe_action(tool_name: str, args: dict) -> str:
    """Human-readable summary for confirmation dialog."""
    if tool_name == "approve_document":
        return f"อนุมัติเอกสาร {args.get('doc_id')}"
    if tool_name == "bulk_approve":
        return f"อนุมัติเอกสารหลายชิ้นใน Job (criteria: {args})"
    if tool_name == "call_api_integration":
        method = args.get("method", "GET")
        path = args.get("path", "")
        if method != "GET":
            return f"เรียก External API: {method} {path}"
    return f"{tool_name}({args})"


def _summarize_result(result: dict, max_chars: int = 500) -> dict:
    """Truncate large results for SSE streaming (full result still in DB)."""
    text = json.dumps(result, ensure_ascii=False)
    if len(text) > max_chars:
        return {"_truncated": True, "preview": text[:max_chars] + "..."}
    return result


async def _wait_for_confirmation(db: Session, pending_id: UUID, timeout: int) -> bool:
    """Poll DB every 1s for confirmation status."""
    from app.crud.crud_agent_pending import agent_pending as crud_pending
    elapsed = 0
    while elapsed < timeout:
        await asyncio.sleep(1)
        elapsed += 1
        action = crud_pending.get(db, pending_id)
        if action and action.status == "confirmed":
            return True
        if action and action.status in ("rejected", "expired"):
            return False
    return False
```

### 6.2 SSE Event Types (`app/agent/events.py`)

```python
import json
from enum import Enum

class SSEEventType(str, Enum):
    THINKING              = "thinking"               # agent กำลังคิด
    TOOL_CALL             = "tool_call"              # agent เรียก tool
    TOOL_RESULT           = "tool_result"            # tool คืนผล
    TOOL_REJECTED         = "tool_rejected"          # user ปฏิเสธ
    DELTA                 = "delta"                  # text streaming
    CONFIRMATION_REQUIRED = "confirmation_required"  # ต้อง user confirm
    DONE                  = "done"                   # จบรอบ
    ERROR                 = "error"

def sse_event(event_type: SSEEventType, payload: dict) -> str:
    """Format as SSE: 'data: {...}\n\n'"""
    data = {"type": event_type.value, **payload}
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
```

---

## 7. Tool Registry — Full Specification

### 7.1 Tool Base Class (`app/agent/tools/base.py`)

```python
from typing import Callable, Any
from pydantic import BaseModel
from dataclasses import dataclass, field

@dataclass
class ToolDef:
    name: str
    category: str             # "document"|"integration"|"code"|...
    description: str
    parameters_schema: dict   # JSON Schema for OpenAI tool format
    handler: Callable         # async function
    requires_confirmation: bool = False
    requires_job_context: bool = True

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef):
        self._tools[tool.name] = tool

    def get_openai_schemas(self, categories: list[str] = None) -> list[dict]:
        result = []
        for tool in self._tools.values():
            if categories and tool.category not in categories:
                continue
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                },
            })
        return result

    async def execute(self, name: str, args: dict, context) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not found"}
        return await tool.handler(args=args, context=context)

tool_registry = ToolRegistry()
```

### 7.2 Tool Specifications

#### Phase 1 Tools — Document Tools (8 tools)

| Tool Name | Category | Confirmation? | Description |
|---|---|---|---|
| `list_documents` | document | No | List documents in current job with status, confidence |
| `get_document_detail` | document | No | Full OCR text + extracted_data + reviewed_data |
| `search_documents` | document | No | Keyword search across OCR text in job |
| `compare_documents` | document | No | Compare extracted_data of 2 documents, return diff |
| `update_document_field` | document | **Yes** | Update single field in extracted/reviewed_data |
| `approve_document` | document | **Yes** | Set status=reviewed, decision=approved |
| `reject_document` | document | **Yes** | Set status=reviewed, decision=rejected |
| `bulk_approve` | document | **Yes** | Approve multiple docs by criteria |

#### Phase 1 Tools — Integration Tools (3 tools) ⭐

| Tool Name | Category | Confirmation? | Description |
|---|---|---|---|
| `list_integrations` | integration | No | List active API integrations available |
| `call_api_integration` | integration | **Yes (if write)** | Call any configured API integration |
| `send_to_workflow` | integration | **Yes** | Trigger webhook/workflow integration |

#### Phase 2 Tools — Memory Tools (4 tools)

| Tool Name | Confirmation? | Description |
|---|---|---|
| `save_memory` | No | Save key-value memory (scope: user/job) |
| `recall_memory` | No | Retrieve memory by query |
| `list_memories` | No | List all memories in scope |
| `forget_memory` | Yes | Delete memory by key |

#### Phase 3 Tools — Code Tool (1 tool)

| Tool Name | Confirmation? | Description |
|---|---|---|
| `execute_python` | No | Run Python code in Docker sandbox |

#### Phase 4 Tools — Skill Tools (4 tools)

| Tool Name | Confirmation? | Description |
|---|---|---|
| `create_skill` | No | Save reusable procedure |
| `list_skills` | No | List user's skills |
| `execute_skill` | No | Run a saved skill |
| `delete_skill` | Yes | Remove a skill |

#### Phase 5 Tools — File System Tools (4 tools)

| Tool Name | Confirmation? | Description |
|---|---|---|
| `read_file` | No | Read file from MinIO (within job scope) |
| `write_file` | No | Write output file to MinIO (job/outputs/) |
| `list_files` | No | List files in job folder |
| `delete_file` | Yes | Delete a file |

### 7.3 Detailed Tool Implementations

#### `list_documents`

```python
# app/agent/tools/document_tools.py
from app.agent.tools.base import ToolDef
from app.agent.tools.registry import tool_registry
from app.models.document import Document

async def _list_documents_handler(args: dict, context) -> dict:
    db = context.db
    job_id = context.job_id

    docs = db.query(Document).filter(Document.job_id == job_id).all()
    result = [
        {
            "id": str(d.id),
            "filename": d.filename,
            "status": d.status,
            "page_count": d.page_count,
            "extraction_confidence": d.extraction_confidence,
            "has_extracted_data": d.extracted_data is not None,
            "has_reviewed_data": d.reviewed_data is not None,
            "review_decision": d.review_decision,
        }
        for d in docs
    ]
    return {"count": len(result), "documents": result}

tool_registry.register(ToolDef(
    name="list_documents",
    category="document",
    description="List all documents in the current job with their status, confidence scores, and review state. Use this to understand what documents are available before taking action.",
    parameters_schema={
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "enum": ["uploaded", "ocr_completed", "extraction_completed", "reviewed", "all"],
                "default": "all",
                "description": "Filter documents by status"
            }
        },
        "required": []
    },
    handler=_list_documents_handler,
))
```

#### `call_api_integration` (สำคัญที่สุดสำหรับ test case)

```python
# app/agent/tools/integration_tools.py
import httpx
import json
from app.agent.tools.base import ToolDef
from app.agent.tools.registry import tool_registry
from app.crud.crud_integration import integration as crud_integration

async def _call_api_integration_handler(args: dict, context) -> dict:
    db = context.db

    integration_id = args.get("integration_id")
    integration_name = args.get("integration_name")
    method = args.get("method", "GET").upper()
    path = args.get("path", "")
    query_params = args.get("query_params") or {}
    body = args.get("body")

    # Resolve integration by id or name
    integration = None
    if integration_id:
        integration = crud_integration.get(db, integration_id=integration_id)
    elif integration_name:
        all_active = crud_integration.get_all_active(db)
        for i in all_active:
            if i.name and i.name.strip().lower() == integration_name.strip().lower():
                integration = i
                break

    if not integration:
        return {"error": f"Integration not found: id={integration_id}, name={integration_name}"}
    if integration.type != "api":
        return {"error": f"Integration type must be 'api', got '{integration.type}'"}
    if integration.status != "active":
        return {"error": f"Integration is not active (status: {integration.status})"}

    # Build URL — support both 'baseUrl' (new) and 'endpoint' (legacy)
    base = (
        integration.config.get("baseUrl")
        or integration.config.get("endpoint", "").rstrip("/")
    )
    if not base:
        return {"error": "Integration has no baseUrl/endpoint configured"}
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"

    # Build headers (reuse logic from send_to_integration)
    headers = {"Content-Type": "application/json"}
    auth_header = integration.config.get("authHeader")
    if auth_header:
        for line in auth_header.split("\n"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                headers[parts[0].strip()] = parts[1].strip()
    headers_json = integration.config.get("headersJson")
    if headers_json:
        try:
            headers.update(json.loads(headers_json))
        except Exception:
            pass

    # Call API
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.request(
                method=method,
                url=url,
                params=query_params if query_params else None,
                json=body if body and method in ("POST", "PUT", "PATCH") else None,
                headers=headers,
            )

        # Parse response
        content_type = res.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                data = res.json()
            except Exception:
                data = res.text
        else:
            data = res.text

        return {
            "ok": res.status_code < 400,
            "status_code": res.status_code,
            "url": url,
            "method": method,
            "data": data,
        }
    except httpx.TimeoutException:
        return {"error": "Request timed out", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}


tool_registry.register(ToolDef(
    name="call_api_integration",
    category="integration",
    description=(
        "Call an external API through a configured API Integration (e.g. ERP, CRM). "
        "Use this to query stock levels, create records in external systems, or fetch data. "
        "The integration must be of type 'api' and active. "
        "Use list_integrations first to see available integrations."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "integration_name": {
                "type": "string",
                "description": "Name of the integration (e.g., 'ERP Stock', 'CRM System'). Use list_integrations to see options."
            },
            "integration_id": {
                "type": "string",
                "description": "Alternative to integration_name — UUID of the integration"
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET",
                "description": "HTTP method"
            },
            "path": {
                "type": "string",
                "description": "Path appended to integration's baseUrl (e.g., '/api/stock/PRD-001')"
            },
            "query_params": {
                "type": "object",
                "description": "URL query parameters (for GET/DELETE)"
            },
            "body": {
                "type": "object",
                "description": "Request body (for POST/PUT/PATCH)"
            }
        },
        "required": ["path"]
    },
    handler=_call_api_integration_handler,
    requires_confirmation=False,  # GET = safe; POST/PUT/PATCH/DELETE checked dynamically in confirmations.py
))
```

#### Confirmation Logic (`app/agent/confirmations.py`)

```python
def requires_confirmation(tool_name: str, args: dict) -> bool:
    """Determine if a tool call needs user confirmation."""
    DESTRUCTIVE_TOOLS = {
        "approve_document", "reject_document", "bulk_approve",
        "update_document_field", "delete_file", "forget_memory",
        "delete_skill", "send_to_workflow",
    }
    if tool_name in DESTRUCTIVE_TOOLS:
        return True

    # call_api_integration: confirm only for write methods
    if tool_name == "call_api_integration":
        method = args.get("method", "GET").upper()
        return method in ("POST", "PUT", "PATCH", "DELETE")

    return False
```

#### `approve_document`

```python
async def _approve_document_handler(args: dict, context) -> dict:
    db = context.db
    user_id = context.user_id
    doc_id = args["doc_id"]
    note = args.get("note")

    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.job_id == context.job_id,  # tenant isolation
    ).first()
    if not doc:
        return {"error": f"Document {doc_id} not found in current job"}

    doc.status = "reviewed"
    doc.review_decision = "approved"
    doc.reviewed_at = datetime.now(timezone.utc)
    doc.reviewed_by = user_id
    if note and not doc.reviewed_data:
        doc.reviewed_data = doc.extracted_data or {}
    db.commit()

    log_activity(
        db, user_id=user_id,
        action=Actions.REVIEW_DOCUMENT,
        resource_type="document", resource_id=str(doc.id),
        details={"decision": "approved", "agent_initiated": True, "note": note},
    )
    return {"ok": True, "doc_id": str(doc.id), "filename": doc.filename, "status": "reviewed"}

tool_registry.register(ToolDef(
    name="approve_document",
    category="document",
    description="Approve a document — sets status to 'reviewed' with decision 'approved'. Requires user confirmation.",
    parameters_schema={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "Document UUID"},
            "note": {"type": "string", "description": "Optional approval note"},
        },
        "required": ["doc_id"]
    },
    handler=_approve_document_handler,
    requires_confirmation=True,
))
```

> **เขียน handler สำหรับทุก tool ที่เหลือตามรูปแบบเดียวกัน** — ดูตารางใน 7.2 สำหรับ list ครบถ้วน

---

## 8. API Endpoints (SSE Streaming)

### 8.1 File: `app/api/v1/endpoints/agent.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from uuid import UUID

from app.api import deps
from app.agent.loop import AgentLoop
from app.crud.crud_agent_conversation import agent_conversation as crud_conv
from app.crud.crud_agent_pending import agent_pending as crud_pending
from app.crud.crud_integration import integration as crud_integration
from app.schemas.agent import (
    AgentConversationCreate,
    AgentConversationResponse,
    AgentMessageCreate,
    ConfirmActionRequest,
)

router = APIRouter()


@router.post("/conversations", status_code=201)
async def create_agent_conversation(
    data: AgentConversationCreate,
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user),
):
    """Create a new agent conversation for a job."""
    conv = crud_conv.create(
        db,
        job_id=data.job_id,
        user_id=current_user.id,
        integration_id=data.integration_id,
        max_iterations=data.max_iterations or 15,
    )
    return AgentConversationResponse.from_orm(conv)


@router.get("/conversations")
async def list_agent_conversations(
    job_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user),
):
    convs = crud_conv.get_by_job(db, job_id=job_id, user_id=current_user.id)
    return [AgentConversationResponse.from_orm(c) for c in convs]


@router.get("/conversations/{conversation_id}")
async def get_agent_conversation(
    conversation_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user),
):
    conv = crud_conv.get(db, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404)
    messages = crud_conv.get_messages(db, conversation_id)
    return {
        "conversation": AgentConversationResponse.from_orm(conv),
        "messages": [m.to_dict() for m in messages],
    }


@router.post("/conversations/{conversation_id}/messages")
async def send_agent_message(
    conversation_id: UUID,
    data: AgentMessageCreate,
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user),
):
    """
    Send a message to the agent. Returns SSE stream.

    Events:
      data: {"type": "thinking", "iteration": 1}
      data: {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
      data: {"type": "tool_result", "id": "...", "result": {...}}
      data: {"type": "confirmation_required", "pending_action_id": "...", ...}
      data: {"type": "delta", "text": "..."}
      data: {"type": "done", "iterations": N}
      data: {"type": "error", "message": "..."}
    """
    conv = crud_conv.get(db, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404)
    if not conv.integration_id:
        raise HTTPException(status_code=400, detail="No LLM integration linked")

    integration = crud_integration.get(db, integration_id=conv.integration_id)
    if not integration or integration.type != "llm":
        raise HTTPException(status_code=400, detail="Integration is not LLM type")

    llm_config = {
        "apiKey":  integration.config.get("apiKey"),
        "baseUrl": integration.config.get("baseUrl"),
        "model":   integration.config.get("model", "gpt-4o"),
    }

    loop = AgentLoop(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        job_id=conv.job_id,
        llm_config=llm_config,
        max_iterations=conv.max_iterations,
    )

    return StreamingResponse(
        loop.run(data.content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/confirm/{pending_action_id}")
async def confirm_pending_action(
    pending_action_id: UUID,
    data: ConfirmActionRequest,         # {"approved": true|false}
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user),
):
    """Confirm or reject a pending agent action."""
    action = crud_pending.get(db, pending_action_id)
    if not action or action.user_id != current_user.id:
        raise HTTPException(status_code=404)
    if action.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action is {action.status}")

    crud_pending.resolve(db, pending_action_id, "confirmed" if data.approved else "rejected")
    return {"ok": True}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_agent_conversation(
    conversation_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user),
):
    conv = crud_conv.get(db, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404)
    crud_conv.delete(db, conversation_id)
```

### 8.2 Register router in `app/api/api.py`

```python
from app.api.v1.endpoints import agent
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
```

---

## 9. Code Execution Sandbox

### 9.1 File: `app/services/code_sandbox.py`

```python
"""
Docker-based Python code execution sandbox.

Constraints:
- No network access (network_disabled=True)
- 256MB memory limit
- Read-only filesystem (except /tmp)
- 30-second timeout
- Auto-cleanup (remove=True)
"""
import json
import docker
from typing import Any

class CodeSandboxError(Exception):
    pass

async def execute_python(
    code: str,
    inputs: dict = None,
    timeout: int = 30,
    memory_mb: int = 256,
) -> dict:
    """Execute Python code in isolated Docker container."""
    inputs = inputs or {}

    # Wrap user code with input injection + result capture
    wrapped = f"""
import json, sys, traceback

inputs = {json.dumps(inputs, ensure_ascii=False)}
result = None
__error__ = None

try:
    # ── User Code Start ──
{_indent(code, 4)}
    # ── User Code End ──
except Exception as e:
    __error__ = {{
        "type": type(e).__name__,
        "message": str(e),
        "traceback": traceback.format_exc(),
    }}

# Capture output
__output__ = {{
    "result": result,
    "error": __error__,
}}
print("__SANDBOX_OUTPUT__:" + json.dumps(__output__, ensure_ascii=False, default=str))
"""

    try:
        client = docker.from_env()
        container_output = client.containers.run(
            image="python:3.12-slim",
            command=["python", "-c", wrapped],
            mem_limit=f"{memory_mb}m",
            memswap_limit=f"{memory_mb}m",
            cpu_period=100000,
            cpu_quota=50000,            # 0.5 CPU
            network_disabled=True,
            read_only=True,
            tmpfs={"/tmp": "size=64m,mode=1777"},
            remove=True,
            stdout=True,
            stderr=True,
            detach=False,
        )

        output = container_output.decode("utf-8", errors="replace")

        # Parse sandbox output
        result_data = {"result": None, "error": None, "stdout": output}
        for line in output.splitlines():
            if line.startswith("__SANDBOX_OUTPUT__:"):
                try:
                    sandbox_out = json.loads(line[19:])
                    result_data["result"] = sandbox_out.get("result")
                    result_data["error"] = sandbox_out.get("error")
                except json.JSONDecodeError:
                    pass
        return result_data

    except docker.errors.ContainerError as e:
        return {"error": "Container exited with error", "stderr": e.stderr.decode("utf-8") if e.stderr else ""}
    except Exception as e:
        return {"error": f"Sandbox failed: {str(e)}"}


def _indent(code: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in code.splitlines())
```

### 9.2 Tool: `execute_python` (`app/agent/tools/code_tools.py`)

```python
from app.agent.tools.base import ToolDef
from app.agent.tools.registry import tool_registry
from app.services.code_sandbox import execute_python

async def _execute_python_handler(args: dict, context) -> dict:
    code = args.get("code", "")
    inputs = args.get("inputs", {})
    if not code:
        return {"error": "code is required"}
    return await execute_python(code=code, inputs=inputs, timeout=30)

tool_registry.register(ToolDef(
    name="execute_python",
    category="code",
    description=(
        "Execute Python code in an isolated sandbox. The code has access to `inputs` (dict) "
        "and should set `result` variable to return data. No network access available. "
        "Use for data processing, calculations, format conversion. Standard library only."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute. Set 'result' variable to return data."},
            "inputs": {"type": "object", "description": "Data passed to code as 'inputs' dict"},
        },
        "required": ["code"]
    },
    handler=_execute_python_handler,
))
```

### 9.3 Docker Setup

เพิ่มใน `docker-compose.yml`:

```yaml
services:
  backend:
    # ... existing config
    volumes:
      - documents_uploads:/app/uploads
      - /var/run/docker.sock:/var/run/docker.sock  # ⚠️ Allow container to spawn containers
    environment:
      - SANDBOX_IMAGE=python:3.12-slim
```

> **Security note:** Mount Docker socket gives backend container ability to spawn containers. ใน production พิจารณา **DinD (Docker-in-Docker)** หรือ **gVisor** หรือ **Firecracker** สำหรับ isolation ที่แข็งแกร่งกว่า

---

## 10. Memory System

### 10.1 Tools (`app/agent/tools/memory_tools.py`)

```python
async def _save_memory_handler(args: dict, context) -> dict:
    db = context.db
    crud_agent_memory.upsert(
        db,
        user_id=context.user_id,
        job_id=context.job_id if args["scope"] == "job" else None,
        scope=args["scope"],
        memory_type=args.get("memory_type", "fact"),
        key=args["key"],
        content=args["content"],
        importance=args.get("importance", 1.0),
    )
    return {"ok": True, "key": args["key"]}

tool_registry.register(ToolDef(
    name="save_memory",
    category="memory",
    description="Save a memory for future sessions. Use 'user' scope for global preferences, 'job' scope for job-specific facts.",
    parameters_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "content": {"type": "string"},
            "scope": {"type": "string", "enum": ["user", "job"]},
            "memory_type": {"type": "string", "enum": ["fact", "preference", "observation"]},
            "importance": {"type": "number", "minimum": 0, "maximum": 5}
        },
        "required": ["key", "content", "scope"]
    },
    handler=_save_memory_handler,
))

# recall_memory, list_memories, forget_memory follow same pattern
```

### 10.2 Auto-inject Relevant Memories

ใน `app/agent/context.py`:

```python
def build_system_prompt(context: AgentContext, user_message: str) -> str:
    memories = context.recall_relevant_memories(user_message, limit=10)
    skills = context.list_relevant_skills(user_message, limit=5)

    return f"""You are an Agentic Document Processing assistant for InsightDOC.

## Your Capabilities
- Read documents (OCR text, structured data)
- Update/approve/reject documents
- Call external APIs (ERP, CRM) via configured integrations
- Execute Python code for data processing
- Read/write files in MinIO
- Save and recall memories

## Current Context
- Job ID: {context.job_id}
- User ID: {context.user_id}

## Relevant Memories
{_format_memories(memories)}

## Available Skills
{_format_skills(skills)}

## Rules
1. Always use list_documents first to understand what's available
2. Confirm with user before destructive actions (the system will gate this)
3. When calling external APIs, check integration_name first via list_integrations
4. Cite document filenames when referencing data
5. Respond in the same language as the user (Thai or English)
6. After completing a multi-step task, summarize what was done and offer next steps
"""
```

---

## 11. Skills System

### 11.1 Skill Tools (`app/agent/tools/skill_tools.py`)

```python
async def _execute_skill_handler(args: dict, context) -> dict:
    """Inject skill procedure into LLM context for the next iteration."""
    db = context.db
    skill_name = args["name"]
    skill_args = args.get("arguments", {})

    skill = crud_agent_skill.get_by_name(db, user_id=context.user_id, name=skill_name)
    if not skill:
        return {"error": f"Skill '{skill_name}' not found"}

    # Increment usage
    skill.success_count += 1
    db.commit()

    # Return procedure as instruction text
    return {
        "skill_name": skill.name,
        "procedure": skill.procedure,
        "arguments": skill_args,
        "instruction": (
            f"Execute the following skill: '{skill.name}'.\n\n"
            f"Procedure:\n{skill.procedure}\n\n"
            f"Arguments: {skill_args}\n\n"
            "Follow these steps using the available tools."
        ),
    }

tool_registry.register(ToolDef(
    name="execute_skill",
    category="skill",
    description="Execute a saved skill (reusable procedure). The procedure will be injected as instructions for the next steps.",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["name"]
    },
    handler=_execute_skill_handler,
))
```

---

## 12. Frontend Implementation

### 12.1 New Components

```
frontend/components/agent/
├── AgentPanel.tsx           ← Main panel (replace ChatPanel)
├── AgentMessage.tsx         ← Render message by role/type
├── ToolCallCard.tsx         ← Collapsible tool call display
├── ToolResultCard.tsx       ← Tool result with status
├── ConfirmationDialog.tsx   ← Modal for destructive actions
├── ThinkingIndicator.tsx    ← Pulsing "agent thinking" indicator
└── IntegrationSelector.tsx  ← Choose LLM integration
```

### 12.2 SSE Event Handling

```tsx
// AgentPanel.tsx — core streaming logic

const sendMessage = async (content: string) => {
    setStreaming(true);
    const events: AgentEvent[] = [];

    const res = await fetch(`${apiBase}/agent/conversations/${convId}/messages`, {
        method: "POST",
        headers: { ...headers(), "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
    });

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const evt = JSON.parse(line.slice(6));

            switch (evt.type) {
                case "thinking":
                    setThinkingIteration(evt.iteration);
                    break;
                case "tool_call":
                    events.push({ type: "tool_call", ...evt });
                    setEvents([...events]);
                    break;
                case "tool_result":
                    events.push({ type: "tool_result", ...evt });
                    setEvents([...events]);
                    break;
                case "confirmation_required":
                    setPendingAction(evt);
                    break;
                case "delta":
                    setStreamText(prev => prev + evt.text);
                    break;
                case "done":
                    setStreaming(false);
                    break;
                case "error":
                    setError(evt.message);
                    break;
            }
        }
    }
};

const confirmAction = async (approved: boolean) => {
    await fetch(`${apiBase}/agent/confirm/${pendingAction.pending_action_id}`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ approved }),
    });
    setPendingAction(null);
};
```

### 12.3 Tool Call Card (UX)

```tsx
// ToolCallCard.tsx

export function ToolCallCard({ call, result, status }: Props) {
    const [expanded, setExpanded] = useState(false);

    const icon = {
        document: "📄",
        integration: "🔗",
        code: "⚡",
        filesystem: "💾",
        memory: "🧠",
        skill: "🎯",
    }[getCategory(call.name)] || "🔧";

    return (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 my-2">
            <button
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center gap-2 text-left"
            >
                <span>{icon}</span>
                <code className="text-xs font-mono">{call.name}</code>
                <StatusBadge status={status} />
                <ChevronDown className={expanded ? "rotate-180" : ""} />
            </button>

            {expanded && (
                <div className="mt-2 space-y-2 text-xs">
                    <details>
                        <summary>Arguments</summary>
                        <pre className="bg-white rounded p-2 overflow-auto">
                            {JSON.stringify(call.arguments, null, 2)}
                        </pre>
                    </details>
                    {result && (
                        <details>
                            <summary>Result</summary>
                            <pre className="bg-white rounded p-2 overflow-auto">
                                {JSON.stringify(result, null, 2)}
                            </pre>
                        </details>
                    )}
                </div>
            )}
        </div>
    );
}
```

---

## 13. End-to-End Test Case — Quotation Workflow

### 13.1 Scenario

User สร้าง project **"Create Quotation"** อัปโหลด PDF Request Quotation ที่มี:
- Customer info (ชื่อ, ที่อยู่)
- Line items (สินค้า, จำนวน, ราคา)

ต้องการให้ Agent:
1. Extract ข้อมูลจาก PDF
2. ตรวจ stock ทุกรายการใน ERP API
3. สำหรับสินค้าที่มี stock — สร้าง Quotation ใน CRM API
4. Generate report:
   - Quotations ที่สร้างสำเร็จ (รออนุมัติใน CRM)
   - สินค้าที่ stock หมด

### 13.2 Pre-test Setup

#### A. สร้าง JSON Schema สำหรับ Request Quotation

```json
{
  "name": "request_quotation_v1",
  "schema": {
    "type": "object",
    "properties": {
      "customer": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "address": {"type": "string"},
          "tax_id": {"type": "string"},
          "contact_email": {"type": "string"}
        }
      },
      "line_items": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "sku": {"type": "string"},
            "name": {"type": "string"},
            "qty": {"type": "number"},
            "unit_price": {"type": "number"}
          },
          "required": ["sku", "qty"]
        }
      },
      "total_amount": {"type": "number"},
      "currency": {"type": "string"}
    },
    "required": ["customer", "line_items"]
  }
}
```

#### B. สร้าง Integration (3 รายการ)

```jsonc
// 1. LLM Integration (สำหรับ agent loop)
{
  "name": "OpenAI GPT-4o",
  "type": "llm",
  "config": {
    "apiKey": "sk-...",
    "model": "gpt-4o",
    "baseUrl": null
  }
}

// 2. ERP Stock API
{
  "name": "ERP Stock",
  "type": "api",
  "config": {
    "baseUrl": "https://erp.example.com",
    "authHeader": "Authorization: Bearer ERP_TOKEN_xxx"
  }
}

// 3. CRM Quotation API
{
  "name": "CRM System",
  "type": "api",
  "config": {
    "baseUrl": "https://crm.example.com",
    "authHeader": "Authorization: Bearer CRM_TOKEN_xxx"
  }
}
```

#### C. ERP/CRM Mock Endpoints (สำหรับ test)

```python
# backend/test/mock_external_api.py — รันเป็น service แยกตอน test

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# ERP Mock
STOCK_DB = {
    "PRD-001": {"name": "สินค้า A", "available_qty": 50, "price": 500},
    "PRD-002": {"name": "สินค้า B", "available_qty": 0,  "price": 1200},
    "PRD-003": {"name": "สินค้า C", "available_qty": 20, "price": 800},
}

@app.get("/api/stock/{sku}")
def get_stock(sku: str):
    if sku not in STOCK_DB:
        return {"error": "SKU not found"}, 404
    return {"sku": sku, **STOCK_DB[sku]}

# CRM Mock
QUOTATIONS = {}

class QuotationCreate(BaseModel):
    customer_name: str
    customer_address: str
    items: list
    total: float

@app.post("/api/quotations")
def create_quotation(q: QuotationCreate):
    quotation_id = f"Q-{len(QUOTATIONS) + 1:04d}"
    QUOTATIONS[quotation_id] = q.dict()
    return {
        "quotation_id": quotation_id,
        "status": "pending_approval",
        "created_at": "2025-..."
    }
```

#### D. Test PDF

ใช้ PDF ตัวอย่างที่มีข้อมูล:
- Customer: "บริษัท ทดสอบ จำกัด"
- Items: PRD-001 (qty=10), PRD-002 (qty=5), PRD-003 (qty=8)

### 13.3 Test Flow

#### Step 1: User สร้าง Job + Upload PDF

```
POST /api/v1/jobs                  → job_id = "abc-123"
POST /api/v1/documents/upload      (PDF) → doc_id = "doc-1"
POST /api/v1/documents/{doc-1}/process (schema_id=request_quotation_v1)
→ wait for status=extraction_completed
```

#### Step 2: User สร้าง Agent Conversation

```
POST /api/v1/agent/conversations
{
  "job_id": "abc-123",
  "integration_id": "<llm-integration-uuid>"
}
```

#### Step 3: User ส่งคำสั่ง

```
POST /api/v1/agent/conversations/{conv_id}/messages
{
  "content": "ช่วยสร้าง Quotation จากเอกสารที่อัปโหลด ตรวจ stock ใน ERP ก่อน รายการที่ stock หมดให้ทำรายงานแยก รายการที่มี stock ให้สร้าง Quotation ใน CRM พร้อมสรุปผลให้ดู"
}
```

### 13.4 Expected Agent Behavior

```
Iteration 1
  → Tool call: list_documents()
  → Result: 1 document, status=extraction_completed

Iteration 2
  → Tool call: get_document_detail(doc_id="doc-1")
  → Result: customer + 3 line_items extracted

Iteration 3
  → Tool call: list_integrations()
  → Result: ERP Stock, CRM System

Iteration 4
  → Parallel tool calls:
    - call_api_integration(integration_name="ERP Stock", method="GET", path="/api/stock/PRD-001")
    - call_api_integration(integration_name="ERP Stock", method="GET", path="/api/stock/PRD-002")
    - call_api_integration(integration_name="ERP Stock", method="GET", path="/api/stock/PRD-003")
  → Results: PRD-001=50 (OK), PRD-002=0 (OUT), PRD-003=20 (OK)

Iteration 5
  → Tool call: execute_python(
      code="""
      in_stock = [i for i in inputs['items']
                  if inputs['stock'][i['sku']]['available_qty'] >= i['qty']]
      out_stock = [i for i in inputs['items']
                   if inputs['stock'][i['sku']]['available_qty'] < i['qty']]
      result = {'in_stock': in_stock, 'out_of_stock': out_stock}
      """,
      inputs={...}
    )
  → Result: in_stock=[PRD-001, PRD-003], out_of_stock=[PRD-002]

Iteration 6 [CONFIRMATION REQUIRED]
  → Tool call: call_api_integration(
      integration_name="CRM System",
      method="POST",
      path="/api/quotations",
      body={
        "customer_name": "บริษัท ทดสอบ จำกัด",
        "customer_address": "...",
        "items": [PRD-001, PRD-003],
        "total": 11400.0
      }
    )
  → System: confirmation_required event sent
  → User: clicks "Confirm" in UI
  → POST /agent/confirm/{pending_id} {approved: true}
  → Tool executes → quotation_id=Q-0001

Iteration 7
  → Tool call: execute_python(
      code="""
      report = '''
      === Quotation Creation Report ===

      Customer: {customer}

      Successful Quotation:
      - {qid}: ฿{total:,.2f}
        - {sku1} x {qty1} = ฿{sub1:,.2f}
        - {sku3} x {qty3} = ฿{sub3:,.2f}

      Out of Stock:
      - {sku2}: requested {qty2}, available 0
      '''
      result = {'report': report.format(...)}
      """
    )
  → Result: formatted report text

Iteration 8
  → Tool call: write_file(
      filename="quotation_report.txt",
      content=report_text
    )
  → Result: saved to MinIO

Iteration 9 (no tool calls — final answer)
  → Text response:
    "สรุปผลการสร้าง Quotation:

    ✅ สร้างสำเร็จ 1 รายการ:
    - Q-0001 (รออนุมัติใน CRM)
      มูลค่า ฿11,400 — สินค้า PRD-001 (10 ชิ้น), PRD-003 (8 ชิ้น)

    ❌ สินค้าที่ stock หมด:
    - PRD-002 (สินค้า B) — ต้องการ 5 ชิ้น, มีในสต็อก 0

    รายงานเต็มถูกบันทึกที่: jobs/abc-123/outputs/quotation_report.txt"
```

### 13.5 Acceptance Criteria

```
✅ Agent ใช้เครื่องมือต่อไปนี้ตามลำดับที่สมเหตุสมผล:
   list_documents → get_document_detail → list_integrations →
   call_api_integration (×3 GET) → execute_python →
   call_api_integration (POST, with confirmation) →
   execute_python → write_file → final response

✅ User เห็น confirmation dialog ก่อนสร้าง Quotation ใน CRM

✅ Agent ตอบเป็นภาษาไทย เพราะ user ใช้ภาษาไทย

✅ Quotation ถูกสร้างใน CRM mock เฉพาะรายการที่ stock เพียงพอ

✅ สินค้า PRD-002 ไม่ถูกส่งเข้า CRM (stock=0)

✅ Report file ถูกบันทึกใน MinIO

✅ Activity log บันทึก action call_api_integration ครั้งที่เป็น POST

✅ ChatMessage ถูกบันทึกครบทุก iteration ใน DB
```

---

## 14. Development Phases & Task Breakdown

### Phase 1 — Core Agent Loop (1.5-2 weeks)

**เป้าหมาย:** Agent ทำ test case ใน Section 13 ได้

#### Backend Tasks

- [ ] **T1.1** Alembic migration สร้าง 5 tables (agent_*)
- [ ] **T1.2** SQLAlchemy models + CRUD modules (5 files)
- [ ] **T1.3** Pydantic schemas (`app/schemas/agent.py`)
- [ ] **T1.4** Tool registry + base classes (`app/agent/tools/registry.py`, `base.py`)
- [ ] **T1.5** Document tools (8 tools, ~400 LOC)
- [ ] **T1.6** Integration tools — **`call_api_integration`** เป็น priority สูงสุด
- [ ] **T1.7** Agent context builder (`app/agent/context.py`) — system prompt + history
- [ ] **T1.8** Confirmations module (`app/agent/confirmations.py`)
- [ ] **T1.9** SSE events module (`app/agent/events.py`)
- [ ] **T1.10** Agent loop core (`app/agent/loop.py`)
- [ ] **T1.11** API endpoint (`app/api/v1/endpoints/agent.py`)
- [ ] **T1.12** Register router in `api.py`

#### Frontend Tasks

- [ ] **T1.13** AgentPanel component (replace usage of ChatPanel)
- [ ] **T1.14** SSE event handler
- [ ] **T1.15** ToolCallCard, ToolResultCard
- [ ] **T1.16** ConfirmationDialog
- [ ] **T1.17** ThinkingIndicator

#### Testing

- [ ] **T1.18** Mock ERP/CRM service (`backend/test/mock_external_api.py`)
- [ ] **T1.19** Unit tests for each tool handler
- [ ] **T1.20** Integration test: complete Quotation Workflow E2E
- [ ] **T1.21** Manual UI test (multi-tenant: 2 users)

### Phase 2 — Memory System (1 week)

- [ ] **T2.1** Migration: `agent_memories` table
- [ ] **T2.2** Memory model + CRUD
- [ ] **T2.3** 4 memory tools (save/recall/list/forget)
- [ ] **T2.4** Auto-inject relevant memories in `context.py`
- [ ] **T2.5** UI: memory inspector panel (read-only first)
- [ ] **T2.6** Test: agent จำ preference ข้าม session

### Phase 3 — Code Execution (1.5 weeks)

- [ ] **T3.1** `code_sandbox.py` (Docker exec wrapper)
- [ ] **T3.2** Mount Docker socket in `docker-compose.yml`
- [ ] **T3.3** `execute_python` tool + registration
- [ ] **T3.4** Pre-pull `python:3.12-slim` image at startup
- [ ] **T3.5** UI: code preview/syntax highlight ใน ToolCallCard
- [ ] **T3.6** Stress test: 50 concurrent executions
- [ ] **T3.7** Security audit: container escape, resource exhaustion

### Phase 4 — Skills System (1 week)

- [ ] **T4.1** Migration: `agent_skills` table
- [ ] **T4.2** Skill model + CRUD
- [ ] **T4.3** 4 skill tools (create/list/execute/delete)
- [ ] **T4.4** UI: skill library page (list, edit, share)
- [ ] **T4.5** Test: agent บันทึก skill หลัง task สำเร็จ และเรียกใช้ skill ได้

### Phase 5 — File System (3-5 days)

- [ ] **T5.1** 4 filesystem tools (read/write/list/delete)
- [ ] **T5.2** MinIO path scoping (`jobs/{job_id}/`)
- [ ] **T5.3** UI: download report files from agent output
- [ ] **T5.4** Test: agent สร้าง report file และ user ดาวน์โหลดได้

### Phase 6 — Polish & Deprecate ChatDOC (1 week)

- [ ] **T6.1** Migrate active ChatDOC conversations → AgentConversations
- [ ] **T6.2** Add deprecation banner ใน ChatPanel
- [ ] **T6.3** Performance optimization (LLM call caching, parallel tool exec)
- [ ] **T6.4** Documentation: user guide + tool reference
- [ ] **T6.5** Remove ChatDOC code (Phase 7)

### Total Estimate: 6-8 weeks

---

## 15. Security & Multi-tenancy

### 15.1 Tenant Isolation Rules

ทุก tool handler **ต้อง** ตรวจสอบ:

1. **Job ownership** — เอกสาร/conversation ที่เข้าถึงต้องอยู่ใน `context.job_id` เท่านั้น
2. **User ownership** — `context.user_id` ตรงกับ JWT user
3. **Integration access** — ใช้ได้เฉพาะ integration ที่ `is_active=true` และ `user_id` ตรงกัน (หรือ shared)

### 15.2 Confirmation Gate Rules

| Tool Pattern | Confirmation? |
|---|---|
| Read-only (list, get, search, recall) | No |
| Write to InsightDOC DB (approve, update) | **Yes** |
| Write to External API (POST/PUT/DELETE) | **Yes** |
| Code execution | No (sandboxed) |
| Memory write (save_memory) | No (low risk) |
| Memory delete (forget_memory) | **Yes** |
| File write to MinIO | No (within job scope) |
| File delete | **Yes** |

### 15.3 Sandbox Security

```
Layer 1: Docker container (network_disabled, read_only, mem_limit, cpu_limit)
Layer 2: Timeout (30s hard kill)
Layer 3: No mount of host filesystem
Layer 4: Auto-cleanup (--rm flag)
Layer 5: stdlib only (no pip install in sandbox)
```

### 15.4 Audit Logging

ทุก tool call ที่ `requires_confirmation=True` ต้องเขียน `activity_log` ด้วย:
- `action`: tool_name
- `resource_type`, `resource_id`: target resource
- `details`: full arguments + agent_initiated=True
- `user_id`: actual user (not impersonated)

### 15.5 Rate Limiting

- Max 10 agent runs/minute/user
- Max 100 tool calls/run
- Max 5 concurrent agent runs/user

---

## 16. Migration from ChatDOC

### 16.1 Coexistence Strategy (Phase 1-5)

```
Frontend:
  ├── /jobs/{id}/chat  → ChatPanel (existing)
  └── /jobs/{id}/agent → AgentPanel (new)
```

User เลือกได้ทั้งสองโหมด ระหว่างพัฒนาและทดสอบ

### 16.2 Deprecation Timeline

- **Phase 1-3:** ChatDOC active, AgentPanel เพิ่มเข้ามา
- **Phase 4:** ChatPanel แสดง banner "ChatDOC จะถูกแทนที่ด้วย Agent ใน X สัปดาห์"
- **Phase 6:** Hide ChatPanel button (เก็บ data เดิมไว้)
- **Phase 7:** Remove ChatPanel code + deprecate `chat.py` endpoint

### 16.3 Data Migration Script

```python
# scripts/migrate_chat_to_agent.py
# One-time script: copy active ChatConversations → AgentConversations
# Keep both tables; users can read history from either side until Phase 7

for chat_conv in db.query(ChatConversation).all():
    agent_conv = AgentConversation(
        id=chat_conv.id,
        job_id=chat_conv.job_id,
        user_id=chat_conv.user_id,
        integration_id=chat_conv.integration_id,
        title=chat_conv.title,
        max_iterations=15,
        created_at=chat_conv.created_at,
    )
    db.add(agent_conv)
    for chat_msg in chat_conv.messages:
        agent_msg = AgentMessage(
            conversation_id=agent_conv.id,
            role=chat_msg.role,
            content=chat_msg.content,
            model_used=chat_msg.model_used,
            iteration=0,
            created_at=chat_msg.created_at,
        )
        db.add(agent_msg)
db.commit()
```

---

## 17. Testing Strategy

### 17.1 Unit Tests

```
backend/test/agent/
├── test_tool_registry.py
├── test_document_tools.py
├── test_integration_tools.py     ← critical: call_api_integration
├── test_code_sandbox.py
├── test_memory_tools.py
├── test_confirmations.py
├── test_loop.py                  ← mock LLM, verify flow
└── test_context.py
```

ตัวอย่าง:

```python
# test_integration_tools.py
import pytest
from app.agent.tools.integration_tools import _call_api_integration_handler

@pytest.mark.asyncio
async def test_call_api_integration_get(mock_integration_get, mock_httpx):
    context = make_context(integration={"baseUrl": "http://erp.test"})
    result = await _call_api_integration_handler(
        args={"integration_name": "ERP", "method": "GET", "path": "/api/stock/PRD-001"},
        context=context,
    )
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert mock_httpx.last_call.url == "http://erp.test/api/stock/PRD-001"
    assert "Authorization" in mock_httpx.last_call.headers
```

### 17.2 Integration Tests

```python
# test_e2e_quotation.py
@pytest.mark.asyncio
async def test_quotation_workflow_e2e(client, db, mock_external_api):
    # Setup
    user = create_test_user(db)
    job = create_job(db, user_id=user.id, schema=QUOTATION_SCHEMA)
    upload_test_pdf(client, job.id, "test_quotation.pdf")
    process_document(client, job.id)
    create_test_integrations(db, user.id)  # LLM, ERP, CRM

    # Create agent conversation
    conv = client.post("/agent/conversations", json={
        "job_id": str(job.id),
        "integration_id": str(llm_integration.id),
    }).json()

    # Send command
    response = client.post(
        f"/agent/conversations/{conv['id']}/messages",
        json={"content": "ช่วยสร้าง Quotation..."},
        stream=True,
    )

    events = parse_sse(response)

    # Assertions
    assert any(e["type"] == "tool_call" and e["name"] == "list_documents" for e in events)
    assert any(e["type"] == "tool_call" and e["name"] == "call_api_integration" for e in events)
    assert any(e["type"] == "confirmation_required" for e in events)

    # Confirm action
    pending_id = next(e["pending_action_id"] for e in events if e["type"] == "confirmation_required")
    client.post(f"/agent/confirm/{pending_id}", json={"approved": True})

    # Continue stream → final result
    final_event = next(e for e in events if e["type"] == "done")
    assert final_event["iterations"] >= 5

    # Verify CRM was called
    assert mock_external_api.crm_quotations_created == 1
    assert mock_external_api.last_quotation["items"][0]["sku"] == "PRD-001"
```

### 17.3 Manual Test Checklist

```
[ ] Multi-tenancy: User A ไม่เห็น conversation ของ User B
[ ] Tool fail gracefully — agent อธิบาย error ให้ user เข้าใจ
[ ] Long-running task (>30 sec) — connection ไม่ขาด
[ ] Confirmation timeout — agent หยุดและแจ้ง user
[ ] Re-run conversation: history โหลดถูกต้อง, agent ใช้ context เดิม
[ ] LLM error (key หมดอายุ) — แจ้ง user ชัดเจน
[ ] PDF complex (10+ pages, 100+ line items) — ทำงานได้
[ ] Code sandbox ป้องกัน infinite loop, fork bomb, network access
```

---

## 18. Acceptance Criteria

### 18.1 Phase 1 — Definition of Done

```
□ Migration ผ่านบน fresh DB
□ ทุก agent_* table มี FK constraint และ indexes ครบ
□ Agent endpoint POST /agent/conversations/{id}/messages ส่ง SSE ได้
□ Tool registry โหลด 11 tools (8 doc + 3 integration)
□ E2E test (Quotation Workflow) PASS
□ Frontend AgentPanel ทำงานได้บน Chrome + Safari
□ Multi-tenancy test PASS (2 users, 2 jobs)
□ Activity log บันทึก agent action ครบถ้วน
□ README.md ใหม่อธิบายการใช้งาน Agent Panel
□ ไม่มี hardcoded credentials
□ ทุก tool มี docstring + parameters_schema valid
```

### 18.2 Overall Success Metrics

```
[Performance]
  ✓ First-token latency < 3 sec
  ✓ Tool execution < 10 sec ต่อครั้ง
  ✓ Agent loop จบใน 8-12 iterations สำหรับ test case นี้

[Reliability]
  ✓ Tool fail rate < 2% ใน production load
  ✓ LLM call success rate > 98%
  ✓ Confirmation flow ไม่มี race condition

[UX]
  ✓ User เห็น real-time progress ผ่าน SSE
  ✓ Tool call display readable, expandable
  ✓ Confirmation dialog ชัดเจนว่ากำลัง confirm อะไร
  ✓ Error message เข้าใจง่าย (ไม่ใช่ stack trace)

[Code Quality]
  ✓ Type hints ครบใน Python files
  ✓ ทุก tool handler มี unit test
  ✓ E2E test runs ใน CI
```

---

## 19. Glossary

| Term | Definition |
|---|---|
| **Agent Loop** | Multi-turn cycle: LLM call → tool exec → tool result → LLM call (until done) |
| **Tool** | Python function ที่ agent เรียกได้ ต้องมี OpenAI tool schema |
| **Tool Call** | Request จาก LLM ให้ execute tool (มี name + arguments) |
| **Tool Result** | Output จาก tool ส่งกลับให้ LLM ใน next iteration |
| **Confirmation Gate** | กลไกที่หยุดก่อน destructive action รอ user approve |
| **Pending Action** | Tool call ที่รอ user confirmation, มี TTL 5 นาที |
| **Iteration** | หนึ่งรอบของ Agent Loop (LLM call + tool execution) |
| **Memory** | Persistent key-value ที่ agent บันทึกข้ามแชต |
| **Skill** | Reusable procedure ที่ agent เรียนรู้และใช้ซ้ำ |
| **SSE** | Server-Sent Events — protocol สำหรับ streaming events |
| **Sandbox** | Docker container ที่รัน code แบบ isolated |
| **MinIO** | S3-compatible object storage ใช้เก็บ PDF + agent outputs |
| **Integration** | Configuration record สำหรับเชื่อม external system (LLM/API/Workflow) |

---

## Appendix A — Reference Files

| File | Purpose |
|---|---|
| [backend/app/api/v1/endpoints/chat.py](backend/app/api/v1/endpoints/chat.py) | Existing ChatDOC — reference for SSE pattern |
| [backend/app/api/v1/endpoints/integrations.py:833](backend/app/api/v1/endpoints/integrations.py) | Existing API integration call logic — reuse headers logic |
| [backend/app/models/integration.py](backend/app/models/integration.py) | Integration model — no schema changes needed |
| [backend/app/models/document.py](backend/app/models/document.py) | Document model — used by document tools |
| [backend/app/services/storage.py](backend/app/services/storage.py) | MinIO wrapper — used by filesystem tools |
| [backend/app/utils/activity_logger.py](backend/app/utils/activity_logger.py) | Activity logging — call from confirmable tools |
| [docker-compose.yml](docker-compose.yml) | Add Docker socket mount for sandbox (Phase 3) |

---

## Appendix B — LLM Prompt Template (Reference)

```
You are an Agentic Document Processing assistant for InsightDOC.

# Capabilities
You can take actions on documents in this job, query external APIs (ERP, CRM),
process data with Python, and generate reports.

# Current Context
- Job ID: {job_id}
- User: {user_name} (role: {role})
- Documents in job: {doc_count}

# Workflow Pattern
For complex tasks, follow this pattern:
1. EXPLORE: list_documents, list_integrations to understand what's available
2. ANALYZE: get_document_detail, search_documents to gather data
3. EXECUTE: call_api_integration, approve_document, etc. to take action
4. VERIFY: re-query to confirm changes
5. SUMMARIZE: report what was done

# Rules
- ALWAYS use list_documents first if user mentions documents/products/items
- ALWAYS use list_integrations before calling external APIs (so you know available names)
- For external API calls (call_api_integration), GET requests don't need confirmation,
  but POST/PUT/DELETE will trigger confirmation dialog (handled by system)
- Cite document filenames when referencing extracted data
- Respond in user's language (Thai or English) — match their last message
- After multi-step tasks, provide a clear summary with what succeeded and what didn't

# Memory & Skills
{memory_section}
{skills_section}
```

---

**End of Document**

> สำหรับคำถามหรือข้อสงสัยระหว่างพัฒนา — บันทึกเป็น GitHub Issue ใน repo InsightOCRv2 พร้อม label `agent-platform`
