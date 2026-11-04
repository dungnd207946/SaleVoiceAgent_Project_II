"""Cấu hình portal. Mọi biến môi trường khai ở đây, không đọc os.environ rải rác."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# HAI DSN, HAI ROLE: `portal_migrator` là chủ mọi schema (chỉ alembic dùng),
# `portal_api` chỉ có CRUD trên bảng `shop` (API + worker dùng). Runtime nối bằng
# owner là runtime sửa được lược đồ.
#
# CỔNG MẶC ĐỊNH = cổng của stack `pj2-backend` (docker-compose.local.yml + .env).
# Máy dev còn chạy stack của dự án KHÁC ở 5442/6382/6343/9002 — default trỏ vào đó
# là migrate/ghi nhầm sang DB người khác mà không có lỗi nào.
_DEFAULT_RUNTIME_DSN = "postgresql://portal_api:apidev@localhost:5452/portal"
_DEFAULT_MIGRATOR_DSN = "postgresql://portal_migrator:dev@localhost:5452/portal"


def to_alembic_url(dsn: str) -> str:
    """Alembic chạy qua SQLAlchemy + psycopg (sync); runtime dùng asyncpg."""
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


class Settings(BaseSettings):
    """Cấu hình runtime + migration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    """development | production."""

    database_url: str = _DEFAULT_RUNTIME_DSN
    """DSN RUNTIME (asyncpg) — role `portal_api`. API và worker dùng đúng cái này."""

    migrator_url: str = _DEFAULT_MIGRATOR_DSN
    """DSN chỉ-DDL — role `portal_migrator`. CHỈ `alembic` dùng."""

    redis_url: str = "redis://localhost:6392/0"

    worker_budget: int = 12
    """Số job chạy đồng thời trong MỘT worker. Trần từng loại việc khai ở register()."""

    public_base_url: str = ""
    """Gốc URL CÔNG KHAI của backend — `core/public_url.py` nối
    `{base}/api/v1/public/files/<khoá>` cho tệp agent gửi khách. Rỗng hoặc địa chỉ
    nội bộ (`localhost`…) ⇒ không sinh link."""

    # ─── Kho tệp (MinIO ở dev, S3 ở prod) ────────────────────────────────────
    s3_endpoint_url: str | None = "http://localhost:9012"
    """Rỗng/None ⇒ endpoint AWS thật (credential lấy từ IAM role)."""
    s3_bucket: str = "shop"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"

    s3_redirect_enabled: bool = False
    """Route phát tệp trả 307 tới URL kho có hạn thay vì tự stream. Chỉ bật khi kho
    mở được từ Internet công cộng — không thì ảnh vỡ phía khách mà không có lỗi."""
    s3_redirect_ttl_sec: int = 900

    # ─── Kho tri thức (Qdrant) ────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6353"
    qdrant_api_key: str = ""
    """Phải trùng `service.api_key` của Qdrant. Rỗng = Qdrant chưa bật xác thực."""

    @property
    def alembic_url(self) -> str:
        """DSN cho Alembic — suy từ `migrator_url`, KHÔNG phải `database_url`."""
        return to_alembic_url(self.migrator_url)


def get_settings() -> Settings:
    return Settings()
