"""Cổng kết nối an toàn từ máy chủ API tới Temporal kèm chế độ dự phòng khi phát triển cục bộ."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from temporalio.client import Client

from app.core.config import Settings, get_settings

from .contracts import (
    ApprovalSignalPayload,
    ExternalEventSignalPayload,
    HumanTaskSignalPayload,
    WorkflowRunInput,
)


@dataclass(slots=True)
class RecordedSignalEvent:
    """Bản ghi tín hiệu cục bộ dùng khi máy chủ Temporal chưa khởi chạy trong môi trường phát triển."""

    temporal_workflow_id: str
    signal_name: str
    payload: Any


@dataclass
class TemporalRuntimeGateway:
    """Bộ kết nối thống nhất để khởi phát quy trình và gửi tín hiệu điều khiển tới Temporal."""

    settings: Settings = field(default_factory=get_settings)
    client: Client | None = None
    _local_mode: bool = False
    _recorded_starts: list[WorkflowRunInput] = field(default_factory=list)
    _recorded_signals: list[RecordedSignalEvent] = field(default_factory=list)

    async def _ensure_client(self) -> Client | None:
        if self.client is not None:
            return self.client
        if not self.settings.temporal_address.strip():
            if self.settings.demo_mode:
                self._local_mode = True
                return None
            raise RuntimeError("Chưa cấu hình TEMPORAL_ADDRESS.")
        try:
            self.client = await Client.connect(
                self.settings.temporal_address,
                namespace=self.settings.temporal_namespace,
            )
            self._local_mode = False
            return self.client
        except Exception:
            if self.settings.demo_mode:
                self._local_mode = True
                return None
            raise

    async def check_health(self) -> str:
        """Kiểm tra trạng thái kết nối tới máy chủ Temporal mà không ném ngoại lệ."""
        if self.client is not None:
            return "up"
        if not self.settings.temporal_address.strip():
            return "disconnected"
        try:
            self.client = await Client.connect(
                self.settings.temporal_address,
                namespace=self.settings.temporal_namespace,
            )
            return "up"
        except Exception:
            return "disconnected"

    async def start_workflow(self, inp: WorkflowRunInput) -> str | None:
        """Khởi phát thực thi `RequestOrchestrationWorkflow` và trả về `temporal_run_id` nếu có."""
        temporal_wf_id = f"wf-run-{inp.workflow_run_id}"
        client = await self._ensure_client()
        if client is None:
            self._recorded_starts.append(inp)
            return f"local-sim-{inp.workflow_run_id}"

        handle = await client.start_workflow(
            "RequestOrchestrationWorkflow",
            inp,
            id=temporal_wf_id,
            task_queue=self.settings.temporal_task_queue,
        )
        return handle.first_execution_run_id

    async def _send_signal(self, temporal_workflow_id: str, signal_name: str, arg: Any) -> None:
        client = await self._ensure_client()
        if client is None:
            self._recorded_signals.append(
                RecordedSignalEvent(
                    temporal_workflow_id=temporal_workflow_id,
                    signal_name=signal_name,
                    payload=arg,
                )
            )
            return
        handle = client.get_workflow_handle(temporal_workflow_id)
        await handle.signal(signal_name, arg)

    async def signal_pause(self, temporal_workflow_id: str, reason: str = "") -> None:
        """Gửi tín hiệu tạm dừng tới quy trình đang chạy trên Temporal."""
        await self._send_signal(temporal_workflow_id, "pause_run", reason)

    async def signal_resume(self, temporal_workflow_id: str, reason: str = "") -> None:
        """Gửi tín hiệu tiếp tục tới quy trình đang tạm dừng."""
        await self._send_signal(temporal_workflow_id, "resume_run", reason)

    async def signal_cancel(self, temporal_workflow_id: str, reason: str = "") -> None:
        """Gửi tín hiệu hủy bỏ tới quy trình trên Temporal."""
        await self._send_signal(temporal_workflow_id, "cancel_run", reason)

    async def signal_approval(
        self,
        temporal_workflow_id: str,
        payload: ApprovalSignalPayload,
    ) -> None:
        """Gửi quyết định phê duyệt/từ chối để đánh thức bước `APPROVAL` đang chờ."""
        await self._send_signal(temporal_workflow_id, "submit_approval_decision", payload)

    async def signal_external_event(
        self,
        temporal_workflow_id: str,
        payload: ExternalEventSignalPayload,
    ) -> None:
        """Gửi sự kiện ngoài vào bước `WAIT_EVENT` đang chờ."""
        await self._send_signal(temporal_workflow_id, "receive_external_event", payload)

    async def signal_human_task(
        self,
        temporal_workflow_id: str,
        payload: HumanTaskSignalPayload,
    ) -> None:
        """Gửi kết quả hoàn thành đầu việc nhân sự vào bước `HUMAN_TASK` đang chờ."""
        await self._send_signal(temporal_workflow_id, "complete_human_task", payload)
