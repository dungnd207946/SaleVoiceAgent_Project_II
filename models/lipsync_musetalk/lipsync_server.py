"""lipsync-musetalk :8020 — lip sync THỜI GIAN THỰC (MuseTalk 1.5) cho tab Voice của portal.

Protocol (ws://host:8020/avatar) — ĐỒNG HỒ LÀ TRÌNH DUYỆT (AudioContext), không phải server:

  client → server  binary: [f64 ctxNow][f64 tStart][PCM16 LE 48 kHz mono]
                    = một khối audio agent mà trình duyệt ĐÃ XẾP LỊCH phát ở `tStart`
                      (giây AudioContext). Trình duyệt trễ phát ~1,2s để kịp render.
                   text: {"type":"het_luot","t":<ctx>} · {"type":"cau","t":<ctx>,"s":<giây>}
                         · {"type":"gio_tay"} · {"type":"flush"}
  server → client  text {"type":"ready","w","h","fps"} rồi
                   binary: [u8 loai][7 byte đệm][f64 t][JPEG «stacked alpha»]
                    loai 0 = frame chờ (vẽ ngay), loai 1 = frame nói (vẽ khi currentTime ≥ t)
  ?avatar=<id>     chọn nhân vật (thiếu = mặc định); chưa dựng xong ⇒ đóng 4404 avatar_not_found
  GET /health      200 khi đã nạp xong (healthcheck compose).

API quản lý nhân vật khách (HTTP :8021 — upload video, dựng, xem trước): quan_ly.py.

Client của protocol: portal `src/features/platform/avatarLipSync.ts`.
Số phiên đồng thời: LIPSYNC_MAX_SESSIONS (mặc định 1); phiên vượt trần bị đóng 1013.
Giới hạn là SỨC TÍNH chứ không phải VRAM — model dùng chung, mỗi phiên cần ~25 frame/s
real-time. RTX 5060 Ti ~30 fps ⇒ 1 phiên; GPU mạnh hơn thì đo bằng `do_tai.py` rồi nâng.

Env:
  LIPSYNC_PORT            8020
  LIPSYNC_DATA_DIR        /data — volume: weights (models/) + cache avatar (avatars/)
  LIPSYNC_AVATAR          avatars/nguoi-dan.mp4 trong image (clip stacked-alpha, xem avatar.py)
  LIPSYNC_BATCH_SIZE      8 (16 hết VRAM khi chung card TTS)
  LIPSYNC_MAX_SESSIONS    1 — số phiên lip sync cùng lúc (xem trên)
  LIPSYNC_FACEPARSE_REPO  mirror HF của face-parse-bisent (weights.py — có kiểm SHA-256)
  LIPSYNC_UNET_{REPO,FILE,SHA256}  UNet (rỗng = fine-tune tiếng Việt, xem weights.py)
  HF_TOKEN                BẮT BUỘC với UNet mặc định (NobleX-AI/santa-lipsync-musetalk private)
  ODYSSEY_MODELS_TOKEN    token chung; rỗng = TẮT auth (dev loopback). Trình duyệt không đặt
                          được header nên nhận thêm `?token=` trên URL — xem README.
"""

import argparse
import asyncio
import contextlib
import json
import logging
import math
import os
import pickle
import struct
import sys
import threading
import time
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np
import torch
import websockets
from einops import rearrange
from transformers import WhisperModel

THU_MUC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THU_MUC)                      # musetalk/ + các module cạnh file này

import avatar as av  # noqa: E402
import quan_ly  # noqa: E402
import weights  # noqa: E402
from tu_the import (  # noqa: E402
    CUA_SO_HET,
    DU_THUA_S,
    FPS,
    HET_DOAN_S,
    JPEG_Q,
    LECH_CUA_SO_S,
    MAU16,
    MUON_TOI,
    NGU_CANH_PHAI,
    NGU_CANH_TRAI,
    NGUONG_IM,
    SR16,
    BoCuc,
    Doan,
    DuongTuThe,
    dang_noi,
)

log = logging.getLogger("lipsync-musetalk")
# Trần ước lượng thời gian một lô: lô 8 frame chạy real-time phải ≤ 0,32s; vượt xa là quá
# tải nhất thời — để ước lượng phình theo thì mọi frame sau bị coi là trễ (xem _render).
TG_LO_TOI_DA = 0.6
# Phiên KẸT GỬI: phía kia (tab trình duyệt treo / máy ngủ, đứng sau proxy vite) không đọc nữa mà TCP
# vẫn mở. Ping keepalive của `websockets` KHÔNG cứu được: ping xếp sau hàng MB frame chưa gửi nên
# không bao giờ đi, timeout không bao giờ chạy ⇒ phiên giữ chỗ mãi, mọi phiên mới «đã đủ 1/1»
# (gặp 2026-10-08: kẹt 44 phút, send-Q 2,6 MB). Dấu hiệu: đệm gửi của transport KHÁC 0 và ĐỨNG
# YÊN (không nhích một byte) liền KET_GUI_S giây ⇒ cắt. KHÔNG đo theo ngưỡng MB: dữ liệu dồn ở đệm
# kernel (~2,5 MB), đệm của transport chỉ lên ~64 KB rồi `send` bị chặn (đo bằng client giả treo).
KET_GUI_S = 8
TOKEN = os.environ.get("ODYSSEY_MODELS_TOKEN", "").strip()

# ─────────────────────────────────────────────────────────────── engine (GPU)

class Engine:
    """Model MuseTalk + whisper — DÙNG CHUNG cho mọi nhân vật và mọi phiên."""

    def __init__(self, args):
        # Import muộn: musetalk mở weights bằng đường dẫn TƯƠNG ĐỐI ./models/… nên chỉ
        # được nạp sau khi main() đã chdir vào data dir và tải đủ weights.
        global AudioProcessor, get_image_blending, FaceParsing
        from musetalk.utils.audio_processor import AudioProcessor
        from musetalk.utils.blending import get_image_blending
        from musetalk.utils.face_parsing import FaceParsing
        from musetalk.utils.utils import load_all_model

        self.args = args
        self.gpu_lock = threading.Lock()
        self.device = torch.device("cuda")
        vae, unet, pe = load_all_model(device=torch.device("cpu"))
        self.pe = pe.half().to(self.device)
        vae.vae = vae.vae.half().to(self.device)
        unet.model = unet.model.half().to(self.device)
        unet.device = self.device
        self.vae, self.unet = vae, unet
        self.dtype = unet.model.dtype
        self.timesteps = torch.tensor([0], device=self.device)
        self.ap = AudioProcessor(feature_extractor_path="./models/whisper")
        self.whisper = WhisperModel.from_pretrained("./models/whisper").to(self.device, dtype=self.dtype)
        self.whisper.eval()
        self.fp = FaceParsing(left_cheek_width=90, right_cheek_width=90)
        torch.cuda.empty_cache()

    def warm_up(self, av):
        # Warm-up: lần chạy CUDA đầu (nạp kernel, cuDNN autotune) mất vài trăm ms —
        # để nó rơi vào lúc khởi động, không vào batch đầu của cuộc gọi đầu tiên
        # (đo được: không warm-up thì 3 frame đầu trễ hạn tới 60ms).
        im = self.chunks(self.dac_trung(np.zeros(MAU16 * 12, np.float32), 0, 8), list(range(8)))
        self.render(av, im, list(range(8)))

    # ── các bước render ──
    @torch.no_grad()
    def dac_trung(self, wav16, f0_win, n_frame):
        """Whisper hidden states của cửa sổ `wav16` (bắt đầu đúng ở frame `f0_win`).

        Trả (features đã đệm 4 bước 0 bên trái, f0_win). Đệm trái LUÔN có: với frame
        tương đối r, clip [2r, 2r+10) của bản đệm = [2r−4, 2r+6) của bản gốc — đúng công
        thức get_whisper_chunk; khi r ≥ 2 (có ngữ cảnh trái thật) phần đệm không bị chạm.
        """
        feat = self.ap.feature_extractor(wav16, return_tensors="pt", sampling_rate=SR16).input_features
        hs = self.whisper.encoder(feat.to(self.device, self.dtype), output_hidden_states=True).hidden_states
        wf = torch.stack(hs, dim=2)[:, : math.floor(len(wav16) / SR16 * 50)]   # [1, T, 5, 384]
        wf = torch.cat([torch.zeros_like(wf[:, :4]), wf, torch.zeros_like(wf[:, :8])], 1)
        return wf, f0_win

    @torch.no_grad()
    def chunks(self, wf_f0, frames_abs):
        wf, f0_win = wf_f0
        clips = []
        for k in frames_abs:
            b = 2 * (k - f0_win)              # đã đệm 4 bước trái ⇒ khớp công thức gốc
            clips.append(wf[:, b : b + 10])
        x = torch.cat(clips, 0)               # [B, 10, 5, 384]
        return rearrange(x, "b c h w -> b (c h) w")

    @torch.no_grad()
    def render(self, av, whisper_batch, idxs):
        lat = torch.cat([av.latents[i] for i in idxs], 0).to(self.device, self.dtype)
        audio = self.pe(whisper_batch.to(self.device))
        pred = self.unet.model(lat, self.timesteps, encoder_hidden_states=audio).sample
        return self.vae.decode_latents(pred)


# ─────────────────────────────────────────────────────────────── nhân vật

class Avatar:
    """Dữ liệu MỘT nhân vật đã dựng: frame gốc, mặt nạ, latent, alpha, frame chờ, bố cục.

    Chỉ số tư thế `i` ∈ [0, N): N = 2·NB (xuôi rồi ngược), i ≥ NB là frame gốc N−1−i.
    """

    def __init__(self, eng: Engine, avatar_dir, bo_cuc: BoCuc):
        self.eng, self.avatar_dir, self.bo_cuc = eng, avatar_dir, bo_cuc
        (self.frames, self.masks, self.latents, self.coords, self.mask_boxes, self.alpha) = av.load_avatar(
            avatar_dir)
        self.N = len(self.coords)
        self.NB = self.N // 2                # số frame GỐC (cycle = xuôi + ngược)
        if bo_cuc.so_frame != self.NB:
            raise RuntimeError(f"bố cục {bo_cuc.so_frame} frame ≠ cache {self.NB} frame ({avatar_dir})")
        self.h, self.w = self.frames.shape[1:3]
        # Vùng tư thế CHỜ: frame GỐC (không qua MuseTalk — miệng khép thật), đưa qua
        # đưa lại chậm như người dẫn Kling cũ (`nguoiDan.ts`: khung 1–15, tốc 0,45).
        # Nhân vật khách (`cho_goc=False`): KHÔNG dùng frame gốc — video AI có thể đang mấp máy môi
        # ở đó; `frame_cho` rơi về frame MuseTalk trên âm im lặng (miệng khép) cho cả vùng chờ.
        self.idle = (
            {i: self.ghep(self.frame(i), i) for i in range(bo_cuc.idle_from, bo_cuc.idle_to + 1)}
            if bo_cuc.cho_goc else {}
        )
        self.im_lang = self._im_lang()
        self._poster()

    def _goc(self, arr, i):
        return arr[i] if len(arr) == self.N else arr[i if i < self.NB else self.N - 1 - i]

    def frame(self, i):
        return self._goc(self.frames, i)

    def ghep(self, bgr, idx):
        """BGR + alpha[idx] → JPEG stacked (trên: màu đã nhân alpha, dưới: mặt nạ)."""
        a = np.asarray(self._goc(self.alpha, idx))
        mau = (bgr.astype(np.uint16) * a[:, :, None] // 255).astype(np.uint8)
        mat = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
        ok, buf = cv2.imencode(".jpg", np.vstack([mau, mat]), [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
        return buf.tobytes()

    def _im_lang(self):
        """Frame MuseTalk trên audio IM LẶNG cho mọi tư thế gốc — dùng khi người đang ở
        tư thế NÓI/ĐƯA TAY mà không có tiếng (đi về chờ, khoảng lặng giữa câu): frame gốc
        ở đó đang há miệng (clip Kling vốn là cảnh nói). Vùng chờ thì dùng frame gốc."""
        path = os.path.join(self.avatar_dir, "im_lang.pkl")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return pickle.load(f)
        log.info("👄 render %d frame miệng khép (một lần, cache vào volume)…", self.NB)
        eng = self.eng
        feat = eng.chunks(eng.dac_trung(np.zeros(MAU16 * (1 + NGU_CANH_PHAI), np.float32), 0, 1), [0])
        out = {}
        for s in range(0, self.NB, 8):
            idxs = list(range(s, min(s + 8, self.NB)))
            with eng.gpu_lock:               # nhường lô cho phiên đang gọi (dựng nhân vật lúc có cuộc gọi)
                faces = eng.render(self, feat.repeat(len(idxs), 1, 1), idxs)
            for f, i in zip(faces, idxs, strict=False):
                out[i] = self.ghep(self.blend(f, i), i)
        with open(path + ".tmp", "wb") as f:      # tmp + rename: bị kill giữa chừng không để lại file dở
            pickle.dump(out, f)
        os.replace(path + ".tmp", path)
        # Mốc UNet đã render cache này — lần boot sau weights.don_cache_theo_unet so mốc.
        with open(os.path.join(self.avatar_dir, weights.MOC_UNET_AVATAR), "w") as f:
            f.write(weights.UNET_SHA256)
        return out

    def frame_cho(self, i):
        """JPEG của tư thế `i` khi KHÔNG có tiếng (nửa ngược dùng frame gốc tương ứng)."""
        j = i if i < self.NB else self.N - 1 - i
        return self.idle.get(j) or self.im_lang[j]

    def _poster(self):
        """PNG RGBA của tư thế chờ đầu — portal dùng làm ảnh chờ trước khi có kết nối."""
        path = os.path.join(self.avatar_dir, "poster.png")
        if os.path.exists(path):
            return
        st = cv2.imdecode(np.frombuffer(self.frame_cho(self.bo_cuc.idle_from), np.uint8), cv2.IMREAD_COLOR)
        h = st.shape[0] // 2
        mau, a = st[:h].astype(np.float32), st[h:, :, 0].astype(np.float32)
        rgb = np.clip(mau * 255 / np.maximum(a[:, :, None], 1), 0, 255).astype(np.uint8)
        cv2.imwrite(path, np.dstack([rgb, a.astype(np.uint8)]))

    def blend(self, face, idx):
        x1, y1, x2, y2 = self.coords[idx]
        face = cv2.resize(face.astype(np.uint8), (x2 - x1, y2 - y1))
        return get_image_blending(np.array(self.frame(idx)), face, self.coords[idx],
                                  self.masks[idx], self.mask_boxes[idx])


class KhoAvatar:
    """Nhân vật đã nạp, LRU. Nhân vật mặc định luôn nằm trong kho; nhân vật khách nạp khi
    có phiên/xem trước cần tới (vài giây — frames/alpha là mmap) và bị đẩy ra khi kho đầy
    (`LIPSYNC_MAX_AVATARS`). Phiên đang giữ tham chiếu thì vẫn chạy tiếp bình thường."""

    def __init__(self, eng: Engine, mac_dinh: Avatar, mac_dinh_id: str, toi_da: int):
        self.eng, self.mac_dinh_id, self.toi_da = eng, mac_dinh_id, toi_da
        self._kho: OrderedDict[str, Avatar] = OrderedDict({mac_dinh_id: mac_dinh})
        self._khoa = threading.Lock()
        self._khoa_nap: dict[str, threading.Lock] = {}

    def lay(self, avatar_id: str) -> Avatar:
        """Avatar sẵn sàng, hoặc KeyError (chưa có / chưa dựng xong)."""
        with self._khoa:
            if avatar_id in self._kho:
                self._kho.move_to_end(avatar_id)
                return self._kho[avatar_id]
            khoa = self._khoa_nap.setdefault(avatar_id, threading.Lock())
        with khoa:                                       # hai phiên cùng mở một nhân vật ⇒ nạp một lần
            with self._khoa:
                if avatar_id in self._kho:
                    return self._kho[avatar_id]
            info = av.doc_info(avatar_id)
            if info is None:
                raise KeyError(avatar_id)
            a = Avatar(self.eng, av.thu_muc(avatar_id), BoCuc.tu_dict(info["bo_cuc"]))
            with self._kho_va_don():
                self._kho[avatar_id] = a
            return a

    @contextlib.contextmanager
    def _kho_va_don(self):
        with self._khoa:
            yield
            while len(self._kho) > self.toi_da + 1:          # +1: nhân vật mặc định không tính
                for k in self._kho:
                    if k != self.mac_dinh_id:
                        del self._kho[k]
                        break

    def bo(self, avatar_id: str):
        with self._khoa:
            if avatar_id != self.mac_dinh_id:
                self._kho.pop(avatar_id, None)


# ─────────────────────────────────────────────────────────────── phiên

class Phien:
    def __init__(self, eng: Engine, av: Avatar, ws, loop):
        self.eng, self.av, self.ws, self.loop = eng, av, ws, loop
        self.lech = None                     # ctx_time − monotonic (ước lượng tốt nhất)
        self._mau_lech = deque()             # (monotonic, mẫu lech) trong LECH_CUA_SO_S gần nhất
        self.doan: list[Doan] = []
        self.dong = False
        self.pool = ThreadPoolExecutor(4)
        self.thong_ke = {"batch": 0, "frame": 0, "im": 0, "tre": 0, "thua": 0, "gpu_s": 0.0}
        self.tg_lo = 0.3                     # thời gian GPU một lô đủ (s), cập nhật dần
        self.t_noi_cuoi = -1e9               # t (ctx) của frame nói muộn nhất đã gửi
        self.duong = DuongTuThe(av.bo_cuc)
        self._im_truoc = None                # tư thế frame im lặng gửi gần nhất
        self.tieng: dict[int, bool] = {}     # nhịp (floor(t_server·25)) → có tiếng

    def _nhip(self, t_ctx):
        return int(math.floor((t_ctx - self.lech) * FPS))

    def idx_cua(self, t_ctx):
        return self.tu_the(self._nhip(t_ctx))

    def tu_the(self, nhip):
        return self.duong.toi(nhip, self.co_tieng)

    def co_tieng(self, n):
        return dang_noi(lambda m: self.tieng.get(m, False), self.duong.het, n, self.duong.giu_noi)

    def nhan_audio(self, data: bytes):
        ctx_now, t_start = struct.unpack("<dd", data[:16])
        pcm = np.frombuffer(data[16:], np.int16)
        # Độ lệch đồng hồ = MAX trong cửa sổ trượt (mẫu ít trễ mạng nhất) chứ không max
        # từ đầu phiên: đồng hồ AudioContext chạy theo card âm thanh, có thể trôi/khựng
        # so với monotonic — max cả phiên sẽ kẹt ở giá trị cũ.
        now = time.monotonic()
        self._mau_lech.append((now, ctx_now - now))
        while self._mau_lech[0][0] < now - LECH_CUA_SO_S:
            self._mau_lech.popleft()
        self.lech = max(v for _, v in self._mau_lech)
        cuoi = self.doan[-1] if self.doan else None
        if cuoi is None or cuoi.chot or abs(t_start - cuoi.t_cuoi) > 0.01:
            if cuoi is not None:
                cuoi.chot = True
            self.doan.append(Doan(t_start))
        d = self.doan[-1]
        d.them(pcm)
        # Đo tiếng từng frame 40ms vừa đủ ⇒ bảng nhịp có tiếng (nuôi bộ điều khiển tư thế).
        for k in range(d.da_do, d.tong16 // MAU16):
            x = d.lay16(k * MAU16, (k + 1) * MAU16)
            nhip = int(math.floor((d.t0 + k / FPS - self.lech) * FPS))
            co = float(np.sqrt(np.mean(x**2))) >= NGUONG_IM
            self.tieng[nhip] = self.tieng.get(nhip, False) or co
            het = self.duong.het
            if co and het is not None and het < nhip <= het + MUON_TOI:
                self.duong.dat_het_luot(nhip)    # audio cuối lượt tới sau sự kiện agent_done
        d.da_do = d.tong16 // MAU16
        if len(self.tieng) > 4000:           # dọn nhịp cũ (> ~2 phút)
            cu = int(time.monotonic() * FPS) - 3000
            self.tieng = {k: v for k, v in self.tieng.items() if k >= cu}

    # ── vòng render: chạy trong thread riêng (GPU) ──
    def vong_render(self):
        B = self.eng.args.batch_size
        while not self.dong:
            viec = self._lay_viec(B)
            if viec is None:
                time.sleep(0.01)
                continue
            d, ks, chot = viec
            try:
                self._render(d, ks)
            except Exception as e:  # noqa: BLE001 — một batch hỏng không được giết cả phiên
                log.exception("render lỗi: %r", e)
            d.xong = ks[-1] + 1
            if chot and d.xong * MAU16 >= d.tong16:
                self.doan.remove(d)
        # Luồng này là nơi DUY NHẤT submit vào pool ⇒ đóng pool ở đây không đua với submit.
        # Nhiều phiên nối tiếp nhau thì không để lại 4 thread ghép mỗi phiên.
        self.pool.shutdown(wait=False)

    def _lay_viec(self, B):
        for d in list(self.doan):
            if not d.chot and time.monotonic() - d.nhan_luc > HET_DOAN_S:
                d.chot = True
            co = d.tong16 // MAU16
            if co - d.xong >= B + NGU_CANH_PHAI:
                return d, list(range(d.xong, d.xong + B)), False
            if d.chot:
                n = math.ceil(d.tong16 / MAU16) - d.xong
                if n <= 0:
                    self.doan.remove(d)
                    continue
                return d, list(range(d.xong, d.xong + min(n, B))), True
        return None

    def _render(self, d: Doan, ks):
        """Render một lô frame. Ba điều chống «miệng đơ» khi GPU bị tranh (OmniVoice sinh
        câu kế tiếp SONG SONG trong lúc avatar đang nói — đo được: không có nó thì sau
        ~9s frame trễ tới 0,7s và trình duyệt bỏ hết):
          1. Bỏ RIÊNG frame chắc chắn trễ (t < bây giờ + thời gian render một lô), không
             bỏ cả lô — phần còn lại vẫn kịp.
          2. Sắp trễ (dư < thời gian một lô + DU_THUA_S) ⇒ render CÁCH MỘT frame, mỗi ảnh
             giữ hai nhịp (khẩu hình 12,5 fps) — nửa công GPU để đuổi kịp, thưa còn hơn đơ.
          3. Ghép mặt + nén JPEG chạy NỀN trong pool: luồng GPU không ngồi chờ CPU.
        """
        eng = self.eng
        t_ks = [d.t0 + k / FPS for k in ks]
        f0 = max(0, ks[0] - NGU_CANH_TRAI)
        can = (ks[-1] + 1 + NGU_CANH_PHAI) * MAU16
        wav = d.lay16(f0 * MAU16, can)
        if len(wav) < can - f0 * MAU16:
            wav = np.concatenate([wav, np.zeros(can - f0 * MAU16 - len(wav), np.float32)])
        doan_batch = d.lay16(ks[0] * MAU16, (ks[-1] + 1) * MAU16)
        self.thong_ke["batch"] += 1
        ctx_now = time.monotonic() + self.lech
        if len(doan_batch) == 0 or float(np.sqrt(np.mean(doan_batch**2))) < NGUONG_IM:
            # Im ⇒ không tốn GPU, gửi frame chờ đúng lịch để miệng khép đúng lúc.
            for t in t_ks:
                i = self.idx_cua(t)
                # Gateway stream cả lúc im ⇒ chỉ gửi khi tư thế ĐỔI (trình duyệt giữ ảnh cũ).
                if t >= ctx_now and i != self._im_truoc:
                    self.thong_ke["im"] += 1
                    self._gui(1, t, self.av.frame_cho(i))
                self._im_truoc = i
            return
        han = ctx_now + self.tg_lo + 0.05
        con = [(k, t) for k, t in zip(ks, t_ks, strict=False) if t >= han]
        self.thong_ke["tre"] += len(ks) - len(con)
        if not con:
            # Cả lô trễ ⇒ hạ ước lượng: `tg_lo` chỉ được cập nhật khi CÓ lô render, nên
            # một lô chậm bất thường (vd. lần chạy đầu) mà không hạ ở đây thì mọi lô sau
            # đều bị coi là trễ và bỏ — kẹt vĩnh viễn, miệng đứng yên cả phiên.
            self.tg_lo *= 0.5
            return
        # Đuôi im lặng SAU tiếng cuối của lượt (đã biết `het_luot`) mà nằm chung lô với tiếng:
        # frame chờ miệng khép, không qua MuseTalk — ngữ cảnh whisper (0,4s trái) còn dính tiếng
        # nên môi mấp máy thêm vài frame sau khi voice đã tắt.
        het = self.duong.het
        if het is not None:
            for k, t in [x for x in con if self._nhip(x[1]) > het and not self.co_tieng(self._nhip(x[1]))]:
                self._gui(1, t, self.av.frame_cho(self.idx_cua(t)))
                con.remove((k, t))
            if not con:
                return
        thua = con[0][1] - ctx_now < self.tg_lo + DU_THUA_S and len(con) > 1
        ve = con[::2] if thua else con
        if thua:
            self.thong_ke["thua"] += len(con) - len(ve)
        idxs = [self.idx_cua(t) for _, t in ve]
        g0 = time.monotonic()
        with eng.gpu_lock:
            wf = eng.dac_trung(wav, f0, len(ks))
            wb = eng.chunks(wf, [k for k, _ in ve])
            faces = eng.render(self.av, wb, idxs)
        dt = time.monotonic() - g0
        self.thong_ke["gpu_s"] += dt
        # ước lượng thời gian một lô ĐỦ (trung bình trượt) — dùng cho hạn ở lô sau
        self.tg_lo = min(TG_LO_TOI_DA, 0.8 * self.tg_lo + 0.2 * dt * len(ks) / len(ve))
        self.thong_ke["frame"] += len(ve)
        self._im_truoc = None
        cac_t = [t for _, t in con]
        for j, ((_k, t), face, idx) in enumerate(zip(ve, faces, idxs, strict=False)):
            # thưa ⇒ ảnh này giữ cả nhịp của frame bị bỏ ngay sau nó
            nhip = cac_t[2 * j : 2 * j + 2] if thua else [t]
            self.pool.submit(self._ghep_gui, face, idx, nhip)

    def _ghep_gui(self, face, idx, cac_t):
        try:
            jpg = self.av.ghep(self.av.blend(face, idx), idx)
            for t in cac_t:
                self._gui(1, t, jpg)
        except Exception as e:  # noqa: BLE001
            log.exception("ghép lỗi: %r", e)

    def _gui(self, loai, t, jpg):
        if loai == 1:
            self.t_noi_cuoi = max(self.t_noi_cuoi, t)
        goi = struct.pack("<B7xd", loai, t) + jpg
        asyncio.run_coroutine_threadsafe(self._send(goi), self.loop)

    def dem_gui(self):
        """Số byte đang nằm trong đệm gửi (chưa ra mạng)."""
        tr = getattr(self.ws, "transport", None)
        return tr.get_write_buffer_size() if tr is not None else 0

    async def _send(self, goi):
        try:
            await self.ws.send(goi)
        except Exception:  # noqa: BLE001
            pass

    async def canh_ket_gui(self):
        """Task RIÊNG (không gửi gì — `vong_idle` cũng kẹt ở `send` khi đệm đầy) cắt phiên kẹt gửi."""
        truoc, dung_yen = -1, 0
        while not self.dong:
            await asyncio.sleep(1)
            dem = self.dem_gui()
            dung_yen = dung_yen + 1 if dem > 0 and dem == truoc else 0
            truoc = dem
            if dung_yen >= KET_GUI_S:
                log.warning("✂️  phiên kẹt gửi %d byte đứng yên %ds (phía kia không đọc) — cắt", dem, dung_yen)
                self.ws.transport.abort()
                return

    # ── nhịp idle 25 fps ──
    async def vong_idle(self):
        """Frame chờ — CHỈ gửi khi tư thế đổi (tốc 0,45 ⇒ ~11 lần/giây thay vì 25),
        và NGỪNG hẳn khi đang/sắp có lời nói: trình duyệt khi đó chỉ vẽ frame nói, giải
        mã frame chờ rồi vứt là gánh gấp đôi cho main thread (nguyên nhân giật)."""
        nhip = time.monotonic()
        truoc = None
        while not self.dong:
            now = time.monotonic()
            dang_noi = self.lech is not None and now + self.lech < self.t_noi_cuoi + 0.1
            co_viec = any(d.tong16 > d.xong * MAU16 for d in list(self.doan))
            i = self.tu_the(int(math.floor(now * FPS)))
            if not dang_noi and not co_viec and i != truoc:
                await self._send(struct.pack("<B7xd", 0, 0.0) + self.av.frame_cho(i))
                truoc = i
            elif dang_noi or co_viec:
                truoc = None                 # hết nói ⇒ gửi lại ngay frame chờ đúng tư thế
            nhip += 1 / FPS
            await asyncio.sleep(max(0, nhip - time.monotonic()))


# ─────────────────────────────────────────────────────────────── server

def _env(ten, mac_dinh, kieu=str):
    v = os.environ.get(ten, "").strip()
    return kieu(v) if v else mac_dinh


def _tham_so(ws, ten):
    try:
        return parse_qs(urlsplit(ws.request.path).query).get(ten, [""])[0].strip()
    except Exception:  # noqa: BLE001
        return ""


def _hop_le(ws) -> bool:
    """Token chung ODYSSEY_MODELS_TOKEN — header `Authorization: Bearer` (như mọi service
    khác) HOẶC `?token=` trên URL: WebSocket của trình duyệt KHÔNG đặt được header, và
    client của service này là trình duyệt (qua reverse proxy của portal, xem README)."""
    if not TOKEN:
        return True
    try:
        hdr = ws.request.headers.get("Authorization", "")
    except Exception:  # noqa: BLE001
        return False
    q = _tham_so(ws, "token")
    return hdr.removeprefix("Bearer ").strip() == TOKEN or q == TOKEN


async def _process_request(connection, request):
    if request.path.split("?", 1)[0] == "/health":
        return connection.respond(HTTPStatus.OK, "ok")
    return None


def main():
    logging.basicConfig(level=os.environ.get("ODYSSEY_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    nguon_mac_dinh = os.path.join(THU_MUC, "avatars", "nguoi-dan.mp4")
    ap.add_argument("--avatar-src", default=_env("LIPSYNC_AVATAR", nguon_mac_dinh))
    ap.add_argument("--avatar-id", default=_env("LIPSYNC_AVATAR_ID", "nguoi_dan"))
    ap.add_argument("--data-dir", default=_env("LIPSYNC_DATA_DIR", "/data"))
    ap.add_argument("--port", type=int, default=_env("LIPSYNC_PORT", 8020, int))
    ap.add_argument("--batch-size", type=int, default=_env("LIPSYNC_BATCH_SIZE", 8, int))
    ap.add_argument("--max-sessions", type=int, default=_env("LIPSYNC_MAX_SESSIONS", 1, int),
                    help="số phiên đồng thời; vượt ⇒ đóng 1013 (đo bằng do_tai.py trước khi nâng)")
    ap.add_argument("--prepare-only", action="store_true", help="tải weights + dựng avatar rồi thoát")
    # Bố cục clip người dẫn — xem DOAN/KHUNG ở portal nguoiDan.ts. Đổi clip là phải đo lại.
    ap.add_argument("--f-cuoi", type=int, default=120, help="frame cuối đoạn nói F; G bắt đầu ngay sau")
    ap.add_argument("--noi-tu", type=int, default=22, help="dải tư thế lúc nói (đầu có cử động)")
    ap.add_argument("--noi-den", type=int, default=100)
    ap.add_argument("--nhac-tay", type=int, default=46, help="frame trong G bắt đầu nhấc tay")
    ap.add_argument("--idle-from", type=int, default=1, help="frame đầu vùng tư thế chờ (miệng khép)")
    ap.add_argument("--idle-to", type=int, default=15, help="frame cuối vùng tư thế chờ")
    ap.add_argument("--idle-speed", type=float, default=0.45, help="tốc đưa qua lại trong vùng chờ")
    ap.add_argument("--extra-margin", type=int, default=10)
    ap.add_argument("--parsing-mode", default="jaw")
    ap.add_argument("--http-port", type=int, default=_env("LIPSYNC_HTTP_PORT", 8021, int),
                    help="API quản lý nhân vật (dựng / trạng thái / xem trước) — xem quan_ly.py")
    ap.add_argument("--max-avatars", type=int, default=_env("LIPSYNC_MAX_AVATARS", 3, int),
                    help="số nhân vật KHÁCH giữ nạp sẵn cùng lúc (LRU; mặc định luôn nạp)")
    ap.add_argument("--tts-url", default=_env("LIPSYNC_TTS_URL", "ws://localhost:8016/tts"),
                    help="service TTS cho video xem trước (protocol remote ws /tts)")
    args = ap.parse_args()
    if args.max_sessions < 1:
        ap.error("LIPSYNC_MAX_SESSIONS phải ≥ 1")
    args.avatar_src = os.path.abspath(args.avatar_src)

    # Mọi weights + cache nằm trong data dir (volume). musetalk mở file bằng đường dẫn
    # tương đối ./models/… và S3FD tìm weights trong cache torch hub ⇒ chdir + TORCH_HOME.
    os.makedirs(args.data_dir, exist_ok=True)
    os.chdir(args.data_dir)
    os.environ["TORCH_HOME"] = os.path.join(args.data_dir, "torch")
    weights.dam_bao_weights(args.data_dir)
    weights.don_cache_theo_unet(args.data_dir)

    eng = Engine(args)
    avatar_dir = os.path.join("avatars", args.avatar_id)
    av.chuan_bi(args.avatar_src, avatar_dir, eng.vae, eng.fp, args.extra_margin, args.parsing_mode)
    bo_cuc = BoCuc(f_cuoi=args.f_cuoi, g_dai=args.f_cuoi + 1, noi_tu=args.noi_tu, noi_den=args.noi_den,
                   nhac_tay=args.nhac_tay, idle_from=args.idle_from, idle_to=args.idle_to,
                   idle_speed=args.idle_speed, vong=True)
    mac_dinh = Avatar(eng, avatar_dir, bo_cuc)
    eng.warm_up(mac_dinh)
    log.info("🧑 avatar sẵn sàng: %d tư thế (%s)", mac_dinh.N, avatar_dir)
    if args.prepare_only:
        return
    kho = KhoAvatar(eng, mac_dinh, args.avatar_id, args.max_avatars)
    quan_ly.chay_nen(eng, kho, Avatar, args, TOKEN)

    # Các phiên dùng chung Engine; GPU tuần tự hoá bằng eng.gpu_lock. Thời gian chờ lock
    # được tính vào `tg_lo` của từng phiên (g0 đo TRƯỚC khi lấy lock) ⇒ khi nhiều phiên
    # tranh nhau, mỗi phiên tự chuyển sang render thưa thay vì trễ hạn.
    dang_mo: set[Phien] = set()
    dang_nap: set = set()                            # phiên đang nạp nhân vật (đã giữ chỗ)

    async def xu_ly(ws):
        if not _hop_le(ws):
            log.warning("🔒 auth rejected %s", getattr(ws, "remote_address", None))
            await ws.close(code=1008, reason="unauthorized")
            return
        if len(dang_mo) + len(dang_nap) >= args.max_sessions:
            log.info("⛔ từ chối phiên: đã đủ %d/%d", len(dang_mo), args.max_sessions)
            await ws.close(1013, "avatar_busy")       # vượt sức GPU ⇒ mọi phiên cùng giật
            return
        loop = asyncio.get_running_loop()
        # Nhân vật của phiên: `?avatar=<id>` (portal gửi nhân vật workspace đang dùng); thiếu
        # = nhân vật mặc định. Chưa có / chưa dựng xong ⇒ đóng 4404, portal lùi về mặc định.
        avatar_id = _tham_so(ws, "avatar") or args.avatar_id
        dang_nap.add(ws)
        try:
            hop_le = av.MA_HOP_LE.match(avatar_id)
            a = await loop.run_in_executor(None, kho.lay, avatar_id) if hop_le else None
        except KeyError:
            a = None
        except Exception:  # noqa: BLE001 — cache hỏng không được giết server
            log.exception("nạp nhân vật %s lỗi", avatar_id)
            a = None
        finally:
            dang_nap.discard(ws)
        if a is None:
            log.info("❓ nhân vật %r chưa sẵn sàng — đóng 4404", avatar_id)
            await ws.close(4404, "avatar_not_found")
            return
        p = Phien(eng, a, ws, loop)
        dang_mo.add(p)
        await ws.send(json.dumps({"type": "ready", "w": int(a.w), "h": int(a.h), "fps": FPS,
                                  "avatar": avatar_id}))
        th = threading.Thread(target=p.vong_render, daemon=True)
        th.start()
        idle = asyncio.create_task(p.vong_idle())
        canh = asyncio.create_task(p.canh_ket_gui())
        log.info("🔌 phiên mở %s nhân vật=%s (%d/%d)", getattr(ws, "remote_address", None),
                 avatar_id, len(dang_mo), args.max_sessions)
        try:
            async for msg in ws:
                if isinstance(msg, bytes) and len(msg) > 16:
                    p.nhan_audio(msg)
                elif isinstance(msg, str):
                    lenh = json.loads(msg).get("type")
                    if lenh == "flush":
                        p.doan.clear()
                    elif lenh == "het_luot":  # agent_done/agent_interrupted: audio lượt này hết ở ctx t
                        t = float(json.loads(msg).get("t", 0))
                        if p.lech is not None and t > 0:
                            moc = int(math.floor((t - p.lech) * FPS)) - 1
                            # Mốc trình duyệt báo = cuối audio ĐÃ xếp lịch, gồm cả khung im lặng
                            # gateway gửi kèm ⇒ lấy nhịp CÓ TIẾNG cuối cùng ≤ mốc (nếu có trong 2s).
                            co = [m for m in range(moc - CUA_SO_HET, moc + 1) if p.tieng.get(m)]
                            p.duong.dat_het_luot(co[-1] if co else moc)
                    elif lenh == "cau":  # agent_speaking: câu bắt đầu ở ctx t, dài ~s giây (ước từ text)
                        d = json.loads(msg)
                        t, s = float(d.get("t", 0)), float(d.get("s", 0))
                        if p.lech is not None and t > 0 and s > 0:
                            p.duong.dat_cau(int(math.floor((t - p.lech + s) * FPS)))
                    elif lenh == "gio_tay":  # agent gửi ảnh ⇒ đưa tay giới thiệu (như người dẫn cũ)
                        p.duong.yeu_cau_gio_tay(int(time.monotonic() * FPS))
        except websockets.ConnectionClosed:
            pass
        finally:
            p.dong = True
            idle.cancel()
            canh.cancel()
            dang_mo.discard(p)
            log.info("🔌 phiên đóng %s (còn %d)", p.thong_ke, len(dang_mo))

    async def chay():
        async with websockets.serve(xu_ly, "0.0.0.0", args.port, process_request=_process_request,
                                    max_size=8 * 1024 * 1024):
            log.info("🚀 lipsync-musetalk listening on 0.0.0.0:%d/avatar (auth=%s, max_sessions=%d)",
                     args.port, "on" if TOKEN else "off", args.max_sessions)
            await asyncio.Future()

    asyncio.run(chay())


if __name__ == "__main__":
    main()
