"""Pre-generate tool-ack bridge-phrase audio assets via the CONFIGURED TTS backend.

Runs each phrase through the same TTS that serves live calls — the backend
selected by `TTS_BACKEND` (vieneu / vieneu_vllm / remote / elevenlabs), same
voice and `tts_sample_rate` — and writes the concatenated PCM16 output to
`assets/voice/acks/*.pcm`. Also writes a `manifest.json` recording the exact
settings used so the runtime loader (voice_agent._load_ack_assets) can warn
when live-TTS config drifts from the cached assets (e.g. you switched
VIENEU_VOICE_ID after generation).

The generator deliberately does NOT use the runtime init-fallback chain: if
the configured backend can't be constructed it fails loudly instead of
silently baking assets in a fallback voice.

At call time the VoiceAgent loads these blobs into memory and pushes them
directly into the audio track when a slow tool starts, eliminating the live
TTS TTFB on every bridge phrase.

Usage
-----
    uv run python scripts/gen_ack_assets.py
    uv run python scripts/gen_ack_assets.py --phrases "custom.txt"
    uv run python scripts/gen_ack_assets.py --voice-id <id> --out-dir <dir>
    uv run python scripts/gen_ack_assets.py --manifest-only   # backfill manifest
                                                              # for existing .pcm
    uv run python scripts/gen_ack_assets.py --resume-ack      # addressee-gate
                                                              # resume_ack.pcm

Re-run any time you change the backend, voice, or phrase list.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Default bridge phrases — short, natural, Vietnamese. Keep ~10 variants so
# the agent doesn't sound robotic across calls/turns (picked at random per
# turn). Phrases must stay generic "checking / please hold" — they play for
# ANY slow tool (search, pricing, booking availability alike).
# Register follows persona Style (2026-08-27): no "Dạ…" opener, no "quý khách",
# at most one "ạ", ≤ ~2 s — a colleague saying "để em xem", not a call centre.
_DEFAULT_PHRASES: list[str] = [
    "Để em kiểm tra ngay.",
    "Anh chị chờ em một chút nhé.",
    "Em xem trong hệ thống ngay đây.",
    "Đợi em một lát nhé.",
    "Em tra nhanh rồi báo lại ngay.",
    "Để em xem lại thông tin đã.",
    "Em kiểm tra một chút, anh chị chờ em nhé.",
    "Anh chị giữ máy giúp em một chút.",
    "Em tìm ngay đây ạ.",
    "Để em xem bên em còn gì phù hợp.",
]


def _slugify(text: str) -> str:
    """Make a filesystem-safe name from a Vietnamese phrase."""
    vn_map = str.maketrans(
        "àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
        "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ",
        "aaaaaaaaaaaaaaaaadeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyy"
        "AAAAAAAAAAAAAAAAADEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYY",
    )
    slug = text.translate(vn_map).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug[:50] or "phrase"


def _load_phrases(path: Path | None) -> list[str]:
    if path is None:
        return _DEFAULT_PHRASES
    if not path.exists():
        print(f"error: phrases file not found: {path}", file=sys.stderr)
        sys.exit(2)
    phrases: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            phrases.append(line)
    if not phrases:
        print(f"error: no phrases in {path}", file=sys.stderr)
        sys.exit(2)
    return phrases


def _build_tts(settings):
    """Construct EXACTLY the configured backend — no fallback chain here."""
    backend = settings.tts_backend
    if backend == "elevenlabs":
        if not settings.elevenlabs_api_key:
            print("error: ELEVENLABS_API_KEY is not set (checked .env).", file=sys.stderr)
            sys.exit(1)
        from noble_agent.voice.tts.elevenlabs import AsyncElevenLabsTTS

        return AsyncElevenLabsTTS()
    if backend == "remote":
        from noble_agent.voice.tts.remote import RemoteTTS

        return RemoteTTS()
    if backend == "vieneu_vllm":
        from noble_agent.voice.tts.vieneu_vllm import AsyncVieNeuVLLMTTS

        return AsyncVieNeuVLLMTTS()
    from noble_agent.voice.tts.vieneu import AsyncVieNeuTTS

    return AsyncVieNeuTTS()


def _current_voice_id(settings, override: str) -> str:
    if override:
        return override
    if settings.tts_backend == "elevenlabs":
        return settings.elevenlabs_tts_voice_id
    return settings.vieneu_voice_id


def _build_manifest(settings, voice_id: str, entries: list[dict]) -> dict:
    manifest = {
        "backend": settings.tts_backend,
        "voice_id": voice_id,
        "sample_rate": settings.tts_sample_rate,
        "assets": entries,
    }
    if settings.tts_backend == "elevenlabs":
        manifest.update(
            {
                "model": settings.elevenlabs_tts_model,
                "speed": settings.elevenlabs_tts_speed,
                "stability": settings.elevenlabs_tts_stability,
                "similarity_boost": settings.elevenlabs_tts_similarity_boost,
                "language_code": settings.elevenlabs_tts_language_code,
            }
        )
    return manifest


def _write_manifest(out_dir: Path, manifest: dict) -> None:
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest → {manifest_path}")


def _merge_existing_entries(out_dir: Path, new_entries: list[dict]) -> list[dict]:
    """Keep manifest entries of .pcm files NOT touched by this run (still on
    disk), so a partial run (--start-index / --phrases subset) doesn't drop
    the untouched assets from the manifest."""
    by_file = {e["file"]: e for e in new_entries}
    manifest_path = out_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            for e in json.loads(manifest_path.read_text(encoding="utf-8")).get("assets", []):
                name = e.get("file")
                if name and name not in by_file and (out_dir / name).is_file():
                    by_file[name] = e
        except Exception as exc:  # noqa: BLE001
            print(f"warning: could not merge old manifest ({exc}) — writing this run only", file=sys.stderr)
    return [by_file[k] for k in sorted(by_file)]


def _manifest_only(settings, out_dir: Path, voice_id: str) -> None:
    """Backfill manifest.json for already-generated .pcm files. The caller is
    asserting these assets ARE the current voice — verify by ear first."""
    # resume_ack.pcm is a separate fixed asset (see _generate_resume_ack /
    # voice_agent._load_resume_ack_asset) — never part of the tool-ack pool
    # or its manifest.
    pcms = sorted(p for p in out_dir.glob("*.pcm") if p.name != "resume_ack.pcm")
    if not pcms:
        print(f"error: no .pcm files in {out_dir}", file=sys.stderr)
        sys.exit(2)
    entries = []
    for p in pcms:
        n = p.stat().st_size
        entries.append(
            {
                "file": p.name,
                "bytes": n,
                "duration_s": round(n / 2 / settings.tts_sample_rate, 3),
            }
        )
    _write_manifest(out_dir, _build_manifest(settings, voice_id, entries))
    print(f"backfilled for {len(entries)} existing assets (no audio regenerated).")


async def _generate_one(tts, text: str, out_path: Path) -> int:
    """Stream `text` via the configured TTS, write concatenated PCM16 to
    `out_path`. Returns bytes written."""
    pcm_blob = bytearray()
    async for chunk in tts.stream(text):
        if chunk:
            pcm_blob.extend(chunk)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(pcm_blob))
    return len(pcm_blob)


async def _generate_resume_ack(settings, out_dir: Path, voice_id_override: str) -> None:
    """Synthesize `settings.addressee_resume_ack_text` to a FIXED filename
    `resume_ack.pcm` — separate from the tool-ack phrase pool. voice_agent
    loads it via `_load_resume_ack_asset` (not the `*.pcm` glob used for
    random tool-ack picks), so it must NOT be added to manifest.json."""
    text = (settings.addressee_resume_ack_text or "").strip()
    if not text:
        print("error: settings.addressee_resume_ack_text is empty", file=sys.stderr)
        sys.exit(2)
    tts = _build_tts(settings)
    if voice_id_override:
        tts.set_voice(voice_id_override)
    out_path = out_dir / "resume_ack.pcm"
    n = await _generate_one(tts, text, out_path)
    secs = (n // 2) / settings.tts_sample_rate
    print(f"resume-ack → {out_path}  {n:,} bytes  ({secs:.2f}s)  text={text!r}")


async def _main_async(args: argparse.Namespace) -> None:
    # Lazy imports so --help works even if deps aren't installed.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from noble_agent.config import settings  # noqa: E402

    out_dir = Path(args.out_dir)
    voice_id = _current_voice_id(settings, args.voice_id)

    if args.resume_ack:
        await _generate_resume_ack(settings, out_dir, args.voice_id)
        return

    if args.manifest_only:
        _manifest_only(settings, out_dir, voice_id)
        return

    phrases = _load_phrases(Path(args.phrases) if args.phrases else None)
    tts = _build_tts(settings)
    if args.voice_id:
        tts.set_voice(args.voice_id)

    print(
        f"backend={settings.tts_backend}  voice={voice_id}  "
        f"rate={settings.tts_sample_rate}Hz  phrases={len(phrases)}  out={out_dir}",
    )

    entries: list[dict] = []
    for i, text in enumerate(phrases, start=args.start_index):
        slug = _slugify(text)
        out_path = out_dir / f"{i:02d}_{slug}.pcm"
        print(f"  [{i - args.start_index + 1}/{len(phrases)}] {text!r}")
        try:
            n = await _generate_one(tts, text, out_path)
            samples = n // 2
            secs = samples / settings.tts_sample_rate
            print(f"         → {out_path.name}  {n:,} bytes  ({secs:.2f}s)")
            entries.append({
                "file": out_path.name,
                "text": text,
                "bytes": n,
                "duration_s": round(secs, 3),
            })
        except Exception as exc:  # noqa: BLE001
            print(f"         ! failed: {exc}", file=sys.stderr)

    _write_manifest(out_dir, _build_manifest(settings, voice_id, _merge_existing_entries(out_dir, entries)))
    print("done. Listen to the output before shipping — vieneu synth is non-deterministic.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--phrases",
        default="",
        help="Optional text file (one phrase per line; '#' lines skipped). "
             "Default: built-in 5-phrase list.",
    )
    ap.add_argument(
        "--out-dir",
        default="assets/voice/acks",
        help="Where to write .pcm files (default: assets/voice/acks).",
    )
    ap.add_argument(
        "--voice-id",
        default="",
        help="Override voice id (default: VIENEU_VOICE_ID, or "
             "ELEVENLABS_TTS_VOICE_ID when TTS_BACKEND=elevenlabs).",
    )
    ap.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="First file-number prefix (default 1). Use e.g. --start-index 6 "
             "with a --phrases file of NEW phrases to add variants without "
             "regenerating the existing takes.",
    )
    ap.add_argument(
        "--manifest-only",
        action="store_true",
        help="Don't synthesize; write manifest.json for the existing .pcm "
             "files in --out-dir using CURRENT settings. Use only when the "
             "existing assets are verified to be the current voice.",
    )
    ap.add_argument(
        "--resume-ack",
        action="store_true",
        help="Synthesize settings.addressee_resume_ack_text to "
             "<out-dir>/resume_ack.pcm (addressee-gate resume ack) instead of "
             "the tool-ack phrase pool. Fixed filename, not added to manifest.json.",
    )
    args = ap.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
