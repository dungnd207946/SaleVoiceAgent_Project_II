"""Add a shared voice from ElevenLabs Voice Library to your account.

Usage:
    python scripts/add_shared_voice.py <voice_id> [--name NAME] [--update-env]

Example:
    python scripts/add_shared_voice.py pGapy9MNHCukzJtjavF0 --name Luna_VN --update-env

Why this script exists:
    Voices browsed in the Voice Library can't be used directly via API.
    They must first be "added" to your account — which mints a NEW voice_id
    owned by you. This script does both steps (find public_owner_id → add).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

load_dotenv(ENV_PATH)

API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
BASE = "https://api.elevenlabs.io/v1"


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def find_public_owner(voice_id: str) -> tuple[str, dict]:
    """Find voice_id in /shared-voices → return (public_owner_id, voice_meta).

    Fast path: ?search={voice_id} returns the voice directly in one call.
    Fallback: paginate by `page` integer (ElevenLabs uses page-based, not cursor).
    """
    headers = {"xi-api-key": API_KEY}

    # Fast path — ElevenLabs `search` param accepts voice_id.
    r = httpx.get(
        f"{BASE}/shared-voices",
        headers=headers,
        params={"page_size": 10, "search": voice_id},
        timeout=15,
    )
    if r.status_code == 200:
        for v in r.json().get("voices", []):
            if v.get("voice_id") == voice_id:
                owner = v.get("public_owner_id")
                if not owner:
                    die(f"Voice {voice_id} found but has no public_owner_id")
                return owner, v

    # Fallback — paginate all pages by integer `page` (0, 1, 2, …)
    scanned = 0
    for page in range(0, 200):  # hard cap 200 pages * 100 voices = 20,000
        params = {"page_size": 100, "page": page}
        r = httpx.get(f"{BASE}/shared-voices", headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            die(f"shared-voices lookup failed: {r.status_code} {r.text[:200]}")

        payload = r.json()
        voices = payload.get("voices", [])
        for v in voices:
            scanned += 1
            if v.get("voice_id") == voice_id:
                owner = v.get("public_owner_id")
                if not owner:
                    die(f"Voice {voice_id} found but has no public_owner_id")
                return owner, v

        if not payload.get("has_more", False) or not voices:
            break

    die(
        f"Voice {voice_id} not found in shared library (scanned {scanned} voices). "
        f"Check the ID, or the voice may not be publicly shared."
    )
    raise SystemExit  # unreachable; for type-checkers


def already_in_account(voice_id: str) -> str | None:
    """Return voice name if voice_id already exists in user's account."""
    r = httpx.get(
        f"{BASE}/voices/{voice_id}",
        headers={"xi-api-key": API_KEY},
        timeout=10,
    )
    if r.status_code == 200:
        return r.json().get("name", "unknown")
    return None


def add_shared_voice(public_owner_id: str, voice_id: str, new_name: str) -> str:
    """POST /v1/voices/add/{public_owner_id}/{voice_id} → returns NEW voice_id."""
    r = httpx.post(
        f"{BASE}/voices/add/{public_owner_id}/{voice_id}",
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
        json={"new_name": new_name},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        die(f"add failed: {r.status_code} {r.text[:300]}")

    new_id = r.json().get("voice_id")
    if not new_id:
        die(f"add succeeded but response missing voice_id: {r.text[:300]}")
    return new_id


def update_env_file(new_voice_id: str) -> None:
    """Rewrite ELEVENLABS_TTS_VOICE_ID line in .env."""
    if not ENV_PATH.exists():
        print(f"NOTE: {ENV_PATH} does not exist — skipping env update.")
        return

    original = ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"^ELEVENLABS_TTS_VOICE_ID\s*=.*$", re.MULTILINE)

    if pattern.search(original):
        updated = pattern.sub(f"ELEVENLABS_TTS_VOICE_ID={new_voice_id}", original)
    else:
        sep = "" if original.endswith("\n") else "\n"
        updated = f"{original}{sep}ELEVENLABS_TTS_VOICE_ID={new_voice_id}\n"

    ENV_PATH.write_text(updated, encoding="utf-8")
    print(f"✓ Updated {ENV_PATH} → ELEVENLABS_TTS_VOICE_ID={new_voice_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("voice_id", help="Shared voice_id from ElevenLabs Voice Library")
    ap.add_argument("--name", default=None, help="Name for the voice in your account (default: derived)")
    ap.add_argument("--update-env", action="store_true", help="Rewrite ELEVENLABS_TTS_VOICE_ID in .env after adding")
    args = ap.parse_args()

    if not API_KEY:
        die("ELEVENLABS_API_KEY not set — put it in .env or export it")

    voice_id = args.voice_id.strip()

    existing = already_in_account(voice_id)
    if existing:
        print(f"Voice {voice_id} is ALREADY in your account (name: {existing}).")
        print("Paste this into .env:")
        print(f"  ELEVENLABS_TTS_VOICE_ID={voice_id}")
        if args.update_env:
            update_env_file(voice_id)
        return

    print(f"Searching shared library for {voice_id}…")
    public_owner_id, meta = find_public_owner(voice_id)
    display_name = meta.get("name", "<unknown>")
    lang = meta.get("language", "?")
    accent = meta.get("accent", "?")
    gender = meta.get("gender", "?")
    print(f"✓ Found: {display_name} (lang={lang}, accent={accent}, gender={gender})")
    print(f"  public_owner_id={public_owner_id}")

    new_name = args.name or f"{display_name}_imported"
    new_id = add_shared_voice(public_owner_id, voice_id, new_name)
    print(f"✓ Added to your account: voice_id={new_id}  name={new_name}")
    print()
    print("Paste this into .env:")
    print(f"  ELEVENLABS_TTS_VOICE_ID={new_id}")

    if args.update_env:
        update_env_file(new_id)


if __name__ == "__main__":
    main()
