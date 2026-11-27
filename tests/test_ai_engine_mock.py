"""Offline tests for app/ai_engine.py: no API key, no network, no cost."""
import hashlib
import json
import os
import sys
import types
from pathlib import Path

import httpx
import openai

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ai_engine
from app.ai_engine import AIEngineError, analyze_request_with_usage
from app.schemas import (
    CustomerInfo, CustomerTier, InboundRequest, PreprocessedContext,
    ProductInfo, RetrievedDocument, SimilarTicket, SourceChannel,
)
REAL_GET_CLIENT = ai_engine._get_client  # lưu hàm thật trước khi test thay bằng hàm giả
ai_engine.time.sleep = lambda s: None  # không chờ thật khi retry
ai_engine.time.sleep = lambda s: None  # không chờ thật khi retry

# ---------- dữ liệu mẫu ----------
RAW_EMAIL = "khach01@example.com"
DESC = "Đổi mật khẩu xong đăng nhập báo lỗi 401. Liên hệ: [EMAIL]"

request = InboundRequest(
    source_channel=SourceChannel.WEB_FORM,
    customer=CustomerInfo(customer_id="C-1", organization="Cty Demo",
                          contact_email=RAW_EMAIL, tier=CustomerTier.STANDARD),
    product=ProductInfo(name="DemoApp", module="Auth", version="2.4.1",
                        environment="production"),
    subject="Không đăng nhập được",
    description=DESC,
    requested_action="Xin hỗ trợ",
)
context = PreprocessedContext(
    request_id=request.request_id,
    idempotency_hash=hashlib.sha256(DESC.encode()).hexdigest(),
    validation_status="PASSED",
    sanitized_text=f"{request.subject}. {DESC}",
    retrieved_kb=[RetrievedDocument(document_id="KB-AUTH-001", title="Doi mat khau",
                                    content="Thu hoi token", score=1.0)],
    similar_tickets=[SimilarTicket(ticket_id="HT-012", title="Bi dang xuat",
                                   resolution="Dong bo gio", score=0.8)],
)

# ---------- phản hồi OpenAI giả ----------
def fake_output(**override):
    data = {
        "request_id": "AI-TU-BIA",  # cố tình sai, code phải ghi đè
        "is_valid_support_request": True,
        "category": "account_access",
        "priority": "P3_MEDIUM",
        "risk_level": "LOW",
        "summary": "Khách không đăng nhập được sau khi đổi mật khẩu.",
        "root_cause_hypothesis": "Token cũ chưa bị thu hồi.",
        "missing_information": [],
        "recommended_team": "IAM-Security",
        "recommended_workflow_template": "WF_STANDARD_BUG_TRIAGE",
        "proposed_actions": [],
        "policy_flags": ["none"],
        "confidence_score": 1.7,  # cố tình vượt 1, code phải kẹp về 1.0
        "reasoning_trace": "Khớp KB-AUTH-001.",
    }
    data.update(override)
    return data


def fake_response(content, refusal=None):
    message = types.SimpleNamespace(content=content, refusal=refusal)
    usage = types.SimpleNamespace(prompt_tokens=500, completion_tokens=120)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)],
                                 usage=usage)


class FakeClient:
    """Mỗi phần tử trong `script` là một Exception (sẽ bị ném) hoặc một response."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def use_client(client):
    ai_engine._get_client = lambda: client
    return client


def timeout_error():
    return openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))


# ---------- các ca kiểm tra ----------
def test_success():
    c = use_client(FakeClient([fake_response(json.dumps(fake_output()))]))
    out, usage = analyze_request_with_usage(request, context)
    assert out.category.value == "account_access"
    assert out.request_id == request.request_id, "phải ghi đè request_id do AI trả"
    assert out.confidence_score == 1.0, "phải kẹp điểm về 1.0"
    assert usage.prompt_tokens == 500 and usage.completion_tokens == 120
    assert usage.retry_count == 0 and len(c.calls) == 1


def test_retry_then_success():
    c = use_client(FakeClient([timeout_error(),
                               fake_response(json.dumps(fake_output()))]))
    out, usage = analyze_request_with_usage(request, context)
    assert usage.retry_count == 1 and len(c.calls) == 2


def test_all_attempts_fail():
    c = use_client(FakeClient([timeout_error(), timeout_error(), timeout_error()]))
    try:
        analyze_request_with_usage(request, context)
    except AIEngineError:
        assert len(c.calls) == 3, "1 lần đầu + 2 lần thử lại"
        return
    raise AssertionError("phải ném AIEngineError sau 3 lần thất bại")


def test_malformed_json_then_success():
    c = use_client(FakeClient([fake_response('{"hong": '),
                               fake_response(json.dumps(fake_output()))]))
    _, usage = analyze_request_with_usage(request, context)
    assert usage.retry_count == 1 and len(c.calls) == 2


def test_invalid_enum_is_rejected_after_retries():
    bad = json.dumps(fake_output(category="khong_ton_tai"))
    c = use_client(FakeClient([fake_response(bad)] * 3))
    try:
        analyze_request_with_usage(request, context)
    except AIEngineError:
        assert len(c.calls) == 3
        return
    raise AssertionError("giá trị enum sai phải bị Pydantic từ chối")


def test_model_refusal():
    use_client(FakeClient([fake_response(None, refusal="Toi tu choi")]))
    try:
        analyze_request_with_usage(request, context)
    except AIEngineError as exc:
        assert "refused" in str(exc)
        return
    raise AssertionError("refusal phải thành AIEngineError")


def test_prompt_has_no_raw_pii():
    c = use_client(FakeClient([fake_response(json.dumps(fake_output()))]))
    analyze_request_with_usage(request, context)
    user_msg = c.calls[0]["messages"][1]["content"]
    assert RAW_EMAIL not in user_msg, "không được gửi email thật cho AI"
    assert "KB-AUTH-001" in user_msg and "HT-012" in user_msg
    assert c.calls[0]["response_format"]["json_schema"]["strict"] is True


def test_missing_api_key():
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        REAL_GET_CLIENT()
    except AIEngineError as exc:
        assert "OPENAI_API_KEY" in str(exc)
        return
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved
    raise AssertionError("thiếu key phải ném AIEngineError")

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} test đạt")
    sys.exit(1 if failed else 0)