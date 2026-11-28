"""Kiểm thử đơn vị cho lớp bảo mật (Argon2id, JWT, HMAC) và bộ lọc che thông tin nhạy cảm."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.logging import REDACTED_VALUE, SensitiveDataRedactionFilter, redact_sensitive_data
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_hmac_sha256,
    verify_password,
)


def _test_settings() -> Settings:
    return Settings(
        app_env="test",
        jwt_secret_key="khoa_bi_mat_kiem_thu_don_vi_toi_thieu_32_ky_tu",
        jwt_issuer="vadiras-flow",
        jwt_audience="vadiras-flow-api",
    )


def test_argon2id_password_hashing_and_verification() -> None:
    """Đảm bảo mật khẩu được băm bằng Argon2id, có muối ngẫu nhiên và đối chiếu chính xác."""
    plain = "MatKhauBaoMat#123"
    hashed_1 = hash_password(plain)
    hashed_2 = hash_password(plain)

    assert hashed_1.startswith("$argon2id$")
    assert hashed_1 != hashed_2
    assert verify_password(plain, hashed_1) is True
    assert verify_password("SaiMatKhau", hashed_1) is False
    assert verify_password(plain, "chuoi_bam_hong") is False


def test_jwt_access_and_refresh_token_validation() -> None:
    """Kiểm tra tạo, giải mã, phát hiện hết hạn, sai khóa và dùng nhầm loại thẻ JWT."""
    settings = _test_settings()
    access_token, jti, _ = create_access_token(
        user_id="user-1",
        organization_id="org-1",
        membership_id="mem-1",
        user_kind="EMPLOYEE",
        settings=settings,
    )
    decoded = decode_token(access_token, expected_type="access", settings=settings)
    assert decoded["sub"] == "user-1"
    assert decoded["org_id"] == "org-1"
    assert decoded["mid"] == "mem-1"
    assert decoded["jti"] == jti
    assert "password" not in decoded
    assert "permissions" not in decoded

    # Không cho phép dùng thẻ làm mới (refresh) thay cho thẻ truy cập (access)
    refresh_token, _, _ = create_refresh_token(
        user_id="user-1",
        organization_id="org-1",
        membership_id="mem-1",
        settings=settings,
    )
    with pytest.raises(AuthenticationError) as exc_type:
        decode_token(refresh_token, expected_type="access", settings=settings)
    assert exc_type.value.code == "INVALID_TOKEN_TYPE"

    # Kiểm tra thẻ đã hết hạn
    expired_token, _, _ = create_access_token(
        user_id="user-1",
        organization_id="org-1",
        membership_id="mem-1",
        user_kind="EMPLOYEE",
        settings=settings,
        expires_delta=timedelta(seconds=-5),
    )
    with pytest.raises(AuthenticationError) as exc_exp:
        decode_token(expired_token, expected_type="access", settings=settings)
    assert exc_exp.value.code == "TOKEN_EXPIRED"

    # Kiểm tra thẻ ký bằng khóa giả mạo
    forged = jwt.encode(
        {
            "sub": "user-1",
            "org_id": "org-1",
            "mid": "mem-1",
            "type": "access",
            "jti": "jti-1",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "exp": 9999999999,
        },
        "khoa_gia_mao_khong_hop_le_1234567890",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError) as exc_sig:
        decode_token(forged, expected_type="access", settings=settings)
    assert exc_sig.value.code == "INVALID_TOKEN"


def test_hmac_sha256_verification() -> None:
    """Đảm bảo kiểm tra chữ ký webhook bằng phép so sánh hằng thời gian chính xác."""
    raw_body = b'{"event":"issues","action":"opened"}'
    secret = "bi_mat_webhook_github"
    valid_sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    assert verify_hmac_sha256(raw_body, valid_sig, secret) is True
    assert verify_hmac_sha256(raw_body, valid_sig + "a", secret) is False
    assert verify_hmac_sha256(raw_body, "md5=1234", secret) is False
    assert verify_hmac_sha256(raw_body, None, secret) is False


def test_sensitive_data_redaction_in_logs() -> None:
    """Đảm bảo mật khẩu, thẻ JWT, khóa API và suy nghĩ ẩn bị che trước khi ghi nhật ký."""
    payload = {
        "email": "user@vadiras.local",
        "password": "secret_password_123",
        "nested": {
            "access_token": "eyJhbGci...",
            "private_key": "BEGIN RSA PRIVATE KEY",
            "chain_of_thought": "suy nghi noi bo",
            "safe_note": "ok",
        },
    }
    sanitized = redact_sensitive_data(payload)
    assert sanitized["email"] == "user@vadiras.local"
    assert sanitized["password"] == REDACTED_VALUE
    assert sanitized["nested"]["access_token"] == REDACTED_VALUE
    assert sanitized["nested"]["private_key"] == REDACTED_VALUE
    assert sanitized["nested"]["chain_of_thought"] == REDACTED_VALUE
    assert sanitized["nested"]["safe_note"] == "ok"

    record = logging.LogRecord(
        name="vadiras.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Đăng nhập thất bại với password=matkhau_tho và api_key:khoa_bi_mat",
        args=(),
        exc_info=None,
    )
    record.token = "token_khong_duoc_lo"
    log_filter = SensitiveDataRedactionFilter()
    assert log_filter.filter(record) is True
    assert "matkhau_tho" not in str(record.msg)
    assert "khoa_bi_mat" not in str(record.msg)
    assert REDACTED_VALUE in str(record.msg)
    assert getattr(record, "token") == REDACTED_VALUE
