"""Thuật toán chấm điểm và phân tầng rủi ro cho hành động trong quy trình."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.modules.workflows.registry import FORBIDDEN_DEMO_ACTIONS

RiskBand = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass(frozen=True, slots=True)
class RiskInput:
    """Các yếu tố đầu vào phục vụ đánh giá mức độ rủi ro của một hành động."""

    action: str
    request_type: str = "SERVICE_REQUEST"
    side_effect_class: str = "WRITE"  # NONE | READ | WRITE
    impact_score: int = 2  # 1..5
    likelihood_score: int = 2  # 1..5
    data_sensitivity: int = 1  # 1..3
    scope_breadth: int = 1  # 1..3
    privilege_level: int = 1  # 1..3
    external_customer_impact: bool = False
    irreversible: bool = False
    injection_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Kết quả đánh giá rủi ro kèm điểm số tham khảo và lý do phân tầng."""

    risk_level: RiskBand
    numeric_score: int
    factors: dict[str, int | bool]
    reasons: list[str]


def assess_risk(data: RiskInput) -> RiskAssessment:
    """Đánh giá mức độ rủi ro dựa trên quy tắc cứng kết hợp điểm `Tác động x Khả năng xảy ra`.

    Thuật toán gồm 3 bước:
    1. Kiểm tra quy tắc chặn cứng trước: hành động cấm (`FORBIDDEN_DEMO_ACTIONS`) hoặc
       thao tác không thể đảo ngược ở mức tác động tối đa -> ép mức `CRITICAL`.
    2. Kiểm tra yếu tố nâng rủi ro lên tối thiểu `HIGH`: phát hiện cờ cài cắm lệnh AI,
       hoặc thao tác thuộc loại `CHANGE` (yêu cầu thay đổi cấu hình), hoặc tác động diện rộng.
    3. Tính tổng điểm số (`impact * likelihood + các hệ số phụ`) để phân vào 4 ngưỡng:
       `LOW` (<= 8), `MEDIUM` (9..16), `HIGH` (17..24), `CRITICAL` (>= 25).
    """
    action_lower = data.action.strip().lower()
    reasons: list[str] = []

    base_score = max(1, min(5, data.impact_score)) * max(1, min(5, data.likelihood_score))
    extra = (
        max(0, data.data_sensitivity - 1) * 3
        + max(0, data.scope_breadth - 1) * 3
        + max(0, data.privilege_level - 1) * 4
        + (3 if data.external_customer_impact else 0)
        + (5 if data.irreversible else 0)
        + (8 if data.injection_flags else 0)
    )
    total_score = base_score + extra

    # Bước 1: Các điều kiện bắt buộc nâng lên CRITICAL
    if action_lower in FORBIDDEN_DEMO_ACTIONS:
        reasons.append(f"Hành động `{action_lower}` nằm trong danh sách cấm của bản thử nghiệm.")
        return RiskAssessment(
            risk_level="CRITICAL",
            numeric_score=max(total_score, 30),
            factors={"base_score": base_score, "extra": extra, "forbidden": True},
            reasons=reasons,
        )

    if data.irreversible and data.impact_score >= 5:
        reasons.append("Hành động không thể khôi phục và có mức độ tác động tối đa.")
        return RiskAssessment(
            risk_level="CRITICAL",
            numeric_score=max(total_score, 28),
            factors={"base_score": base_score, "extra": extra, "irreversible": True},
            reasons=reasons,
        )

    # Bước 2 & 3: Phân tầng theo ngưỡng điểm kết hợp quy tắc cứng tối thiểu
    if total_score >= 25:
        level: RiskBand = "CRITICAL"
    elif total_score >= 17:
        level = "HIGH"
    elif total_score >= 9:
        level = "MEDIUM"
    else:
        level = "LOW"

    if data.injection_flags and level in {"LOW", "MEDIUM"}:
        level = "HIGH"
        reasons.append("Nâng mức rủi ro lên tối thiểu HIGH do phát hiện dấu hiệu cài cắm câu lệnh.")

    if data.request_type.strip().upper() == "CHANGE" and data.side_effect_class == "WRITE" and level == "LOW":
        level = "HIGH"
        reasons.append("Yêu cầu thay đổi có tác động ghi ngoài bắt buộc tối thiểu mức HIGH.")

    if not reasons:
        reasons.append(f"Phân tầng mức `{level}` với tổng điểm đánh giá {total_score}.")

    return RiskAssessment(
        risk_level=level,
        numeric_score=total_score,
        factors={
            "base_score": base_score,
            "extra": extra,
            "external_customer_impact": data.external_customer_impact,
            "irreversible": data.irreversible,
        },
        reasons=reasons,
    )
