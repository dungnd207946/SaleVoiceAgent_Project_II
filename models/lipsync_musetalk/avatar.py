"""Dựng avatar MỘT LẦN từ video nhân vật gốc, cache vào volume — tự động lúc boot.

Video nguồn (`avatars/nguoi-dan.mp4`, đóng gói trong image) là clip «stacked alpha»
của người dẫn Kling: nửa trên màu ĐÃ nhân alpha trên nền đen, nửa dưới mặt nạ, bố
cục theo `DOAN` của portal `nguoiDan.ts` — vị trí 0–120 đoạn F (nói), 121–241 đoạn G
(đưa tay). Lần boot đầu (hoặc khi video nguồn đổi) service làm:

  1. Tách 242 vị trí F+G thành video màu thường + mặt nạ alpha GỐC (không tách nền
     lại bằng model — mặt nạ của clip đã tốt hơn mọi thứ tự tách trên nền đen).
  2. MuseTalk chuẩn bị: dò mặt (S3FD) + landmark (DWPose) từng frame, latent VAE của
     vùng mặt, mặt nạ ghép mặt (face parsing). ~1–2 phút trên GPU.
  3. Ghi `info.json` CUỐI CÙNG, mang SHA-256 của video nguồn + tham số.

Các lần boot sau: `info.json` khớp ⇒ nạp thẳng cache, bỏ qua cả ba bước. Đổi nhân
vật = commit video mới ⇒ SHA-256 đổi ⇒ tự dựng lại. Dựng hỏng giữa chừng (container
bị kill) thì không có `info.json` ⇒ lần sau dựng lại từ đầu, không nạp cache dở.
"""

import contextlib
import glob
import hashlib
import json
import logging
import os
import pickle
import re
import shutil
import subprocess

import cv2
import numpy as np
import torch

log = logging.getLogger("lipsync-avatar")

FPS = 25
SO_FRAME = 242            # F (0–120) + G (121–241) — xem DOAN ở nguoiDan.ts
NGUONG_ALPHA = 12         # dưới mức này coi như trong suốt (chia lại alpha ở đó chỉ ra nhiễu)
PHIEN_BAN = 1             # tăng khi đổi CÁCH dựng ⇒ mọi cache cũ tự bị dựng lại


@contextlib.contextmanager
def giu_cudnn():
    """Bộ dò mặt S3FD bật `cudnn.benchmark` toàn cục — trả lại giá trị cũ sau khi dựng."""
    truoc = torch.backends.cudnn.benchmark
    try:
        yield
    finally:
        torch.backends.cudnn.benchmark = truoc


# ── nhân vật KHÁCH tự tạo: avatars/<id>/ (xem dung_avatar.py) ──
MA_HOP_LE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
PHIEN_BAN_KHACH = 1        # tăng khi đổi CÁCH dựng nhân vật khách ⇒ cache cũ bị coi là chưa dựng


def thu_muc(avatar_id):
    return os.path.join("avatars", avatar_id)


def doc_info(avatar_id):
    """info.json của nhân vật khách đã dựng xong (có `bo_cuc`), hoặc None."""
    try:
        with open(os.path.join(thu_muc(avatar_id), "info.json")) as f:
            info = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return info if info.get("phien_ban") == PHIEN_BAN_KHACH and "bo_cuc" in info else None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for khoi in iter(lambda: f.read(1 << 20), b""):
            h.update(khoi)
    return h.hexdigest()


def dung_nguon(stacked, video_ra, alpha_ra):
    """Bước 1: clip stacked-alpha → video màu thường (25 fps) + mặt nạ (xuôi + ngược,
    khớp vòng frame của `prepare_avatar`)."""
    cap = cv2.VideoCapture(stacked)
    mau, alpha = [], []
    for _ in range(SO_FRAME):
        ok, f = cap.read()
        if not ok:
            raise RuntimeError(f"{stacked} có ít hơn {SO_FRAME} frame")
        h = f.shape[0] // 2
        tren = f[:h].astype(np.float32)
        a = f[h:].mean(2)
        mo = np.clip(tren * 255 / np.maximum(a[:, :, None], 1), 0, 255)   # bỏ nhân alpha
        c = np.where(a[:, :, None] > NGUONG_ALPHA, mo, 0)
        mau.append(c.astype(np.uint8))
        alpha.append(np.clip(a, 0, 255).astype(np.uint8))
    h, w = mau[0].shape[:2]
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", video_ra],
        stdin=subprocess.PIPE,
    )
    for m in mau:
        p.stdin.write(m.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg lỗi khi ghi video nguồn")
    np.save(alpha_ra, np.stack(alpha))            # chỉ frame gốc — nửa ngược đổi chỉ số lúc dùng


def prepare_avatar(video_path, avatar_dir, vae, fp, extra_margin, parsing_mode):
    """Bước 2 — giống Avatar.prepare_material() của MuseTalk realtime_inference.

    Trả danh sách bbox mặt (frame gốc) để bên gọi kiểm cỡ mặt. Ném `LoiKhongThayMat`
    (mang chỉ số frame) nếu có frame không dò được mặt.
    """
    from musetalk.utils.blending import get_image_prepare_material
    from musetalk.utils.preprocessing import coord_placeholder, get_landmark_and_bbox  # nạp DWPose + S3FD

    frames_dir = os.path.join(avatar_dir, "src_frames")
    os.makedirs(frames_dir, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video_path, "-vf", f"fps={FPS}",
                    "-start_number", "0", f"{frames_dir}/%08d.png"], check=True)
    img_list = sorted(glob.glob(os.path.join(frames_dir, "*.png")))

    coord_list, frame_list = get_landmark_and_bbox(img_list, 0)  # v1.5 dùng bbox_shift = 0
    if any(b == coord_placeholder for b in coord_list):
        # Bỏ frame không thấy mặt (như bản gốc) sẽ làm LỆCH mặt nạ alpha và mọi chỉ số
        # tư thế (DuongTuThe đánh số theo frame gốc) — thà dừng còn hơn chạy sai.
        shutil.rmtree(frames_dir, ignore_errors=True)
        raise LoiKhongThayMat([i for i, b in enumerate(coord_list) if b == coord_placeholder])
    latents, coords = [], []
    for (x1, y1, x2, y2), frame in zip(coord_list, frame_list, strict=False):
        y2 = min(y2 + extra_margin, frame.shape[0])
        crop = cv2.resize(frame[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
        latents.append(vae.get_latents_for_unet(crop))
        coords.append([x1, y1, x2, y2])
    frames = list(frame_list)

    # Mặt nạ ghép chỉ phụ thuộc frame + bbox ⇒ tính cho frame gốc rồi soi gương cho nửa
    # ngược (bản gốc tính lại cả nửa ngược: gấp đôi thời gian dựng, kết quả y hệt).
    masks, mask_boxes = [], []
    for frame, box in zip(frames, coords, strict=False):
        mask, crop_box = get_image_prepare_material(frame, box, fp=fp, mode=parsing_mode)
        masks.append(mask)
        mask_boxes.append(crop_box)

    # Phát xuôi rồi ngược (vòng liền mạch) — chỉ số < N/2 là frame gốc. frames.npy chỉ
    # lưu frame GỐC (nửa ngược là chính chúng) — `Avatar.frame()` tự đổi chỉ số.
    coords, latents = coords + coords[::-1], latents + latents[::-1]
    masks, mask_boxes = masks + masks[::-1], mask_boxes + mask_boxes[::-1]
    np.save(os.path.join(avatar_dir, "frames.npy"), np.stack(frames))
    with open(os.path.join(avatar_dir, "masks.pkl"), "wb") as f:  # mỗi mask một kích thước (theo crop box)
        pickle.dump(masks, f)
    torch.save(latents, os.path.join(avatar_dir, "latents.pt"))
    with open(os.path.join(avatar_dir, "coords.pkl"), "wb") as f:
        pickle.dump({"coords": coords, "mask_boxes": mask_boxes}, f)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return coords[: len(frames)]


class LoiKhongThayMat(RuntimeError):
    def __init__(self, frames):
        super().__init__(f"Không dò được mặt ở frame {frames[:10]}… — avatar phải thấy mặt ở MỌI frame")
        self.frames = frames


def load_avatar(avatar_dir):
    """frames/alpha mở bằng mmap: một nhân vật ~0,5–1 GB ảnh thô, nạp cả vào RAM thì vài
    nhân vật là hết bộ nhớ — mmap để page cache của OS lo, chỉ frame đang dùng nằm trong RAM.
    Cache cũ (bản đầu) lưu frames/alpha đủ N = 2·N_gốc; bản mới chỉ N_gốc — `Avatar` xử lý cả hai."""
    with open(os.path.join(avatar_dir, "coords.pkl"), "rb") as f:
        c = pickle.load(f)
    with open(os.path.join(avatar_dir, "masks.pkl"), "rb") as f:
        masks = pickle.load(f)
    alpha_npy = os.path.join(avatar_dir, "alpha.npy")
    if not os.path.exists(alpha_npy):                # cache bản đầu: npz nén ⇒ đổi một lần sang npy
        np.save(alpha_npy + ".tmp.npy", np.load(os.path.join(avatar_dir, "alpha.npz"))["a"])
        os.replace(alpha_npy + ".tmp.npy", alpha_npy)
    alpha = np.load(alpha_npy, mmap_mode="r")
    return (np.load(os.path.join(avatar_dir, "frames.npy"), mmap_mode="r"), masks,
            torch.load(os.path.join(avatar_dir, "latents.pt")), c["coords"], c["mask_boxes"], alpha)


def chuan_bi(nguon, avatar_dir, vae, fp, extra_margin, parsing_mode):
    """Đảm bảo cache avatar khớp video nguồn; dựng lại nếu không. Trả kết quả `load_avatar`."""
    khoa = {"phien_ban": PHIEN_BAN, "nguon_sha256": _sha256(nguon), "so_frame": SO_FRAME,
            "fps": FPS, "extra_margin": extra_margin, "parsing_mode": parsing_mode}
    info = os.path.join(avatar_dir, "info.json")
    try:
        with open(info) as f:
            if json.load(f) == khoa:
                log.info("🧑 avatar: dùng cache %s (nguồn khớp)", avatar_dir)
                return load_avatar(avatar_dir)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    log.info("🧑 avatar: dựng MỚI từ %s (lần đầu hoặc video nguồn đã đổi) …", nguon)
    shutil.rmtree(avatar_dir, ignore_errors=True)
    os.makedirs(avatar_dir)
    video = os.path.join(avatar_dir, "nguon.mp4")
    dung_nguon(nguon, video, os.path.join(avatar_dir, "alpha.npy"))
    # Bộ dò mặt S3FD của musetalk BẬT `cudnn.benchmark` toàn cục và không trả lại. Để
    # nguyên thì mỗi thread render mới (= mỗi phiên gọi) tự dò lại thuật toán cuDNN ở lô
    # đầu: 4,1s thay vì 0,27s (đo 2026-10-06) — đúng lần boot ĐẦU trên server, khi avatar
    # vừa dựng trong cùng process. Trả về như cũ sau khi dựng.
    with giu_cudnn():
        prepare_avatar(video, avatar_dir, vae, fp, extra_margin, parsing_mode)
    with open(info, "w") as f:                    # CUỐI CÙNG — dấu «cache dùng được»
        json.dump(khoa, f)
    log.info("🧑 avatar: dựng xong")
    return load_avatar(avatar_dir)
