"""`TENANT_ID_PATTERN` — cổng chặn tenant_id sai định dạng TRƯỚC khi xuống DB.

VÌ SAO CÓ FILE NÀY: trước bản đầu (2026-08-06) payload chỉ khai `min_length=1,
max_length=64`, nên một tenant_id sai định dạng đi thẳng xuống
`control.dat_mat_khau_agent()` và người dùng nhận **500** kèm stacktrace asyncpg
(`RaiseError: tenant id không hợp lệ cho tên role: ...`) thay vì 422 nói rõ định dạng.
Đã mất một phiên truy lỗi để đi từ stacktrace đó về tới regex trong migration 0900.

CHỖ CƯỠNG CHẾ ĐỔI Ở `0941`, RÀNG BUỘC KHÔNG ĐỔI: `DeploymentIn` (body của
`POST /admin/deployments`) đã xoá cùng bảng `deployments`. Cùng regex nay nằm trên PATH
PARAM của `POST /admin/tenants/{tenant_id}/provision` và `.../keys`. File này vì thế
kiểm CHÍNH `TENANT_ID_PATTERN` — nguồn duy nhất cả hai route đọc — thay vì kiểm một
model đã biến mất.

Ràng buộc ở đây PHẢI khớp `tenants_id_check` (0002, nới ở 0911). Lệch một ký tự là API
từ chối một tenant mà DB nhận, hoặc ngược lại.
"""

import re

import pytest

from portal.modules.enrollment.contracts import TENANT_ID_PATTERN

_RE = re.compile(TENANT_ID_PATTERN)


def test_nhan_tenant_id_co_gach_ngang():
    """tenant_id import từ hệ ngoài mang dấu `-`. Đây là ca đã nổ ở production."""
    assert _RE.match("noble-homes_k3n7_retail")


def test_nhan_tenant_id_thuan_gach_duoi():
    """Dạng `slug_tenant()` sinh ra vẫn phải qua — nới không được phá ca cũ."""
    assert _RE.match("noble_homes_k3n7_retail")


@pytest.mark.parametrize(
    "xau",
    [
        "-noble-homes",  # `-` ở ký tự đầu: tên role `agent_-x` và nhãn subdomain đều sai
        "1noble",  # ký tự đầu phải là [a-z]
        "Noble-Homes",  # hoa: Postgres fold thường, hai tenant khác nhau đụng một role
        "noble homes",  # khoảng trắng
        "noble.homes",  # dấu `.` cắt nhãn subdomain thành hai
        "n",  # 1 ký tự: `{1,30}` đòi ký tự đầu CỘNG ít nhất một nữa
        "a" * 32,  # 32 > 31
    ],
)
def test_tu_choi_tenant_id_sai_dinh_dang(xau: str):
    assert not _RE.match(xau)


async def test_route_provision_tu_choi_tenant_id_sai_dinh_dang(app_client, monkeypatch, hai_tenant):
    """Regex đúng mà không gắn vào route thì vô dụng — bài này canh chỗ GẮN.

    `Noble-Homes` (chữ hoa) là ca chọn có chủ ý: nó khớp mọi ký tự hợp lệ khác nên chỉ
    có regex mới loại được, và nó chính là ca sinh ra hai tenant đụng một role Postgres.
    """
    from tests.modules.enrollment.conftest import ADMIN_TOKEN, MASTER_KEY

    monkeypatch.setenv("AGENT_MASTER_KEY", MASTER_KEY)
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", ADMIN_TOKEN)

    r = await app_client.post(
        "/api/v1/agent/admin/tenants/Noble-Homes/provision",
        headers={"X-Platform-Admin-Token": ADMIN_TOKEN},
    )
    assert r.status_code == 422, r.text
