"""Kịch bản nạp dữ liệu mẫu chạy lại nhiều lần an toàn cho môi trường phát triển cục bộ.

LƯU Ý BẢO MẬT: Toàn bộ mật khẩu mẫu dưới đây CHỈ DÙNG CHO MÔI TRƯỜNG PHÁT TRIỂN
VÀ TRÌNH DIỄN CỤC BỘ, tuyệt đối không sử dụng làm mặc định trên môi trường thật.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.identity.models import (
    AgentCapability,
    AgentIdentity,
    Department,
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
    Permission,
    Role,
    RolePermission,
    User,
    UserKind,
)
from app.modules.requests import intake
from app.modules.requests.models import (
    ImpactLevel,
    MessageKind,
    PriorityLevel,
    Request,
    RequestMessage,
    RequestParticipant,
    RequestSource,
    RequestStatus,
    RequestType,
    VisibilityLevel,
)

# Mật khẩu chung chỉ dùng để thử nghiệm và trình diễn cục bộ
DEMO_DEV_PASSWORD = "VadirasDemo#2026"

DEMO_DEPARTMENTS = (
    ("SUPPORT", "Hỗ trợ khách hàng", "Tiếp nhận và phân loại yêu cầu từ khách hàng và người dùng."),
    ("ENGINEERING", "Kỹ thuật phần mềm", "Xử lý lỗi hệ thống, sự cố dịch vụ và chỉnh sửa mã nguồn."),
    ("DEVOPS", "Vận hành hạ tầng", "Quản lý cấu hình môi trường, triển khai và độ ổn định hệ thống."),
    ("SECURITY", "An toàn thông tin", "Đánh giá rủi ro bảo mật, quyền truy cập và kiểm toán."),
    ("PRODUCT", "Quản lý sản phẩm", "Điều phối tiếp nhận khách hàng mới và tính năng sản phẩm."),
    ("MANAGEMENT", "Ban quản lý", "Phê duyệt thay đổi rủi ro cao và điều phối liên phòng ban."),
)

DEMO_PERMISSIONS = (
    ("users:read", "Xem danh sách thành viên trong tổ chức"),
    ("departments:read", "Xem danh sách phòng ban trong tổ chức"),
    ("requests:create", "Tạo yêu cầu công việc mới"),
    ("requests:read_all", "Xem toàn bộ yêu cầu thuộc tổ chức"),
    ("requests:read_own", "Xem các yêu cầu thuộc phạm vi của chính mình"),
    ("requests:update", "Cập nhật trạng thái, ưu tiên và phân công yêu cầu"),
    ("tasks:read", "Xem các đầu việc giao cho nhân viên"),
    ("tasks:manage", "Tạo, nhận xử lý, báo vướng mắc và hoàn tất đầu việc"),
    ("workflows:manage", "Thiết kế, kiểm tra và ban hành quy trình"),
    ("approvals:decide", "Phê duyệt hoặc từ chối yêu cầu thay đổi có rủi ro"),
    ("audit:read", "Xem nhật ký kiểm toán và bằng chứng xác minh"),
    ("agents:read", "Xem danh sách trợ lý AI và năng lực được cấp"),
)

DEMO_ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "admin": (
        "Quản trị viên tổ chức",
        tuple(code for code, _ in DEMO_PERMISSIONS),
    ),
    "department_manager": (
        "Quản lý phòng ban",
        (
            "users:read",
            "departments:read",
            "requests:create",
            "requests:read_all",
            "requests:update",
            "tasks:read",
            "tasks:manage",
            "workflows:manage",
            "approvals:decide",
            "agents:read",
        ),
    ),
    "security_auditor": (
        "Chuyên viên bảo mật & kiểm toán",
        (
            "departments:read",
            "requests:read_all",
            "tasks:read",
            "approvals:decide",
            "audit:read",
            "agents:read",
        ),
    ),
    "worker": (
        "Nhân viên xử lý nghiệp vụ",
        (
            "departments:read",
            "requests:create",
            "requests:read_all",
            "requests:update",
            "tasks:read",
            "tasks:manage",
        ),
    ),
    "employee": (
        "Nhân viên gửi yêu cầu",
        ("departments:read", "requests:create", "requests:read_own"),
    ),
    "customer_contact": (
        "Liên hệ khách hàng",
        ("requests:create", "requests:read_own"),
    ),
}

DEMO_USERS = (
    ("admin@vadiras.local", "Quản trị Hệ thống Demo", "MANAGEMENT", UserKind.EMPLOYEE, None, "admin"),
    ("manager@vadiras.local", "Trưởng nhóm Kỹ thuật", "ENGINEERING", UserKind.EMPLOYEE, None, "department_manager"),
    ("security@vadiras.local", "Kiểm toán Bảo mật", "SECURITY", UserKind.EMPLOYEE, None, "security_auditor"),
    ("worker@vadiras.local", "Kỹ sư Vận hành", "DEVOPS", UserKind.EMPLOYEE, None, "worker"),
    ("employee@vadiras.local", "Nhân viên Sản phẩm", "PRODUCT", UserKind.EMPLOYEE, None, "employee"),
    ("customer.a@acme.local", "Đại diện Khách hàng Acme", None, UserKind.CUSTOMER_CONTACT, "CUST-ACME", "customer_contact"),
    ("customer.b@globex.local", "Đại diện Khách hàng Globex", None, UserKind.CUSTOMER_CONTACT, "CUST-GLOBEX", "customer_contact"),
)

DEMO_AGENTS = (
    ("supervisor", "Điều phối viên trưởng", ("swarm:orchestrate", "swarm:resolve_conflicts")),
    ("request_analyst", "Chuyên viên Phân tích Yêu cầu", ("request:classify", "request:extract_entities")),
    ("technical_analyst", "Chuyên viên Kỹ thuật", ("tech:analyze_dependencies", "tech:decompose_tasks")),
    ("operations_analyst", "Chuyên viên Vận hành", ("ops:route_department", "ops:estimate_sla")),
    ("security_risk_analyst", "Chuyên viên Bảo mật & Rủi ro", ("security:scan_risk", "security:check_scope")),
    ("workflow_planner", "Trợ lý Thiết kế Quy trình", ("workflow:propose_dag",)),
    ("critic_reviewer", "Trợ lý Phản biện", ("workflow:critique_plan",)),
    ("executor_worker", "Trợ lý Thực thi", ("connector:execute_scoped_action",)),
    ("verification_worker", "Trợ lý Xác minh", ("verification:read_back_evidence",)),
)


@dataclass(frozen=True, slots=True)
class SeedSummary:
    """Thống kê số lượng bản ghi đã được bảo đảm tồn tại sau khi nạp dữ liệu mẫu."""

    organization_id: str
    departments_count: int
    users_count: int
    agents_count: int
    requests_count: int


async def seed_demo_data(session: AsyncSession) -> SeedSummary:
    """Nạp dữ liệu mẫu cho 1 tổ chức, 6 phòng ban, 7 tài khoản, 9 trợ lý AI và 5 loại yêu cầu.

    Thuật toán chạy lại an toàn: mỗi thực thể đều được kiểm tra bằng khóa tự nhiên
    (mã tổ chức, mã phòng ban, email, khóa chống trùng lặp) trước khi thêm mới,
    do đó có thể chạy nhiều lần liên tiếp mà không sinh dữ liệu trùng.
    """
    # Bước 1: Tạo hoặc lấy tổ chức mẫu duy nhất
    org = (
        await session.execute(sa.select(Organization).where(Organization.slug == "vadiras-demo"))
    ).scalar_one_or_none()
    if org is None:
        org = Organization(
            slug="vadiras-demo",
            name="VADIRAS FLOW Demo Enterprise",
            is_active=True,
            settings_json={"demo_mode": True},
        )
        session.add(org)
        await session.flush()

    # Bước 2: Bảo đảm đủ 6 phòng ban
    dept_map: dict[str, Department] = {}
    for code, name, desc in DEMO_DEPARTMENTS:
        dept = (
            await session.execute(
                sa.select(Department).where(
                    Department.organization_id == org.id,
                    Department.code == code,
                )
            )
        ).scalar_one_or_none()
        if dept is None:
            dept = Department(organization_id=org.id, code=code, name=name, description=desc)
            session.add(dept)
            await session.flush()
        dept_map[code] = dept

    # Bước 3: Bảo đảm danh mục quyền chuẩn
    perm_map: dict[str, Permission] = {}
    for code, desc in DEMO_PERMISSIONS:
        perm = (
            await session.execute(sa.select(Permission).where(Permission.code == code))
        ).scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code, description=desc)
            session.add(perm)
            await session.flush()
        perm_map[code] = perm

    # Bước 4: Bảo đảm 6 vai trò và gán quyền tương ứng
    role_map: dict[str, Role] = {}
    for role_code, (role_name, perm_codes) in DEMO_ROLES.items():
        role = (
            await session.execute(
                sa.select(Role).where(
                    Role.organization_id == org.id,
                    Role.code == role_code,
                )
            )
        ).scalar_one_or_none()
        if role is None:
            role = Role(organization_id=org.id, code=role_code, name=role_name)
            session.add(role)
            await session.flush()
        role_map[role_code] = role

        for p_code in perm_codes:
            perm = perm_map[p_code]
            rp_exists = (
                await session.execute(
                    sa.select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
            ).scalar_one_or_none()
            if rp_exists is None:
                session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    # Bước 5: Tạo 7 tài khoản thử nghiệm cục bộ và liên kết thành viên
    membership_by_email: dict[str, Membership] = {}
    shared_pw_hash = hash_password(DEMO_DEV_PASSWORD)
    for email, full_name, dept_code, user_kind, customer_ref, role_code in DEMO_USERS:
        user = (
            await session.execute(sa.select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = User(email=email, full_name=full_name, password_hash=shared_pw_hash, is_active=True)
            session.add(user)
            await session.flush()

        membership = (
            await session.execute(
                sa.select(Membership).where(
                    Membership.organization_id == org.id,
                    Membership.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            membership = Membership(
                organization_id=org.id,
                user_id=user.id,
                department_id=dept_map[dept_code].id if dept_code else None,
                user_kind=user_kind.value,
                customer_account_ref=customer_ref,
                status=MembershipStatus.ACTIVE.value,
            )
            session.add(membership)
            await session.flush()

        role = role_map[role_code]
        mr_exists = (
            await session.execute(
                sa.select(MembershipRole).where(
                    MembershipRole.membership_id == membership.id,
                    MembershipRole.role_id == role.id,
                )
            )
        ).scalar_one_or_none()
        if mr_exists is None:
            session.add(MembershipRole(membership_id=membership.id, role_id=role.id))

        membership_by_email[email] = membership

    # Bước 6: Tạo 9 danh tính dịch vụ trợ lý AI kèm năng lực đăng ký
    admin_membership = membership_by_email["admin@vadiras.local"]
    for role_code, display_name, capabilities in DEMO_AGENTS:
        agent = (
            await session.execute(
                sa.select(AgentIdentity).where(
                    AgentIdentity.organization_id == org.id,
                    AgentIdentity.role_code == role_code,
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            agent = AgentIdentity(
                organization_id=org.id,
                role_code=role_code,
                display_name=display_name,
                status="ACTIVE",
                owner_user_id=admin_membership.user_id,
                limits_json={"max_concurrent_tasks": 4, "max_review_rounds": 2},
            )
            session.add(agent)
            await session.flush()

        for cap_code in capabilities:
            cap_exists = (
                await session.execute(
                    sa.select(AgentCapability).where(
                        AgentCapability.agent_identity_id == agent.id,
                        AgentCapability.capability_code == cap_code,
                    )
                )
            ).scalar_one_or_none()
            if cap_exists is None:
                session.add(
                    AgentCapability(
                        organization_id=org.id,
                        agent_identity_id=agent.id,
                        capability_code=cap_code,
                        is_enabled=True,
                    )
                )

    # Bước 7: Tạo 5 yêu cầu mẫu phủ đủ 5 loại yêu cầu
    sample_requests = [
        (
            "seed-incident-001",
            "REQ-000001",
            "customer.a@acme.local",
            "SUPPORT",
            RequestType.INCIDENT,
            PriorityLevel.P1_CRITICAL,
            ImpactLevel.HIGH,
            "Lỗi 502 khi xuất báo cáo PDF cuối tháng",
            "Hệ thống báo cáo trả lỗi 502 từ 09:00 UTC. Liên hệ hỗ trợ qua ops@acme.local hoặc 0901234567.",
            "Đã chuyển nhóm Kỹ thuật kiểm tra nhật ký máy chủ (ghi chú nội bộ).",
            "Chúng tôi đã tiếp nhận sự cố và đang điều phối xử lý ưu tiên cao.",
        ),
        (
            "seed-change-002",
            "REQ-000002",
            "worker@vadiras.local",
            "DEVOPS",
            RequestType.CHANGE,
            PriorityLevel.P2_HIGH,
            ImpactLevel.HIGH,
            "Thay đổi giới hạn kết nối CSDL cho dịch vụ thanh toán",
            "Đề xuất tăng số kết nối tối đa ở môi trường thử nghiệm lên 200 trước đợt kiểm tải.",
            "Cần Quản lý và Bảo mật phê duyệt rõ trước khi thực thi thay đổi.",
            None,
        ),
        (
            "seed-service-003",
            "REQ-000003",
            "customer.b@globex.local",
            "SUPPORT",
            RequestType.SERVICE_REQUEST,
            PriorityLevel.P3_MEDIUM,
            ImpactLevel.LOW,
            "Cấp thêm quyền đọc bảng điều khiển phân tích cho tài khoản mới",
            "Khách hàng Globex cần mở quyền xem báo cáo định kỳ cho nhân sự phụ trách mới.",
            "Đang kiểm tra danh sách tài khoản hợp lệ thuộc CUST-GLOBEX.",
            "Yêu cầu dịch vụ của quý khách đang được bộ phận Hỗ trợ xử lý.",
        ),
        (
            "seed-onboarding-004",
            "REQ-000004",
            "customer.a@acme.local",
            "PRODUCT",
            RequestType.ONBOARDING,
            PriorityLevel.P2_HIGH,
            ImpactLevel.MEDIUM,
            "Tiếp nhận và cấu hình không gian làm việc cho khách hàng Acme",
            "Hoàn tất danh mục bàn giao kỹ thuật, kiểm tra bảo mật và hướng dẫn sử dụng ban đầu.",
            "Cần phối hợp 4 phòng ban: Hỗ trợ, Sản phẩm, Kỹ thuật và Bảo mật.",
            "Chào mừng Acme! Lộ trình tiếp nhận khách hàng mới đã được khởi tạo.",
        ),
        (
            "seed-internal-005",
            "REQ-000005",
            "employee@vadiras.local",
            "MANAGEMENT",
            RequestType.INTERNAL_TASK,
            PriorityLevel.P3_MEDIUM,
            ImpactLevel.MEDIUM,
            "Rà soát quy trình phản ứng sự cố liên phòng ban Quý 4",
            "Cần Sản phẩm, Kỹ thuật và An toàn thông tin cập nhật danh sách trực sự cố.",
            "Đầu việc nội bộ liên phòng ban, không hiển thị cho khách hàng.",
            None,
        ),
    ]

    for (
        idem_key,
        req_num,
        requester_email,
        dept_code,
        req_type,
        priority,
        impact,
        title,
        description,
        internal_note,
        customer_reply,
    ) in sample_requests:
        existing_req = (
            await session.execute(
                sa.select(Request).where(
                    Request.organization_id == org.id,
                    Request.idempotency_key == idem_key,
                )
            )
        ).scalar_one_or_none()
        if existing_req is not None:
            continue

        requester = membership_by_email[requester_email]
        sanitized_desc, pii_list = intake.redact_pii(description)
        flags = intake.detect_prompt_injection_signals(f"{title}\n{description}")
        content_hash = intake.compute_content_hash(
            organization_id=org.id,
            requester_membership_id=requester.id,
            request_type=req_type.value,
            title=title,
            description=description,
        )

        new_req = Request(
            organization_id=org.id,
            request_number=req_num,
            title=title,
            description=description,
            sanitized_description=sanitized_desc,
            pii_redactions_json=pii_list,
            injection_flags_json=flags,
            request_type=req_type.value,
            source=RequestSource.API.value,
            status=RequestStatus.OPEN.value,
            priority=priority.value,
            impact=impact.value,
            urgency=impact.value,
            requester_membership_id=requester.id,
            requester_kind=requester.user_kind,
            customer_account_ref=requester.customer_account_ref,
            department_id=dept_map[dept_code].id,
            proposed_departments_json=[dept_code],
            idempotency_key=idem_key,
            content_hash=content_hash,
            metadata_json={"seeded": True},
            created_by_user_id=requester.user_id,
            updated_by_user_id=requester.user_id,
        )
        session.add(new_req)
        await session.flush()

        session.add(
            RequestParticipant(
                organization_id=org.id,
                request_id=new_req.id,
                membership_id=requester.id,
                participant_role="REQUESTER",
            )
        )
        session.add(
            RequestMessage(
                organization_id=org.id,
                request_id=new_req.id,
                author_membership_id=admin_membership.id,
                body=internal_note,
                visibility=VisibilityLevel.INTERNAL_ONLY.value,
                message_kind=MessageKind.SYSTEM_NOTE.value,
            )
        )
        if customer_reply:
            session.add(
                RequestMessage(
                    organization_id=org.id,
                    request_id=new_req.id,
                    author_membership_id=admin_membership.id,
                    body=customer_reply,
                    visibility=VisibilityLevel.CUSTOMER_VISIBLE.value,
                    message_kind=MessageKind.COMMENT.value,
                )
            )

    await session.commit()

    total_reqs = int(
        (
            await session.execute(
                sa.select(sa.func.count()).select_from(Request).where(Request.organization_id == org.id)
            )
        ).scalar_one()
    )
    return SeedSummary(
        organization_id=org.id,
        departments_count=len(dept_map),
        users_count=len(membership_by_email),
        agents_count=len(DEMO_AGENTS),
        requests_count=total_reqs,
    )
