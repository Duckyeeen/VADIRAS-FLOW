# VADIRAS FLOW — Backend Điều phối Quy trình Doanh nghiệp Hỗ trợ AI

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL 16 + pgvector](https://img.shields.io/badge/PostgreSQL_16-pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Temporal](https://img.shields.io/badge/Temporal-1.25-111111?logo=temporal&logoColor=white)](https://temporal.io/)
[![Docker Compose](https://img.shields.io/badge/Docker_Compose-6_Services-2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![API Endpoints](https://img.shields.io/badge/API-64_Endpoints-success)](#tổng-quan-64-tuyến-api)
[![Tests](https://img.shields.io/badge/Pytest-74_Passed-brightgreen)](#kiểm-thử-tự-động)

**VADIRAS FLOW** là nền tảng Backend điều phối các quy trình tiếp nhận và xử lý yêu cầu doanh nghiệp với sự hỗ trợ của nhóm trợ lý AI, được thiết kế theo nguyên tắc kiến trúc cốt lõi:

> **AI đề xuất — Bộ kiểm soát quy tắc cấp phép — Temporal thực thi bền vững — Bộ máy xác minh chứng minh bằng bằng chứng thực tế.**

**Mục lục nhanh:** [Kiến trúc](#-kiến-trúc-hệ-thống) · [10 Phân hệ](#-10-phân-hệ-nghiệp-vụ-cốt-lõi) · [Cấu trúc thư mục](#-cấu-trúc-thư-mục-backend) · [Khởi chạy nhanh](#-khởi-chạy-nhanh) · [Tài khoản demo](#-tài-khoản-demo-cục-bộ) · [64 Tuyến API](#tổng-quan-64-tuyến-api) · [Biến môi trường](#-cấu-hình-môi-trường--tích-hợp-thật) · [Kiểm thử](#kiểm-thử-tự-động) · [Tài liệu](#-tài-liệu-dự-án)

---

## 🏗 Kiến trúc Hệ thống

```mermaid
flowchart LR
    CLIENT["Client / Frontend / Webhook"] --> API["FastAPI Gateway (app/api + app/main)"]
    API --> ID["Identity & RBAC (JWT + Argon2id)"]
    API --> REQ["Requests Intake (PII Redaction & Guard)"]
    REQ --> AI["AI Swarm (9 Roles, Bounded Rounds)"]
    AI --> WF["Workflow DSL v1 (7-Stage Validator + Hash)"]
    WF --> GOV["Governance Guard (Policy + 7-Factor Approval)"]
    GOV --> RT["Temporal Runtime & Worker"]
    RT --> CONN["Connectors (Mock / GitHub App + Reconciler)"]
    CONN --> VER["Verification Engine & Append-Only Audit"]
    API <--> DB[("PostgreSQL 16 + pgvector (43 Bảng)")]
    RT <--> DB
    VER --> DB
    DB --> OUTBOX["Outbox Worker -> SSE & 7 Metrics APIs"]
    DB --> MEM["Semantic Memory (pgvector + Promotion Gate)"]
```

### Nguyên tắc Thiết kế Bảo mật & Tin cậy
- **Không tự nâng quyền / không sửa bản đang chạy:** Phiên bản quy trình ở trạng thái `PUBLISHED` bị khóa bất biến kèm mã băm SHA-256 (`content_hash`); đề xuất lập lại (`replan`) bị giới hạn cứng tối đa 2 lần và tự động mở cổng phê duyệt nếu tăng phạm vi hoặc rủi ro.
- **Phê duyệt ràng buộc 7 yếu tố:** Mỗi lệnh phê duyệt khóa chặt theo tổ chức, phiên bản quy trình, mã bước, mã băm tham số, phạm vi tài nguyên, quyết định chính sách và thời hạn; chống tự phê duyệt (`SELF_APPROVAL_FORBIDDEN`).
- **Tách biệt dữ liệu đa tổ chức & khách hàng:** Lọc theo `organization_id` và quyền xem (`CUSTOMER_VISIBLE` so với nội bộ); không bao giờ lưu hay trả về suy nghĩ ẩn (`reasoning_trace`) của AI hoặc bí mật trong log.
- **Chống trùng lặp đầu–cuối:** Áp dụng `Idempotency-Key` cho yêu cầu, lượt chạy, thao tác connector và `X-GitHub-Delivery` + HMAC-SHA256 cho Webhook.

---

## 🧩 10 Phân hệ Nghiệp vụ Cốt lõi

| Phân hệ (`app/modules/`) | Trách nhiệm chính | Điểm nổi bật kỹ thuật |
| :--- | :--- | :--- |
| **`identity`** | Định danh, tổ chức, phòng ban & RBAC | JWT access + refresh rotation, Argon2id, kiểm tra lại quyền mới nhất từ CSDL |
| **`requests`** | Tiếp nhận 5 nhóm yêu cầu & đầu việc nhân sự | `INCIDENT`, `CHANGE`, `SERVICE_REQUEST`, `ONBOARDING`, `INTERNAL_TASK`; che PII; gắn cờ prompt injection |
| **`ai_intelligence`** | Lớp trừu tượng `LLMProvider` & nhóm 9 trợ lý AI | `MockLLMProvider` / `OpenAICompatibleProvider`, bounded JSON repair, tối đa 4 tác vụ song song / 2 vòng phản biện |
| **`workflows`** | Ngôn ngữ mô tả DAG 12 bước & kiểm định 7 tầng | Điều kiện rẽ nhánh bằng JSON AST an toàn (không `eval`), chấm điểm phương án, khóa bất biến SHA-256 |
| **`governance`** | Đánh giá rủi ro, chính sách & phê duyệt 7 yếu tố | Phân tầng `LOW`–`CRITICAL`, `PolicyEngine`, `ToolBroker`, `ExecutionGuard` |
| **`runtime`** | Bộ chạy bền vững trên Temporal | `RequestOrchestrationWorkflow`, `pause` / `resume` / `cancel`, replay-safe khi worker khởi động lại |
| **`connectors`** | Kết nối hệ thống ngoài (`providers/`), Webhook & bù sự kiện | `MockGitHubConnector` và `GitHubAppConnector` (JWT RS256), xác thực chữ ký thô `X-Hub-Signature-256`, `Reconciler` |
| **`verification`** | Bộ máy xác minh bằng chứng & kiểm toán | Đọc ngược tài nguyên đích chấm 4 trạng thái (`VERIFIED`, `PARTIALLY_VERIFIED`, `FAILED`, `UNVERIFIED`), `audit_logs` chỉ thêm mới |
| **`memory`** | Bộ nhớ ngữ nghĩa đa tầng trên `pgvector` | Vector embedding, cổng kiểm duyệt thăng hạng tri thức, lọc kết quả theo quyền truy cập |
| **`observability`** | Hàng đợi giao dịch `outbox_events`, SSE, SLA & thống kê | `outbox-worker` phát luồng SSE theo `run_id`, tính SLA 4 mức, đủ 7 API `/api/v1/metrics/*` |

---

## 📂 Cấu trúc Thư mục Backend

```text
VADIRAS-FLOW/
├── alembic/                      # 8 bản nâng cấp schema PostgreSQL/SQLite (43 bảng nghiệp vụ)
├── app/
│   ├── main.py                   # App factory, lifespan, middleware correlation/CORS & error handlers
│   ├── api/                      # Tầng định tuyến HTTP: health.py (/health/*) & v1.py (/api/v1/*)
│   ├── core/                     # Config, security, logging (redact secrets), correlation, shared schemas
│   ├── db/                       # Async SQLAlchemy engine/session, Base & mixins chuẩn
│   ├── adapters/                 # Lớp tương thích ngược v0 (8 module giữ ổn định hợp đồng cũ)
│   └── modules/                  # 10 phân hệ nghiệp vụ độc lập
│       ├── ai_intelligence/      # prompts/, providers/ (mock, openai_compat), swarm/
│       ├── connectors/           # providers/ (base, factory, github_app, mock_github), webhook_inbox, reconciler
│       ├── governance/           # risk, policy_engine, approvals, tool_broker, execution_guard
│       ├── identity/             # auth, dependencies, models, router, service
│       ├── memory/               # embeddings, retrieval, promotion gating
│       ├── observability/        # events, outbox, sse, sla, analytics
│       ├── requests/             # intake, PII redaction, human tasks
│       ├── runtime/              # temporal_client, workflows, activities, worker, state_machine
│       ├── verification/         # engine, evidence, audit
│       └── workflows/            # dsl/ (schemas, AST conditions), registry, scoring, validator
├── data/
│   ├── seeds/demo_seed.py        # Nạp dữ liệu mẫu idempotent cho môi trường phát triển
│   └── workflow_templates/       # 5 mẫu quy trình JSON chuẩn cho 5 nhóm yêu cầu
├── prompts/swarm_v1.json         # Cấu hình hệ thống câu lệnh 9 vai trò trợ lý AI
├── scripts/seed_demo.py          # Lệnh CLI nạp dữ liệu mẫu
├── tests/                        # 74 bài kiểm thử (unit, integration, security, e2e)
├── docker-compose.yml            # Cụm 6 dịch vụ cho Docker Desktop (stack: vadiras-flow)
├── Dockerfile                    # Image chung cho api, temporal-worker và outbox-worker
├── alembic.ini
└── requirements.txt
```

---

## 🚀 Khởi chạy Nhanh

### Cách 1: Docker Compose / Docker Desktop (Khuyến nghị — đủ 6 dịch vụ)

Cấu hình mặc định trong [docker-compose.yml](docker-compose.yml) đã sẵn sàng chạy chế độ phát triển (`DEMO_MODE=true`, `LLM_PROVIDER=mock`, `GITHUB_CONNECTOR_MODE=mock`) mà **không cần tạo `.env` hay API key**.

```powershell
# Khởi chạy toàn bộ 6 dịch vụ (PostgreSQL 16 + pgvector, Temporal, Temporal UI, API, 2 Workers)
docker compose up --build -d

# Kiểm tra trạng thái 6 container
docker compose ps
```

> [!WARNING]
> Tệp `.env.example` có đặt `TEMPORAL_ADDRESS=localhost:7233` để chạy Python trực tiếp ngoài Docker. Nếu bạn tạo tệp `.env` khi chạy Docker Compose, hãy giữ `TEMPORAL_ADDRESS=temporal:7233` và `DATABASE_URL=postgresql+asyncpg://vadiras:vadiras_dev_password@postgres:5432/vadiras_flow` (tên dịch vụ nội bộ Docker), nếu không container `api` và `temporal-worker` sẽ tìm nhầm `localhost` bên trong container.

**6 dịch vụ sau khi khởi động:**

| Container | Dịch vụ | Vai trò | Cổng truy cập |
| :--- | :--- | :--- | :--- |
| `vadiras-api` | `api` | FastAPI + tự động chạy `alembic upgrade head` & nạp seed | `http://localhost:8000` |
| `vadiras-postgres` | `postgres` | PostgreSQL 16 tích hợp sẵn `pgvector` | `localhost:5432` |
| `vadiras-temporal` | `temporal` | Máy chủ điều phối quy trình Temporal | `localhost:7233` |
| `vadiras-temporal-ui` | `temporal-ui` | Giao diện web giám sát workflow Temporal | `http://localhost:8080` |
| `vadiras-temporal-worker` | `temporal-worker` | Tiến trình chạy quy trình & activities (`app.modules.runtime.worker`) | nội bộ |
| `vadiras-outbox-worker` | `outbox-worker` | Tiến trình đọc `outbox_events` & đẩy SSE (`app.modules.observability.outbox`) | nội bộ |

**Các địa chỉ kiểm tra nhanh:**
- **Swagger UI:** `http://localhost:8000/docs`
- **Health Live:** `http://localhost:8000/health/live`
- **Health Ready (CSDL + Temporal):** `http://localhost:8000/health/ready`
- **Temporal Web UI:** `http://localhost:8080`

**Lệnh vận hành Docker thường dùng:**
```powershell
docker compose logs -f                 # Xem nhật ký trực tiếp toàn cụm
docker compose stop                    # Tạm dừng container (giữ nguyên dữ liệu)
docker compose down                    # Tắt và gỡ container (giữ volume postgres_data)
docker compose down -v                 # Xóa sạch cả dữ liệu DB để làm mới từ đầu
```

### Cách 2: Chạy Cục bộ với Python 3.11+ (SQLite / phát triển nhanh)

```powershell
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m scripts.seed_demo
uvicorn app.main:app --reload --port 8000
```

---

## 👥 Tài khoản Demo Cục bộ

Khi bật `DEMO_MODE=true`, [demo_seed.py](data/seeds/demo_seed.py) tự động khởi tạo **1 tổ chức** (`vadiras-demo`), **6 phòng ban**, **9 trợ lý AI**, **5 yêu cầu mẫu** và **7 tài khoản** với mật khẩu thử nghiệm chung `VadirasDemo#2026`:

| Email | Vai trò | Phòng ban | Phạm vi trình diễn chính |
| :--- | :--- | :--- | :--- |
| `admin@vadiras.local` | `admin` | `MANAGEMENT` | Toàn quyền quản trị tổ chức và điều phối |
| `manager@vadiras.local` | `department_manager` | `ENGINEERING` | Phân tích AI, ban hành quy trình, phê duyệt, kiểm toán, thống kê |
| `security@vadiras.local` | `security_auditor` | `SECURITY` | Phê duyệt thay đổi, kiểm tra bằng chứng và nhật ký kiểm toán |
| `worker@vadiras.local` | `worker` | `DEVOPS` | Nhận và hoàn thành đầu việc nhân sự (`human_tasks`) |
| `employee@vadiras.local` | `employee` | `PRODUCT` | Gửi yêu cầu nội bộ và theo dõi yêu cầu của mình |
| `customer.a@acme.local` | `customer_contact` | — | Gửi yêu cầu; chỉ xem bằng chứng `CUSTOMER_VISIBLE` của chính mình |
| `customer.b@globex.local` | `customer_contact` | — | Kiểm chứng cô lập: không thể xem dữ liệu của Khách hàng A |

---

<a id="tổng-quan-64-tuyến-api"></a>
## 🔌 Tổng quan 64 Tuyến API

Hệ thống phục vụ **64 endpoints** (xem đặc tả chi tiết tương tác tại `/docs` khi khởi chạy):

| Nhóm API | Số tuyến | Đường dẫn tiêu biểu |
| :--- | :---: | :--- |
| **Sức khỏe hệ thống** | 2 | `GET /health/live`, `GET /health/ready` |
| **Định danh & Tổ chức** | 6 | `POST /api/v1/auth/{login,refresh,logout}`, `GET /api/v1/auth/me`, `GET /api/v1/{users,departments}` |
| **Yêu cầu & Đầu việc** | 11 | `GET/POST /api/v1/requests`, `GET/PATCH /api/v1/requests/{id}`, `clarifications`, `messages`, `GET /api/v1/tasks`, `{claim,complete,block}` |
| **Trí tuệ AI & Trợ lý** | 5 | `GET /api/v1/agents`, `GET /api/v1/agents/{id}`, `POST /api/v1/requests/{id}/{analyze,propose-workflows}`, `GET .../analysis` |
| **Thiết kế & Kiểm định Quy trình** | 8 | `GET /api/v1/workflows/node-registry`, `POST .../validate`, `GET/POST /api/v1/workflows`, `publish`, `versions` |
| **Kiểm soát & Phê duyệt** | 5 | `POST /api/v1/governance/evaluate`, `GET/POST /api/v1/approvals`, `GET /approvals/{id}`, `POST .../decision` |
| **Thực thi Temporal Runtime** | 7 | `GET/POST /api/v1/workflow-runs`, `GET /{run_id}`, `POST /{run_id}/{pause,resume,cancel,replan}` |
| **Bộ kết nối & Webhook** | 5 | `GET /api/v1/connectors`, `GET /connectors/github/status`, `POST /connectors/github/{installations,reconcile}`, `POST /api/v1/webhooks/github` |
| **Xác minh & Kiểm toán** | 3 | `GET /api/v1/requests/{id}/verification`, `GET /api/v1/workflow-runs/{id}/evidence`, `GET /api/v1/audit-logs` |
| **Bộ nhớ Ngữ nghĩa** | 3 | `POST /api/v1/memory/items`, `POST /api/v1/memory/items/{id}/promote`, `GET /api/v1/memory/search` |
| **Giám sát, SSE & Thống kê** | 8 | `GET /api/v1/workflow-runs/{id}/events` (SSE), `GET /api/v1/metrics/{overview,sla,automation,cost,agents,departments,industries}` |

---

## ⚙️ Cấu hình Môi trường & Tích hợp Thật

Xem mẫu đầy đủ tại [.env.example](.env.example). Các biến quan trọng khi chuyển sang tích hợp thật:

| Nhóm cấu hình | Biến môi trường chính | Giá trị mặc định (Dev/Demo) |
| :--- | :--- | :--- |
| **Ứng dụng & CORS** | `APP_ENV`, `DEMO_MODE`, `CORS_ALLOWED_ORIGINS` | `development`, `true`, `http://localhost:3000,http://localhost:5173` *(chặn `*`)* |
| **CSDL & Temporal** | `DATABASE_URL`, `TEMPORAL_ADDRESS`, `TEMPORAL_TASK_QUEUE` | SQLite cục bộ hoặc `postgres:5432` / `temporal:7233` trong Docker |
| **JWT Auth** | `JWT_SECRET_KEY`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Khóa phát triển cục bộ (cần thay chuỗi $\ge 32$ ký tự khi deploy) |
| **Nhà cung cấp AI** | `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_API_BASE_URL`, `LLM_MODEL` | `mock` / `mock-default` (đổi sang `openai_compatible` để dùng API thật) |
| **GitHub App** | `GITHUB_CONNECTOR_MODE`, `GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, `GITHUB_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_ALLOWED_REPOS` | `mock` (hướng dẫn cấp quyền tối thiểu & tạo `.pem` xem tại [DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md)) |

> [!CAUTION]
> Tuyệt đối **không commit** `.env`, tệp khóa riêng `*.pem` / `*.key`, hoặc tệp cơ sở dữ liệu `*.db` / `*.sqlite3` lên Git (đã cấu hình chặn sẵn trong [.gitignore](.gitignore)).

---

<a id="kiểm-thử-tự-động"></a>
## 🧪 Kiểm thử Tự động

Bộ kiểm thử tự động gồm **74 test cases** bao phủ đủ 4 lớp (đơn vị, tích hợp, bảo mật cô lập dữ liệu và đầu–cuối E2E trên Temporal + FastAPI):

| Nhóm kiểm thử | Thư mục | Trọng tâm kiểm tra |
| :--- | :--- | :--- |
| **Unit (`35`)** | `tests/unit/` | PII redaction, Swarm bounds, Workflow DSL & 7-stage validator, Policy/Risk/7-factor approval, Connector errors, Memory/SLA, Security/Logs |
| **Integration (`26`)** | `tests/integration/` | Alembic upgrade/downgrade, Auth/RBAC, Requests/Tasks, AI API, Workflows immutability, Governance guard, Temporal DAG & worker restart, Webhooks, Verification/Audit, Memory/SSE/7 Metrics |
| **Security (`1`)** | `tests/security/` | Cô lập tổ chức & lọc dữ liệu khách hàng (`CUSTOMER_VISIBLE`) |
| **E2E (`12`)** | `tests/e2e/` | 2 vertical slice MVP + đủ 10 kịch bản nghiệm thu đầu–cuối (`test_full_10_acceptance_scenarios.py`) |

```powershell
# Chạy nhanh toàn bộ unit test (~2 giây)
python -m pytest tests/unit -v

# Chạy toàn bộ 74 bài kiểm thử
python -m pytest -v
```

---

## 📚 Tài liệu Dự án

- [Kế hoạch Triển khai Backend & 7 Sơ đồ Kiến trúc](docs/BACKEND_IMPLEMENTATION_PLAN.md)
- [Đặc tả Kỹ thuật Backend v1](docs/Vadiras_Flow_Backend_Technical_Spec_v1.md)
- [Sổ tay Vận hành, Kịch bản Trình diễn & Cấu hình GitHub App](docs/DEMO_RUNBOOK.md)
- [Báo cáo Tổng kết Từng Giai đoạn (Giai đoạn 1–11)](docs/phase_summaries/README.md)
