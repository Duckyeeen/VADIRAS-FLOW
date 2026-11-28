"""Bộ quét đồng bộ dự phòng định kỳ hoặc kích hoạt tay khi mất kết nối Webhook cục bộ."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.runtime.contracts import ExternalEventSignalPayload
from app.modules.runtime.temporal_client import TemporalRuntimeGateway
from app.modules.workflows.models import WorkflowRun

from . import repository
from .models import ConnectorOperationRecord, OperationRecordStatus
from .providers.base import BaseConnector, ConnectorError
from .schemas import ReconcileReportOut


class GitHubReconciler:
    """Đối chiếu lại trạng thái thực tế của các Issue trên GitHub để bù các sự kiện webhook bị trễ hoặc thất lạc."""

    async def reconcile_organization(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        connector: BaseConnector,
        default_allowed_repos: list[str],
        runtime_gateway: TemporalRuntimeGateway | None = None,
    ) -> ReconcileReportOut:
        """Quét lại toàn bộ các bản cài đặt đang bật và các giao dịch đang theo dõi của một tổ chức."""
        now = datetime.now(timezone.utc)
        installations = await repository.list_installations(session, organization_id=organization_id)
        active_installations = [inst for inst in installations if inst.status == "ACTIVE"]

        # Xác định tập các kho hợp lệ để quét danh sách Issue gần nhất
        repos_to_scan: set[str] = set()
        for inst in active_installations:
            for scope in inst.resource_scopes:
                if scope.is_active:
                    repos_to_scan.add(scope.resource_identifier)
        if not repos_to_scan:
            repos_to_scan.update(default_allowed_repos)

        details: list[dict[str, Any]] = []
        issues_seen = 0
        for repo in sorted(repos_to_scan):
            try:
                listed = await connector.list_issues(repository=repo, since=None)
                issues_seen += len(listed)
                details.append({"repository": repo, "issues_fetched": len(listed), "status": "ok"})
            except ConnectorError as exc:
                details.append({"repository": repo, "issues_fetched": 0, "status": "error", "error": exc.message})

        # Đọc ngược lại từng giao dịch đã tạo/cập nhật phiếu ngoài của tổ chức
        op_stmt = (
            sa.select(ConnectorOperationRecord)
            .where(
                ConnectorOperationRecord.organization_id == organization_id,
                ConnectorOperationRecord.external_number.is_not(None),
                ConnectorOperationRecord.status.in_(
                    [
                        OperationRecordStatus.SUCCEEDED.value,
                        OperationRecordStatus.RECONCILED.value,
                    ]
                ),
            )
            .order_by(ConnectorOperationRecord.created_at.desc())
        )
        ops = list((await session.execute(op_stmt)).scalars().all())
        checked_operations = 0
        updated_operations = 0

        for op in ops:
            repo_name = op.resource_scope.replace("github:repo:", "", 1).strip()
            if not repo_name or op.external_number is None:
                continue
            checked_operations += 1
            try:
                snap = await connector.get_resource(repository=repo_name, resource_number=op.external_number)
            except ConnectorError:
                continue

            old_summary = dict(op.response_summary_json or {})
            if old_summary.get("state") != snap.state or old_summary.get("labels") != snap.labels:
                updated_operations += 1
                op.status = OperationRecordStatus.RECONCILED.value
                op.response_summary_json = {
                    **old_summary,
                    "state": snap.state,
                    "title": snap.title,
                    "labels": list(snap.labels),
                    "assignees": list(snap.assignees),
                    "comments_count": snap.comments_count,
                    "reconciled_at": now.isoformat(),
                }
                if op.workflow_run_id and runtime_gateway is not None:
                    run_row = (
                        await session.execute(
                            sa.select(WorkflowRun).where(
                                WorkflowRun.id == op.workflow_run_id,
                                WorkflowRun.organization_id == organization_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if run_row is not None:
                        await runtime_gateway.signal_external_event(
                            run_row.temporal_workflow_id,
                            ExternalEventSignalPayload(
                                node_id=op.node_id or "wait_event",
                                event_source="github_reconciler",
                                event_type="issues.reconciled",
                                payload=dict(op.response_summary_json),
                            ),
                        )

        for inst in active_installations:
            inst.last_synced_at = now
            inst.sync_cursor = f"reconcile:{now.isoformat()}"

        await session.commit()
        return ReconcileReportOut(
            organization_id=organization_id,
            scanned_installations=len(active_installations),
            checked_operations=checked_operations,
            updated_operations=updated_operations,
            issues_seen=issues_seen,
            synced_at=now,
            details=details,
        )
