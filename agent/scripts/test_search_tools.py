"""Live check of the two retrieval tools against the real embed service + Qdrant.

Calls the SAME functions the tools call — `kb_service_adapter` for `kb_search` and
`media_data.search_media` for `send_media` — so a pass here means the tools work, not
that a mock works.

Why this script exists: both tools **degrade silently** when the infra is unreachable
(`kb_search` → empty context, `send_media` → `no_media`). Nothing crashes, so in the
agent logs a dead tunnel or a missing SG rule looks exactly like "the KB has no data".
This script separates the two: it probes Qdrant first and tells you which it is.

Usage:
    python scripts/test_search_tools.py -i                 # type your own queries (see /help)
    python scripts/test_search_tools.py                    # auto-pick a tenant, run the smoke set
    python scripts/test_search_tools.py --list             # what tenants/collections exist
    python scripts/test_search_tools.py -t <tenant>        # pin the tenant
    python scripts/test_search_tools.py --kb "câu hỏi"     # one kb_search query
    python scripts/test_search_tools.py --media "hồ bơi" --category tien_ich
    python scripts/test_search_tools.py --project VRI      # scope to one project code

`-i` keeps ONE Qdrant connection for the whole session, so each query costs only an
embed + a search — that is the mode to use when exploring.

Needs QDRANT_URL reachable — see docs/handoff/qdrant-access.md (from outside the VPC
that means an SSM port-forward).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _load_dotenv() -> None:
    """Read .env the way the agent entrypoint does (config import alone doesn't)."""
    env = _ROOT / ".env"
    if not env.is_file():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.split(" #")[0].strip())


_load_dotenv()

from noble_agent.agent.rag import kb_service_adapter  # noqa: E402
from noble_agent.config import get_settings  # noqa: E402
from noble_agent.data import media_data, qdrant_search  # noqa: E402
from noble_agent.tenant.current import use_tenant  # noqa: E402

DEFAULT_KB_QUERIES = ["dự án có những tiện ích gì", "chủ đầu tư là ai"]
DEFAULT_MEDIA = [
    ("phối cảnh tổng thể dự án", "tong_quan", ""),
    ("tiện ích hồ bơi", "tien_ich", ""),
    ("video dự án", "", "video"),  # ca hồi quy: video nằm rải rác category
]

OK, BAD, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m!\033[0m"
BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def hr(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m\n{'─' * 74}")


async def _collections(base_url: str, api_key: str) -> list[str]:
    """Every collection on the Qdrant behind QDRANT_URL. Raises if unreachable."""
    client = qdrant_search._get_client(base_url, api_key)
    resp = await client.get_collections()
    return sorted(c.name for c in resp.collections)


def _tenants(names: list[str]) -> list[str]:
    """Tenants that have BOTH a _documents and a _media collection."""
    docs = {n[: -len("_documents")] for n in names if n.endswith("_documents")}
    media = {n[: -len("_media")] for n in names if n.endswith("_media")}
    return sorted(docs & media)


async def preflight(s) -> tuple[bool, list[str]]:
    """Report what is and isn't configured/reachable before running any tool."""
    hr("CONFIG")
    print(f"  QDRANT_URL         {s.qdrant_url or '(unset)'}")
    dense = f"{s.embed_backend}" + (f" ({s.embed_model})" if s.embed_model else "")
    print(f"  EMBED_BACKEND      {dense}  dim={s.embed_dim}")
    print(f"  EMBED_SPARSE_MODEL {s.embed_sparse_model}   {DIM}in-process{RESET}")
    print(f"  EMBED_SERVICE_URL  {s.embed_service_url or '(unset)'}   {DIM}visual only{RESET}")
    print(f"  NOBLE_RAG_BACKEND  {s.noble_rag_backend}"
          f"{'' if s.noble_rag_backend == 'kb_service' else f'  {WARN} kb_search chỉ dùng đường mới khi = kb_service'}")
    print(f"  SANTA_MODELS_TOKEN {'set' if os.environ.get('SANTA_MODELS_TOKEN', '').strip() else BAD + ' MISSING'}")
    print(f"  kb top_k / media top_k / threshold   {s.kb_search_top_k} / "
          f"{s.media_search_top_k} / {s.media_search_threshold}")

    if not s.qdrant_url:
        print(f"\n{BAD} QDRANT_URL chưa set → cả 2 tool sẽ trả rỗng.")
        return False, []
    if not s.embed_service_url:
        print(f"  {WARN} EMBED_SERVICE_URL chưa set → media tìm text-only (kb không ảnh hưởng)")

    hr("QDRANT")
    try:
        names = await _collections(s.qdrant_url, s.qdrant_api_key)
    except Exception as exc:
        print(f"  {BAD} không kết nối được {s.qdrant_url}\n     {type(exc).__name__}: {exc}")
        print("\n  Nếu đang ở ngoài VPC: tunnel chưa chạy. Xem docs/handoff/qdrant-access.md")
        return False, []
    tenants = _tenants(names)
    print(f"  {OK} kết nối được — {len(names)} collection, {len(tenants)} tenant hoàn chỉnh")
    for t in tenants:
        print(f"     • {t}")
    if not tenants:
        print(f"  {WARN} không tenant nào có đủ cặp _documents + _media")
    return True, tenants


async def run_kb(tenant: str, queries: list[str], project: str, top_k: int) -> int:
    hr(f"kb_search  ·  {tenant}_documents")
    empty = 0
    for q in queries:
        with use_tenant(tenant):
            out = await kb_service_adapter.query_kb_service_for_noble_kb(q, project, top_k=top_k)
        scope = f"project={project}" if project else "toàn tenant"
        if not out:
            empty += 1
            print(f"\n  {BAD} {q!r} ({scope}) → RỖNG")
            continue
        chunks = out.count("\n---\n") + 1
        print(f"\n  {OK} {q!r} ({scope}) → {chunks} đoạn, {len(out)} ký tự")
        for line in out.splitlines()[:6]:
            print(f"       {line[:96]}")
        if len(out.splitlines()) > 6:
            print("       …")
    return empty


async def run_media(tenant: str, cases: list[tuple[str, str, str]], project: str, s) -> int:
    hr(f"send_media  ·  {tenant}_media")
    empty = 0
    for query, category, content_type in cases:
        items = await media_data.search_media(
            query, project, category,
            tenant_id=tenant,
            qdrant_url=s.qdrant_url,
            qdrant_api_key=s.qdrant_api_key,
            content_type=content_type,
            top_k=s.media_search_top_k,
            threshold=s.media_search_threshold,
            qdrant_timeout=s.qdrant_timeout,
            cache_ttl=0.0,  # bypass the cache so each run really hits the backends
        )
        scope = f"project={project}, " if project else ""
        ct = f", content_type={content_type}" if content_type else ""
        mark = BAD if not items else OK
        print(f"\n  {mark} {query!r} ({scope}category={category or '-'}{ct}) → {len(items)} item")
        if not items:
            empty += 1
        for it in items:
            if it["kind"] == "image":
                print(f"       [image] {it['url'][:88]}")
                if it.get("label"):
                    print(f"               {it['label'].splitlines()[0][:80]!r}")
            else:
                print(f"       [video] youtube={it['video_id']}  {it['title'][:60]!r}")
    return empty


async def run_isolation(tenant: str, s) -> bool:
    """A tenant with no collection must return nothing — never another tenant's data."""
    hr("TENANT ISOLATION")
    bogus = "tenant-khong-ton-tai"
    with use_tenant(bogus):
        out = await kb_service_adapter.query_kb_service_for_noble_kb("tiện ích", "", top_k=3)
    items = await media_data.search_media(
        "hồ bơi", "", "tien_ich",
        tenant_id=bogus,
        qdrant_url=s.qdrant_url, qdrant_api_key=s.qdrant_api_key, cache_ttl=0.0,
    )
    kb_ok, media_ok = out == "", items == []
    print(f"  {OK if kb_ok else BAD} kb_search({bogus})  → {out[:40]!r}")
    print(f"  {OK if media_ok else BAD} send_media({bogus}) → {items}")
    return kb_ok and media_ok


_HELP = """
  <gõ câu hỏi>        chạy query ở mode hiện tại
  /kb                 chuyển sang mode kb_search
  /media [category]   chuyển sang mode send_media (mặc định giữ category đang dùng)
  /cat [category]     đổi category; không tham số = bỏ lọc (tong_quan ngoai_that...)
  /ct [image|video]   lọc theo content_type; không tham số = bỏ lọc
  /project [CODE]     giới hạn 1 mã dự án; không tham số = bỏ giới hạn
  /tenant [id]        đổi tenant; không tham số = liệt kê tenant có sẵn
  /topk <n>           đổi số kết quả kb_search
  /both <query>       chạy CẢ kb_search và send_media với cùng câu hỏi
  /help  /quit
"""


async def interactive(tenant: str, tenants: list[str], s) -> int:
    """Query loop — one Qdrant connection reused, so each query is just embed+search."""
    # category mặc định RỖNG = không lọc, khớp default của --category ở main() và khớp
    # ngữ nghĩa mới của tool (category là optional). Gõ /cat <loại> để lọc.
    mode, category, project, top_k = "kb", "", "", s.kb_search_top_k
    ctype = ""
    print(_HELP)

    def prompt() -> str:
        bits = [tenant.split("_")[0]]
        if project:
            bits.append(project)
        if mode == "media":
            bits.append(category or "-")
            if ctype:
                bits.append(ctype)
        return f"{BOLD}{mode}[{' '.join(bits)}]>{RESET} "

    while True:
        try:
            line = input(prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue

        if line.startswith("/"):
            cmd, _, rest = line[1:].partition(" ")
            cmd, rest = cmd.strip().lower(), rest.strip()
            if cmd in ("quit", "exit", "q"):
                return 0
            if cmd == "help":
                print(_HELP)
            elif cmd == "kb":
                mode = "kb"
            elif cmd == "media":
                mode = "media"
                if rest:
                    category = rest
            elif cmd == "cat":
                category = rest
                print(f"  category = {category or '(không lọc)'}")
            elif cmd == "ct":
                ctype = rest.strip().lower()
                print(f"  content_type = {ctype or '(cả hai)'}")
            elif cmd == "project":
                project = rest.upper()
                print(f"  project = {project or '(toàn tenant)'}")
            elif cmd == "topk":
                if rest.isdigit():
                    top_k = int(rest)
                print(f"  top_k = {top_k}")
            elif cmd == "tenant":
                if not rest:
                    print("  " + "\n  ".join(tenants))
                else:
                    tenant = rest
                    if tenants and tenant not in tenants:
                        print(f"  {WARN} {tenant!r} không có collection — kỳ vọng rỗng")
            elif cmd == "both":
                if rest:
                    await run_kb(tenant, [rest], project, top_k)
                    await run_media(tenant, [(rest, category, ctype)], project, s)
            else:
                print(f"  lệnh lạ: /{cmd} — /help để xem")
            continue

        if mode == "kb":
            await run_kb(tenant, [line], project, top_k)
        else:
            await run_media(tenant, [(line, category, ctype)], project, s)


async def main() -> int:
    p = argparse.ArgumentParser(description="Live check kb_search + send_media")
    p.add_argument("-i", "--interactive", action="store_true", help="gõ query của bạn, xem kết quả ngay")
    p.add_argument("--list", action="store_true", help="chỉ liệt kê tenant/collection rồi thoát")
    p.add_argument("-t", "--tenant", default="", help="tenant_id (mặc định: tenant đầu tiên tìm được)")
    p.add_argument("--kb", action="append", metavar="QUERY", help="câu hỏi kb_search (lặp được)")
    p.add_argument("--media", action="append", metavar="QUERY", help="câu hỏi send_media (lặp được)")
    p.add_argument("--category", default="", help="category cho --media (mặc định: không lọc)")
    p.add_argument("--content-type", default="", choices=["", "image", "video"], help="lọc image/video cho --media")
    p.add_argument("--project", default="", help="giới hạn 1 mã dự án, vd VRI")
    p.add_argument("--skip-isolation", action="store_true", help="bỏ bước kiểm tra tenant isolation")
    args = p.parse_args()

    s = get_settings()
    reachable, tenants = await preflight(s)
    if not reachable:
        return 2
    if args.list:
        return 0

    tenant = args.tenant or (tenants[0] if tenants else "")
    if not tenant:
        print(f"\n{BAD} không có tenant nào để test. Dùng -t <tenant> để chỉ định.")
        return 2
    if tenants and tenant not in tenants:
        print(f"\n{WARN} {tenant!r} không có trong danh sách trên — vẫn thử (kỳ vọng: rỗng).")

    if args.interactive:
        return await interactive(tenant, tenants, s)

    kb_queries = args.kb or DEFAULT_KB_QUERIES
    media_cases = (
        [(q, args.category, args.content_type) for q in args.media] if args.media else DEFAULT_MEDIA
    )

    empty_kb = await run_kb(tenant, kb_queries, args.project, s.kb_search_top_k)
    empty_media = await run_media(tenant, media_cases, args.project, s)
    isolated = True if args.skip_isolation else await run_isolation(tenant, s)

    hr("KẾT QUẢ")
    total = len(kb_queries) + len(media_cases)
    print(f"  tenant           {tenant}")
    print(f"  kb_search        {len(kb_queries) - empty_kb}/{len(kb_queries)} có kết quả")
    print(f"  send_media       {len(media_cases) - empty_media}/{len(media_cases)} có kết quả")
    if not args.skip_isolation:
        print(f"  isolation        {OK + ' fail-closed' if isolated else BAD + ' RÒ RỈ DỮ LIỆU'}")
    if not isolated:
        print(f"\n{BAD} tenant isolation vỡ — dừng lại điều tra ngay, đây là lỗi nghiêm trọng.")
        return 1
    if empty_kb + empty_media == total:
        print(f"\n{BAD} Qdrant kết nối được nhưng KHÔNG query nào ra kết quả.")
        print("   Kiểm tra: tenant đúng chưa · embed service còn sống không · collection có data không.")
        return 1
    if empty_kb or empty_media:
        print(f"\n{WARN} Một phần query trả rỗng — có thể đúng (không có data khớp), xem lại từng dòng trên.")
        return 0
    print(f"\n{OK} Cả hai tool hoạt động end-to-end.")
    return 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    finally:
        asyncio.run(qdrant_search.close_all())
    sys.exit(code)
