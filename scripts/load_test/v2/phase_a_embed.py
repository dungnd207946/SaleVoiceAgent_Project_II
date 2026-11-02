"""Load client for the embed service (:8013). POST /embed {"texts","is_query"} + Bearer."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ENV = dotenv_values(ROOT / ".env")
URL = ENV["EMBED_REMOTE_URL"].rstrip("/") + "/embed"
TOKEN = (ENV.get("EMBED_REMOTE_TOKEN") or "").strip()
QUERY = "bảng giá và chính sách thanh toán căn hộ dự án Noble"


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=256)
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        async def make_request() -> float:
            t = time.monotonic()
            r = await client.post(URL, json={"texts": [QUERY], "is_query": True})
            r.raise_for_status()
            if not r.json().get("embeddings"):
                raise ValueError("no embeddings in response")
            return time.monotonic() - t

        print(f"embed load → {URL} (token={'yes' if TOKEN else 'no'})")
        result = await common.run_campaign(
            make_request, label="embed :8013",
            ramp=common.ramp_schedule(max_concurrency=args.max), hold_s=args.hold,
            full_ramp=True,
        )
    args.out.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, args.out / "embed_RESULTS.md")
    print(f"knee={result.knee}  → {args.out / 'embed_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
