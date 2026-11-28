"""Cấu hình ghi nhật ký định dạng JSON kèm bộ lọc che giấu thông tin nhạy cảm."""

from __future__ import annotations

import logging
import re
from typing import Any

from .correlation import get_correlation_id

try:
    from pythonjsonlogger.json import JsonFormatter as _BaseJsonFormatter
except ImportError:  # Dự phòng nếu dùng phiên bản thư viện cũ hơn
    from pythonjsonlogger.jsonlogger import JsonFormatter as _BaseJsonFormatter

# Danh sách các tên trường nhạy cảm tuyệt đối không được xuất hiện nguyên văn trong nhật ký
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "plain_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "jwt_secret",
        "jwt_secret_key",
        "webhook_secret",
        "private_key",
        "api_key",
        "authorization",
        "cookie",
        "reasoning_trace",
        "chain_of_thought",
    }
)

# Biểu thức tìm kiếm nhanh cặp khóa=giá trị nhạy cảm nằm lẫn trong chuỗi thông điệp văn bản
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)\b(password|token|secret|private_key|api_key|authorization|chain_of_thought)"
    r"\s*([:=])\s*([^\s,;]+)"
)
REDACTED_VALUE = "[DA_AN]"


def redact_sensitive_data(value: Any) -> Any:
    """Đệ quy kiểm tra và che giấu toàn bộ dữ liệu nhạy cảm trước khi ghi nhật ký.

    Thuật toán gồm 3 bước:
    1. Nếu là từ điển (`dict`), kiểm tra từng tên khóa (không phân biệt hoa thường); nếu nằm
       trong danh sách nhạy cảm thì thay giá trị bằng `[DA_AN]`, ngược lại duyệt tiếp vào trong.
    2. Nếu là danh sách hoặc bộ giá trị (`list`, `tuple`), duyệt đệ quy từng phần tử.
    3. Nếu là chuỗi văn bản (`str`), dùng biểu thức chính quy thay thế phần giá trị đứng sau
       các từ khóa như `password=...` hoặc `token:...` bằng `[DA_AN]`.
    """
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            key_lower = str(key).strip().lower()
            if key_lower in SENSITIVE_KEYS or any(
                marker in key_lower for marker in ("password", "secret", "private_key", "api_key", "token")
            ):
                sanitized[key] = REDACTED_VALUE
            else:
                sanitized[key] = redact_sensitive_data(item)
        return sanitized

    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)

    if isinstance(value, str):
        return _SENSITIVE_TEXT_PATTERN.sub(rf"\1\2{REDACTED_VALUE}", value)

    return value


class SensitiveDataRedactionFilter(logging.Filter):
    """Bộ lọc nhật ký tự động gắn mã theo dõi và che thông tin bí mật trên mọi bản ghi."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Bước 1: Gắn mã theo dõi của lượt xử lý hiện tại vào bản ghi nhật ký
        if not hasattr(record, "correlation_id") or not getattr(record, "correlation_id"):
            record.correlation_id = get_correlation_id() or "-"

        # Bước 2: Che thông tin nhạy cảm trong nội dung thông điệp chính
        if isinstance(record.msg, dict):
            record.msg = redact_sensitive_data(record.msg)
        elif isinstance(record.msg, str):
            record.msg = redact_sensitive_data(record.msg)

        # Bước 3: Che thông tin nhạy cảm trong các tham số định dạng đi kèm
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_sensitive_data(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_sensitive_data(arg) for arg in record.args)

        # Bước 4: Che thông tin nhạy cảm trong các trường mở rộng gắn trên bản ghi
        for attr_name in list(vars(record).keys()):
            if attr_name in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
            }:
                continue
            attr_lower = attr_name.lower()
            if attr_lower in SENSITIVE_KEYS or any(
                marker in attr_lower for marker in ("password", "secret", "private_key", "api_key", "token")
            ):
                setattr(record, attr_name, REDACTED_VALUE)
            else:
                setattr(record, attr_name, redact_sensitive_data(getattr(record, attr_name)))

        return True


def configure_logging(log_level: str = "INFO") -> None:
    """Thiết lập hệ thống ghi nhật ký định dạng JSON thống nhất cho toàn ứng dụng.

    Đầu vào: `log_level` là mức ghi nhật ký (ví dụ `INFO`, `DEBUG`, `WARNING`).
    Đầu ra: không trả về giá trị; cấu hình trực tiếp bộ ghi gốc của Python.
    """
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    formatter = _BaseJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(correlation_id)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    redaction_filter = SensitiveDataRedactionFilter()

    handler = logging.StreamHandler()
    handler.setLevel(numeric_level)
    handler.setFormatter(formatter)
    handler.addFilter(redaction_filter)

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
