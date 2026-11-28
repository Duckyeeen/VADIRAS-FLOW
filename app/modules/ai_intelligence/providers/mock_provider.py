"""Bộ giả lập nhà cung cấp AI chạy xác định cho kiểm thử và trình diễn không cần khóa API."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.modules.requests.intake import suggest_default_department_code

from .base import (
    LLMCallResult,
    LLMUsage,
    ProviderCapabilities,
    RawLLMResponse,
    TModel,
    run_structured_with_bounded_repair,
)


class MockLLMProvider:
    """Nhà cung cấp AI giả lập trả về JSON chuẩn xác định theo từng vai trò và kịch bản kiểm thử."""

    provider_name = "mock"

    def __init__(
        self,
        *,
        model_name: str = "mock-default",
        failure_mode: str = "none",
        force_critic_reject_round_1: bool = False,
        always_reject_critic: bool = False,
        simulated_delay_seconds: float = 0.0,
    ) -> None:
        self.model_name = model_name
        self._failure_mode = failure_mode
        self._force_critic_reject_round_1 = force_critic_reject_round_1
        self._always_reject_critic = always_reject_critic
        self._simulated_delay_seconds = simulated_delay_seconds
        self._call_counter: dict[str, int] = {}
        self.active_concurrency = 0
        self.peak_concurrency = 0

    def get_capabilities(self) -> ProviderCapabilities:
        """Khai báo năng lực hỗ trợ JSON có cấu trúc của bộ giả lập."""
        return ProviderCapabilities(
            supports_structured_json=True,
            supports_tool_proposal=True,
            max_context_tokens=16_384,
        )

    async def generate_raw_json(
        self,
        *,
        role_code: str,
        system_prompt: str,
        user_context: dict[str, Any],
        schema_name: str,
        repair_hint: str | None = None,
    ) -> RawLLMResponse:
        """Sinh chuỗi JSON giả lập kèm bộ đếm song song thực tế phục vụ kiểm thử giới hạn."""
        del system_prompt, schema_name
        self.active_concurrency += 1
        self.peak_concurrency = max(self.peak_concurrency, self.active_concurrency)
        try:
            if self._simulated_delay_seconds > 0:
                await asyncio.sleep(self._simulated_delay_seconds)

            call_idx = self._call_counter.get(role_code, 0) + 1
            self._call_counter[role_code] = call_idx

            # Hỗ trợ giả lập lỗi định dạng JSON để kiểm chứng cơ chế sửa lỗi có giới hạn
            if self._failure_mode == "always_malformed":
                return RawLLMResponse(
                    raw_text="{day_khong_phai_json_hop_le",
                    usage=LLMUsage(prompt_tokens=120, completion_tokens=20, cost_usd=0.0001, cost_source="ESTIMATED"),
                )
            if self._failure_mode == "malformed_once" and repair_hint is None and call_idx == 1:
                return RawLLMResponse(
                    raw_text='{"thieu_truong_bat_buoc": true}',
                    usage=LLMUsage(prompt_tokens=120, completion_tokens=25, cost_usd=0.0001, cost_source="ESTIMATED"),
                )

            payload = self._build_payload(role_code=role_code, user_context=user_context)
            return RawLLMResponse(
                raw_text=json.dumps(payload, ensure_ascii=False),
                usage=LLMUsage(
                    prompt_tokens=240,
                    completion_tokens=160,
                    cost_usd=0.0004,
                    cost_source="ESTIMATED",
                ),
            )
        finally:
            self.active_concurrency -= 1

    async def generate_structured(
        self,
        *,
        role_code: str,
        system_prompt: str,
        user_context: dict[str, Any],
        output_model: type[TModel],
        max_repair_attempts: int = 2,
    ) -> LLMCallResult[TModel]:
        """Sinh và kiểm tra dữ liệu đầu ra theo mô hình Pydantic với số lần sửa có giới hạn."""
        return await run_structured_with_bounded_repair(
            self,
            role_code=role_code,
            system_prompt=system_prompt,
            user_context=user_context,
            output_model=output_model,
            max_repair_attempts=max_repair_attempts,
        )

    def _build_payload(self, *, role_code: str, user_context: dict[str, Any]) -> dict[str, Any]:
        """Xây dựng câu trả lời xác định phù hợp với từng vai trò và ngữ cảnh yêu cầu."""
        req_type = str(user_context.get("request_type", "SERVICE_REQUEST")).upper()
        title = str(user_context.get("title", ""))
        desc = str(user_context.get("sanitized_description", ""))
        injection_flags = list(user_context.get("injection_flags", []))
        combined_lower = f"{title} {desc}".lower()

        dept_code = suggest_default_department_code(req_type)
        missing_info: list[str] = []
        if len(desc.strip()) < 15 or any(
            marker in combined_lower for marker in ("thiếu thông tin", "chưa rõ", "tbd", "[thieu_thong_tin]")
        ):
            missing_info.append("Cần bổ sung môi trường xảy ra, thời điểm phát sinh và bước tái hiện chi tiết.")

        is_critical = any(
            kw in combined_lower for kw in ("xóa toàn bộ", "delete all", "drop database", "grant admin")
        )
        is_high_risk = req_type == "CHANGE" or bool(injection_flags) or any(
            kw in combined_lower for kw in ("production", "refund", "hoàn tiền", "quyền quản trị", "502")
        )

        risk_level = "CRITICAL" if is_critical else ("HIGH" if is_high_risk else ("MEDIUM" if req_type == "ONBOARDING" else "LOW"))
        priority = "P1_CRITICAL" if req_type == "INCIDENT" or is_critical else ("P2_HIGH" if is_high_risk else "P3_MEDIUM")

        if role_code in {"request_analyst", "technical_analyst", "operations_analyst", "security_risk_analyst"}:
            hard_blockers: list[str] = []
            risks: list[str] = []
            if role_code == "security_risk_analyst":
                if injection_flags:
                    risks.append(f"Phát hiện dấu hiệu cài cắm câu lệnh: {', '.join(injection_flags)}")
                    hard_blockers.append("Bắt buộc kiểm tra thủ công do có dấu hiệu cài cắm câu lệnh AI.")
                if is_critical:
                    hard_blockers.append("Hành động có mức độ rủi ro CRITICAL bị chặn trong cấu hình thử nghiệm.")
                if req_type == "CHANGE":
                    risks.append("Yêu cầu thay đổi cấu hình bắt buộc qua cổng phê duyệt của Quản lý.")

            role_summary_map = {
                "request_analyst": f"Đã phân loại yêu cầu thuộc nhóm `{req_type}` với mức ưu tiên đề xuất `{priority}`.",
                "technical_analyst": f"Đã rà soát phụ thuộc kỹ thuật và đề xuất tách đầu việc cho nhóm `{dept_code}`.",
                "operations_analyst": f"Định tuyến phòng ban `{dept_code}` và gắn khung theo dõi thời hạn phù hợp.",
                "security_risk_analyst": f"Đánh giá mức rủi ro `{risk_level}` và kiểm tra phạm vi dữ liệu nhạy cảm.",
            }
            return {
                "role_code": role_code,
                "recommended_request_type": req_type,
                "recommended_department": dept_code,
                "recommended_priority": priority,
                "risk_level": risk_level if role_code == "security_risk_analyst" else "LOW",
                "findings": [role_summary_map[role_code]],
                "assumptions": ["Chỉ sử dụng ngữ cảnh đã được che thông tin cá nhân nhạy cảm."],
                "risks": risks,
                "missing_information": missing_info if role_code == "request_analyst" else [],
                "hard_blockers": hard_blockers,
                "evidence_refs": [f"request:{user_context.get('request_id', 'unknown')}"],
                "confidence": 0.9 if not missing_info else 0.55,
                "decision_summary": role_summary_map[role_code],
            }

        if role_code == "workflow_planner":
            needs_approval = risk_level in {"HIGH", "CRITICAL"} or req_type == "CHANGE"
            nodes = [
                {"id": "n1_trigger", "type": "TRIGGER", "name": "Tiếp nhận yêu cầu", "config": {"source": "api"}},
                {"id": "n2_classify", "type": "CLASSIFY", "name": "Chuẩn hóa phân loại", "config": {"request_type": req_type}},
            ]
            edges = [{"id": "e1", "source": "n1_trigger", "target": "n2_classify", "label": "Bắt đầu"}]
            prev_node = "n2_classify"

            if needs_approval:
                nodes.append(
                    {
                        "id": "n3_approval",
                        "type": "APPROVAL",
                        "name": "Cổng phê duyệt thay đổi rủi ro cao",
                        "config": {"required_role": "department_manager"},
                    }
                )
                edges.append({"id": "e2", "source": prev_node, "target": "n3_approval", "label": "Chờ duyệt"})
                prev_node = "n3_approval"

            nodes.extend(
                [
                    {
                        "id": "n4_action",
                        "type": "CONNECTOR_ACTION",
                        "name": "Tạo phiếu theo dõi trên GitHub",
                        "config": {"connector": "github", "action": "create_issue"},
                    },
                    {
                        "id": "n5_verify",
                        "type": "VERIFICATION",
                        "name": "Đối chiếu bằng chứng hoàn tất",
                        "config": {"require_read_back": True},
                    },
                    {
                        "id": "n6_end",
                        "type": "END",
                        "name": "Kết thúc quy trình",
                        "config": {"expected_outcome": "VERIFIED"},
                    },
                ]
            )
            edges.extend(
                [
                    {"id": "e3", "source": prev_node, "target": "n4_action", "label": "Thực thi"},
                    {"id": "e4", "source": "n4_action", "target": "n5_verify", "label": "Kiểm chứng"},
                    {"id": "e5", "source": "n5_verify", "target": "n6_end", "label": "Hoàn tất"},
                ]
            )

            return {
                "proposals": [
                    {
                        "template_code": f"TPL_{req_type}_V1",
                        "name": f"Quy trình chuẩn cho nhóm {req_type}",
                        "description": "Sơ đồ lắp ghép từ các bước chuẩn kèm bước xác minh đối chiếu ngược.",
                        "nodes": nodes,
                        "edges": edges,
                        "requires_approval": needs_approval,
                        "verification_criteria": [
                            "Đọc ngược lại trạng thái Issue đã tạo và đối chiếu kho mã đích.",
                        ],
                    }
                ],
                "decision_summary": f"Đã đề xuất 1 phương án sơ đồ chuẩn cho `{req_type}` (cần duyệt={needs_approval}).",
                "assumptions": ["Bộ kết nối GitHub hoặc bản giả lập đang sẵn sàng."],
                "evidence_refs": [f"prompt:{user_context.get('prompt_version', 'v1.0.0')}"],
                "confidence": 0.88,
            }

        # Vai trò critic_reviewer
        round_number = int(user_context.get("round_number", 1))
        if self._always_reject_critic or (self._force_critic_reject_round_1 and round_number == 1):
            return {
                "approved": False,
                "blocking_issues": [],
                "warnings": ["Cần rà soát lại điều kiện chuyển tiếp trước bước xác minh."],
                "required_changes": ["Bổ sung mô tả tiêu chí đối chiếu bằng chứng rõ ràng hơn."],
                "decision_summary": f"Vòng {round_number}: yêu cầu chỉnh sửa lại phương án trước khi chốt.",
                "assumptions": [],
                "evidence_refs": [],
                "confidence": 0.72,
            }

        return {
            "approved": True,
            "blocking_issues": [],
            "warnings": [],
            "required_changes": [],
            "decision_summary": f"Vòng {round_number}: sơ đồ đề xuất đầy đủ cổng kiểm soát và bước xác minh.",
            "assumptions": ["Đã rà soát ràng buộc rủi ro và tính đầy đủ của các bước."],
            "evidence_refs": [f"round:{round_number}"],
            "confidence": 0.92,
        }
