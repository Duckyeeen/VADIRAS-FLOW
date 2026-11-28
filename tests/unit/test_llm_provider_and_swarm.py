"""Kiểm thử đơn vị cho lớp giao tiếp AI, sửa lỗi định dạng có giới hạn và Điều phối viên trưởng."""

from __future__ import annotations

import pytest

from app.adapters.ai_engine import analyze_request
from app.modules.ai_intelligence.prompts.registry import PromptRegistry
from app.modules.ai_intelligence.providers.base import LLMOutputValidationError
from app.modules.ai_intelligence.providers.mock_provider import MockLLMProvider
from app.modules.ai_intelligence.swarm.aggregator import aggregate_swarm_outputs
from app.modules.ai_intelligence.swarm.schemas import (
    CandidateWorkflowEdge,
    CandidateWorkflowNode,
    CandidateWorkflowProposal,
    CriticReview,
    SpecialistFinding,
)
from app.modules.ai_intelligence.swarm.supervisor import SwarmSupervisor
from app.adapters.schemas import CustomerInfo, CustomerTier, InboundRequest, PreprocessedContext, ProductInfo, SourceChannel


@pytest.mark.asyncio
async def test_bounded_json_repair_succeeds_and_fails_safely_when_exceeded() -> None:
    """Kiểm tra cơ chế sửa định dạng JSON có giới hạn và ném lỗi an toàn khi vượt ngưỡng."""
    registry = PromptRegistry()
    spec = registry.get_prompt("request_analyst")
    ctx = {
        "request_id": "req-1",
        "request_type": "INCIDENT",
        "title": "Lỗi 502 ở cổng báo cáo",
        "sanitized_description": "Dịch vụ báo cáo trả lỗi 502 từ sáng nay khi xuất PDF.",
        "injection_flags": [],
    }

    # Trường hợp 1: Sai định dạng ở lần gọi đầu, tự sửa thành công ở lần thử lại thứ nhất
    repairable_provider = MockLLMProvider(failure_mode="malformed_once")
    repaired_res = await repairable_provider.generate_structured(
        role_code="request_analyst",
        system_prompt=spec.system_prompt,
        user_context=ctx,
        output_model=SpecialistFinding,
        max_repair_attempts=2,
    )
    assert repaired_res.status == "REPAIRED"
    assert repaired_res.repair_attempts == 1
    assert repaired_res.parsed.role_code == "request_analyst"

    # Trường hợp 2: Luôn sai định dạng -> phải dừng an toàn sau tối đa 2 lần sửa, không bịa trường
    broken_provider = MockLLMProvider(failure_mode="always_malformed")
    with pytest.raises(LLMOutputValidationError):
        await broken_provider.generate_structured(
            role_code="request_analyst",
            system_prompt=spec.system_prompt,
            user_context=ctx,
            output_model=SpecialistFinding,
            max_repair_attempts=2,
        )


@pytest.mark.asyncio
async def test_swarm_respects_concurrency_and_review_round_bounds() -> None:
    """Đảm bảo nhóm trợ lý AI tôn trọng giới hạn chạy song song và số vòng phản biện tối đa."""
    registry = PromptRegistry()

    # Giới hạn tối đa 2 chuyên viên chạy cùng lúc dù có 4 chuyên viên độc lập
    provider_bounded = MockLLMProvider(
        simulated_delay_seconds=0.02,
        always_reject_critic=True,
    )
    supervisor = SwarmSupervisor(
        provider=provider_bounded,
        prompt_registry=registry,
        max_concurrent=2,
        max_review_rounds=2,
    )
    result = await supervisor.run_analysis(
        context_snapshot={
            "request_id": "req-bounds",
            "request_type": "CHANGE",
            "title": "Thay đổi cấu hình kết nối",
            "sanitized_description": "Tăng giới hạn kết nối cho dịch vụ thanh toán ở staging.",
            "injection_flags": [],
        }
    )

    assert provider_bounded.peak_concurrency <= 2
    assert result.rounds_executed == 2
    # Vì Phản biện không duyệt sau 2 vòng, kết luận an toàn phải là NO_SAFE_PLAN
    assert result.status == "NO_SAFE_PLAN"

    # Nếu Phản biện chỉ từ chối ở vòng 1 và đồng ý ở vòng 2 -> dừng đúng ở vòng 2 với COMPLETED
    provider_round2_ok = MockLLMProvider(force_critic_reject_round_1=True)
    supervisor_ok = SwarmSupervisor(
        provider=provider_round2_ok,
        prompt_registry=registry,
        max_concurrent=4,
        max_review_rounds=2,
    )
    ok_res = await supervisor_ok.run_analysis(
        context_snapshot={
            "request_id": "req-round2",
            "request_type": "SERVICE_REQUEST",
            "title": "Mở quyền truy cập bảng điều khiển",
            "sanitized_description": "Cấp quyền đọc báo cáo cho nhân viên mới thuộc hỗ trợ.",
            "injection_flags": [],
        }
    )
    assert ok_res.rounds_executed == 2
    assert ok_res.status == "COMPLETED"


def test_conflict_resolution_hard_blocker_overrides_majority_and_no_cot() -> None:
    """Xác nhận cảnh báo bảo mật thắng biểu quyết số đông và không lưu suy nghĩ ẩn."""
    findings = [
        SpecialistFinding(
            role_code="request_analyst",
            recommended_request_type="CHANGE",
            recommended_department="DEVOPS",
            recommended_priority="P3_MEDIUM",
            risk_level="LOW",
            confidence=0.9,
            decision_summary="Yêu cầu thay đổi thông thường.",
        ),
        SpecialistFinding(
            role_code="technical_analyst",
            recommended_request_type="CHANGE",
            recommended_department="DEVOPS",
            recommended_priority="P3_MEDIUM",
            risk_level="LOW",
            confidence=0.85,
            decision_summary="Không có xung đột mã nguồn.",
        ),
        SpecialistFinding(
            role_code="operations_analyst",
            recommended_request_type="CHANGE",
            recommended_department="DEVOPS",
            recommended_priority="P3_MEDIUM",
            risk_level="LOW",
            confidence=0.88,
            decision_summary="Khối lượng công việc bình thường.",
        ),
        SpecialistFinding(
            role_code="security_risk_analyst",
            recommended_request_type="CHANGE",
            recommended_department="SECURITY",
            recommended_priority="P1_CRITICAL",
            risk_level="CRITICAL",
            hard_blockers=["Thao tác xóa dữ liệu hàng loạt bị chặn theo chính sách demo."],
            confidence=0.95,
            decision_summary="Phát hiện thao tác rủi ro mức CRITICAL.",
        ),
    ]
    proposal = CandidateWorkflowProposal(
        template_code="TPL_1",
        name="Mẫu thay đổi",
        description="Quy trình mẫu",
        nodes=[
            CandidateWorkflowNode(id="n1", type="TRIGGER", name="Bắt đầu"),
            CandidateWorkflowNode(id="n2", type="END", name="Kết thúc"),
        ],
        edges=[CandidateWorkflowEdge(id="e1", source="n1", target="n2")],
    )
    critic = CriticReview(
        approved=True,
        decision_summary="Đã rà soát.",
        confidence=0.9,
    )

    aggregated = aggregate_swarm_outputs(
        analysis_job_id="job-conflict-1",
        provider_name="mock",
        model_name="mock-default",
        prompt_version="v1.0.0",
        specialist_findings=findings,
        candidate_workflows=[proposal],
        critic_review=critic,
        rounds_executed=1,
        agent_logs=[],
    )

    assert aggregated.risk_level == "CRITICAL"
    assert aggregated.recommended_priority == "P1_CRITICAL"
    assert aggregated.status == "NO_SAFE_PLAN"
    assert len(aggregated.hard_blockers) == 1
    serialized = aggregated.model_dump()
    assert "reasoning_trace" not in serialized
    assert "chain_of_thought" not in serialized


@pytest.mark.asyncio
async def test_missing_information_returns_needs_information_without_fabricating() -> None:
    """Khi mô tả thiếu dữ liệu bắt buộc, hệ thống trả về `NEEDS_INFORMATION` thay vì tự bịa."""
    supervisor = SwarmSupervisor(
        provider=MockLLMProvider(),
        prompt_registry=PromptRegistry(),
    )
    result = await supervisor.run_analysis(
        context_snapshot={
            "request_id": "req-missing",
            "request_type": "INCIDENT",
            "title": "Lỗi hệ thống",
            "sanitized_description": "Chưa rõ lỗi gì",
            "injection_flags": [],
        }
    )
    assert result.status == "NEEDS_INFORMATION"
    assert len(result.missing_information) >= 1
    assert result.candidate_workflows == []


def test_legacy_ai_engine_adapter_works() -> None:
    """Xác nhận hàm `app.ai_engine.analyze_request` chạy thông suốt và không lưu suy nghĩ ẩn."""
    inbound = InboundRequest(
        source_channel=SourceChannel.WEB_FORM,
        customer=CustomerInfo(
            customer_id="cust-1",
            organization="Acme",
            contact_email="ops@acme.com",
            tier=CustomerTier.ENTERPRISE,
        ),
        product=ProductInfo(
            name="Vadiras Core",
            module="Reporting",
            version="1.0.0",
            environment="production",
        ),
        subject="Lỗi 502 khi xuất báo cáo",
        description="Cổng xuất báo cáo trả lỗi 502 trên production từ sáng nay.",
        requested_action="Tạo phiếu kiểm tra",
    )
    ctx = PreprocessedContext(
        request_id=inbound.request_id,
        idempotency_hash="a" * 64,
        validation_status="PASSED",
        sanitized_text="Cổng xuất báo cáo trả lỗi 502 trên production từ sáng nay.",
    )
    output = analyze_request(inbound, ctx)
    assert output.request_id == inbound.request_id
    assert output.reasoning_trace == ""
    assert output.risk_level.value in {"HIGH", "CRITICAL"}
