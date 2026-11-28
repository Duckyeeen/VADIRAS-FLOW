"""Bộ làm sạch dữ liệu đầu vào: ẩn thông tin cá nhân, phát hiện cài cắm lệnh và tạo mã chống trùng."""

from __future__ import annotations

import hashlib
import re

from .models import RequestType

# Các mẫu nhận diện thông tin cá nhân và khóa bí mật cần che trước khi đưa vào AI
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]?\d{3,4}(?!\d)")
_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:bearer\s+[A-Za-z0-9._-]+|sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{16,}|ghs_[A-Za-z0-9]{16,})"
)

# Danh sách dấu hiệu nghi vấn cài cắm câu lệnh điều khiển AI trái phép
_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("IGNORE_INSTRUCTIONS", re.compile(r"(?i)\bignore\s+(all\s+)?(previous|prior)\s+instructions\b")),
    ("BYPASS_POLICY", re.compile(r"(?i)\b(bypass|disable|override)\s+(the\s+)?(policy|guardian|security|approval)\b")),
    ("PRIVILEGE_ESCALATION_TEXT", re.compile(r"(?i)\b(grant|give)\s+(me\s+)?admin(\s+role|\s+access)?\b")),
    ("SYSTEM_PROMPT_EXFIL", re.compile(r"(?i)\b(reveal|print|dump)\s+(your\s+)?system\s+prompt\b")),
)

# Ánh xạ gợi ý phòng ban mặc định theo 5 loại yêu cầu chuẩn
_DEFAULT_DEPARTMENT_BY_TYPE: dict[str, str] = {
    RequestType.INCIDENT.value: "ENGINEERING",
    RequestType.CHANGE.value: "DEVOPS",
    RequestType.SERVICE_REQUEST.value: "SUPPORT",
    RequestType.ONBOARDING.value: "PRODUCT",
    RequestType.INTERNAL_TASK.value: "MANAGEMENT",
}


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Ẩn thông tin cá nhân nhạy cảm và khóa bí mật trong văn bản đầu vào.

    Thuật toán gồm 4 bước thay thế tuần tự:
    1. Che chuỗi giống khóa API hoặc thẻ Bearer thành `[KHOA_BI_MAT_DA_AN]`.
    2. Che chuỗi 13–19 chữ số giống số thẻ thanh toán thành `[THE_DA_AN]`.
    3. Che địa chỉ email thành `[EMAIL_DA_AN]`.
    4. Che số điện thoại thành `[SDT_DA_AN]`.
    Đầu ra: bộ `(văn_bản_đã_che, danh_sách_loại_đã_che)` (không bao giờ lưu giá trị thô).
    """
    redactions: list[str] = []
    sanitized = text

    if _SECRET_PATTERN.search(sanitized):
        sanitized = _SECRET_PATTERN.sub("[KHOA_BI_MAT_DA_AN]", sanitized)
        redactions.append("SECRET_OR_TOKEN")

    if _CARD_PATTERN.search(sanitized):
        sanitized = _CARD_PATTERN.sub("[THE_DA_AN]", sanitized)
        redactions.append("PAYMENT_CARD")

    if _EMAIL_PATTERN.search(sanitized):
        sanitized = _EMAIL_PATTERN.sub("[EMAIL_DA_AN]", sanitized)
        redactions.append("EMAIL")

    if _PHONE_PATTERN.search(sanitized):
        sanitized = _PHONE_PATTERN.sub("[SDT_DA_AN]", sanitized)
        redactions.append("PHONE")

    return sanitized, redactions


def detect_prompt_injection_signals(text: str) -> list[str]:
    """Quét văn bản đầu vào để phát hiện các mẫu câu nghi vấn cài cắm lệnh cho AI.

    Đầu vào: văn bản gốc do người gửi hoặc bên ngoài cung cấp.
    Đầu ra: danh sách mã cờ cảnh báo (trả về danh sách rỗng nếu không thấy dấu hiệu bất thường).
    """
    flags: list[str] = []
    for flag_code, pattern in _INJECTION_RULES:
        if pattern.search(text):
            flags.append(flag_code)
    return flags


def compute_content_hash(
    *,
    organization_id: str,
    requester_membership_id: str,
    request_type: str,
    title: str,
    description: str,
) -> str:
    """Tính mã băm SHA-256 (64 ký tự hex) đại diện cho nội dung cốt lõi của yêu cầu.

    Dùng để kiểm tra tính trùng lặp nội dung và làm dấu vân tay cố định của bản gốc.
    """
    normalized = "|".join(
        [
            organization_id.strip(),
            requester_membership_id.strip(),
            request_type.strip().upper(),
            title.strip(),
            description.strip(),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def suggest_default_department_code(request_type: str) -> str:
    """Gợi ý mã phòng ban phụ trách mặc định dựa trên loại yêu cầu.

    Mặc định trả về `SUPPORT` nếu loại yêu cầu mở rộng chưa có ánh xạ riêng.
    """
    return _DEFAULT_DEPARTMENT_BY_TYPE.get(request_type.strip().upper(), "SUPPORT")
