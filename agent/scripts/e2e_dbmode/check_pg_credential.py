#!/usr/bin/env python3
"""Verify giai đoạn B của live test gateway runtime-credentials:

1. Gọi Portal runtime-credentials API bằng API key (mặc định lấy TOKEN trong
   chat_via_gateway.py, hoặc truyền --key).
2. Login Postgres bằng chính postgres_role/postgres_password API trả về
   (truyền user/password tách rời — không lắp DSN nên không dính lỗi quoting).
3. Đếm rows các bảng tenant_data.* và kiểm tra RLS: rows của tenant KHÁC phải = 0.

Usage:
  .venv/bin/python scripts/e2e_dbmode/check_pg_credential.py
  .venv/bin/python scripts/e2e_dbmode/check_pg_credential.py --key ody_ag_xxx \
      --api http://10.50.13.208:8100/api/v1/agent/runtime-credentials \
      --host 10.50.13.208 --port 5442 --db portal
"""
import argparse
import asyncio
import json
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_API = "http://10.50.13.208:8100/api/v1/agent/runtime-credentials"
TABLES = ("conversations", "conversation_messages", "appointments", "contacts", "projects")


def default_key() -> str:
    src = (Path(__file__).parent / "chat_via_gateway.py").read_text("utf-8")
    m = re.search(r'TOKEN = "([^"]+)"', src)
    if not m:
        sys.exit("Không tìm thấy TOKEN trong chat_via_gateway.py — truyền --key")
    return m.group(1)


def fetch_credentials(api: str, key: str) -> dict:
    req = urllib.request.Request(api, method="POST", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


async def check(cred: dict, host: str, port: int, db: str) -> None:
    import asyncpg

    tenant = cred["tenant_id"]
    print(f"tenant_id      : {tenant}")
    print(f"postgres_role  : {cred['postgres_role']}")
    print(f"expires_at     : {cred['expires_at']}")
    try:
        conn = await asyncpg.connect(
            host=host, port=port, database=db,
            user=cred["postgres_role"], password=cred["postgres_password"], timeout=10,
        )
    except Exception as exc:
        print(f"\n❌ LOGIN FAIL: {type(exc).__name__}: {exc}")
        print("→ Password API trả về không khớp role trên PG — việc của team Portal (ALTER ROLE ... PASSWORD).")
        sys.exit(1)
    print(f"\n✅ login OK, current_user = {await conn.fetchval('SELECT current_user')}")
    for t in TABLES:
        try:
            n = await conn.fetchval(f"SELECT count(*) FROM tenant_data.{t}")
            print(f"  tenant_data.{t:24s}: {n} rows visible")
        except Exception as exc:
            print(f"  tenant_data.{t:24s}: ❌ {type(exc).__name__}: {str(exc)[:90]}")
    try:
        leak = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.conversations WHERE tenant_id <> $1", tenant
        )
        verdict = "✅ RLS chặn đúng" if leak == 0 else "❌ LỘ DỮ LIỆU TENANT KHÁC"
        print(f"\nRows của tenant khác nhìn thấy được: {leak} → {verdict}")
    except Exception as exc:
        print(f"\nRLS leak-check lỗi: {exc}")
    await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=None, help="API key (mặc định: TOKEN trong chat_via_gateway.py)")
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--host", default="10.50.13.208")
    ap.add_argument("--port", type=int, default=5442)
    ap.add_argument("--db", default="portal")
    args = ap.parse_args()
    cred = fetch_credentials(args.api, args.key or default_key())
    asyncio.run(check(cred, args.host, args.port, args.db))


if __name__ == "__main__":
    main()
