"""KB backfill CLI: Mongo nbx_* -> Postgres tenant_data.projects/units (tenant noble).

Usage:
  python -m kb_backfill [--mongo-uri ...] [--mongo-db ...] [--pg-dsn ...]
                        [--tenant noble] [--dry-run] [--limit N]
Defaults read the repo .env (MONGODB_URI / MONGODB_DATABASE / POSTGRES_ADMIN_DSN).
"""
from __future__ import annotations

import argparse
import asyncio
import os

from kb_backfill import mongo_source, pg_sink, transform


async def run(db, tenant: str, sink_conn=None, dry_run: bool = False, limit: int = 0) -> dict:
    stats = {"projects_migrated": 0, "units_migrated": 0, "projects_skipped_no_code": 0,
             "direction_unmapped": 0, "product_type_null": 0, "sale_status_fallback": 0,
             "unittype_string_fallback": 0}
    all_docs = mongo_source.read_all_projects(db)
    docs = [d for d in all_docs if transform.project_code_of(d)]
    stats["projects_skipped_no_code"] = len(all_docs) - len(docs)
    if limit:
        docs = docs[:limit]
    for doc in docs:
        code = transform.project_code_of(doc)
        ptype = (doc.get("type") or "")
        raw_units = mongo_source.read_units(db, str(doc.get("_id")))
        unit_rows = [transform.unit_row(u, code, ptype, stats) for u in raw_units]
        proj = transform.project_row(doc, unit_rows)
        if not dry_run:
            async with sink_conn.transaction():
                await pg_sink.upsert_project(sink_conn, tenant, proj)
                await pg_sink.replace_units(sink_conn, tenant, code, unit_rows)
        stats["projects_migrated"] += 1
        stats["units_migrated"] += len(unit_rows)
    return stats


def _load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv()  # repo-root .env


async def _amain(args) -> None:
    db = mongo_source.connect(args.mongo_uri, args.mongo_db)
    conn = None
    if not args.dry_run:
        conn = await pg_sink.connect(args.pg_dsn)
    try:
        stats = await run(db, args.tenant, sink_conn=conn, dry_run=args.dry_run, limit=args.limit)
    finally:
        if conn is not None:
            await conn.close()
    print("KB backfill stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


def main(argv=None) -> None:
    _load_env()
    p = argparse.ArgumentParser(prog="kb_backfill")
    p.add_argument("--mongo-uri", default=os.environ.get("MONGODB_URI", ""))
    p.add_argument("--mongo-db", default=os.environ.get("MONGODB_DATABASE", "noble_agent"))
    p.add_argument("--pg-dsn", default=os.environ.get("POSTGRES_ADMIN_DSN", ""))
    p.add_argument("--tenant", default="noble")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
