"""So sánh TTS: Soniox tts-rt-v2 vs ElevenLabs — pha REST (chất lượng + latency tổng)."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from _common import UA, api_key, audio_duration, ssl_context

SONIOX_REST = "https://tts-rt.soniox.com/tts"
EL_REST = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"

# Cấu hình chung để so sánh công bằng: mp3 44.1kHz 128kbps
FMT = {"container": "mp3", "sample_rate": 44100, "bitrate": 128000}

SSL_CTX = ssl_context()


def soniox_request(cfg: dict, text: str, key: str) -> tuple[bytes, dict]:
    body = {
        "model": cfg["model"],
        "language": "vi",
        "voice": cfg["voice"],
        "audio_format": FMT["container"],
        "sample_rate": FMT["sample_rate"],
        "bitrate": FMT["bitrate"],
        "text": text,
        "speed": cfg.get("speed", 1.0),
        "reduce_silence": cfg.get("reduce_silence", False),
    }
    req = urllib.request.Request(
        SONIOX_REST,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    return _timed_read(req)


def elevenlabs_request(cfg: dict, text: str, key: str) -> tuple[bytes, dict]:
    voice_settings = {
        "stability": cfg.get("stability", 1.0),
        "similarity_boost": cfg.get("similarity_boost", 0.75),
        "speed": cfg.get("speed", 1.0),
    }
    body = {
        "text": text,
        "model_id": cfg["model"],
        "voice_settings": voice_settings,
    }
    if cfg.get("language_code"):
        body["language_code"] = cfg["language_code"]
    # output_format là QUERY param ở ElevenLabs, không phải body field.
    fmt = f"mp3_{FMT['sample_rate']}_{FMT['bitrate'] // 1000}"
    req = urllib.request.Request(
        EL_REST.format(voice=cfg["voice"]) + f"?output_format={fmt}",
        data=json.dumps(body).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    return _timed_read(req)


def _timed_read(req: urllib.request.Request) -> tuple[bytes, dict]:
    """Gửi request, đo TTFB (chunk đầu) và tổng thời gian."""
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as resp:
            first = resp.read(1)
            ttfb = time.perf_counter() - start
            rest = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URLError: {exc.reason}") from exc
    total = time.perf_counter() - start
    return first + rest, {"ttfb_s": round(ttfb, 3), "total_s": round(total, 3)}


PROVIDERS = {"soniox": soniox_request, "elevenlabs": elevenlabs_request}


def run(configs: list[dict], cases: list[dict], out_dir: Path, repeats: int) -> list[dict]:
    keys = {cfg["provider"]: api_key(cfg["provider"]) for cfg in configs}
    results: list[dict] = []
    for cfg in configs:
        fn = PROVIDERS[cfg["provider"]]
        key = keys[cfg["provider"]]
        for case in cases:
            samples: list[dict] = []
            audio = b""
            error = None
            for i in range(repeats):
                try:
                    audio, timing = fn(cfg, case["text"], key)
                    samples.append(timing)
                except RuntimeError as exc:
                    error = str(exc)
                    print(f"FAIL {cfg['name']}/{case['id']}: {error}", file=sys.stderr)
                    break
                if i < repeats - 1:
                    time.sleep(0.4)
            if error or not samples:
                results.append({**_meta(cfg, case), "error": error})
                continue
            path = out_dir / f"{case['id']}__{cfg['name']}.mp3"
            path.write_bytes(audio)
            dur = audio_duration(path)
            ttfbs = sorted(s["ttfb_s"] for s in samples)
            totals = sorted(s["total_s"] for s in samples)
            results.append(
                {
                    **_meta(cfg, case),
                    "runs": len(samples),
                    "ttfb_best_s": ttfbs[0],
                    "ttfb_median_s": ttfbs[len(ttfbs) // 2],
                    "total_best_s": totals[0],
                    "total_median_s": totals[len(totals) // 2],
                    "audio_s": dur,
                    "bytes": len(audio),
                    "rtf": round(totals[0] / dur, 3) if dur else None,
                    "file": path.name,
                }
            )
            print(
                f"OK  {cfg['name']:34s} {case['id']:8s} ttfb={ttfbs[0]:.2f}s total={totals[0]:.2f}s audio={dur}s",
                flush=True,
            )
    return results


def _meta(cfg: dict, case: dict) -> dict:
    return {
        "config": cfg["name"],
        "provider": cfg["provider"],
        "model": cfg["model"],
        "voice": cfg["voice"],
        "case": case["id"],
        "chars": len(case["text"]),
    }


if __name__ == "__main__":
    base = Path(__file__).parent
    configs = json.loads((base / os.environ.get("CONFIGS_FILE", "configs.json")).read_text())
    cases_file = os.environ.get("CASES_FILE", "cases.json")
    cases = json.loads((base / cases_file).read_text())
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        cases = [c for c in cases if c["id"] in only.split(",")]
    repeats = int(os.environ.get("REPEATS", "3"))
    out = base / "out"
    out.mkdir(exist_ok=True)
    res = run(configs, cases, out, repeats)
    out_json = os.environ.get("RESULTS_FILE", "results_rest.json")
    (base / out_json).write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"\n{len(res)} kết quả -> {out_json}")
