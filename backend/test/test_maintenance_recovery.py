import os
from unittest.mock import Mock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-for-unit-tests")

from app.tasks.maintenance_tasks import _active_document_task_ids


def test_active_document_task_ids_filters_other_celery_tasks():
    inspector = Mock()
    inspector.active.return_value = {
        "worker-1": [
            {
                "id": "document-task-1",
                "name": "app.tasks.document_tasks.process_document_task",
            },
            {
                "id": "workflow-task-1",
                "name": "app.tasks.workflow_tasks.run_workflow_task",
            },
        ],
        "worker-2": None,
    }

    with patch("app.tasks.maintenance_tasks.celery_app.control.inspect", return_value=inspector):
        assert _active_document_task_ids() == {"document-task-1"}


def test_active_document_task_ids_skips_recovery_when_inspection_is_unavailable():
    inspector = Mock()
    inspector.active.return_value = None

    with patch("app.tasks.maintenance_tasks.celery_app.control.inspect", return_value=inspector):
        assert _active_document_task_ids() is None
