"""CRUD dùng chung cho các bảng `shop`.

Hai tầng:
- Hàm SQL (`chen`, `sua`, `lay`, `xoa`, `liet_ke`) — module tự viết route phức tạp vẫn dùng.
- `dang_ky_crud()` — sinh đủ 5 route list/get/create/patch/delete cho bảng "phẳng".

Tên bảng/cột LUÔN đến từ code (field của model Pydantic, hằng của module), không bao
giờ từ request — nên ghép vào SQL được, và vẫn được bọc `"…"` cho chắc. Giá trị luôn
đi qua tham số bind.

Lỗi ràng buộc (UNIQUE/FK/CHECK) KHÔNG bắt ở đây: để nổi lên, `api/loi.py` dịch sang
409/422 ở một chỗ.
"""

import inspect
from collections.abc import Sequence
from copy import copy
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, create_model
from pydantic.alias_generators import to_camel

from portal.api.loi import khong_tim_thay
from portal.core.db.pool import get_pool
from portal.core.db.session import tx
from portal.core.dto import CamelOut

SCHEMA = "shop"
LIMIT_MAC_DINH = 50
LIMIT_TOI_DA = 500


class CamelIn(BaseModel):
    """Thân request: camelCase trên dây, snake_case trong code (khớp tên cột).

    `extra="forbid"`: gõ sai tên trường là 422 ngay, không âm thầm bị bỏ qua.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Trang[T](CamelOut):
    items: list[T]
    total: int
    limit: int
    offset: int


def ban_sua(model: type[CamelIn]) -> type[CamelIn]:
    """Model PATCH: mọi trường tuỳ chọn. Chỉ trường CLIENT GỬI mới được ghi
    (`model_dump(exclude_unset=True)`), nên gửi `null` tường minh = xoá giá trị."""
    truong = {}
    for ten, f in model.model_fields.items():
        fi = copy(f)  # giữ ràng buộc (pattern, ge/le, max_length…), chỉ bỏ "bắt buộc"
        fi.default = None
        fi.default_factory = None
        truong[ten] = (f.annotation | None, fi)
    return create_model(f"{model.__name__}Patch", __base__=CamelIn, **truong)  # type: ignore[call-overload]


def _bang(ten: str) -> str:
    return f'{SCHEMA}."{ten}"'


def _cot(ten: str) -> str:
    return f'"{ten}"'


async def chen(conn: asyncpg.Connection, bang: str, du_lieu: dict[str, Any]) -> asyncpg.Record:
    cot = list(du_lieu)
    sql = (
        f"INSERT INTO {_bang(bang)} ({', '.join(map(_cot, cot))}) "
        f"VALUES ({', '.join(f'${i}' for i in range(1, len(cot) + 1))}) RETURNING *"
    )
    return await conn.fetchrow(sql, *du_lieu.values())


async def sua(
    conn: asyncpg.Connection, bang: str, id_: int, du_lieu: dict[str, Any], *, khoa: str = "id"
) -> asyncpg.Record | None:
    if not du_lieu:
        return await lay(conn, bang, id_, khoa=khoa)
    gan = ", ".join(f"{_cot(c)} = ${i}" for i, c in enumerate(du_lieu, start=2))
    sql = f"UPDATE {_bang(bang)} SET {gan} WHERE {_cot(khoa)} = $1 RETURNING *"
    return await conn.fetchrow(sql, id_, *du_lieu.values())


async def lay(conn: asyncpg.Connection, bang: str, id_: int, *, khoa: str = "id") -> asyncpg.Record | None:
    return await conn.fetchrow(f"SELECT * FROM {_bang(bang)} WHERE {_cot(khoa)} = $1", id_)


async def xoa(conn: asyncpg.Connection, bang: str, id_: int, *, khoa: str = "id") -> bool:
    return await conn.fetchval(f"DELETE FROM {_bang(bang)} WHERE {_cot(khoa)} = $1 RETURNING true", id_) is True


async def liet_ke(
    conn: asyncpg.Connection,
    bang: str,
    *,
    dieu_kien: Sequence[str] = (),
    tham_so: Sequence[Any] = (),
    sap_xep: str = "id",
    limit: int = LIMIT_MAC_DINH,
    offset: int = 0,
) -> tuple[list[asyncpg.Record], int]:
    """`dieu_kien` là mảnh SQL do CODE viết, tham chiếu `$1..$n` trong `tham_so`."""
    where = f"WHERE {' AND '.join(dieu_kien)}" if dieu_kien else ""
    n = len(tham_so)
    rows = await conn.fetch(
        f"SELECT *, count(*) OVER () AS _total FROM {_bang(bang)} {where} "
        f"ORDER BY {sap_xep} LIMIT ${n + 1} OFFSET ${n + 2}",
        *tham_so,
        limit,
        offset,
    )
    if rows:
        return rows, int(rows[0]["_total"])
    total = await conn.fetchval(f"SELECT count(*) FROM {_bang(bang)} {where}", *tham_so)
    return [], int(total)


def ve_out(model: type[BaseModel], hang: asyncpg.Record) -> Any:
    return model.model_validate({k: v for k, v in dict(hang).items() if k != "_total"})


Limit = Annotated[int, Query(ge=1, le=LIMIT_TOI_DA)]
Offset = Annotated[int, Query(ge=0)]


def dang_ky_crud(
    router: APIRouter,
    *,
    duong_dan: str,
    bang: str,
    ten: str,
    model_in: type[CamelIn],
    model_out: type[CamelOut],
    loc: dict[str, str] | None = None,
    tim_kiem: Sequence[str] = (),
    sap_xep: str = "id",
) -> None:
    """Sinh 5 route cho một bảng phẳng.

    `loc`: tham số query → cột lọc bằng (vd `{"brandId": "brand_id"}`), giá trị là số nguyên.
    `tim_kiem`: các cột text cho `?q=` (ILIKE, không phân biệt hoa thường).
    """
    model_sua = ban_sua(model_in)
    loc = loc or {}

    async def liet_ke_route(
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        limit: Limit = LIMIT_MAC_DINH,
        offset: Offset = 0,
        q: str | None = None,
        **gia_tri_loc: int | None,
    ) -> Trang[model_out]:  # type: ignore[valid-type]
        dk: list[str] = []
        ts: list[Any] = []
        for tham, cot in loc.items():
            v = gia_tri_loc.get(tham)
            if v is not None:
                ts.append(v)
                dk.append(f"{_cot(cot)} = ${len(ts)}")
        if q and tim_kiem:
            ts.append(f"%{q}%")
            dk.append("(" + " OR ".join(f"{_cot(c)}::text ILIKE ${len(ts)}" for c in tim_kiem) + ")")
        async with pool.acquire() as conn:
            rows, total = await liet_ke(
                conn, bang, dieu_kien=dk, tham_so=ts, sap_xep=sap_xep, limit=limit, offset=offset
            )
        return Trang[model_out](  # type: ignore[valid-type]
            items=[ve_out(model_out, r) for r in rows], total=total, limit=limit, offset=offset
        )

    # FastAPI đọc chữ ký hàm để sinh tham số query — `**kwargs` không được, phải dựng chữ ký thật.
    sig = inspect.signature(liet_ke_route)
    tham_co_dinh = [p for p in sig.parameters.values() if p.kind != inspect.Parameter.VAR_KEYWORD]
    tham_loc = [inspect.Parameter(t, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=int | None) for t in loc]
    liet_ke_route.__signature__ = sig.replace(parameters=[*tham_co_dinh, *tham_loc])  # type: ignore[attr-defined]

    async def lay_route(id: int, pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> model_out:  # type: ignore[valid-type]
        async with pool.acquire() as conn:
            hang = await lay(conn, bang, id)
        if hang is None:
            raise khong_tim_thay(ten, id)
        return ve_out(model_out, hang)

    async def tao_route(body: model_in, pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> model_out:  # type: ignore[valid-type]
        async with tx(pool) as conn:
            hang = await chen(conn, bang, body.model_dump())
        return ve_out(model_out, hang)

    async def sua_route(
        id: int,
        body: model_sua,  # type: ignore[valid-type]
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ) -> model_out:  # type: ignore[valid-type]
        async with tx(pool) as conn:
            hang = await sua(conn, bang, id, body.model_dump(exclude_unset=True))
        if hang is None:
            raise khong_tim_thay(ten, id)
        return ve_out(model_out, hang)

    async def xoa_route(id: int, pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> Response:
        async with tx(pool) as conn:
            if not await xoa(conn, bang, id):
                raise khong_tim_thay(ten, id)
        return Response(status_code=204)

    router.add_api_route(duong_dan, liet_ke_route, methods=["GET"], summary=f"Danh sách {ten}")
    router.add_api_route(f"{duong_dan}/{{id}}", lay_route, methods=["GET"], summary=f"Chi tiết {ten}")
    router.add_api_route(duong_dan, tao_route, methods=["POST"], status_code=201, summary=f"Tạo {ten}")
    router.add_api_route(f"{duong_dan}/{{id}}", sua_route, methods=["PATCH"], summary=f"Sửa {ten}")
    router.add_api_route(f"{duong_dan}/{{id}}", xoa_route, methods=["DELETE"], status_code=204, summary=f"Xoá {ten}")
