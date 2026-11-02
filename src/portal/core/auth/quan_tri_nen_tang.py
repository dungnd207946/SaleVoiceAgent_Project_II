"""Cổng quản trị NỀN TẢNG — xuyên tenant, ngoài 13 nhóm của PQ_01.

VÌ SAO KHÔNG DÙNG ACTIONS: 13 nhóm của PQ_01 §3.1 là quyền TRONG một workspace.
`Principal` mang `tenant_id`; `require()` trả về một Principal đã gắn workspace.
Admin nền tảng hành động XUYÊN tenant — họ không có tenant_id để mang.

Và M2a phát CẢ danh mục action cho MỌI user, nên thêm 'platform_admin.manage'
vào ACTIONS là phát quyền quản trị nền tảng cho mọi người dùng workspace. Các
test khoá cứng con số đó (`tests/api/test_actions.py::test_dung_14_nhom` ·
`tests/api/test_contracts.py::test_dem_14_truoc_khi_so` ·
`tests/modules/enrollment/test_router.py::test_admin_khong_dung_14_action_cua_pq01`)
sẽ đỏ, và chúng đỏ ĐÚNG. ⚠ `test_login.py`/`test_tao.py` KHÔNG còn nằm trong
danh sách này (2026-08-20): chúng so bằng `len(ALL_ACTIONS)` thay vì một
literal, nên chỉ đỏ nếu action mới ĐƯỢC CẤP cho Quản trị mà không tăng danh
mục theo — canh việc thêm action vào `ACTIONS` mà không cấp gì phải dựa vào
ba test khoá cứng ở trên.

TẠM THỜI: một token tĩnh trong env. Hệ quả đã biết — không biết ai đang gọi, nên
audit_log.actor ghi "platform_admin" chứ không ghi tên người. Khi M2b chốt vai
trò thật, hàm này đổi RUỘT và giữ nguyên CHỮ KÝ, nên không route nào phải sửa.
Đó là lý do nó là một hàm chứ không phải Depends(...) viết thẳng trong router.
"""

import hmac
from typing import Annotated, Any

from fastapi import Depends, Header

from portal.api.loi import LoiPortal
from portal.core.config import get_settings

ACTOR_QUAN_TRI = "platform_admin"
"""Ghi vào audit_log.actor. Chưa biết người thật — xem docstring module."""

DO_DAI_TOKEN_TOI_THIEU = 32


def _token_khong_hop_le() -> LoiPortal:
    return LoiPortal("INVALID_ADMIN_TOKEN", 401, "Token quản trị nền tảng không hợp lệ")


async def _kiem_token(x_platform_admin_token: Annotated[str, Header()] = "") -> None:
    c = get_settings()
    mong_doi = c.platform_admin_token

    if c.environment == "production" and len(mong_doi) < DO_DAI_TOKEN_TOI_THIEU:
        raise RuntimeError(
            f"PLATFORM_ADMIN_TOKEN phải từ {DO_DAI_TOKEN_TOI_THIEU} ký tự ở production. "
            f"Sinh: python -c 'import secrets;print(secrets.token_urlsafe(32))'"
        )

    # compare_digest cả khi header rỗng: thoát sớm là để lộ độ dài qua thời gian.
    # Và token chưa cấu hình (mong_doi rỗng) phải TỪ CHỐI, không phải cho qua.
    if not mong_doi or not hmac.compare_digest(x_platform_admin_token, mong_doi):
        raise _token_khong_hop_le()


def require_quan_tri_nen_tang() -> Any:
    """Dùng làm default của tham số endpoint:

        async def tao(_: None = require_quan_tri_nen_tang()): ...

    Route vẫn PHẢI khai thêm `require(None, ly_do=...)` để qua cổng
    test_moi_route_khai_action.py của M2a. Hai thứ khác nhau: require(None) nói
    "route này cố ý không dùng action"; hàm này nói "nhưng nó vẫn có cổng riêng".
    """
    return Depends(_kiem_token)
