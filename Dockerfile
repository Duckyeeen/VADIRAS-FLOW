# Ảnh đóng gói máy chủ API và tiến trình nền VADIRAS FLOW
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Cài đặt thư viện hệ thống tối thiểu để kết nối PostgreSQL và kiểm tra sức khỏe dịch vụ
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

# Tạo người dùng riêng không mang quyền quản trị tối cao trong container
RUN useradd --create-home --shell /bin/bash appuser

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY data ./data
COPY prompts ./prompts
COPY scripts ./scripts

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Nâng cấp bảng CSDL mới nhất, nạp dữ liệu mẫu khi bật DEMO_MODE=true và mở máy chủ FastAPI
CMD ["sh", "-c", "alembic upgrade head && if [ \"${DEMO_MODE:-true}\" = \"true\" ]; then python -m scripts.seed_demo; fi && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
