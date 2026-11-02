"""Build FlatStore artifacts from data/faq/*.md.

The production FlatStore expects LightRAG-style chunks at
`data/rag/lightrag_s02_<key>/<key>/kv_store_text_chunks.json`, where the
chunks are normally exported from the santa-chat-agent repo. When that
repo isn't checked out (e.g. on a developer laptop or a fresh clone), we
can substitute by slicing the per-project FAQ Markdown directly into the
same JSON shape — this lets `noble_search` return real hits at runtime
without changing FlatStore or noble_kb.

Usage:
    python scripts/build_faq_flatstore.py            # write chunks + encode
    python scripts/build_faq_flatstore.py --dry-run  # only show chunk plan
    python scripts/build_faq_flatstore.py --force    # overwrite existing JSON

After this script succeeds you can leave `NOBLE_RAG_BACKEND=flat_store`
(default). To A/B compare against the substring-grep path used at SFT
synthesis time, set `NOBLE_RAG_BACKEND=grep_faq`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

# Map from FlatStore's expected dir key → canonical project code.
# Mirrors PROJECT_MAP in src/noble_agent/agent/rag/flat_store.py.
PROJECT_MAP: dict[str, str] = {
    "crystal_tay_ho": "NCTH",
    "noble_crystal_long_bien": "NCLB",
    "noble_palace_long_bien": "NPLB",
    "noble_palace_tay_thang_long": "NPTTL",
    "noble_sunshine_legend_city": "SLC",
    "noble_crystal_riverside": "NCR",
    "noble_palace_tay_ho": "NPTH",
    "sunshine_sky_city": "SSC",
    "sunshine_golden_river": "SGR",
    "sunshine_green_iconic": "SGI",
    "sunshine_river_park": "SRP",
    "sunshine_city_ha_noi": "SCHN",
    "sunshine_bay_retreat": "SBR",
    "alluvia_sunshine_marina": "ASM",
    "alumi": "ALM",
}

FAQ_DIR = _REPO_ROOT / "data" / "faq"
RAG_DIR = _REPO_ROOT / "data" / "rag"
MD_V2_DIR = _REPO_ROOT / "data" / "md_v2"

# code → source markdown path. All 15 projects are re-sourced from data/md_v2/
# (the existing 5 keep their dir-keys, so their data/rag/ dirs are reused; only
# the content is re-encoded). Absent from the map ⇒ fall back to data/faq/{code}.md.
SOURCE_OVERRIDE: dict[str, Path] = {
    "NCLB": MD_V2_DIR / "ABOUT_NobleCrystalLongBien.md",
    "NCTH": MD_V2_DIR / "ABOUT_NobleCrystalTayHo.md",
    "NCR": MD_V2_DIR / "ABOUT_NobleCrystalRiverside.md",
    "NPLB": MD_V2_DIR / "ABOUT_NoblePalaceLongBien.md",
    "NPTH": MD_V2_DIR / "ABOUT_NoblePalaceTayHo.md",
    "NPTTL": MD_V2_DIR / "ABOUT_NoblePalaceTayThangLong.md",
    "SLC": MD_V2_DIR / "ABOUT_SunshineLegendCity.md",
    "SSC": MD_V2_DIR / "ABOUT_SunshineSkyCity.md",
    "SGR": MD_V2_DIR / "ABOUT_SunshineGoldenRiver.md",
    "SGI": MD_V2_DIR / "ABOUT_SunshineGreenIconic.md",
    "SRP": MD_V2_DIR / "ABOUT_SunshineRiverPark.md",
    "SCHN": MD_V2_DIR / "ABOUT_SunshineCityHaNoi.md",
    "SBR": MD_V2_DIR / "ABOUT_SunshineBayRetreat.md",
    "ASM": MD_V2_DIR / "ABOUT_AlluviaSunshineMarina.md",
    "ALM": MD_V2_DIR / "ABOUT_Alumi.md",
}


def _slice_md(text: str, source_doc: str) -> list[dict]:
    """Split a Markdown file into chunks at each '## ' heading.

    Each chunk's `content` is `<heading>\n\n<body>`. Pre-heading preamble
    (everything before the first '##') becomes one extra chunk so the title
    / intro paragraph isn't lost.

    `tokens` is approximated by `len(content.split())` — FlatStore only uses
    this field for analytics, retrieval relies on the encoded vector + BM25.
    """
    # Strip CRLF
    text = text.replace("\r\n", "\n")

    # Split keeping headings as separators
    parts = re.split(r"(?m)^(##\s+.*)$", text)
    # `re.split` with a capturing group yields: [preamble, head1, body1, head2, body2, ...]
    chunks: list[dict] = []

    preamble = parts[0].strip()
    if preamble:
        chunks.append({"heading": "", "body": preamble})

    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        chunks.append({"heading": heading, "body": body})

    out: list[dict] = []
    for idx, ch in enumerate(chunks):
        if ch["heading"]:
            content = f"{ch['heading']}\n\n{ch['body']}".strip()
        else:
            content = ch["body"]
        if not content:
            continue
        out.append({
            "id": f"chunk-{source_doc}-{idx:03d}",
            "content": content,
            "tokens": len(content.split()),
            "chunk_order_index": idx,
            "full_doc_id": source_doc,
        })
    return out


def _write_chunks(dir_key: str, code: str, chunks: list[dict], *, dry_run: bool, force: bool) -> Path:
    out_dir = RAG_DIR / f"lightrag_s02_{dir_key}" / dir_key
    out_path = out_dir / "kv_store_text_chunks.json"

    if out_path.exists() and not force:
        print(f"  skip {out_path.relative_to(_REPO_ROOT)} (exists; --force to overwrite)")
        return out_path

    payload = {c["id"]: {k: v for k, v in c.items() if k != "id"} for c in chunks}

    if dry_run:
        return out_path

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _build_all_projects(*, dry_run: bool, force: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dir_key, code in PROJECT_MAP.items():
        md = SOURCE_OVERRIDE.get(code, FAQ_DIR / f"{code}.md")
        if not md.is_file():
            print(f"  WARN no FAQ markdown for {code} at {md.relative_to(_REPO_ROOT)} — skipping")
            counts[code] = 0
            continue
        text = md.read_text(encoding="utf-8")
        chunks = _slice_md(text, source_doc=f"{code}_FAQ")
        path = _write_chunks(dir_key, code, chunks, dry_run=dry_run, force=force)
        action = "would write" if dry_run else "wrote"
        print(f"  {action} {path.relative_to(_REPO_ROOT)} ({len(chunks)} chunks)")
        counts[code] = len(chunks)
    return counts


def _encode_and_bm25() -> None:
    """Load FlatStore so it encodes embeddings + builds BM25 index, then
    caches both to disk. Subsequent boots are warm — load takes ~1s."""
    from noble_agent.agent.rag.flat_store import FlatStore

    # skip_faq=False so FAQ chunks (the only thing we have) aren't filtered.
    store = FlatStore(skip_faq=False)
    print("[encode] loading + encoding chunks (first run may take ~30-60s)…")
    store.load()
    print(f"[encode] loaded {len(store.chunks)} chunks. building BM25…")
    if hasattr(store, "build_bm25"):
        store.build_bm25()
    elif hasattr(store, "load_bm25"):
        store.load_bm25()  # builds on first call when no cache exists
    print("[encode] done. cache written under data/flat_store/")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be written without writing")
    p.add_argument("--force", action="store_true",
                   help="overwrite existing chunk JSON files")
    p.add_argument("--skip-encode", action="store_true",
                   help="write JSON only; skip the FlatStore encode + BM25 build")
    args = p.parse_args()

    if not FAQ_DIR.is_dir():
        print(f"ERROR: {FAQ_DIR} does not exist", file=sys.stderr)
        return 2

    print(f"[build] FAQ source: {FAQ_DIR.relative_to(_REPO_ROOT)}")
    print(f"[build] RAG target: {RAG_DIR.relative_to(_REPO_ROOT)}")
    counts = _build_all_projects(dry_run=args.dry_run, force=args.force)

    total = sum(counts.values())
    if total == 0:
        print("ERROR: no chunks produced — check data/faq/*.md", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"[build] DRY RUN — {total} chunks across {sum(1 for v in counts.values() if v)} projects")
        return 0

    if args.skip_encode:
        print(f"[build] wrote {total} chunks; --skip-encode set, skipping FlatStore encode")
        return 0

    _encode_and_bm25()
    print(f"[build] OK — {total} chunks ready. NOBLE_RAG_BACKEND=flat_store will use them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
