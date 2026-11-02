"""SQL của `tenant_data.nhan_vat` — nơi gọi giữ giao dịch (luôn trong `tenant_conn`).

Mọi câu mang vị từ `tenant_id = portal.current_tenant()` (cổng 7 — cách ly ở tầng app).
"""

import json
import uuid

import asyncpg

_COT = """id::text AS id, ten, nguon, trang_thai, buoc, tien_do, loi_ma, loi_chi_tiet, avatar_id, mo_ta,
          anh_key, video_key, video_tay_key, poster_key, tac_vu, xem_truoc, dang_dung, created_at"""


def _hang(r: asyncpg.Record | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["tac_vu"] = json.loads(d["tac_vu"]) if isinstance(d["tac_vu"], str) else d["tac_vu"]
    d["xem_truoc"] = json.loads(d["xem_truoc"]) if isinstance(d["xem_truoc"], str) else d["xem_truoc"]
    return d


async def liet_ke(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        f"SELECT {_COT} FROM tenant_data.nhan_vat WHERE tenant_id = portal.current_tenant() ORDER BY created_at"
    )
    return [_hang(r) for r in rows]


async def dem(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT count(*) FROM tenant_data.nhan_vat WHERE tenant_id = portal.current_tenant()")


async def doc(conn: asyncpg.Connection, id_: str, *, khoa: bool = False) -> dict | None:
    """Một hàng (của tenant hiện tại), hoặc None. `id_` không phải uuid ⇒ None."""
    try:
        uuid.UUID(id_)
    except ValueError:
        return None
    r = await conn.fetchrow(
        f"""SELECT {_COT} FROM tenant_data.nhan_vat
             WHERE tenant_id = portal.current_tenant() AND id = $1::uuid{" FOR UPDATE" if khoa else ""}""",
        id_,
    )
    return _hang(r)


async def doc_dang_dung(conn: asyncpg.Connection) -> dict | None:
    r = await conn.fetchrow(
        f"""SELECT {_COT} FROM tenant_data.nhan_vat
             WHERE tenant_id = portal.current_tenant() AND dang_dung"""
    )
    return _hang(r)


async def tao(
    conn: asyncpg.Connection,
    *,
    ten: str,
    nguon: str,
    trang_thai: str,
    avatar_id: str,
    mo_ta: str | None,
    anh_key: str | None,
    video_key: str | None,
    video_tay_key: str | None,
    tao_boi: str,
) -> str:
    return await conn.fetchval(
        """INSERT INTO tenant_data.nhan_vat
               (tenant_id, ten, nguon, trang_thai, avatar_id, mo_ta, anh_key, video_key, video_tay_key,
                dong_y_luc, tao_boi)
           VALUES (portal.current_tenant(), $1, $2, $3, $4, $5, $6, $7, $8, now(), $9)
           RETURNING id::text""",
        ten,
        nguon,
        trang_thai,
        avatar_id,
        mo_ta,
        anh_key,
        video_key,
        video_tay_key,
        tao_boi,
    )


_DUOC_SUA = frozenset(
    {
        "trang_thai",
        "buoc",
        "tien_do",
        "loi_ma",
        "loi_chi_tiet",
        "anh_key",
        "video_key",
        "video_tay_key",
        "poster_key",
        "tac_vu",
        "xem_truoc",
    }
)


async def cap_nhat(conn: asyncpg.Connection, id_: str, **cot) -> None:
    """Sửa các cột trạng thái. Tên cột lấy từ danh sách cho phép (không bao giờ từ input)."""
    if not cot:
        return
    la = set(cot) - _DUOC_SUA
    if la:
        raise ValueError(f"cột không được sửa: {sorted(la)}")
    ten = sorted(cot)
    gan = ", ".join(
        f"{c} = ${i + 2}::jsonb" if c in ("tac_vu", "xem_truoc") else f"{c} = ${i + 2}" for i, c in enumerate(ten)
    )
    gia_tri = [json.dumps(cot[c]) if c in ("tac_vu", "xem_truoc") else cot[c] for c in ten]
    await conn.execute(
        f"""UPDATE tenant_data.nhan_vat SET {gan}, updated_at = now()
             WHERE tenant_id = portal.current_tenant() AND id = $1::uuid""",
        id_,
        *gia_tri,
    )


async def chon(conn: asyncpg.Connection, id_: str | None) -> None:
    """Đặt nhân vật đang dùng (None = mặc định). Bỏ cờ cũ TRƯỚC — unique index một phần."""
    await conn.execute(
        """UPDATE tenant_data.nhan_vat SET dang_dung = false, updated_at = now()
            WHERE tenant_id = portal.current_tenant() AND dang_dung"""
    )
    if id_ is not None:
        await conn.execute(
            """UPDATE tenant_data.nhan_vat SET dang_dung = true, updated_at = now()
                WHERE tenant_id = portal.current_tenant() AND id = $1::uuid""",
            id_,
        )


async def xoa(conn: asyncpg.Connection, id_: str) -> None:
    await conn.execute(
        "DELETE FROM tenant_data.nhan_vat WHERE tenant_id = portal.current_tenant() AND id = $1::uuid", id_
    )
