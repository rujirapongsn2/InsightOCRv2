"""Small dependency-free contracts shared by Workflow Agent execution and validation."""

OUTPUT_FORMAT_REQUIRED_TOOLS: dict[str, set[str]] = {
    "text": set(),
    "json": set(),
    "html": {"create_html"},
    "docx": {"create_docx"},
    "pdf": {"create_pdf"},
    "xlsx": {"write_file", "convert_to_xlsx"},
}

# Routes that satisfy an output format without the deterministic tool above.
# A Skill written before ``create_html`` existed still declares run_report_code,
# and that remains a valid (if higher-variance) way to produce HTML.
OUTPUT_FORMAT_ALTERNATIVE_TOOLS: dict[str, set[str]] = {
    "html": {"run_report_code"},
}

# The tool that renders a finished document from content alone — no code
# generation, no sandbox. Workflow nodes use it both as the primary artifact
# route and as the last-resort renderer when an agent loop ends empty-handed.
OUTPUT_FORMAT_RENDER_TOOLS: dict[str, str] = {
    "html": "create_html",
    "docx": "create_docx",
    "pdf": "create_pdf",
}

FILE_OUTPUT_FORMATS = frozenset({"html", "docx", "pdf", "xlsx"})

# Presets turn the workflow Agent node into a small number of predictable
# stages.  The first three stages only produce a handoff; only the report stage
# is allowed to create a downloadable artifact.
AGENT_TASK_PRESETS: dict[str, dict[str, object]] = {
    "custom": {},
    "analysis": {
        "output_format": "text",
        "max_iterations": 3,
        "timeout_seconds": 120,
        "request_timeout_seconds": 85,
        "max_output_tokens": 1600,
        "max_request_attempts": 1,
        "handoff_only": True,
    },
    "risk_assessment": {
        "output_format": "text",
        "max_iterations": 3,
        "timeout_seconds": 120,
        "request_timeout_seconds": 85,
        "max_output_tokens": 1200,
        "max_request_attempts": 1,
        "handoff_only": True,
    },
    "recommendations": {
        "output_format": "text",
        "max_iterations": 3,
        "timeout_seconds": 120,
        "request_timeout_seconds": 85,
        "max_output_tokens": 1200,
        "max_request_attempts": 1,
        "handoff_only": True,
    },
    "report": {
        "max_iterations": 3,
        "timeout_seconds": 300,
        "request_timeout_seconds": 240,
        # The report body is written as content, so the whole token budget goes
        # to the deliverable instead of document-generating code.
        "max_output_tokens": 8000,
        "max_request_attempts": 2,
        "handoff_only": False,
        "compose_and_render": True,
    },
}


def agent_task_preset(task: object) -> dict[str, object] | None:
    """Return a known task preset, excluding the legacy custom mode."""
    preset = AGENT_TASK_PRESETS.get(str(task or "custom"))
    return preset if preset else None


def missing_output_tools(declared: set[str], output_format: str) -> set[str]:
    """Tools a Skill must still allow to satisfy an output format."""
    required = OUTPUT_FORMAT_REQUIRED_TOOLS.get(output_format, set())
    if required & declared == required:
        return set()
    alternatives = OUTPUT_FORMAT_ALTERNATIVE_TOOLS.get(output_format, set())
    if alternatives and alternatives & declared:
        return set()
    return required - declared
