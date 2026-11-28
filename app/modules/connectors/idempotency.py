"""Lớp điều phối chống trùng lặp giao dịch ra hệ thống ngoài dựa trên `connector_operation_records`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ConnectorOperationRecord, OperationRecordStatus
from .providers.base import (
    BaseConnector,
    ConnectorActionResult,
    ConnectorError,
    ConnectorExecutionContext,
)


def _compute_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotentExecutionOutcome:
    """Kết quả thực thi thao tác ngoài kèm cờ cho biết có dùng lại kết quả cũ hay không."""

    result: ConnectorActionResult
    operation_record_id: str
    replayed: bool


class ConnectorOperationExecutor:
    """Bảo đảm thử lại thao tác hoặc gọi lặp không bao giờ tạo ra 2 phiếu trùng trên hệ thống ngoài."""

    def __init__(self, connector: BaseConnector) -> None:
        self._connector = connector

    async def execute_with_idempotency(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        action: str,
        repository: str,
        payload: dict[str, Any],
        idempotency_key: str,
        request_id: str | None = None,
        workflow_run_id: str | None = None,
        node_id: str | None = None,
        connector_installation_id: str | None = None,
        actor_id: str = "system",
    ) -> IdempotentExecutionOutcome:
        """Kiểm tra bảng `connector_operation_records` trước khi gửi lệnh mới ra hệ thống ngoài.

        Quy trình 4 bước:
        1. Nếu đã tồn tại bản ghi trùng `idempotency_key` ở trạng thái `SUCCEEDED`/`RECONCILED`
           -> trả ngay kết quả đã lưu (`replayed=True`), tuyệt đối không gọi lại GitHub.
        2. Nếu bản ghi từng ghi nhận dở dang (`PENDING`) và đã có `external_number`
           -> đọc ngược tài nguyên để xác minh xem thao tác trước đó đã thành công thực tế chưa.
        3. Lưu bản ghi trạng thái `PENDING` (hoặc tăng `attempt_count` nếu thử lại từ `FAILED`).
        4. Gọi `connector.execute_action`, cập nhật `SUCCEEDED` kèm mã ngoại vi hoặc `FAILED` nếu lỗi.
        """
        normalized_action = action.strip().lower()
        repo = repository.strip()
        scope = f"github:repo:{repo}"
        payload_hash = _compute_payload_hash({"action": normalized_action, "repo": repo, "payload": payload})

        existing = (
            await session.execute(
                sa.select(ConnectorOperationRecord)
                .execution_options(populate_existing=True)
                .where(
                    ConnectorOperationRecord.organization_id == organization_id,
                    ConnectorOperationRecord.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

        if existing is not None and existing.status in {
            OperationRecordStatus.SUCCEEDED.value,
            OperationRecordStatus.RECONCILED.value,
        }:
            cached_summary = dict(existing.response_summary_json or {})
            return IdempotentExecutionOutcome(
                result=ConnectorActionResult(
                    connector_type=existing.connector_type,
                    action=existing.action,
                    repository=repo,
                    external_id=existing.external_id or "",
                    external_number=existing.external_number,
                    external_url=existing.external_url or "",
                    status=existing.status,
                    raw_summary=cached_summary,
                ),
                operation_record_id=existing.id,
                replayed=True,
            )

        if (
            existing is not None
            and existing.status == OperationRecordStatus.PENDING.value
            and existing.external_number is not None
        ):
            try:
                snap = await self._connector.get_resource(
                    repository=repo, resource_number=existing.external_number
                )
                existing.status = OperationRecordStatus.RECONCILED.value
                existing.external_id = snap.external_id
                existing.external_url = snap.external_url
                existing.response_summary_json = {
                    "external_id": snap.external_id,
                    "external_number": snap.external_number,
                    "external_url": snap.external_url,
                    "title": snap.title,
                    "state": snap.state,
                    "labels": list(snap.labels),
                }
                existing.executed_at = datetime.now(timezone.utc)
                await session.commit()
                return IdempotentExecutionOutcome(
                    result=ConnectorActionResult(
                        connector_type=existing.connector_type,
                        action=existing.action,
                        repository=repo,
                        external_id=snap.external_id,
                        external_number=snap.external_number,
                        external_url=snap.external_url,
                        status=existing.status,
                        raw_summary=dict(existing.response_summary_json),
                    ),
                    operation_record_id=existing.id,
                    replayed=True,
                )
            except ConnectorError:
                pass

        if existing is None:
            record = ConnectorOperationRecord(
                organization_id=organization_id,
                connector_installation_id=connector_installation_id,
                request_id=request_id,
                workflow_run_id=workflow_run_id,
                node_id=node_id,
                connector_type=self._connector.connector_type,
                action=normalized_action,
                resource_scope=scope,
                idempotency_key=idempotency_key,
                request_payload_hash=payload_hash,
                status=OperationRecordStatus.PENDING.value,
                attempt_count=1,
            )
            session.add(record)
        else:
            record = existing
            record.status = OperationRecordStatus.PENDING.value
            record.attempt_count += 1
            record.error_class = None
            record.error_message = None

        await session.commit()

        exec_ctx = ConnectorExecutionContext(
            organization_id=organization_id,
            repository=repo,
            idempotency_key=idempotency_key,
            request_id=request_id,
            workflow_run_id=workflow_run_id,
            node_id=node_id,
            actor_id=actor_id,
        )
        try:
            action_result = await self._connector.execute_action(
                normalized_action,
                payload,
                exec_ctx,
            )
        except ConnectorError as exc:
            record.status = OperationRecordStatus.FAILED.value
            record.error_class = "TRANSIENT" if exc.retryable else "PERMANENT"
            record.error_message = exc.message
            await session.commit()
            raise

        record.status = OperationRecordStatus.SUCCEEDED.value
        record.external_id = action_result.external_id
        record.external_number = action_result.external_number
        record.external_url = action_result.external_url
        record.response_summary_json = dict(action_result.raw_summary)
        record.executed_at = datetime.now(timezone.utc)
        await session.commit()

        return IdempotentExecutionOutcome(
            result=action_result,
            operation_record_id=record.id,
            replayed=False,
        )
