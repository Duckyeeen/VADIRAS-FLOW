"""Bộ kiểm tra sơ đồ quy trình 7 tầng trước khi lưu hoặc ban hành phiên bản bất biến."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from pydantic import ValidationError

from app.core.schemas import ContractModel

from .dsl.conditions import validate_condition_expr
from .dsl.schemas import NodeType, WorkflowGraphSpec, WorkflowNodeSpec
from .registry import (
    FORBIDDEN_DEMO_ACTIONS,
    REGISTERED_CAPABILITIES,
    NodeRegistry,
    default_node_registry,
)

HARD_MAX_NODES = 30
HARD_MAX_RETRIES = 3
HARD_MAX_PARALLELISM = 4
HARD_MAX_REPLANS = 2


class ValidationIssue(ContractModel):
    """Mô tả một lỗi hoặc cảnh báo gắn với đúng tầng kiểm tra và mã bước/cạnh."""

    stage: str
    severity: str  # ERROR | WARNING
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None


class WorkflowValidationReport(ContractModel):
    """Báo cáo tổng hợp kết quả chạy bộ kiểm tra 7 tầng trên một sơ đồ quy trình."""

    valid: bool
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    stage_results: dict[str, bool] = {}


def _is_reachable_avoiding(
    start_id: str,
    target_id: str,
    adjacency: dict[str, list[str]],
    blocked_nodes: set[str],
) -> bool:
    """Kiểm tra có tồn tại đường đi từ `start_id` tới `target_id` mà không đi qua `blocked_nodes` hay không."""
    if start_id in blocked_nodes:
        return False
    visited: set[str] = {start_id}
    queue: deque[str] = deque([start_id])
    while queue:
        curr = queue.popleft()
        if curr == target_id:
            return True
        for nxt in adjacency.get(curr, []):
            if nxt not in visited and nxt not in blocked_nodes:
                visited.add(nxt)
                queue.append(nxt)
    return False


def validate_workflow_graph(
    graph_data: dict[str, Any],
    *,
    registry: NodeRegistry = default_node_registry,
) -> WorkflowValidationReport:
    """Chạy tuần tự 7 tầng kiểm tra cố định trên một sơ đồ quy trình JSON.

    7 tầng kiểm tra bao gồm:
    1. `STRUCTURAL`: đúng khuôn mẫu, ID duy nhất, chỉ dùng 12 loại bước đăng ký, đúng 1 `TRIGGER`,
       có `END`, không chu trình, đi tới được mọi bước và điều kiện rẽ nhánh an toàn.
    2. `DATAFLOW`: mọi `input_mapping` phải trỏ tới dữ liệu đầu vào `trigger.*` hoặc bước tổ tiên hợp lệ.
    3. `CAPABILITY`: năng lực của trợ lý AI và bộ kết nối phải tồn tại trong danh mục đăng ký.
    4. `PERMISSION`: mọi thao tác ngoài phải có `resource_scope` cụ thể (không `*`) và không nằm trong danh sách cấm.
    5. `POLICY_RISK`: chặn mức rủi ro `CRITICAL`; yêu cầu `CHANGE` hoặc bước `HIGH` bắt buộc có `APPROVAL` phía trước.
    6. `RESOURCE`: giới hạn số bước, số lần thử lại, độ song song, số lần lập lại và trần chi phí.
    7. `VERIFICATION`: quy trình có thao tác ngoài hoặc việc nhân sự bắt buộc phải có bước `VERIFICATION`
       kèm tiêu chí `postconditions` và `evidence_sources` trước khi tới `END`.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    stage_results: dict[str, bool] = {
        "STRUCTURAL": False,
        "DATAFLOW": False,
        "CAPABILITY": False,
        "PERMISSION": False,
        "POLICY_RISK": False,
        "RESOURCE": False,
        "VERIFICATION": False,
    }

    # --- TẦNG 1: KIỂM TRA CẤU TRÚC ĐỒ THỊ & LOẠI BƯỚC ---
    try:
        graph = WorkflowGraphSpec.model_validate(graph_data)
    except ValidationError as exc:
        for err in exc.errors():
            errors.append(
                ValidationIssue(
                    stage="STRUCTURAL",
                    severity="ERROR",
                    code="SCHEMA_INVALID",
                    message=f"Lỗi cấu trúc tại `{'.'.join(str(x) for x in err.get('loc', []))}`: {err.get('msg')}",
                )
            )
        return WorkflowValidationReport(valid=False, errors=errors, warnings=warnings, stage_results=stage_results)

    if len(graph.nodes) < 2:
        errors.append(
            ValidationIssue(
                stage="STRUCTURAL",
                severity="ERROR",
                code="TOO_FEW_NODES",
                message="Sơ đồ quy trình phải có ít nhất 2 bước (`TRIGGER` và `END`).",
            )
        )

    nodes_by_id: dict[str, WorkflowNodeSpec] = {}
    for node in graph.nodes:
        if node.id in nodes_by_id:
            errors.append(
                ValidationIssue(
                    stage="STRUCTURAL",
                    severity="ERROR",
                    code="DUPLICATE_NODE_ID",
                    message=f"Mã bước `{node.id}` bị trùng lặp trong sơ đồ.",
                    node_id=node.id,
                )
            )
            continue
        nodes_by_id[node.id] = node

        spec = registry.get_spec(node.type)
        if spec is None:
            errors.append(
                ValidationIssue(
                    stage="STRUCTURAL",
                    severity="ERROR",
                    code="UNKNOWN_NODE_TYPE",
                    message=f"Loại bước `{node.type}` chưa được đăng ký trong NodeRegistry.",
                    node_id=node.id,
                )
            )
        else:
            try:
                spec.config_model.model_validate(node.config)
            except ValidationError as exc:
                errors.append(
                    ValidationIssue(
                        stage="STRUCTURAL",
                        severity="ERROR",
                        code="INVALID_NODE_CONFIG",
                        message=f"Cấu hình của bước `{node.id}` ({node.type}) không hợp lệ: {exc.errors()[0].get('msg')}",
                        node_id=node.id,
                    )
                )

    trigger_nodes = [n for n in graph.nodes if n.type.upper() == NodeType.TRIGGER.value]
    end_nodes = [n for n in graph.nodes if n.type.upper() == NodeType.END.value]
    if len(trigger_nodes) != 1:
        errors.append(
            ValidationIssue(
                stage="STRUCTURAL",
                severity="ERROR",
                code="INVALID_TRIGGER_COUNT",
                message=f"Sơ đồ phải có đúng 1 bước `TRIGGER` (hiện có {len(trigger_nodes)}).",
            )
        )
    if len(end_nodes) < 1:
        errors.append(
            ValidationIssue(
                stage="STRUCTURAL",
                severity="ERROR",
                code="MISSING_END_NODE",
                message="Sơ đồ phải có ít nhất 1 bước `END`.",
            )
        )

    seen_edge_ids: set[str] = set()
    adjacency: dict[str, list[str]] = defaultdict(list)
    reverse_adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {nid: 0 for nid in nodes_by_id}

    for edge in graph.edges:
        if edge.id in seen_edge_ids:
            errors.append(
                ValidationIssue(
                    stage="STRUCTURAL",
                    severity="ERROR",
                    code="DUPLICATE_EDGE_ID",
                    message=f"Mã cạnh nối `{edge.id}` bị trùng lặp.",
                    edge_id=edge.id,
                )
            )
        seen_edge_ids.add(edge.id)

        if edge.source not in nodes_by_id or edge.target not in nodes_by_id:
            errors.append(
                ValidationIssue(
                    stage="STRUCTURAL",
                    severity="ERROR",
                    code="INVALID_EDGE_REFERENCE",
                    message=f"Cạnh `{edge.id}` trỏ tới mã bước không tồn tại.",
                    edge_id=edge.id,
                )
            )
            continue

        if edge.source == edge.target:
            errors.append(
                ValidationIssue(
                    stage="STRUCTURAL",
                    severity="ERROR",
                    code="SELF_LOOP_NOT_ALLOWED",
                    message=f"Cạnh `{edge.id}` không được tự nối vào chính bước `{edge.source}`.",
                    edge_id=edge.id,
                    node_id=edge.source,
                )
            )
            continue

        adjacency[edge.source].append(edge.target)
        reverse_adj[edge.target].append(edge.source)
        in_degree[edge.target] += 1

        if edge.condition is not None:
            cond_errors = validate_condition_expr(edge.condition)
            for msg in cond_errors:
                errors.append(
                    ValidationIssue(
                        stage="STRUCTURAL",
                        severity="ERROR",
                        code="UNSAFE_OR_INVALID_CONDITION",
                        message=f"Điều kiện trên cạnh `{edge.id}` không hợp lệ: {msg}",
                        edge_id=edge.id,
                    )
                )

    # Kiểm tra đồ thị không chu trình (DAG) bằng thuật toán Kahn
    topo_order: list[str] = []
    if nodes_by_id and not any(e.code in {"INVALID_EDGE_REFERENCE", "SELF_LOOP_NOT_ALLOWED"} for e in errors):
        zero_queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        in_deg_copy = dict(in_degree)
        while zero_queue:
            curr = zero_queue.popleft()
            topo_order.append(curr)
            for nxt in adjacency.get(curr, []):
                in_deg_copy[nxt] -= 1
                if in_deg_copy[nxt] == 0:
                    zero_queue.append(nxt)
        if len(topo_order) != len(nodes_by_id):
            errors.append(
                ValidationIssue(
                    stage="STRUCTURAL",
                    severity="ERROR",
                    code="CYCLE_DETECTED",
                    message="Phát hiện chu trình lặp trong sơ đồ quy trình; đồ thị bắt buộc không có chu trình.",
                )
            )

    # Kiểm tra khả năng đi tới mọi bước từ TRIGGER và đi tới END từ mọi bước
    if len(trigger_nodes) == 1 and end_nodes and not any(e.code == "CYCLE_DETECTED" for e in errors):
        trigger_id = trigger_nodes[0].id
        reachable_from_trigger: set[str] = {trigger_id}
        q = deque([trigger_id])
        while q:
            curr = q.popleft()
            for nxt in adjacency.get(curr, []):
                if nxt not in reachable_from_trigger:
                    reachable_from_trigger.add(nxt)
                    q.append(nxt)

        for nid in nodes_by_id:
            if nid not in reachable_from_trigger:
                errors.append(
                    ValidationIssue(
                        stage="STRUCTURAL",
                        severity="ERROR",
                        code="UNREACHABLE_NODE",
                        message=f"Bước `{nid}` không thể đi tới được từ điểm khởi phát `TRIGGER`.",
                        node_id=nid,
                    )
                )

        can_reach_end: set[str] = {e.id for e in end_nodes}
        rq = deque(list(can_reach_end))
        while rq:
            curr = rq.popleft()
            for prev in reverse_adj.get(curr, []):
                if prev not in can_reach_end:
                    can_reach_end.add(prev)
                    rq.append(prev)

        for nid in nodes_by_id:
            if nid not in can_reach_end:
                errors.append(
                    ValidationIssue(
                        stage="STRUCTURAL",
                        severity="ERROR",
                        code="DEAD_END_NODE",
                        message=f"Bước `{nid}` không có đường dẫn tới bất kỳ bước `END` nào.",
                        node_id=nid,
                    )
                )

    stage_results["STRUCTURAL"] = not any(e.stage == "STRUCTURAL" for e in errors)

    # --- TẦNG 2: KIỂM TRA LUỒNG DỮ LIỆU ---
    # Tính tập hợp các bước tổ tiên của từng bước theo thứ tự tô-pô
    ancestors: dict[str, set[str]] = {nid: set() for nid in nodes_by_id}
    for nid in topo_order:
        for nxt in adjacency.get(nid, []):
            ancestors[nxt].add(nid)
            ancestors[nxt].update(ancestors[nid])

    trigger_inputs = set(graph.input_schema)
    for node in graph.nodes:
        for target_field, source_expr in node.input_mapping.items():
            if "." not in source_expr:
                errors.append(
                    ValidationIssue(
                        stage="DATAFLOW",
                        severity="ERROR",
                        code="INVALID_DATA_MAPPING_SYNTAX",
                        message=f"Ánh xạ `{target_field}={source_expr}` ở bước `{node.id}` phải có dạng `<nguồn>.<tên_trường>`.",
                        node_id=node.id,
                    )
                )
                continue
            src_node_id, src_field = source_expr.split(".", 1)
            if src_node_id == "trigger":
                if src_field not in trigger_inputs:
                    errors.append(
                        ValidationIssue(
                            stage="DATAFLOW",
                            severity="ERROR",
                            code="MISSING_TRIGGER_INPUT",
                            message=f"Bước `{node.id}` yêu cầu `trigger.{src_field}` nhưng không có trong `input_schema`.",
                            node_id=node.id,
                        )
                    )
            else:
                if src_node_id not in ancestors.get(node.id, set()):
                    errors.append(
                        ValidationIssue(
                            stage="DATAFLOW",
                            severity="ERROR",
                            code="INVALID_UPSTREAM_REFERENCE",
                            message=f"Bước `{node.id}` tham chiếu `{source_expr}` nhưng `{src_node_id}` không phải bước tiền nhiệm.",
                            node_id=node.id,
                        )
                    )
                else:
                    src_node = nodes_by_id[src_node_id]
                    src_spec = registry.get_spec(src_node.type)
                    available_keys = set(src_node.output_keys)
                    if src_spec is not None:
                        available_keys.update(src_spec.default_output_keys)
                    if src_field not in available_keys:
                        errors.append(
                            ValidationIssue(
                                stage="DATAFLOW",
                                severity="ERROR",
                                code="MISSING_UPSTREAM_OUTPUT_KEY",
                                message=f"Bước `{src_node_id}` không cung cấp đầu ra `{src_field}` cho bước `{node.id}`.",
                                node_id=node.id,
                            )
                        )

    stage_results["DATAFLOW"] = not any(e.stage == "DATAFLOW" for e in errors)

    # --- TẦNG 3: KIỂM TRA NĂNG LỰC SẴN CÓ ---
    for node in graph.nodes:
        for cap in node.required_capabilities:
            if cap not in REGISTERED_CAPABILITIES:
                errors.append(
                    ValidationIssue(
                        stage="CAPABILITY",
                        severity="ERROR",
                        code="UNKNOWN_CAPABILITY",
                        message=f"Năng lực `{cap}` tại bước `{node.id}` chưa được đăng ký trong hệ thống.",
                        node_id=node.id,
                    )
                )
        if node.type.upper() == NodeType.CONNECTOR_ACTION.value:
            connector = str(node.config.get("connector", "")).strip().lower()
            action = str(node.config.get("action", "")).strip().lower()
            cap_key = f"{connector}:{action}"
            if cap_key not in REGISTERED_CAPABILITIES and action not in FORBIDDEN_DEMO_ACTIONS:
                errors.append(
                    ValidationIssue(
                        stage="CAPABILITY",
                        severity="ERROR",
                        code="UNKNOWN_CONNECTOR_ACTION",
                        message=f"Hành động bộ kết nối `{cap_key}` tại bước `{node.id}` chưa được hỗ trợ.",
                        node_id=node.id,
                    )
                )
        if node.type.upper() == NodeType.AGENT_TASK.value:
            agent_cap = str(node.config.get("capability", "")).strip()
            if agent_cap not in REGISTERED_CAPABILITIES:
                errors.append(
                    ValidationIssue(
                        stage="CAPABILITY",
                        severity="ERROR",
                        code="UNKNOWN_AGENT_CAPABILITY",
                        message=f"Năng lực trợ lý AI `{agent_cap}` tại bước `{node.id}` chưa được đăng ký.",
                        node_id=node.id,
                    )
                )

    stage_results["CAPABILITY"] = not any(e.stage == "CAPABILITY" for e in errors)

    # --- TẦNG 4: KIỂM TRA PHẠM VI QUYỀN & HÀNH ĐỘNG CẤM ---
    for node in graph.nodes:
        if node.type.upper() == NodeType.CONNECTOR_ACTION.value:
            action = str(node.config.get("action", "")).strip().lower()
            if action in FORBIDDEN_DEMO_ACTIONS:
                errors.append(
                    ValidationIssue(
                        stage="PERMISSION",
                        severity="ERROR",
                        code="FORBIDDEN_DEMO_ACTION",
                        message=f"Hành động `{action}` tại bước `{node.id}` bị cấm trong bản thử nghiệm.",
                        node_id=node.id,
                    )
                )
            scope = (node.resource_scope or "").strip()
            if not scope or "*" in scope:
                errors.append(
                    ValidationIssue(
                        stage="PERMISSION",
                        severity="ERROR",
                        code="INVALID_RESOURCE_SCOPE",
                        message=f"Bước `{node.id}` phải khai báo `resource_scope` cụ thể, không được rỗng hoặc dùng `*`.",
                        node_id=node.id,
                    )
                )

    stage_results["PERMISSION"] = not any(e.stage == "PERMISSION" for e in errors)

    # --- TẦNG 5: KIỂM TRA CHÍNH SÁCH & MỨC ĐỘ RỦI RO ---
    approval_node_ids = {n.id for n in graph.nodes if n.type.upper() == NodeType.APPROVAL.value}
    for node in graph.nodes:
        if node.risk_class == "CRITICAL":
            errors.append(
                ValidationIssue(
                    stage="POLICY_RISK",
                    severity="ERROR",
                    code="CRITICAL_RISK_BLOCKED",
                    message=f"Bước `{node.id}` có mức rủi ro `CRITICAL` bị chặn mặc định theo chính sách.",
                    node_id=node.id,
                )
            )
        needs_gate = (
            node.type.upper() == NodeType.CONNECTOR_ACTION.value
            and (graph.request_type.strip().upper() == "CHANGE" or node.risk_class == "HIGH")
        )
        if needs_gate and len(trigger_nodes) == 1:
            # Nếu vẫn có thể đi từ TRIGGER tới bước CONNECTOR_ACTION mà bỏ qua mọi bước APPROVAL -> báo lỗi thiếu cổng duyệt
            if _is_reachable_avoiding(trigger_nodes[0].id, node.id, adjacency, approval_node_ids):
                errors.append(
                    ValidationIssue(
                        stage="POLICY_RISK",
                        severity="ERROR",
                        code="MISSING_APPROVAL_GATE",
                        message=f"Bước `{node.id}` thuộc loại thay đổi hoặc rủi ro cao nhưng chưa có cổng `APPROVAL` chặn phía trước.",
                        node_id=node.id,
                    )
                )

    stage_results["POLICY_RISK"] = not any(e.stage == "POLICY_RISK" for e in errors)

    # --- TẦNG 6: KIỂM TRA GIỚI HẠN TÀI NGUYÊN ---
    if len(graph.nodes) > min(graph.limits.max_nodes, HARD_MAX_NODES):
        errors.append(
            ValidationIssue(
                stage="RESOURCE",
                severity="ERROR",
                code="MAX_NODES_EXCEEDED",
                message=f"Số bước ({len(graph.nodes)}) vượt quá giới hạn tối đa cho phép.",
            )
        )
    if graph.limits.max_retries > HARD_MAX_RETRIES:
        errors.append(
            ValidationIssue(
                stage="RESOURCE",
                severity="ERROR",
                code="MAX_RETRIES_EXCEEDED",
                message=f"Số lần thử lại tối đa ({graph.limits.max_retries}) vượt trần hệ thống ({HARD_MAX_RETRIES}).",
            )
        )
    if graph.limits.max_parallelism > HARD_MAX_PARALLELISM:
        errors.append(
            ValidationIssue(
                stage="RESOURCE",
                severity="ERROR",
                code="MAX_PARALLELISM_EXCEEDED",
                message=f"Độ song song tối đa ({graph.limits.max_parallelism}) vượt trần hệ thống ({HARD_MAX_PARALLELISM}).",
            )
        )
    if graph.limits.max_replans > HARD_MAX_REPLANS:
        errors.append(
            ValidationIssue(
                stage="RESOURCE",
                severity="ERROR",
                code="MAX_REPLANS_EXCEEDED",
                message=f"Số lần lập lại phương án ({graph.limits.max_replans}) vượt trần ({HARD_MAX_REPLANS}).",
            )
        )

    total_est_cost = 0.0
    for node in graph.nodes:
        total_est_cost += node.estimated_cost_usd
        if node.timeout_seconds > graph.limits.max_duration_seconds:
            errors.append(
                ValidationIssue(
                    stage="RESOURCE",
                    severity="ERROR",
                    code="NODE_TIMEOUT_EXCEEDS_RUN_LIMIT",
                    message=f"Thời gian chờ của bước `{node.id}` vượt quá tổng thời gian quy trình.",
                    node_id=node.id,
                )
            )
    if total_est_cost > graph.limits.max_estimated_cost_usd:
        errors.append(
            ValidationIssue(
                stage="RESOURCE",
                severity="ERROR",
                code="ESTIMATED_COST_EXCEEDED",
                message=f"Tổng chi phí ước tính ({total_est_cost:.2f} USD) vượt trần ({graph.limits.max_estimated_cost_usd:.2f} USD).",
            )
        )

    stage_results["RESOURCE"] = not any(e.stage == "RESOURCE" for e in errors)

    # --- TẦNG 7: KIỂM TRA TIÊU CHÍ XÁC MINH ---
    material_nodes = [
        n for n in graph.nodes if n.type.upper() in {NodeType.CONNECTOR_ACTION.value, NodeType.HUMAN_TASK.value}
    ]
    verification_nodes = [n for n in graph.nodes if n.type.upper() == NodeType.VERIFICATION.value]
    verification_ids = {n.id for n in verification_nodes}

    if material_nodes and not verification_nodes:
        errors.append(
            ValidationIssue(
                stage="VERIFICATION",
                severity="ERROR",
                code="MISSING_VERIFICATION_NODE",
                message="Quy trình có thao tác ngoài hoặc việc nhân sự bắt buộc phải có bước `VERIFICATION`.",
            )
        )

    for v_node in verification_nodes:
        postconds = v_node.config.get("postconditions") or []
        ev_sources = v_node.config.get("evidence_sources") or []
        if not postconds or not ev_sources:
            errors.append(
                ValidationIssue(
                    stage="VERIFICATION",
                    severity="ERROR",
                    code="EMPTY_VERIFICATION_CRITERIA",
                    message=f"Bước xác minh `{v_node.id}` phải khai báo đầy đủ `postconditions` và `evidence_sources`.",
                    node_id=v_node.id,
                )
            )

    if material_nodes and verification_nodes and end_nodes:
        for m_node in material_nodes:
            for e_node in end_nodes:
                if _is_reachable_avoiding(m_node.id, e_node.id, adjacency, verification_ids):
                    errors.append(
                        ValidationIssue(
                            stage="VERIFICATION",
                            severity="ERROR",
                            code="VERIFICATION_BYPASSED_TO_END",
                            message=f"Thao tác trọng yếu `{m_node.id}` đi tới `{e_node.id}` mà không qua bước `VERIFICATION`.",
                            node_id=m_node.id,
                        )
                    )

    stage_results["VERIFICATION"] = not any(e.stage == "VERIFICATION" for e in errors)

    return WorkflowValidationReport(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        stage_results=stage_results,
    )
