"""`PATCH` và `DELETE /api/v1/workspaces/{id}` — đổi tên và đóng một workspace.

Hai đường của màn «Cài đặt workspace» (mảng Quản trị của portal). Chúng đi cùng
một file vì chúng chia CHUNG một bất biến, và bất biến đó là thứ dễ hỏng nhất ở
đây: **chỉ sửa được workspace mà PHIÊN ĐANG MỞ**.

`require(WORKSPACE_ADMIN)` tra ma trận quyền cho `Principal.tenant_id` — workspace
của phiên. Nếu endpoint lấy tenant từ ĐƯỜNG DẪN mà không đối chiếu, thì một Quản
trị của workspace A gọi `DELETE /workspaces/B` sẽ đi qua đúng cổng quyền của A rồi
đóng B. Cổng vẫn xanh, quyền vẫn được kiểm — chỉ là kiểm nhầm workspace. Đó là lý
do có `test_sua_workspace_khac_tra_403` và `test_xoa_workspace_khac_tra_403`.

BỐN ĐIỀU KHÁC NEO Ở ĐÂY:

  ① **Mã workspace KHÔNG đổi khi đổi tên.** `tenants.id` là khoá cách ly dùng cho
     bốn việc (policy RLS · role `agent_<id>` · `tenants/<id>/` trên kho tệp ·
     collection `kb_<id>` — xem `core/ten_tai_nguyen.py`). Sinh lại id từ tên mới
     là đổi cả bốn cùng lúc, trong một request PATCH.

  ② **Trùng tên xét theo NGƯỜI TẠO của workspace, không theo người đang sửa.**
     UNIQUE INDEX `tenants_nguoi_tao_ten_key` (0106) đặt trên
     `(created_by, lower(btrim(name)))`. Một Quản trị được mời vào workspace của
     người khác thì `created_by` không phải họ — tra theo actor là tra nhầm vế, và
     hậu quả là 500 `UniqueViolation` thay vì 409 có thông điệp.

  ③ **Không xoá được workspace CUỐI CÙNG.** Phiên không còn workspace nào là trạng
     thái mà portal chưa có màn nào cho (`SessionReady` của FE ném lỗi). 409 ở đây
     rẻ hơn nhiều so với một màn trắng.

  ④ **XOÁ LÀ XOÁ CỨNG.** `DELETE FROM control.tenants` — mọi bảng đều
     `REFERENCES control.tenants(id) ON DELETE CASCADE` nên một câu lệnh cuốn theo
     17 bảng `tenant_data` và ~14 bảng `control`. Không có `lifecycle='closed'`,
     không có kỳ chờ, không có job dọn.

  ⑤ **NHẬT KÝ PHẢI SỐNG SÓT CHÍNH CUỘC XOÁ.** `audit_log.tenant_id` cũng cascade,
     nên `nhat_ky.ghi()` (có tenant) sẽ tự xoá dòng vừa ghi trong CÙNG câu lệnh —
     xoá xong thì không còn bằng chứng nào rằng workspace từng tồn tại, hay ai đã
     xoá nó. Đường xoá vì thế dùng `ghi_he_thong()` (`tenant_id IS NULL`, ngoài
     cascade). `test_xoa_ghi_nhat_ky_song_sot_cascade` là bài canh điều đó, và nó
     là bài quan trọng nhất của cả nhóm xoá.

  ⑥ **ID ĐƯỢC TÁI SỬ DỤNG SAU KHI XOÁ.** `sinh_tenant_id()` tra trùng trên
     `control.tenants`; hàng đã xoá thì id đó rảnh. Nên dọn hụt một kho NGOÀI
     Postgres (collection Qdrant · tiền tố `tenants/<id>/` · role `agent_<id>`) là
     để workspace của khách SAU thừa hưởng dữ liệu của khách TRƯỚC. Với đóng mềm
     thì lớp lỗi này không tồn tại — nó là cái giá của quyết định xoá cứng.
"""

import asyncpg
import httpx
import pytest

from portal.modules.workspace import service

pytestmark = pytest.mark.integration


async def _xoa_trong_db(pool: asyncpg.Pool, tenant_id: str) -> None:
    """Xoá workspace THẲNG trong DB, không qua endpoint.

    Endpoint xoá xong sẽ dời con trỏ phiên sang workspace khác — đúng như thiết kế,
    nhưng nó xoá mất chính tình huống ba test cuối cần đo: một phiên CÒN trỏ vào
    workspace đã biến mất (tab thứ hai, máy thứ hai, hoặc một thành viên khác đang
    mở workspace lúc Quản trị bấm xoá).
    """
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", tenant_id)


# ─── Đổi tên ────────────────────────────────────────────────────────────────


async def test_sua_ten_tra_200_va_giu_nguyen_ma(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """① — đổi tên là đổi ĐÚNG một cột."""
    r = await client_owner.patch("/api/v1/workspaces/ws_co_san", json={"name": "Ws Tên Mới"})
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["id"] == "ws_co_san", "mã workspace là khoá cách ly — đổi tên không được sinh lại nó"
    assert body["name"] == "Ws Tên Mới"

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT name FROM control.tenants WHERE id = 'ws_co_san'") == "Ws Tên Mới"


async def test_sua_ten_trung_workspace_khac_cua_minh_tra_409(client_owner: httpx.AsyncClient):
    """② vế thuận: hai workspace CÙNG người tạo không được trùng tên."""
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Thứ Hai"})
    assert r.status_code == 201, r.text

    r = await client_owner.patch("/api/v1/workspaces/ws_co_san", json={"name": "Ws Thứ Hai"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "WORKSPACE_TRUNG_TEN"


async def test_trung_ten_xet_theo_nguoi_tao_khong_theo_nguoi_sua(client_member: httpx.AsyncClient, pool: asyncpg.Pool):
    """② vế nghịch — CHỖ DỄ VIẾT SAI NHẤT của cả file này.

    `u_ws_member` là Quản trị ở `ws_co_san` nhưng KHÔNG phải người tạo nó
    (`created_by = 'u_ws_owner'`). Họ tự tạo một workspace tên "Ws Của Member", rồi
    đổi tên `ws_co_san` thành đúng chuỗi đó.

    Phải 200: ràng buộc là `(created_by, name)`, và hai hàng này có `created_by`
    khác nhau. Tra trùng theo actor thì test đỏ ở đây — đúng chỗ nó phải đỏ.
    """
    r = await client_member.post("/api/v1/workspaces", json={"name": "Ws Của Member"})
    assert r.status_code == 201, r.text

    r = await client_member.patch("/api/v1/workspaces/ws_co_san", json={"name": "Ws Của Member"})
    assert r.status_code == 200, r.text

    async with pool.acquire() as conn:
        ten = await conn.fetchval("SELECT name FROM control.tenants WHERE id = 'ws_co_san'")
    assert ten == "Ws Của Member"


async def test_doi_ten_thanh_chinh_ten_dang_co_tra_200(client_owner: httpx.AsyncClient):
    """Lưu mà không đổi gì là luỹ đẳng, không phải 409.

    Người dùng sửa tên rồi bấm Lưu hai lần — lần thứ hai không được là một lỗi.
    Câu tra trùng phải loại chính hàng đang sửa ra khỏi phép so.
    """
    r = await client_owner.patch("/api/v1/workspaces/ws_co_san", json={"name": "Ws Có Sẵn"})
    assert r.status_code == 200, r.text


async def test_sua_workspace_khac_tra_403(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """Phiên đang ở `ws_co_san`; `ws_co_san2` là của người khác."""
    r = await client_owner.patch("/api/v1/workspaces/ws_co_san2", json={"name": "Ws Chiếm Đoạt"})
    assert r.status_code == 403, r.text

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT name FROM control.tenants WHERE id = 'ws_co_san2'") == "Ws Có Sẵn"


async def test_ten_toan_khoang_trang_tra_422(client_owner: httpx.AsyncClient):
    """`min_length=1` một mình KHÔNG chặn được "   " — nó dài 3 ký tự.

    Không chặn thì tên workspace thành chuỗi rỗng sau `strip()`, và switcher hiện
    một dòng không có chữ nào.
    """
    r = await client_owner.patch("/api/v1/workspaces/ws_co_san", json={"name": "   "})
    assert r.status_code == 422, r.text


# ─── Xoá cứng ───────────────────────────────────────────────────────────────


async def test_xoa_tra_204_va_xoa_han_hang(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """④ — không còn `lifecycle='closed'`, hàng biến mất hẳn."""
    assert (await client_owner.post("/api/v1/workspaces", json={"name": "Ws Thứ Hai"})).status_code == 201

    r = await client_owner.delete("/api/v1/workspaces/ws_co_san")
    assert r.status_code == 204, r.text

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.tenants WHERE id = 'ws_co_san'") == 0


async def test_xoa_cuon_theo_du_lieu_cua_workspace(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """④ — cascade, chứ không phải một danh sách `DELETE` chép tay ở tầng app.

    Đo trên BA bảng thuộc ba hạng khác nhau: `memberships` (control-plane quyết định
    quyền) · `tenant_verticals` (cấu hình control-plane) · `projects` (dữ liệu nghiệp
    vụ dưới RLS). Một hàng sót ở bảng đầu là người dùng vẫn "thuộc" một workspace
    không tồn tại; sót ở bảng cuối là dữ liệu khách còn nằm trong DB sau khi đã hứa
    xoá.
    """
    assert (await client_owner.post("/api/v1/workspaces", json={"name": "Ws Thứ Hai"})).status_code == 201
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)
                    VALUES ('ws_co_san', 'WS-CANARY', 'Dự án chim báo bão', 'draft')"""
        )

    assert (await client_owner.delete("/api/v1/workspaces/ws_co_san")).status_code == 204

    async with pool.acquire() as conn:
        for bang, dieu_kien in (
            ("control.memberships", "tenant_id = 'ws_co_san'"),
            ("control.tenant_verticals", "tenant_id = 'ws_co_san'"),
            ("tenant_data.projects", "tenant_id = 'ws_co_san'"),
        ):
            con = await conn.fetchval(f"SELECT count(*) FROM {bang} WHERE {dieu_kien}")  # noqa: S608
            assert con == 0, f"{bang} còn {con} hàng — FK ON DELETE CASCADE không phủ bảng này?"


async def test_xoa_ghi_nhat_ky_song_sot_cascade(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """⑤ — BÀI QUAN TRỌNG NHẤT của nhóm này.

    `audit_log.tenant_id` là FK cascade tới `control.tenants`, nên `nhat_ky.ghi()`
    (có tenant) sẽ ghi một dòng rồi tự xoá nó trong CÙNG câu `DELETE` — xoá xong là
    không còn dấu vết nào rằng workspace từng tồn tại. Đổi `ghi_he_thong` thành
    `ghi` ở `service.xoa` thì bài này đỏ, và nó đỏ TRƯỚC khi ai đó cần tra nhật ký
    thật để trả lời "ai xoá workspace của tôi".
    """
    assert (await client_owner.post("/api/v1/workspaces", json={"name": "Ws Thứ Hai"})).status_code == 201
    assert (await client_owner.delete("/api/v1/workspaces/ws_co_san")).status_code == 204

    async with pool.acquire() as conn:
        hang = await conn.fetchrow(
            """SELECT tenant_id, actor, chi_tiet FROM control.audit_log
                WHERE hanh_dong = 'workspace.xoa' AND chi_tiet->>'id' = 'ws_co_san'"""
        )
    assert hang is not None, "không còn dòng nhật ký nào — nó bị cascade xoá cùng workspace"
    assert hang["tenant_id"] is None, "dòng mang tenant_id thì nó nằm TRONG cascade và sẽ biến mất"
    assert hang["actor"] == "u_ws_owner"
    # Tên phải nằm trong nhật ký: sau khi xoá, không còn hàng nào để tra id → tên.
    # Một dòng chỉ có id là dòng không trả lời được câu người ta mở nhật ký ra để hỏi.
    assert "Ws Có Sẵn" in hang["chi_tiet"]


async def test_xoa_cung_xoa_role_postgres_cua_pod(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """⑥ — role `agent_<id>` là một trong ba tài nguyên NGOÀI cascade.

    Để lại role nghĩa là mật khẩu Postgres của pod cũ vẫn đăng nhập được, VÀ ngày
    ai đó tạo lại một workspace trùng id thì `create_agent_role` gặp role đã tồn tại.
    """
    assert (await client_owner.post("/api/v1/workspaces", json={"name": "Ws Thứ Hai"})).status_code == 201
    async with pool.acquire() as conn:
        await conn.execute("SELECT control.dat_mat_khau_agent($1, $2)", "ws_co_san", "x" * 43)
        assert await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'agent_ws_co_san'")

    assert (await client_owner.delete("/api/v1/workspaces/ws_co_san")).status_code == 204

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM pg_roles WHERE rolname = 'agent_ws_co_san'") == 0


async def test_xoa_xong_bien_mat_khoi_me_va_phien_chuyen_sang_ws_khac(client_owner: httpx.AsyncClient):
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Thứ Hai"})
    id_moi = r.json()["id"]

    assert (await client_owner.delete("/api/v1/workspaces/ws_co_san")).status_code == 204

    me = (await client_owner.get("/api/v1/me")).json()
    assert [w["id"] for w in me["workspaces"]] == [id_moi]
    assert me["currentWorkspaceId"] == id_moi, (
        "phiên phải rời workspace vừa xoá ngay trong request xoá — để nguyên thì "
        "request kế tiếp 403 và FE không có gì để hiện"
    )


async def test_xoa_workspace_cuoi_cung_tra_409(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """③ — `u_ws_owner` chỉ có đúng `ws_co_san`.

    Khẳng định hàng CÒN NGUYÊN, không chỉ khẳng định mã lỗi: chặn mà vẫn xoá thì tệ
    hơn không chặn, và với xoá cứng thì không có đường lùi nào.
    """
    r = await client_owner.delete("/api/v1/workspaces/ws_co_san")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "WORKSPACE_CUOI_CUNG"

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.tenants WHERE id = 'ws_co_san'") == 1


async def test_xoa_workspace_khac_tra_403(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    r = await client_owner.delete("/api/v1/workspaces/ws_co_san2")
    assert r.status_code == 403, r.text

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.tenants WHERE id = 'ws_co_san2'") == 1


# ─── Phiên còn trỏ vào workspace đã biến mất ────────────────────────────────


async def test_workspace_da_xoa_thi_request_bi_403_noi_dung_ly_do(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """`require()` phải nói ĐÚNG lý do, không phải "vai trò của bạn thiếu quyền".

    Sau xoá cứng thì `memberships` cũng biến mất, nên phép kiểm `action not in
    q.actions` sẵn có ĐÃ trả 403 rồi — nhưng với thông điệp nói về vai trò, tức
    người dùng đi xin thêm quyền cho một workspace không còn tồn tại. Nhánh
    `tenant_lifecycle IS NULL` đứng TRƯỚC nó để câu trả lời là sự thật.
    """
    await _xoa_trong_db(pool, "ws_co_san")

    r = await client_owner.get("/api/v1/members")
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "WORKSPACE_DA_DONG"


async def test_khong_doi_duoc_vao_workspace_da_xoa(client_member: httpx.AsyncClient, pool: asyncpg.Pool):
    """`POST /me/workspace` khai `require(None, ...)` nên `require()` không che nó."""
    r = await client_member.post("/api/v1/workspaces", json={"name": "Ws Của Member"})
    id_moi = r.json()["id"]
    assert (await client_member.post("/api/v1/me/workspace", json={"workspaceId": id_moi})).status_code == 200

    await _xoa_trong_db(pool, "ws_co_san")

    r = await client_member.post("/api/v1/me/workspace", json={"workspaceId": "ws_co_san"})
    assert r.status_code == 403, r.text


async def test_me_tu_chuyen_khi_phien_tro_vao_workspace_da_xoa(client_owner: httpx.AsyncClient, pool: asyncpg.Pool):
    """Tab thứ hai — và mọi THÀNH VIÊN KHÁC đang mở workspace lúc Quản trị bấm xoá.

    Phiên của họ vẫn trỏ vào `ws_co_san`, còn `liet_ke_workspace()` đã thôi trả nó
    về. Không tự chữa thì `currentWorkspaceId` chỉ vào một id không có trong
    `workspaces`, và `SessionReady` của FE ném "Phiên không có workspace nào" —
    một màn trắng cho người chẳng bấm gì cả.
    """
    r = await client_owner.post("/api/v1/workspaces", json={"name": "Ws Thứ Hai"})
    id_moi = r.json()["id"]

    await _xoa_trong_db(pool, "ws_co_san")

    me = (await client_owner.get("/api/v1/me")).json()
    assert me["currentWorkspaceId"] == id_moi
    assert [w["id"] for w in me["workspaces"]] == [id_moi]


# ─── Dọn ba kho NGOÀI cascade ────────────────────────────────────────────────


async def test_don_ha_tang_khong_bao_loi_khi_chua_tung_cap_phat(pool: asyncpg.Pool, to_chuc_ws):
    """«Chưa từng cấp phát» là đường THƯỜNG, không phải thất bại.

    Đây là bug đo được trên stack thật, không phải ca giả định: phần lớn workspace
    chưa bao giờ có pod, nên không có role `agent_<id>`, không có access key
    `agent-<id>` trên MinIO, và không có collection Qdrant nào. Bản đầu của
    `xoa_khoa_kho_tep` để `MinioAdmin.user_remove` ném 404 `XMinioAdminNoSuchUser`
    ra ngoài, nên MỌI lượt xoá workspace ghi một dòng `ERROR` nói rằng credential
    có thể còn sống — trong khi nó chưa từng tồn tại. Một cảnh báo kêu ở mọi lượt
    bình thường là một cảnh báo người trực học cách bỏ qua, và đúng lúc nó kêu thật
    thì không ai đọc.

    Bài này khẳng định báo cáo KHÔNG mang khoá `loi_*` nào. Nó cũng là bài duy nhất
    canh việc ba bước dọn ĐỘC LẬP với nhau: gộp chúng vào một `try` thì một 404 của
    MinIO che luôn kết quả của hai bước kia.
    """
    bao_cao = await service.don_ha_tang_ngoai(pool, "ws_co_san")

    loi = {k: v for k, v in bao_cao.items() if k.startswith("loi_")}
    assert not loi, f"dọn hạ tầng của một workspace chưa cấp phát không được báo lỗi: {loi}"
    assert bao_cao["role"] is False, "chưa cấp phát thì không có role nào để xoá"
    assert bao_cao["khoa_kho_tep"] is False, "chưa cấp phát thì không có access key nào để gỡ"
