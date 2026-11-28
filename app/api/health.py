"""Các tuyến kiểm tra tiến trình sống (`/health/live`) và sẵn sàng kết nối (`/health/ready`)."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import check_database_health
from app.modules.runtime.temporal_client import TemporalRuntimeGateway

router = APIRouter(tags=["Sức khỏe hệ thống"])


@router.get("/health/live", summary="Kiểm tra tiến trình API đang sống")
async def health_live() -> dict[str, str]:
    """Xác nhận tiến trình máy chủ web đang chạy và phản hồi được."""
    return {"status": "ok"}


@router.get("/health/ready", summary="Kiểm tra sẵn sàng kết nối hạ tầng")
async def health_ready(request: Request) -> JSONResponse:
    """Kiểm tra kết nối thực tế tới cơ sở dữ liệu và máy chủ điều phối Temporal."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    db_ok = await check_database_health(factory)
    gateway: TemporalRuntimeGateway = request.app.state.runtime_gateway
    temporal_status = await gateway.check_health()
    http_status = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ready" if db_ok else "degraded",
            "checks": {
                "database": "up" if db_ok else "down",
                "temporal": temporal_status,
            },
        },
    )
