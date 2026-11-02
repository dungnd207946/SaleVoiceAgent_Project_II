"""Hai khối endpoint mất chủ sau khi bỏ `org_role` — mặc định phải TẮT.

Vai trò TOÀN CỤC từ migration 0105: một bộ 4 dùng chung cho MỌI workspace. Nếu để
ghi `/roles` mở cho `WORKSPACE_ADMIN` thì Quản trị của một workspace bất kỳ sửa
hoặc xoá được vai trò của TẤT CẢ workspace khác — trước đây `org_role='owner'`
giới hạn phạm vi đó.

`/users*` thì mất chủ hoàn toàn: không còn admin hệ thống nào trong mô hình mới.

⚠ File này CỐ Ý không dùng fixture `bat_hai_co` của conftest (nó `delenv` cả hai):
đây là chỗ duy nhất canh chiều "mặc định tắt". Xem spec bo-organization §6.2.
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def tat_hai_co(monkeypatch):
    monkeypatch.delenv("USERS_ADMIN_ENABLED", raising=False)
    monkeypatch.delenv("ROLES_CRUD_ENABLED", raising=False)


def test_mac_dinh_trong_code_la_tat():
    """`Settings(_env_file=None)`: đo giá trị mặc định trong CODE, không phải `.env`
    của lập trình viên — xem Gotchas ở CLAUDE.md."""
    from portal.core.config import Settings

    s = Settings(_env_file=None)
    assert s.roles_crud_enabled is False
    assert s.users_admin_enabled is False


@pytest.mark.parametrize(
    ("method", "duong", "than"),
    [
        ("post", "/api/v1/roles", {"name": "X", "description": None, "actions": []}),
        ("patch", "/api/v1/roles/r_x", {"name": "X", "description": None, "actions": []}),
        ("delete", "/api/v1/roles/r_x", None),
    ],
)
async def test_ghi_vai_tro_bi_tat(dang_nhap_san, method, duong, than):
    r = await getattr(dang_nhap_san, method)(duong, **({"json": than} if than else {}))
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "FEATURE_DISABLED"


async def test_doc_vai_tro_van_mo(dang_nhap_san):
    """FE cần `GET /roles` để render dropdown chọn vai trò khi mời thành viên.

    Đóng luôn đường đọc là làm hỏng luồng mời người — thứ không liên quan gì tới
    rủi ro mà cờ này chặn.
    """
    r = await dang_nhap_san.get("/api/v1/roles")
    assert r.status_code == 200, r.text
    assert {v["name"] for v in r.json()} == {"Quản trị", "CSKH", "Biên tập", "Người xem"}


@pytest.mark.parametrize(
    ("method", "duong"),
    [("get", "/api/v1/users"), ("get", "/api/v1/users/u_x"), ("delete", "/api/v1/users/u_x")],
)
async def test_quan_tri_user_bi_tat(dang_nhap_san, method, duong):
    r = await getattr(dang_nhap_san, method)(duong)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "FEATURE_DISABLED"
