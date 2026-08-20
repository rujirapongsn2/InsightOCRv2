"""Small dependency-free contracts shared by Workflow Agent execution and validation."""

OUTPUT_FORMAT_REQUIRED_TOOLS: dict[str, set[str]] = {
    "text": set(),
    "json": set(),
    "html": {"run_report_code"},
    "docx": {"create_docx"},
    "pdf": {"create_pdf"},
    "xlsx": {"write_file", "convert_to_xlsx"},
}

FILE_OUTPUT_FORMATS = frozenset({"html", "docx", "pdf", "xlsx"})
