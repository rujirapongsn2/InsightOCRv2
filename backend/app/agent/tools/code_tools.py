from app.agent.tools.registry import ToolDef, tool_registry
from app.services.code_sandbox import execute_python


async def _execute_python_handler(args: dict, context) -> dict:
    code = args.get("code", "")
    if not code.strip():
        return {"error": "code is required"}
    if len(code) > 100_000:
        return {"error": "code must be under 100,000 characters"}

    inputs = args.get("inputs", {})
    if not isinstance(inputs, dict):
        return {"error": "inputs must be a dict"}

    allow_network = args.get("allow_network", True)
    timeout = min(int(args.get("timeout", 30)), 60)  # cap at 60s

    return await execute_python(
        code=code, inputs=inputs,
        timeout=timeout,
        allow_network=allow_network,
    )


tool_registry.register(ToolDef(
    name="execute_python",
    category="code",
    description=(
        "Execute Python code in an isolated Docker sandbox. "
        "The code has access to `inputs` (dict) and should assign to a `result` variable to return data. "
        "Network is enabled by default — use `_pip_install('package1 package2')` to install dependencies. "
        "For binary output files (xlsx, pdf, docx, pptx): save to disk then call `_save_file(path)` to get base64 — "
        "then use write_file with `content_base64` to store the file. "
        "Set `allow_network=false` to disable outbound network if not needed."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute. Use 'inputs' dict for input data. Set 'result' variable to return data. Call _pip_install('pkg') for dependencies.",
            },
            "inputs": {
                "type": "object",
                "description": "Data passed to the code as an 'inputs' dict variable",
            },
            "allow_network": {
                "type": "boolean",
                "default": True,
                "description": "Allow outbound network (for pip install, HTTP requests). Set false for untrusted code.",
            },
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "maximum": 60,
                "default": 30,
                "description": "Execution timeout in seconds.",
            },
        },
        "required": ["code"],
    },
    handler=_execute_python_handler,
))
