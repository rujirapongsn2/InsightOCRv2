from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import deps
from app.main import app


def test_mcp_http_route_returns_scope_filtered_tools():
    principal = SimpleNamespace(
        api_token=SimpleNamespace(mcp_access_only=False, scopes=["mcp:read"]),
    )
    app.dependency_overrides[deps.get_db] = lambda: object()
    app.dependency_overrides[deps.get_current_active_api_token_principal] = lambda: principal
    try:
        response = TestClient(app).post(
            "/api/v1/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    finally:
        app.dependency_overrides.pop(deps.get_db, None)
        app.dependency_overrides.pop(deps.get_current_active_api_token_principal, None)

    assert response.status_code == 200
    tool_names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert "insightdoc_list_jobs" in tool_names
    assert "insightdoc_create_job" not in tool_names
