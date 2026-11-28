"""Các bảng cơ sở dữ liệu cho định nghĩa quy trình, phiên bản bất biến, lượt chạy và đề xuất lập lại."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowVersionStatus(str, Enum):
    """Trạng thái vòng đời của một phiên bản sơ đồ quy trình."""

    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    INVALID = "INVALID"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class WorkflowRunStatus(str, Enum):
    """Trạng thái vận hành của một lượt chạy quy trình trên bộ điều phối Temporal."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_EVENT = "WAITING_EVENT"
    PAUSED = "PAUSED"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class NodeRunStatus(str, Enum):
    """Trạng thái thực thi của từng bước trong một lượt chạy quy trình."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_EVENT = "WAITING_EVENT"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class WorkflowDefinition(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Định nghĩa cấp cao của một quy trình (gom các phiên bản theo thời gian)."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "code", name="uq_workflow_definitions_org_code"),
    )

    code: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)
    domain_pack: Mapped[str] = mapped_column(sa.String(64), default="enterprise_core", nullable=False)
    request_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    is_archived: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    updated_by_user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    versions: Mapped[list[WorkflowVersion]] = relationship(
        "WorkflowVersion",
        back_populates="definition",
        order_by="WorkflowVersion.version_number.asc()",
    )


class WorkflowVersion(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Một phiên bản cụ thể của sơ đồ quy trình (khi đã `PUBLISHED` thì bất biến tuyệt đối)."""

    __tablename__ = "workflow_versions"
    __table_args__ = (
        sa.UniqueConstraint("workflow_definition_id", "version_number", name="uq_workflow_versions_def_num"),
    )

    workflow_definition_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_definitions.id", ondelete="CASCADE", name="fk_workflow_versions_definition_id"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=WorkflowVersionStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    graph_json: Mapped[dict] = mapped_column(JSONType, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    validation_report_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    score_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_from_analysis_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("request_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    definition: Mapped[WorkflowDefinition] = relationship("WorkflowDefinition", back_populates="versions")


class WorkflowRun(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Một lượt thực thi cụ thể gắn chặt vào đúng mã phiên bản và mã băm bất biến của sơ đồ."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_runs_org_idempotency"),
    )

    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_definition_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workflow_version_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    workflow_content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    temporal_workflow_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    temporal_run_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=WorkflowRunStatus.QUEUED.value,
        nullable=False,
        index=True,
    )
    replan_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    started_by_user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    result_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class WorkflowNodeRun(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu vết trạng thái, số lần thử và tóm tắt kết quả của từng bước trong lượt chạy."""

    __tablename__ = "workflow_node_runs"
    __table_args__ = (
        sa.UniqueConstraint("workflow_run_id", "node_id", "attempt", name="uq_node_runs_run_node_attempt"),
    )

    workflow_run_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=NodeRunStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    input_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    output_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    error_class: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class WorkflowReplanProposal(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Đề xuất lập lại sơ đồ mới khi quy trình gặp bế tắc (không sửa đè bản đang chạy)."""

    __tablename__ = "workflow_replan_proposals"

    workflow_run_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_version_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_versions.id", ondelete="RESTRICT", name="fk_replan_proposals_parent_version_id"),
        nullable=False,
    )
    proposed_version_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_versions.id", ondelete="SET NULL", name="fk_replan_proposals_proposed_version_id"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scope_delta_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    risk_escalated: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), default="PENDING", nullable=False)
    proposed_by_actor_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
