"""Web search tools for Agent DOC using DuckDuckGo.

Search is a support tool only. Document/database tool results remain source of truth
for InsightDOC job data.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.agent.tools.registry import ToolDef, tool_registry

MAX_RESULTS = 8


def _search_sync(query: str, max_results: int, region: str, safesearch: str) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS
    except Exception:
        try:
            from duckduckgo_search import DDGS
        except Exception as exc:
            return [{"error": f"ddgs/duckduckgo_search is not installed: {exc}"}]

    results: list[dict[str, Any]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(
            query,
            region=region or "wt-wt",
            safesearch=safesearch or "moderate",
            max_results=max_results,
        ):
            results.append({
                "title": item.get("title"),
                "url": item.get("href") or item.get("url"),
                "snippet": item.get("body"),
            })
    return results


async def _web_search_handler(args: dict, context) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}

    max_results = min(max(int(args.get("max_results", 5)), 1), MAX_RESULTS)
    region = str(args.get("region") or "wt-wt")
    safesearch = str(args.get("safesearch") or "moderate")

    try:
        results = await asyncio.to_thread(_search_sync, query, max_results, region, safesearch)
    except Exception as exc:
        return {"error": f"web search failed: {exc}"}

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "note": "Use web results as external context only. InsightDOC document tools remain source of truth for job data.",
    }


tool_registry.register(ToolDef(
    name="web_search",
    category="web",
    description=(
        "Search the web using DuckDuckGo for external context such as vendor information, "
        "public product references, regulations, or current facts. Do not use this as source "
        "of truth for uploaded job documents; cite URLs when using web results."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS, "default": 5},
            "region": {"type": "string", "default": "wt-wt", "description": "DuckDuckGo region, e.g. wt-wt, th-th, us-en"},
            "safesearch": {"type": "string", "enum": ["on", "moderate", "off"], "default": "moderate"},
        },
        "required": ["query"],
    },
    handler=_web_search_handler,
))
