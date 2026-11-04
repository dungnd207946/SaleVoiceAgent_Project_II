"""Hình dạng lỗi DUY NHẤT của API: `{"error": {"code", "message", "fields"?}}`.

Một hình dạng cho mọi endpoint nghĩa là FE viết một chỗ xử lý lỗi. Module KHÔNG tự
trả JSON lỗi — nó raise LoiPortal, hoặc để lỗi ràng buộc của Postgres nổi lên và
handler ở đây dịch sang HTTP.
"""

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class LoiPortal(Exception):
    """Lỗi có mã, dịch được sang HTTP. Mọi lỗi nghiệp vụ đi qua đây."""

    def __init__(self, ma: str, http: int, thong_diep: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(thong_diep)
        self.ma = ma
        self.http = http
        self.thong_diep = thong_diep
        self.headers = headers or {}


def khong_tim_thay(ten: str, id_: object) -> LoiPortal:
    return LoiPortal("NOT_FOUND", 404, f"Không tìm thấy {ten} #{id_}")


def du_lieu_khong_hop_le(thong_diep: str) -> LoiPortal:
    return LoiPortal("INVALID_DATA", 422, thong_diep)


def _duong_dan_truong(loc: tuple) -> str:
    """`('body', 'listPriceVnd')` → `"body.listPriceVnd"`; chỉ số mảng thành `[i]`.

    Giữ tiền tố `body`/`query`/`path` để FE biết sửa ở đâu; tên field là alias camelCase
    client đã gửi nên FE map thẳng về ô nhập.
    """
    phan: list[str] = []
    for p in loc:
        if isinstance(p, int):
            phan.append(f"[{p}]")
        elif phan:
            phan.append(f".{p}")
        else:
            phan.append(str(p))
    return "".join(phan)


def _than_loi_validate(e: RequestValidationError) -> dict:
    """422 có cấu trúc. CHỈ lấy `loc`/`msg` — `ctx` có thể chứa object không JSON-hoá
    được (vỡ 500 ngay trong handler lỗi), `input` là phản chiếu dữ liệu client."""
    truong = [
        {"field": _duong_dan_truong(tuple(loi_con.get("loc", ()))), "reason": str(loi_con.get("msg", ""))}
        for loi_con in e.errors()
    ]
    ten = ", ".join(t["field"] for t in truong) or "không rõ"
    return {
        "code": "VALIDATION_ERROR",
        "message": f"Dữ liệu gửi lên không hợp lệ ({len(truong)} lỗi): {ten}",
        "fields": truong,
    }


def _loi_rang_buoc(e: asyncpg.IntegrityConstraintViolationError) -> tuple[int, str, str]:
    """Ràng buộc DB là nguồn sự thật cuối cùng (CHECK/UNIQUE/FK trong schema `shop`).

    Dịch ở MỘT chỗ để route không phải bắt từng loại. Tên constraint đi kèm thông điệp —
    đủ để dev FE biết ràng buộc nào, không lộ dữ liệu hàng khác (không kèm `detail`).
    """
    ten = getattr(e, "constraint_name", None) or "không rõ"
    if isinstance(e, asyncpg.UniqueViolationError):
        return 409, "DUPLICATE", f"Giá trị đã tồn tại (ràng buộc {ten})"
    if isinstance(e, asyncpg.ForeignKeyViolationError):
        return 409, "REFERENCE_ERROR", f"Tham chiếu không hợp lệ hoặc bản ghi đang được dùng (ràng buộc {ten})"
    if isinstance(e, asyncpg.CheckViolationError):
        return 422, "CHECK_FAILED", f"Dữ liệu vi phạm điều kiện (ràng buộc {ten})"
    if isinstance(e, asyncpg.NotNullViolationError):
        cot = getattr(e, "column_name", None) or "không rõ"
        return 422, "MISSING_FIELD", f"Thiếu giá trị bắt buộc: {cot}"
    return 409, "CONSTRAINT_ERROR", f"Vi phạm ràng buộc dữ liệu ({ten})"


def dang_ky_handler_loi(app: FastAPI) -> None:
    @app.exception_handler(LoiPortal)
    async def _handler(_: Request, e: LoiPortal) -> JSONResponse:
        return JSONResponse(
            status_code=e.http,
            content={"error": {"code": e.ma, "message": e.thong_diep}},
            headers=e.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _handler_validation(_: Request, e: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": _than_loi_validate(e)})

    @app.exception_handler(asyncpg.IntegrityConstraintViolationError)
    async def _handler_rang_buoc(_: Request, e: asyncpg.IntegrityConstraintViolationError) -> JSONResponse:
        http, ma, thong_diep = _loi_rang_buoc(e)
        return JSONResponse(status_code=http, content={"error": {"code": ma, "message": thong_diep}})
