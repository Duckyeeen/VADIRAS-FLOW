"""Bộ kiểm tra và đánh giá biểu thức điều kiện rẽ nhánh an toàn (tuyệt đối không dùng `eval`)."""

from __future__ import annotations

import re
from typing import Any

# Chỉ cho phép đường dẫn trường dữ liệu gồm chữ cái, số, dấu gạch dưới và dấu chấm
_FIELD_PATH_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
_COMPARISON_OPERATORS = frozenset({"eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "exists", "contains"})
_LOGICAL_OPERATORS = frozenset({"all", "any", "not"})
MAX_CONDITION_DEPTH = 5


def _resolve_field_path(context: dict[str, Any], field_path: str) -> tuple[bool, Any]:
    """Lấy giá trị từ từ điển ngữ cảnh theo đường dẫn dạng `a.b.c` mà không chạy mã động."""
    current: Any = context
    for part in field_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def validate_condition_expr(expr: Any, *, depth: int = 1) -> list[str]:
    """Kiểm tra tính hợp lệ và an toàn của một biểu thức điều kiện dạng JSON.

    Thuật toán an toàn:
    1. Từ chối mọi chuỗi mã lệnh thô (`str`) để tránh chèn lệnh Python/biểu thức nguy hiểm.
    2. Giới hạn độ sâu lồng tối đa 5 cấp để chống treo bộ phân tích.
    3. Kiểm tra toán tử phải nằm trong danh sách cho phép (`all`/`any`/`not` hoặc `eq`/`neq`/`in`/...).
    4. Kiểm tra tên trường `field` chỉ chứa ký tự an toàn `[a-zA-Z0-9_.]`.
    Đầu ra: danh sách thông báo lỗi (rỗng nếu biểu thức hoàn toàn hợp lệ).
    """
    if depth > MAX_CONDITION_DEPTH:
        return [f"Biểu thức điều kiện vượt quá độ sâu cho phép ({MAX_CONDITION_DEPTH} cấp)."]

    if not isinstance(expr, dict):
        return ["Điều kiện rẽ nhánh phải là đối tượng JSON có cấu trúc, không chấp nhận chuỗi mã lệnh."]

    if any(op in expr for op in _LOGICAL_OPERATORS):
        errors: list[str] = []
        if len(expr) != 1:
            return ["Mỗi nhóm logic chỉ được chứa duy nhất một khóa `all`, `any` hoặc `not`."]
        if "not" in expr:
            return validate_condition_expr(expr["not"], depth=depth + 1)
        group_key = "all" if "all" in expr else "any"
        children = expr[group_key]
        if not isinstance(children, list) or not children:
            return [f"Khóa `{group_key}` phải là danh sách không rỗng các điều kiện con."]
        for child in children:
            errors.extend(validate_condition_expr(child, depth=depth + 1))
        return errors

    op = expr.get("op")
    field = expr.get("field")
    if not isinstance(op, str) or op not in _COMPARISON_OPERATORS:
        return [f"Toán tử `{op}` không nằm trong danh sách cho phép."]
    if not isinstance(field, str) or not _FIELD_PATH_PATTERN.fullmatch(field):
        return [f"Tên trường `{field}` chứa ký tự không hợp lệ."]
    if op != "exists" and "value" not in expr:
        return [f"Toán tử `{op}` bắt buộc phải khai báo trường `value`."]
    if op in {"in", "not_in"} and not isinstance(expr.get("value"), list):
        return [f"Toán tử `{op}` yêu cầu `value` phải là một danh sách."]
    return []


def evaluate_condition_expr(expr: dict[str, Any], context: dict[str, Any]) -> bool:
    """Đánh giá kết quả đúng/sai của một biểu thức điều kiện an toàn trên ngữ cảnh chạy thực tế.

    Đầu vào: `expr` (đã qua kiểm tra cấu trúc) và `context` (dữ liệu của lượt chạy).
    Đầu ra: `True` hoặc `False`.
    """
    if errors := validate_condition_expr(expr):
        raise ValueError("; ".join(errors))

    if "all" in expr:
        return all(evaluate_condition_expr(child, context) for child in expr["all"])
    if "any" in expr:
        return any(evaluate_condition_expr(child, context) for child in expr["any"])
    if "not" in expr:
        return not evaluate_condition_expr(expr["not"], context)

    op = str(expr["op"])
    field = str(expr["field"])
    found, actual = _resolve_field_path(context, field)
    expected = expr.get("value")

    if op == "exists":
        want_exists = True if expected is None else bool(expected)
        return (found and actual is not None) if want_exists else (not found or actual is None)
    if not found:
        return False

    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    if op == "contains":
        return isinstance(actual, (str, list, tuple, set, dict)) and expected in actual
    if op in {"gt", "gte", "lt", "lte"}:
        if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
            return False
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        return actual <= expected
    return False
