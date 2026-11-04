"""Tính chi phí thực trên mỗi giờ audio, dựa trên tỉ lệ ký tự/giây đo được."""

import json
from pathlib import Path

# Đơn giá công bố (2026-08). Khoá theo NHÀ CUNG CẤP / MODEL, không theo tên cấu hình:
# tên cấu hình do người chạy tự đặt trong configs.json, nên một sổ chép tay theo tên
# sẽ lệch ngay lần ai đó thêm cấu hình mới (đã xảy ra: `-rs` làm script ném KeyError).
GIA_SONIOX = {"kind": "per_audio_hour", "usd": 0.70}  # mọi model tts-rt-*
GIA_ELEVENLABS = {
    "eleven_flash_v2_5": {"kind": "per_1k_chars", "usd": 0.05},
    "eleven_turbo_v2_5": {"kind": "per_1k_chars", "usd": 0.05},
    "eleven_v3": {"kind": "per_1k_chars", "usd": 0.10},
    "eleven_multilingual_v2": {"kind": "per_1k_chars", "usd": 0.10},
}


def don_gia(provider: str, model: str) -> dict:
    """Ném rõ ràng khi gặp model chưa có giá — đoán giá thì bảng chi phí sai mà im lặng."""
    if provider == "soniox":
        return GIA_SONIOX
    if provider == "elevenlabs":
        try:
            return GIA_ELEVENLABS[model]
        except KeyError:
            raise SystemExit(f"chưa khai đơn giá cho model ElevenLabs {model!r} — thêm vào GIA_ELEVENLABS") from None
    raise SystemExit(f"chưa khai đơn giá cho nhà cung cấp {provider!r}")


base = Path(__file__).parent
rows = [r for r in json.loads((base / "results_rest.json").read_text()) if not r.get("error")]

by_cfg: dict[str, dict] = {}
for r in rows:
    acc = by_cfg.setdefault(r["config"], {"chars": 0, "audio_s": 0.0, "provider": r["provider"], "model": r["model"]})
    acc["chars"] += r["chars"]
    acc["audio_s"] += r["audio_s"]

print(f"{'config':24s}{'chars':>7s}{'audio_s':>9s}{'ch/s':>7s}{'ch/giờ':>10s}{'USD/giờ audio':>15s}")
print("-" * 74)
out = []
for cfg, acc in by_cfg.items():
    price = don_gia(acc["provider"], acc["model"])
    chars_per_s = acc["chars"] / acc["audio_s"]
    chars_per_h = chars_per_s * 3600
    usd_h = price["usd"] if price["kind"] == "per_audio_hour" else chars_per_h / 1000 * price["usd"]
    print(f"{cfg:24s}{acc['chars']:7d}{acc['audio_s']:9.2f}{chars_per_s:7.2f}{chars_per_h:10.0f}{usd_h:15.2f}")
    out.append({"config": cfg, "chars_per_audio_s": round(chars_per_s, 2), "usd_per_audio_hour": round(usd_h, 3)})

cheapest = min(out, key=lambda r: r["usd_per_audio_hour"])
print(f"\nRẻ nhất: {cheapest['config']} = ${cheapest['usd_per_audio_hour']}/giờ audio")
for r in sorted(out, key=lambda r: r["usd_per_audio_hour"]):
    ratio = r["usd_per_audio_hour"] / cheapest["usd_per_audio_hour"]
    print(f"  {r['config']:24s} ${r['usd_per_audio_hour']:6.2f}/giờ   = {ratio:5.2f}x")
(base / "results_cost.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
