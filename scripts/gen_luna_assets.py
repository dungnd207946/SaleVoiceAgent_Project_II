#!/usr/bin/env python3
"""Generate Luna persona image assets with Nano Banana (Gemini image models).

Produces the two visuals the Luna prototype pages reference:
  static/assets/luna-portrait.jpg  — half-body portrait for the voice screen frame
  static/assets/luna-avatar.jpg    — round headshot for the chat header / message avatars

The avatar is generated FROM the portrait (image-to-image) so the character stays
consistent across both screens. Reads GEMINI_API_KEY from .env. Re-run to refresh.

    python scripts/gen_luna_assets.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "static" / "assets"
PORTRAIT_MODEL = "gemini-3-pro-image"      # Nano Banana Pro — hero quality
AVATAR_MODEL = "gemini-3-pro-image"

LUNA = (
    "Luna is the friendly AI concierge of NobleX, a premium real-estate brand. Render her as "
    "a polished STYLIZED 3D CHARACTER — soft global illumination, gentle subsurface skin, clean "
    "modern high-end app-mascot look (elegant and premium, NOT a childish cartoon, NOT a real "
    "photograph). She is a warm, confident young Vietnamese woman in her late twenties: "
    "shoulder-length dark hair, gentle genuine smile, tailored emerald-green blazer over a cream "
    "top. Trustworthy, approachable, upscale. Rich emerald brand palette with a warm gold key "
    "light and a soft mint-teal rim light."
)

PORTRAIT_PROMPT = (
    f"{LUNA} Three-quarter / half-body, upper body facing the camera, relaxed welcoming pose, "
    "looking at the viewer. Vertical 3:4 composition, head near the top. Cinematic soft studio "
    "lighting, subtle depth of field. Seamless dark emerald gradient background (from #0d1a16 to "
    "#14261f) so she sits perfectly on a dark premium app screen. Polished 3D render, high detail. "
    "No text, no logos, no watermark."
)

AVATAR_PROMPT = (
    "Close-up headshot of the SAME stylized 3D character in the reference image — identical face, "
    "hair, emerald blazer and 3D render style. Centered face and shoulders, warm smile, soft mint "
    "rim-light and warm gold key light, dark emerald background. Square 1:1 composition for a small "
    "round chat avatar. Polished 3D render. No text, no logos, no watermark."
)


def _load_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*GEMINI_API_KEY\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    sys.exit("GEMINI_API_KEY not found in .env")


def _first_image(resp) -> bytes:
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
    raise RuntimeError("no image part in response")


def main() -> None:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_load_key())
    ASSETS.mkdir(parents=True, exist_ok=True)

    print(f"[1/2] portrait via {PORTRAIT_MODEL} ...")
    r = client.models.generate_content(
        model=PORTRAIT_MODEL,
        contents=[PORTRAIT_PROMPT],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="3:4"),
        ),
    )
    portrait = _first_image(r)
    (ASSETS / "luna-portrait.jpg").write_bytes(portrait)
    print(f"      saved static/assets/luna-portrait.jpg ({len(portrait)//1024} KB)")

    print(f"[2/2] avatar via {AVATAR_MODEL} (from portrait) ...")
    r = client.models.generate_content(
        model=AVATAR_MODEL,
        contents=[
            types.Part.from_bytes(data=portrait, mime_type="image/png"),
            AVATAR_PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="1:1"),
        ),
    )
    avatar = _first_image(r)
    (ASSETS / "luna-avatar.jpg").write_bytes(avatar)
    print(f"      saved static/assets/luna-avatar.jpg ({len(avatar)//1024} KB)")
    print("done.")


if __name__ == "__main__":
    main()
