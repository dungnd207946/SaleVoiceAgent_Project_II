"""noble-tenant CLI — provision tenant bundles into the store (slice #1)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.validation import validate_bundle


def _read_dir_bundle(dirpath: str) -> tuple[str, dict[str, str], str]:
    """Return (manifest_text, files, tenant_id_from_manifest_or_empty)."""
    root = Path(dirpath)
    manifest_text = (root / "manifest.toml").read_text(encoding="utf-8")
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in ("manifest.toml", "_meta.json") or rel.endswith(".pyc") or "__pycache__" in rel:
            continue
        files[rel] = path.read_text(encoding="utf-8")
    import tomllib

    tid = str(tomllib.loads(manifest_text).get("tenant_id", ""))
    return manifest_text, files, tid


def _get_store(injected):
    if injected is not None:
        return injected
    from noble_agent.config import get_settings
    from noble_agent.tenant.store import MinioTenantStore

    return MinioTenantStore.from_settings(get_settings())


def main(argv: list[str] | None = None, *, store=None) -> int:
    parser = argparse.ArgumentParser(prog="noble-tenant")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--dir", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("tenant_id")
    p_create.add_argument("--dir", required=True)
    p_create.add_argument("--status", default="draft", choices=["draft", "active", "disabled"])

    p_update = sub.add_parser("update")
    p_update.add_argument("tenant_id")
    p_update.add_argument("--dir", required=True)

    p_show = sub.add_parser("show")
    p_show.add_argument("tenant_id")

    p_list = sub.add_parser("list")



    p_ct = sub.add_parser("create-tenant")
    p_ct.add_argument("--name", required=True)
    p_ct.add_argument("--dir", required=True)
    p_ct.add_argument("--status", default="draft", choices=["draft", "active", "disabled"])


    p_act = sub.add_parser("activate")
    p_act.add_argument("tenant_id")

    p_dis = sub.add_parser("disable")
    p_dis.add_argument("tenant_id")

    p_imp = sub.add_parser("import-from-package")
    p_imp.add_argument("tenant_id")

    p_issue = sub.add_parser("issue-cred")
    p_issue.add_argument("tenant_id")

    p_revoke = sub.add_parser("revoke-cred")
    p_revoke.add_argument("tenant_id")
    p_revoke.add_argument("key_id")

    p_lc = sub.add_parser("list-creds")
    p_lc.add_argument("tenant_id")

    p_sd = sub.add_parser("save-draft")
    p_sd.add_argument("tenant_id")
    p_sd.add_argument("dir")

    p_pub = sub.add_parser("publish")
    p_pub.add_argument("tenant_id")
    p_pub.add_argument("--by", default="")

    p_rb = sub.add_parser("rollback")
    p_rb.add_argument("tenant_id")
    p_rb.add_argument("version", type=int)
    p_rb.add_argument("--by", default="")

    p_lv = sub.add_parser("list-versions")
    p_lv.add_argument("tenant_id")

    p_diff = sub.add_parser("diff")
    p_diff.add_argument("tenant_id")
    p_diff.add_argument("a", nargs="?", type=int, default=None)
    p_diff.add_argument("b", nargs="?", type=int, default=None)

    # SP-E1 Postgres data plane (agent owns DDL + roles, N9).
    p_pgs = sub.add_parser("pg-apply-schema")
    p_pgs.add_argument("--admin-dsn", default="")
    p_pgp = sub.add_parser("pg-provision")
    p_pgp.add_argument("tenant_id")
    p_pgp.add_argument("--password", default="")
    p_pgp.add_argument("--admin-dsn", default="")
    p_pgd = sub.add_parser("pg-deprovision")
    p_pgd.add_argument("tenant_id")
    p_pgd.add_argument("--admin-dsn", default="")
    p_pge = sub.add_parser("pg-ensure-app-role")
    p_pge.add_argument("--password", default="")
    p_pge.add_argument("--admin-dsn", default="")
    p_pgro = sub.add_parser("pg-ensure-sql-ro")
    p_pgro.add_argument("--admin-dsn", default="")

    args = parser.parse_args(argv)

    if args.cmd == "validate":
        manifest_text, files, tid = _read_dir_bundle(args.dir)
        report = validate_bundle(tid or "placeholder", manifest_text, files)
        for w in report.warnings:
            print(f"WARN: {w}")
        if report.ok:
            print("OK")
            return 0
        for e in report.errors:
            print(f"ERROR: {e}")
        return 1

    if args.cmd in ("pg-apply-schema", "pg-provision", "pg-deprovision", "pg-ensure-app-role", "pg-ensure-sql-ro"):
        import asyncio
        import secrets

        from noble_agent.config import get_settings
        from noble_agent.tenant import pg_provisioning as pg

        settings = get_settings()
        admin = args.admin_dsn or settings.postgres_admin_dsn
        if not admin:
            print("ERROR: no admin DSN (set POSTGRES_ADMIN_DSN or pass --admin-dsn)")
            return 1
        if args.cmd == "pg-apply-schema":
            asyncio.run(pg.apply_schema(admin))
            print("schema applied")
            return 0
        if args.cmd == "pg-provision":
            pw = args.password or secrets.token_urlsafe(24)
            role = pg.role_name(args.tenant_id)  # validate BEFORE connecting
            app_role = get_settings().postgres_app_role
            if args.tenant_id == app_role:
                print(
                    f"ERROR: tenant id {args.tenant_id!r} collides with the shared app role "
                    f"POSTGRES_APP_ROLE ({app_role!r}); a per-tenant role must not equal the app role "
                    f"(the tenant_isolation/current_user policy would match the app role's connections)."
                )
                return 1
            asyncio.run(pg.provision(admin, args.tenant_id, pw, sql_ro_role=settings.analyze_sql_role))
            print(f"provisioned role={role}")
            print(f"password={pw}")  # shown ONCE — put in the tenant deploy's POSTGRES_DSN
            return 0
        if args.cmd == "pg-ensure-app-role":
            role = settings.postgres_app_role
            pw = args.password or secrets.token_urlsafe(24)
            # Source existing tenant ids best-effort from the store to catch a
            # collision; degrade to [] if the store is unconfigured/unreachable
            # (the pg CLI must not hard-require MinIO).
            try:
                tenant_ids = [m.tenant_id for m in prov.list_tenants(_get_store(store))]
            except Exception:
                tenant_ids = []
                print(
                    "WARN: could not list tenants from the store; app-role/tenant collision "
                    "check limited to name-shape only (verify POSTGRES_APP_ROLE differs from every tenant_id)."
                )
            pg.assert_app_role_distinct(role, tenant_ids)
            asyncio.run(pg.ensure_app_role(admin, role=role, password=pw))
            print(f"ensured app role={role}")
            print(f"password={pw}")  # shown ONCE — put in POSTGRES_DSN
            return 0
        if args.cmd == "pg-ensure-sql-ro":
            sql_ro = settings.analyze_sql_role
            try:
                tenant_ids = [m.tenant_id for m in prov.list_tenants(_get_store(store))]
            except Exception:
                tenant_ids = []
                print("WARN: could not list tenants; sql_ro membership granted to app role only.")
            pg.assert_app_role_distinct(sql_ro, tenant_ids)  # tên không được trùng tenant_id
            pg.assert_app_role_distinct(pg.VIEW_OWNER_ROLE, tenant_ids)
            asyncio.run(
                pg.ensure_sql_ro_roles(
                    admin, sql_ro_role=sql_ro,
                    app_role=settings.postgres_app_role, tenant_roles=tuple(tenant_ids),
                )
            )
            print(f"ensured sql-ro role={sql_ro} owner={pg.VIEW_OWNER_ROLE}")
            return 0
        # pg-deprovision
        asyncio.run(pg.deprovision(admin, args.tenant_id))
        print(f"deprovisioned {args.tenant_id}")
        return 0

    st = _get_store(store)

    if args.cmd == "create":
        manifest_text, files, _ = _read_dir_bundle(args.dir)
        meta = prov.create_tenant(st, args.tenant_id, manifest_text, files, status=args.status)
        print(f"created {meta.tenant_id} v{meta.version} status={meta.status}")
        return 0
    if args.cmd == "update":
        manifest_text, files, _ = _read_dir_bundle(args.dir)
        meta = prov.update_tenant(st, args.tenant_id, manifest_text=manifest_text, files=files)
        print(f"updated {meta.tenant_id} v{meta.version}")
        return 0
    if args.cmd == "show":
        b = prov.get_tenant(st, args.tenant_id)
        print(f"{b.meta.tenant_id} v{b.meta.version} status={b.meta.status} files={sorted(b.files)}")
        return 0
    if args.cmd == "list":
        for m in prov.list_tenants(st):
            print(f"{m.tenant_id}\t{m.status}\tv{m.version}")
        return 0
    # Lệnh `create-org` / `list-orgs` / `migrate-org-layout` XOÁ 2026-08-15 cùng
    # khái niệm org (xem `identity.py`).
    if args.cmd == "create-tenant":
        manifest_text, files, _ = _read_dir_bundle(args.dir)
        tid, meta = prov.provision_tenant(
            st, name=args.name, manifest_text=manifest_text, files=files, status=args.status
        )
        print(f"created {tid} v{meta.version} status={meta.status}")
        return 0
    if args.cmd == "activate":
        m = prov.set_status(st, args.tenant_id, "active")
        print(f"{m.tenant_id} status={m.status}")
        return 0
    if args.cmd == "disable":
        m = prov.disable_tenant(st, args.tenant_id)
        print(f"{m.tenant_id} status={m.status}")
        return 0
    if args.cmd == "import-from-package":
        m = prov.import_from_package(st, args.tenant_id)
        print(f"imported {m.tenant_id} status={m.status}")
        return 0
    if args.cmd == "issue-cred":
        plaintext = prov.issue_credential(st, args.tenant_id)
        print(plaintext)
        return 0
    if args.cmd == "revoke-cred":
        prov.revoke_credential(st, args.tenant_id, args.key_id)
        print(f"revoked {args.key_id}")
        return 0
    if args.cmd == "list-creds":
        for m in prov.list_credentials(st, args.tenant_id):
            print(f"{m['key_id']}\t{m['created_at']}\t{'revoked' if m['revoked_at'] else 'active'}")
        return 0
    if args.cmd == "save-draft":
        manifest_text, files, _ = _read_dir_bundle(args.dir)
        prov.save_draft(st, args.tenant_id, manifest_text=manifest_text, files=files)
        print(f"saved draft for {args.tenant_id}")
        return 0
    if args.cmd == "publish":
        info = prov.publish(st, args.tenant_id, created_by=args.by)
        print(f"published {args.tenant_id} v{info.version}")
        return 0
    if args.cmd == "rollback":
        v = prov.rollback(st, args.tenant_id, args.version, updated_by=args.by)
        print(f"rolled back {args.tenant_id} -> v{v}")
        return 0
    if args.cmd == "list-versions":
        ptr = st.read_pointer(args.tenant_id)
        for v in prov.list_versions(st, args.tenant_id):
            print(f"{v}{' (published)' if v == ptr else ''}")
        return 0
    if args.cmd == "diff":
        a = args.a if args.a is not None else st.read_pointer(args.tenant_id)
        b = args.b  # None -> compare published vs draft
        d = prov.diff_versions(st, args.tenant_id, a, b)
        for kind in ("added", "removed", "changed"):
            for path in d[kind]:
                print(f"{kind}: {path}")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
