"""Các hàm tính toán 7 nhóm chỉ số thống kê hiệu suất, SLA, tự động hóa và chi phí AI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import statistics
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_intelligence.models import AgentRun, AgentTask, LLMCallRecord
from app.modules.governance.models import ApprovalDecision, ApprovalRequest
from app.modules.identity.models import Department
from app.modules.requests.models import HumanTask, HumanTaskStatus, Request, RequestStatus
from app.modules.verification.models import VerificationOutcome, VerificationRun
from app.modules.workflows.models import NodeRunStatus, WorkflowDefinition, WorkflowNodeRun, WorkflowRun

from .sla import evaluate_request_sla


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(sorted_values[0], 2)
    idx = min(len(sorted_values) - 1, max(0, int(round((pct / 100.0) * (len(sorted_values) - 1)))))
    return round(sorted_values[idx], 2)


@dataclass(frozen=True, slots=True)
class AnalyticsFilter:
    """Bộ lọc chung cho 7 tuyến API thống kê."""

    organization_id: str
    from_date: datetime | None = None
    to_date: datetime | None = None
    department_id: str | None = None
    request_type: str | None = None
    workflow_id: str | None = None
    domain_pack: str | None = None


async def _load_filtered_requests(
    session: AsyncSession,
    flt: AnalyticsFilter,
) -> list[Request]:
    conds: list[sa.ColumnElement[bool]] = [Request.organization_id == flt.organization_id]
    if flt.from_date is not None:
        conds.append(Request.created_at >= _normalize_utc(flt.from_date))
    if flt.to_date is not None:
        conds.append(Request.created_at <= _normalize_utc(flt.to_date))
    if flt.department_id:
        conds.append(Request.department_id == flt.department_id)
    if flt.request_type:
        conds.append(Request.request_type == flt.request_type.strip().upper())
    return list((await session.execute(sa.select(Request).where(*conds))).scalars().all())


async def _load_filtered_runs(
    session: AsyncSession,
    flt: AnalyticsFilter,
    req_ids: set[str] | None = None,
) -> list[WorkflowRun]:
    conds: list[sa.ColumnElement[bool]] = [WorkflowRun.organization_id == flt.organization_id]
    if flt.from_date is not None:
        conds.append(WorkflowRun.created_at >= _normalize_utc(flt.from_date))
    if flt.to_date is not None:
        conds.append(WorkflowRun.created_at <= _normalize_utc(flt.to_date))
    if flt.workflow_id:
        conds.append(WorkflowRun.workflow_definition_id == flt.workflow_id)

    rows = list((await session.execute(sa.select(WorkflowRun).where(*conds))).scalars().all())
    if req_ids is not None:
        rows = [r for r in rows if r.request_id in req_ids]
    if flt.domain_pack:
        defs = list(
            (
                await session.execute(
                    sa.select(WorkflowDefinition).where(
                        WorkflowDefinition.organization_id == flt.organization_id,
                        WorkflowDefinition.domain_pack == flt.domain_pack,
                    )
                )
            )
            .scalars()
            .all()
        )
        allowed_def_ids = {d.id for d in defs}
        rows = [r for r in rows if r.workflow_definition_id in allowed_def_ids]
    return rows


async def compute_overview_metrics(session: AsyncSession, flt: AnalyticsFilter) -> dict[str, Any]:
    """Tính tổng quan khối lượng yêu cầu, tỷ lệ xác minh và độ tin cậy của lượt chạy."""
    requests = await _load_filtered_requests(session, flt)
    req_ids = {r.id for r in requests}
    runs = await _load_filtered_runs(session, flt, req_ids if (flt.department_id or flt.request_type) else None)

    ver_rows = list(
        (
            await session.execute(
                sa.select(VerificationRun).where(VerificationRun.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    if req_ids and (flt.department_id or flt.request_type):
        ver_rows = [v for v in ver_rows if v.request_id in req_ids]

    total_requests = len(requests)
    resolved_requests = sum(1 for r in requests if r.status == RequestStatus.RESOLVED.value)
    verified_requests = sum(1 for r in requests if r.business_outcome == VerificationOutcome.VERIFIED.value)

    total_runs = len(runs)
    completed_runs = sum(1 for r in runs if r.status in {"COMPLETED", "PARTIALLY_COMPLETED"})
    replanned_runs = sum(1 for r in runs if r.replan_count > 0)

    total_vers = len(ver_rows)
    failed_or_unverified = sum(
        1 for v in ver_rows if v.outcome in {VerificationOutcome.FAILED.value, VerificationOutcome.UNVERIFIED.value}
    )

    return {
        "organization_id": flt.organization_id,
        "window": {
            "from_date": flt.from_date.isoformat() if flt.from_date else None,
            "to_date": flt.to_date.isoformat() if flt.to_date else None,
        },
        "request_volume": total_requests,
        "resolved_requests": resolved_requests,
        "verified_requests": verified_requests,
        "verified_resolution_rate": {
            "numerator": verified_requests,
            "denominator": total_requests,
            "value": round(verified_requests / total_requests, 4) if total_requests else 0.0,
            "definition": "Số yêu cầu đạt kết quả xác minh VERIFIED trên tổng số yêu cầu trong kỳ.",
        },
        "workflow_success_rate": {
            "numerator": completed_runs,
            "denominator": total_runs,
            "value": round(completed_runs / total_runs, 4) if total_runs else 0.0,
            "definition": "Số lượt chạy hoàn thành chuẩn trên tổng số lượt chạy đã khởi phát.",
        },
        "replan_rate": {
            "numerator": replanned_runs,
            "denominator": total_runs,
            "value": round(replanned_runs / total_runs, 4) if total_runs else 0.0,
            "definition": "Số lượt chạy có ít nhất 1 đề xuất lập lại trên tổng số lượt chạy.",
        },
        "verification_failure_rate": {
            "numerator": failed_or_unverified,
            "denominator": total_vers,
            "value": round(failed_or_unverified / total_vers, 4) if total_vers else 0.0,
            "definition": "Số lượt xác minh FAILED hoặc UNVERIFIED trên tổng số lượt xác minh.",
        },
    }


async def compute_sla_metrics(session: AsyncSession, flt: AnalyticsFilter) -> dict[str, Any]:
    """Tính tỷ lệ tuân thủ SLA kèm thời gian giải quyết trung bình, trung vị và p95."""
    requests = await _load_filtered_requests(session, flt)
    now = datetime.now(timezone.utc)

    met_count = 0
    breached_count = 0
    warning_count = 0
    on_track_count = 0
    resolution_minutes: list[float] = []

    for req in requests:
        sla = evaluate_request_sla(
            created_at=req.created_at,
            due_at=req.due_at,
            status=req.status,
            business_outcome=req.business_outcome,
            now=now,
        )
        state = sla["sla_state"]
        if state == "MET":
            met_count += 1
        elif state == "BREACHED":
            breached_count += 1
        elif state == "WARNING":
            warning_count += 1
        else:
            on_track_count += 1

        if req.status == RequestStatus.RESOLVED.value or req.business_outcome == VerificationOutcome.VERIFIED.value:
            dur_min = max(
                0.0,
                (_normalize_utc(req.updated_at) - _normalize_utc(req.created_at)).total_seconds() / 60.0,
            )
            resolution_minutes.append(dur_min)

    resolution_minutes.sort()
    total = len(requests)
    return {
        "organization_id": flt.organization_id,
        "total_requests": total,
        "sla_compliance": {
            "numerator": met_count + on_track_count + warning_count,
            "denominator": total,
            "value": round((total - breached_count) / total, 4) if total else 1.0,
            "open_requests_policy": "Yêu cầu đang mở chưa quá hạn được tính chưa vi phạm (ON_TRACK/WARNING); chỉ đánh BREACHED khi vượt `due_at`.",
        },
        "breakdown": {
            "met": met_count,
            "on_track": on_track_count,
            "warning": warning_count,
            "breached": breached_count,
        },
        "mean_resolution_minutes": round(statistics.mean(resolution_minutes), 2) if resolution_minutes else 0.0,
        "median_resolution_minutes": round(statistics.median(resolution_minutes), 2) if resolution_minutes else 0.0,
        "p95_resolution_minutes": _percentile(resolution_minutes, 95.0),
    }


async def compute_automation_metrics(session: AsyncSession, flt: AnalyticsFilter) -> dict[str, Any]:
    """Tính tỷ lệ tự động hóa theo bước đủ điều kiện, tỷ lệ cần người duyệt và độ trễ duyệt."""
    requests = await _load_filtered_requests(session, flt)
    req_ids = {r.id for r in requests}
    runs = await _load_filtered_runs(session, flt, req_ids if (flt.department_id or flt.request_type) else None)
    run_ids = {r.id for r in runs}

    node_rows = list(
        (
            await session.execute(
                sa.select(WorkflowNodeRun).where(WorkflowNodeRun.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    if run_ids or flt.workflow_id or flt.domain_pack or flt.department_id or flt.request_type:
        node_rows = [n for n in node_rows if n.workflow_run_id in run_ids]

    eligible_nodes = [
        n for n in node_rows if n.node_type not in {"TRIGGER", "END"} and n.status == NodeRunStatus.COMPLETED.value
    ]
    automated_nodes = [n for n in eligible_nodes if n.node_type not in {"HUMAN_TASK", "APPROVAL"}]

    approvals = list(
        (
            await session.execute(
                sa.select(ApprovalRequest).where(ApprovalRequest.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    decisions = list(
        (
            await session.execute(
                sa.select(ApprovalDecision).where(ApprovalDecision.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    app_created_by_id = {a.id: a.created_at for a in approvals}
    latencies_sec: list[float] = []
    for dec in decisions:
        c_at = app_created_by_id.get(dec.approval_request_id)
        if c_at is not None:
            latencies_sec.append(
                max(0.0, (_normalize_utc(dec.decided_at) - _normalize_utc(c_at)).total_seconds())
            )

    human_tasks = list(
        (
            await session.execute(
                sa.select(HumanTask).where(HumanTask.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    human_run_ids = {a.workflow_run_id for a in approvals if a.workflow_run_id} | {
        t.workflow_run_id for t in human_tasks if t.workflow_run_id
    }
    runs_with_human = sum(1 for r in runs if r.id in human_run_ids)

    return {
        "organization_id": flt.organization_id,
        "automation_rate": {
            "numerator": len(automated_nodes),
            "denominator": len(eligible_nodes),
            "value": round(len(automated_nodes) / len(eligible_nodes), 4) if eligible_nodes else 0.0,
            "definition": "Số bước nghiệp vụ hoàn tất tự động (không tính `HUMAN_TASK`/`APPROVAL`) trên tổng số bước đủ điều kiện.",
        },
        "human_intervention_rate": {
            "numerator": runs_with_human,
            "denominator": len(runs),
            "value": round(runs_with_human / len(runs), 4) if runs else 0.0,
            "definition": "Số lượt chạy có yêu cầu phê duyệt hoặc đầu việc nhân sự trên tổng số lượt chạy.",
        },
        "approval_latency_seconds": {
            "count": len(latencies_sec),
            "mean": round(statistics.mean(latencies_sec), 2) if latencies_sec else 0.0,
            "median": round(statistics.median(latencies_sec), 2) if latencies_sec else 0.0,
        },
    }


async def compute_cost_metrics(session: AsyncSession, flt: AnalyticsFilter) -> dict[str, Any]:
    """Tổng hợp chi phí AI và tách bạch tuyệt đối 3 nhãn nguồn: `ACTUAL`, `ESTIMATED`, `UNKNOWN`."""
    requests = await _load_filtered_requests(session, flt)
    req_ids = {r.id for r in requests}

    conds: list[sa.ColumnElement[bool]] = [LLMCallRecord.organization_id == flt.organization_id]
    if flt.from_date is not None:
        conds.append(LLMCallRecord.created_at >= _normalize_utc(flt.from_date))
    if flt.to_date is not None:
        conds.append(LLMCallRecord.created_at <= _normalize_utc(flt.to_date))

    calls = list((await session.execute(sa.select(LLMCallRecord).where(*conds))).scalars().all())
    if flt.department_id or flt.request_type:
        calls = [c for c in calls if c.request_id in req_ids]

    by_source: dict[str, dict[str, Any]] = {
        "ACTUAL": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
        "ESTIMATED": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
        "UNKNOWN": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
    }
    for call in calls:
        src = call.cost_source if call.cost_source in by_source else "UNKNOWN"
        bucket = by_source[src]
        bucket["calls"] += 1
        bucket["prompt_tokens"] += int(call.prompt_tokens)
        bucket["completion_tokens"] += int(call.completion_tokens)
        bucket["cost_usd"] = round(bucket["cost_usd"] + float(call.cost_usd), 6)

    total_calls = len(calls)
    return {
        "organization_id": flt.organization_id,
        "total_llm_calls": total_calls,
        "cost_by_source": by_source,
        "cost_disclosure": "Chi phí `ESTIMATED` là ước tính nội bộ, không phải hóa đơn thực tế từ nhà cung cấp.",
    }


async def compute_agent_metrics(session: AsyncSession, flt: AnalyticsFilter) -> dict[str, Any]:
    """Tính tỷ lệ thành công và thất bại/thử lại của nhóm 9 trợ lý AI theo từng vai trò."""
    runs = list(
        (
            await session.execute(
                sa.select(AgentRun).where(AgentRun.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    tasks = list(
        (
            await session.execute(
                sa.select(AgentTask).where(AgentTask.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )

    by_role: dict[str, dict[str, Any]] = {}
    for run in runs:
        bucket = by_role.setdefault(
            run.role_code,
            {"role_code": run.role_code, "total_runs": 0, "succeeded": 0, "failed": 0, "avg_latency_ms": 0.0, "_lats": []},
        )
        bucket["total_runs"] += 1
        if run.status in {"COMPLETED", "SUCCEEDED", "REPAIRED"}:
            bucket["succeeded"] += 1
        else:
            bucket["failed"] += 1
        bucket["_lats"].append(float(run.latency_ms))

    role_items: list[dict[str, Any]] = []
    for item in by_role.values():
        lats = item.pop("_lats")
        item["avg_latency_ms"] = round(statistics.mean(lats), 2) if lats else 0.0
        role_items.append(item)

    total_runs = len(runs)
    succeeded_runs = sum(1 for r in runs if r.status in {"COMPLETED", "SUCCEEDED", "REPAIRED"})
    failed_runs = total_runs - succeeded_runs
    return {
        "organization_id": flt.organization_id,
        "total_agent_tasks": len(tasks),
        "total_agent_runs": total_runs,
        "agent_success_rate": {
            "numerator": succeeded_runs,
            "denominator": total_runs,
            "value": round(succeeded_runs / total_runs, 4) if total_runs else 0.0,
        },
        "agent_failure_rate": {
            "numerator": failed_runs,
            "denominator": total_runs,
            "value": round(failed_runs / total_runs, 4) if total_runs else 0.0,
        },
        "by_role": role_items,
    }


async def compute_department_metrics(session: AsyncSession, flt: AnalyticsFilter) -> dict[str, Any]:
    """Thống kê khối lượng yêu cầu, đầu việc mở/hoàn tất và trễ hạn SLA theo từng phòng ban."""
    depts = list(
        (
            await session.execute(
                sa.select(Department).where(Department.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    requests = await _load_filtered_requests(session, flt)
    tasks = list(
        (
            await session.execute(
                sa.select(HumanTask).where(HumanTask.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)

    items: list[dict[str, Any]] = []
    for dept in depts:
        d_reqs = [r for r in requests if r.department_id == dept.id]
        d_tasks = [t for t in tasks if t.department_id == dept.id]
        breached = sum(
            1
            for r in d_reqs
            if evaluate_request_sla(
                created_at=r.created_at,
                due_at=r.due_at,
                status=r.status,
                business_outcome=r.business_outcome,
                now=now,
            )["breached"]
        )
        items.append(
            {
                "department_id": dept.id,
                "department_code": dept.code,
                "department_name": dept.name,
                "request_count": len(d_reqs),
                "open_tasks": sum(1 for t in d_tasks if t.status in {HumanTaskStatus.OPEN.value, HumanTaskStatus.CLAIMED.value}),
                "completed_tasks": sum(1 for t in d_tasks if t.status == HumanTaskStatus.COMPLETED.value),
                "sla_breached_count": breached,
            }
        )

    return {"organization_id": flt.organization_id, "departments": items}


async def compute_industry_metrics(session: AsyncSession, flt: AnalyticsFilter) -> dict[str, Any]:
    """Thống kê khối lượng theo gói miền nghiệp vụ (`domain_pack`) và phân loại yêu cầu."""
    requests = await _load_filtered_requests(session, flt)
    defs = list(
        (
            await session.execute(
                sa.select(WorkflowDefinition).where(WorkflowDefinition.organization_id == flt.organization_id)
            )
        )
        .scalars()
        .all()
    )
    runs = await _load_filtered_runs(session, flt)

    by_request_type: dict[str, dict[str, Any]] = {}
    for req in requests:
        bucket = by_request_type.setdefault(
            req.request_type, {"request_type": req.request_type, "total": 0, "verified": 0}
        )
        bucket["total"] += 1
        if req.business_outcome == VerificationOutcome.VERIFIED.value:
            bucket["verified"] += 1

    defs_by_id = {d.id: d.domain_pack for d in defs}
    by_domain_pack: dict[str, dict[str, Any]] = {}
    for run in runs:
        pack = defs_by_id.get(run.workflow_definition_id, "enterprise_core")
        bucket = by_domain_pack.setdefault(pack, {"domain_pack": pack, "runs": 0, "completed": 0})
        bucket["runs"] += 1
        if run.status == "COMPLETED":
            bucket["completed"] += 1

    return {
        "organization_id": flt.organization_id,
        "by_request_type": list(by_request_type.values()),
        "by_domain_pack": list(by_domain_pack.values()),
    }
