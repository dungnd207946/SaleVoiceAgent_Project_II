"""Cấu hình embed service. Tên biến theo VAI TRÒ (dense/sparse/visual), không theo model.

systemd và docker compose KHÔNG cắt inline comment (`FOO=10  # ghi chú`) nên phải cắt ở
đây. Chỉ cắt khi có whitespace trước `#`, để không phá URL fragment / password.
"""

import os

_COMMENT_SEPS = (" #", "\t#")


def clean(value: str) -> str:
    for sep in _COMMENT_SEPS:
        if sep in value:
            value = value.split(sep, 1)[0]
    return value.strip()


def env(key: str, default: str = "") -> str:
    raw = os.environ.get(key)
    return clean(raw) if raw is not None else default


def env_int(key: str, default: int) -> int:
    value = env(key)
    return int(value) if value else default


DENSE_MODEL = env("EMBED_DENSE_MODEL", "intfloat/multilingual-e5-large")
SPARSE_MODEL = env("EMBED_SPARSE_MODEL", "Qdrant/bm25")
VISUAL_MODEL = env("EMBED_VISUAL_MODEL", "google/siglip2-base-patch16-256")

MODEL_BY_KIND = {
    "dense": DENSE_MODEL,
    "sparse": SPARSE_MODEL,
    "visual_text": VISUAL_MODEL,
    "visual_image": VISUAL_MODEL,
}

DEVICE = env("EMBED_DEVICE", "cpu")
BATCH_SIZE = env_int("EMBED_BATCH_SIZE", 32)
CACHE_DIR = env("EMBED_CACHE_DIR", "/root/.cache/fastembed")

WARMUP = tuple(k for k in env("EMBED_WARMUP", "dense").split(",") if k.strip())

TOKEN = env("ODYSSEY_MODELS_TOKEN")
LOG_LEVEL = env("ODYSSEY_LOG_LEVEL", "INFO")

# Padding của visual text tower — phải khớp giữa index và query.
VISUAL_MAXLEN = env_int("EMBED_VISUAL_MAXLEN", 64)
