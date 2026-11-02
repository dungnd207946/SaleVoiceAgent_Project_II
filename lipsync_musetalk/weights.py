"""Tải weights của lipsync_musetalk về volume cache — mỗi lần boot, idempotent.

Weights KHÔNG nằm trong image/git (giống mọi service khác, xem README gốc §Models):
lần boot đầu tải ~3,9 GB về `$LIPSYNC_DATA_DIR/models` (volume `lipsync_cache`), các
lần sau chỉ kiểm tồn tại + kích thước rồi bỏ qua.

MỌI file được kiểm SHA-256 ngay sau khi tải: giá trị dưới đây đo trên đúng bộ
weights đã chạy thật (2026-10-06). Hai file face-parsing không có bản chính thức
trên HF (repo gốc tải từ Google Drive / pytorch.org — trên server hay hỏng) nên lấy
từ một mirror; chính SHA-256 là thứ bảo đảm mirror đó KHÔNG bị tráo nội dung.
Muốn dùng mirror khác/repo HF riêng của mình: đổi `LIPSYNC_FACEPARSE_REPO` — hash
vẫn phải khớp.

UNet (2026-10-14): mặc định là bản FINE-TUNE TIẾNG VIỆT của MuseTalk V1.5 (cùng kiến
trúc, cùng định dạng file) ở repo HF private `NobleX-AI/santa-lipsync-musetalk` — cần
HF_TOKEN như santa-stt / santa-tts-omnivoice. Đo trên người nói chưa thấy: LSE-C
4.16 → 6.66, LMD miệng 7.51 → 6.15 (quy trình train/đo: MuseTalk/vi_finetune/BAO_CAO.md).
Đổi model = đặt ba biến LIPSYNC_UNET_{REPO,FILE,SHA256}; về bản gốc:
  LIPSYNC_UNET_REPO=TMElyralab/MuseTalk LIPSYNC_UNET_FILE=musetalkV15/unet.pth
  LIPSYNC_UNET_SHA256=7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007
File đích vẫn là models/musetalkV15/unet.pth: mốc `.sha256` khác ⇒ tự tải lại, đè bản cũ.
"""

import hashlib
import logging
import os
import shutil

log = logging.getLogger("lipsync-weights")

FACEPARSE_REPO = os.environ.get("LIPSYNC_FACEPARSE_REPO", "ManyOtherFunctions/face-parse-bisent")

# `or`: compose truyền biến RỖNG khi .env không khai — rỗng phải rơi về mặc định.
UNET_REPO = os.environ.get("LIPSYNC_UNET_REPO") or "NobleX-AI/santa-lipsync-musetalk"
UNET_FILE = os.environ.get("LIPSYNC_UNET_FILE") or "unet.pth"
UNET_SHA256 = (os.environ.get("LIPSYNC_UNET_SHA256")
               or "6db22374831890150c908235817354dfe312b97e9c469293e39cada48a726244")
UNET_DICH = "models/musetalkV15/unet.pth"

# Cache của nhân vật render BẰNG UNet (miệng khép, ảnh chờ) — đổi UNet là phải bỏ,
# phần còn lại (frame, mặt nạ, latent VAE) không phụ thuộc UNet nên giữ.
CACHE_THEO_UNET = ("im_lang.pkl", "poster.png")
MOC_UNET_AVATAR = "unet.sha256"

# (repo HF, file trong repo, đích tương đối trong data dir, sha256)
WEIGHTS = [
    (UNET_REPO, UNET_FILE, UNET_DICH, UNET_SHA256),
    ("TMElyralab/MuseTalk", "musetalkV15/musetalk.json", "models/musetalkV15/musetalk.json",
     "5b6923aee04d71692e0e9846c471e0a4ea07a4f686d39545e472bd4ba17e1b47"),
    ("stabilityai/sd-vae-ft-mse", "config.json", "models/sd-vae/config.json",
     "92d3dfb746fca211a2c9e019e285f8597412211728dce3c5bcf4eda0f2d62e7e"),
    ("stabilityai/sd-vae-ft-mse", "diffusion_pytorch_model.bin", "models/sd-vae/diffusion_pytorch_model.bin",
     "1b4889b6b1d4ce7ae320a02dedaeff1780ad77d415ea0d744b476155c6377ddc"),
    ("openai/whisper-tiny", "config.json", "models/whisper/config.json",
     "ffdccec4f3211f4c63310f2b7098f309fe70f3952cedc5e4d11e43f5b2379b98"),
    ("openai/whisper-tiny", "pytorch_model.bin", "models/whisper/pytorch_model.bin",
     "9607f98a2b22d9e229ae43c52ecea79dcede9e0c5cfae67e8da6eda86d8aac1d"),
    ("openai/whisper-tiny", "preprocessor_config.json", "models/whisper/preprocessor_config.json",
     "9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666"),
    # DWPose bản ONNX (chạy bằng rtmlib/onnxruntime) — bản .pth gốc cần mmcv, không có
    # build cho torch cu128 / GPU Blackwell. Xem musetalk/VENDORED.md.
    ("yzd-v/DWPose", "dw-ll_ucoco_384.onnx", "models/dwpose/dw-ll_ucoco_384.onnx",
     "724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843"),
    (FACEPARSE_REPO, "79999_iter.pth", "models/face-parse-bisent/79999_iter.pth",
     "468e13ca13a9b43cc0881a9f99083a430e9c0a38abd935431d1c28ee94b26567"),
    (FACEPARSE_REPO, "resnet18-5c106cde.pth", "models/face-parse-bisent/resnet18-5c106cde.pth",
     "5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8"),
    # Bộ dò mặt S3FD: code MuseTalk tự tải từ adrianbulat.com (~15 kB/s) vào cache
    # torch hub — đặt sẵn đúng chỗ đó (TORCH_HOME trỏ vào data dir, xem lipsync_server).
    ("ByteDance/LatentSync", "auxiliary/s3fd-619a316812.pth", "torch/hub/checkpoints/s3fd-619a316812.pth",
     "619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543"),
]


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for khoi in iter(lambda: f.read(1 << 20), b""):
            h.update(khoi)
    return h.hexdigest()


def dam_bao_weights(data_dir: str) -> None:
    """Tải những file còn thiếu, kiểm SHA-256. Lỗi ⇒ raise (service chết trước khi mở
    cổng, healthcheck bắt — cùng nguyên tắc với stt/tts-omnivoice)."""
    # hf_xet treo ở 0 byte trên đường on-prem — tắt trước khi import huggingface_hub.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import hf_hub_download

    for repo, ten, dich, sha in WEIGHTS:
        dich_day = os.path.join(data_dir, dich)
        moc = dich_day + ".sha256"
        if os.path.exists(dich_day) and os.path.exists(moc) and open(moc).read().strip() == sha:
            continue
        log.info("⬇️  %s/%s → %s", repo, ten, dich)
        # Tải thẳng vào thư mục tạm TRÊN CÙNG volume rồi đổi tên — không qua cache HF
        # (~/.cache nằm ngoài volume: vừa tải lại mỗi lần tạo container, vừa tốn gấp đôi).
        tai = os.path.join(data_dir, "_dang_tai", repo.replace("/", "__"))
        tam = hf_hub_download(repo, ten, local_dir=tai, token=os.environ.get("HF_TOKEN") or None)
        thuc = _sha256(tam)
        if thuc != sha:
            os.remove(tam)
            raise RuntimeError(f"SHA-256 lệch cho {repo}/{ten}: {thuc} ≠ {sha} — KHÔNG dùng file này")
        os.makedirs(os.path.dirname(dich_day), exist_ok=True)
        os.replace(tam, dich_day)
        with open(moc, "w") as f:
            f.write(sha)
    shutil.rmtree(os.path.join(data_dir, "_dang_tai"), ignore_errors=True)
    log.info("✅ weights đủ (%d file)", len(WEIGHTS))


def don_cache_theo_unet(data_dir: str, unet_sha: str = UNET_SHA256) -> int:
    """Bỏ cache render bằng UNet khác UNet đang chạy, trong MỌI nhân vật đã dựng.

    Mỗi thư mục nhân vật giữ mốc `unet.sha256`; thiếu mốc = cache dựng trước khi có cơ
    chế này (tức bằng UNet gốc). Gọi lúc boot, trước khi nạp nhân vật nào — cache bị bỏ
    sẽ tự render lại bằng UNet mới ở lần nạp đầu (vài giây). Trả số nhân vật đã dọn.
    """
    goc = os.path.join(data_dir, "avatars")
    if not os.path.isdir(goc):
        return 0
    so = 0
    for ten in sorted(os.listdir(goc)):
        d = os.path.join(goc, ten)
        if not os.path.isdir(d):
            continue
        moc = os.path.join(d, MOC_UNET_AVATAR)
        if os.path.exists(moc) and open(moc).read().strip() == unet_sha:
            continue
        bo = [f for f in CACHE_THEO_UNET if os.path.exists(os.path.join(d, f))]
        for f in bo:
            os.remove(os.path.join(d, f))
        with open(moc, "w") as f:
            f.write(unet_sha)
        if bo:
            so += 1
            log.info("🧹 %s: bỏ %s (render bằng UNet khác)", ten, ", ".join(bo))
    return so
