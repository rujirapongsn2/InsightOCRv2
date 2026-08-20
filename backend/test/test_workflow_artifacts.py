from contextlib import contextmanager
import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services import workflow_engine
from app.services.workflow_engine import NodeExecutionError, _exec_publish_artifact
from app.api.v1.endpoints import workflows as workflow_endpoints
from app.api.v1.endpoints.workflows import (
    _download_storage_file,
    _job_artifact_key,
    _upstream_job_id_from_definition,
)
from app.models.workflow import WorkflowRun


class MemoryStorage:
    def __init__(self, tmp_path: Path, files: dict[str, bytes]):
        self.tmp_path = tmp_path
        self.files = dict(files)

    def exists(self, path: str) -> bool:
        return path in self.files

    @contextmanager
    def get_local_path(self, path: str):
        file_path = self.tmp_path / path.replace("/", "_")
        file_path.write_bytes(self.files[path])
        yield str(file_path)

    def upload_file(self, file_obj, destination_path: str, content_type=None):
        self.files[destination_path] = file_obj.read()
        return destination_path


def test_publish_artifact_copies_verified_job_file_to_run_storage(tmp_path, monkeypatch):
    job_id = uuid4()
    run_id = uuid4()
    storage = MemoryStorage(
        tmp_path,
        {f"jobs/{job_id}/outputs/report-contract.docx": b"DOCX bytes"},
    )
    monkeypatch.setattr(workflow_engine, "get_storage_service", lambda: storage)

    result = _exec_publish_artifact(
        None,
        {"source_path": "outputs/report-contract.docx", "job_id": str(job_id)},
        {"_run_id": str(run_id), "_node_id": "publish_report"},
        lambda _message: None,
    )

    artifact = result["artifact"]
    assert artifact["verified"] is True
    assert artifact["filename"] == "report-contract.docx"
    assert artifact["storage_key"] == f"workflow_outputs/{run_id}/publish_report/report-contract.docx"
    assert storage.files[artifact["storage_key"]] == b"DOCX bytes"


@pytest.mark.parametrize("source_path", ["../report.docx", "documents/report.docx", "jobs/other/outputs/report.docx"])
def test_publish_artifact_rejects_paths_outside_current_job_outputs(tmp_path, monkeypatch, source_path):
    storage = MemoryStorage(tmp_path, {})
    monkeypatch.setattr(workflow_engine, "get_storage_service", lambda: storage)

    with pytest.raises(NodeExecutionError, match="(cross-job|under outputs)"):
        _exec_publish_artifact(
            None,
            {"source_path": source_path, "job_id": str(uuid4())},
            {"_run_id": str(uuid4()), "_node_id": "publish_report"},
            lambda _message: None,
        )


def test_publish_artifact_infers_a_single_upstream_job_context():
    job_id = str(uuid4())
    resolved = workflow_engine._add_inferred_publish_artifact_job_id(
        {"id": "publish", "type": "publish_artifact"},
        {"source_path": "outputs/report.docx"},
        [{"source": "agent", "target": "publish"}],
        {"agent": {"job_id": job_id}},
        {"agent": "succeeded"},
    )

    assert resolved["_inferred_job_id"] == job_id


def test_publish_artifact_resolution_is_shared_by_single_node_execution_path():
    job_id = str(uuid4())
    resolved = workflow_engine._resolve_node_config(
        {"id": "publish", "type": "publish_artifact"},
        {"source_path": "outputs/report.docx"},
        [{"source": "agent", "target": "publish"}],
        {"agent": {"job_id": job_id}},
    )

    assert resolved["_inferred_job_id"] == job_id


def test_safe_json_keeps_artifact_metadata_when_agent_output_is_truncated():
    artifact = {"filename": "report.docx", "path": "outputs/report.docx", "verified": True}
    result = workflow_engine._safe_json({
        "status": "succeeded",
        "job_id": str(uuid4()),
        "text": "x" * 210_000,
        "artifacts": [artifact],
    })

    assert result["truncated"] is True
    assert result["artifacts"] == [artifact]
    assert result["job_id"]


def test_download_storage_file_streams_content_without_buffering(tmp_path, monkeypatch):
    storage = MemoryStorage(tmp_path, {"workflow_outputs/run/report.docx": b"DOCX bytes"})
    monkeypatch.setattr(workflow_endpoints, "get_storage_service", lambda: storage)

    response = _download_storage_file(
        "workflow_outputs/run/report.docx", "report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    async def collect_body():
        return b"".join([chunk async for chunk in response.body_iterator])

    assert asyncio.run(collect_body()) == b"DOCX bytes"
    assert response.headers["content-length"] == str(len(b"DOCX bytes"))


def test_download_path_resolution_accepts_only_the_current_jobs_outputs():
    job_id = uuid4()

    assert _job_artifact_key(job_id, "outputs/report.docx") == f"jobs/{job_id}/outputs/report.docx"
    assert _job_artifact_key(job_id, f"jobs/{job_id}/outputs/report.docx") == f"jobs/{job_id}/outputs/report.docx"
    with pytest.raises(HTTPException, match="Artifact path"):
        _job_artifact_key(job_id, "jobs/another-job/outputs/report.docx")


def test_legacy_agent_artifact_recovers_job_from_upstream_run_definition():
    job_id = str(uuid4())
    run = WorkflowRun(
        id=uuid4(),
        workflow_id=uuid4(),
        definition_snapshot={
            "nodes": [
                {"id": "jobs", "type": "job_source", "data": {"config": {"job_id": job_id}}},
                {"id": "agent", "type": "llm", "data": {"config": {"mode": "agent", "job_id": ""}}},
            ],
            "edges": [{"source": "jobs", "target": "agent"}],
        },
    )

    assert _upstream_job_id_from_definition(run, "agent") == job_id
