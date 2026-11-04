"""Tính RTF và biên phát lại từ kết quả streaming."""

import json
from pathlib import Path

from _common import audio_duration

base = Path(__file__).parent


for tag, fn in (("greet", "results_stream_greet.json"), ("long", "results_stream_long.json")):
    if not (base / fn).exists():
        print(f"(bỏ qua {tag}: chưa có {fn})")
        continue
    rows = json.loads((base / fn).read_text())
    print(f"\n=== case {tag} ===")
    print(f"{'target':30s}{'ttfb_med':>9s}{'gen_tot':>9s}{'audio':>8s}{'RTF':>6s}{'biên_s':>8s}")
    print("-" * 70)
    for r in rows:
        if r.get("error"):
            print(f"{r['target']:30s} ERROR {r['error'][:30]}")
            continue
        ext = "ulaw" if "ulaw" in r["target"] or "mulaw" in r["target"] else "pcm" if "pcm" in r["target"] else "mp3"
        f = base / "out" / f"stream_{tag}__{r['target']}.{ext}"
        if not f.exists():
            print(f"{r['target']:30s} (thiếu file {f.name})")
            continue
        d = audio_duration(f)
        rtf = r["total_median_s"] / d
        margin = (r["ttfb_median_s"] + d) - r["total_median_s"]
        print(f"{r['target']:30s}{r['ttfb_median_s']:9.3f}{r['total_median_s']:9.2f}{d:8.2f}{rtf:6.2f}{margin:8.2f}")
print("\nRTF < 1 = sinh nhanh hơn realtime. biên_s > 0 = phát liên tục không hụt.")
