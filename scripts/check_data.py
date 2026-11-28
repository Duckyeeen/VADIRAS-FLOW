"""Validate the VADIRAS FLOW sample datasets."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]

ALLOWED_SOURCE_CHANNELS = {"web_form", "email_webhook", "api_batch"}
ALLOWED_CUSTOMER_TIERS = {"free", "standard", "enterprise"}
ALLOWED_CATEGORIES = {
    "bug_backend",
    "bug_frontend",
    "account_access",
    "billing_refund",
    "feature_request",
    "how_to_question",
    "out_of_scope_or_spam",
}
ALLOWED_PRIORITIES = {"P1_CRITICAL", "P2_HIGH", "P3_MEDIUM", "P4_LOW"}
ALLOWED_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
ALLOWED_TEAMS = {
    "Backend-Reporting",
    "Backend-Core",
    "Frontend-Web",
    "IAM-Security",
    "Billing-Ops",
    "Customer-Success",
    "Triage-Human",
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE_OR_ID_RE = re.compile(
    r"(?<!\d)(?:0\d{9}|\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|\d{12})(?!\d)"
)
PLACEHOLDER_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "example.test"}


def load_json(relative_path: str) -> Any:
    """Load JSON from the project root and explain file/JSON errors clearly."""
    path = PROJECT_ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path.relative_to(PROJECT_ROOT)}")

    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"JSON không hợp lệ trong {path.relative_to(PROJECT_ROOT)} "
            f"(dòng {error.lineno}, cột {error.colno}): {error.msg}"
        ) from error


def require_list(value: Any, label: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{label} phải là một JSON array [...].")
        return []
    return value


def check_unique_ids(
    rows: list[Any], field: str, label: str, errors: list[str]
) -> None:
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"{label} mục {index} phải là object JSON.")
            continue
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label} mục {index} thiếu {field} hợp lệ.")
        elif value in seen:
            errors.append(f"{label} bị trùng {field}: {value}")
        else:
            seen.add(value)


def check_choice(
    value: Any, allowed: set[str], field: str, case_id: str, errors: list[str]
) -> None:
    if not isinstance(value, str) or value not in allowed:
        errors.append(
            f"{case_id}: {field}={value!r} không nằm trong schema. "
            f"Giá trị hợp lệ: {', '.join(sorted(allowed))}."
        )


def check_request(case_id: str, request: Any, errors: list[str]) -> None:
    if not isinstance(request, dict):
        errors.append(f"{case_id}: request phải là object JSON.")
        return

    required_request_fields = {
        "source_channel",
        "customer",
        "product",
        "subject",
        "description",
        "requested_action",
    }
    for field in sorted(required_request_fields - request.keys()):
        errors.append(f"{case_id}: request thiếu trường {field}.")

    check_choice(
        request.get("source_channel"), ALLOWED_SOURCE_CHANNELS,
        "request.source_channel", case_id, errors
    )

    customer = request.get("customer")
    if not isinstance(customer, dict):
        errors.append(f"{case_id}: request.customer phải là object JSON.")
    else:
        for field in ("customer_id", "organization", "contact_email", "tier"):
            if not isinstance(customer.get(field), str) or not customer[field].strip():
                errors.append(f"{case_id}: customer.{field} phải là chuỗi không rỗng.")
        check_choice(
            customer.get("tier"), ALLOWED_CUSTOMER_TIERS,
            "request.customer.tier", case_id, errors
        )
        email = customer.get("contact_email", "")
        if isinstance(email, str) and not EMAIL_RE.fullmatch(email):
            errors.append(f"{case_id}: customer.contact_email không đúng định dạng email.")

    product = request.get("product")
    if not isinstance(product, dict):
        errors.append(f"{case_id}: request.product phải là object JSON.")
    else:
        for field in ("name", "module", "version", "environment"):
            if not isinstance(product.get(field), str) or not product[field].strip():
                errors.append(f"{case_id}: product.{field} phải là chuỗi không rỗng.")

    for field in ("subject", "description", "requested_action"):
        if not isinstance(request.get(field), str) or not request[field].strip():
            errors.append(f"{case_id}: request.{field} phải là chuỗi không rỗng.")


def check_test_cases(cases: list[Any], errors: list[str]) -> None:
    if len(cases) != 30:
        errors.append(f"test_dataset_30.json có {len(cases)} ca; yêu cầu đúng 30 ca.")

    check_unique_ids(cases, "case_id", "Dataset", errors)

    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            continue

        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            case_id = f"Ca số {index}"

        check_request(case_id, case.get("request"), errors)

        expected = case.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{case_id}: expected phải là object JSON.")
            continue

        required_expected_fields = {
            "is_valid_support_request",
            "category",
            "priority",
            "risk_level",
            "recommended_team",
        }
        for field in sorted(required_expected_fields - expected.keys()):
            errors.append(f"{case_id}: expected thiếu trường {field}.")

        if not isinstance(expected.get("is_valid_support_request"), bool):
            errors.append(f"{case_id}: expected.is_valid_support_request phải là true/false.")

        check_choice(expected.get("category"), ALLOWED_CATEGORIES, "expected.category", case_id, errors)
        check_choice(expected.get("priority"), ALLOWED_PRIORITIES, "expected.priority", case_id, errors)
        check_choice(expected.get("risk_level"), ALLOWED_RISK_LEVELS, "expected.risk_level", case_id, errors)
        check_choice(
            expected.get("recommended_team"), ALLOWED_TEAMS,
            "expected.recommended_team", case_id, errors
        )


def find_pii(value: Any, path: str, errors: list[str]) -> None:
    """Flag likely real emails, phone numbers, or 12-digit personal IDs.

    Reserved example domains are accepted for synthetic test data.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "contact_email" and isinstance(child, str):
                domain = child.rsplit("@", 1)[-1].lower() if "@" in child else ""
                if domain in PLACEHOLDER_EMAIL_DOMAINS:
                    continue
            find_pii(child, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value, start=1):
            find_pii(child, f"{path}[{index}]", errors)
    elif isinstance(value, str):
        emails = [
            email for email in EMAIL_RE.findall(value)
            if email.rsplit("@", 1)[-1].lower() not in PLACEHOLDER_EMAIL_DOMAINS
        ]
        match = PHONE_OR_ID_RE.search(value)
        if emails:
            errors.append(f"Có email không phải địa chỉ mẫu tại {path}.")
        if match:
            errors.append(f"Có chuỗi giống số điện thoại/CCCD tại {path}: {match.group()}.")


def check_data() -> int:
    print("--- BẮT ĐẦU KIỂM TRA DỮ LIỆU ---")
    errors: list[str] = []

    try:
        kb = require_list(load_json("data/knowledge_base.json"), "knowledge_base.json", errors)
        tickets = require_list(load_json("data/historical_tickets.json"), "historical_tickets.json", errors)
        cases = require_list(load_json("data/test_dataset_30.json"), "test_dataset_30.json", errors)
    except (FileNotFoundError, ValueError) as error:
        print(f"[LỖI] {error}")
        return 1

    if len(kb) < 12:
        errors.append(f"KB có {len(kb)} mục; cần ít nhất 12.")
    if len(tickets) < 15:
        errors.append(f"Tickets có {len(tickets)} mục; cần ít nhất 15.")

    check_unique_ids(kb, "doc_id", "KB", errors)
    check_unique_ids(tickets, "ticket_id", "Tickets", errors)
    check_test_cases(cases, errors)

    find_pii(kb, "knowledge_base.json", errors)
    find_pii(tickets, "historical_tickets.json", errors)
    find_pii(cases, "test_dataset_30.json", errors)

    if errors:
        print(f"\n[CHƯA ĐẠT] Tìm thấy {len(errors)} vấn đề:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"[OK] Knowledge base: {len(kb)} mục.")
    print(f"[OK] Historical tickets: {len(tickets)} mục.")
    print(f"[OK] Test dataset: {len(cases)} ca, ID không trùng.")
    print("[OK] Request và expected dùng các trường/giá trị theo schema.")
    print("[OK] Không phát hiện PII; email miền example.* được xem là dữ liệu giả lập.")
    print("--- KIỂM TRA HOÀN TẤT ---")
    return 0


if __name__ == "__main__":
    sys.exit(check_data())
