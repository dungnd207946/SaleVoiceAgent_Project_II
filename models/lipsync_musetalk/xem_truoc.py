"""Video XEM TRƯỚC nhân vật: câu demo → TTS → MuseTalk (offline) → mp4 có tiếng.

Khách xem nhân vật mới nói thử vài câu TRƯỚC khi chốt dùng. Đi đúng đường của phiên
real-time — cùng `DuongTuThe` (chờ → nói → về chờ), cùng frame miệng khép, cùng ảnh
«stacked alpha» trình duyệt nhận — chỉ khác là render một lèo rồi ghép lên màu nền.
Không chiếm phiên real-time (LIPSYNC_MAX_SESSIONS) nên xem trước được cả lúc có cuộc gọi.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile

import cv2
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from tu_the import FPS, MAU16, NGUONG_IM, SR16, DuongTuThe, dang_noi

TRUOC_S = 0.4              # im lặng trước câu — người đứng chờ một nhịp rồi mới nói
SAU_S = 0.8                # im lặng sau câu — thấy người về tư thế chờ
TOI_DA_S = 28.0            # whisper encoder nhận tối đa 30s mỗi lượt
LAN_CAN = 2                # frame có tiếng trong ±2 frame ⇒ render MuseTalk (miệng chuyển mượt)


def tts(url, token, text, voice=None, timeout=90):
    """Gọi service TTS (protocol remote: ws /tts, PCM16 mono). Trả (pcm int16, sr)."""
    from websockets.sync.client import connect

    sr = int(os.environ.get("LIPSYNC_TTS_SR", "24000"))
    hdr = {"Authorization": f"Bearer {token}"} if token else None
    goi = {"type": "synthesize", "text": text}
    if voice:
        goi["voice"] = voice
    pcm = bytearray()
    with connect(url, additional_headers=hdr, open_timeout=10, close_timeout=2, max_size=None) as ws:
        ws.send(json.dumps(goi))
        while True:
            msg = ws.recv(timeout=timeout)
            if isinstance(msg, bytes):
                pcm += msg
            elif json.loads(msg).get("type") in ("end", "error"):
                break
    if not pcm:
        raise RuntimeError("TTS không trả tiếng")
    return np.frombuffer(bytes(pcm), np.int16), sr


def mau_nen(hex_):
    h = (hex_ or "#eef1f5").lstrip("#")
    if len(h) != 6:
        h = "eef1f5"
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return np.array([b, g, r], np.float32)


def render(eng, av, pcm, sr, nen="#eef1f5"):
    """Trả bytes mp4 (H.264 + AAC) — nhân vật nói `pcm` trên nền màu `nen`."""
    x = pcm.astype(np.float32) / 32768.0
    x = x[: int(TOI_DA_S * sr)]
    x = np.concatenate([np.zeros(int(TRUOC_S * sr), np.float32), x, np.zeros(int(SAU_S * sr), np.float32)])
    g = math.gcd(sr, SR16)
    wav16 = resample_poly(x, SR16 // g, sr // g).astype(np.float32) if sr != SR16 else x
    n = math.ceil(len(wav16) / MAU16)
    wav16 = np.concatenate([wav16, np.zeros(n * MAU16 - len(wav16) + MAU16 * 4, np.float32)])

    tieng = [float(np.sqrt(np.mean(wav16[k * MAU16 : (k + 1) * MAU16] ** 2))) >= NGUONG_IM for k in range(n)]
    duong = DuongTuThe(av.bo_cuc)
    co = [k for k, t in enumerate(tieng) if t]
    if co:
        duong.dat_het_luot(co[-1])             # offline ⇒ biết trước tiếng cuối, về chờ đúng lúc

    def co_tieng(m):
        return dang_noi(lambda k: 0 <= k < n and tieng[k], duong.het, m, duong.giu_noi)

    tu_the = [duong.toi(k, co_tieng) for k in range(n)]
    noi = [any(tieng[j] for j in range(max(0, k - LAN_CAN), min(n, k + LAN_CAN + 1))) for k in range(n)]

    jpg = [None] * n
    can = [k for k in range(n) if noi[k]]
    if can:
        with eng.gpu_lock:
            wf = eng.dac_trung(wav16, 0, n)
        B = eng.args.batch_size
        for s in range(0, len(can), B):
            ks = can[s : s + B]
            idxs = [tu_the[k] for k in ks]
            with eng.gpu_lock:
                faces = eng.render(av, eng.chunks(wf, ks), idxs)
            for k, face, i in zip(ks, faces, idxs, strict=False):
                jpg[k] = av.ghep(av.blend(face, i), i)
    for k in range(n):
        if jpg[k] is None:
            jpg[k] = av.frame_cho(tu_the[k])

    nen_bgr = mau_nen(nen)
    h, w = av.h, av.w
    with tempfile.TemporaryDirectory() as tmp:
        wav_path, mp4 = os.path.join(tmp, "a.wav"), os.path.join(tmp, "o.mp4")
        sf.write(wav_path, x, sr)
        p = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
             "-r", str(FPS), "-i", "-", "-i", wav_path,
             "-c:v", "libx264", "-crf", "22", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", mp4],
            stdin=subprocess.PIPE,
        )
        for j in jpg:
            st = cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR).astype(np.float32)
            mau, a = st[:h], st[h:, :, :1] / 255.0
            p.stdin.write(np.clip(mau + nen_bgr * (1 - a), 0, 255).astype(np.uint8).tobytes())
        p.stdin.close()
        if p.wait() != 0:
            raise RuntimeError("ffmpeg lỗi khi ghép video xem trước")
        with open(mp4, "rb") as f:
            return f.read()
