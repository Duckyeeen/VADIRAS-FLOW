"""Bộ đọc và kiểm tra phiên bản mẫu câu lệnh từ thư mục `prompts/`."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import NotFoundError

DEFAULT_PROMPTS_FILE = Path(__file__).resolve().parents[4] / "prompts" / "swarm_v1.json"


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """Thông tin một mẫu câu lệnh đã gắn phiên bản và mã băm nội dung."""

    role_code: str
    version: str
    system_prompt: str
    output_schema_name: str
    content_hash: str


class PromptRegistry:
    """Nạp danh mục mẫu câu lệnh theo phiên bản để bảo đảm mọi lượt gọi AI đều truy vết được."""

    def __init__(self, prompts_path: Path | None = None) -> None:
        self._path = prompts_path or DEFAULT_PROMPTS_FILE
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        self._version = str(raw["version"])
        self._trust_notice = str(raw.get("trust_boundary_notice", ""))
        self._roles: dict[str, PromptSpec] = {}
        for role_code, item in raw["roles"].items():
            full_prompt = f"{item['system_prompt']}\n\n[RANH_GIOI_AN_TOAN]: {self._trust_notice}".strip()
            digest = hashlib.sha256(full_prompt.encode("utf-8")).hexdigest()
            self._roles[role_code] = PromptSpec(
                role_code=role_code,
                version=self._version,
                system_prompt=full_prompt,
                output_schema_name=str(item["output_schema_name"]),
                content_hash=digest,
            )

    @property
    def version(self) -> str:
        """Trả về mã phiên bản hiện tại của bộ câu lệnh."""
        return self._version

    def get_prompt(self, role_code: str) -> PromptSpec:
        """Lấy mẫu câu lệnh của một vai trò trợ lý AI cụ thể.

        Ném `NotFoundError` nếu mã vai trò chưa được đăng ký trong kho câu lệnh.
        """
        spec = self._roles.get(role_code)
        if spec is None:
            raise NotFoundError(
                f"Chưa cấu hình mẫu câu lệnh cho vai trò `{role_code}`.",
                code="PROMPT_NOT_FOUND",
            )
        return spec
