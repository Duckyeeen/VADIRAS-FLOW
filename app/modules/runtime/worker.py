"""Tiến trình Temporal Worker độc lập chuyên lắng nghe hàng đợi và thực thi quy trình."""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine_and_session_factory

from .activities import RuntimeActivities
from .workflows import RequestOrchestrationWorkflow

logger = logging.getLogger(__name__)


async def _connect_temporal_with_retry(
    address: str,
    namespace: str,
    *,
    max_attempts: int = 20,
    delay_seconds: float = 3.0,
) -> Client:
    """Kết nối máy chủ Temporal với cơ chế thử lại giới hạn khi Temporal đang khởi tạo schema."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            client = await Client.connect(address, namespace=namespace)
            logger.info(
                "Kết nối máy chủ Temporal thành công (%s, namespace=%s, lần=%s)",
                address,
                namespace,
                attempt,
            )
            return client
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= max_attempts:
                logger.error(
                    "Không thể kết nối máy chủ Temporal sau %s lần (%s, namespace=%s): %s",
                    max_attempts,
                    address,
                    namespace,
                    exc,
                )
                raise
            logger.warning(
                "Đang chờ máy chủ Temporal sẵn sàng (%s, namespace=%s, lần=%s/%s, thử lại sau %.1fs): %s",
                address,
                namespace,
                attempt,
                max_attempts,
                delay_seconds,
                exc,
            )
            await asyncio.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


async def run_worker() -> None:
    """Kết nối máy chủ Temporal, đăng ký quy trình cùng các tác vụ và chạy liên tục."""
    settings = get_settings()
    configure_logging(settings.log_level)
    engine, session_factory = create_engine_and_session_factory(
        settings.database_url,
        echo=settings.database_echo,
    )
    activities = RuntimeActivities(session_factory=session_factory)
    client = await _connect_temporal_with_retry(
        settings.temporal_address,
        settings.temporal_namespace,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[RequestOrchestrationWorkflow],
        activities=[
            activities.update_run_status_activity,
            activities.persist_node_state_activity,
            activities.execute_node_activity,
        ],
    )
    try:
        await worker.run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker())
