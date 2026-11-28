"""Các bảng cơ sở dữ liệu theo dõi phiên bản câu lệnh, tác vụ trợ lý AI và chi phí gọi mô hình."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class PromptVersion(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu vết các phiên bản mẫu câu lệnh giao cho từng vai trò trợ lý AI."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "role_code", "version", name="uq_prompt_versions_org_role_ver"),
    )

    role_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    system_prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    output_schema_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class AgentTask(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu đầu việc phân tích được Điều phối viên trưởng giao cho từng vai trò trợ lý AI."""

    __tablename__ = "agent_tasks"

    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_job_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    agent_identity_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("agent_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    role_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    round_number: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    input_snapshot_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class AgentRun(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu kết quả đầu ra có cấu trúc của một lượt chạy trợ lý AI (không lưu suy nghĩ ẩn)."""

    __tablename__ = "agent_runs"

    agent_task_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_job_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    round_number: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    structured_output_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    decision_summary: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)
    assumptions_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    evidence_refs_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)


class LLMCallRecord(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Theo dõi từng lượt gọi mô hình AI kèm độ trễ, số token, số lần sửa và nguồn chi phí."""

    __tablename__ = "llm_call_records"

    request_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    analysis_job_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    repair_attempts: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    cost_source: Mapped[str] = mapped_column(sa.String(32), default="ESTIMATED", nullable=False)
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
