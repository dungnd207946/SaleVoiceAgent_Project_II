"""HOTFIX — đẩy link tour 360 của từng dự án vào Qdrant `<tenant>_documents`.

`link_360` đã có trong `tenant_data.projects` và ra được qua `get_project_overview`,
nhưng `kb_search` chỉ đọc Qdrant nên khách hỏi "có tham quan ảo không" thì không có
context. Script này ghi thêm 1 point/dự án mang câu trả lời đó.

Đây là hotfix, cố ý gói gọn trong MỘT file, không đụng gì trong `src/`. Gỡ đi:

    python scripts/ingest_link360.py --all-tenants --delete   # dọn point trong Qdrant
    rm scripts/ingest_link360.py

Point do script này ghi mang `doc_type="tour_360"` — không trùng doc_type nào của
ingest chính, nên `--delete` không thể chạm vào dữ liệu của họ.

Embed đi qua `noble_agent.data.embed_client`, đúng seam mà `kb_search` gọi lúc query.
Không tự viết embed: model ingest lệch model query thì Qdrant trả rác mà KHÔNG báo
lỗi (đo được: E5-query trên collection E5 ~0.82, Gemini-query trên cùng collection
~0.03).

Cần: Postgres đọc được + `QDRANT_URL` với tới được (ngoài VPC thì mở
`scripts/qdrant_tunnel.sh` trước) + embed service sống nếu `EMBED_BACKEND=service`.

Usage:
    python scripts/ingest_link360.py --tenant noble-homes_k3n7_retail --dry-run
    python scripts/ingest_link360.py --tenant noble-homes_k3n7_retail --project VRI
    python scripts/ingest_link360.py --all-tenants
    python scripts/ingest_link360.py --all-tenants --delete
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
import uuid
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

from noble_agent.data import embed_client, qdrant_search  # noqa: E402

# Named vectors trên `<tenant>_documents` — đọc từ collection thật, khớp
# kb_service_adapter.
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "bm25"

# doc_type riêng: vừa là nhãn, vừa là tay cầm để `--delete` xoá đúng point của
# script này.
DOC_TYPE = "tour_360"
SECTION = "Tour 360"

# Namespace cố định để point id tất định → chạy lại là ghi đè, không nhân bản.
_NS = uuid.NAMESPACE_URL

_SQL_ROWS = """
SELECT project_code, name, link_360
FROM tenant_data.projects
WHERE tenant_id = $1
  AND status = 'published'
  AND link_360 IS NOT NULL
  AND btrim(link_360) <> ''
ORDER BY project_code
"""

_SQL_TENANTS = """
SELECT DISTINCT tenant_id
FROM tenant_data.projects
WHERE status = 'published' AND link_360 IS NOT NULL AND btrim(link_360) <> ''
ORDER BY tenant_id
"""


def build_text(name: str, link: str) -> str:
    """Chunk mà LLM sẽ đọc.

    Mở đầu bằng tên dự án theo đúng quy ước chunk của ingest chính (giúp BM25 khớp
    tên dự án). URL nằm THẲNG trong text chứ không phải payload field riêng, vì
    `_format_kb_hits` chỉ render text/project_name/section/updated_at — URL để ở
    payload thì LLM không nhìn thấy.
    """
    return (
        f"{name}\n\n"
        f"Tour tham quan thực tế ảo 360 độ\n\n"
        f"Dự án {name} có tour tham quan thực tế ảo 360 độ trực tuyến. "
        f"Khách hàng có thể xem trước toàn cảnh dự án, nhà mẫu và tiện ích "
        f"mà không cần tới tận nơi, qua đường link: {link}"
    )


def point_id(tenant: str, code: str) -> str:
    return str(uuid.uuid5(_NS, f"{tenant}:{code}:link_360"))


def build_payload(code: str, name: str, text: str) -> dict:
    """Khớp shape point thật của ingest chính, trừ `record_id` (id hàng nguồn bên
    Portal — không bịa ra để khỏi đụng id thật)."""
    return {
        "project_id": code,
        "project_name": name,
        "section": SECTION,
        "chunk_index": 0,
        "text": text,
        "content_hash": hashlib.sha1(text.encode("utf-8")).hexdigest(),
        "doc_type": DOC_TYPE,
        "updated_at": None,
        "source_file_url": None,
    }


async def fetch_rows(dsn: str, tenant: str, project: str = "") -> list[dict]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(_SQL_ROWS, tenant)
    finally:
        await conn.close()
    out = [{"code": r["project_code"], "name": r["name"], "link": r["link_360"].strip()} for r in rows]
    if project:
        out = [r for r in out if r["code"].upper() == project.upper()]
    return out


async def fetch_tenants(dsn: str) -> list[str]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(_SQL_TENANTS)
    finally:
        await conn.close()
    return [r["tenant_id"] for r in rows]


async def upsert(client, collection: str, tenant: str, rows: list[dict]) -> int:
    """Embed + upsert từng dự án. Một dự án lỗi thì log rồi đi tiếp — mất một
    chunk tốt hơn mất cả lượt chạy."""
    from qdrant_client import models

    done = 0
    for row in rows:
        text = build_text(row["name"], row["link"])
        try:
            dense, sparse = await asyncio.gather(
                embed_client.embed_dense([text], side="index"),
                embed_client.embed_sparse([text], side="index"),
            )
            await client.upsert(
                collection_name=collection,
                points=[
                    models.PointStruct(
                        id=point_id(tenant, row["code"]),
                        vector={
                            DENSE_VECTOR: dense[0],
                            SPARSE_VECTOR: models.SparseVector(
                                indices=sparse[0].get("indices", []),
                                values=sparse[0].get("values", []),
                            ),
                        },
                        payload=build_payload(row["code"], row["name"], text),
                    )
                ],
                wait=True,
            )
        except Exception as exc:  # noqa: BLE001 — mỗi dự án độc lập
            print(f"  ✗ {row['code']}: {type(exc).__name__}: {exc}")
            continue
        print(f"  ✓ {row['code']}  {row['link'][:60]}")
        done += 1
    return done


def _doc_type_cond(models):
    return models.FieldCondition(key="doc_type", match=models.MatchValue(value=DOC_TYPE))


async def delete_points(client, collection: str) -> None:
    from qdrant_client import models

    await client.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(filter=models.Filter(must=[_doc_type_cond(models)])),
        wait=True,
    )


async def run_tenant(args, tenant: str) -> tuple[int, int]:
    """Trả (số dự án nguồn, số point đã ghi/xoá)."""
    collection = qdrant_search.collection_name(tenant, "documents")
    print(f"\n=== {tenant} → {collection}")

    qdrant_url = os.environ.get("QDRANT_URL", "").strip()
    api_key = os.environ.get("QDRANT_API_KEY", "").strip()
    if not qdrant_url:
        raise SystemExit("QDRANT_URL rỗng — không biết ghi vào đâu")

    if not await qdrant_search.collection_exists(qdrant_url, api_key, collection):
        # Cố ý KHÔNG tự tạo: schema (tên vector, dim, payload index) do ingest
        # chính định nghĩa, tạo sai là hỏng collection cho mọi document khác.
        raise SystemExit(f"collection {collection} không tồn tại — dừng, không tự tạo")

    client = qdrant_search._get_client(qdrant_url, api_key)

    if args.delete:
        if args.dry_run:
            print("  (dry-run) sẽ xoá mọi point doc_type=tour_360")
            return 0, 0
        await delete_points(client, collection)
        print("  đã xoá point doc_type=tour_360")
        return 0, 0

    rows = await fetch_rows(args.pg_dsn, tenant, args.project)
    if not rows:
        print("  không dự án nào có link_360 — bỏ qua")
        return 0, 0

    if args.dry_run:
        for row in rows:
            print(f"  ─ {row['code']}  id={point_id(tenant, row['code'])}")
            print("    " + build_text(row["name"], row["link"]).replace("\n", "\n    "))
        print(f"  (dry-run) sẽ ghi {len(rows)} point")
        return len(rows), 0

    done = await upsert(client, collection, tenant, rows)
    return len(rows), done


async def amain(args) -> None:
    if args.all_tenants:
        tenants = await fetch_tenants(args.pg_dsn)
        if not tenants:
            raise SystemExit("không tenant nào có dự án mang link_360")
    else:
        if not args.tenant:
            raise SystemExit("cần --tenant <id> hoặc --all-tenants")
        tenants = [args.tenant]

    total_src = total_done = 0
    try:
        for tenant in tenants:
            src, done = await run_tenant(args, tenant)
            total_src += src
            total_done += done
    finally:
        await qdrant_search.close_all()

    print(f"\nTổng: {total_done}/{total_src} point đã ghi trên {len(tenants)} tenant")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="ingest_link360")
    p.add_argument("--tenant", default="", help="tenant_id (vd noble-homes_k3n7_retail)")
    p.add_argument("--all-tenants", action="store_true", help="mọi tenant có dự án mang link_360")
    p.add_argument("--project", default="", help="chỉ một project_code")
    p.add_argument("--pg-dsn", default=os.environ.get("POSTGRES_DSN", ""))
    p.add_argument("--dry-run", action="store_true", help="in ra, không embed, không ghi")
    p.add_argument("--delete", action="store_true", help="xoá point doc_type=tour_360")
    args = p.parse_args(argv)
    if not args.pg_dsn and not args.delete:
        raise SystemExit("cần --pg-dsn hoặc POSTGRES_DSN trong .env")
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
