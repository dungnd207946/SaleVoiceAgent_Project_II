"""Mọi tham số điều chỉnh được của module kb. Sửa ở đây, không rải khắp các thư mục con."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# ─── Chunk ──────────────────────────────────────────────────────────────────────
CHUNK_MAX_CHARS = 1000
CHUNK_OVERLAP = 100
CHUNK_MIN_CHARS = 300

# ─── Kho tệp ────────────────────────────────────────────────────────────────────
KB_PREFIX = "kb/"
"""Mọi tệp của module nằm dưới đây. Tài liệu gốc (`kb/files/`) là RIÊNG TƯ; chỉ ảnh đã
kéo về (`kb/anh/`) được phát công khai — xem `router.PUBLIC_PREFIXES`."""
FILES_PREFIX = "kb/files/"
IMAGES_PREFIX = "kb/anh/"

PRESIGN_TTL_SEC = 300
THUMB_WIDTH = 512
THUMB_QUALITY = 80
THUMB_SUFFIX = ".thumb.webp"

# ─── HTTP: timeout · retry · backpressure ───────────────────────────────────────
HTTP_TIMEOUT_SEC = 120.0
RETRY_ATTEMPTS = 3
WORKER_CONCURRENCY = 4

# ─── embed service ──────────────────────────────────────────────────────────────
PATH_EMBED = "/embed"
SIDE_INDEX = "index"
KIND_DENSE = "dense"
KIND_SPARSE = "sparse"
KIND_VISUAL_IMAGE = "visual_image"

VISUAL_MAX_BYTES = 2_000_000
VISUAL_IMAGE_WIDTH = 1024


class KbEnv(BaseSettings):
    """Cấu hình theo môi trường, prefix `KB_`."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KB_", extra="ignore")

    embed_url: str = "http://embed:8013"
    santa_models_token: str = ""
    collection_prefix: str = "shop"
    """Hai collection: `<prefix>_documents` (text) và `<prefix>_media` (ảnh). Agent đọc
    đúng hai tên này — đổi prefix là đổi hợp đồng với repo agent."""
    file_max_mb: int = 25
    """Trần dung lượng một tệp «Tài liệu tra cứu»."""


def get_env() -> KbEnv:
    return KbEnv()


def collection_documents() -> str:
    return f"{get_env().collection_prefix}_documents"


def collection_media() -> str:
    return f"{get_env().collection_prefix}_media"
