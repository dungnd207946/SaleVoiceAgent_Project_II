"""Đo tải lip sync: N phiên NÓI CÙNG LÚC, xem GPU còn theo kịp real-time không.

Dùng để chọn LIPSYNC_MAX_SESSIONS trên máy deploy (giới hạn là SỨC TÍNH, không phải VRAM).
Mỗi phiên giả lập đúng một trình duyệt: gửi audio khối 10ms theo nhịp thật, xếp lịch phát
trễ 1,2s như portal (`TRE_PHAT_S`), rồi chấm từng frame nói về:

  thiếu  frame không về (service bỏ vì chắc chắn trễ)
  bỏ     về sau hạn quá 80ms ⇒ trình duyệt vứt (QUA_HAN_S ở avatarLipSync.ts)
  thưa   service render cách một frame (khẩu hình 12,5 fps) để đuổi kịp — chạy được nhưng
         kém mượt; nhiều nghĩa là GPU đang sát giới hạn

Chạy TRONG container (đã có numpy/websockets, token lấy từ env của container):

    docker exec odyssey-models-lipsync-musetalk-1 python3 do_tai.py -n 3
    # tải thật hơn: OmniVoice sinh câu song song như lúc agent đang trả lời
    docker exec odyssey-models-lipsync-musetalk-1 python3 do_tai.py -n 3 \\
        --tts ws://tts-omnivoice:8016/tts

Server phải đang đặt LIPSYNC_MAX_SESSIONS ≥ N (không thì phiên dư bị đóng 1013 — script
báo ra). Nên chạy lúc không ai đang dùng tab Voice. Đọc kết quả: chọn N lớn nhất mà
mọi phiên «đạt» KÈM tải TTS, rồi chừa một nấc an toàn nếu «thưa» đã cao.
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import struct
import time
import wave

import numpy as np
import websockets

FPS = 25
SR = 48000
KHOI = SR // 100                 # 10ms — đúng nhịp gateway stream xuống trình duyệt
TRE_PHAT_S = 1.2                 # portal avatarLipSync.ts
QUA_HAN_S = 0.08                 # portal: frame về trễ hơn mức này bị bỏ


def am_thanh(giay: float, wav: str | None) -> np.ndarray:
    """PCM16 48kHz. Không có wav ⇒ tín hiệu giống giọng nói (hài âm + nhịp âm tiết ~4Hz)
    — đủ để mọi lô đều chạy GPU; khẩu hình ra sao không quan trọng với phép đo tải."""
    n = int(giay * SR)
    if wav:
        with wave.open(wav) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
            if w.getnchannels() > 1:
                x = x[:: w.getnchannels()]
            x = np.repeat(x, max(1, SR // w.getframerate()))
        return np.resize(x, n).astype(np.int16)
    t = np.arange(n) / SR
    f0 = 140 + 30 * np.sin(2 * np.pi * 0.7 * t)
    pha = 2 * np.pi * np.cumsum(f0) / SR
    x = sum(np.sin(k * pha) / k for k in range(1, 8))
    bao = 0.55 + 0.45 * np.sin(2 * np.pi * 4.0 * t)
    return (x / np.max(np.abs(x)) * bao * 0.3 * 32767).astype(np.int16)


async def mot_phien(so: int, url: str, hdr: dict, pcm: np.ndarray, bat_dau: asyncio.Event) -> dict:
    lech = random.uniform(100, 5000)              # mỗi «trình duyệt» một đồng hồ riêng
    ctx = lambda: time.monotonic() + lech         # noqa: E731
    kq = {"so": so, "tu_choi": None, "frame": []}
    try:
        ws = await websockets.connect(url, additional_headers=hdr, max_size=None, open_timeout=15)
    except Exception as e:  # noqa: BLE001
        kq["tu_choi"] = f"không nối được: {e}"
        return kq
    async with ws:
        try:
            await asyncio.wait_for(ws.recv(), 15)             # {"type":"ready"}
        except websockets.ConnectionClosed as e:
            kq["tu_choi"] = f"bị đóng {e.rcvd.code if e.rcvd else '?'} {e.rcvd.reason if e.rcvd else ''}"
            return kq

        async def nhan():
            async for m in ws:
                if isinstance(m, bytes):
                    loai, t = struct.unpack("<B7xd", m[:16])
                    if loai == 1:
                        kq["frame"].append((t, t - ctx(), hashlib.blake2s(m[16:], digest_size=8).digest()))

        rx = asyncio.create_task(nhan())
        await bat_dau.wait()
        t0 = time.monotonic()
        moc = 0.0
        kq["t_dau"] = None
        for i in range(0, len(pcm), KHOI):
            k = pcm[i : i + KHOI]
            now = ctx()
            ts = now + TRE_PHAT_S if moc < now + 0.02 else moc
            moc = ts + len(k) / SR
            kq["t_dau"] = kq["t_dau"] or ts
            await ws.send(struct.pack("<dd", now, ts) + k.tobytes())
            await asyncio.sleep(max(0.0, t0 + (i + KHOI) / SR - time.monotonic()))
        kq["t_cuoi"] = moc
        await ws.send(json.dumps({"type": "het_luot", "t": moc}))
        await asyncio.sleep(TRE_PHAT_S + 1.5)
        rx.cancel()
    return kq


async def tai_tts(url: str, hdr: dict, dung: asyncio.Event):
    """OmniVoice sinh câu liên tục — mô phỏng agent đang trả lời các lượt khác."""
    i = 0
    while not dung.is_set():
        try:
            async with websockets.connect(url, additional_headers=hdr, max_size=None) as w:
                await w.send(json.dumps({"type": "synthesize", "text":
                    f"Câu {i}: căn hộ hai phòng ngủ rộng bảy mươi lăm mét vuông, giá khoảng ba tỷ rưỡi ạ."}))
                async for r in w:
                    if isinstance(r, str) and json.loads(r).get("type") in ("end", "error"):
                        break
        except Exception as e:  # noqa: BLE001
            print(f"  (tải TTS lỗi: {e} — đo tiếp không có tải TTS)")
            return
        i += 1
        await asyncio.sleep(0.5)


def cham(kq: dict) -> tuple[bool, str]:
    if kq["tu_choi"]:
        return False, f"phiên {kq['so']}: {kq['tu_choi']}"
    t_dau, t_cuoi = kq["t_dau"], kq["t_cuoi"]
    can = int((t_cuoi - t_dau) * FPS)
    fr = [f for f in kq["frame"] if t_dau <= f[0] < t_cuoi]
    du = {k for t, _, _ in fr if 0 <= (k := round((t - t_dau) * FPS)) < can}
    thieu = max(0, can - len(du))
    bo = sum(1 for _, s, _ in fr if s < -QUA_HAN_S)
    fr.sort()
    thua = sum(1 for a, b in zip(fr, fr[1:], strict=False) if a[2] == b[2])
    som = sorted(s for _, s, _ in fr) or [float("nan")]
    p5 = som[int(len(som) * 0.05)]
    hong = (thieu + bo) / max(can, 1)
    dat = hong <= 0.01
    return dat, (f"phiên {kq['so']}: {len(du)}/{can} frame · thiếu {thieu} · bỏ {bo} · "
                 f"thưa {thua / max(len(fr), 1):.0%} · sớm p5 {p5:+.2f}s min {som[0]:+.2f}s"
                 f" ⇒ {'ĐẠT' if dat else 'KHÔNG ĐẠT'}")


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", type=int, default=1, help="số phiên nói cùng lúc")
    ap.add_argument("--giay", type=float, default=30, help="độ dài câu nói mỗi phiên (s)")
    ap.add_argument("--url", default=f"ws://127.0.0.1:{os.environ.get('LIPSYNC_PORT', '8020')}/avatar")
    ap.add_argument("--wav", help="file wav giọng thật (mặc định: tín hiệu tổng hợp)")
    ap.add_argument("--tts", help="URL OmniVoice để tạo tải TTS song song, vd ws://tts-omnivoice:8016/tts")
    a = ap.parse_args()

    tok = os.environ.get("ODYSSEY_MODELS_TOKEN", "").strip()
    hdr = {"Authorization": f"Bearer {tok}"} if tok else {}
    pcm = am_thanh(a.giay, a.wav)
    print(f"Đo {a.n} phiên × {a.giay:.0f}s{' + tải OmniVoice' if a.tts else ''} → {a.url}")

    bat_dau, dung = asyncio.Event(), asyncio.Event()
    viec = [asyncio.create_task(mot_phien(i + 1, a.url, hdr, pcm, bat_dau)) for i in range(a.n)]
    await asyncio.sleep(2)                     # mọi phiên nối xong rồi mới cùng nói
    tts = asyncio.create_task(tai_tts(a.tts, hdr, dung)) if a.tts else None
    if tts:
        await asyncio.sleep(1)
    bat_dau.set()
    ket_qua = await asyncio.gather(*viec)
    dung.set()
    if tts:
        await tts

    dat_het = True
    for kq in ket_qua:
        dat, dong = cham(kq)
        dat_het &= dat
        print("  " + dong)
    print(f"KẾT LUẬN: {a.n} phiên {'ĐẠT' if dat_het else 'KHÔNG ĐẠT'}"
          " (đạt = thiếu + bỏ ≤ 1% frame ở MỌI phiên)")


if __name__ == "__main__":
    asyncio.run(main())
