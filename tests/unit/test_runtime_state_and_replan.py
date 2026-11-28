"""Kiểm thử đơn vị cho máy trạng thái lượt chạy, phân loại lỗi và phát hiện nâng rủi ro khi lập lại."""

from __future__ import annotations

import pytest

from app.core.errors import ConflictError
from app.modules.runtime.state_machine import (
    ErrorClass,
    assert_replan_allowed,
    assert_valid_run_transition,
    build_node_idempotency_key,
    can_transition_run_status,
    compute_replan_delta,
    is_retryable_error,
)
from app.modules.workflows.models import WorkflowRunStatus


def _base_change_graph() -> dict:
    return {
        "workflow_id": "tpl-change-test",
        "version": 1,
        "name": "Quy trình thử nghiệm",
        "request_type": "CHANGE",
        "limits": {
            "max_nodes": 20,
            "max_duration_seconds": 86400,
            "max_retries": 3,
            "max_parallelism": 4,
            "max_estimated_cost_usd": 2.0,
            "max_replans": 2,
        },
        "nodes": [
            {"id": "n1", "type": "TRIGGER", "name": "Bắt đầu", "config": {"source": "api"}},
            {
                "id": "n2",
                "type": "APPROVAL",
                "name": "Phê duyệt",
                "config": {"required_role": "department_manager", "approval_timeout_hours": 24},
            },
            {
                "id": "n3",
                "type": "CONNECTOR_ACTION",
                "name": "Tạo issue",
                "config": {
                    "connector": "mock_github",
                    "action": "create_issue",
                    "target_repository": "Duckyeeen/VADIRAS-FLOW",
                    "parameters": {"labels": ["change"]},
                },
                "required_capabilities": ["mock_github:create_issue"],
                "resource_scope": "github:repo:Duckyeeen/VADIRAS-FLOW",
                "risk_class": "MEDIUM",
            },
            {
                "id": "n4",
                "type": "VERIFICATION",
                "name": "Kiểm chứng",
                "config": {
                    "postconditions": ["issue_created"],
                    "evidence_sources": ["github_issue_readback"],
                },
            },
            {"id": "n5", "type": "END", "name": "Kết thúc", "config": {"expected_outcome": "VERIFIED"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
            {"id": "e3", "source": "n3", "target": "n4"},
            {"id": "e4", "source": "n4", "target": "n5"},
        ],
    }


def test_run_state_transitions_and_terminal_locks() -> None:
    """Kiểm tra các phép chuyển trạng thái hợp lệ và chặn chuyển trạng thái sau khi đã kết thúc."""
    assert can_transition_run_status(WorkflowRunStatus.QUEUED.value, WorkflowRunStatus.RUNNING.value)
    assert can_transition_run_status(WorkflowRunStatus.RUNNING.value, WorkflowRunStatus.PAUSED.value)
    assert can_transition_run_status(WorkflowRunStatus.PAUSED.value, WorkflowRunStatus.RUNNING.value)
    assert can_transition_run_status(WorkflowRunStatus.WAITING_APPROVAL.value, WorkflowRunStatus.CANCELLED.value)

    assert not can_transition_run_status(WorkflowRunStatus.COMPLETED.value, WorkflowRunStatus.PAUSED.value)
    assert not can_transition_run_status(WorkflowRunStatus.CANCELLED.value, WorkflowRunStatus.RUNNING.value)

    with pytest.raises(ConflictError) as exc_info:
        assert_valid_run_transition(WorkflowRunStatus.COMPLETED.value, WorkflowRunStatus.PAUSED.value)
    assert exc_info.value.code == "INVALID_RUN_STATE_TRANSITION"


def test_error_classification_retry_policy_and_idempotency_key() -> None:
    """Chỉ cho phép thử lại lỗi tạm thời `TRANSIENT` và sinh khóa chống trùng lặp cố định."""
    assert is_retryable_error(ErrorClass.TRANSIENT.value) is True
    assert is_retryable_error(ErrorClass.PERMISSION.value) is False
    assert is_retryable_error(ErrorClass.BUSINESS.value) is False
    assert is_retryable_error(ErrorClass.PERMANENT.value) is False

    key = build_node_idempotency_key("run-123", "n3_action", 1)
    assert key == "run:run-123:node:n3_action:att:1"


def test_replan_limit_enforced_at_hard_cap_2() -> None:
    """Giới hạn lập lại không bao giờ vượt quá 2 lần trên một lượt chạy."""
    assert_replan_allowed(0, 2)
    assert_replan_allowed(1, 5)
    with pytest.raises(ConflictError) as exc_info:
        assert_replan_allowed(2, 2)
    assert exc_info.value.code == "REPLAN_LIMIT_EXCEEDED"


def test_compute_replan_delta_detects_no_escalation_on_safe_adjustment() -> None:
    """Thay đổi mô tả hoặc thêm bước thông báo nội bộ không kích hoạt cảnh báo tăng rủi ro."""
    parent = _base_change_graph()
    proposed = _base_change_graph()
    proposed["nodes"].insert(
        4,
        {
            "id": "n4b_notify",
            "type": "NOTIFICATION",
            "name": "Báo nội bộ",
            "config": {"audience": "INTERNAL_ONLY", "channel": "in_app", "template_code": "replan_note"},
        },
    )
    delta = compute_replan_delta(parent, proposed)
    assert delta.risk_escalated is False
    assert delta.added_nodes == ["n4b_notify"]
    assert delta.reasons == []


def test_compute_replan_delta_flags_scope_risk_and_approval_removal() -> None:
    """Mở rộng phạm vi tài nguyên, tăng rủi ro hoặc bỏ cổng duyệt đều phải đánh dấu `risk_escalated`."""
    parent = _base_change_graph()

    # Trường hợp 1: Mở rộng phạm vi kho mới và nâng rủi ro lên HIGH
    escalated_scope = _base_change_graph()
    escalated_scope["nodes"][2]["resource_scope"] = "github:repo:Duckyeeen/OTHER-REPO"
    escalated_scope["nodes"][2]["risk_class"] = "HIGH"
    delta_scope = compute_replan_delta(parent, escalated_scope)
    assert delta_scope.risk_escalated is True
    assert "github:repo:Duckyeeen/OTHER-REPO" in delta_scope.new_scopes
    assert delta_scope.max_proposed_risk == "HIGH"

    # Trường hợp 2: Xóa bỏ cổng phê duyệt đã có
    removed_gate = _base_change_graph()
    removed_gate["nodes"] = [n for n in removed_gate["nodes"] if n["id"] != "n2"]
    delta_gate = compute_replan_delta(parent, removed_gate)
    assert delta_gate.risk_escalated is True
    assert delta_gate.removed_approvals == ["n2"]
