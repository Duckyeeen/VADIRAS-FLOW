"""Cổng điều phối công cụ tập trung: mọi lệnh gọi công cụ ngoài đều phải qua danh sách cho phép và cổng kiểm soát."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError

from .execution_guard import ExecutionGuard
from .policy_engine import PolicyEvaluationContext

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ToolExecutionReceipt:
    """Biên nhận thực thi công cụ kèm mã quyết định kiểm soát và kết quả trả về."""

    tool_name: str
    policy_decision_id: str
    parameter_hash: str
    output: dict[str, Any]


class ToolBroker:
    """Cổng điều phối công cụ tập trung ngăn không cho AI hoặc quy trình gọi công cụ tùy tiện."""

    def __init__(self, *, guard: ExecutionGuard | None = None) -> None:
        self._guard = guard or ExecutionGuard()
        self._tools: dict[str, ToolHandler] = {}

    def register_tool(self, tool_name: str, handler: ToolHandler) -> None:
        """Đăng ký một công cụ hợp lệ vào danh sách được phép thực thi."""
        self._tools[tool_name.strip().lower()] = handler

    def is_allowlisted(self, tool_name: str) -> bool:
        """Kiểm tra công cụ có nằm trong danh sách cho phép hay không."""
        return tool_name.strip().lower() in self._tools

    async def execute(
        self,
        session: AsyncSession,
        *,
        tool_name: str,
        context: PolicyEvaluationContext,
        request_id: str | None = None,
        workflow_run_id: str | None = None,
        workflow_version_id: str | None = None,
        node_id: str = "tool_node",
        approval_id: str | None = None,
    ) -> ToolExecutionReceipt:
        """Kiểm tra danh sách công cụ cho phép + cổng kiểm soát cuối cùng trước khi gọi hàm xử lý.

        Các bước bảo vệ:
        1. Từ chối ngay lập tức nếu `tool_name` chưa đăng ký trong danh sách cho phép.
        2. Gọi `ExecutionGuard.authorize_side_effect` kiểm tra lại quyền, rủi ro, ngân sách
           và 7 yếu tố ràng buộc của lệnh phê duyệt ngay trước khi chạy.
        3. Chỉ khi đạt chuẩn mới gọi hàm xử lý công cụ và trả về `ToolExecutionReceipt`.
        """
        normalized_name = tool_name.strip().lower()
        handler = self._tools.get(normalized_name)
        if handler is None:
            raise AuthorizationError(
                f"Công cụ `{tool_name}` không nằm trong danh sách được phép gọi.",
                code="TOOL_NOT_ALLOWLISTED",
            )

        decision = await self._guard.authorize_side_effect(
            session,
            context=context,
            request_id=request_id,
            workflow_run_id=workflow_run_id,
            workflow_version_id=workflow_version_id,
            node_id=node_id,
            approval_id=approval_id,
        )

        output = await handler(dict(context.parameters))
        return ToolExecutionReceipt(
            tool_name=normalized_name,
            policy_decision_id=decision.id,
            parameter_hash=decision.parameter_hash,
            output=output,
        )
