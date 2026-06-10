"""
Skill file discovery, SKILL.md parsing, and import/export.

Implements the agentskills.io specification:
- Directory structure: skill-name/SKILL.md + optional scripts/, references/, assets/
- YAML frontmatter: name, description, license, compatibility, metadata, allowed-tools
- Validation: name format (lowercase, hyphens, 1-64 chars), description (1-1024 chars)
"""
from __future__ import annotations

import os
import re
import io
import zipfile
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# agentskills.io: name is lowercase letters, numbers, hyphens only, 1-64 chars
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")

# Default search directories (relative to project root)
DEFAULT_SKILL_DIRS = [
    ".agents/skills",
    "skills",
    ".claude/skills",
]


def parse_skill_md(file_path: str | Path) -> dict:
    """Parse a SKILL.md file into frontmatter + body.

    Returns dict with keys matching agentskills.io fields + 'body' for markdown content.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"SKILL.md not found: {file_path}")

    content = path.read_text(encoding="utf-8")

    # Parse YAML frontmatter (between --- delimiters)
    frontmatter: dict = {}
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as e:
                logger.warning(f"Invalid YAML frontmatter in {file_path}: {e}")
            body = parts[2].strip()

    # Extract known fields
    skill_data = {
        "name": str(frontmatter.get("name", "")).strip(),
        "description": str(frontmatter.get("description", "")).strip(),
        "license": str(frontmatter.get("license", "")).strip() or None,
        "compatibility": str(frontmatter.get("compatibility", "")).strip() or None,
        "metadata_": frontmatter.get("metadata") if isinstance(frontmatter.get("metadata"), dict) else None,
        "allowed_tools": str(frontmatter.get("allowed-tools", "")).strip() or None,
        "body": body,
        "file_path": str(path.resolve()),
        "directory": str(path.parent.resolve()),
    }

    return skill_data


def validate_skill(skill_data: dict) -> list[str]:
    """Validate skill data against agentskills.io specification.

    Returns list of validation errors (empty = valid).
    """
    errors = []

    name = skill_data.get("name", "")
    if not name:
        errors.append("name is required")
    elif len(name) > 64:
        errors.append(f"name must be <= 64 chars (got {len(name)})")
    elif not _NAME_RE.match(name):
        errors.append(f"name must be lowercase letters, numbers, and hyphens only: '{name}'")
    elif "--" in name:
        errors.append("name must not contain consecutive hyphens")

    desc = skill_data.get("description", "")
    if not desc:
        errors.append("description is required")
    elif len(desc) > 1024:
        errors.append(f"description must be <= 1024 chars (got {len(desc)})")

    compat = skill_data.get("compatibility")
    if compat and len(compat) > 500:
        errors.append(f"compatibility must be <= 500 chars (got {len(compat)})")

    return errors


def discover_skills(search_paths: list[str] | None = None) -> list[dict]:
    """Scan directories for SKILL.md files and parse them.

    Returns list of parsed skill data dicts.
    """
    if search_paths is None:
        search_paths = DEFAULT_SKILL_DIRS

    discovered = []
    seen_names: set[str] = set()

    for search_path in search_paths:
        base = Path(search_path)
        if not base.exists() or not base.is_dir():
            continue

        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                skill_data = parse_skill_md(str(skill_md))

                # Enforce directory name matches skill name
                dir_name = skill_dir.name.lower()
                skill_name = skill_data["name"].lower()
                if skill_name and skill_name != dir_name:
                    logger.warning(
                        f"Skill name '{skill_name}' does not match directory '{dir_name}' "
                        f"in {skill_dir}"
                    )

                # Skip duplicates — first discovery wins
                if skill_name in seen_names:
                    logger.info(f"Skipping duplicate skill '{skill_name}' at {skill_dir}")
                    continue

                errors = validate_skill(skill_data)
                if errors:
                    logger.warning(f"Invalid skill at {skill_md}: {errors}")
                    continue

                seen_names.add(skill_name)
                discovered.append(skill_data)

            except Exception as e:
                logger.error(f"Error loading skill from {skill_dir}: {e}")
                continue

    return discovered


def export_skill_to_md(skill, include_bundle: bool = False) -> bytes | str:
    """Export a skill as SKILL.md content or a ZIP bundle.

    Returns:
        str if include_bundle=False (just SKILL.md text)
        bytes if include_bundle=True (ZIP archive)
    """
    lines = ["---"]
    lines.append(f"name: {skill.name}")
    lines.append(f"description: {skill.description}")
    if getattr(skill, "license", None):
        lines.append(f"license: {skill.license}")
    if getattr(skill, "compatibility", None):
        lines.append(f"compatibility: {skill.compatibility}")
    if getattr(skill, "metadata_", None):
        import yaml
        lines.append("metadata:")
        for k, v in skill.metadata_.items():
            lines.append(f"  {k}: {v}")
    if getattr(skill, "allowed_tools", None):
        lines.append(f"allowed-tools: {skill.allowed_tools}")
    lines.append("---")
    lines.append("")
    lines.append(skill.procedure or "")

    md_content = "\n".join(lines)

    if not include_bundle:
        return md_content

    # Build ZIP bundle
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        root = f"{skill.name}/"
        zf.writestr(zipfile.ZipInfo(root), "")

        # SKILL.md
        info = zipfile.ZipInfo(f"{root}SKILL.md")
        info.external_attr = 0o644 << 16
        zf.writestr(info, md_content)

    return buffer.getvalue()
