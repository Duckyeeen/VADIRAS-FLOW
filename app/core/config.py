"""Quản lý cấu hình ứng dụng từ biến môi trường một cách an toàn."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Tập hợp các thông số cấu hình hệ thống được nạp từ biến môi trường hoặc tệp `.env`.

    Lớp này tách biệt hoàn toàn cấu hình chạy thực tế khỏi mã nguồn, đồng thời
    ngăn chặn việc cấu hình sai quy tắc an toàn như mở rộng CORS tùy tiện.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Thông tin ứng dụng web ---
    app_name: str = "VADIRAS FLOW"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    demo_mode: bool = True

    # Danh sách các địa chỉ giao diện web được phép gọi API (phân cách bằng dấu phẩy)
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    # --- Kết nối cơ sở dữ liệu ---
    database_url: str = Field(
        default="sqlite+aiosqlite:///./vadiraflow_dev.db",
        description="Chuỗi kết nối cơ sở dữ liệu bất đồng bộ cho PostgreSQL hoặc SQLite cục bộ.",
    )
    database_echo: bool = False

    # --- Cấu hình máy chủ điều phối quy trình Temporal ---
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "vadiras-flow-main"

    # --- Cấu hình thẻ đăng nhập JWT ---
    jwt_secret_key: str = "chi_dung_cho_phat_trien_cuc_bo_khong_dung_o_moi_truong_that_32ky_tu"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=30, ge=5, le=120)
    jwt_refresh_token_expire_days: int = Field(default=7, ge=1, le=30)
    jwt_issuer: str = "vadiras-flow"
    jwt_audience: str = "vadiras-flow-api"

    # --- Cấu hình nhà cung cấp AI (mặc định dùng bộ giả lập, không gắn cứng một hãng) ---
    llm_provider: str = "mock"
    llm_model: str = "mock-default"
    llm_api_base_url: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: int = Field(default=30, ge=1, le=300)
    llm_max_repair_attempts: int = Field(default=2, ge=0, le=5)

    # --- Giới hạn an toàn cho nhóm trợ lý AI ---
    swarm_max_concurrent: int = Field(default=4, ge=1, le=10)
    swarm_max_rounds: int = Field(default=2, ge=1, le=5)

    # --- Cấu hình kết nối GitHub ---
    github_connector_mode: str = "mock"
    github_app_id: str = ""
    github_installation_id: str = ""
    github_private_key_path: str = ""
    github_api_base_url: str = "https://api.github.com"
    github_webhook_secret: str = "chi_dung_kiem_thu_cuc_bo_khong_dung_that"
    github_allowed_repos: str = "Duckyeeen/VADIRAS-FLOW"

    def get_github_allowed_repos_list(self) -> list[str]:
        """Tách chuỗi `github_allowed_repos` thành danh sách tên kho hợp lệ."""
        return [repo.strip() for repo in self.github_allowed_repos.split(",") if repo.strip()]

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        """Kiểm tra danh sách nguồn giao diện hợp lệ và chặn ký tự đại diện `*`."""
        cleaned = value.strip()
        if cleaned == "*":
            raise ValueError("Không được phép đặt CORS_ALLOWED_ORIGINS='*' vì lý do bảo mật.")
        return cleaned

    def get_cors_origins_list(self) -> list[str]:
        """Tách chuỗi `cors_allowed_origins` thành danh sách địa chỉ hoàn chỉnh.

        Đầu vào: đọc từ thuộc tính `cors_allowed_origins`.
        Đầu ra: danh sách các chuỗi địa chỉ đã bỏ khoảng trắng dư.
        """
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Trả về đối tượng cấu hình dùng chung đã lưu trong bộ nhớ đệm.

    Khi chạy kiểm thử với cấu hình khác nhau, có thể gọi `get_settings.cache_clear()`
    để nạp lại giá trị mới từ biến môi trường.
    """
    return Settings()
