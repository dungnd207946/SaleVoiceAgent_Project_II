"""Bản kịch bản riêng của workspace — bảng `kich_ban` (0976, spec 2026-10-06 đợt 2 §1–2).

Khoá lạc quan theo `version`: chưa có hàng thì client gửi 0 (INSERT), có hàng thì UPDATE … WHERE version = $2.
Không khớp ⇒ `DaDoi` (router trả 409); giao dịch vỡ theo nên không có gì được ghi."""

from __future__ import annotations

import json

import asyncpg

_COT = "nut, tu_template, role_dung, version, updated_at, updated_by"

_THEM = f"""
    INSERT INTO tenant_data.kich_ban (tenant_id, nut, tu_template, role_dung, version, updated_by)
    VALUES ($1, $2::jsonb, $3, COALESCE($4::text[], '{{customer}}'), 1, $5)
    ON CONFLICT (tenant_id) DO NOTHING
    RETURNING {_COT}
"""

# `nut IS NULL` trong SET đọc giá trị CŨ: lưu lần đầu (chưa áp dụng) thì nhận templateVersion hiện tại.
_SUA = f"""
    UPDATE tenant_data.kich_ban
       SET nut = CASE WHEN $3 THEN $4::jsonb ELSE nut END,
           tu_template = CASE WHEN $3 AND ($5 OR nut IS NULL) THEN $6 ELSE tu_template END,
           role_dung = COALESCE($7::text[], role_dung),
           version = version + 1, updated_at = now(), updated_by = $8
     WHERE tenant_id = $1 AND tenant_id = portal.current_tenant() AND version = $2
    RETURNING {_COT}
"""


class DaDoi(Exception):
    """`version` client gửi ≠ DB."""


async def doc(conn: asyncpg.Connection) -> asyncpg.Record | None:
    return await conn.fetchrow(f"SELECT {_COT} FROM tenant_data.kich_ban WHERE tenant_id = portal.current_tenant()")


async def role_co(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT key FROM tenant_data.role_config WHERE tenant_id = portal.current_tenant()")
    return {r["key"] for r in rows}


async def ghi(
    conn: asyncpg.Connection,
    tenant_id: str,
    *,
    version: int,
    actor: str,
    nut: list[dict] | None = None,
    tu_template: str | None = None,
    ghi_de_template: bool = False,
    role_dung: list[str] | None = None,
) -> asyncpg.Record:
    """`nut` None = giữ nguyên; `role_dung` None = giữ nguyên. `ghi_de_template` (áp dụng) ghi `tu_template` kể cả
    khi đã áp dụng; lưu thường chỉ ghi khi trước đó chưa áp dụng."""
    nut_json = json.dumps(nut, ensure_ascii=False) if nut is not None else None
    if version == 0:
        row = await conn.fetchrow(
            _THEM, tenant_id, nut_json, tu_template if nut is not None else None, role_dung, actor
        )
    else:
        row = await conn.fetchrow(
            _SUA, tenant_id, version, nut is not None, nut_json, ghi_de_template, tu_template, role_dung, actor
        )
    if row is None:
        raise DaDoi
    return row
