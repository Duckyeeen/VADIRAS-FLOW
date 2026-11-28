"""Khuôn mẫu dữ liệu Pydantic gốc dùng chung cho toàn bộ các phân hệ API và quy trình."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Mô hình dữ liệu gốc: chặn các trường lạ không khai báo và tự động cắt khoảng trắng dư ở đầu/cuối chuỗi."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
