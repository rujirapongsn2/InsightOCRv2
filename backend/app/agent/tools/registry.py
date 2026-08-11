import asyncio
import re
from typing import Callable, Any, Iterable
from dataclasses import dataclass, field

# Hard cap per tool call so one hung tool (e.g. an unresponsive external API)
# cannot stall the whole agent run. Generous enough for sandboxed python /
# report generation, which are the slowest legitimate tools.
TOOL_EXECUTION_TIMEOUT_S = 180.0


@dataclass
class ToolDef:
    name: str
    category: str
    description: str
    parameters_schema: dict
    handler: Callable
    requires_confirmation: bool = False
    requires_job_context: bool = True


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef):
        self._tools[tool.name] = tool

    def tool_catalog(self) -> list[dict]:
        """Return the stable, user-safe tool metadata used by API clients."""
        from app.agent.confirmations import requires_confirmation

        return [
            {
                "name": tool.name,
                "category": tool.category,
                "description": tool.description,
                "requires_confirmation": (
                    tool.requires_confirmation
                    or requires_confirmation(
                        tool.name,
                        {"method": "POST"} if tool.name == "call_api_integration" else {},
                    )
                ),
            }
            for tool in sorted(self._tools.values(), key=lambda item: (item.category, item.name))
        ]

    def has_tools(self, names: Iterable[str]) -> bool:
        return all(name in self._tools for name in names)

    def get_openai_schemas(
        self,
        categories: list[str] = None,
        allowed_names: set[str] | None = None,
    ) -> list[dict]:
        result = []
        for tool in self._tools.values():
            if categories and tool.category not in categories:
                continue
            if allowed_names is not None and tool.name not in allowed_names:
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
        allowed_names = getattr(context, "active_skill_allowed_tools", None)
        if allowed_names is not None and name not in allowed_names:
            return {
                "error": f"Tool '{name}' is not allowed by the active skill policy",
                "blocked_by_skill_policy": True,
            }
        try:
            result = await asyncio.wait_for(
                tool.handler(args=args, context=context),
                timeout=TOOL_EXECUTION_TIMEOUT_S,
            )
            if name == "execute_skill" and isinstance(result, dict) and result.get("ok"):
                context.activate_skill_tool_policy(
                    result.get("allowed_tool_names", []),
                    enforce=bool(result.get("enforce_tools")),
                )
            return result
        except asyncio.TimeoutError:
            return {
                "error": f"Tool '{name}' timed out after {int(TOOL_EXECUTION_TIMEOUT_S)}s",
                "timeout": True,
            }
        except Exception as e:
            return {"error": f"Tool '{name}' raised {type(e).__name__}: {e}"}


tool_registry = ToolRegistry()
