"""Cấu hình dùng chung và dữ liệu mẫu cho các bài kiểm thử Giai đoạn 2."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import create_engine_and_session_factory
from app.main import create_app
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
from data.seeds.demo_seed import DEMO_AGENTS

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_alembic_config(database_url: str) -> Config:
    """Tạo đối tượng cấu hình Alembic trỏ tới một đường dẫn cơ sở dữ liệu cụ thể."""
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest_asyncio.fixture
async def db_and_session_factory(
    tmp_path: Path,
) -> AsyncIterator[tuple[str, async_sessionmaker[AsyncSession]]]:
    """Tạo một cơ sở dữ liệu sạch, chạy nâng cấp bảng Alembic mới tinh cho mỗi bài kiểm thử."""
    db_file = tmp_path / "test_phase2.db"
    database_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    previous_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        alembic_cfg = build_alembic_config(database_url)
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

        engine, session_factory = create_engine_and_session_factory(database_url)
        try:
            yield database_url, session_factory
        finally:
            await engine.dispose()
    finally:
        if previous_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_db_url


@pytest_asyncio.fixture
async def seeded_env(
    db_and_session_factory: tuple[str, async_sessionmaker[AsyncSession]],
) -> dict[str, object]:
    """Nạp dữ liệu mẫu cho 2 tổ chức độc lập, 6 phòng ban, các vai trò và 6 tài khoản kiểm thử."""
    database_url, session_factory = db_and_session_factory

    settings = Settings(
        app_env="test",
        database_url=database_url,
        temporal_address="",
        jwt_secret_key="khoa_bi_mat_kiem_thu_cuc_bo_du_do_dai_32_ky_tu",
        jwt_access_token_expire_minutes=15,
        jwt_refresh_token_expire_days=7,
    )

    async with session_factory() as session:
        # 1. Tạo 2 tổ chức để kiểm thử khả năng cô lập dữ liệu giữa các tổ chức
        org_a = Organization(slug="vadiras-demo", name="Vadiras Demo Corp", is_active=True)
        org_b = Organization(slug="other-org", name="Tổ chức Khác", is_active=True)
        session.add_all([org_a, org_b])
        await session.flush()

        # 2. Tạo đủ 6 phòng ban mẫu cho tổ chức A và 1 phòng ban cho tổ chức B
        dept_specs = [
            ("SUPPORT", "Hỗ trợ khách hàng"),
            ("ENGINEERING", "Kỹ thuật phần mềm"),
            ("DEVOPS", "Vận hành hạ tầng"),
            ("SECURITY", "An toàn thông tin"),
            ("PRODUCT", "Sản phẩm"),
            ("MANAGEMENT", "Quản lý"),
        ]
        depts_a: dict[str, Department] = {}
        for code, name in dept_specs:
            dept = Department(organization_id=org_a.id, code=code, name=name)
            session.add(dept)
            depts_a[code] = dept

        dept_b = Department(organization_id=org_b.id, code="OPS_B", name="Vận hành B")
        session.add(dept_b)
        await session.flush()

        # 3. Tạo danh mục quyền chuẩn cho Định danh, Yêu cầu và Tác vụ
        perm_users_read = Permission(code="users:read", description="Xem danh sách thành viên")
        perm_depts_read = Permission(code="departments:read", description="Xem danh sách phòng ban")
        perm_req_create = Permission(code="requests:create", description="Tạo yêu cầu mới")
        perm_req_read_all = Permission(code="requests:read_all", description="Xem toàn bộ yêu cầu tổ chức")
        perm_req_read_own = Permission(code="requests:read_own", description="Xem yêu cầu của chính mình")
        perm_req_update = Permission(code="requests:update", description="Cập nhật yêu cầu")
        perm_tasks_read = Permission(code="tasks:read", description="Xem đầu việc nội bộ")
        perm_tasks_manage = Permission(code="tasks:manage", description="Quản lý đầu việc nội bộ")
        perm_agents_read = Permission(code="agents:read", description="Xem danh sách trợ lý AI")
        perm_workflows_manage = Permission(code="workflows:manage", description="Đề xuất và quản lý quy trình")
        perm_approvals_decide = Permission(code="approvals:decide", description="Phê duyệt hoặc từ chối thay đổi")
        session.add_all(
            [
                perm_users_read,
                perm_depts_read,
                perm_req_create,
                perm_req_read_all,
                perm_req_read_own,
                perm_req_update,
                perm_tasks_read,
                perm_tasks_manage,
                perm_agents_read,
                perm_workflows_manage,
                perm_approvals_decide,
            ]
        )
        await session.flush()

        # 4. Tạo các vai trò cho Tổ chức A và Tổ chức B
        role_admin_a = Role(organization_id=org_a.id, code="admin", name="Quản trị viên")
        role_mgr_a = Role(organization_id=org_a.id, code="department_manager", name="Quản lý phòng ban")
        role_emp_a = Role(organization_id=org_a.id, code="employee", name="Nhân viên")
        role_cust_a = Role(organization_id=org_a.id, code="customer_contact", name="Liên hệ khách hàng")
        role_admin_b = Role(organization_id=org_b.id, code="admin", name="Quản trị viên B")
        session.add_all([role_admin_a, role_mgr_a, role_emp_a, role_cust_a, role_admin_b])
        await session.flush()

        session.add_all(
            [
                RolePermission(role_id=role_admin_a.id, permission_id=perm_users_read.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_depts_read.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_req_create.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_req_read_all.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_req_update.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_tasks_read.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_tasks_manage.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_agents_read.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_workflows_manage.id),
                RolePermission(role_id=role_admin_a.id, permission_id=perm_approvals_decide.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_users_read.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_depts_read.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_req_create.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_req_read_all.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_req_update.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_tasks_read.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_tasks_manage.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_agents_read.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_workflows_manage.id),
                RolePermission(role_id=role_mgr_a.id, permission_id=perm_approvals_decide.id),
                RolePermission(role_id=role_emp_a.id, permission_id=perm_depts_read.id),
                RolePermission(role_id=role_emp_a.id, permission_id=perm_req_create.id),
                RolePermission(role_id=role_emp_a.id, permission_id=perm_req_read_own.id),
                RolePermission(role_id=role_emp_a.id, permission_id=perm_tasks_read.id),
                RolePermission(role_id=role_emp_a.id, permission_id=perm_tasks_manage.id),
                RolePermission(role_id=role_cust_a.id, permission_id=perm_req_create.id),
                RolePermission(role_id=role_cust_a.id, permission_id=perm_req_read_own.id),
                RolePermission(role_id=role_admin_b.id, permission_id=perm_users_read.id),
                RolePermission(role_id=role_admin_b.id, permission_id=perm_depts_read.id),
                RolePermission(role_id=role_admin_b.id, permission_id=perm_req_create.id),
                RolePermission(role_id=role_admin_b.id, permission_id=perm_req_read_all.id),
                RolePermission(role_id=role_admin_b.id, permission_id=perm_tasks_read.id),
                RolePermission(role_id=role_admin_b.id, permission_id=perm_agents_read.id),
                RolePermission(role_id=role_admin_b.id, permission_id=perm_approvals_decide.id),
            ]
        )

        # 5. Tạo người dùng mẫu với mật khẩu chung chỉ dùng để kiểm thử
        demo_pw_hash = hash_password("MatKhauThuNghiem#2026")
        user_admin_a = User(email="admin@vadiras.local", full_name="Quản trị A", password_hash=demo_pw_hash)
        user_mgr_a = User(email="manager@vadiras.local", full_name="Quản lý Kỹ thuật", password_hash=demo_pw_hash)
        user_emp_a = User(email="employee@vadiras.local", full_name="Nhân viên Hỗ trợ", password_hash=demo_pw_hash)
        user_cust_a = User(email="customer@client.local", full_name="Khách hàng A", password_hash=demo_pw_hash)
        user_suspended_a = User(
            email="locked@vadiras.local",
            full_name="Tài khoản bị khóa",
            password_hash=demo_pw_hash,
            is_active=True,
        )
        user_admin_b = User(email="admin@other.local", full_name="Quản trị B", password_hash=demo_pw_hash)
        session.add_all([user_admin_a, user_mgr_a, user_emp_a, user_cust_a, user_suspended_a, user_admin_b])
        await session.flush()

        mem_admin_a = Membership(
            organization_id=org_a.id,
            user_id=user_admin_a.id,
            department_id=depts_a["MANAGEMENT"].id,
            user_kind=UserKind.EMPLOYEE.value,
            status=MembershipStatus.ACTIVE.value,
        )
        mem_mgr_a = Membership(
            organization_id=org_a.id,
            user_id=user_mgr_a.id,
            department_id=depts_a["ENGINEERING"].id,
            user_kind=UserKind.EMPLOYEE.value,
            status=MembershipStatus.ACTIVE.value,
        )
        mem_emp_a = Membership(
            organization_id=org_a.id,
            user_id=user_emp_a.id,
            department_id=depts_a["SUPPORT"].id,
            user_kind=UserKind.EMPLOYEE.value,
            status=MembershipStatus.ACTIVE.value,
        )
        mem_cust_a = Membership(
            organization_id=org_a.id,
            user_id=user_cust_a.id,
            department_id=None,
            user_kind=UserKind.CUSTOMER_CONTACT.value,
            customer_account_ref="CUST-001",
            status=MembershipStatus.ACTIVE.value,
        )
        mem_suspended_a = Membership(
            organization_id=org_a.id,
            user_id=user_suspended_a.id,
            department_id=depts_a["SUPPORT"].id,
            user_kind=UserKind.EMPLOYEE.value,
            status=MembershipStatus.SUSPENDED.value,
        )
        mem_admin_b = Membership(
            organization_id=org_b.id,
            user_id=user_admin_b.id,
            department_id=dept_b.id,
            user_kind=UserKind.EMPLOYEE.value,
            status=MembershipStatus.ACTIVE.value,
        )
        session.add_all([mem_admin_a, mem_mgr_a, mem_emp_a, mem_cust_a, mem_suspended_a, mem_admin_b])
        await session.flush()

        session.add_all(
            [
                MembershipRole(membership_id=mem_admin_a.id, role_id=role_admin_a.id),
                MembershipRole(membership_id=mem_mgr_a.id, role_id=role_mgr_a.id),
                MembershipRole(membership_id=mem_emp_a.id, role_id=role_emp_a.id),
                MembershipRole(membership_id=mem_cust_a.id, role_id=role_cust_a.id),
                MembershipRole(membership_id=mem_admin_b.id, role_id=role_admin_b.id),
            ]
        )

        # 6. Nạp sẵn 9 danh tính trợ lý AI chuẩn cho Tổ chức A
        for role_code, display_name, capabilities in DEMO_AGENTS:
            agent = AgentIdentity(
                organization_id=org_a.id,
                role_code=role_code,
                display_name=display_name,
                status="ACTIVE",
                owner_user_id=user_admin_a.id,
                limits_json={"max_concurrent_tasks": 4, "max_review_rounds": 2},
            )
            session.add(agent)
            await session.flush()
            for cap_code in capabilities:
                session.add(
                    AgentCapability(
                        organization_id=org_a.id,
                        agent_identity_id=agent.id,
                        capability_code=cap_code,
                        is_enabled=True,
                    )
                )

        await session.commit()

    app = create_app(settings=settings, session_factory=session_factory)
    return {
        "app": app,
        "settings": settings,
        "session_factory": session_factory,
        "org_a_id": org_a.id,
        "org_b_id": org_b.id,
        "emp_membership_id": mem_emp_a.id,
        "mgr_membership_id": mem_mgr_a.id,
        "role_mgr_a_id": role_mgr_a.id,
        "role_cust_a_id": role_cust_a.id,
        "password": "MatKhauThuNghiem#2026",
    }


@pytest_asyncio.fixture
async def api_client(seeded_env: dict[str, object]) -> AsyncIterator[AsyncClient]:
    """Tạo bộ gọi HTTP bất đồng bộ chạy trực tiếp trên ứng dụng FastAPI kiểm thử."""
    app = seeded_env["app"]
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
