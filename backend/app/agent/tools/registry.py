from typing import Callable, Any
from dataclasses import dataclass, field


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
        return await tool.handler(args=args, context=context)


tool_registry = ToolRegistry()
