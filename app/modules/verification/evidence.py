"""Thu thập bằng chứng đối chiếu ngược từ hệ thống đích, lệnh duyệt và đầu việc nhân sự."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connectors.providers.base import BaseConnector, ConnectorError
from app.modules.connectors.models import ConnectorOperationRecord
from app.modules.governance.models import ApprovalRequest
from app.modules.requests.models import HumanTask, HumanTaskStatus, VisibilityLevel


def normalize_utc(dt: datetime) -> datetime:
    """Chuẩn hóa đối tượng `datetime` về múi giờ UTC để so sánh an toàn trên cả SQLite và Postgres."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_evidence_fresh(
    captured_at: datetime,
    *,
    freshness_seconds: int,
    now: datetime | None = None,
) -> bool:
    """Kiểm tra bằng chứng có được thu thập trong khoảng thời gian tươi mới cho phép hay không."""
    ref_now = normalize_utc(now or datetime.now(timezone.utc))
    age_seconds = (ref_now - normalize_utc(captured_at)).total_seconds()
    return 0 <= age_seconds <= freshness_seconds or (-5 <= age_seconds < 0)


def compute_evidence_hash(summary: dict[str, Any]) -> str:
    """Tính mã băm SHA-256 cố định của bản tóm tắt bằng chứng để bảo đảm tính toàn vẹn."""
    canonical = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CollectedEvidenceItem:
    """Một đơn vị bằng chứng đã thu thập kèm đánh giá độ mới và tính nhất quán."""

    source_type: str
    source_ref: str
    captured_at: datetime
    actor_id: str
    resource_identifier: str
    content_hash: str
    verification_rule: str
    is_fresh: bool
    access_classification: str  # CUSTOMER_VISIBLE | INTERNAL_ONLY
    summary: dict[str, Any] = field(default_factory=dict)
    contradicted: bool = False
    error_reason: str | None = None


def _parse_external_id(external_id: str | None) -> tuple[str, int] | None:
    if not external_id or "#" not in external_id:
        return None
    repo_part, num_part = external_id.rsplit("#", 1)
    repo = repo_part.strip()
    try:
        num = int(num_part.strip())
    except ValueError:
        return None
    if not repo:
        return None
    return repo, num


async def collect_github_readback_evidence(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
    workflow_run_id: str | None,
    external_id_hint: str | None,
    connector: BaseConnector | None,
    freshness_seconds: int,
    expected_state: dict[str, Any] | None = None,
) -> CollectedEvidenceItem:
    """Đọc ngược lại GitHub Issue thực tế qua bộ kết nối để thu thập bằng chứng xác minh."""
    now = datetime.now(timezone.utc)
    parsed = _parse_external_id(external_id_hint)

    # Nếu chưa truyền sẵn external_id_hint, tự tra cứu từ nhật ký giao dịch bộ kết nối mới nhất
    if parsed is None:
        filters: list[sa.ColumnElement[bool]] = [
            ConnectorOperationRecord.organization_id == organization_id,
            ConnectorOperationRecord.external_number.is_not(None),
        ]
        if workflow_run_id:
            filters.append(ConnectorOperationRecord.workflow_run_id == workflow_run_id)
        else:
            filters.append(ConnectorOperationRecord.request_id == request_id)
        stmt = (
            sa.select(ConnectorOperationRecord)
            .where(*filters)
            .order_by(ConnectorOperationRecord.created_at.desc())
            .limit(1)
        )
        op_row = (await session.execute(stmt)).scalar_one_or_none()
        if op_row is not None and op_row.external_id:
            parsed = _parse_external_id(op_row.external_id)

    if parsed is None or connector is None:
        summary = {"reason": "Không có mã Issue ngoài hoặc bộ kết nối để đọc ngược."}
        return CollectedEvidenceItem(
            source_type="github_issue_readback",
            source_ref="unavailable",
            captured_at=now,
            actor_id="verifier",
            resource_identifier="unknown",
            content_hash=compute_evidence_hash(summary),
            verification_rule="read_back_issue_from_allowlisted_repo",
            is_fresh=False,
            access_classification=VisibilityLevel.INTERNAL_ONLY.value,
            summary=summary,
            contradicted=False,
            error_reason=summary["reason"],
        )

    repo, issue_num = parsed
    try:
        snapshot = await connector.get_resource(repository=repo, resource_number=issue_num)
    except ConnectorError as exc:
        summary = {"repository": repo, "external_number": issue_num, "error": exc.message}
        return CollectedEvidenceItem(
            source_type="github_issue_readback",
            source_ref=f"{repo}#{issue_num}",
            captured_at=now,
            actor_id="verifier",
            resource_identifier=f"github:repo:{repo}",
            content_hash=compute_evidence_hash(summary),
            verification_rule="read_back_issue_from_allowlisted_repo",
            is_fresh=False,
            access_classification=VisibilityLevel.INTERNAL_ONLY.value,
            summary=summary,
            contradicted=True,
            error_reason=exc.message,
        )

    # Đối chiếu sâu qua verify_result của bộ kết nối (phát hiện cả trường hợp mô phỏng sai lệch)
    verify_check = await connector.verify_result(
        "read_issue",
        dict(expected_state or {}),
        {"repository": repo, "external_number": issue_num},
    )
    captured_at = datetime.now(timezone.utc)
    safe_summary = {
        "external_id": snapshot.external_id,
        "external_number": snapshot.external_number,
        "external_url": snapshot.external_url,
        "title": snapshot.title,
        "state": snapshot.state,
        "labels": list(snapshot.labels),
        "assignees": list(snapshot.assignees),
        "comments_count": snapshot.comments_count,
        "verify_outcome": verify_check.outcome,
        "mismatched_fields": list(verify_check.mismatched_fields),
    }
    return CollectedEvidenceItem(
        source_type="github_issue_readback",
        source_ref=snapshot.external_url,
        captured_at=captured_at,
        actor_id="verifier",
        resource_identifier=snapshot.external_id,
        content_hash=compute_evidence_hash(safe_summary),
        verification_rule="read_back_issue_from_allowlisted_repo",
        is_fresh=is_evidence_fresh(captured_at, freshness_seconds=freshness_seconds),
        access_classification=VisibilityLevel.CUSTOMER_VISIBLE.value,
        summary=safe_summary,
        contradicted=(verify_check.outcome == "FAILED"),
        error_reason=verify_check.reason if not verify_check.matched else None,
    )


async def collect_approval_record_evidence(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
    workflow_run_id: str | None,
    freshness_seconds: int,
) -> CollectedEvidenceItem:
    """Thu thập bằng chứng về trạng thái phê duyệt ràng buộc 7 yếu tố liên quan tới lượt chạy."""
    now = datetime.now(timezone.utc)
    filters: list[sa.ColumnElement[bool]] = [
        ApprovalRequest.organization_id == organization_id,
        ApprovalRequest.request_id == request_id,
    ]
    if workflow_run_id:
        filters.append(ApprovalRequest.workflow_run_id == workflow_run_id)

    rows = list(
        (
            await session.execute(
                sa.select(ApprovalRequest)
                .where(*filters)
                .order_by(ApprovalRequest.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        summary = {"reason": "Không tìm thấy bản ghi phê duyệt nào gắn với yêu cầu."}
        return CollectedEvidenceItem(
            source_type="approval_record",
            source_ref="none",
            captured_at=now,
            actor_id="verifier",
            resource_identifier=request_id,
            content_hash=compute_evidence_hash(summary),
            verification_rule="approval_record_must_be_approved",
            is_fresh=False,
            access_classification=VisibilityLevel.INTERNAL_ONLY.value,
            summary=summary,
            error_reason=summary["reason"],
        )

    latest = rows[0]
    contradicted = latest.status in {"REJECTED", "EXPIRED"}
    summary = {
        "approval_id": latest.id,
        "status": latest.status,
        "required_role": latest.required_role,
        "risk_level": latest.risk_level,
        "parameter_hash": latest.parameter_hash,
        "resource_scope": latest.resource_scope,
    }
    return CollectedEvidenceItem(
        source_type="approval_record",
        source_ref=latest.id,
        captured_at=now,
        actor_id="verifier",
        resource_identifier=latest.resource_scope,
        content_hash=compute_evidence_hash(summary),
        verification_rule="approval_record_must_be_approved",
        is_fresh=is_evidence_fresh(now, freshness_seconds=freshness_seconds),
        access_classification=VisibilityLevel.INTERNAL_ONLY.value,
        summary=summary,
        contradicted=contradicted,
        error_reason=f"Lệnh phê duyệt đang ở trạng thái `{latest.status}`." if latest.status != "APPROVED" else None,
    )


async def collect_human_task_evidence(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
    workflow_run_id: str | None,
    freshness_seconds: int,
) -> CollectedEvidenceItem:
    """Thu thập bằng chứng hoàn thành các đầu việc nhân sự được giao."""
    now = datetime.now(timezone.utc)
    filters: list[sa.ColumnElement[bool]] = [
        HumanTask.organization_id == organization_id,
        HumanTask.request_id == request_id,
    ]
    if workflow_run_id:
        filters.append(HumanTask.workflow_run_id == workflow_run_id)

    tasks = list((await session.execute(sa.select(HumanTask).where(*filters))).scalars().all())
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == HumanTaskStatus.COMPLETED.value)
    blocked = sum(1 for t in tasks if t.status == HumanTaskStatus.BLOCKED.value)
    summary = {
        "total_tasks": total,
        "completed_tasks": completed,
        "blocked_tasks": blocked,
        "all_completed": total > 0 and completed == total,
    }
    return CollectedEvidenceItem(
        source_type="human_task_record",
        source_ref=request_id,
        captured_at=now,
        actor_id="verifier",
        resource_identifier=request_id,
        content_hash=compute_evidence_hash(summary),
        verification_rule="all_human_tasks_completed",
        is_fresh=total > 0 and is_evidence_fresh(now, freshness_seconds=freshness_seconds),
        access_classification=VisibilityLevel.INTERNAL_ONLY.value,
        summary=summary,
        contradicted=blocked > 0,
        error_reason="Có đầu việc nhân sự bị vướng mắc (BLOCKED)." if blocked > 0 else None,
    )
