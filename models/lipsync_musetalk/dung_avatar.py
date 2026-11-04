"""Dựng nhân vật KHÁCH TỰ TẠO từ video thường (khách tự quay, hoặc sinh bằng AI từ ảnh).

Khác nhân vật mặc định (`avatar.chuan_bi`, clip stacked-alpha đã có mặt nạ + mốc đo tay):

  1. chuẩn hoá  — ffmpeg: 25 fps, ≤ ~640k điểm ảnh/frame, cắt độ dài (F ≤ 8s, G ≤ 5s), bỏ tiếng
  2. tách nền   — RobustVideoMatting (theo thời gian ⇒ viền tóc không nhấp nháy như tách từng ảnh)
  3. phân tích  — chuyển động từng frame, độ mở miệng + cổ tay (DWPose) ⇒ `bo_cuc.do_bo_cuc`
  4. MuseTalk   — `avatar.prepare_avatar` (dò mặt MỌI frame, latent, mặt nạ ghép)

Lỗi khách sửa được (video ngắn, không thấy mặt, mặt quá nhỏ…) ném `LoiDung` có MÃ —
portal đổi mã thành hướng dẫn. Thư mục nhân vật:

    avatars/<id>/nguon/chinh.*  nguon/tay.*   video khách gửi (giữ lại để dựng lại được)
    avatars/<id>/trang_thai.json              tiến độ / lỗi (đọc qua GET /avatars/<id>)
    avatars/<id>/info.json                    CUỐI CÙNG — dấu «nhân vật dùng được» (+ bố cục)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

import avatar as av
import cv2
import numpy as np
import torch
from bo_cuc import (
    KHUNG_CHO_JPG,
    KHUNG_CHO_JSON,
    LoiDung,
    diem_on_dinh,
    do_bo_cuc,
    doc_khung_cho,
    luu_khung_cho,
    mieng_khep,
    noi_tu_sau_khep,
    vung_cho_da_luu,
)
from tu_the import FPS

log = logging.getLogger("lipsync-dung")

F_TOI_DA_S = 8                 # đoạn nói: lấy tối đa 8s đầu (frames.npy ~ N·w·h·3 byte)
G_TOI_DA_S = 5                 # đoạn đưa tay: tối đa 5s
DIEM_ANH_TOI_DA = 640_000      # ~ bằng clip người dẫn gốc (628×1000)
MAT_TOI_THIEU_PX = 72          # bbox mặt hẹp hơn ⇒ MuseTalk ra miệng nhoè
NGUOI_TOI_THIEU = 0.03         # vùng người (alpha) < 3% khung ⇒ không thấy người
# Vùng chờ của nhân vật khách: NGẮN + CHẬM — đứng chờ phải gần như bất động. Đo trên video Wan
# thật (2026-10-08): cửa sổ 16 frame ôm cả phần đuôi động tác chỉnh dáng ⇒ chuyển động TB 0,0121,
# CAO HƠN lúc nói (0,0081) — người dùng thấy «rung người»; 8 frame cuối của nó chỉ 0,0060.
# Người dùng chốt 2026-10-08: 3 frame (≈ 0,1s) — một dáng đứng gần như cố định, lấy trong đoạn
# im lặng 0,5–2s của video AI.
CHO_SO_FRAME = int(os.environ.get("LIPSYNC_CHO_SO_FRAME", "3"))
CHO_TOC = float(os.environ.get("LIPSYNC_CHO_TOC", "0.3"))
# Mức cắt đầu TỐI THIỂU (giây) do bên đặt dựng gửi — portal gửi cho nhân vật TẠO TỪ ẢNH: video AI
# «chỉnh dáng» trong ~0,75–1s đầu mà `diem_on_dinh` chỉ nhìn cổ tay nên có lúc trả 0 (ảnh gốc tay đã
# ở gần dáng cuối, trong khi đầu/vai/thân vẫn đang dịch) ⇒ khung chờ = dáng ảnh, dải nói đi qua
# đoạn chỉnh dáng — nhân vật nhảy dáng (đo 2026-10-09: nv-71bd cắt 0s, nv-e5ac cắt 0,6s). Video
# khách tự quay không gửi ⇒ 0. Lưu cạnh nguồn để dựng lại (kể cả sau restart) vẫn áp đúng.
CAU_DUNG_JSON = "cau_dung.json"
RVM_REPO = os.environ.get("LIPSYNC_RVM_REPO", "PeterL1n/RobustVideoMatting")
RVM_MODEL = os.environ.get("LIPSYNC_RVM_MODEL", "resnet50")


def ghi_trang_thai(avatar_dir, **kv):
    path = os.path.join(avatar_dir, "trang_thai.json")
    with open(path + ".tmp", "w") as f:
        json.dump(kv, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def ghi_cau_dung(avatar_dir, cat_dau_s: float) -> None:
    with open(os.path.join(avatar_dir, CAU_DUNG_JSON), "w") as f:
        json.dump({"cat_dau_s": float(cat_dau_s)}, f)


def doc_cat_dau_s(avatar_dir) -> float:
    try:
        with open(os.path.join(avatar_dir, CAU_DUNG_JSON)) as f:
            return max(0.0, float(json.load(f).get("cat_dau_s") or 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0


def doc_trang_thai(avatar_dir):
    try:
        with open(os.path.join(avatar_dir, "trang_thai.json")) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ───────────────────────────────────────────────────────── 1. chuẩn hoá

def doc_video(path, toi_da_s):
    """Video bất kỳ → list frame BGR 25 fps (đã xoay theo metadata điện thoại, đã thu nhỏ)."""
    scale = (f"scale='trunc(iw*min(1,sqrt({DIEM_ANH_TOI_DA}/(iw*ih)))/2)*2'"
             f":'trunc(ih*min(1,sqrt({DIEM_ANH_TOI_DA}/(iw*ih)))/2)*2'")
    with tempfile.TemporaryDirectory() as tmp:
        ra = os.path.join(tmp, "chuan.mp4")
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-t", str(toi_da_s), "-an",
                            "-vf", f"fps={FPS},{scale}", "-c:v", "libx264", "-crf", "12",
                            "-pix_fmt", "yuv420p", ra], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(ra):
            raise LoiDung("VIDEO_HONG", (r.stderr or "ffmpeg không đọc được video")[-300:])
        cap = cv2.VideoCapture(ra)
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(f)
    if not frames:
        raise LoiDung("VIDEO_HONG", "video không có frame nào")
    return frames


# ───────────────────────────────────────────────────────── 2. tách nền

def nap_rvm(device):
    """RobustVideoMatting qua torch.hub (cache trong TORCH_HOME = volume). GPL-3.0: tải lúc
    chạy, không đóng gói vào image — xem README §Giấy phép."""
    m = torch.hub.load(RVM_REPO, RVM_MODEL, trust_repo=True)
    return m.eval().to(device)


@torch.no_grad()
def tach_nen(frames, rvm, device, lo=8):
    """list BGR → list alpha uint8. Trạng thái hồi quy của RVM nối qua các lô (một clip)."""
    h, w = frames[0].shape[:2]
    ty_le = min(1.0, 512 / max(h, w))           # khuyến nghị của RVM: cạnh dài ~512 ở nhánh thô
    rec = [None] * 4
    ra = []
    for s in range(0, len(frames), lo):
        lo_bgr = np.stack(frames[s : s + lo])[..., ::-1].copy()            # → RGB
        src = torch.from_numpy(lo_bgr).to(device).permute(0, 3, 1, 2).float().div_(255)[None]
        _fgr, pha, *rec = rvm(src, *rec, ty_le)
        ra.extend((pha[0, :, 0].clamp(0, 1) * 255).byte().cpu().numpy())
    return ra


# ───────────────────────────────────────────────────────── 3. phân tích

def chuyen_dong(frames, alpha):
    """Độ đổi hình từng frame so với frame trước, trong vùng người (thang 0–1)."""
    nho = [cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), None, fx=0.25, fy=0.25).astype(np.float32)
           for f in frames]
    mat = [cv2.resize(a, None, fx=0.25, fy=0.25) > 128 for a in alpha]
    ra = [0.0]
    for k in range(1, len(nho)):
        vung = mat[k] | mat[k - 1]
        d = np.abs(nho[k] - nho[k - 1])[vung]
        ra.append(float(d.mean() / 255) if d.size else 0.0)
    return np.array(ra)


def lech(f1, f2, a1, a2):
    """Hai frame lệch nhau bao nhiêu (cùng thang `chuyen_dong`)."""
    g1 = cv2.resize(cv2.cvtColor(f1, cv2.COLOR_BGR2GRAY), None, fx=0.25, fy=0.25).astype(np.float32)
    g2 = cv2.resize(cv2.cvtColor(f2, cv2.COLOR_BGR2GRAY), None, fx=0.25, fy=0.25).astype(np.float32)
    vung = (cv2.resize(a1, None, fx=0.25, fy=0.25) > 128) | (cv2.resize(a2, None, fx=0.25, fy=0.25) > 128)
    d = np.abs(g1 - g2)[vung]
    return float(d.mean() / 255) if d.size else 1.0


def diem_than(frames):
    """(độ mở miệng, độ cao cổ tay cao nhất, vị trí TB hai cổ tay) từng frame — DWPose 133 điểm.

    Miệng: môi trong trên/dưới (68 điểm mặt: 62/66 ⇒ 23+62, 23+66) chia chiều cao mặt (27→8).
    Cổ tay: COCO 9/10, y nhỏ hơn = cao hơn; trả −y/h để «lớn hơn = tay cao hơn». Vị trí TB hai cổ
    tay (y/h) dùng để biết lúc nào người đã VÀO DÁNG (`bo_cuc.diem_on_dinh`).
    """
    from musetalk.utils.preprocessing import _wholebody_keypoints

    mieng, tay, tb = [], [], []
    for f in frames:
        kp = np.asarray(_wholebody_keypoints(f))[0]
        mat = kp[23:91]
        cao = max(1.0, float(mat[8, 1] - mat[27, 1]))
        mieng.append(abs(float(mat[66, 1] - mat[62, 1])) / cao)
        tay.append(-min(float(kp[9, 1]), float(kp[10, 1])) / f.shape[0])
        tb.append((float(kp[9, 1]) + float(kp[10, 1])) / 2 / f.shape[0])
    return np.array(mieng), np.array(tay), np.array(tb)


# ───────────────────────────────────────────────────────── toàn bộ

def dung(avatar_dir, vae, fp, extra_margin, parsing_mode, bao=lambda buoc, tien_do: None):
    """Dựng cache MuseTalk cho nhân vật ở `avatar_dir` (đã có nguon/chinh.*). Trả dict meta
    (bo_cuc, w, h, so_frame) — bên gọi nạp `Avatar` (render miệng khép + poster) rồi mới ghi info.json."""
    nguon = os.path.join(avatar_dir, "nguon")
    tep = {os.path.splitext(t)[0]: os.path.join(nguon, t) for t in os.listdir(nguon)}
    if "chinh" not in tep:
        raise LoiDung("THIEU_VIDEO", "chưa có video chính")
    khung_luu = doc_khung_cho(avatar_dir) if "tay" in tep else None
    for ten in os.listdir(avatar_dir):                 # dựng lại ⇒ xoá cache cũ, giữ nguồn + khung chờ
        if ten not in ("nguon", "trang_thai.json", KHUNG_CHO_JPG, KHUNG_CHO_JSON, CAU_DUNG_JSON):
            p = os.path.join(avatar_dir, ten)
            if os.path.isfile(p):
                os.remove(p)
    device = torch.device("cuda")

    bao("chuan_hoa", 0.02)
    f_frames = doc_video(tep["chinh"], F_TOI_DA_S)
    g_frames = doc_video(tep["tay"], G_TOI_DA_S) if "tay" in tep else []
    if g_frames and g_frames[0].shape != f_frames[0].shape:
        # Hai clip khác cỡ ⇒ ép G về cỡ F (cùng khung hình là điều kiện của mối nối F↔G).
        h, w = f_frames[0].shape[:2]
        g_frames = [cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA) for g in g_frames]

    bao("tach_nen", 0.08)
    rvm = nap_rvm(device)
    try:
        f_alpha = tach_nen(f_frames, rvm, device)
        g_alpha = tach_nen(g_frames, rvm, device) if g_frames else []
    finally:
        del rvm
        torch.cuda.empty_cache()
    if float(np.mean(f_alpha[0] > 128)) < NGUOI_TOI_THIEU:
        raise LoiDung("KHONG_THAY_NGUOI", "không tách được người khỏi nền ở frame đầu")

    bao("phan_tich", 0.25)
    mieng, _, co_tay = diem_than(f_frames)
    tay_g = None
    if g_frames:
        _, tay, _ = diem_than(g_frames)
        tay_g = tay - tay[0]
    cd = chuyen_dong(f_frames, f_alpha)
    # Vùng chờ tìm SAU khi người đã vào dáng (cổ tay ổn định ở vị trí của phần lớn clip): video
    # AI chỉnh dáng đưa tay từ dáng ảnh lên trước bụng rồi NÓI NGAY — đo 2026-10-08: miệng chỉ khép
    # ở 8 frame đầu (dáng ảnh, tay buông) ⇒ chọn theo «miệng khép» TỪ ĐẦU clip là lấy đúng dáng SAI.
    # Nên: chỉ tìm sau điểm vào dáng; trong đó ưu tiên đoạn miệng khép (prompt: giây 0,5–2 đứng im
    # lặng, môi khép), không có thì chọn đoạn yên nhất. Vùng chờ chỉ ~0,1s (`CHO_SO_FRAME`) trong đó.
    # Có G (clip đưa tay portal sinh TỪ khung chờ của lần dựng trước) ⇒ vùng chờ = đúng khung đã
    # lưu, KHÔNG đo lại: G0 chính là frame đó, đo lệch một frame là mối nối F↔G giật.
    vung_luu = vung_cho_da_luu(khung_luu, CHO_SO_FRAME, len(f_frames))
    on_dinh = diem_on_dinh(co_tay) if vung_luu is None else 0
    if vung_luu is None:
        # Sàn cắt đầu: KHÔNG áp khi đã có khung chờ lưu — clip đưa tay G sinh TỪ đúng khung đó.
        on_dinh = max(on_dinh, round(doc_cat_dau_s(avatar_dir) * FPS))
    log.info("🧍 vào dáng ổn định từ frame %d (%.2fs)%s", on_dinh, on_dinh / FPS,
             f" — khung chờ đã lưu: frame {khung_luu}" if vung_luu else "")
    bo_cuc = do_bo_cuc(cd, mieng, len(g_frames), tay_g,
                       lech(f_frames[-1], f_frames[0], f_alpha[-1], f_alpha[0]),
                       vung_cho=vung_luu, dai_cho=CHO_SO_FRAME, toc_cho=CHO_TOC, tu_cho=on_dinh)
    if not g_frames:
        ok, jpg = cv2.imencode(".jpg", f_frames[bo_cuc.idle_from], [cv2.IMWRITE_JPEG_QUALITY, 95])
        if ok:
            luu_khung_cho(avatar_dir, bo_cuc.idle_from, jpg.tobytes())
    if bo_cuc.idle_from > 0:
        # CẮT phần trước vùng chờ: video AI «chỉnh dáng» mất ~1,5s đầu chuyển từ dáng trong ảnh
        # sang dáng chuẩn — giữ lại thì đường tư thế (lùi về chờ, dải nói) có lúc đi qua đúng đoạn
        # dáng SAI đó. Có G thì cắt cũng đúng: G0 = khung chờ = F0 sau khi cắt.
        a, b = bo_cuc.idle_from, bo_cuc.idle_to
        log.info("✂️  bỏ %d frame đầu (trước vùng chờ — đoạn chuyển dáng / dạo đầu)", a)
        f_frames, f_alpha, mieng = f_frames[a:], f_alpha[a:], mieng[a:]
        cd = np.concatenate([[0.0], cd[a + 1:]])
        # GIỮ vùng chờ vừa chọn (nay là [0, b−a]) — KHÔNG tìm lại: lượt tìm lại trên clip đã cắt
        # từng chọn một đoạn ĐANG NÓI ít cử động (lỗi đo được 2026-10-07).
        bo_cuc = do_bo_cuc(cd, mieng, len(g_frames), tay_g,
                           lech(f_frames[-1], f_frames[0], f_alpha[-1], f_alpha[0]),
                           vung_cho=(0, b - a), toc_cho=CHO_TOC)
    # Phần còn lại của đoạn im lặng (sau vùng chờ ~0,1s, tới ~1,4s) KHÔNG vào dải nói: MuseTalk
    # lấy frame gốc làm tham chiếu khuôn miệng — nói trên frame môi khép ra khẩu hình hẹp.
    bo_cuc.noi_tu = noi_tu_sau_khep(mieng, bo_cuc.idle_to, bo_cuc.noi_tu, bo_cuc.noi_den)
    log.info("📐 bố cục tự đo: %s", bo_cuc)
    if bo_cuc.g_dai == 0:                              # clip đưa tay quá ngắn ⇒ do_bo_cuc đã bỏ
        g_frames, g_alpha = [], []

    frames, alpha = f_frames + g_frames, f_alpha + g_alpha
    h, w = frames[0].shape[:2]
    video = os.path.join(avatar_dir, "nguon.mp4")
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "12",
                          "-pix_fmt", "yuv420p", video], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg lỗi khi ghi video nguồn")
    np.save(os.path.join(avatar_dir, "alpha.npy"), np.stack(alpha))

    bao("do_mat", 0.35)
    try:
        with av.giu_cudnn():
            boxes = av.prepare_avatar(video, avatar_dir, vae, fp, extra_margin, parsing_mode)
    except av.LoiKhongThayMat as e:
        giay = sorted({round(i / FPS, 1) for i in e.frames})[:6]
        raise LoiDung("KHONG_THAY_MAT", f"{len(e.frames)} frame không thấy mặt (giây {giay})") from e
    rong = float(np.median([x2 - x1 for x1, _y1, x2, _y2 in boxes]))
    if rong < MAT_TOI_THIEU_PX:
        raise LoiDung("MAT_NHO", f"mặt chỉ rộng ~{rong:.0f}px — cần quay gần hơn (≥ {MAT_TOI_THIEU_PX}px)")
    # Vùng chờ có miệng khép THẬT ⇒ dùng frame gốc (môi khép, nụ cười mỉm của video); không thì
    # frame MuseTalk trên âm im lặng (video đang nói ở đó — hiện frame gốc là mấp máy môi).
    bo_cuc.cho_goc = mieng_khep(mieng, bo_cuc.idle_from, bo_cuc.idle_to)
    log.info("👄 đứng chờ dùng %s",
             "frame GỐC (miệng khép thật)" if bo_cuc.cho_goc else "frame MuseTalk im lặng")
    return {"bo_cuc": bo_cuc.dict(), "w": w, "h": h, "so_frame": len(frames)}
