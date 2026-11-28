"""Bộ máy Xác minh Đối chiếu Ngược: chấm đủ 4 trạng thái dựa trên bằng chứng thực tế và độ mới."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connectors.providers.base import BaseConnector
from app.modules.observability.events import enqueue_outbox_event
from app.modules.requests.models import Request, RequestStatus

from .audit import record_audit_log
from .evidence import (
    CollectedEvidenceItem,
    collect_approval_record_evidence,
    collect_github_readback_evidence,
    collect_human_task_evidence,
)
from .models import AuditActorType, ExecutionEvidence, VerificationOutcome, VerificationRun


@dataclass(frozen=True, slots=True)
class CriterionEvaluation:
    """Kết quả đánh giá riêng lẻ cho từng tiêu chí hậu điều kiện của quy trình."""

    postcondition: str
    status: str  # PASSED | FAILED | MISSING
    evidence_source: str
    detail: str


def evaluate_verification_criteria(
    *,
    postconditions: list[str],
    collected_evidence: list[CollectedEvidenceItem],
    expected_state: dict[str, Any] | None = None,
    requires_human_confirmation: bool = False,
    human_confirmed: bool = False,
) -> tuple[VerificationOutcome, list[CriterionEvaluation], str]:
    """Đánh giá toàn bộ tiêu chí hậu điều kiện trên tập bằng chứng đã thu thập.

    Quy tắc chấm 4 trạng thái theo đặc tả kỹ thuật:
    1. Nếu có bằng chứng mâu thuẫn (`contradicted=True`) -> `FAILED`.
    2. Nếu không thu được bất kỳ bằng chứng tươi mới hợp lệ nào -> `UNVERIFIED`.
    3. Đối chiếu từng `postcondition`:
       - Nếu có bất kỳ tiêu chí nào bị `FAILED` -> `FAILED`.
       - Nếu toàn bộ tiêu chí đều `PASSED` (và đủ xác nhận con người nếu bắt buộc) -> `VERIFIED`.
       - Nếu có ít nhất 1 tiêu chí `PASSED` nhưng còn tiêu chí `MISSING` hoặc thiếu xác nhận con người -> `PARTIALLY_VERIFIED`.
       - Nếu tất cả tiêu chí đều `MISSING` -> `UNVERIFIED`.
    """
    # Trường hợp 1: Có bằng chứng mâu thuẫn trực tiếp với kết quả mong đợi
    contradictions = [ev for ev in collected_evidence if ev.contradicted]
    if contradictions:
        evals = [
            CriterionEvaluation(
                postcondition=pc,
                status="FAILED",
                evidence_source=contradictions[0].source_type,
                detail=contradictions[0].error_reason or "Bằng chứng đọc ngược mâu thuẫn với trạng thái kỳ vọng.",
            )
            for pc in (postconditions or ["overall_consistency"])
        ]
        return (
            VerificationOutcome.FAILED,
            evals,
            contradictions[0].error_reason or "Bằng chứng mâu thuẫn với kết quả kỳ vọng.",
        )

    fresh_evidence = [ev for ev in collected_evidence if ev.is_fresh and ev.error_reason is None]
    if not fresh_evidence:
        reason = "Không thu thập được bằng chứng tươi mới hoặc đủ độ tin cậy để kết luận."
        if collected_evidence and any(not ev.is_fresh for ev in collected_evidence):
            reason = "Bằng chứng thu thập được đã quá hạn độ mới (`freshness_seconds`) hoặc chưa sẵn sàng."
        evals = [
            CriterionEvaluation(
                postcondition=pc,
                status="MISSING",
                evidence_source=collected_evidence[0].source_type if collected_evidence else "none",
                detail=reason,
            )
            for pc in (postconditions or ["evidence_availability"])
        ]
        return VerificationOutcome.UNVERIFIED, evals, reason

    gh_ev = next((ev for ev in fresh_evidence if ev.source_type == "github_issue_readback"), None)
    app_ev = next((ev for ev in fresh_evidence if ev.source_type == "approval_record"), None)
    task_ev = next((ev for ev in fresh_evidence if ev.source_type == "human_task_record"), None)

    criteria_list = list(postconditions or ["linked_evidence_present"])
    evals: list[CriterionEvaluation] = []

    for pc in criteria_list:
        norm = pc.strip().lower()
        if norm in {
            "issue_created",
            "issue_exists_in_allowlisted_repo",
            "linked_evidence_present",
            "issue_created_with_approved_label",
        }:
            if gh_ev is None or not gh_ev.summary.get("external_id"):
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="MISSING",
                        evidence_source="github_issue_readback",
                        detail="Chưa đọc ngược được Issue hợp lệ từ kho mã cho phép.",
                    )
                )
            elif norm == "issue_created_with_approved_label" and "approved" not in [
                str(lbl).lower() for lbl in (gh_ev.summary.get("labels") or [])
            ]:
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="MISSING",
                        evidence_source="github_issue_readback",
                        detail="Issue đã tồn tại nhưng chưa có nhãn `approved` như yêu cầu.",
                    )
                )
            else:
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="PASSED",
                        evidence_source="github_issue_readback",
                        detail=f"Đã đối chiếu ngược thành công tài nguyên `{gh_ev.summary.get('external_id')}`.",
                    )
                )
        elif norm in {"approval_reference_recorded", "approval_granted"}:
            if app_ev is not None and app_ev.summary.get("status") == "APPROVED":
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="PASSED",
                        evidence_source="approval_record",
                        detail=f"Đã xác nhận lệnh phê duyệt `{app_ev.summary.get('approval_id')}` hợp lệ.",
                    )
                )
            else:
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="MISSING",
                        evidence_source="approval_record",
                        detail="Chưa có bằng chứng phê duyệt ở trạng thái `APPROVED`.",
                    )
                )
        elif norm in {"all_human_tasks_completed", "onboarding_checklist_done"}:
            if task_ev is not None and task_ev.summary.get("all_completed"):
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="PASSED",
                        evidence_source="human_task_record",
                        detail="Toàn bộ đầu việc nhân sự bắt buộc đã hoàn tất.",
                    )
                )
            else:
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="MISSING",
                        evidence_source="human_task_record",
                        detail="Vẫn còn đầu việc nhân sự chưa hoàn thành.",
                    )
                )
        elif norm in {"bug_fix_verified", "issue_resolved_with_evidence"}:
            # Đóng issue đơn thuần là chưa đủ nếu không có bằng chứng trạng thái closed + xác nhận
            if gh_ev is not None and gh_ev.summary.get("state") == "closed":
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="PASSED",
                        evidence_source="github_issue_readback",
                        detail="Issue đã đóng và có bằng chứng đối chiếu.",
                    )
                )
            else:
                evals.append(
                    CriterionEvaluation(
                        postcondition=pc,
                        status="MISSING",
                        evidence_source="github_issue_readback",
                        detail="Chưa đủ bằng chứng Issue đã được khắc phục và đóng lại.",
                    )
                )
        else:
            evals.append(
                CriterionEvaluation(
                    postcondition=pc,
                    status="PASSED",
                    evidence_source=fresh_evidence[0].source_type,
                    detail="Đã có bằng chứng tươi mới hỗ trợ tiêu chí.",
                )
            )

    # Đối chiếu thêm các trường expected_state nếu quy trình có quy định
    if expected_state and gh_ev is not None:
        mismatched = list(gh_ev.summary.get("mismatched_fields") or [])
        if mismatched:
            evals.append(
                CriterionEvaluation(
                    postcondition="expected_state_match",
                    status="MISSING",
                    evidence_source="github_issue_readback",
                    detail=f"Một số thuộc tính đọc ngược chưa khớp kỳ vọng: {', '.join(mismatched)}.",
                )
            )

    # Nếu bắt buộc con người xác nhận cuối mà chưa có xác nhận -> chỉ đạt PARTIALLY_VERIFIED
    if requires_human_confirmation and not human_confirmed:
        evals.append(
            CriterionEvaluation(
                postcondition="human_confirmation_required",
                status="MISSING",
                evidence_source="human_confirmation",
                detail="Cần xác nhận cuối cùng từ nhân viên có thẩm quyền.",
            )
        )

    passed_count = sum(1 for item in evals if item.status == "PASSED")
    failed_count = sum(1 for item in evals if item.status == "FAILED")
    missing_count = sum(1 for item in evals if item.status == "MISSING")

    if failed_count > 0:
        return VerificationOutcome.FAILED, evals, "Có tiêu chí hậu điều kiện bị vi phạm khi đối chiếu."
    if passed_count > 0 and missing_count == 0:
        return (
            VerificationOutcome.VERIFIED,
            evals,
            f"Đã xác minh đầy đủ {passed_count}/{len(evals)} tiêu chí từ bằng chứng đối chiếu ngược tươi mới.",
        )
    if passed_count > 0 and missing_count > 0:
        return (
            VerificationOutcome.PARTIALLY_VERIFIED,
            evals,
            f"Đã chứng minh {passed_count}/{len(evals)} tiêu chí; còn {missing_count} tiêu chí chưa đủ bằng chứng.",
        )
    return (
        VerificationOutcome.UNVERIFIED,
        evals,
        "Chưa chứng minh được tiêu chí hậu điều kiện nào từ các nguồn bằng chứng.",
    )


class VerificationEngine:
    """Bộ điều phối thu thập bằng chứng, chấm 4 trạng thái xác minh và ghi nhật ký kiểm toán."""

    async def run_verification(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        request_id: str,
        workflow_run_id: str | None = None,
        node_id: str | None = None,
        postconditions: list[str],
        evidence_sources: list[str],
        expected_state: dict[str, Any] | None = None,
        freshness_seconds: int = 300,
        requires_human_confirmation: bool = False,
        human_confirmed_by_membership_id: str | None = None,
        connector: BaseConnector | None = None,
        external_id_hint: str | None = None,
        evaluator_type: str = "DETERMINISTIC_FIRST",
    ) -> VerificationRun:
        """Thu thập bằng chứng thực tế, lưu `VerificationRun` + `ExecutionEvidence`, cập nhật `Request` và ghi kiểm toán."""
        collected: list[CollectedEvidenceItem] = []
        sources = [s.strip().lower() for s in evidence_sources if s.strip()]
        if not sources:
            sources = ["github_issue_readback"]

        for src in sources:
            if src in {"github_issue_readback", "github_issue", "connector_readback"}:
                collected.append(
                    await collect_github_readback_evidence(
                        session,
                        organization_id=organization_id,
                        request_id=request_id,
                        workflow_run_id=workflow_run_id,
                        external_id_hint=external_id_hint,
                        connector=connector,
                        freshness_seconds=freshness_seconds,
                        expected_state=expected_state,
                    )
                )
            elif src in {"approval_record", "approval"}:
                collected.append(
                    await collect_approval_record_evidence(
                        session,
                        organization_id=organization_id,
                        request_id=request_id,
                        workflow_run_id=workflow_run_id,
                        freshness_seconds=freshness_seconds,
                    )
                )
            elif src in {"human_task_record", "human_tasks", "onboarding_checklist"}:
                collected.append(
                    await collect_human_task_evidence(
                        session,
                        organization_id=organization_id,
                        request_id=request_id,
                        workflow_run_id=workflow_run_id,
                        freshness_seconds=freshness_seconds,
                    )
                )

        outcome, eval_items, rationale = evaluate_verification_criteria(
            postconditions=postconditions,
            collected_evidence=collected,
            expected_state=expected_state,
            requires_human_confirmation=requires_human_confirmation,
            human_confirmed=bool(human_confirmed_by_membership_id),
        )

        now = datetime.now(timezone.utc)
        ver_run = VerificationRun(
            organization_id=organization_id,
            request_id=request_id,
            workflow_run_id=workflow_run_id,
            node_id=node_id,
            evaluator_type=evaluator_type,
            outcome=outcome.value,
            postconditions_json=list(postconditions),
            evaluated_criteria_json=[
                {
                    "postcondition": item.postcondition,
                    "status": item.status,
                    "evidence_source": item.evidence_source,
                    "detail": item.detail,
                }
                for item in eval_items
            ],
            rationale_summary=rationale,
            freshness_seconds=freshness_seconds,
            requires_human_confirmation=requires_human_confirmation,
            human_confirmed_by_membership_id=human_confirmed_by_membership_id,
            verified_at=now,
        )
        session.add(ver_run)
        await session.flush()

        for ev in collected:
            session.add(
                ExecutionEvidence(
                    organization_id=organization_id,
                    verification_run_id=ver_run.id,
                    request_id=request_id,
                    workflow_run_id=workflow_run_id,
                    source_type=ev.source_type,
                    source_ref=ev.source_ref,
                    captured_at=ev.captured_at,
                    actor_id=ev.actor_id,
                    resource_identifier=ev.resource_identifier,
                    content_hash=ev.content_hash,
                    verification_rule=ev.verification_rule,
                    is_fresh=ev.is_fresh,
                    access_classification=ev.access_classification,
                    evidence_summary_json=dict(ev.summary),
                )
            )

        # Cập nhật kết quả nghiệp vụ cuối cùng trên yêu cầu gốc
        req = (
            await session.execute(
                sa.select(Request).where(
                    Request.id == request_id,
                    Request.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if req is not None:
            req.business_outcome = outcome.value
            if outcome == VerificationOutcome.VERIFIED:
                req.status = RequestStatus.RESOLVED.value

        # Ghi vết vào nhật ký kiểm toán chỉ thêm mới
        await record_audit_log(
            session,
            organization_id=organization_id,
            actor_type=AuditActorType.SYSTEM.value,
            actor_id="verification_engine",
            action="verification:completed",
            resource=f"request:{request_id}",
            outcome=outcome.value,
            request_id=request_id,
            workflow_run_id=workflow_run_id,
            node_id=node_id,
            evidence_ref=ver_run.id,
            safe_metadata={
                "verification_run_id": ver_run.id,
                "evidence_count": len(collected),
                "postconditions": list(postconditions),
                "rationale_summary": rationale,
            },
        )
        await enqueue_outbox_event(
            session,
            organization_id=organization_id,
            event_type="VERIFICATION_COMPLETED",
            aggregate_type="verification_run",
            aggregate_id=ver_run.id,
            actor_type=AuditActorType.SYSTEM.value,
            actor_id="verification_engine",
            request_id=request_id,
            workflow_run_id=workflow_run_id,
            payload={"outcome": outcome.value, "evidence_count": len(collected)},
        )
        if outcome == VerificationOutcome.VERIFIED:
            await enqueue_outbox_event(
                session,
                organization_id=organization_id,
                event_type="REQUEST_VERIFIED",
                aggregate_type="request",
                aggregate_id=request_id,
                actor_type=AuditActorType.SYSTEM.value,
                actor_id="verification_engine",
                request_id=request_id,
                workflow_run_id=workflow_run_id,
                access_classification="CUSTOMER_VISIBLE",
                payload={"outcome": outcome.value, "verification_run_id": ver_run.id},
            )
        await session.commit()
        return ver_run
