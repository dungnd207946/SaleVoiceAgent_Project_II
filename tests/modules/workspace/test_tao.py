"""`POST /api/v1/workspaces` — người dùng tự tạo workspace và thành "Quản trị".

VIẾT LẠI 2026-08-15 cùng việc bỏ tầng tổ chức (spec bo-organization §5.2). Bốn
điều bản cũ neo lại đã đổi nghĩa hoặc đảo ngược:

  ① Cửa chặn `users.org_role` — ĐÃ BỎ. Cổng giờ chỉ là "có phiên hợp lệ", nên
     `test_member_bi_403` không còn lý do tồn tại và đã xoá. Thay bằng
     `test_khong_co_phien_thi_401`.

  ② "KHÔNG tạo hàng memberships" — ĐẢO NGƯỢC. Người tạo BẮT BUỘC nhận một hàng
     `memberships` vai trò "Quản trị"; không có nó thì `doc_quyen()` trả 0 action
     và họ không vào được chính workspace vừa tạo. Xem
     `test_nguoi_tao_thanh_quan_tri` và `test_tao_xong_vao_duoc_ngay`.

  ③ `tenant_verticals` được ghi — GIỮ NGUYÊN.

  ④ Giao dịch NGUYÊN TỬ — GIỮ NGUYÊN, và giờ bao gồm cả hàng `memberships`.

Thêm một điều mới:

  ⑤ Ràng buộc tên theo NGƯỜI TẠO, không toàn cục. Hai người khác nhau đặt trùng
     tên là HỢP LỆ (`UNIQUE (created_by, lower(btrim(name)))`, migration 0106) —
     ai cũng tạo được workspace nên "Test" trùng nhau là chuyện bình thường.
"""

import asyncpg
import httpx
import pytest

from portal.core.auth import password as pw
from portal.core.auth.actions import ALL_ACTIONS
from tests.modules.workspace.conftest import dang_nhap

pytestmark = pytest.mark.integration
"""`integration` là marker DUY NHẤT khai trong pyproject (`markers = [...]`).

`asyncio_mode = "auto"` lo phần async — không cần `pytest.mark.anyio`, và một
marker chưa khai chỉ sinh warning rồi bị bỏ qua, tức nó không đánh dấu gì cả.
"""


async def test_tao_duoc_tra_201(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Sàn Đông Nam"})
    assert r.status_code == 201, r.text

    body = r.json()
    assert body["id"] == "ws_san_dong_nam", "id phải fold dấu, không phải ws_s_n_ng_nam"
    assert body["name"] == "Ws Sàn Đông Nam"
    assert "orgId" not in body, "tầng tổ chức đã bỏ — trường này không được quay lại"
    assert body["lifecycle"] == "active"
    # Chưa nhịp tim nào ⇒ provisioning. Đây là trạng thái ĐÚNG của workspace mới,
    # không phải lỗi.
    assert body["status"] == "provisioning"
    assert body["createdAt"]

    async with pool.acquire() as conn:
        hang = await conn.fetchrow("SELECT name, created_by, lifecycle FROM control.tenants WHERE id = $1", body["id"])
        assert hang["name"] == "Ws Sàn Đông Nam"
        assert hang["created_by"] == "u_ws_owner"


async def test_nguoi_tao_thanh_quan_tri(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """② — bất biến ĐẢO NGƯỢC so với bản trước 2026-08-15.

    Bỏ dòng `them_membership` ở `service.tao()` thì test này đỏ, và nó đỏ TRƯỚC
    khi ai đó phát hiện bằng tay rằng workspace mới tạo không vào được.
    """
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Quản Trị"})
    assert r.status_code == 201, r.text

    async with pool.acquire() as conn:
        ten_vai_tro = await conn.fetchval(
            """SELECT ro.name FROM control.memberships m
                 JOIN control.roles ro ON ro.id = m.role_id
                WHERE m.user_id = 'u_ws_owner' AND m.tenant_id = $1""",
            r.json()["id"],
        )
    assert ten_vai_tro == "Quản trị"


async def test_tao_xong_vao_duoc_ngay(client_owner: httpx.AsyncClient):
    """Hệ quả người dùng thấy được của ②: đổi sang workspace vừa tạo và có đủ quyền.

    Đây là test sẽ đỏ nếu ai đó gỡ `LEFT JOIN memberships` hoặc đổi nó thành
    `INNER JOIN` trong `core/auth/repo.doc_quyen()`.
    """
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Vào Ngay"})
    tid = r.json()["id"]

    doi = await client_owner.post("/api/v1/me/workspace", json={"workspaceId": tid})
    assert doi.status_code == 200, doi.text
    body = doi.json()
    assert body["currentWorkspaceId"] == tid
    # So với `len(ALL_ACTIONS)`, không phải một literal: điểm cần canh là "người
    # tạo trở thành Quản trị nên có ĐỦ danh mục", không phải "danh mục có đúng N
    # phần tử" — con số đó đổi mỗi khi thêm action mới (13 → 14 lúc thêm
    # `billing.read`, `0945_billing_action`).
    assert len(body["actions"]) == len(ALL_ACTIONS), "Quản trị phải có đủ danh mục action"


async def test_ghi_tenant_verticals(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """③ — bảng này rỗng suốt từ 0002 tới bản thêm nó."""
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Vertical"})
    assert r.status_code == 201, r.text

    async with pool.acquire() as conn:
        verticals = await conn.fetch(
            "SELECT vertical FROM control.tenant_verticals WHERE tenant_id = $1", r.json()["id"]
        )
    assert [v["vertical"] for v in verticals] == ["realestate"]


async def test_khong_co_phien_thi_401(app_client: httpx.AsyncClient):
    """Cổng còn lại DUY NHẤT là phiên.

    Thay `test_member_bi_403` của bản cũ: `org_role` không còn, nên không có
    người-đăng-nhập-được nào bị 403 ở đường này nữa.
    """
    r = await app_client.post("/api/v1/workspaces", json={"name": "Ws Không Phiên"})
    assert r.status_code == 401


async def test_trung_ten_cung_nguoi_tao_thi_409(client_owner: httpx.AsyncClient):
    await client_owner.post("/api/v1/workspaces", json={"name": "Ws Trùng"})
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Trùng"})
    assert r.status_code == 409, r.text


async def test_trung_ten_khac_hoa_thuong_va_khoang_trang_cung_409(client_owner: httpx.AsyncClient):
    """`lower(btrim(...))` cả hai vế — "Ws A", "ws a" và "Ws A " là MỘT cái tên."""
    await client_owner.post("/api/v1/workspaces", json={"name": "Ws Hoa Thường"})
    r = await client_owner.post("/api/v1/workspaces", json={"name": "  ws hoa thường  "})
    assert r.status_code == 409, r.text


async def test_trung_ten_khac_nguoi_tao_thi_201(app_client: httpx.AsyncClient, to_chuc_ws, pool: asyncpg.Pool):
    """⑤ — bất biến MỚI thay cho "trùng tên khác org thì OK".

    Ai cũng tạo được workspace, nên hai người lạ đặt tên "Test" là chuyện bình
    thường. Ràng buộc toàn cục sẽ 409 vào mặt người thứ hai mà không giải thích
    được — xem `repo.ten_da_dung`.
    """
    await dang_nhap(app_client, "owner@anphuland.vn")
    a = await app_client.post("/api/v1/workspaces", json={"name": "Ws Chung Tên"})
    assert a.status_code == 201, a.text

    await dang_nhap(app_client, "owner2@khac.vn")
    b = await app_client.post("/api/v1/workspaces", json={"name": "Ws Chung Tên"})
    assert b.status_code == 201, b.text
    assert a.json()["id"] != b.json()["id"], "id vẫn phải duy nhất toàn cục"


async def test_ten_rong_thi_422(client_owner: httpx.AsyncClient):
    r = await client_owner.post("/api/v1/workspaces", json={"name": ""})
    assert r.status_code == 422


async def test_truong_la_bi_tu_choi(client_owner: httpx.AsyncClient):
    """`extra="forbid"` — `orgId` từng là trường thật, giờ gửi lên phải bị từ chối
    thay vì im lặng bỏ qua."""
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Lạ", "orgId": "noble"})
    assert r.status_code == 422


async def test_ghi_nhat_ky(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Nhật Ký"})
    async with pool.acquire() as conn:
        hang = await conn.fetchrow(
            "SELECT hanh_dong, actor, chi_tiet FROM control.audit_log WHERE tenant_id = $1",
            r.json()["id"],
        )
    assert hang["hanh_dong"] == "workspace.tao"
    assert hang["actor"] == "u_ws_owner"


async def test_giao_dich_nguyen_tu(client_owner: httpx.AsyncClient, pool: asyncpg.Pool, monkeypatch):
    """④ — hỏng giữa chừng thì KHÔNG để lại hàng `tenants` mồ côi.

    Cho `them_vertical` nổ: hàng `tenants` đã INSERT trước đó phải cuốn theo.
    Giao dịch mở ở router, nên phép kiểm này cũng canh luôn việc không ai chuyển
    nó xuống service rồi thu hẹp phạm vi.
    """
    from portal.modules.workspace import repo

    async def no(*a, **k):
        raise RuntimeError("cố ý nổ giữa giao dịch")

    monkeypatch.setattr(repo, "them_vertical", no)

    with pytest.raises(RuntimeError, match="cố ý nổ"):
        await client_owner.post("/api/v1/workspaces", json={"name": "Ws Nguyên Tử"})

    async with pool.acquire() as conn:
        con = await conn.fetchval("SELECT count(*) FROM control.tenants WHERE id = 'ws_nguyen_tu'")
    assert con == 0


async def test_phien_chua_co_workspace_thi_tro_vao_cai_vua_tao(
    app_client: httpx.AsyncClient, pool: asyncpg.Pool
) -> None:
    """BUG 2026-08-17: tạo xong workspace đầu tiên mà `/me` vẫn trả
    `currentWorkspaceId: null` ⇒ FE đá người dùng về lại `/tao-workspace-dau-tien`.

    Vòng lặp kín: `dung_session_out` trả `currentWorkspaceId` NGUYÊN từ bản ghi
    phiên Redis, không suy từ danh sách `workspaces`. `POST /workspaces` trước đây
    ĐỌC bản ghi đó (để lấy `user_id`) nhưng không bao giờ GHI lại, nên `tenant_id`
    của người vừa tự đăng ký đứng mãi ở NULL — và guard của FE
    (`currentWorkspaceId === null` ⇒ đi tới màn tạo workspace) đưa họ về đúng màn
    họ vừa hoàn thành.

    Bài này canh CẢ BA thứ phải đúng cùng lúc, vì thiếu bất kỳ cái nào là màn
    dashboard vẫn hỏng theo một kiểu khác:
      · `currentWorkspaceId` trỏ vào workspace mới  -> FE thoát được màn tạo
      · workspace mới có trong `workspaces`          -> switcher hiện nó
      · `actions` KHÔNG rỗng                         -> `doc_quyen` chạy được, các
        mục menu hiện ra (nó bị bỏ qua hoàn toàn khi `tenant_id` là None)
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ($1,$2,$3,$4)",
            "u_ws_dau",
            "wsdau@x.vn",
            pw.bam("mat-khau-du-dai"),
            "Người Mới",
        )
    try:
        r = await app_client.post("/api/v1/auth/login", json={"email": "wsdau@x.vn", "password": "mat-khau-du-dai"})
        assert r.status_code == 200, r.text
        assert r.json()["currentWorkspaceId"] is None, "tiền đề: chưa thuộc workspace nào"

        r = await app_client.post("/api/v1/workspaces", json={"name": "WS Đầu Tiên"})
        assert r.status_code == 201, r.text
        ws_id = r.json()["id"]

        me = (await app_client.get("/api/v1/me")).json()
        assert me["currentWorkspaceId"] == ws_id
        assert [w["id"] for w in me["workspaces"]] == [ws_id]
        assert me["actions"], "phiên trỏ vào workspace rồi thì doc_quyen phải trả action"
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM control.memberships WHERE user_id = 'u_ws_dau'")
            await conn.execute("DELETE FROM control.tenants WHERE created_by = 'u_ws_dau'")
            await conn.execute("DELETE FROM control.users WHERE id = 'u_ws_dau'")


async def test_phien_da_co_workspace_thi_KHONG_bi_chuyen(client_owner: httpx.AsyncClient, pool: asyncpg.Pool) -> None:
    """Mặt còn lại của bài trên — nếu thiếu, fix sẽ đổi hành vi một luồng đang đúng.

    Dialog tạo workspace trong app (`WorkspaceSwitcher` → `TaoWorkspaceDialog`) TỰ
    gọi `switchWorkspace` sau khi tạo, theo thứ tự riêng của nó (xoá cache workspace
    cũ TRƯỚC khi đặt phiên mới). Chuyển hộ ở backend là đổi hành vi đó theo cách FE
    không thấy được — và người dùng đang ở workspace A bấm "tạo B" sẽ bị nhấc sang B
    trước khi cache của A được dọn.
    """
    truoc = (await client_owner.get("/api/v1/me")).json()["currentWorkspaceId"]
    assert truoc is not None, "tiền đề: đã ở trong một workspace"

    r = await client_owner.post("/api/v1/workspaces", json={"name": "WS Thu Hai"})
    assert r.status_code == 201, r.text
    moi = r.json()["id"]
    assert moi != truoc

    sau = (await client_owner.get("/api/v1/me")).json()["currentWorkspaceId"]
    assert sau == truoc, "phiên phải đứng nguyên ở workspace cũ"

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.memberships WHERE tenant_id = $1", moi)
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", moi)
