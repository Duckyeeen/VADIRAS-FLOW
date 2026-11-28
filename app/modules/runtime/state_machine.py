"""Máy trạng thái lượt chạy, phân loại lỗi, khóa chống trùng lặp và phát hiện tăng rủi ro khi lập lại."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.errors import ConflictError
from app.modules.workflows.models import NodeRunStatus, WorkflowRunStatus

HARD_MAX_REPLANS = 2

RISK_RANK: dict[str, int] = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

# Các trạng thái kết thúc — khi đã vào nhóm này thì không thể tạm dừng, chạy tiếp hay lập lại
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(
    {
        WorkflowRunStatus.COMPLETED.value,
        WorkflowRunStatus.PARTIALLY_COMPLETED.value,
        WorkflowRunStatus.FAILED.value,
        WorkflowRunStatus.CANCELLED.value,
        WorkflowRunStatus.TIMED_OUT.value,
    }
)

# Bảng chuyển trạng thái hợp lệ cho lượt chạy quy trình
ALLOWED_RUN_TRANSITIONS: dict[WorkflowRunStatus, frozenset[WorkflowRunStatus]] = {
    WorkflowRunStatus.QUEUED: frozenset(
        {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.CANCELLED,
            WorkflowRunStatus.FAILED,
        }
    ),
    WorkflowRunStatus.RUNNING: frozenset(
        {
            WorkflowRunStatus.WAITING_APPROVAL,
            WorkflowRunStatus.WAITING_EVENT,
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.REPLANNING,
            WorkflowRunStatus.COMPLETED,
            WorkflowRunStatus.PARTIALLY_COMPLETED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
            WorkflowRunStatus.TIMED_OUT,
        }
    ),
    WorkflowRunStatus.WAITING_APPROVAL: frozenset(
        {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.REPLANNING,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
            WorkflowRunStatus.TIMED_OUT,
        }
    ),
    WorkflowRunStatus.WAITING_EVENT: frozenset(
        {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.WAITING_APPROVAL,
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.REPLANNING,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
            WorkflowRunStatus.TIMED_OUT,
        }
    ),
    WorkflowRunStatus.PAUSED: frozenset(
        {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.WAITING_APPROVAL,
            WorkflowRunStatus.REPLANNING,
            WorkflowRunStatus.CANCELLED,
        }
    ),
    WorkflowRunStatus.REPLANNING: frozenset(
        {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.WAITING_APPROVAL,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
        }
    ),
    WorkflowRunStatus.COMPLETED: frozenset(),
    WorkflowRunStatus.PARTIALLY_COMPLETED: frozenset(),
    WorkflowRunStatus.FAILED: frozenset(),
    WorkflowRunStatus.CANCELLED: frozenset(),
    WorkflowRunStatus.TIMED_OUT: frozenset(),
}

# Bảng chuyển trạng thái hợp lệ cho từng bước trong lượt chạy
ALLOWED_NODE_TRANSITIONS: dict[NodeRunStatus, frozenset[NodeRunStatus]] = {
    NodeRunStatus.PENDING: frozenset(
        {
            NodeRunStatus.READY,
            NodeRunStatus.RUNNING,
            NodeRunStatus.SKIPPED,
            NodeRunStatus.CANCELLED,
            NodeRunStatus.BLOCKED,
        }
    ),
    NodeRunStatus.READY: frozenset(
        {
            NodeRunStatus.RUNNING,
            NodeRunStatus.SKIPPED,
            NodeRunStatus.CANCELLED,
            NodeRunStatus.BLOCKED,
        }
    ),
    NodeRunStatus.RUNNING: frozenset(
        {
            NodeRunStatus.WAITING_APPROVAL,
            NodeRunStatus.WAITING_EVENT,
            NodeRunStatus.RETRYING,
            NodeRunStatus.COMPLETED,
            NodeRunStatus.FAILED,
            NodeRunStatus.CANCELLED,
            NodeRunStatus.BLOCKED,
        }
    ),
    NodeRunStatus.WAITING_APPROVAL: frozenset(
        {
            NodeRunStatus.RUNNING,
            NodeRunStatus.COMPLETED,
            NodeRunStatus.FAILED,
            NodeRunStatus.CANCELLED,
            NodeRunStatus.BLOCKED,
        }
    ),
    NodeRunStatus.WAITING_EVENT: frozenset(
        {
            NodeRunStatus.RUNNING,
            NodeRunStatus.COMPLETED,
            NodeRunStatus.FAILED,
            NodeRunStatus.CANCELLED,
        }
    ),
    NodeRunStatus.RETRYING: frozenset(
        {
            NodeRunStatus.RUNNING,
            NodeRunStatus.FAILED,
            NodeRunStatus.CANCELLED,
        }
    ),
    NodeRunStatus.COMPLETED: frozenset(),
    NodeRunStatus.FAILED: frozenset(),
    NodeRunStatus.SKIPPED: frozenset(),
    NodeRunStatus.CANCELLED: frozenset(),
    NodeRunStatus.BLOCKED: frozenset(),
}


class ErrorClass(str, Enum):
    """Phân nhóm nguyên nhân lỗi để quyết định có được phép thử lại tự động hay không."""

    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    PERMISSION = "PERMISSION"
    BUSINESS = "BUSINESS"
    TIMEOUT = "TIMEOUT"


def is_retryable_error(error_class: str) -> bool:
    """Chỉ cho phép thử lại tự động đối với lỗi tạm thời (`TRANSIENT`)."""
    return error_class.strip().upper() == ErrorClass.TRANSIENT.value


def can_transition_run_status(current: str, target: str) -> bool:
    """Kiểm tra tính hợp lệ của phép chuyển từ trạng thái `current` sang `target`."""
    try:
        curr_enum = WorkflowRunStatus(current)
        tgt_enum = WorkflowRunStatus(target)
    except ValueError:
        return False
    return tgt_enum in ALLOWED_RUN_TRANSITIONS.get(curr_enum, frozenset())


def assert_valid_run_transition(current: str, target: str) -> None:
    """Ném lỗi `ConflictError` nếu trạng thái hiện tại không thể chuyển sang trạng thái đích."""
    if not can_transition_run_status(current, target):
        raise ConflictError(
            f"Không thể chuyển trạng thái lượt chạy từ `{current}` sang `{target}`.",
            code="INVALID_RUN_STATE_TRANSITION",
        )


def build_node_idempotency_key(workflow_run_id: str, node_id: str, attempt: int) -> str:
    """Tạo mã khóa chống trùng lặp cố định theo lượt chạy, mã bước và lần thử."""
    return f"run:{workflow_run_id}:node:{node_id}:att:{attempt}"


def assert_replan_allowed(replan_count: int, graph_max_replans: int) -> None:
    """Chặn lập lại phương án khi đã chạm giới hạn cho phép (tối đa 2 lần)."""
    effective_limit = min(max(0, graph_max_replans), HARD_MAX_REPLANS)
    if replan_count >= effective_limit:
        raise ConflictError(
            f"Lượt chạy đã đạt giới hạn tối đa số lần lập lại phương án ({effective_limit} lần).",
            code="REPLAN_LIMIT_EXCEEDED",
        )


@dataclass(frozen=True, slots=True)
class ReplanDeltaReport:
    """Báo cáo chênh lệch giữa sơ đồ hiện tại và sơ đồ đề xuất mới khi lập lại."""

    added_nodes: list[str] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    modified_nodes: list[str] = field(default_factory=list)
    new_scopes: list[str] = field(default_factory=list)
    new_connector_actions: list[str] = field(default_factory=list)
    new_capabilities: list[str] = field(default_factory=list)
    removed_approvals: list[str] = field(default_factory=list)
    max_parent_risk: str = "LOW"
    max_proposed_risk: str = "LOW"
    risk_escalated: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Chuyển báo cáo chênh lệch sang từ điển JSON lưu trong `scope_delta_json`."""
        return {
            "added_nodes": list(self.added_nodes),
            "removed_nodes": list(self.removed_nodes),
            "modified_nodes": list(self.modified_nodes),
            "new_scopes": list(self.new_scopes),
            "new_connector_actions": list(self.new_connector_actions),
            "new_capabilities": list(self.new_capabilities),
            "removed_approvals": list(self.removed_approvals),
            "max_parent_risk": self.max_parent_risk,
            "max_proposed_risk": self.max_proposed_risk,
            "risk_escalated": self.risk_escalated,
            "reasons": list(self.reasons),
        }


def _connector_action_signature(node: dict[str, Any]) -> str | None:
    if str(node.get("type", "")).upper() != "CONNECTOR_ACTION":
        return None
    cfg = node.get("config") or {}
    connector = str(cfg.get("connector", "")).strip().lower()
    action = str(cfg.get("action", "")).strip().lower()
    if connector or action:
        return f"{connector}:{action}"
    return None


def _max_risk_label(nodes: list[dict[str, Any]]) -> str:
    best = "LOW"
    best_rank = 1
    for node in nodes:
        r = str(node.get("risk_class", "LOW")).strip().upper()
        rank = RISK_RANK.get(r, 1)
        if rank > best_rank:
            best_rank = rank
            best = r
    return best


def compute_replan_delta(
    parent_graph: dict[str, Any],
    proposed_graph: dict[str, Any],
) -> ReplanDeltaReport:
    """So sánh sơ đồ gốc và sơ đồ đề xuất để chặn mọi hành vi phình quyền hay tăng rủi ro ngầm.

    Các dấu hiệu buộc phải đánh dấu `risk_escalated = True` (dừng chờ phê duyệt lại):
    1. Thêm mới thao tác `CONNECTOR_ACTION` chưa có ở bản gốc.
    2. Bổ sung `resource_scope` mới chưa nằm trong phạm vi bản gốc.
    3. Tăng mức rủi ro `risk_class` của một bước hoặc tăng mức rủi ro tối đa toàn sơ đồ.
    4. Đòi hỏi thêm năng lực `required_capabilities` mới.
    5. Gỡ bỏ bước cổng phê duyệt `APPROVAL` từng có trong bản gốc.
    """
    parent_nodes_list = list(parent_graph.get("nodes") or [])
    proposed_nodes_list = list(proposed_graph.get("nodes") or [])

    parent_nodes: dict[str, dict[str, Any]] = {str(n["id"]): n for n in parent_nodes_list if "id" in n}
    proposed_nodes: dict[str, dict[str, Any]] = {str(n["id"]): n for n in proposed_nodes_list if "id" in n}

    added_nodes = [nid for nid in proposed_nodes if nid not in parent_nodes]
    removed_nodes = [nid for nid in parent_nodes if nid not in proposed_nodes]
    modified_nodes = [
        nid for nid in proposed_nodes if nid in parent_nodes and proposed_nodes[nid] != parent_nodes[nid]
    ]

    parent_scopes = {
        str(n.get("resource_scope")).strip()
        for n in parent_nodes_list
        if n.get("resource_scope")
    }
    proposed_scopes = {
        str(n.get("resource_scope")).strip()
        for n in proposed_nodes_list
        if n.get("resource_scope")
    }
    new_scopes = sorted(proposed_scopes - parent_scopes)

    parent_actions = {sig for n in parent_nodes_list if (sig := _connector_action_signature(n)) is not None}
    proposed_actions = {sig for n in proposed_nodes_list if (sig := _connector_action_signature(n)) is not None}
    new_connector_actions = sorted(proposed_actions - parent_actions)

    parent_caps = {
        str(cap).strip()
        for n in parent_nodes_list
        for cap in (n.get("required_capabilities") or [])
        if str(cap).strip()
    }
    proposed_caps = {
        str(cap).strip()
        for n in proposed_nodes_list
        for cap in (n.get("required_capabilities") or [])
        if str(cap).strip()
    }
    new_capabilities = sorted(proposed_caps - parent_caps)

    removed_approvals = [
        nid
        for nid in removed_nodes
        if str(parent_nodes[nid].get("type", "")).upper() == "APPROVAL"
    ]

    max_parent_risk = _max_risk_label(parent_nodes_list)
    max_proposed_risk = _max_risk_label(proposed_nodes_list)

    reasons: list[str] = []
    # Kiểm tra các thay đổi gây mở rộng quyền hạn hoặc rủi ro
    for nid in added_nodes:
        if str(proposed_nodes[nid].get("type", "")).upper() == "CONNECTOR_ACTION":
            reasons.append(f"Thêm mới bước tương tác ngoài `{nid}` trong bản lập lại.")

    if new_scopes:
        reasons.append(f"Mở rộng phạm vi tài nguyên mới: {', '.join(new_scopes)}.")
    if new_connector_actions:
        reasons.append(f"Bổ sung hành động bộ kết nối mới: {', '.join(new_connector_actions)}.")
    if new_capabilities:
        reasons.append(f"Yêu cầu thêm năng lực mới: {', '.join(new_capabilities)}.")
    if removed_approvals:
        reasons.append(f"Loại bỏ cổng phê duyệt đã có: {', '.join(removed_approvals)}.")

    if RISK_RANK.get(max_proposed_risk, 1) > RISK_RANK.get(max_parent_risk, 1):
        reasons.append(f"Mức rủi ro cao nhất của sơ đồ tăng từ `{max_parent_risk}` lên `{max_proposed_risk}`.")

    for nid in modified_nodes:
        old_r = str(parent_nodes[nid].get("risk_class", "LOW")).strip().upper()
        new_r = str(proposed_nodes[nid].get("risk_class", "LOW")).strip().upper()
        if RISK_RANK.get(new_r, 1) > RISK_RANK.get(old_r, 1):
            reasons.append(f"Bước `{nid}` tăng mức rủi ro từ `{old_r}` lên `{new_r}`.")

    return ReplanDeltaReport(
        added_nodes=added_nodes,
        removed_nodes=removed_nodes,
        modified_nodes=modified_nodes,
        new_scopes=new_scopes,
        new_connector_actions=new_connector_actions,
        new_capabilities=new_capabilities,
        removed_approvals=removed_approvals,
        max_parent_risk=max_parent_risk,
        max_proposed_risk=max_proposed_risk,
        risk_escalated=len(reasons) > 0,
        reasons=reasons,
    )
