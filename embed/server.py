"""embed :8013 — nhà máy vector. Xem embed/README.md."""

import base64
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from embed import settings
from embed.auth import require_token
from embed.log import setup as setup_logging
from embed.models import LOADERS

log = logging.getLogger("embed-svc")

SIDES = ("index", "query")

# Kind chỉ có nghĩa một chiều: ảnh chỉ vào index, visual text tower chỉ để query.
SIDE_BY_KIND = {"visual_image": "index", "visual_text": "query"}

class EmbedRequest(BaseModel):
    # BẮT BUỘC, không default: prefix e5 bất đối xứng nên thiếu chiều phải là 422.
    side: str
    texts: list[str] = []
    images: list[str] = []  # base64
    # `str` không Literal: LOADERS là nguồn sự thật của kind → thêm kind không sửa file này.
    kind: str = "dense"

    # Field lạ là 422, không im lặng bỏ qua: client cũ còn gửi `is_query` (default False từng
    # biến query thành passage âm thầm) hay `normalize` (model luôn L2-norm sẵn) phải biết ngay.
    model_config = {"extra": "forbid"}


def build_app(*, token: str = "", loaders: dict = LOADERS) -> FastAPI:
    # Nạp lazy, một instance mỗi class (hai kind visual dùng chung). Lock vì uvicorn gọi từ nhiều thread.
    instances: dict[type, object] = {}
    lock = threading.Lock()

    def model_for(kind: str):
        cls = loaders[kind]
        if cls not in instances:
            with lock:
                if cls not in instances:
                    log.info("⏳ nạp model cho kind=%s", kind)
                    instances[cls] = cls()
                    log.info("✅ kind=%s sẵn sàng", kind)
        return instances[cls]

    def loaded() -> list[str]:
        return [kind for kind, cls in loaders.items() if cls in instances]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        log.info("🚀 embed :8013 device=%s kinds=%s", settings.DEVICE, ",".join(loaders))
        for kind in settings.WARMUP:
            try:
                model_for(kind.strip())
            except Exception:
                log.exception("warmup kind=%s thất bại", kind)
        yield

    app = FastAPI(title="Odyssey Embed Service", version="3.0.0", lifespan=lifespan)
    guard = [Depends(require_token(token))]

    @app.get("/health")
    def health():
        return {
            "status": "ok" if loaded() else "warming",
            "device": settings.DEVICE,
            "models": settings.MODEL_BY_KIND,
            "kinds": list(loaders),
            "loaded": loaded(),
        }

    @app.post("/embed", dependencies=guard)
    def embed(req: EmbedRequest):
        side = req.side
        if side not in SIDES:
            raise HTTPException(
                status_code=400, detail=f"`side` phải là {' | '.join(SIDES)}, nhận {side!r}"
            )
        is_query = side == "query"

        only = SIDE_BY_KIND.get(req.kind)
        if only is not None and only != side:
            raise HTTPException(
                status_code=400, detail=f"kind={req.kind} chỉ dùng ở chiều {only!r}, nhận side={side!r}"
            )
        if req.kind not in loaders:
            raise HTTPException(
                status_code=400, detail=f"kind không hợp lệ: {req.kind!r}. Hợp lệ: {', '.join(loaders)}"
            )
        model = model_for(req.kind)

        t0 = time.monotonic()
        if req.kind == "visual_image":
            if not req.images:
                raise HTTPException(status_code=400, detail="kind=visual_image cần `images` (base64)")
            try:
                raw = [base64.b64decode(img) for img in req.images]
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"images không phải base64: {exc}") from None
            vectors = model.encode_images(raw)
            count = len(raw)
        else:
            if not req.texts:
                raise HTTPException(status_code=400, detail="`texts` rỗng")
            count = len(req.texts)
            if req.kind == "sparse":
                result = model.encode_sparse(req.texts)
                log.info("embed sparse/%s n=%d in %.1fms", side, count, (time.monotonic() - t0) * 1000)
                return {"sparse": result, "model": settings.SPARSE_MODEL, "count": count}
            vectors = model.encode(req.texts, is_query=is_query)

        dim = len(vectors[0]) if vectors else 0
        log.info(
            "embed %s/%s n=%d dim=%d in %.1fms", req.kind, side, count, dim, (time.monotonic() - t0) * 1000
        )
        return {
            "embeddings": vectors,
            "dim": dim,
            "model": settings.MODEL_BY_KIND.get(req.kind, ""),
            "count": count,
        }

    return app


setup_logging(settings.LOG_LEVEL)
app = build_app(token=settings.TOKEN)
