"""Điểm tập hợp và đăng ký toàn bộ bộ định tuyến `/api/v1` của 10 phân hệ nghiệp vụ."""

from __future__ import annotations

from fastapi import FastAPI

from app.modules.ai_intelligence.router import router as ai_router
from app.modules.connectors.router import router as connectors_router
from app.modules.governance.router import router as governance_router
from app.modules.identity.router import router as identity_router
from app.modules.memory.router import router as memory_router
from app.modules.observability.router import router as observability_router
from app.modules.requests.router import router as requests_router
from app.modules.runtime.router import router as runtime_router
from app.modules.verification.router import router as verification_router
from app.modules.workflows.router import router as workflows_router


def register_v1_routers(application: FastAPI) -> None:
    """Gắn toàn bộ bộ định tuyến `/api/v1` của các phân hệ nghiệp vụ vào ứng dụng FastAPI."""
    for module_router in (
        identity_router,
        requests_router,
        ai_router,
        workflows_router,
        governance_router,
        runtime_router,
        connectors_router,
        verification_router,
        memory_router,
        observability_router,
    ):
        application.include_router(module_router)
