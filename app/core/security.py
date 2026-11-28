"""Các hàm bảo mật cốt lõi: băm mật khẩu Argon2id, tạo/kiểm tra thẻ JWT và chữ ký HMAC."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import Settings
from .errors import AuthenticationError

# Khởi tạo bộ băm mật khẩu dùng thuật toán Argon2id theo khuyến nghị bảo mật hiện hành
_password_hasher = PasswordHasher(type=Type.ID)


def hash_password(plain_password: str) -> str:
    """Chuyển mật khẩu dạng văn bản thuần sang chuỗi băm an toàn bằng thuật toán Argon2id.

    Đầu vào: `plain_password` không được rỗng.
    Đầu ra: chuỗi băm Argon2id có chứa muối ngẫu nhiên riêng cho mỗi lần gọi.
    """
    if not plain_password:
        raise ValueError("Mật khẩu không được để trống.")
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Đối chiếu mật khẩu người dùng nhập với chuỗi băm Argon2id đã lưu trong cơ sở dữ liệu.

    Đầu vào: `plain_password` (mật khẩu thô) và `password_hash` (chuỗi băm lưu trữ).
    Đầu ra: `True` nếu khớp hoàn toàn, `False` nếu sai hoặc chuỗi băm hỏng định dạng.
    """
    if not plain_password or not password_hash:
        return False
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_token(raw_token: str) -> str:
    """Tính mã băm SHA-256 của thẻ làm mới trước khi lưu xuống cơ sở dữ liệu.

    Việc chỉ lưu mã băm giúp ngay cả khi dữ liệu bảng phiên bị lộ cũng không thể
    dùng trực tiếp để xin cấp lại thẻ truy cập.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(
    *,
    user_id: str,
    organization_id: str,
    membership_id: str,
    user_kind: str,
    settings: Settings,
    expires_delta: timedelta | None = None,
) -> tuple[str, str, datetime]:
    """Tạo thẻ truy cập JWT ngắn hạn cho người dùng đã xác thực.

    Quy ước bảo mật:
    1. Chỉ đưa vào các mã định danh tối thiểu (`sub`, `org_id`, `mid`, `kind`, `type`, `jti`),
       tuyệt đối không nhúng mật khẩu hay danh sách quyền cũ kéo dài.
    2. Gắn thời điểm phát hành (`iat`), thời điểm hết hạn (`exp`), nơi phát hành (`iss`)
       và đối tượng sử dụng (`aud`).
    Đầu ra: bộ 3 `(chuỗi_token, mã_phiên_jti, thời_điểm_hết_hạn)`.
    """
    now = datetime.now(timezone.utc)
    expire_at = now + (expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes))
    jti = str(uuid4())
    payload: dict[str, Any] = {
        "sub": user_id,
        "org_id": organization_id,
        "mid": membership_id,
        "kind": user_kind,
        "type": "access",
        "jti": jti,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int(expire_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti, expire_at


def create_refresh_token(
    *,
    user_id: str,
    organization_id: str,
    membership_id: str,
    settings: Settings,
    expires_delta: timedelta | None = None,
) -> tuple[str, str, datetime]:
    """Tạo thẻ làm mới JWT dùng một lần để xoay vòng phiên đăng nhập an toàn.

    Đầu ra: bộ 3 `(chuỗi_refresh_token, mã_phiên_jti, thời_điểm_hết_hạn)`.
    """
    now = datetime.now(timezone.utc)
    expire_at = now + (expires_delta or timedelta(days=settings.jwt_refresh_token_expire_days))
    jti = str(uuid4())
    payload: dict[str, Any] = {
        "sub": user_id,
        "org_id": organization_id,
        "mid": membership_id,
        "type": "refresh",
        "jti": jti,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int(expire_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti, expire_at


def decode_token(token: str, *, expected_type: str, settings: Settings) -> dict[str, Any]:
    """Giải mã và kiểm tra toàn diện chữ ký, thời hạn, nơi phát hành và loại thẻ JWT.

    1. Kiểm tra chữ ký số bằng khóa bí mật và thuật toán đã cấu hình.
    2. Bắt buộc có đủ các trường `sub`, `org_id`, `mid`, `jti`, `exp`, `iss`, `aud`.
    3. Đối chiếu `type` phải khớp đúng `expected_type` (`access` hoặc `refresh`) để
       ngăn hành vi lấy thẻ làm mới gọi trực tiếp vào các tuyến API nghiệp vụ.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "org_id", "mid", "jti", "exp", "iss", "aud", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Phiên đăng nhập đã hết hạn.", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Thẻ xác thực không hợp lệ.", code="INVALID_TOKEN") from exc

    if payload.get("type") != expected_type:
        raise AuthenticationError("Loại thẻ xác thực không phù hợp.", code="INVALID_TOKEN_TYPE")
    return payload


def verify_hmac_sha256(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Kiểm tra chữ ký HMAC-SHA256 của thông điệp gửi đến (ví dụ Webhook GitHub).

    Sử dụng phép so sánh có thời gian thực thi cố định (`hmac.compare_digest`) để tránh
    lỗ hổng suy đoán từng ký tự theo thời gian phản hồi.
    """
    if not signature_header or not secret:
        return False
    expected_prefix = "sha256="
    if not signature_header.startswith(expected_prefix):
        return False
    expected_digest = expected_prefix + hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_digest, signature_header)
