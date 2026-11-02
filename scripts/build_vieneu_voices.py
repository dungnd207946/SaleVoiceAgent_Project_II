"""Offline: encode reference WAVs → vieneu preset codes → reference/presets.json.

The runtime codec (`neuphonic/neucodec-onnx-decoder-int8`) is decode-only, so we
encode here with the full torch codec `neuphonic/neucodec`. `backbone_repo=""`
skips the backbone download — we only pay for the codec.

    python scripts/build_vieneu_voices.py                  # default voice = luna
    python scripts/build_vieneu_voices.py --default gemini
    python scripts/build_vieneu_voices.py --codec-device cpu

Reads reference/voices.json ({name: {wav, text, ...}}), writes reference/presets.json
in the vieneu preset format. Idempotent (overwrites). Requires `pip install -e
".[tts-vieneu]"` + GPU for a reasonable codec speed.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("build_vieneu_voices")

_REFERENCE_DIR = Path(__file__).resolve().parents[1] / "src" / "noble_agent" / "voice" / "tts" / "reference"


def build_presets(
    voices: dict[str, dict],
    encode_fn: Callable[[str], list[int]],
    default_voice: str,
) -> dict:
    """Pure transform: voices.json dict → vieneu presets.json dict.

    `encode_fn(wav_path) -> list[int]` is injected so this stays testable without
    the heavy torch codec. `wav_path` is the resolved absolute path to the WAV.
    """
    if default_voice not in voices:
        raise ValueError(f"default_voice {default_voice!r} not present in voices ({sorted(voices)})")

    presets: dict[str, dict] = {}
    for name, entry in voices.items():
        wav_path = str(_REFERENCE_DIR / entry["wav"])
        presets[name] = {"codes": encode_fn(wav_path), "text": entry["text"]}

    return {
        "meta": {
            "spec": "vieneu.voice.presets",
            "spec_version": "1.0",
            "source": "NobleX-AI santa reference",
        },
        "default_voice": default_voice,
        "presets": presets,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--default", default="luna", help="default_voice name")
    parser.add_argument("--codec-device", default="cuda", help="cuda | cpu")
    parser.add_argument(
        "--codec-repo",
        default="neuphonic/neucodec",
        help="full torch codec with encode_code (NOT the onnx decoder)",
    )
    args = parser.parse_args()

    voices_path = _REFERENCE_DIR / "voices.json"
    voices = json.loads(voices_path.read_text(encoding="utf-8"))
    logger.info("Loaded %d reference voices from %s", len(voices), voices_path)

    # Heavy imports are local so the module collects without the optional dep.
    from vieneu import Vieneu

    logger.info("Loading codec %s on %s (backbone skipped) ...", args.codec_repo, args.codec_device)
    tts = Vieneu(
        mode="standard",
        backbone_repo="",  # skip backbone download — codec only
        codec_repo=args.codec_repo,
        codec_device=args.codec_device,
        gguf_filename=None,
    )

    def encode_fn(wav_path: str) -> list[int]:
        codes = tts.encode_reference(wav_path)
        return tts.to_list(codes)

    out = build_presets(voices, encode_fn, default_voice=args.default)

    out_path = _REFERENCE_DIR / "presets.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %d presets (default=%s) → %s", len(out["presets"]), args.default, out_path)


if __name__ == "__main__":
    main()
