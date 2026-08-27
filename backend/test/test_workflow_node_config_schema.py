"""Regressions for the LLM/Agent node's config_fields schema (the builder UI
reads this to decide what to render/show — a wrong type or visibility
condition here breaks the editor without touching any Python logic).
"""
import os

os.environ.setdefault("SECRET_KEY", "test-secret")

from app.services.workflow_engine import NODE_TYPES


def _llm_field(name):
    llm_node = next(n for n in NODE_TYPES if n["type"] == "llm")
    return next(f for f in llm_node["config_fields"] if f["name"] == name)


def test_skill_ids_stays_multi_select():
    """The server accepts an arbitrary-length skill_ids list (see
    _selected_skills / workflow_validation.py); the field must let users pick
    more than one, or an existing multi-skill node loses skills on edit."""
    field = _llm_field("skill_ids")
    assert field["type"] == "skill_multi_select"


def test_output_format_is_visible_for_legacy_custom_task_nodes():
    """Nodes saved before Agent task presets existed have no agent_task key
    and are treated as 'custom' server-side (still free to pick any
    output_format) — the field must not disappear for them."""
    field = _llm_field("output_format")
    equals = field["visible_when"]["equals"]
    assert "custom" in equals
    assert "report" in equals
