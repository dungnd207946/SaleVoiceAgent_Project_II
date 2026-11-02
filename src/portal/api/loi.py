"""Hình dạng lỗi DUY NHẤT của API (spec §4.4).

Một hình dạng cho mọi endpoint nghĩa là FE viết một chỗ xử lý lỗi, không phải
một chỗ cho mỗi module. Module KHÔNG tự trả JSON lỗi — nó raise LoiPortal.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class LoiPortal(Exception):
    """Lỗi có mã, dịch được sang HTTP. Mọi lỗi nghiệp vụ đi qua đây.

    `headers` cho lỗi nào cần nói thêm bằng HEADER chuẩn HTTP — ca đầu tiên là
    `Retry-After` của 429 (cổng nạp): backoff logic của adapter bên khách đọc
    header bằng thư viện retry sẵn có, thay vì regex một câu tiếng Việt. Thân
    lỗi GIỮ NGUYÊN khuôn `{"error": {...}}` — header là phần THÊM, không phải
    một hình dạng lỗi thứ hai.
    """

    def __init__(self, ma: str, http: int, thong_diep: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(thong_diep)
        self.ma = ma
        self.http = http
        self.thong_diep = thong_diep
        self.headers = headers or {}


# Bốn lỗi của M2a. Module sau thêm hằng số của nó vào file của nó, không vào đây.
def khong_co_phien() -> LoiPortal:
    return LoiPortal("NO_SESSION", 401, "Chưa đăng nhập hoặc phiên đã hết hạn")


def sai_dang_nhap() -> LoiPortal:
    """MỘT mã cho ba tình huống (email không có · sai mật khẩu · user suspended).

    Phân biệt chúng là cho không một máy dò danh sách email khách hàng.
    """
    return LoiPortal("INVALID_CREDENTIALS", 401, "Email hoặc mật khẩu không đúng")


def khong_du_quyen() -> LoiPortal:
    return LoiPortal("FORBIDDEN", 403, "Bạn không có quyền thực hiện việc này")


def workspace_da_dong() -> LoiPortal:
    """403 — phiên trỏ vào một workspace `lifecycle='closed'`.

    Ở ĐÂY CHỨ KHÔNG Ở `modules/workspace/loi.py`, dù module đó sở hữu đường xoá:
    chỗ RAISE nó là `core/auth/require.py`, và core không được import ruột một
    module (Luật 3 — `tests/test_module_boundaries.py` đọc AST). Cùng hạng với
    `khong_co_phien` và `thieu_quyen`: lỗi do chính cổng quyền sinh ra.

    MÃ RIÊNG, không dùng chung `FORBIDDEN`: đây là lỗi FE phải xử lý KHÁC. "Thiếu
    quyền" là đi hỏi Quản trị; "workspace đã đóng" là tải lại phiên và chuyển sang
    workspace khác — `GET /me` tự làm việc đó, nhưng chỉ khi FE biết mà gọi.
    """
    return LoiPortal("WORKSPACE_DA_DONG", 403, "Workspace này đã bị xoá")


def thieu_quyen(action: str, role_name: str | None) -> LoiPortal:
    """403 của M2b — PHẢI nói LÝ DO, không phải câu chung của `khong_du_quyen()`
    (spec §3.4). Người dùng đọc được "vai trò Người xem của tôi không có quyền
    Thêm · sửa" thay vì đoán, và tự đi hỏi admin đúng câu cần hỏi.

    `role_name=None` nghĩa là user còn `lifecycle='active'` nhưng KHÔNG có
    membership ở workspace này. Từ 2026-08-15 nó gồm cả trường hợp phiên CHƯA CÓ
    workspace nào (vừa tự đăng ký) — `require()` gọi thẳng tới đây, xem nhánh
    `ban_ghi.tenant_id is None`.
    """
    from portal.core.auth.actions import NHAN_HANH_DONG

    nhan = NHAN_HANH_DONG.get(action, action)
    if role_name is None:
        return LoiPortal("FORBIDDEN", 403, f"Bạn chưa được cấp vai trò nào ở workspace này nên chưa có quyền: {nhan}")
    return LoiPortal("FORBIDDEN", 403, f"Vai trò «{role_name}» không có quyền: {nhan}")


def khong_co_workspace() -> LoiPortal:
    """Đổi sang một workspace user KHÔNG thuộc (`POST /me/workspace`).

    ⚠ KHÔNG còn dùng cho đăng nhập / `/me`. PQ_01 Q01 từng chốt "phiên không có
    workspace nào là trạng thái HỎNG", và `dang_nhap`/`dung_session_out` raise mã
    này. Q01 đã bị ĐẢO NGƯỢC 2026-08-15 để mở tự đăng ký: người vừa tạo tài khoản
    có 0 workspace, nên 409 ở đó là ngõ cụt — họ không tới được màn tạo workspace.
    Xem spec bo-organization §5.0.
    """
    return LoiPortal("NO_WORKSPACE", 409, "Bạn không thuộc workspace này")


def tinh_nang_dang_tat(ten: str) -> LoiPortal:
    """403 chứ không 404: endpoint CÓ tồn tại và sẽ bật lại.

    404 làm client kết luận sai rằng nó đã bị gỡ và đi tìm đường thay thế; 403
    nói đúng sự thật — cửa có đó, hiện đang khoá.
    """
    return LoiPortal("FEATURE_DISABLED", 403, f"Tính năng «{ten}» đang tắt")


def _duong_dan_truong(loc: tuple) -> str:
    """`('body', 'mediaUrl')` → `"body.mediaUrl"`; `('query', 'limit')` →
    `"query.limit"`; phần tử số (chỉ mảng) thành `[i]`: `('body', 'category', 0)`
    → `"body.category[0]"`.

    GIỮ tiền tố `body`/`query`/`path` — FE cần biết field sai nằm ở THÂN hay ở
    query string mới sửa đúng chỗ (cùng một tên có thể có ở cả hai). Tên field là
    ALIAS camelCase mà client đã gửi (Pydantic báo theo alias khi field có
    `alias=`), nên FE map thẳng về ô nhập của mình, không phải dịch snake_case.
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
    """Thân lỗi 422 CÓ CẤU TRÚC — `error.fields` là danh sách `{field, reason}`.

    VÌ SAO ĐỔI (review vòng cuối, Minor F3): bản trước trả
    `message = str(e)`, tức nguyên văn repr của Pydantic:
    `"1 validation error:\\n  {'type': 'string_too_short', 'loc': ('body',
    'mediaUrl'), ...}"`. Đây là hình dạng 422 của MỌI route trong repo (25 route
    realestate + mọi route M2a — file này dùng CHUNG), và FE KHÔNG map được về
    field nào: nó phải parse repr của một dict Python bằng regex để biết ô nào
    đang đỏ. Danh sách có cấu trúc là thứ duy nhất dùng được để tô đỏ đúng ô.

    `error.code` GIỮ NGUYÊN `VALIDATION_ERROR` — mã lỗi là hợp đồng đã có, và
    `error.message` vẫn còn (một câu người đọc được, không phải repr) nên client
    cũ chỉ hiện `message` vẫn chạy: đây là thay đổi THÊM field, không phải đổi
    khuôn.

    CHỈ lấy `loc`/`msg` từ `e.errors()`, KHÔNG lấy `ctx`/`input`: `ctx` có thể
    chứa object Python (vd `ValueError`) không JSON-serialize được — `JSONResponse`
    sẽ vỡ 500 ngay trong handler lỗi, chỗ tệ nhất để có một lỗi thứ hai. `input`
    thì là dữ liệu client vừa gửi, phản chiếu nó vào body lỗi là một cách vọng lại
    nội dung không kiểm soát mà không đem lại gì cho FE (FE đang giữ input đó).
    """
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
