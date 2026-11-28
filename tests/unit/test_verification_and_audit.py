"""Kiểm thử đơn vị cho Bộ đánh giá xác minh 4 trạng thái, độ mới bằng chứng và lọc nhật ký kiểm toán."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.modules.verification.audit import sanitize_audit_metadata
from app.modules.verification.engine import evaluate_verification_criteria
from app.modules.verification.evidence import CollectedEvidenceItem, is_evidence_fresh
from app.modules.verification.models import VerificationOutcome


def _make_gh_evidence(
    *,
    is_fresh: bool = True,
    contradicted: bool = False,
    labels: list[str] | None = None,
    state: str = "open",
    error_reason: str | None = None,
) -> CollectedEvidenceItem:
    return CollectedEvidenceItem(
        source_type="github_issue_readback",
        source_ref="https://github.com/Duckyeeen/VADIRAS-FLOW/issues/101",
        captured_at=datetime.now(timezone.utc),
        actor_id="verifier",
        resource_identifier="Duckyeeen/VADIRAS-FLOW#101",
        content_hash="a" * 64,
        verification_rule="read_back_issue_from_allowlisted_repo",
        is_fresh=is_fresh,
        access_classification="CUSTOMER_VISIBLE",
        summary={
            "external_id": "Duckyeeen/VADIRAS-FLOW#101",
            "external_number": 101,
            "state": state,
            "labels": labels if labels is not None else ["change-request", "approved"],
        },
        contradicted=contradicted,
        error_reason=error_reason,
    )


def _make_approval_evidence(*, status: str = "APPROVED") -> CollectedEvidenceItem:
    return CollectedEvidenceItem(
        source_type="approval_record",
        source_ref="app-001",
        captured_at=datetime.now(timezone.utc),
        actor_id="verifier",
        resource_identifier="github:repo:Duckyeeen/VADIRAS-FLOW",
        content_hash="b" * 64,
        verification_rule="approval_record_must_be_approved",
        is_fresh=True,
        access_classification="INTERNAL_ONLY",
        summary={"approval_id": "app-001", "status": status},
        contradicted=(status == "REJECTED"),
        error_reason=None if status == "APPROVED" else f"Lệnh phê duyệt ở trạng thái `{status}`.",
    )


def test_verification_produces_all_four_outcomes_and_checks_freshness() -> None:
    """Kiểm chứng đủ 4 trạng thái `VERIFIED`, `PARTIALLY_VERIFIED`, `FAILED`, `UNVERIFIED`."""
    now = datetime.now(timezone.utc)
    assert is_evidence_fresh(now - timedelta(seconds=60), freshness_seconds=300, now=now) is True
    assert is_evidence_fresh(now - timedelta(seconds=600), freshness_seconds=300, now=now) is False

    # 1. VERIFIED: Đọc ngược Issue có nhãn approved + lệnh duyệt APPROVED + tươi mới
    outcome_ok, _, _ = evaluate_verification_criteria(
        postconditions=["issue_created_with_approved_label", "approval_reference_recorded"],
        collected_evidence=[_make_gh_evidence(), _make_approval_evidence(status="APPROVED")],
    )
    assert outcome_ok == VerificationOutcome.VERIFIED

    # 2. PARTIALLY_VERIFIED: Đã tạo Issue nhưng thiếu nhãn `approved` hoặc thiếu xác nhận con người
    outcome_partial, evals_partial, _ = evaluate_verification_criteria(
        postconditions=["issue_created_with_approved_label", "approval_reference_recorded"],
        collected_evidence=[_make_gh_evidence(labels=["incident"]), _make_approval_evidence(status="APPROVED")],
    )
    assert outcome_partial == VerificationOutcome.PARTIALLY_VERIFIED
    assert any(e.status == "MISSING" for e in evals_partial)

    outcome_need_human, _, _ = evaluate_verification_criteria(
        postconditions=["issue_created"],
        collected_evidence=[_make_gh_evidence()],
        requires_human_confirmation=True,
        human_confirmed=False,
    )
    assert outcome_need_human == VerificationOutcome.PARTIALLY_VERIFIED

    # 3. FAILED: Có bằng chứng mâu thuẫn (ví dụ lệnh duyệt bị REJECTED hoặc đọc ngược sai lệch)
    outcome_fail, _, _ = evaluate_verification_criteria(
        postconditions=["issue_created"],
        collected_evidence=[_make_gh_evidence(contradicted=True, error_reason="Sai lệch tiêu đề Issue")],
    )
    assert outcome_fail == VerificationOutcome.FAILED

    # 4. UNVERIFIED: Bằng chứng đã quá hạn freshness_seconds hoặc không thu được bằng chứng
    outcome_stale, _, _ = evaluate_verification_criteria(
        postconditions=["issue_created"],
        collected_evidence=[_make_gh_evidence(is_fresh=False)],
    )
    assert outcome_stale == VerificationOutcome.UNVERIFIED

    outcome_empty, _, _ = evaluate_verification_criteria(
        postconditions=["issue_created"],
        collected_evidence=[],
    )
    assert outcome_empty == VerificationOutcome.UNVERIFIED


def test_sanitize_audit_metadata_removes_secrets_and_hidden_cot() -> None:
    """Đảm bảo hàm làm sạch kiểm toán xóa bỏ `reasoning_trace` và che giấu toàn bộ bí mật."""
    raw = {
        "repository": "Duckyeeen/VADIRAS-FLOW",
        "access_token": "ghs_secret_123",
        "nested": {"private_key": "-----BEGIN RSA-----", "ok_field": 42},
        "reasoning_trace": "Suy nghĩ nội bộ không được phép lưu",
        "chain_of_thought": "step 1 step 2",
    }
    cleaned = sanitize_audit_metadata(raw)
    assert cleaned["repository"] == "Duckyeeen/VADIRAS-FLOW"
    assert cleaned["access_token"] == "[DA_AN]"
    assert cleaned["nested"]["private_key"] == "[DA_AN]"
    assert cleaned["nested"]["ok_field"] == 42
    assert "reasoning_trace" not in cleaned
    assert "chain_of_thought" not in cleaned
