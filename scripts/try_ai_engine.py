"""Quick local test for ai_engine.analyze_request_with_usage."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.ai_engine import AIEngineError, analyze_request_with_usage
from app.schemas import (
    CustomerInfo, CustomerTier, InboundRequest, PreprocessedContext,
    ProductInfo, RetrievedDocument, SimilarTicket, SourceChannel,
)

kb = json.loads((ROOT / "data/knowledge_base.json").read_text(encoding="utf-8"))
tk = json.loads((ROOT / "data/historical_tickets.json").read_text(encoding="utf-8"))
doc = next(d for d in kb if d["doc_id"] == "KB-AUTH-001")
ticket = next(t for t in tk if t["ticket_id"] == "HT-012")

description = (
    "Mình đã đổi mật khẩu hôm qua nhưng giờ đăng nhập báo lỗi 401, "
    "thử nhiều lần vẫn không vào được. Liên hệ: [EMAIL]"
)

request = InboundRequest(
    source_channel=SourceChannel.WEB_FORM,
    customer=CustomerInfo(
        customer_id="C-TEST-01",
        organization="Cong ty Demo",
        contact_email="khach01@example.com",
        tier=CustomerTier.STANDARD,
    ),
    product=ProductInfo(
        name="DemoApp", module="Auth", version="2.4.1", environment="production"
    ),
    subject="Không đăng nhập được sau khi đổi mật khẩu",
    description=description,
    requested_action="Xin hỗ trợ khôi phục đăng nhập",
)

context = PreprocessedContext(
    request_id=request.request_id,
    idempotency_hash=hashlib.sha256(description.encode()).hexdigest(),
    validation_status="PASSED",
    sanitized_text=f"{request.subject}. {description}",
    retrieved_kb=[
        RetrievedDocument(
            document_id=doc["doc_id"], title=doc["title"],
            content=doc["content"], score=1.0,
        )
    ],
    similar_tickets=[
        SimilarTicket(
            ticket_id=ticket["ticket_id"], title=ticket["title"],
            resolution=ticket["resolution"], score=0.8,
        )
    ],
)

try:
    output, usage = analyze_request_with_usage(request, context)
    print(output.model_dump_json(indent=2))
    print("\n--- USAGE ---")
    print(usage)
except AIEngineError as exc:
    print("AIEngineError:", exc)