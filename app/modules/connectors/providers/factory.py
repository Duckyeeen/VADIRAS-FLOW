"""Hàm khởi tạo bộ kết nối GitHub phù hợp theo cấu hình hệ thống."""

from __future__ import annotations

from app.core.config import Settings, get_settings

from .base import BaseConnector
from .github_app import GitHubAppConnector
from .mock_github import MockGitHubConnector


def build_github_connector(settings: Settings | None = None) -> BaseConnector:
    """Khởi tạo `MockGitHubConnector` (mặc định) hoặc `GitHubAppConnector` từ cấu hình."""
    active = settings or get_settings()
    allowed_repos = active.get_github_allowed_repos_list() or ["Duckyeeen/VADIRAS-FLOW"]
    mode = active.github_connector_mode.strip().lower()
    if mode in {"github_app", "github"}:
        return GitHubAppConnector(
            app_id=active.github_app_id,
            installation_id=active.github_installation_id,
            private_key_path=active.github_private_key_path,
            allowed_repos=allowed_repos,
            api_base_url=active.github_api_base_url,
        )
    return MockGitHubConnector(allowed_repos=allowed_repos)
