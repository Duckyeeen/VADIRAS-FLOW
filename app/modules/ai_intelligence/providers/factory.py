"""Hàm khởi tạo nhà cung cấp AI dựa trên cấu hình môi trường hiện tại."""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError

from .base import LLMProvider
from .mock_provider import MockLLMProvider
from .openai_compat import OpenAICompatProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Chọn nhà cung cấp AI tương ứng theo biến `LLM_PROVIDER` (mặc định dùng `mock`)."""
    provider_kind = settings.llm_provider.strip().lower()
    if provider_kind == "mock":
        return MockLLMProvider(model_name=settings.llm_model or "mock-default")
    if provider_kind == "openai_compat":
        return OpenAICompatProvider(
            base_url=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise AppError(
        code="UNSUPPORTED_LLM_PROVIDER",
        message=f"Nhà cung cấp AI `{settings.llm_provider}` chưa được hỗ trợ.",
        status_code=500,
    )
