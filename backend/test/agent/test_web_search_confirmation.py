from app.agent.confirmations import (
    describe_action,
    requires_confirmation,
    requires_explicit_confirmation,
)
from app.agent.tools import web_search_tools
from app.agent.tools.registry import tool_registry


def test_web_search_always_requires_confirmation():
    assert requires_confirmation("web_search", {"query": "current regulations"}) is True
    assert requires_explicit_confirmation("web_search") is True
    assert describe_action("web_search", {"query": "current regulations"}) == (
        "ค้นหาข้อมูลภายนอกจากเว็บ: current regulations"
    )


def test_web_search_catalog_requires_confirmation():
    web_search_tools  # Import registers the tool for this process.
    catalog_item = next(item for item in tool_registry.tool_catalog() if item["name"] == "web_search")
    assert catalog_item["requires_confirmation"] is True
