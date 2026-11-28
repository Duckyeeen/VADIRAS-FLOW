"""Điểm khởi chạy chính của máy chủ API VADIRAS FLOW."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.health import router as health_router
from app.api.v1 import register_v1_routers
from app.core.config import Settings, get_settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import create_engine_and_session_factory
from app.modules.connectors.providers.factory import build_github_connector
from app.modules.runtime.temporal_client import TemporalRuntimeGateway


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    """Khởi tạo ứng dụng FastAPI hoàn chỉnh kèm middleware, bộ xử lý lỗi và các tuyến API.

    Đầu vào:
    - `settings`: cho phép truyền cấu hình tùy chỉnh (hữu ích khi chạy kiểm thử).
    - `session_factory`: cho phép truyền bộ tạo phiên CSDL thay thế khi chạy kiểm thử.
    Đầu ra: đối tượng `FastAPI` sẵn sàng phục vụ yêu cầu HTTP.
    """
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Khởi tạo động cơ kết nối CSDL nếu chưa được truyền sẵn từ bên ngoài (như trong kiểm thử)
        owned_engine = None
        if getattr(application.state, "session_factory", None) is None:
            owned_engine, created_factory = create_engine_and_session_factory(
                active_settings.database_url,
                echo=active_settings.database_echo,
            )
            application.state.session_factory = created_factory
        try:
            yield
        finally:
            if owned_engine is not None:
                await owned_engine.dispose()

    application = FastAPI(
        title=active_settings.app_name,
        version="0.2.0",
        description="Nền tảng điều phối quy trình doanh nghiệp có sự hỗ trợ của AI.",
        lifespan=lifespan,
    )
    application.state.settings = active_settings
    if session_factory is not None:
        application.state.session_factory = session_factory
    if getattr(application.state, "runtime_gateway", None) is None:
        application.state.runtime_gateway = TemporalRuntimeGateway(settings=active_settings)
    if getattr(application.state, "github_connector", None) is None:
        application.state.github_connector = build_github_connector(active_settings)

    # Bộ đón đầu gắn mã theo dõi X-Correlation-ID cho mọi yêu cầu
    application.add_middleware(CorrelationIdMiddleware)

    # Chỉ cho phép các địa chỉ giao diện web được liệt kê rõ ràng trong cấu hình
    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.get_cors_origins_list(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID", "Idempotency-Key"],
    )

    register_exception_handlers(application)
    application.include_router(health_router)
    register_v1_routers(application)
    return application


app = create_app()
