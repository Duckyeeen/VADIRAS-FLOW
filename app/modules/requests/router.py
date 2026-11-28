"""Các tuyến API cho tiếp nhận yêu cầu công việc, trao đổi làm rõ và tác vụ con người."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_actor
from app.modules.identity.service import AuthenticatedActor

from . import service
from .schemas import (
    BlockHumanTaskIn,
    ClarificationIn,
    CompleteHumanTaskIn,
    CreateHumanTaskIn,
    CreateMessageIn,
    CreateRequestIn,
    HumanTaskListResponse,
    HumanTaskOut,
    RequestCustomerOut,
    RequestInternalOut,
    RequestListResponse,
    RequestMessageOut,
    UpdateRequestIn,
)

router = APIRouter(prefix="/api/v1", tags=["Yêu cầu & Tác vụ"])


@router.post(
    "/requests",
    response_model=RequestInternalOut | RequestCustomerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo yêu cầu công việc mới",
)
async def create_request(
    payload: CreateRequestIn,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RequestInternalOut | RequestCustomerOut:
    """Tiếp nhận yêu cầu mới (hỗ trợ `Idempotency-Key` để chống bấm đúp tạo trùng)."""
    result, created = await service.create_request(
        session,
        actor=actor,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return result


@router.get("/requests", response_model=RequestListResponse, summary="Danh sách yêu cầu")
async def list_requests(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy (bắt đầu từ 1)."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    request_type: str | None = Query(default=None, description="Lọc theo loại yêu cầu."),
    status_filter: str | None = Query(default=None, alias="status", description="Lọc theo trạng thái."),
    department_id: str | None = Query(default=None, description="Lọc theo mã phòng ban."),
    priority: str | None = Query(default=None, description="Lọc theo mức ưu tiên."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RequestListResponse:
    """Trả danh sách yêu cầu đã lọc theo tổ chức và quyền xem (khách hàng chỉ thấy yêu cầu của mình)."""
    return await service.list_requests_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
        request_type=request_type,
        status=status_filter,
        department_id=department_id,
        priority=priority,
    )


@router.get(
    "/requests/{request_id}",
    response_model=RequestInternalOut | RequestCustomerOut,
    summary="Xem chi tiết yêu cầu",
)
async def get_request_detail(
    request_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RequestInternalOut | RequestCustomerOut:
    """Xem chi tiết một yêu cầu (tự động ẩn trường nội bộ và tin nhắn nội bộ nếu là khách hàng)."""
    return await service.get_request_detail_for_actor(
        session,
        actor=actor,
        request_id=request_id,
    )


@router.patch(
    "/requests/{request_id}",
    response_model=RequestInternalOut,
    summary="Cập nhật điều phối yêu cầu",
)
async def update_request(
    request_id: str,
    payload: UpdateRequestIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RequestInternalOut:
    """Cập nhật trạng thái, độ ưu tiên hoặc phòng ban phụ trách (chỉ dành cho nhân viên nội bộ)."""
    return await service.update_request_for_actor(
        session,
        actor=actor,
        request_id=request_id,
        payload=payload,
    )


@router.post(
    "/requests/{request_id}/messages",
    response_model=RequestMessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Gửi bình luận hoặc ghi chú lên yêu cầu",
)
async def add_message(
    request_id: str,
    payload: CreateMessageIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RequestMessageOut:
    """Thêm tin nhắn trao đổi; khách hàng chỉ được gửi tin nhắn hiển thị công khai với khách hàng."""
    return await service.add_message_to_request(
        session,
        actor=actor,
        request_id=request_id,
        payload=payload,
    )


@router.post(
    "/requests/{request_id}/clarifications",
    response_model=RequestInternalOut | RequestCustomerOut,
    summary="Bổ sung thông tin làm rõ cho yêu cầu",
)
async def submit_clarification(
    request_id: str,
    payload: ClarificationIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RequestInternalOut | RequestCustomerOut:
    """Gửi câu trả lời làm rõ thông tin và mở lại trạng thái xử lý nếu đang chờ bổ sung."""
    return await service.submit_clarification_answer(
        session,
        actor=actor,
        request_id=request_id,
        payload=payload,
    )


@router.post(
    "/requests/{request_id}/tasks",
    response_model=HumanTaskOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo đầu việc xử lý cho nhân viên",
)
async def create_human_task(
    request_id: str,
    payload: CreateHumanTaskIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> HumanTaskOut:
    """Tạo đầu việc nội bộ gắn vào một yêu cầu (chỉ nhân viên có quyền quản lý tác vụ)."""
    return await service.create_human_task_for_request(
        session,
        actor=actor,
        request_id=request_id,
        payload=payload,
    )


@router.get("/tasks", response_model=HumanTaskListResponse, summary="Danh sách đầu việc con người")
async def list_human_tasks(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy (bắt đầu từ 1)."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    status_filter: str | None = Query(default=None, alias="status", description="Lọc theo trạng thái đầu việc."),
    department_id: str | None = Query(default=None, description="Lọc theo mã phòng ban."),
    request_id: str | None = Query(default=None, description="Lọc theo mã yêu cầu."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> HumanTaskListResponse:
    """Lấy danh sách các đầu việc nội bộ thuộc tổ chức (khách hàng bị chặn truy cập)."""
    return await service.list_human_tasks_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
        status=status_filter,
        department_id=department_id,
        request_id=request_id,
    )


@router.get("/tasks/{task_id}", response_model=HumanTaskOut, summary="Xem chi tiết đầu việc")
async def get_human_task(
    task_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> HumanTaskOut:
    """Xem chi tiết một đầu việc con người trong tổ chức."""
    return await service.get_human_task_for_actor(session, actor=actor, task_id=task_id)


@router.post("/tasks/{task_id}/claim", response_model=HumanTaskOut, summary="Nhận xử lý đầu việc")
async def claim_human_task(
    task_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> HumanTaskOut:
    """Nhân viên nhận phụ trách một đầu việc đang mở hoặc vừa gỡ vướng mắc."""
    return await service.claim_human_task_for_actor(session, actor=actor, task_id=task_id)


@router.post("/tasks/{task_id}/complete", response_model=HumanTaskOut, summary="Hoàn tất đầu việc")
async def complete_human_task(
    task_id: str,
    payload: CompleteHumanTaskIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> HumanTaskOut:
    """Đánh dấu đầu việc đã hoàn tất kèm ghi chú kết quả và bằng chứng liên quan."""
    return await service.complete_human_task_for_actor(
        session,
        actor=actor,
        task_id=task_id,
        payload=payload,
    )


@router.post("/tasks/{task_id}/block", response_model=HumanTaskOut, summary="Báo vướng mắc đầu việc")
async def block_human_task(
    task_id: str,
    payload: BlockHumanTaskIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> HumanTaskOut:
    """Ghi nhận lý do vướng mắc khiến đầu việc tạm thời chưa thể hoàn thành."""
    return await service.block_human_task_for_actor(
        session,
        actor=actor,
        task_id=task_id,
        payload=payload,
    )
