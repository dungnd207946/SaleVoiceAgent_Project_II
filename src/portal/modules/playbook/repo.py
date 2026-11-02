"""Số đo tuân thủ kịch bản từ `conversation_messages.meta.playbook` (agent G1 ghi)."""

from __future__ import annotations

import json
from collections import Counter

import asyncpg

# Nhãn hợp lệ: meta.playbook là object có nut. So sánh bằng jsonb (= 'true'::jsonb) thay vì cast
# ::boolean để nhãn hỏng không ném lỗi cast giữa truy vấn.
_LUOT = """
    SELECT m.session_id, m.seq, m.created_at, m.content, m.meta->'playbook' AS p, c.source, c.phone
      FROM tenant_data.conversation_messages m
      LEFT JOIN tenant_data.conversations c
             ON c.tenant_id = m.tenant_id AND c.session_id = m.session_id
     WHERE m.tenant_id = portal.current_tenant()
       AND m.meta ? 'playbook'
       AND jsonb_typeof(m.meta->'playbook') = 'object'
       AND m.created_at >= now() - make_interval(days => $1)
       AND ($2::text IS NULL OR c.source = $2)
"""

# ponytail: không có chỉ mục theo created_at ⇒ quét mọi tin nhắn của tenant (không chỉ cửa sổ `ngay`), một lần.
# Nâng cấp khi chậm: chỉ mục riêng phần `(tenant_id, created_at) WHERE meta ? 'playbook'` (cần migration).
_NHAN = """
    SELECT m.meta->'playbook' AS p, c.source
      FROM tenant_data.conversation_messages m
      LEFT JOIN tenant_data.conversations c
             ON c.tenant_id = m.tenant_id AND c.session_id = m.session_id
     WHERE m.tenant_id = portal.current_tenant()
       AND m.meta ? 'playbook'
       AND jsonb_typeof(m.meta->'playbook') = 'object'
       AND m.created_at >= now() - make_interval(days => $1)
"""


def _top3(dem: dict[str, Counter]) -> dict[str, list[tuple[str, int]]]:
    return {n: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:3] for n, c in dem.items()}


def _cong(t: dict, p: dict) -> None:
    t["so_luot"] += 1
    if isinstance(p.get("dat"), bool) and "loi" not in p:
        t["da_cham"] += 1
        t["dat"] += p["dat"]
    t["thieu_du_lieu"] += p.get("thieu_du_lieu") is True
    if isinstance(p.get("jev_nut"), str):
        t["jev_so"] += 1
        t["jev_khop"] += p["jev_nut"] == p["nut"]


async def so_do(conn: asyncpg.Connection, *, ngay: int, nguon: str | None, v: str, hash_nut: dict[str, str]) -> dict:
    """Một lần quét cửa sổ ngày; `nguon` chỉ lọc số đo — danh sách nguồn và co_du_lieu tính trên cả cửa sổ.
    `hash_nut` = hash từng nút của bộ đang chạy; nhãn `h` lệch → `phien_ban_cu`."""
    theo_nut: dict[str, dict] = {}
    thieu: dict[str, Counter] = {}
    pham: dict[str, Counter] = {}
    nguon_co, cu, co_du_lieu = set(), 0, False
    for r in await conn.fetch(_NHAN, ngay):
        co_du_lieu = True
        if r["source"] is not None:
            nguon_co.add(r["source"])
        if nguon is not None and r["source"] != nguon:
            continue
        p = json.loads(r["p"]) if isinstance(r["p"], str) else r["p"]
        if p.get("v") != v:
            cu += 1
            continue
        if not isinstance(p.get("nut"), str):
            continue
        if p["nut"] in hash_nut and p.get("h") != hash_nut[p["nut"]]:
            cu += 1  # nút đã sửa (hoặc nhãn trước đợt 2): đếm lại từ đầu cho riêng nút đó
            continue
        t = theo_nut.setdefault(
            p["nut"], dict.fromkeys(("so_luot", "da_cham", "dat", "thieu_du_lieu", "jev_so", "jev_khop"), 0)
        )
        _cong(t, p)
        for truong, dem in (("thieu", thieu), ("vi_pham_cam", pham)):
            if isinstance(p.get(truong), list):
                dem.setdefault(p["nut"], Counter()).update(x for x in p[truong] if isinstance(x, str))
    return {
        "theo_nut": theo_nut,
        "hay_thieu": _top3(thieu),
        "hay_pham": _top3(pham),
        "phien_ban_cu": cu,
        "nguon": sorted(nguon_co),
        "co_du_lieu": co_du_lieu,
    }


async def luot_cua_nut(
    conn: asyncpg.Connection,
    *,
    nut: str,
    ngay: int,
    nguon: str | None,
    v: str,
    h: str,
    chi_khong_dat: bool,
    limit: int,
) -> list[asyncpg.Record]:
    return list(
        await conn.fetch(
            f"""
            WITH l AS ({_LUOT})
            SELECT l.session_id, l.seq, l.phone, l.created_at, l.content AS agent, l.p,
                   (SELECT u.content FROM tenant_data.conversation_messages u
                     WHERE u.tenant_id = portal.current_tenant() AND u.session_id = l.session_id
                       AND u.role = 'user' AND u.seq < l.seq
                     ORDER BY u.seq DESC LIMIT 1) AS khach
              FROM l
             WHERE p->>'v' = $3 AND p->>'nut' = $4 AND p->>'h' = $7
               AND (NOT $5 OR p->'dat' = 'false'::jsonb)
             ORDER BY l.created_at DESC, l.seq DESC
             LIMIT $6
            """,
            ngay,
            nguon,
            v,
            nut,
            chi_khong_dat,
            limit,
            h,
        )
    )
