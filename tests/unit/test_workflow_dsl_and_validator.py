"""Kiểm thử đơn vị cho điều kiện an toàn, kiểm định 7 tầng, 5 mẫu quy trình và chấm điểm ứng viên."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.modules.workflows.dsl.conditions import evaluate_condition_expr, validate_condition_expr
from app.modules.workflows.scoring import score_candidate_workflows
from app.modules.workflows.validator import validate_workflow_graph

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "data" / "workflow_templates"


def _load_template(filename: str) -> dict:
    return json.loads((TEMPLATES_DIR / filename).read_text(encoding="utf-8"))


def test_safe_condition_evaluator_and_rejection_of_code_strings() -> None:
    """Đảm bảo bộ đọc điều kiện hỗ trợ cấu trúc an toàn và chặn chuỗi mã lệnh."""
    expr = {
        "all": [
            {"op": "eq", "field": "approval.status", "value": "APPROVED"},
            {"op": "in", "field": "request.priority", "value": ["P1_CRITICAL", "P2_HIGH"]},
            {"not": {"op": "eq", "field": "risk_level", "value": "CRITICAL"}},
        ]
    }
    assert validate_condition_expr(expr) == []
    assert (
        evaluate_condition_expr(
            expr,
            {"approval": {"status": "APPROVED"}, "request": {"priority": "P1_CRITICAL"}, "risk_level": "HIGH"},
        )
        is True
    )
    assert (
        evaluate_condition_expr(
            expr,
            {"approval": {"status": "REJECTED"}, "request": {"priority": "P1_CRITICAL"}, "risk_level": "HIGH"},
        )
        is False
    )

    # Từ chối chuỗi mã lệnh hoặc toán tử lạ
    assert validate_condition_expr("__import__('os').system('ls')")
    assert validate_condition_expr({"op": "eval_python", "field": "a", "value": "1"})


def test_all_five_workflow_templates_pass_seven_stage_validation() -> None:
    """Xác nhận cả 5 mẫu sơ đồ quy trình chuẩn đều vượt qua trọn vẹn 7 tầng kiểm tra."""
    template_files = [
        "incident_v1.json",
        "change_request_v1.json",
        "service_request_v1.json",
        "customer_onboarding_v1.json",
        "internal_task_v1.json",
    ]
    for filename in template_files:
        graph = _load_template(filename)
        report = validate_workflow_graph(graph)
        assert report.valid is True, f"Mẫu {filename} gặp lỗi: {report.errors}"
        assert all(report.stage_results.values()), f"Mẫu {filename} chưa đạt đủ 7 tầng: {report.stage_results}"


def test_seven_stage_validator_catches_errors_at_each_stage() -> None:
    """Kiểm tra từng tầng trong 7 tầng phát hiện đúng lỗi bảo mật và cấu trúc."""
    base_incident = _load_template("incident_v1.json")

    # Tầng 1: Phát hiện chu trình (cycle)
    cyclic = copy.deepcopy(base_incident)
    cyclic["edges"].append({"id": "e_cycle", "source": "n4_github_issue", "target": "n2_classify"})
    r_cycle = validate_workflow_graph(cyclic)
    assert r_cycle.valid is False
    assert any(e.code == "CYCLE_DETECTED" for e in r_cycle.errors)

    # Tầng 1: Từ chối loại bước chưa đăng ký
    unknown_type = copy.deepcopy(base_incident)
    unknown_type["nodes"][1]["type"] = "RUN_SHELL_SCRIPT"
    r_unknown = validate_workflow_graph(unknown_type)
    assert r_unknown.valid is False
    assert any(e.code == "UNKNOWN_NODE_TYPE" for e in r_unknown.errors)

    # Tầng 2: Thiếu ánh xạ đầu ra từ bước tiền nhiệm
    bad_data = copy.deepcopy(base_incident)
    bad_data["nodes"][3]["input_mapping"] = {"bad": "n2_classify.khong_ton_tai"}
    r_data = validate_workflow_graph(bad_data)
    assert r_data.valid is False
    assert any(e.code == "MISSING_UPSTREAM_OUTPUT_KEY" for e in r_data.errors)

    # Tầng 3 & 4: Hành động bị cấm `deploy_production` và thiếu resource_scope cụ thể
    forbidden = copy.deepcopy(base_incident)
    forbidden["nodes"][3]["config"]["action"] = "deploy_production"
    forbidden["nodes"][3]["resource_scope"] = "*"
    r_perm = validate_workflow_graph(forbidden)
    assert r_perm.valid is False
    assert any(e.code == "FORBIDDEN_DEMO_ACTION" for e in r_perm.errors)
    assert any(e.code == "INVALID_RESOURCE_SCOPE" for e in r_perm.errors)

    # Tầng 5: Yêu cầu CHANGE bỏ qua bước APPROVAL trước CONNECTOR_ACTION -> bị chặn
    change_no_approval = _load_template("change_request_v1.json")
    change_no_approval["edges"] = [
        e for e in change_no_approval["edges"] if e["id"] not in {"e3", "e4"}
    ]
    change_no_approval["edges"].append({"id": "e_bypass", "source": "n3_risk_analysis", "target": "n5_action"})
    change_no_approval["edges"].append({"id": "e_dead", "source": "n3_risk_analysis", "target": "n4_approval"})
    change_no_approval["edges"].append({"id": "e_merge", "source": "n4_approval", "target": "n5_action"})
    r_policy = validate_workflow_graph(change_no_approval)
    assert r_policy.valid is False
    assert any(e.code == "MISSING_APPROVAL_GATE" for e in r_policy.errors)

    # Tầng 5: Bước mức rủi ro CRITICAL bị chặn
    crit_graph = copy.deepcopy(base_incident)
    crit_graph["nodes"][3]["risk_class"] = "CRITICAL"
    r_crit = validate_workflow_graph(crit_graph)
    assert r_crit.valid is False
    assert any(e.code == "CRITICAL_RISK_BLOCKED" for e in r_crit.errors)

    # Tầng 6: Vượt giới hạn retry cho phép (> 3)
    over_limit = copy.deepcopy(base_incident)
    over_limit["limits"]["max_retries"] = 5
    r_limit = validate_workflow_graph(over_limit)
    assert r_limit.valid is False
    assert any(e.code == "MAX_RETRIES_EXCEEDED" for e in r_limit.errors)

    # Tầng 7: Bỏ trống postconditions/evidence_sources ở bước VERIFICATION
    bad_verify = copy.deepcopy(base_incident)
    bad_verify["nodes"][5]["config"]["postconditions"] = []
    r_verify = validate_workflow_graph(bad_verify)
    assert r_verify.valid is False
    assert any(e.code == "EMPTY_VERIFICATION_CRITERIA" for e in r_verify.errors)


def test_candidate_scoring_never_ranks_ineligible_candidate() -> None:
    """Ứng viên vi phạm kiểm định 7 tầng không bao giờ được xếp hạng cùng ứng viên hợp lệ."""
    valid_incident = _load_template("incident_v1.json")
    valid_service = _load_template("service_request_v1.json")
    invalid_graph = _load_template("incident_v1.json")
    invalid_graph["workflow_id"] = "bad-candidate"
    invalid_graph["nodes"][3]["risk_class"] = "CRITICAL"

    ranked = score_candidate_workflows([invalid_graph, valid_service, valid_incident])
    assert ranked[0].eligible is True and ranked[0].rank == 1
    assert ranked[1].eligible is True and ranked[1].rank == 2
    assert ranked[2].workflow_id == "bad-candidate"
    assert ranked[2].eligible is False
    assert ranked[2].rank is None
    assert ranked[2].total_score is None
