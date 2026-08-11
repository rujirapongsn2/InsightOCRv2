---
name: create-skill
description: Use when a user wants to create, design, or save a reusable InsightDOC skill through Agent DOC. ใช้เมื่อผู้ใช้ต้องการสร้าง ออกแบบ หรือบันทึก Skill ใหม่สำหรับ InsightDOC.
compatibility: InsightDOC Agent DOC with skill tools enabled.
allowed-tools: list_skills create_skill
---

# Create InsightDOC Skill

Help the user create one focused, reusable Personal Skill. Do not save anything until the user has reviewed a concise draft and explicitly approved it.

## Discovery

Ask only for information that is still missing:

1. The business goal and the result the user expects.
2. When the Skill should be suggested or invoked.
3. The document/job inputs it needs and the output it should produce.
4. Whether it needs to change data, approve/reject, delete, create files, or send data to an integration.

Call `list_skills` before proposing a name. Reuse or extend an existing Skill when it already covers the request instead of creating a duplicate.

## Design rules

- Keep the Skill narrowly scoped to one repeatable outcome.
- Read and validate documents before any update. Prefer `reviewed_data`; explain uncertainty when only OCR text is available.
- Use only the minimum registered InsightDOC tools that are necessary. Do not invent tools or include shell commands, secrets, API keys, authentication tokens, or instructions that bypass permissions.
- Write explicit stop conditions for ambiguous data and external side effects. Approval, changes, deletion, and external dispatch remain subject to InsightDOC confirmation.
- Use clear Thai by default, preserve required field names/tool names exactly, and use `{{variable_name}}` only for genuine user-provided inputs.

## Draft and approval

Show a compact draft containing:

- Name: lowercase letters, numbers, and single hyphens only.
- Purpose and trigger hint.
- Inputs and expected result.
- Allowed platform tools.
- Procedure and safety boundaries.
- Invocation example: `/skill-name <optional input>`.

Ask the user to approve the draft or state the change they want. Do not call `create_skill` until the user explicitly approves the current draft.

## Save

After explicit approval, call `create_skill` with the draft. Always provide `allowed_tools` as an array of registered platform tool names; use an empty array for a guidance-only Skill. The Skill is always personal. After the tool returns `ok=true`, state the saved name and show its `/skill-name` invocation.
Do not call `execute_skill` or any document/file tool after `create_skill` succeeds in the same user turn. Creating the Skill ends this turn; the user must invoke it separately.
