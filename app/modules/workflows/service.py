"""Tầng xử lý nghiệp vụ kiểm định 7 tầng, chấm điểm và ban hành phiên bản quy trình bất biến."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.identity.schemas import PaginationMeta
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission

from . import repository
from .dsl.schemas import compute_graph_content_hash
from .models import WorkflowDefinition, WorkflowVersion, WorkflowVersionStatus
from .registry import default_node_registry
from .schemas import (
    CreateWorkflowIn,
    CreateWorkflowVersionIn,
    NodeRegistryResponse,
    PublishWorkflowIn,
    WorkflowDefinitionOut,
    WorkflowListResponse,
    WorkflowVersionOut,
)
from .scoring import score_candidate_workflows
from .validator import WorkflowValidationReport, validate_workflow_graph


def _to_version_out(version: WorkflowVersion) -> WorkflowVersionOut:
    """Chuyển bản ghi `WorkflowVersion` sang khuôn mẫu đầu ra API."""
    return WorkflowVersionOut(
        id=version.id,
        organization_id=version.organization_id,
        workflow_definition_id=version.workflow_definition_id,
        version_number=version.version_number,
        status=version.status,
        graph=dict(version.graph_json or {}),
        content_hash=version.content_hash,
        validation_report=dict(version.validation_report_json or {}),
        score_summary=dict(version.score_summary_json or {}),
        created_from_analysis_id=version.created_from_analysis_id,
        published_at=version.published_at,
        created_at=version.created_at,
    )


def _to_definition_out(definition: WorkflowDefinition) -> WorkflowDefinitionOut:
    """Chuyển bản ghi `WorkflowDefinition` kèm danh sách phiên bản sang đầu ra API."""
    return WorkflowDefinitionOut(
        id=definition.id,
        organization_id=definition.organization_id,
        code=definition.code,
        name=definition.name,
        description=definition.description,
        domain_pack=definition.domain_pack,
        request_type=definition.request_type,
        is_archived=definition.is_archived,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
        versions=[_to_version_out(v) for v in definition.versions],
    )


def get_node_registry_for_actor(actor: AuthenticatedActor) -> NodeRegistryResponse:
    """Xuất danh mục 12 loại bước chuẩn kèm cấu trúc nhập liệu cho nhân viên nội bộ."""
    require_employee(actor)
    return NodeRegistryResponse(node_types=default_node_registry.export_for_frontend())


def validate_graph_for_actor(
    actor: AuthenticatedActor,
    *,
    graph_data: dict,
) -> WorkflowValidationReport:
    """Chạy kiểm định 7 tầng trên sơ đồ JSON mà chưa lưu xuống cơ sở dữ liệu."""
    require_employee(actor)
    return validate_workflow_graph(graph_data)


async def create_workflow_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    payload: CreateWorkflowIn,
) -> WorkflowDefinitionOut:
    """Tạo định nghĩa quy trình mới kèm phiên bản đầu tiên v1 và chạy kiểm định 7 tầng."""
    require_employee(actor)
    require_permission(actor, "workflows:manage")

    existing = await repository.get_definition_by_code(
        session,
        organization_id=actor.organization_id,
        code=payload.code,
    )
    if existing is not None:
        raise ConflictError(
            f"Mã quy trình `{payload.code}` đã tồn tại trong tổ chức.",
            code="WORKFLOW_CODE_EXISTS",
        )

    report = validate_workflow_graph(payload.graph)
    scores = score_candidate_workflows([payload.graph])
    score_dict = scores[0].model_dump() if scores else {}
    version_status = WorkflowVersionStatus.VALID.value if report.valid else WorkflowVersionStatus.INVALID.value

    definition = WorkflowDefinition(
        organization_id=actor.organization_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        domain_pack=payload.domain_pack,
        request_type=payload.request_type.strip().upper(),
        created_by_user_id=actor.user_id,
        updated_by_user_id=actor.user_id,
    )
    session.add(definition)
    await session.flush()

    version = WorkflowVersion(
        organization_id=actor.organization_id,
        workflow_definition_id=definition.id,
        version_number=1,
        status=version_status,
        graph_json=payload.graph,
        content_hash=compute_graph_content_hash(payload.graph),
        validation_report_json=report.model_dump(),
        score_summary_json=score_dict,
        created_from_analysis_id=payload.created_from_analysis_id,
        created_by_user_id=actor.user_id,
    )
    session.add(version)
    await session.commit()

    refreshed = await repository.get_definition_by_id(
        session,
        organization_id=actor.organization_id,
        workflow_id=definition.id,
    )
    assert refreshed is not None
    return _to_definition_out(refreshed)


async def list_workflows_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
    request_type: str | None = None,
) -> WorkflowListResponse:
    """Liệt kê danh sách quy trình thuộc phạm vi tổ chức của nhân viên gọi API."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    rows, total = await repository.list_definitions(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
        request_type=request_type,
    )
    return WorkflowListResponse(
        items=[_to_definition_out(row) for row in rows],
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )


async def get_workflow_detail_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    workflow_id: str,
) -> WorkflowDefinitionOut:
    """Xem chi tiết một định nghĩa quy trình và các phiên bản thuộc tổ chức."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    definition = await repository.get_definition_by_id(
        session,
        organization_id=actor.organization_id,
        workflow_id=workflow_id,
    )
    if definition is None:
        raise NotFoundError("Không tìm thấy quy trình yêu cầu.", code="WORKFLOW_NOT_FOUND")
    return _to_definition_out(definition)


async def create_workflow_version_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    workflow_id: str,
    payload: CreateWorkflowVersionIn,
) -> WorkflowVersionOut:
    """Tạo một phiên bản mới (`version_number + 1`) cho quy trình mà không sửa đè các bản cũ."""
    require_employee(actor)
    require_permission(actor, "workflows:manage")

    definition = await repository.get_definition_by_id(
        session,
        organization_id=actor.organization_id,
        workflow_id=workflow_id,
    )
    if definition is None:
        raise NotFoundError("Không tìm thấy quy trình yêu cầu.", code="WORKFLOW_NOT_FOUND")

    latest = await repository.get_latest_version(
        session,
        organization_id=actor.organization_id,
        workflow_id=definition.id,
    )
    next_num = (latest.version_number if latest is not None else 0) + 1

    report = validate_workflow_graph(payload.graph)
    scores = score_candidate_workflows([payload.graph])
    score_dict = scores[0].model_dump() if scores else {}
    version_status = WorkflowVersionStatus.VALID.value if report.valid else WorkflowVersionStatus.INVALID.value

    version = WorkflowVersion(
        organization_id=actor.organization_id,
        workflow_definition_id=definition.id,
        version_number=next_num,
        status=version_status,
        graph_json=payload.graph,
        content_hash=compute_graph_content_hash(payload.graph),
        validation_report_json=report.model_dump(),
        score_summary_json=score_dict,
        created_from_analysis_id=payload.created_from_analysis_id,
        created_by_user_id=actor.user_id,
    )
    session.add(version)
    definition.updated_by_user_id = actor.user_id
    await session.commit()
    await session.refresh(version)
    return _to_version_out(version)


async def get_workflow_version_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    workflow_id: str,
    version_id: str,
) -> WorkflowVersionOut:
    """Xem chi tiết một phiên bản sơ đồ quy trình cụ thể."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    version = await repository.get_version_by_id(
        session,
        organization_id=actor.organization_id,
        workflow_id=workflow_id,
        version_id=version_id,
    )
    if version is None:
        raise NotFoundError("Không tìm thấy phiên bản quy trình yêu cầu.", code="WORKFLOW_VERSION_NOT_FOUND")
    return _to_version_out(version)


async def publish_workflow_version_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    workflow_id: str,
    payload: PublishWorkflowIn,
) -> WorkflowVersionOut:
    """Ban hành chính thức một phiên bản quy trình và khóa bất biến sơ đồ + mã băm.

    Quy tắc an toàn:
    1. Nếu phiên bản đã `PUBLISHED` -> trả `409 IMMUTABLE_WORKFLOW_VERSION` (cấm sửa hoặc ban hành đè).
    2. Chạy lại toàn bộ 7 tầng kiểm tra ngay lúc ban hành; nếu còn lỗi -> lưu trạng thái `INVALID`
       và trả `422 WORKFLOW_VALIDATION_FAILED` kèm danh sách lỗi từng tầng.
    3. Nếu đạt cả 7 tầng -> khóa trạng thái `PUBLISHED`, ghi thời điểm `published_at` và mã băm bất biến.
    """
    require_employee(actor)
    require_permission(actor, "workflows:manage")

    if payload.version_id:
        version = await repository.get_version_by_id(
            session,
            organization_id=actor.organization_id,
            workflow_id=workflow_id,
            version_id=payload.version_id,
        )
    else:
        version = await repository.get_latest_version(
            session,
            organization_id=actor.organization_id,
            workflow_id=workflow_id,
        )

    if version is None:
        raise NotFoundError("Không tìm thấy phiên bản quy trình để ban hành.", code="WORKFLOW_VERSION_NOT_FOUND")

    if version.status == WorkflowVersionStatus.PUBLISHED.value:
        raise ConflictError(
            "Phiên bản quy trình này đã ban hành và bất biến; hãy tạo phiên bản mới nếu cần thay đổi.",
            code="IMMUTABLE_WORKFLOW_VERSION",
        )

    report = validate_workflow_graph(version.graph_json)
    version.validation_report_json = report.model_dump()
    if not report.valid:
        version.status = WorkflowVersionStatus.INVALID.value
        await session.commit()
        raise ValidationAppError(
            message="Sơ đồ quy trình chưa vượt qua kiểm định 7 tầng nên không thể ban hành.",
            code="WORKFLOW_VALIDATION_FAILED",
            details=[err.model_dump() for err in report.errors],
        )

    version.content_hash = compute_graph_content_hash(version.graph_json)
    version.status = WorkflowVersionStatus.PUBLISHED.value
    version.published_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(version)
    return _to_version_out(version)
