"""Structured AI analysis via OpenAI Structured Outputs (workflow step 3)."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import openai
from openai import OpenAI
from pydantic import ValidationError

from .schemas import AIAnalysisOutput, InboundRequest, PreprocessedContext

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SCHEMA_FILE = "ai_output_schema.json"

MAX_RETRIES = 2  # 1 lần gọi đầu + tối đa 2 lần thử lại
BACKOFF_BASE_SECONDS = 1.0  # chờ 1s, rồi 2s giữa các lần thử


class AIEngineError(Exception):
    """AI analysis failed after all retries.

    The orchestrator catches this and calls ``push_dead_letter``.
    """


@dataclass(frozen=True)
class AIUsage:
    """Usage numbers the orchestrator stores in ``WorkflowMetrics``."""

    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    retry_count: int


# Lỗi chờ rồi thử lại có thể thành công.
_RETRYABLE = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
    json.JSONDecodeError,  # AI trả JSON hỏng hoặc bị cắt cụt
    ValidationError,  # AI trả JSON không khớp AIAnalysisOutput
)

# Lỗi thử lại cũng vô ích (sai key, sai model, schema bị từ chối...).
_NON_RETRYABLE = (
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.BadRequestError,
    openai.NotFoundError,
)

_QUOTA_ERROR_CODES = {
    "insufficient_quota",
    "credit_balance_exhausted",
    "organization_spend_limit_exceeded",
    "project_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
}


def _model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _timeout_seconds() -> float:
    return float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))


def _prompt_file() -> str:
    return os.getenv("PROMPT_FILE", "system_prompt_v1.txt")


@lru_cache(maxsize=None)
def _read_text(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _load_system_prompt() -> str:
    return _read_text(_prompt_file())


def _load_response_format() -> dict:
    # ai_output_schema.json có dạng {"name", "strict", "schema"},
    # đúng với trường "json_schema" mà OpenAI yêu cầu.
    return {"type": "json_schema", "json_schema": json.loads(_read_text(_SCHEMA_FILE))}


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AIEngineError("OPENAI_API_KEY is not set")
    # max_retries=0: tự retry bên dưới để kiểm soát đúng "≤ 2 lần".
    return OpenAI(api_key=api_key, timeout=_timeout_seconds(), max_retries=0)


def _build_user_prompt(request: InboundRequest, context: PreprocessedContext) -> str:
    """Build the user message from MASKED text and non-PII metadata only.

    Never use request.description / request.subject / customer.contact_email
    here: they are raw and may contain PII. Only context.sanitized_text is safe.
    """
    kb_block = "\n".join(
        f"[{d.document_id}] {d.title}: {d.content}" for d in context.retrieved_kb
    ) or "(không có tài liệu liên quan)"

    ticket_block = "\n".join(
        f"[{t.ticket_id}] {t.title}. Cách xử lý: {t.resolution or 'không có'}"
        for t in context.similar_tickets
    ) or "(không có ticket tương tự)"

    missing = ", ".join(context.missing_mandatory_fields) or "không có"

    return (
        f"request_id: {context.request_id}\n"
        f"Kênh gửi: {request.source_channel.value}\n"
        f"Gói khách hàng: {request.customer.tier.value}\n"
        f"Sản phẩm: {request.product.name} | Module: {request.product.module} | "
        f"Phiên bản: {request.product.version} | Môi trường: {request.product.environment}\n"
        f"Trường bắt buộc còn thiếu (do bộ kiểm tra phát hiện): {missing}\n\n"
        f"YÊU CẦU CỦA KHÁCH (đã che thông tin cá nhân):\n{context.sanitized_text}\n\n"
        f"TÀI LIỆU THAM KHẢO:\n{kb_block}\n\n"
        f"TICKET THAM KHẢO:\n{ticket_block}\n"
    )


def _parse_output(raw: str, request_id: str) -> AIAnalysisOutput:
    data = json.loads(raw)
    data["request_id"] = request_id  # luôn dùng request_id thật, không tin AI
    score = data.get("confidence_score")
    if isinstance(score, (int, float)):
        # Strict schema không giới hạn được 0..1 nên kẹp lại ở đây.
        data["confidence_score"] = min(1.0, max(0.0, float(score)))
    return AIAnalysisOutput.model_validate(data)


def analyze_request_with_usage(
    request: InboundRequest,
    context: PreprocessedContext,
) -> tuple[AIAnalysisOutput, AIUsage]:
    """Call OpenAI and return the analysis plus token/latency/retry numbers.

    Retries up to ``MAX_RETRIES`` times (exponential backoff) on timeouts,
    network errors, rate limits, 5xx and malformed output. Raises
    ``AIEngineError`` when all attempts fail or the error cannot be retried.
    """
    client = _get_client()
    messages = [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": _build_user_prompt(request, context)},
    ]
    response_format = _load_response_format()

    started = time.perf_counter()
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=_model(),
                messages=messages,
                response_format=response_format,
            )
            message = response.choices[0].message
            if message.refusal:
                raise AIEngineError(f"Model refused the request: {message.refusal}")

            output = _parse_output(message.content or "", context.request_id)
            usage = AIUsage(
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                latency_ms=(time.perf_counter() - started) * 1000,
                retry_count=attempt,
            )
            return output, usage

        except AIEngineError:
            raise
        except _NON_RETRYABLE as exc:
            raise AIEngineError(f"Non-retryable OpenAI error: {type(exc).__name__}") from exc
        except _RETRYABLE as exc:
            error_code = getattr(exc, "code", None)
            status_code = getattr(exc, "status_code", None)

            # Credits and spend caps need an account-side change; retries cannot fix them.
            if isinstance(exc, openai.RateLimitError) and error_code in _QUOTA_ERROR_CODES:
                raise AIEngineError(
                    f"OpenAI quota or spend limit reached (code={error_code})"
                ) from exc

            last_error = exc
            logger.warning(
                "AI attempt %d/%d failed: %s (status=%s, code=%s)",
                attempt + 1,
                MAX_RETRIES + 1,
                type(exc).__name__,
                status_code,
                error_code,
            )
            if attempt < MAX_RETRIES:
                wait_seconds = BACKOFF_BASE_SECONDS * (2**attempt)
                response = getattr(exc, "response", None)
                headers = getattr(response, "headers", {})
                retry_after = headers.get("retry-after") if headers else None
                if retry_after:
                    try:
                        wait_seconds = max(wait_seconds, float(retry_after))
                    except (TypeError, ValueError):
                        pass
                time.sleep(wait_seconds)
        except openai.OpenAIError as exc:
            raise AIEngineError(f"OpenAI error: {type(exc).__name__}") from exc

    raise AIEngineError(
        f"AI analysis failed after {MAX_RETRIES + 1} attempts: "
        f"{type(last_error).__name__} (code={getattr(last_error, 'code', None)})"
    ) from last_error


def analyze_request(
    request: InboundRequest,
    context: PreprocessedContext,
) -> AIAnalysisOutput:
    """Analyze an ``InboundRequest`` with its ``PreprocessedContext``.

    Returns the validated structured classification, risk, routing, and proposed
    actions as ``AIAnalysisOutput``. Raises ``AIEngineError`` after 2 failed retries.
    """
    output, _ = analyze_request_with_usage(request, context)
    return output
