import pytest

from app.schemas.api_token import APIAccessTokenCreate
from app.services.api_token_scopes import MCP_DOCUMENT_PROCESS_SCOPE, MCP_READ_SCOPE, normalize_api_token_scopes


def test_new_tokens_default_to_read_only_mcp_access():
    token = APIAccessTokenCreate(name="Read only agent")

    assert token.scopes == [MCP_READ_SCOPE]
    assert token.mcp_access_only is False


def test_scope_normalizer_keeps_read_access_for_controlled_tokens():
    assert normalize_api_token_scopes([MCP_DOCUMENT_PROCESS_SCOPE]) == [MCP_READ_SCOPE, MCP_DOCUMENT_PROCESS_SCOPE]


def test_controlled_mcp_scopes_require_an_mcp_only_token():
    with pytest.raises(ValueError, match="MCP action scopes require"):
        APIAccessTokenCreate(name="Invalid general token", scopes=[MCP_DOCUMENT_PROCESS_SCOPE])

    token = APIAccessTokenCreate(
        name="MCP processor",
        mcp_access_only=True,
        scopes=[MCP_DOCUMENT_PROCESS_SCOPE],
    )

    assert token.scopes == [MCP_READ_SCOPE, MCP_DOCUMENT_PROCESS_SCOPE]


def test_scope_normalizer_rejects_unknown_scope():
    with pytest.raises(ValueError, match="Unsupported token scope"):
        APIAccessTokenCreate(name="Bad scopes", scopes=["mcp:delete"])


def test_token_name_is_trimmed_and_cannot_be_whitespace():
    token = APIAccessTokenCreate(name="  Production agent  ")
    assert token.name == "Production agent"

    with pytest.raises(ValueError, match="must not be empty"):
        APIAccessTokenCreate(name="   ")
