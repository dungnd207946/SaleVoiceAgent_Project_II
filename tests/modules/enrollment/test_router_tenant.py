"""Ba endpoint `/agent/keys` qua app THẬT — đường owner workspace tự phát khoá.

Điều bộ test này bảo vệ, theo thứ tự quan trọng:

  1. CÁCH LY TENANT. `control.agent_keys` KHÔNG có RLS (repo.py:6), nên chỗ duy
     nhất chặn "người workspace A đổi trạng thái khoá của workspace B" là
     `p.tenant_id` ở service. Nếu cổng đó hỏng thì không gì khác bắt được.
  2. Khoá thô CÓ rời khỏi endpoint liệt kê (`GET /agent/keys`, từ `0918`) — có
     chủ đích, xem `contracts.KhoaOut`. Test dưới canh chiều NGƯỢC: khoá tạo
     ĐÚNG tenant thì thấy được `api_key` của chính nó, KHÔNG thấy của tenant khác.
  3. Cổng quyền là action thứ 13, không phải "đã đăng nhập là được".

Fixture `client`/`client_admin`/`nguoi_dung`/`vai_tro_hep` và helper `_vao` sống
ở `conftest.py` (không phải ở đây) — `test_feedback.py` dùng chung đúng ba cổng
`/agent/keys` này để dựng khoá thật, nên fixture PHẢI ở conftest để pytest-discover
cho cả hai file mà không phải import chéo (import một fixture từ file test khác
vào tên tham số cùng tên bị ruff coi là redefine — F811).

TIỀN TỐ `u_ak_` cho mọi user fixture dựng: câu dọn cuối dùng `LIKE 'u\\_ak\\_%'`.
"""

from portal.core.auth.actions import ACTIONS
from tests.modules.enrollment.conftest import EMAIL_ADMIN, EMAIL_THUONG, TENANT_A, TENANT_B, _vao

GOC = "/api/v1/agent"


# ─── Tạo khoá ─────────────────────────────────────────────────────────────────


async def test_tao_khoa_khi_chua_co_deployment_thi_tu_cap_phat(client_admin):
    """Nhánh chính của demo: workspace trắng, bấm một nút, ra khoá dùng được.

    `hai_tenant` xoá sạch `deployments` ở đầu mỗi test nên đây đúng là nhánh
    "chưa có deployment" → `cap_phat` chạy, không phải `_phat_khoa`.
    """
    r = await client_admin.post(f"{GOC}/keys", json={"label": "Pod chat prod"})
    assert r.status_code == 201, r.text
    body = r.json()

    assert body["api_key"].startswith("ody_ag_")
    assert body["endpoint_chat_url"] == f"wss://{TENANT_A}.agents-dev.noble.vn/v1/chat"
    assert body["endpoint_voice_url"] == f"wss://{TENANT_A}.agents-dev.noble.vn/v1/voice"
    assert body["key_prefix"] == body["api_key"][:12]


async def test_tao_khoa_lan_hai_khong_cap_phat_lai(client_admin, pool):
    """Khoá thứ hai đi nhánh `_phat_khoa`, KHÔNG chạy lại `cap_phat`.

    Trước `0941` bài này đếm hàng `control.deployments` (phải đúng 1). Bảng đã bỏ, nên
    dấu vết của "đã chạy cap_phat mấy lần" chuyển sang nhật ký: `cap_phat` ghi
    `agent.cap_phat`, `_phat_khoa` chỉ ghi `agent.phat_khoa`. Hai lượt bấm ⇒ đúng MỘT
    dòng cấp phát và HAI dòng phát khoá.

    Vì sao vẫn đáng canh: nhánh sai làm mỗi lần xoay khoá chạy lại `dat_mat_khau_role`
    — thao tác idempotent nhưng chạm hạ tầng thật, và nó là đường duy nhất đặt lại mật
    khẩu Postgres của tenant.
    """
    await client_admin.post(f"{GOC}/keys", json={})
    await client_admin.post(f"{GOC}/keys", json={})

    async def _dem(hanh_dong: str) -> int:
        return await pool.fetchval(
            "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = $2",
            TENANT_A,
            hanh_dong,
        )

    assert await _dem("agent.cap_phat") == 1
    assert await _dem("agent.phat_khoa") == 2

    r = await client_admin.get(f"{GOC}/keys")
    assert len(r.json()["keys"]) == 2


async def test_khoa_vua_tao_lay_runtime_credentials_duoc_that(client_admin):
    """Cổng end-to-end: khoá do UI phát PHẢI đổi được credential ở /runtime-credentials.

    Không có test này thì cả tính năng có thể xanh hết mà khoá vẫn vô dụng với
    bên agent — và đó chính là thứ người dùng cần.
    """
    khoa = (await client_admin.post(f"{GOC}/keys", json={})).json()["api_key"]
    r = await client_admin.post(f"{GOC}/runtime-credentials", headers={"Authorization": f"Bearer {khoa}"})
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == TENANT_A


async def test_nhan_qua_dai_thi_422(client_admin):
    r = await client_admin.post(f"{GOC}/keys", json={"label": "x" * 61})
    assert r.status_code == 422


async def test_gui_them_truong_la_thi_422(client_admin):
    """`extra="forbid"`: gửi `tenant_id` phải bị TỪ CHỐI, không bị làm ngơ. Làm
    ngơ là để người gọi tưởng mình chọn được tenant."""
    r = await client_admin.post(f"{GOC}/keys", json={"label": "x", "tenant_id": TENANT_B})
    assert r.status_code == 422


async def test_s3_rong_van_phat_duoc_khoa_va_audit_ghi_ro(client_admin, monkeypatch, pool):
    """Tái hiện sự cố production 2026-08-05: env chép từ .env.example để trống
    S3_ACCESS_KEY/S3_SECRET_KEY → StaticProvider ném "Access key must not be
    empty" ngay lúc FastAPI dựng dependency `lay_ha_tang` → POST 500 câm (GET
    vẫn 200 vì không cần MinIO — đúng triệu chứng đánh lạc hướng).

    Hành vi chốt với người vận hành: khoá KHÔNG cần kho tệp — S3 rỗng thì vẫn
    phát khoá, chỉ bước cấp access key kho tệp bị bỏ qua, và việc bỏ qua PHẢI
    đọc được từ audit log (`kho_tep: false`), không im lặng.
    """
    monkeypatch.setenv("S3_ACCESS_KEY", "")
    monkeypatch.setenv("S3_SECRET_KEY", "")

    r = await client_admin.post(f"{GOC}/keys", json={"label": "khong can s3"})
    assert r.status_code == 201, r.text
    assert r.json()["api_key"].startswith("ody_ag_")

    chi_tiet = await pool.fetchval(
        """SELECT chi_tiet FROM control.audit_log
            WHERE tenant_id = $1 AND hanh_dong = 'agent.cap_phat'
            ORDER BY luc DESC LIMIT 1""",
        TENANT_A,
    )
    assert '"kho_tep": false' in chi_tiet, chi_tiet

    # Khoá phát trong chế độ thiếu S3 vẫn lấy runtime-credentials được — kho tệp là phần
    # DUY NHẤT bị thiếu, không phải cả đường đấu nối.
    khoa = r.json()["api_key"]
    rb = await client_admin.post(f"{GOC}/runtime-credentials", headers={"Authorization": f"Bearer {khoa}"})
    assert rb.status_code == 200, rb.text


# ─── Liệt kê ──────────────────────────────────────────────────────────────────


async def test_liet_ke_co_khoa_tho_dung_cua_chinh_no(client_admin):
    """Từ `0918`: `GET /agent/keys` trả `api_key` — CÓ CHỦ Ý, xem `contracts.KhoaOut`.
    Khoá vừa tạo phải liệt kê lại đúng giá trị thô đó, không phải rỗng/None."""
    tao = (await client_admin.post(f"{GOC}/keys", json={"label": "n"})).json()

    r = await client_admin.get(f"{GOC}/keys")
    assert r.status_code == 200
    hang = next(k for k in r.json()["keys"] if k["id"] == tao["id"])
    assert hang["api_key"] == tao["api_key"]


async def test_liet_ke_khoa_tho_khong_lo_sang_tenant_khac(client_admin, client):
    """Cách ly tenant PHẢI giữ đúng cho trường mới này: khoá thô của workspace A
    không được xuất hiện khi cùng người xem sang workspace B."""
    tao = (await client_admin.post(f"{GOC}/keys", json={"label": "n"})).json()

    await _vao(client, EMAIL_ADMIN, TENANT_B)
    r = await client.get(f"{GOC}/keys")
    assert r.status_code == 200
    assert tao["api_key"] not in r.text


async def test_liet_ke_rong_van_tra_endpoint_url(client_admin):
    """Trạng thái rỗng vẫn phải bàn giao được endpoint — đó là lý do
    `DanhSachKhoaOut` bọc list trong một object thay vì trả list trần."""
    r = await client_admin.get(f"{GOC}/keys")
    assert r.status_code == 200
    body = r.json()
    assert body["keys"] == []
    assert body["endpoint_chat_url"] == f"wss://{TENANT_A}.agents-dev.noble.vn/v1/chat"
    assert body["endpoint_voice_url"] == f"wss://{TENANT_A}.agents-dev.noble.vn/v1/voice"


async def test_khoa_tat_van_hien_voi_status_inactive(client_admin):
    """Từ endpoint hai chiều (2026-08-12): khoá TẮT không còn biến mất khỏi
    danh sách — nó phải hiện lại để bật được, đúng mô hình Anthropic Admin API
    mà FE đã định trước (`ThuHoiKhoaDialog.tsx`)."""
    tao = (await client_admin.post(f"{GOC}/keys", json={})).json()

    r = await client_admin.post(f"{GOC}/keys/{tao['id']}", json={"status": "inactive"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "inactive"
    assert r.json()["revoked_at"] is not None

    hang = next(k for k in (await client_admin.get(f"{GOC}/keys")).json()["keys"] if k["id"] == tao["id"])
    assert hang["status"] == "inactive"
    assert hang["revoked_at"] is not None


async def test_bat_lai_khoa_da_tat(client_admin):
    tao = (await client_admin.post(f"{GOC}/keys", json={})).json()
    await client_admin.post(f"{GOC}/keys/{tao['id']}", json={"status": "inactive"})

    r = await client_admin.post(f"{GOC}/keys/{tao['id']}", json={"status": "active"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    assert r.json()["revoked_at"] is None


async def test_status_sai_gia_tri_thi_422(client_admin):
    """Khoá không có vòng đời lưu trữ — `archived`/`expired` của Anthropic
    không có nghĩa ở đây (contracts.DatTrangThaiKhoaIn)."""
    tao = (await client_admin.post(f"{GOC}/keys", json={})).json()
    r = await client_admin.post(f"{GOC}/keys/{tao['id']}", json={"status": "archived"})
    assert r.status_code == 422


async def test_khoa_chua_dung_thi_last_used_at_la_null(client_admin):
    """FE phân biệt "Chưa dùng" với một giá trị thời gian. Gộp hai thứ đó thành
    chuỗi rỗng là làm mất thông tin người vận hành cần."""
    await client_admin.post(f"{GOC}/keys", json={"label": "moi"})
    hang = (await client_admin.get(f"{GOC}/keys")).json()["keys"][0]
    assert hang["last_used_at"] is None
    assert hang["label"] == "moi"


# ─── Xoay khoá ─────────────────────────────────────────────────────────────────


async def test_xoay_khoa_giu_nguyen_nhan_va_tra_khoa_moi(client_admin):
    tao = (await client_admin.post(f"{GOC}/keys", json={"label": "Pod chat prod"})).json()

    r = await client_admin.post(f"{GOC}/keys/{tao['id']}/rotate")
    assert r.status_code == 201, r.text
    body = r.json()

    assert body["id"] != tao["id"]
    assert body["api_key"] != tao["api_key"]
    assert body["api_key"].startswith("ody_ag_")
    assert body["key_prefix"] == body["api_key"][:12]

    hang_moi = next(k for k in (await client_admin.get(f"{GOC}/keys")).json()["keys"] if k["id"] == body["id"])
    assert hang_moi["label"] == "Pod chat prod"


async def test_xoay_khoa_thu_hoi_khoa_cu(client_admin, pool):
    tao = (await client_admin.post(f"{GOC}/keys", json={})).json()
    await client_admin.post(f"{GOC}/keys/{tao['id']}/rotate")

    hang_cu = next(k for k in (await client_admin.get(f"{GOC}/keys")).json()["keys"] if k["id"] == tao["id"])
    assert hang_cu["status"] == "inactive"
    assert hang_cu["revoked_at"] is not None

    dem = await pool.fetchval(
        "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'agent.xoay_khoa'",
        TENANT_A,
    )
    assert dem == 1


async def test_khoa_moi_tu_xoay_dung_duoc_khoa_cu_thi_khong(client_admin):
    """Đúng lý do tính năng tồn tại: khoá mới thay được khoá cũ ngay, khoá cũ
    ngừng mở được `/runtime-credentials` từ đây."""
    tao = (await client_admin.post(f"{GOC}/keys", json={})).json()
    moi = (await client_admin.post(f"{GOC}/keys/{tao['id']}/rotate")).json()

    r_moi = await client_admin.post(f"{GOC}/runtime-credentials", headers={"Authorization": f"Bearer {moi['api_key']}"})
    assert r_moi.status_code == 200, r_moi.text

    r_cu = await client_admin.post(f"{GOC}/runtime-credentials", headers={"Authorization": f"Bearer {tao['api_key']}"})
    assert r_cu.status_code == 401, r_cu.text


async def test_xoay_khoa_khong_ton_tai_thi_404(client_admin):
    r = await client_admin.post(f"{GOC}/keys/999999999/rotate")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


# ─── Cách ly tenant — phần quan trọng nhất ────────────────────────────────────


async def test_khong_doi_duoc_trang_thai_khoa_cua_workspace_khac(client, pool):
    """CỔNG QUAN TRỌNG NHẤT CỦA CẢ MODULE NÀY.

    `control.agent_keys` không có RLS. Chỗ duy nhất chặn là `p.tenant_id` ở
    `dat_trang_thai_khoa_cua_tenant`. Nếu ai đó "đơn giản hoá" nó thành
    `service.dat_trang_thai_khoa(pool, key_id, ...)` thì mọi test khác vẫn xanh
    và workspace A đổi được trạng thái khoá của workspace B.

    Cùng một phiên, đổi workspace hai lần — đúng cách một người thật làm được.
    """
    await _vao(client, EMAIL_ADMIN, TENANT_B)
    khoa_b = (await client.post(f"{GOC}/keys", json={"label": "cua B"})).json()

    r = await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT_A})
    assert r.status_code == 200, r.text

    r = await client.post(f"{GOC}/keys/{khoa_b['id']}", json={"status": "inactive"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"

    con_song = await pool.fetchval("SELECT revoked_at IS NULL FROM control.agent_keys WHERE id = $1", khoa_b["id"])
    assert con_song is True, "khoá của B phải còn sống sau khi A thử đổi trạng thái"


async def test_khong_xoay_duoc_khoa_cua_workspace_khac(client, pool):
    """Cùng cổng quan trọng nhất, cho đường xoay khoá: workspace A không được
    xoay (và qua đó thu hồi) khoá của workspace B."""
    await _vao(client, EMAIL_ADMIN, TENANT_B)
    khoa_b = (await client.post(f"{GOC}/keys", json={"label": "cua B"})).json()

    r = await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT_A})
    assert r.status_code == 200, r.text

    r = await client.post(f"{GOC}/keys/{khoa_b['id']}/rotate")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"

    con_song = await pool.fetchval("SELECT revoked_at IS NULL FROM control.agent_keys WHERE id = $1", khoa_b["id"])
    assert con_song is True, "khoá của B phải còn sống sau khi A thử xoay"

    dong_moi_nao = await pool.fetchval("SELECT count(*) FROM control.agent_keys WHERE tenant_id = $1", TENANT_B)
    assert dong_moi_nao == 1, "A không được phép tạo ra một khoá mới trong tenant B"


async def test_khoa_khong_ton_tai_va_khoa_cua_tenant_khac_cung_cau_chu(client, pool):
    """Phân biệt hai nhánh là cho không một máy dò id khoá của mọi workspace."""
    await _vao(client, EMAIL_ADMIN, TENANT_B)
    khoa_b = (await client.post(f"{GOC}/keys", json={})).json()
    await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT_A})

    cua_b = await client.post(f"{GOC}/keys/{khoa_b['id']}", json={"status": "inactive"})
    khong_co = await client.post(f"{GOC}/keys/999999999", json={"status": "inactive"})

    assert cua_b.status_code == khong_co.status_code == 404
    assert cua_b.json()["error"]["code"] == khong_co.json()["error"]["code"]


async def test_liet_ke_chi_thay_khoa_cua_workspace_hien_tai(client):
    await _vao(client, EMAIL_ADMIN, TENANT_B)
    khoa_b = (await client.post(f"{GOC}/keys", json={"label": "cua B"})).json()
    await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT_A})
    await client.post(f"{GOC}/keys", json={"label": "cua A"})

    body = (await client.get(f"{GOC}/keys")).json()
    assert [k["label"] for k in body["keys"]] == ["cua A"]
    assert all(k["id"] != khoa_b["id"] for k in body["keys"])


# ─── Cổng quyền ───────────────────────────────────────────────────────────────


async def test_chua_dang_nhap_thi_401(client):
    assert (await client.get(f"{GOC}/keys")).status_code == 401


async def test_thieu_workspace_admin_thi_403(client, vai_tro_hep):
    """Đăng nhập được, thuộc workspace, nhưng vai trò không có action thứ 13.

    Ba endpoint phải chặn CẢ BA — quên khai `require` ở một cái là một đường đọc
    khoá bằng quyền của người xem.
    """
    await _vao(client, EMAIL_THUONG, TENANT_A)

    assert (await client.get(f"{GOC}/keys")).status_code == 403
    assert (await client.post(f"{GOC}/keys", json={})).status_code == 403
    assert (await client.post(f"{GOC}/keys/1", json={"status": "inactive"})).status_code == 403


def test_action_dung_la_thu_muoi_ba():
    """Neo lựa chọn action vào PQ_01. Nhãn của `workspace.admin` là "Khoá API ·
    Thành viên · Cài đặt workspace" — tính năng này thuộc đúng nhóm đó, không phải
    `agent_config.*` (nhóm 10-12 là cấu hình nội dung agent, không phải đấu nối)."""
    assert ACTIONS.WORKSPACE_ADMIN == "workspace.admin"
