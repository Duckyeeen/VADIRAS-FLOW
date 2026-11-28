"""Bộ tạo vector nhúng tất định phục vụ tìm kiếm ngữ nghĩa ổn định không phụ thuộc API ngoài."""

from __future__ import annotations

import hashlib
import math
import re

from .models import DEFAULT_EMBEDDING_DIMENSIONS

_TOKEN_RE = re.compile(r"[a-zA-ZÀ-ỹ0-9_]+")


def tokenize_text(text: str) -> list[str]:
    """Tách văn bản thành danh sách từ khóa chuẩn hóa chữ thường để tạo vector và chấm điểm."""
    return _TOKEN_RE.findall(text.lower())


class DeterministicEmbeddingProvider:
    """Chuyển đổi văn bản thành vector chuẩn hóa L2 tất định bằng phương pháp băm đặc trưng."""

    def __init__(
        self,
        *,
        dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        model_name: str = "deterministic-hash-v1",
        provider_name: str = "local",
    ) -> None:
        self.dimensions = dimensions
        self.model_name = model_name
        self.provider_name = provider_name

    def embed_text(self, text: str) -> list[float]:
        """Tạo vector số thực chuẩn hóa độ dài đơn vị có chiều cố định `self.dimensions`."""
        vec = [0.0] * self.dimensions
        tokens = tokenize_text(text)
        if not tokens:
            return vec

        # Kết hợp từ đơn và cặp từ liên tiếp để giữ cả ngữ nghĩa cụm từ ngắn
        features = list(tokens) + [f"{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1)]
        for feat in features:
            digest = hashlib.sha256(feat.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [round(v / norm, 6) for v in vec]
        return vec


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Tính độ tương đồng cô-sin trong khoảng `[-1.0, 1.0]` giữa hai vector cùng số chiều."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, (dot / (norm_a * norm_b) + 1.0) / 2.0))


def keyword_overlap_score(query: str, text: str) -> float:
    """Tính tỷ lệ trùng lặp từ khóa giữa câu truy vấn và văn bản tri thức."""
    q_tokens = set(tokenize_text(query))
    if not q_tokens:
        return 0.0
    t_tokens = set(tokenize_text(text))
    if not t_tokens:
        return 0.0
    return len(q_tokens & t_tokens) / len(q_tokens)
