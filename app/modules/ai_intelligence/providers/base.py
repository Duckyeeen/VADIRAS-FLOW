"""Khuôn mẫu giao tiếp chung độc lập nhà cung cấp AI và cơ chế sửa định dạng JSON có giới hạn."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import AppError

TModel = TypeVar("TModel", bound=BaseModel)


class LLMOutputValidationError(AppError):
    """Lỗi khi mô hình AI trả về dữ liệu sai định dạng vượt quá số lần sửa cho phép."""

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(
            code="LLM_OUTPUT_INVALID",
            message=message,
            status_code=502,
            details=details or [],
        )


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Mô tả năng lực thực tế của một nhà cung cấp mô hình AI."""

    supports_structured_json: bool
    supports_tool_proposal: bool
    max_context_tokens: int


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Số liệu tiêu thụ và chi phí gọi AI (luôn ghi rõ là số thật, ước tính hay chưa rõ)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_source: str = "ESTIMATED"  # ACTUAL | ESTIMATED | UNKNOWN


@dataclass(frozen=True, slots=True)
class RawLLMResponse:
    """Phản hồi thô từ một lượt gọi mô hình trước khi kiểm tra cấu trúc."""

    raw_text: str
    usage: LLMUsage


@dataclass(frozen=True, slots=True)
class LLMCallResult(Generic[TModel]):
    """Kết quả sau khi đã kiểm tra cấu trúc Pydantic và thống kê số lần sửa lỗi."""

    parsed: TModel
    usage: LLMUsage
    repair_attempts: int
    status: str  # SUCCESS | REPAIRED
    latency_ms: float


class LLMProvider(Protocol):
    """Giao diện chung cho mọi nhà cung cấp AI (giả lập hoặc dịch vụ thật)."""

    provider_name: str
    model_name: str

    def get_capabilities(self) -> ProviderCapabilities:
        """Trả về năng lực hỗ trợ của nhà cung cấp AI hiện tại."""

    async def generate_raw_json(
        self,
        *,
        role_code: str,
        system_prompt: str,
        user_context: dict[str, Any],
        schema_name: str,
        repair_hint: str | None = None,
    ) -> RawLLMResponse:
        """Gọi mô hình AI sinh chuỗi JSON thô theo ngữ cảnh sạch được cung cấp."""

    async def generate_structured(
        self,
        *,
        role_code: str,
        system_prompt: str,
        user_context: dict[str, Any],
        output_model: type[TModel],
        max_repair_attempts: int = 2,
    ) -> LLMCallResult[TModel]:
        """Gọi mô hình AI và kiểm tra chặt chẽ kết quả theo khuôn mẫu Pydantic."""


async def run_structured_with_bounded_repair(
    provider: LLMProvider,
    *,
    role_code: str,
    system_prompt: str,
    user_context: dict[str, Any],
    output_model: type[TModel],
    max_repair_attempts: int = 2,
) -> LLMCallResult[TModel]:
    """Gọi AI tạo dữ liệu có cấu trúc kèm tối đa `max_repair_attempts` lần sửa lỗi định dạng.

    Thuật toán an toàn:
    1. Gọi `provider.generate_raw_json` và dùng `output_model.model_validate_json` kiểm tra ngay.
    2. Nếu dữ liệu sai định dạng JSON hoặc thiếu trường bắt buộc, gửi gợi ý lỗi cho mô hình
       thử sửa lại trong giới hạn `max_repair_attempts`.
    3. Nếu hết số lần cho phép vẫn sai, ném `LLMOutputValidationError` chứ tuyệt đối
       không tự bịa giá trị thay cho mô hình.
    """
    started = time.perf_counter()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0
    cost_source = "UNKNOWN"
    repair_hint: str | None = None
    last_error = ""

    for attempt in range(max_repair_attempts + 1):
        raw_response = await provider.generate_raw_json(
            role_code=role_code,
            system_prompt=system_prompt,
            user_context=user_context,
            schema_name=output_model.__name__,
            repair_hint=repair_hint,
        )
        total_prompt_tokens += raw_response.usage.prompt_tokens
        total_completion_tokens += raw_response.usage.completion_tokens
        total_cost += raw_response.usage.cost_usd
        cost_source = raw_response.usage.cost_source

        try:
            parsed = output_model.model_validate_json(raw_response.raw_text)
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return LLMCallResult(
                parsed=parsed,
                usage=LLMUsage(
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    cost_usd=round(total_cost, 6),
                    cost_source=cost_source,
                ),
                repair_attempts=attempt,
                status="REPAIRED" if attempt > 0 else "SUCCESS",
                latency_ms=elapsed_ms,
            )
        except ValidationError as exc:
            last_error = str(exc)
            repair_hint = (
                f"Kết quả JSON chưa đúng khuôn mẫu `{output_model.__name__}`. "
                f"Chi tiết lỗi: {last_error[:500]}"
            )

    raise LLMOutputValidationError(
        f"Đầu ra từ mô hình AI cho vai trò `{role_code}` không đạt chuẩn sau {max_repair_attempts} lần sửa.",
        details=[{"role_code": role_code, "error": last_error[:500]}],
    )
