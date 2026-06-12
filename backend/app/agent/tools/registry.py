import asyncio
from typing import Callable, Any
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
        try:
            return await asyncio.wait_for(
                tool.handler(args=args, context=context),
                timeout=TOOL_EXECUTION_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            return {
                "error": f"Tool '{name}' timed out after {int(TOOL_EXECUTION_TIMEOUT_S)}s",
                "timeout": True,
            }
        except Exception as e:
            return {"error": f"Tool '{name}' raised {type(e).__name__}: {e}"}


tool_registry = ToolRegistry()
