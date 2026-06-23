"""Verify CONFIRMATION_REQUIRED event payload includes tool_call_id.

The frontend uses tool_call_id to badge the right ToolCallCard when
auto-confirm is on. This is a regression guard — catches removal of the
field even when the full async integration test is impractical to set up.
"""
import inspect

from app.agent import loop as loop_mod


def test_confirmation_payload_includes_tool_call_id():
    """Both CONFIRMATION_REQUIRED emit sites (openai_compatible path +
    completion_messages path) must include tool_call_id in the payload."""
    src = inspect.getsource(loop_mod)
    marker = '"tool_call_id": tc.id'
    occurrences = src.count(marker)
    assert occurrences >= 2, (
        f"Expected tool_call_id in both CONFIRMATION_REQUIRED emit sites "
        f"(openai_compatible + completion_messages paths), found "
        f"{occurrences} occurrence(s) in loop.py source"
    )


def test_confirmation_payload_still_has_required_fields():
    """Sanity check: the existing required fields haven't been removed."""
    src = inspect.getsource(loop_mod)
    for required_field in ('"pending_action_id"', '"tool_name"', '"description"', '"arguments"'):
        assert required_field in src, (
            f"Required field {required_field} missing from loop.py — "
            f"check CONFIRMATION_REQUIRED emit sites"
        )
