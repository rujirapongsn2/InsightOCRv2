"""Database driver and startup imports must work without a live database."""
import os
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scheme", ["postgresql+psycopg2", "postgresql"])
def test_session_import_uses_psycopg2(scheme):
    env = {**os.environ, "DATABASE_URL": f"{scheme}://test:test@127.0.0.1:1/test"}
    result = subprocess.run(
        [sys.executable, "-c", "from app.db.session import engine; assert engine.dialect.driver == 'psycopg2'; assert engine.dialect.dbapi.__name__ == 'psycopg2'"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_image_startup_imports_without_database():
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg2://test:test@127.0.0.1:1/test"}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.smoke_startup"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "driver psycopg2" in result.stdout
    assert "API, Celery tasks and Alembic imports passed" in result.stdout


def test_image_check_fails_when_database_driver_is_missing():
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, runpy; sys.modules['psycopg2'] = None; "
         "runpy.run_module('scripts.smoke_startup', run_name='__main__')"],
        cwd=BACKEND_DIR, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr
    assert "psycopg2" in result.stderr


def test_smoke_check_does_not_start_background_threads():
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg2://test:test@127.0.0.1:1/test"}
    result = subprocess.run(
        [sys.executable, "-c",
         "from unittest.mock import patch; from scripts.smoke_startup import main\n"
         "with patch('threading.Thread.start', side_effect=AssertionError('Unexpected background thread')) as start:\n"
         " main()\n"
         " assert start.call_count == 0\n"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_startup_migrations_remain_serialized(monkeypatch):
    from app.db import migrate

    events = []

    @contextmanager
    def lock(lock_id):
        assert lock_id == migrate.MIGRATION_LOCK_ID
        events.append("lock")
        yield
        events.append("unlock")

    monkeypatch.setattr(migrate, "advisory_lock", lock)
    monkeypatch.setattr(migrate, "_upgrade_to_head", lambda: events.append("upgrade"))
    monkeypatch.setattr(migrate, "_extend_integration_type_enum", lambda: events.append("enum"))
    migrate.run_startup_migrations()
    assert events == ["lock", "upgrade", "enum", "unlock"]


def test_failed_image_check_does_not_replace_services(tmp_path):
    root = BACKEND_DIR.parent
    (tmp_path / "backend").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text("#!/bin/sh\ncase \"$1\" in\nrev-parse) echo abc123;;\nbranch) echo main;;\nesac\n")
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n'
        'case "$*" in\n*" run "*) exit 1;;\nesac\n'
    )
    git.chmod(0o755)
    docker.chmod(0o755)
    log = tmp_path / "commands"
    result = subprocess.run(
        ["bash", str(root / "scripts/services.sh"), "update"],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "COMMAND_LOG": str(log)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    commands = log.read_text()
    assert "compose build" in commands
    assert "scripts.smoke_startup" in commands
    assert "compose up" not in commands
    assert "compose restart" not in commands
