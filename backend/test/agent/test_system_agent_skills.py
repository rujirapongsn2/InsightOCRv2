from pathlib import Path
from unittest.mock import MagicMock, patch

from app.agent.context import _skill_matches_query
from app.initial_agent_skills import sync_system_agent_skills
from app.services.skill_discovery import parse_skill_md, validate_skill


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".agents/skills/cross-document-html-report/SKILL.md").exists():
            return parent
    raise AssertionError("Could not locate repo root with .agents/skills")


def test_cross_document_skill_file_is_valid():
    skill = parse_skill_md(_repo_root() / ".agents/skills/cross-document-html-report/SKILL.md")

    assert skill["name"] == "cross-document-html-report"
    assert "multiple documents" in skill["description"]
    assert "run_report_code" in skill["allowed_tools"]
    assert "outputs/cross_document_validation_report.html" in skill["body"]
    assert validate_skill(skill) == []


def test_contract_comparison_skill_file_is_valid():
    skill = parse_skill_md(_repo_root() / ".agents/skills/contract-comparison-html-report/SKILL.md")

    assert skill["name"] == "contract-comparison-html-report"
    assert "contracts" in skill["description"]
    assert "run_report_code" in skill["allowed_tools"]
    assert "web_search" in skill["allowed_tools"]
    assert "outputs/contract_comparison_report.html" in skill["body"]
    assert "qualified legal reviewer" in skill["body"]
    assert validate_skill(skill) == []


def test_thai_cross_document_request_matches_skill():
    skill = MagicMock()
    skill.name = "cross-document-html-report"
    skill.description = "Analyze and compare multiple documents."
    skill.trigger_hint = None

    assert _skill_matches_query(
        skill,
        "ช่วยวิเคราะห์ข้อมูลระหว่างเอกสาร เพื่อรายงานความไม่ถูกต้องต่างๆ",
    ) is True


def test_thai_contract_request_matches_contract_skill():
    skill = MagicMock()
    skill.name = "contract-comparison-html-report"
    skill.description = "Analyze and compare contracts."
    skill.trigger_hint = None

    assert _skill_matches_query(
        skill,
        "ช่วยวิเคราะห์และเปรียบเทียบสัญญาฉบับเก่าและใหม่สำหรับการต่ออายุสัญญา",
    ) is True


def test_sync_system_agent_skills_upserts_file_backed_system_skill():
    db = MagicMock()
    fake_db_skill = MagicMock()
    fake_db_skill.name = "cross-document-html-report"
    fake_db_skill.scope = "system"
    fake_db_skill.source = "file"

    discovered = [{
        "name": "cross-document-html-report",
        "description": "Compare documents and create an HTML report.",
        "body": "# Procedure",
        "file_path": "/repo/.agents/skills/cross-document-html-report/SKILL.md",
        "license": None,
        "compatibility": "InsightDOC",
        "metadata_": None,
        "allowed_tools": "list_documents write_file",
    }]

    with patch("app.initial_agent_skills.discover_skills", return_value=discovered), \
         patch("app.initial_agent_skills.crud_skill.upsert_file_skill", return_value=fake_db_skill) as upsert:
        result = sync_system_agent_skills(db, search_paths=["/repo/.agents/skills"])

    upsert.assert_called_once()
    kwargs = upsert.call_args.kwargs
    assert kwargs["user_id"] is None
    assert kwargs["scope"] == "system"
    assert kwargs["name"] == "cross-document-html-report"
    assert kwargs["allowed_tools"] == "list_documents write_file"
    assert result == [{"name": "cross-document-html-report", "scope": "system", "source": "file"}]

def test_sync_system_agent_skills_upserts_multiple_file_backed_system_skills():
    db = MagicMock()
    fake_cross_doc = MagicMock(name="cross_doc_skill")
    fake_cross_doc.name = "cross-document-html-report"
    fake_cross_doc.scope = "system"
    fake_cross_doc.source = "file"
    fake_contract = MagicMock(name="contract_skill")
    fake_contract.name = "contract-comparison-html-report"
    fake_contract.scope = "system"
    fake_contract.source = "file"

    discovered = [
        {
            "name": "cross-document-html-report",
            "description": "Compare documents and create an HTML report.",
            "body": "# Procedure",
            "file_path": "/repo/.agents/skills/cross-document-html-report/SKILL.md",
            "license": None,
            "compatibility": "InsightDOC",
            "metadata_": None,
            "allowed_tools": "list_documents run_report_code",
        },
        {
            "name": "contract-comparison-html-report",
            "description": "Compare contracts and create an HTML report.",
            "body": "# Procedure",
            "file_path": "/repo/.agents/skills/contract-comparison-html-report/SKILL.md",
            "license": None,
            "compatibility": "InsightDOC",
            "metadata_": None,
            "allowed_tools": "list_documents run_report_code web_search",
        },
    ]

    with patch("app.initial_agent_skills.discover_skills", return_value=discovered), \
         patch("app.initial_agent_skills.crud_skill.upsert_file_skill", side_effect=[fake_cross_doc, fake_contract]) as upsert:
        result = sync_system_agent_skills(db, search_paths=["/repo/.agents/skills"])

    assert upsert.call_count == 2
    assert [call.kwargs["name"] for call in upsert.call_args_list] == [
        "cross-document-html-report",
        "contract-comparison-html-report",
    ]
    assert result == [
        {"name": "cross-document-html-report", "scope": "system", "source": "file"},
        {"name": "contract-comparison-html-report", "scope": "system", "source": "file"},
    ]

