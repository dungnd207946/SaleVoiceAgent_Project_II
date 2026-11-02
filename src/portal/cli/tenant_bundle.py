"""Copy one tenant's catalog (DB rows + stored files) between environments.

    python -m portal.cli.tenant_bundle export --tenant aina_test --out /tmp/aina
    python -m portal.cli.tenant_bundle import --dir /tmp/aina --tenant aina_demo --name "AINA demo" \
        --owner a@b.vn [--replace] [--no-index]
    python -m portal.cli.tenant_bundle import --dir /tmp/aina --tenant aina_demo --into-existing [--no-index]

Customer data (conversations, contacts, leads, feedback) and ingest state are never exported.
The vector store is rebuilt on the target by the queued sync jobs, not copied.
"""

import argparse
import asyncio
import json
import mimetypes
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from portal.core.jobs import enqueue
from portal.core.public_url import public_url_of
from portal.core.storage import KhoTep, kho_tep_tu_cai_dat, tien_to_tenant
from portal.modules.kb.contracts import KIND_KB_FILE_INDEX, KIND_SYNC_PROJECT, MODE_FULL
from portal.modules.kb.ops.enqueue import dat_viec_provision
from portal.modules.realestate import repo as realestate_repo
from portal.modules.workspace import repo as ws_repo
from portal.modules.workspace import service as ws_service

# Insert order follows the foreign keys.
TABLES = (
    "role_config",
    "agent_config",
    "kich_ban",
    "projects",
    "zones",
    "buildings",
    "units",
    "media",
    "documents",
    "kb_files",
    "kbweb_sources",
    "kbweb_topics",
    "kbweb_schedules",
    "kbweb_limits",
    "kbweb_hidden_items",
    "kbweb_page_exclusions",
    "web_pages",
)
MEDIA_REFS = ("cover_media_id", "map_media_id", "layout_media_id")
# Config bundles from before migration 0966; nothing reads them.
LEGACY_PREFIXES = ("bundles/", "LIVE")
ACTOR = "tenant_bundle"


class BundleError(Exception):
    pass


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"tenant_data.{table}")


async def export_bundle(pool: asyncpg.Pool, store: KhoTep, tenant: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "tables").mkdir(exist_ok=True)
    counts: dict[str, int] = {}
    async with tenant_conn(pool, tenant) as conn:
        await conn.execute("SET TRANSACTION READ ONLY")
        for table in TABLES:
            if not await _table_exists(conn, table):
                continue
            rows = await conn.fetch(
                f"SELECT to_jsonb(x)::text AS j FROM tenant_data.{table} x WHERE x.tenant_id = portal.current_tenant()"
            )
            (out / "tables" / f"{table}.jsonl").write_text("".join(r["j"] + "\n" for r in rows), encoding="utf-8")
            counts[table] = len(rows)

    prefix = tien_to_tenant(tenant)
    keys = [k for k in await store.liet_ke(prefix) if not k.removeprefix(prefix).startswith(LEGACY_PREFIXES)]
    for key in keys:
        dest = out / "files" / key.removeprefix(prefix)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await store.doc(key))

    manifest = {
        "tenant": tenant,
        "exported_at": datetime.now(UTC).isoformat(),
        "tables": counts,
        "files": len(keys),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


async def _columns(conn: asyncpg.Connection, table: str) -> tuple[set[str], bool]:
    rows = await conn.fetch(
        """SELECT column_name, column_default, is_identity, is_generated
             FROM information_schema.columns
            WHERE table_schema = 'tenant_data' AND table_name = $1""",
        table,
    )
    cols = {r["column_name"] for r in rows if r["is_generated"] != "ALWAYS"}
    serial_id = any(
        r["column_name"] == "id" and (r["is_identity"] == "YES" or str(r["column_default"] or "").startswith("nextval"))
        for r in rows
    )
    return cols, serial_id


def _read_rows(src: Path, table: str, old_tenant: str, new_tenant: str) -> list[dict]:
    path = src / "tables" / f"{table}.jsonl"
    if not path.exists():
        return []
    old, new = tien_to_tenant(old_tenant), tien_to_tenant(new_tenant)
    return [json.loads(line.replace(old, new)) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _prepare(table: str, row: dict, tenant: str) -> dict:
    row["tenant_id"] = tenant
    if "external_id" in row:
        row["external_id"] = None
    # Bundle xuất trước migration 0978: tiêu chuẩn bàn giao còn là chữ.
    if table == "projects" and isinstance(row.get("handover_standard"), str):
        chu = row["handover_standard"].strip()
        row["handover_standard"] = [{"item": "Tiêu chuẩn chung", "note": chu}] if chu else None
    if table == "media":
        row["public_url"] = public_url_of(row.get("media_url") or "")
        row["public_thumb_url"] = public_url_of(row.get("thumb_url") or "")
    if table == "documents" and "public_thumb_url" in row:
        row["public_thumb_url"] = public_url_of(row.get("thumb_url") or "")
    if table == "kb_files":
        row["uploaded_by"] = None
    return row


async def _insert(conn: asyncpg.Connection, table: str, row: dict, cols: set[str], returning: bool) -> int | None:
    names = [c for c in row if c in cols]
    col_list = ", ".join(names)
    sql = (
        f"INSERT INTO tenant_data.{table} ({col_list}) "
        f"SELECT {col_list} FROM jsonb_populate_record(NULL::tenant_data.{table}, $1::jsonb)"
    )
    if table == "role_config":
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in names if c not in ("tenant_id", "key"))
        sql += f" ON CONFLICT (tenant_id, key) DO UPDATE SET {updates}"
    if returning:
        return await conn.fetchval(sql + " RETURNING id", json.dumps(row))
    await conn.execute(sql, json.dumps(row))
    return None


async def _drop_tenant(pool: asyncpg.Pool, tenant: str) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await ws_repo.xoa_han(conn, tenant)
    await ws_service.don_ha_tang_ngoai(pool, tenant)


async def _create_tenant(pool: asyncpg.Pool, tenant: str, name: str, owner_email: str) -> None:
    async with pool.acquire() as conn, conn.transaction():
        owner = await conn.fetchval("SELECT id FROM control.users WHERE lower(email) = lower($1)", owner_email)
        if owner is None:
            raise BundleError(f"no user with email {owner_email!r} on this environment")
        await ws_repo.them_tenant(conn, tenant, name, owner)
        await ws_repo.them_vertical(conn, tenant, ws_service.VERTICAL_MAC_DINH)
        await ws_repo.them_membership(conn, owner, tenant, await ws_repo.id_vai_tro_quan_tri(conn))


async def import_bundle(
    pool: asyncpg.Pool,
    store: KhoTep,
    src: Path,
    tenant: str,
    name: str,
    owner_email: str,
    *,
    replace: bool = False,
    into_existing: bool = False,
    index: bool = True,
) -> dict:
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    old_tenant = manifest["tenant"]

    async with pool.acquire() as conn:
        exists = await ws_repo.id_da_dung(conn, tenant)
    # Workspace tạo sẵn trên UI giữ nguyên mã, tên, thành viên và khoá; chỉ dữ liệu danh mục bị thay.
    if into_existing:
        if not exists:
            raise BundleError(f"tenant {tenant!r} does not exist — create the workspace in the UI first")
    else:
        if exists:
            if not replace:
                raise BundleError(
                    f"tenant {tenant!r} already exists — pass --replace to rebuild it or --into-existing to fill it"
                )
            await _drop_tenant(pool, tenant)
        await _create_tenant(pool, tenant, name, owner_email)

    files_dir = src / "files"
    uploaded = 0
    if files_dir.exists():
        prefix = tien_to_tenant(tenant)
        for path in sorted(p for p in files_dir.rglob("*") if p.is_file()):
            key = prefix + path.relative_to(files_dir).as_posix()
            await store.ghi(key, path.read_bytes(), content_type=mimetypes.guess_type(path.name)[0])
            uploaded += 1

    counts: dict[str, int] = {}
    async with tenant_conn(pool, tenant) as conn:
        media_ids: dict[int, int] = {}
        pending_refs: list[tuple[str, int, dict]] = []
        for table in TABLES:
            if table not in manifest["tables"] or not await _table_exists(conn, table):
                continue
            cols, serial_id = await _columns(conn, table)
            if table != "role_config":
                await conn.execute(f"DELETE FROM tenant_data.{table} WHERE tenant_id = portal.current_tenant()")
            n = 0
            for row in _read_rows(src, table, old_tenant, tenant):
                row = _prepare(table, row, tenant)
                old_id = row.pop("id", None) if serial_id else None
                refs = {k: row.pop(k) for k in MEDIA_REFS if row.get(k) is not None}
                new_id = await _insert(conn, table, row, cols, returning=serial_id)
                if table == "media" and old_id is not None:
                    media_ids[int(old_id)] = new_id
                if refs:
                    pending_refs.append((table, new_id, refs))
                n += 1
            counts[table] = n

        for table, row_id, refs in pending_refs:
            mapped = {k: media_ids.get(int(v)) for k, v in refs.items()}
            sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(mapped))
            await conn.execute(f"UPDATE tenant_data.{table} SET {sets} WHERE id = $1", row_id, *mapped.values())

        projects = await conn.fetch(
            "SELECT id, project_code, name, status FROM tenant_data.projects WHERE tenant_id = portal.current_tenant()"
        )
        for p in projects:
            await realestate_repo.dong_bo_hot_word(conn, tenant, int(p["id"]), str(p["name"]))

        if index:
            await dat_viec_provision(conn, tenant_id=tenant, actor=ACTOR)
            for p in projects:
                if p["status"] != "published" or p["project_code"] == "__ALL__":
                    continue
                await enqueue(
                    conn,
                    tenant_id=tenant,
                    kind=KIND_SYNC_PROJECT,
                    actor=ACTOR,
                    payload={
                        "vertical": "real_estate",
                        "project_code": p["project_code"],
                        "actor": ACTOR,
                        "mode": MODE_FULL,
                    },
                )
            # Tài liệu tra cứu chung không thuộc dự án nào nên việc nạp dự án không chạm tới.
            for f in await conn.fetch("SELECT id FROM tenant_data.kb_files WHERE tenant_id = portal.current_tenant()"):
                await enqueue(
                    conn, tenant_id=tenant, kind=KIND_KB_FILE_INDEX, actor=ACTOR, payload={"record_id": int(f["id"])}
                )

    return {"tenant": tenant, "source": old_tenant, "tables": counts, "files": uploaded}


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m portal.cli.tenant_bundle")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--tenant", required=True)
    ex.add_argument("--out", required=True, type=Path)
    im = sub.add_parser("import")
    im.add_argument("--dir", required=True, type=Path)
    im.add_argument("--tenant", required=True)
    im.add_argument("--name", help="workspace name (not used with --into-existing)")
    im.add_argument("--owner", help="email of an existing user who becomes the workspace admin")
    mode = im.add_mutually_exclusive_group()
    mode.add_argument("--replace", action="store_true", help="delete the target tenant first if it exists")
    mode.add_argument(
        "--into-existing",
        action="store_true",
        help="fill a workspace created in the UI; keep its id, name, members and keys",
    )
    im.add_argument("--no-index", action="store_true", help="do not queue knowledge-base sync jobs")
    return ap


async def _main(args: argparse.Namespace) -> dict:
    pool = await create_pool(get_settings().database_url, min_size=1, max_size=2)
    store = kho_tep_tu_cai_dat()
    try:
        if args.cmd == "export":
            return await export_bundle(pool, store, args.tenant, args.out)
        return await import_bundle(
            pool,
            store,
            args.dir,
            args.tenant,
            args.name,
            args.owner,
            replace=args.replace,
            into_existing=args.into_existing,
            index=not args.no_index,
        )
    finally:
        await pool.close()


def main() -> None:
    ap = _parser()
    args = ap.parse_args()
    if args.cmd == "import" and not args.into_existing and not (args.name and args.owner):
        ap.error("import needs --name and --owner unless --into-existing is given")
    try:
        result = asyncio.run(_main(args))
    except BundleError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
