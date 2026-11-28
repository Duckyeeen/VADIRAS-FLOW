"""Bộ cấu trúc dữ liệu dùng chung và đã kiểm tra chặt chẽ cho API và quy trình VADIRAS FLOW."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContractModel(BaseModel):
    """Mô hình dữ liệu gốc: chặn các trường lạ không khai báo và tự động cắt khoảng trắng dư ở đầu/cuối chuỗi."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- Nhóm dữ liệu đầu vào khi tiếp nhận yêu cầu ---

class SourceChannel(str, Enum):
    WEB_FORM = "web_form"
    EMAIL_WEBHOOK = "email_webhook"
    API_BATCH = "api_batch"


class CustomerTier(str, Enum):
    FREE = "free"
    STANDARD = "standard"
    ENTERPRISE = "enterprise"


class CustomerInfo(ContractModel):
    customer_id: str = Field(min_length=1, max_length=128)
    organization: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(min_length=3, max_length=254)
    tier: CustomerTier

    # Kiểm tra định dạng địa chỉ email liên hệ hợp lệ (có ký tự @ và tên miền)
    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: str) -> str:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("contact_email must be a valid email address")
        return value


class ProductInfo(ContractModel):
    name: str = Field(min_length=1, max_length=120)
    module: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=64)
    environment: str = Field(min_length=1, max_length=64)


class AttachmentMeta(ContractModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=120)
    size_bytes: int | None = Field(default=None, ge=0)
    reference: str | None = Field(default=None, max_length=2048)


class InboundRequest(ContractModel):
    """Dữ liệu yêu cầu từ khách hàng sau khi được kiểm tra hợp lệ tại cổng tiếp nhận POST /requests/ingest."""

    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)
    source_channel: SourceChannel
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    customer: CustomerInfo
    product: ProductInfo
    subject: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20_000)
    requested_action: str = Field(min_length=1, max_length=2_000)
    attachments_meta: list[AttachmentMeta] = Field(default_factory=list, max_length=20)
    demo_sla_seconds: int = Field(default=45, ge=1, le=604_800)

    # Bắt buộc thời gian gửi yêu cầu phải có thông tin múi giờ rõ ràng (tránh lệch giờ UTC/nội địa)
    @field_validator("submitted_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("submitted_at must include a timezone")
        return value


# --- Nhóm dữ liệu ngữ cảnh sạch và tài liệu tham khảo trước khi đưa cho AI ---

class RetrievedDocument(ContractModel):
    document_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20_000)
    score: float = Field(ge=0.0)
    source: str | None = Field(default=None, max_length=500)


class SimilarTicket(ContractModel):
    ticket_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    resolution: str | None = Field(default=None, max_length=10_000)
    score: float = Field(ge=0.0)


class PreprocessedContext(ContractModel):
    """Ngữ cảnh đã được làm sạch, ẩn thông tin nhạy cảm và bổ sung tài liệu trước khi AI phân tích."""

    request_id: str = Field(min_length=1, max_length=64)
    idempotency_hash: str = Field(min_length=64, max_length=64)
    is_duplicate: bool = False
    validation_status: Literal["PASSED", "FAILED"]
    missing_mandatory_fields: list[str] = Field(default_factory=list)
    pii_redactions: list[str] = Field(default_factory=list)
    sanitized_text: str = Field(default="", max_length=50_000)
    retrieved_kb: list[RetrievedDocument] = Field(default_factory=list)
    similar_tickets: list[SimilarTicket] = Field(default_factory=list)

    # Đảm bảo mã chống trùng lặp đúng định dạng chuỗi thập lục phân SHA-256 dài 64 ký tự và chuẩn hóa về chữ thường
    @field_validator("idempotency_hash")
    @classmethod
    def validate_sha256_hash(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("idempotency_hash must be a 64-character SHA-256 hex digest")
        return value.lower()


# --- Nhóm dữ liệu kết quả phân tích của AI và quy tắc kiểm soát an toàn ---

class RequestCategory(str, Enum):
    BUG_BACKEND = "bug_backend"
    BUG_FRONTEND = "bug_frontend"
    ACCOUNT_ACCESS = "account_access"
    BILLING_REFUND = "billing_refund"
    FEATURE_REQUEST = "feature_request"
    HOW_TO_QUESTION = "how_to_question"
    OUT_OF_SCOPE_OR_SPAM = "out_of_scope_or_spam"


class Priority(str, Enum):
    P1_CRITICAL = "P1_CRITICAL"
    P2_HIGH = "P2_HIGH"
    P3_MEDIUM = "P3_MEDIUM"
    P4_LOW = "P4_LOW"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendedTeam(str, Enum):
    BACKEND_REPORTING = "Backend-Reporting"
    BACKEND_CORE = "Backend-Core"
    FRONTEND_WEB = "Frontend-Web"
    IAM_SECURITY = "IAM-Security"
    BILLING_OPS = "Billing-Ops"
    CUSTOMER_SUCCESS = "Customer-Success"
    TRIAGE_HUMAN = "Triage-Human"


class WorkflowTemplate(str, Enum):
    BACKEND_INCIDENT_FASTTRACK = "WF_BACKEND_INCIDENT_FASTTRACK"
    STANDARD_BUG_TRIAGE = "WF_STANDARD_BUG_TRIAGE"
    REQUEST_MORE_INFO = "WF_REQUEST_MORE_INFO"
    HIGH_RISK_HUMAN_APPROVAL = "WF_HIGH_RISK_HUMAN_APPROVAL"
    SELF_SERVICE_KB_REPLY = "WF_SELF_SERVICE_KB_REPLY"
    SAFE_REJECT = "WF_SAFE_REJECT"


class ProposedAction(ContractModel):
    action_type: str = Field(min_length=1, max_length=100)
    target_system: str = Field(min_length=1, max_length=100)
    ticket_title: str | None = Field(default=None, max_length=300)
    labels: list[str] = Field(default_factory=list, max_length=30)
    message_draft: str | None = Field(default=None, max_length=10_000)


class AIAnalysisOutput(ContractModel):
    """Kết quả phân loại có cấu trúc, đánh giá rủi ro và các hành động do AI đề xuất."""

    request_id: str = Field(min_length=1, max_length=64)
    is_valid_support_request: bool
    category: RequestCategory
    priority: Priority
    risk_level: RiskLevel
    summary: str = Field(min_length=1, max_length=2_000)
    root_cause_hypothesis: str = Field(default="", max_length=5_000)
    missing_information: list[str] = Field(default_factory=list)
    recommended_team: RecommendedTeam
    recommended_workflow_template: WorkflowTemplate
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    policy_flags: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning_trace: str = Field(default="", max_length=20_000)


class GuardianChoice(str, Enum):
    AUTO_EXECUTE = "AUTO_EXECUTE"
    REQUIRE_HUMAN_APPROVAL = "REQUIRE_HUMAN_APPROVAL"
    REQUEST_MORE_INFO = "REQUEST_MORE_INFO"
    REJECT_SAFE = "REJECT_SAFE"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GuardianDecision(ContractModel):
    """Quyết định kiểm soát quyền theo quy tắc cố định đối với các hành động AI đề xuất."""

    request_id: str = Field(min_length=1, max_length=64)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decision: GuardianChoice
    triggered_rules: list[str] = Field(default_factory=list)
    requires_human_approval: bool
    approval_status: ApprovalStatus
    approved_by: str | None = Field(default=None, max_length=200)
    block_reason: str | None = Field(default=None, max_length=2_000)
    permitted_actions: list[ProposedAction] = Field(default_factory=list)

    # Bắt buộc thời điểm đánh giá quy tắc phải gắn múi giờ rõ ràng
    @field_validator("evaluated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must include a timezone")
        return value


# --- Nhóm dữ liệu theo dõi trạng thái quy trình, chi phí và xác nhận hoàn tất ---

class WorkflowStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    REJECTED_SAFE = "REJECTED_SAFE"
    EXECUTED = "EXECUTED"
    SLA_BREACHED = "SLA_BREACHED"
    VERIFIED_RESOLVED = "VERIFIED_RESOLVED"
    FALLBACK_QUEUED = "FALLBACK_QUEUED"


class WorkflowTimestamps(ContractModel):
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class WorkflowMetrics(ContractModel):
    automation_latency_ms: float = Field(default=0.0, ge=0.0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    human_touchpoints: int = Field(default=0, ge=0)


class ExternalReferences(ContractModel):
    ticket_id: str | None = Field(default=None, max_length=200)
    ticket_url: str | None = Field(default=None, max_length=2_048)
    sla_breached: bool = False


class StateTransition(ContractModel):
    status: WorkflowStatus
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str | None = Field(default=None, max_length=2_000)


class WorkflowAuditRecord(ContractModel):
    """Bản ghi lưu trữ trạng thái quy trình, thời gian, chi phí ước tính và liên kết hệ thống ngoài."""

    request_id: str = Field(min_length=1, max_length=64)
    status: WorkflowStatus
    timestamps: WorkflowTimestamps = Field(default_factory=WorkflowTimestamps)
    metrics: WorkflowMetrics = Field(default_factory=WorkflowMetrics)
    external_refs: ExternalReferences = Field(default_factory=ExternalReferences)
    state_history: list[StateTransition] = Field(default_factory=list)


class ApprovalActionRequest(ContractModel):
    """Thông tin người duyệt gửi lên khi phê duyệt hoặc từ chối hành động."""

    reviewer_name: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=5_000)


class VerifyResolutionRequest(ContractModel):
    """Thông tin xác nhận từ con người gửi lên để chốt kết quả giải quyết yêu cầu."""

    verified_by: str = Field(min_length=1, max_length=200)
    resolution_note: str = Field(min_length=1, max_length=5_000)
