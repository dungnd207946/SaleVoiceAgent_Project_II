"""Mọi tham số điều chỉnh được của module kb. Sửa ở đây, không rải trong 6 thư mục."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ─── Postgres ───────────────────────────────────────────────────────────────────

SCHEMA = "tenant_data"

# Anchor hệ thống, luôn published (02a §4b). Không bao giờ vào cascade fanout.
SYSTEM_ANCHOR = "__ALL__"

# ─── Chunk (§15.2) ──────────────────────────────────────────────────────────────
CHUNK_MAX_CHARS = 1000
CHUNK_OVERLAP = 100
CHUNK_MIN_CHARS = 300

# ─── S3 / MinIO ─────────────────────────────────────────────────────────────────

ROOT_PREFIX = "tenants"
PRESIGN_TTL_SEC = 300
THUMB_WIDTH = 512
THUMB_QUALITY = 80
THUMB_SUFFIX = ".thumb.webp"

# ─── santa-models ───────────────────────────────────────────────────────────────

COLLECTION_SUFFIX_DOCUMENTS = "documents"
COLLECTION_SUFFIX_MEDIA = "media"

# ─── HTTP: timeout · retry · backpressure (§10) ─────────────────────────────────

HTTP_TIMEOUT_SEC = 120.0
RETRY_ATTEMPTS = 3

WORKER_CONCURRENCY = 4

# ─── embed service ──────────────────────────────────────────────────────────────

PATH_EMBED = "/embed"
SIDE_INDEX = "index"

KIND_DENSE = "dense"
KIND_SPARSE = "sparse"
KIND_VISUAL_IMAGE = "visual_image"

VLM_IMAGE_WIDTH = 1600
VLM_MAX_BYTES = 4_000_000

# Video: trần tải về và nhịp chờ Gemini giải mã.
VIDEO_MAX_BYTES = 200_000_000
VIDEO_POLL_LAN = 30
VIDEO_POLL_GIAY = 2.0

VISUAL_MAX_BYTES = 2_000_000
VISUAL_IMAGE_WIDTH = 1024

OCR_MAX_PAGES = 20


class KbEnv(BaseSettings):
    """Cấu hình theo môi trường, prefix `KB_`. Chuyển sang core/config.py khi ổn định."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KB_", extra="ignore")

    # `embed` của odyssey-models trên odyssey-network. KHÔNG phải 8016 —
    # đó là query_rag đã khai tử 2026-08-05, default cũ trỏ vào cổng chết.
    embed_url: str = "http://embed:8013"
    santa_models_token: str = ""
    vlm_api_key: str = ""
    vlm_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    gemini_api_key: str = ""

    # ─── kb/web (thu thập dữ liệu công khai) ────────────────────────────────
    # Dùng chung key với phần trên: DashScope = `vlm_api_key`/`vlm_base_url`, Gemini = `gemini_api_key`.
    web_llm_concurrency: int = 4
    web_grounding_daily_cap: int = 1200
    web_fetch_per_domain: int = 2
    web_fetch_delay_sec: float = 1.0
    web_browser_enabled: bool = True
    """Tầng trình duyệt (Playwright). Tắt thì trang chặn bot chỉ mang dấu `needs_browser`."""
    # Lượt sâu xếp 1/N số dự án mỗi ngày (N=1: mọi dự án mỗi ngày).
    web_deep_slices: int = 2

    @field_validator("web_deep_slices")
    @classmethod
    def _slices_duong(cls, v: int) -> int:
        if v < 1:
            raise ValueError("web_deep_slices phải >= 1")
        return v


def get_env() -> KbEnv:
    return KbEnv()
