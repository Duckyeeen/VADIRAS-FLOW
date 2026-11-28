"""Kiểm thử tích hợp cho quá trình nâng cấp bảng Alembic từ CSDL trống và tuyến sức khỏe API."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory
from app.main import create_app
from tests.conftest import build_alembic_config

EXPECTED_ALL_TABLES = {
    # 12 bảng từ bản nâng cấp 0001
    "organizations",
    "departments",
    "users",
    "memberships",
    "roles",
    "permissions",
    "role_permissions",
    "membership_roles",
    "refresh_token_sessions",
    "agent_identities",
    "agent_capabilities",
    "agent_tool_grants",
    # 6 bảng từ bản nâng cấp 0002
    "requests",
    "request_participants",
    "request_attachments",
    "request_messages",
    "request_analyses",
    "human_tasks",
    # 4 bảng từ bản nâng cấp 0003
    "prompt_versions",
    "agent_tasks",
    "agent_runs",
    "llm_call_records",
    # 5 bảng từ bản nâng cấp 0004
    "workflow_definitions",
    "workflow_versions",
    "workflow_runs",
    "workflow_node_runs",
    "workflow_replan_proposals",
    # 6 bảng từ bản nâng cấp 0005
    "policy_sets",
    "policy_rules",
    "policy_decisions",
    "approval_requests",
    "approval_decisions",
    "permission_grants",
    # 4 bảng từ bản nâng cấp 0006
    "connector_installations",
    "connector_resource_scopes",
    "connector_operation_records",
    "webhook_inbox",
    # 3 bảng từ bản nâng cấp 0007
    "verification_runs",
    "execution_evidence",
    "audit_logs",
    # 3 bảng từ bản nâng cấp 0008
    "memory_items",
    "outbox_events",
    "sla_policies",
}


def test_alembic_upgrade_and_downgrade_from_clean_database(tmp_path: Path) -> None:
    """Chạy nâng cấp `upgrade head`, hạ cấp `downgrade base` và nâng lại trên một CSDL trống."""
    db_file = tmp_path / "clean_migration.db"
    database_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    previous_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        cfg = build_alembic_config(database_url)
        command.upgrade(cfg, "head")

        with sqlite3.connect(db_file) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        assert EXPECTED_ALL_TABLES.issubset(tables)

        command.downgrade(cfg, "base")
        with sqlite3.connect(db_file) as conn:
            remaining = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        assert EXPECTED_ALL_TABLES.isdisjoint(remaining)

        command.upgrade(cfg, "head")
        with sqlite3.connect(db_file) as conn:
            recreated = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        assert EXPECTED_ALL_TABLES.issubset(recreated)
    finally:
        if previous_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_db_url


@pytest.mark.asyncio
async def test_health_live_and_ready_endpoints(
    db_and_session_factory: tuple[str, object],
) -> None:
    """Kiểm tra `/health/live`, `/health/ready` và việc tự động gắn tiêu đề `X-Correlation-ID`."""
    database_url, session_factory = db_and_session_factory
    settings = Settings(app_env="test", database_url=database_url)
    app = create_app(settings=settings, session_factory=session_factory)  # type: ignore[arg-type]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        live_res = await client.get("/health/live")
        assert live_res.status_code == 200
        assert live_res.json() == {"status": "ok"}
        assert live_res.headers.get("X-Correlation-ID")

        ready_res = await client.get("/health/ready", headers={"X-Correlation-ID": "trace-health-001"})
        assert ready_res.status_code == 200
        assert ready_res.headers.get("X-Correlation-ID") == "trace-health-001"
        body = ready_res.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "up"
