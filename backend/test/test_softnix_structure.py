from types import SimpleNamespace
from unittest.mock import Mock

from app.services import structure


def test_v3_ocr_endpoint_resolves_unversioned_structure_route(monkeypatch):
    setting = SimpleNamespace(
        api_token="test-token", verify_ssl=True,
        structured_output_endpoint=None,
        ocr_endpoint="https://ocr.test/v3/ai-process-file",
        api_endpoint="https://ocr.test/v3/ai-process-file",
    )
    db = Mock()
    db.query.return_value.first.return_value = setting
    response = Mock()
    response.json.return_value = {"data": {"total": 25}}
    post = Mock(return_value=response)
    monkeypatch.setattr(structure.requests, "post", post)
    structure.extract_structure("Total: 25", '{"type":"object"}', db)
    assert post.call_args.args == ("https://ocr.test/structured-output",)
    assert post.call_args.kwargs["data"]["context"] == "Total: 25"
    assert "json_schema" in post.call_args.kwargs["data"]
