"""Tầng xử lý nghiệp vụ cho tiếp nhận yêu cầu, tách dữ liệu khách hàng và quản lý tác vụ con người."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, ConflictError, NotFoundError
from app.modules.identity.models import UserKind
from app.modules.identity.schemas import PaginationMeta
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission

from . import intake, repository
from .models import (
    HumanTask,
    HumanTaskStatus,
    MessageKind,
    Request,
    RequestMessage,
    RequestStatus,
    VisibilityLevel,
)
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


def _is_customer(actor: AuthenticatedActor) -> bool:
    """Kiểm tra người đang gọi API có phải là tài khoản liên hệ khách hàng hay không."""
    return actor.user_kind == UserKind.CUSTOMER_CONTACT.value


def _ensure_request_accessible(actor: AuthenticatedActor, req: Request) -> None:
    """Kiểm tra quyền xem chi tiết một yêu cầu cụ thể theo tổ chức và vai trò.

    Quy tắc cô lập dữ liệu:
    1. Phải trùng tổ chức (`organization_id`).
    2. Nếu là khách hàng (`CUSTOMER_CONTACT`): chỉ được phép xem yêu cầu do chính mình gửi
       hoặc thuộc cùng mã tài khoản khách hàng (`customer_account_ref`).
    3. Nếu là nhân viên nhưng không có quyền `requests:read_all`: chỉ xem được yêu cầu mình tạo.
    """
    if req.organization_id != actor.organization_id:
        raise NotFoundError("Không tìm thấy yêu cầu trong tổ chức của bạn.", code="REQUEST_NOT_FOUND")

    if _is_customer(actor):
        same_requester = req.requester_membership_id == actor.membership_id
        same_account = (
            actor.customer_account_ref is not None
            and req.customer_account_ref == actor.customer_account_ref
        )
        if not (same_requester or same_account):
            raise AuthorizationError(
                "Khách hàng không được phép xem yêu cầu của khách hàng khác hoặc yêu cầu nội bộ.",
                code="CUSTOMER_ISOLATION_DENIED",
            )
        return

    if "requests:read_all" not in actor.permissions:
        require_permission(actor, "requests:read_own")
        if req.requester_membership_id != actor.membership_id:
            raise AuthorizationError(
                "Bạn chỉ được phép xem các yêu cầu do chính mình tạo.",
                code="REQUEST_ACCESS_DENIED",
            )


def _to_message_out(message: RequestMessage) -> RequestMessageOut:
    """Chuyển bản ghi tin nhắn sang khuôn mẫu phản hồi API."""
    return RequestMessageOut(
        id=message.id,
        request_id=message.request_id,
        author_membership_id=message.author_membership_id,
        body=message.body,
        visibility=message.visibility,
        message_kind=message.message_kind,
        created_at=message.created_at,
    )


def _to_human_task_out(task: HumanTask) -> HumanTaskOut:
    """Chuyển bản ghi đầu việc con người sang khuôn mẫu phản hồi API."""
    return HumanTaskOut(
        id=task.id,
        organization_id=task.organization_id,
        request_id=task.request_id,
        workflow_run_id=task.workflow_run_id,
        department_id=task.department_id,
        assignee_membership_id=task.assignee_membership_id,
        title=task.title,
        instructions=task.instructions,
        status=task.status,
        visibility=task.visibility,
        due_at=task.due_at,
        completion_note=task.completion_note,
        evidence=dict(task.evidence_json or {}),
        blocked_reason=task.blocked_reason,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def serialize_request_for_actor(
    actor: AuthenticatedActor,
    req: Request,
    *,
    messages: list[RequestMessage] | None = None,
    tasks: list[HumanTask] | None = None,
) -> RequestCustomerOut | RequestInternalOut:
    """Chọn bộ chuyển đổi đầu ra an toàn tùy theo người xem là khách hàng hay nhân viên.

    Nếu người gọi là `CUSTOMER_CONTACT`, hàm lọc bỏ hoàn toàn tin nhắn `INTERNAL_ONLY`
    và trả về `RequestCustomerOut` (không chứa dữ liệu nội bộ).
    """
    source_messages = messages if messages is not None else list(req.messages)
    if _is_customer(actor):
        visible_messages = [
            _to_message_out(msg)
            for msg in source_messages
            if msg.visibility == VisibilityLevel.CUSTOMER_VISIBLE.value
        ]
        return RequestCustomerOut(
            id=req.id,
            organization_id=req.organization_id,
            request_number=req.request_number,
            title=req.title,
            description=req.description,
            request_type=req.request_type,
            status=req.status,
            business_outcome=req.business_outcome,
            priority=req.priority,
            due_at=req.due_at,
            created_at=req.created_at,
            updated_at=req.updated_at,
            messages=visible_messages,
        )

    source_tasks = tasks if tasks is not None else list(req.human_tasks)
    return RequestInternalOut(
        id=req.id,
        organization_id=req.organization_id,
        request_number=req.request_number,
        title=req.title,
        description=req.description,
        sanitized_description=req.sanitized_description,
        pii_redactions=list(req.pii_redactions_json or []),
        injection_flags=list(req.injection_flags_json or []),
        request_type=req.request_type,
        source=req.source,
        status=req.status,
        business_outcome=req.business_outcome,
        priority=req.priority,
        impact=req.impact,
        urgency=req.urgency,
        requester_membership_id=req.requester_membership_id,
        requester_kind=req.requester_kind,
        customer_account_ref=req.customer_account_ref,
        department_id=req.department_id,
        proposed_departments=list(req.proposed_departments_json or []),
        due_at=req.due_at,
        content_hash=req.content_hash,
        metadata=dict(req.metadata_json or {}),
        created_at=req.created_at,
        updated_at=req.updated_at,
        messages=[_to_message_out(msg) for msg in source_messages],
        human_tasks=[_to_human_task_out(task) for task in source_tasks],
    )


async def create_request(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    payload: CreateRequestIn,
    idempotency_key: str | None = None,
) -> tuple[RequestCustomerOut | RequestInternalOut, bool]:
    """Tiếp nhận, chuẩn hóa và lưu yêu cầu mới kèm cơ chế chống tạo trùng lặp.

    Các bước xử lý:
    1. Kiểm tra quyền `requests:create`.
    2. Nếu có `idempotency_key`, kiểm tra trong cùng tổ chức đã tồn tại yêu cầu này chưa;
       nếu đã có và người gọi có quyền xem thì trả lại bản ghi cũ (`created=False`).
    3. Ẩn thông tin cá nhân nhạy cảm (email, SĐT, thẻ, khóa) vào `sanitized_description` và
       quét dấu hiệu cài cắm lệnh trên tiêu đề + mô tả.
    4. Xác định phòng ban tiếp nhận mặc định (hoặc theo mã phòng ban được chỉ định).
    5. Lưu bản ghi `Request`, ghi nhận người gửi vào `request_participants`.
    """
    require_permission(actor, "requests:create")
    cleaned_key = idempotency_key.strip()[:128] if idempotency_key and idempotency_key.strip() else None

    if cleaned_key:
        existing = await repository.get_request_by_idempotency_key(
            session,
            organization_id=actor.organization_id,
            idempotency_key=cleaned_key,
        )
        if existing is not None:
            _ensure_request_accessible(actor, existing)
            return serialize_request_for_actor(actor, existing), False

    normalized_type = payload.request_type.strip().upper()
    sanitized_desc, pii_redactions = intake.redact_pii(payload.description)
    injection_flags = intake.detect_prompt_injection_signals(f"{payload.title}\n{payload.description}")
    content_hash = intake.compute_content_hash(
        organization_id=actor.organization_id,
        requester_membership_id=actor.membership_id,
        request_type=normalized_type,
        title=payload.title,
        description=payload.description,
    )

    suggested_dept_code = payload.department_code or intake.suggest_default_department_code(normalized_type)
    department = await repository.get_department_by_code(
        session,
        organization_id=actor.organization_id,
        code=suggested_dept_code,
    )
    if payload.department_code and department is None:
        raise NotFoundError(
            f"Không tìm thấy phòng ban `{payload.department_code}` trong tổ chức.",
            code="DEPARTMENT_NOT_FOUND",
        )

    request_number = await repository.generate_next_request_number(
        session,
        organization_id=actor.organization_id,
    )
    req = Request(
        organization_id=actor.organization_id,
        request_number=request_number,
        title=payload.title,
        description=payload.description,
        sanitized_description=sanitized_desc,
        pii_redactions_json=pii_redactions,
        injection_flags_json=injection_flags,
        request_type=normalized_type,
        source=payload.source.value,
        status=RequestStatus.OPEN.value,
        priority=payload.priority.value,
        impact=payload.impact.value,
        urgency=payload.urgency.value,
        requester_membership_id=actor.membership_id,
        requester_kind=actor.user_kind,
        customer_account_ref=actor.customer_account_ref,
        department_id=department.id if department is not None else None,
        proposed_departments_json=[department.code] if department is not None else [],
        due_at=payload.due_at,
        idempotency_key=cleaned_key,
        content_hash=content_hash,
        metadata_json=payload.metadata,
        created_by_user_id=actor.user_id,
        updated_by_user_id=actor.user_id,
    )
    session.add(req)
    await session.flush()

    await repository.add_participant_if_missing(
        session,
        organization_id=actor.organization_id,
        request_id=req.id,
        membership_id=actor.membership_id,
        participant_role="REQUESTER",
    )
    await session.commit()

    created_req = await repository.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=req.id,
    )
    assert created_req is not None
    return serialize_request_for_actor(actor, created_req), True


async def list_requests_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
    request_type: str | None = None,
    status: str | None = None,
    department_id: str | None = None,
    priority: str | None = None,
) -> RequestListResponse:
    """Lấy danh sách yêu cầu đã lọc chặt theo tổ chức và quyền xem của người gọi."""
    only_requester_id: str | None = None
    customer_ref: str | None = None

    if _is_customer(actor):
        require_permission(actor, "requests:read_own")
        only_requester_id = actor.membership_id
        customer_ref = actor.customer_account_ref
    elif "requests:read_all" not in actor.permissions:
        require_permission(actor, "requests:read_own")
        only_requester_id = actor.membership_id

    rows, total = await repository.list_requests(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
        only_requester_membership_id=only_requester_id,
        customer_account_ref=customer_ref,
        request_type=request_type,
        status=status,
        department_id=department_id,
        priority=priority,
    )
    return RequestListResponse(
        items=[serialize_request_for_actor(actor, row) for row in rows],
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )


async def get_request_detail_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
) -> RequestCustomerOut | RequestInternalOut:
    """Xem chi tiết một yêu cầu (tự động lọc tin nhắn và trường nội bộ nếu là khách hàng)."""
    req = await repository.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu.", code="REQUEST_NOT_FOUND")
    _ensure_request_accessible(actor, req)
    return serialize_request_for_actor(actor, req)


async def update_request_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
    payload: UpdateRequestIn,
) -> RequestInternalOut:
    """Cập nhật thông tin điều phối yêu cầu (chỉ nhân viên có quyền `requests:update`)."""
    require_employee(actor)
    require_permission(actor, "requests:update")

    req = await repository.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu.", code="REQUEST_NOT_FOUND")

    if payload.title is not None:
        req.title = payload.title
    if payload.status is not None:
        req.status = payload.status.value
    if payload.priority is not None:
        req.priority = payload.priority.value
    if payload.impact is not None:
        req.impact = payload.impact.value
    if payload.urgency is not None:
        req.urgency = payload.urgency.value
    if payload.due_at is not None:
        req.due_at = payload.due_at
    if payload.department_code is not None:
        dept = await repository.get_department_by_code(
            session,
            organization_id=actor.organization_id,
            code=payload.department_code,
        )
        if dept is None:
            raise NotFoundError(
                f"Không tìm thấy phòng ban `{payload.department_code}` trong tổ chức.",
                code="DEPARTMENT_NOT_FOUND",
            )
        req.department_id = dept.id

    req.updated_by_user_id = actor.user_id
    await session.commit()

    refreshed = await repository.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=req.id,
    )
    assert refreshed is not None
    result = serialize_request_for_actor(actor, refreshed)
    assert isinstance(result, RequestInternalOut)
    return result


async def add_message_to_request(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
    payload: CreateMessageIn,
) -> RequestMessageOut:
    """Thêm tin nhắn trao đổi vào yêu cầu kèm kiểm soát phân tách hiển thị khách hàng/nội bộ."""
    req = await repository.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu.", code="REQUEST_NOT_FOUND")
    _ensure_request_accessible(actor, req)

    if _is_customer(actor) and payload.visibility != VisibilityLevel.CUSTOMER_VISIBLE:
        raise AuthorizationError(
            "Khách hàng không thể tạo ghi chú nội bộ.",
            code="CUSTOMER_CANNOT_POST_INTERNAL_NOTE",
        )

    msg = RequestMessage(
        organization_id=actor.organization_id,
        request_id=req.id,
        author_membership_id=actor.membership_id,
        body=payload.body,
        visibility=payload.visibility.value,
        message_kind=payload.message_kind.value,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return _to_message_out(msg)


async def submit_clarification_answer(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
    payload: ClarificationIn,
) -> RequestCustomerOut | RequestInternalOut:
    """Gửi câu trả lời làm rõ thông tin và chuyển yêu cầu từ `NEEDS_INFORMATION` về `OPEN`."""
    req = await repository.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu.", code="REQUEST_NOT_FOUND")
    _ensure_request_accessible(actor, req)

    visibility = (
        VisibilityLevel.CUSTOMER_VISIBLE.value
        if _is_customer(actor)
        else payload.visibility.value
    )
    msg = RequestMessage(
        organization_id=actor.organization_id,
        request_id=req.id,
        author_membership_id=actor.membership_id,
        body=payload.answer,
        visibility=visibility,
        message_kind=MessageKind.CLARIFICATION_ANSWER.value,
    )
    session.add(msg)

    if req.status == RequestStatus.NEEDS_INFORMATION.value:
        req.status = RequestStatus.OPEN.value
        req.updated_by_user_id = actor.user_id

    await session.commit()
    refreshed = await repository.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=req.id,
    )
    assert refreshed is not None
    return serialize_request_for_actor(actor, refreshed)


async def create_human_task_for_request(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
    payload: CreateHumanTaskIn,
) -> HumanTaskOut:
    """Tạo đầu việc giao cho nhân viên trong tổ chức (khách hàng không thể tạo hoặc xem)."""
    require_employee(actor)
    require_permission(actor, "tasks:manage")

    req = await repository.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu.", code="REQUEST_NOT_FOUND")

    department_id = req.department_id
    if payload.department_code is not None:
        dept = await repository.get_department_by_code(
            session,
            organization_id=actor.organization_id,
            code=payload.department_code,
        )
        if dept is None:
            raise NotFoundError(
                f"Không tìm thấy phòng ban `{payload.department_code}` trong tổ chức.",
                code="DEPARTMENT_NOT_FOUND",
            )
        department_id = dept.id

    if payload.assignee_membership_id is not None:
        assignee = await repository.get_membership_in_org(
            session,
            organization_id=actor.organization_id,
            membership_id=payload.assignee_membership_id,
        )
        if assignee is None or assignee.user_kind != UserKind.EMPLOYEE.value:
            raise NotFoundError(
                "Không tìm thấy nhân viên được giao việc trong tổ chức.",
                code="ASSIGNEE_NOT_FOUND",
            )

    task = HumanTask(
        organization_id=actor.organization_id,
        request_id=req.id,
        department_id=department_id,
        assignee_membership_id=payload.assignee_membership_id,
        title=payload.title,
        instructions=payload.instructions,
        status=HumanTaskStatus.OPEN.value,
        visibility=VisibilityLevel.INTERNAL_ONLY.value,
        due_at=payload.due_at,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return _to_human_task_out(task)


async def list_human_tasks_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
    status: str | None = None,
    department_id: str | None = None,
    request_id: str | None = None,
) -> HumanTaskListResponse:
    """Liệt kê các đầu việc con người thuộc phạm vi tổ chức của nhân viên gọi API."""
    require_employee(actor)
    require_permission(actor, "tasks:read")

    rows, total = await repository.list_human_tasks(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
        status=status,
        department_id=department_id,
        request_id=request_id,
    )
    return HumanTaskListResponse(
        items=[_to_human_task_out(row) for row in rows],
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )


async def get_human_task_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    task_id: str,
) -> HumanTaskOut:
    """Xem chi tiết một đầu việc con người (chỉ nhân viên nội bộ có quyền `tasks:read`)."""
    require_employee(actor)
    require_permission(actor, "tasks:read")

    task = await repository.get_human_task_by_id(
        session,
        organization_id=actor.organization_id,
        task_id=task_id,
    )
    if task is None:
        raise NotFoundError("Không tìm thấy đầu việc yêu cầu.", code="TASK_NOT_FOUND")
    return _to_human_task_out(task)


async def claim_human_task_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    task_id: str,
) -> HumanTaskOut:
    """Nhân viên nhận xử lý đầu việc đang mở hoặc đang gỡ vướng mắc."""
    require_employee(actor)
    require_permission(actor, "tasks:manage")

    task = await repository.get_human_task_by_id(
        session,
        organization_id=actor.organization_id,
        task_id=task_id,
    )
    if task is None:
        raise NotFoundError("Không tìm thấy đầu việc yêu cầu.", code="TASK_NOT_FOUND")
    if task.status not in {HumanTaskStatus.OPEN.value, HumanTaskStatus.BLOCKED.value}:
        raise ConflictError(
            f"Không thể nhận xử lý đầu việc đang ở trạng thái `{task.status}`.",
            code="INVALID_TASK_TRANSITION",
        )

    task.assignee_membership_id = actor.membership_id
    task.status = HumanTaskStatus.CLAIMED.value
    task.blocked_reason = None
    await session.commit()
    await session.refresh(task)
    return _to_human_task_out(task)


async def complete_human_task_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    task_id: str,
    payload: CompleteHumanTaskIn,
) -> HumanTaskOut:
    """Đánh dấu hoàn tất đầu việc kèm ghi chú kết quả và bằng chứng."""
    require_employee(actor)
    require_permission(actor, "tasks:manage")

    task = await repository.get_human_task_by_id(
        session,
        organization_id=actor.organization_id,
        task_id=task_id,
    )
    if task is None:
        raise NotFoundError("Không tìm thấy đầu việc yêu cầu.", code="TASK_NOT_FOUND")
    if task.status not in {HumanTaskStatus.OPEN.value, HumanTaskStatus.CLAIMED.value}:
        raise ConflictError(
            f"Không thể hoàn tất đầu việc đang ở trạng thái `{task.status}`.",
            code="INVALID_TASK_TRANSITION",
        )

    task.assignee_membership_id = task.assignee_membership_id or actor.membership_id
    task.status = HumanTaskStatus.COMPLETED.value
    task.completion_note = payload.completion_note
    task.evidence_json = payload.evidence
    task.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(task)
    return _to_human_task_out(task)


async def block_human_task_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    task_id: str,
    payload: BlockHumanTaskIn,
) -> HumanTaskOut:
    """Báo cáo vướng mắc khiến đầu việc tạm thời chưa thể tiếp tục."""
    require_employee(actor)
    require_permission(actor, "tasks:manage")

    task = await repository.get_human_task_by_id(
        session,
        organization_id=actor.organization_id,
        task_id=task_id,
    )
    if task is None:
        raise NotFoundError("Không tìm thấy đầu việc yêu cầu.", code="TASK_NOT_FOUND")
    if task.status in {HumanTaskStatus.COMPLETED.value, HumanTaskStatus.CANCELLED.value}:
        raise ConflictError(
            f"Không thể báo vướng mắc khi đầu việc đã `{task.status}`.",
            code="INVALID_TASK_TRANSITION",
        )

    task.status = HumanTaskStatus.BLOCKED.value
    task.blocked_reason = payload.blocked_reason
    await session.commit()
    await session.refresh(task)
    return _to_human_task_out(task)
