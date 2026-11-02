"""Fixture dùng chung cho test của module auth.

Gom vào đây vì bốn file test sau đều cần "một user đã đăng nhập, thuộc 2
workspace, có 1 workspace thứ ba mà mình KHÔNG thuộc" — lặp lại ở mỗi file là
bốn chỗ phải sửa khi hình dạng seed đổi.
"""

from dataclasses import dataclass

import httpx
import pytest

from portal.core.auth import password as pw


@pytest.fixture(autouse=True)
def bat_hai_co(monkeypatch):
    """BẬT `USERS_ADMIN_ENABLED` và `ROLES_CRUD_ENABLED` cho cả module auth.

    Hai khối này mất chủ sau khi bỏ `org_role` và bị đóng bằng cờ (mặc định
    `False`, xem `core/config.py` và spec bo-organization §6.2). Nhưng CODE của
    chúng vẫn còn và vẫn phải đúng — bật lại cờ là bật một tính năng đã có, không
    phải viết mới, nên bộ test này phải tiếp tục canh nó.

    Xoá fixture này thì 29 test dưới đây đỏ với `FEATURE_DISABLED` và ta mất toàn
    bộ độ phủ của luồng quản trị user/vai trò — đúng lúc muốn bật lại thì không
    còn gì bảo đảm nó chạy.

    `test_co_dong_cong.py` KHÔNG dùng fixture này (nó `monkeypatch.delenv`): đó là
    chỗ canh chiều ngược lại — mặc định phải TẮT.

    `get_settings()` dựng `Settings()` mới mỗi lần gọi (không lru_cache), nên
    `setenv` là đủ, không cần clear cache nào.
    """
    monkeypatch.setenv("USERS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("ROLES_CRUD_ENABLED", "true")


MAT_KHAU = "mat-khau-that-cua-dang"

# migration 0104 xoá cột `memberships.role` (4 mã cố định), thay bằng `role_id`
# trỏ vào `control.roles` — vai trò giờ do TỪNG tổ chức tự định nghĩa, không còn
# một danh sách 4 giá trị chung. `org` 'noble' đã có 4 vai trò mẫu (trigger +
# backfill của 0104 chạy lúc migration, trước khi test nào tới), nên fixture chỉ
# TRA id theo tên — không tự tạo, tự tạo sẽ vỡ UNIQUE (name).
_MAP_CU = {"admin": "Quản trị", "care": "CSKH", "editor": "Biên tập", "viewer": "Người xem"}


async def _role_id(conn, ma_cu: str) -> str:
    """`ma_cu` là mã cũ (admin·care·editor·viewer, PQ_01 §2.4 — chết ở 0104) —
    fixture giữ nó làm tên tham số quen mắt, dịch sang vai trò mẫu tương ứng
    rồi tra id thật. Dùng LẠI ở nhiều fixture nên viết một lần ở đây."""
    ten = _MAP_CU[ma_cu]
    r = await conn.fetchval("SELECT id FROM control.roles WHERE name = $1", ten)
    assert r is not None, f"migration phải đã seed vai trò mẫu '{ten}'"
    return r


@pytest.fixture
async def ba_workspace(pool):
    """1 user · 3 workspace · 2 membership — cùng hình dạng seed dev (spec §7).

    `cs_haven` tồn tại mà user KHÔNG thuộc: đó là thứ chứng minh phép lọc thật
    sự lọc. Seed đúng những workspace user thuộc thì mọi bug lọc trông như chạy đúng.
    """
    async with pool.acquire() as conn, conn.transaction():
        for tid, ten in [("cs_anphu", "An Phú Land"), ("cs_sunrise", "Sunrise"), ("cs_haven", "Havenly")]:
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')", tid, ten
            )
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ($1, $2, $3, $4)",
            "u_dang",
            "dang@anphuland.vn",
            pw.bam(MAT_KHAU),
            "Trần Hải Đăng",
        )
        # cs_anphu -> Quản trị, cs_sunrise -> CSKH — GIỮ NGUYÊN sự khác nhau
        # giữa hai workspace (review round 2: cho cả hai Quản trị là nới quá
        # tay, mất luôn khả năng bắt hồi quy "cs_sunrise có ÍT quyền hơn"). Đây
        # đúng cùng hình dạng seed dev mà docstring fixture này đã hứa.
        for tid, vai in [("cs_anphu", "admin"), ("cs_sunrise", "care")]:
            r_id = await _role_id(conn, vai)
            await conn.execute(
                "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_dang', $1, $2)",
                tid,
                r_id,
            )
    yield
    async with pool.acquire() as conn, conn.transaction():
        # tenants TRƯỚC users: `tenants.created_by` là FK không CASCADE (0106).
        await conn.execute("DELETE FROM control.tenants WHERE created_by LIKE 'u\\_%' AND created_by <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_%' AND id <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cs\\_%'")


@pytest.fixture
async def dang_nhap_san(app_client: httpx.AsyncClient, ba_workspace) -> httpx.AsyncClient:
    """Client đã có cookie phiên hợp lệ, workspace hiện tại = cs_anphu."""
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    return app_client


# --- M2b -----------------------------------------------------------------


@pytest.fixture
async def owner_dang_nhap(pool, dang_nhap_san: httpx.AsyncClient) -> httpx.AsyncClient:
    """`u_dang` được nâng lên vai trò "Quản trị" SAU khi đã đăng nhập.

    Nâng sau chứ không seed sẵn là cố ý — nó chứng minh luôn một điều spec đã hứa:
    Vai trò đọc từ DB ở MỖI request (BR-Q04), không chốt vào bản ghi phiên. Nếu
    có ngày ai đó cache nó vào Redis thì fixture này đỏ trước khi lỗ hổng ra ngoài.
    """
    async with pool.acquire() as conn:
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute("UPDATE control.memberships SET role_id = $1 WHERE user_id = 'u_dang'", r_admin)
    return dang_nhap_san


@pytest.fixture
async def org_khac(pool):
    """Một workspace mà người dùng của test KHÔNG có membership.

    Trước 2026-08-15 đây là "workspace của một tổ chức THỨ HAI" — thứ chứng minh
    phép lọc org thật sự lọc. Tầng tổ chức đã bỏ, và phép lọc còn lại là
    membership: một workspace không có hàng `memberships` cho người đang gọi thì
    họ không thấy và không vào được. Bất biến mới, cùng vai trò trong test.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_ngoai', 'Ngoài tổ chức', 'u_seed_test')"
        )
    yield "cs_ngoai"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = 'cs_ngoai'")


@pytest.fixture
async def id_vai_tro(pool) -> dict[str, str]:
    """`{'Quản trị': 'r_...', 'CSKH': 'r_...', ...}` — bốn vai trò TOÀN CỤC.

    Quyết định 2026-08-04 (spec §4.0): membership neo vào `roleId`, không còn 4 mã
    cố định — mọi test HTTP gán vai trò cần TRA id thật, không gõ tay một chuỗi.

    Không còn lọc theo org: migration 0105 gỡ `roles.org_id` và đặt `UNIQUE (name)`,
    nên bốn vai trò mẫu là một bộ dùng chung cho mọi workspace.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name, id FROM control.roles")
    return {r["name"]: r["id"] for r in rows}


@pytest.fixture
async def client_viewer(pool, dang_nhap_san: httpx.AsyncClient) -> httpx.AsyncClient:
    """`u_dang` ở `cs_anphu` đổi từ Quản trị sang Người xem SAU khi đã đăng nhập.

    Cùng khuôn `owner_dang_nhap` — đổi vai trò SAU login, không seed sẵn, để chính
    fixture này chứng minh luôn BR-Q04: ma trận đọc từ CSDL mỗi request, không
    chốt vào phiên. Client vẫn còn cookie hợp lệ, workspace hiện tại vẫn `cs_anphu`
    — chỉ có hàng `role_id` bên dưới đổi.
    """
    async with pool.acquire() as conn:
        r_id = await _role_id(conn, "viewer")
        await conn.execute(
            "UPDATE control.memberships SET role_id = $1 WHERE user_id = 'u_dang' AND tenant_id = 'cs_anphu'",
            r_id,
        )
    return dang_nhap_san


@pytest.fixture
async def workspace_cfg(pool):
    """Một workspace trống — DÙNG RIÊNG cho `tests/modules/auth/`.

    ⚠ KHÔNG PHẢI fixture cùng tên ở `tests/modules/config/conftest.py`
    (`cf_anphu`). Fixture đó chỉ re-export qua `tests/modules/agent_seam/`, không
    qua đây — dùng tên `workspace_cfg` trong file test của module `auth` mà
    không khai cục bộ sẽ lỗi "fixture 'workspace_cfg' not found". Đây là chỗ khai
    cục bộ đó (task-4-brief.md dùng nhầm fixture ngoài phạm vi — xem báo cáo).

    Chỉ cần MỘT hàng `control.tenants` hợp lệ: các bài test seam `/members` tự
    chèn user/membership riêng của chúng.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cf_tv', 'CF Thanh Vien', 'u_seed_test')"
        )
    yield "cf_tv"
    async with pool.acquire() as conn, conn.transaction():
        # memberships/CASCADE trước; users cụ thể của từng test tự dọn nếu cần.
        await conn.execute("DELETE FROM control.tenants WHERE id = 'cf_tv'")


@pytest.fixture
async def role_id_bien_tap(pool):
    return await pool.fetchval("SELECT id FROM control.roles WHERE name = 'Biên tập'")


@pytest.fixture
async def role_id_nguoi_xem(pool):
    return await pool.fetchval("SELECT id FROM control.roles WHERE name = 'Người xem'")


THU_DA_GUI: list[dict] = []
"""Hộp thư giả của `mailer_stub` — mỗi thư gửi qua stub được ghi lại một dòng ở
đây. Module-level (không phải trong fixture) vì `test_dang_ky.py` đọc nó bằng
`from tests.modules.auth.conftest import THU_DA_GUI` NGOÀI hàm test, sau khi
request đã chạy xong."""


@pytest.fixture
async def mailer_stub(monkeypatch):
    """Bắt thư thay vì gửi thật. Token thô CHỈ tồn tại trong link, DB chỉ có sha256.

    KHÔNG `autouse=True` (lệch có chủ ý so với brief task-7): `tests/modules/auth/`
    đã có bộ test cho seam `/members` (task trước) canh qua mailer THẬT, và một stub
    autouse trả `True` vô điều kiện sẽ đổi `invitePath` ở MỌI bài trong thư mục, làm
    chúng đỏ vì lý do không liên quan. Chỉ khai fixture thường — bài nào cần đọc
    token thô qua thư thì tự yêu cầu nó.

    ⚠ Bản đầu của docstring này khẳng định mailer «đang tắt trong môi trường test»
    (thiếu SMTP_HOST/SMTP_FROM/PUBLIC_BASE_URL) nên `gui()` luôn trả `False`. ĐỪNG
    TIN CÂU ĐÓ: `Settings` đọc `.env` của repo (`env_file=".env"`, và `get_settings()`
    không cache), nên máy nào có SMTP thật trong `.env` thì các bài KHÔNG dùng fixture
    này sẽ bắt tay SMTP THẬT. Chúng vẫn xanh (gửi được ⇒ `invitePath=None`, gửi hỏng
    ⇒ giữ đường dẫn — cả hai nhánh đều có bài canh), nhưng thư có thể đi thật tới
    địa chỉ trong dữ liệu test.
    """
    THU_DA_GUI.clear()

    async def _gui(*, den, tieu_de, than_text, than_html, anh_nhung=None):
        # `anh_nhung` mặc định None để stub không đòi hơn `mailer.gui` thật; nhưng
        # nó ĐƯỢC GHI LẠI, vì thân HTML trỏ `cid:` tới ảnh đó — router quên chuyển
        # tiếp là thư có ô vuông vỡ, một lỗi không cổng nào khác bắt được.
        token = than_text.split("/invite/")[-1].split()[0] if "/invite/" in than_text else ""
        # `than_text` GHI LẠI cùng lý do `anh_nhung`: `thu_loi_moi_moi` và
        # `thu_loi_moi_da_co` chia CÙNG một `tieu_de` (chỉ khác thân thư) —
        # thiếu `than_text` thì không bài nào phân biệt được ĐÃ GỬI đúng lá thư
        # nào, chỉ biết một thư NÀO ĐÓ đã gửi.
        THU_DA_GUI.append(
            {"den": den, "tieu_de": tieu_de, "token": token, "than_text": than_text, "anh_nhung": anh_nhung}
        )
        return True

    monkeypatch.setattr("portal.core.mailer.gui", _gui)
    monkeypatch.setattr("portal.core.mailer.dang_bat", lambda: True)
    monkeypatch.setattr("portal.core.mailer.url_tuyet_doi", lambda p: f"https://test.local{p}")


@dataclass(frozen=True, slots=True)
class DuLieuQuyen:
    tenant_id: str
    owner_id: str
    viewer_id: str
    editor_id: str
    het_han_id: str
    nguoi_la_id: str
    """User tồn tại nhưng KHÔNG có membership ở tenant này."""
    role_viewer_id: str
    role_editor_id: str


@pytest.fixture
async def du_lieu_quyen(pool):
    """Một workspace đủ năm loại người để kiểm ma trận.

    Dùng workspace RIÊNG (`ws_q`) chứ không mượn dữ liệu seed: test khác sửa seed
    thì test này đỏ vì lý do không liên quan.

    KHÔNG tự tạo vai trò — bốn vai trò mẫu là TOÀN CỤC từ migration 0105 và đã có
    sẵn trước khi test nào chạy. Tự chèn thêm 'Người xem' sẽ vỡ `UNIQUE (name)`.
    Fixture chỉ TRA id theo tên.

    `u_q_owner` giữ tên cũ nhưng nghĩa đã đổi: nó là "Quản trị của workspace này",
    không phải "chủ tổ chức". Nhánh owner trong `doc_quyen()` đã bỏ, nên nó PHẢI
    có membership — không có thì nó là một user 0 quyền và mọi test quản trị đỏ ở
    `require()` với 403, trước khi chạm tới thứ chúng định đo.

    `u_q_la` là user KHÔNG membership — vai trò cũ của `u_q_owner`. Giữ để test
    phân biệt "chưa từng được cấp" với "đã hết hạn" (`u_q_hethan`).
    """
    ten = "ws_q"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by)"
            " VALUES ($1, 'WS Quyền', 'u_seed_test') ON CONFLICT (id) DO NOTHING",
            ten,
        )

        r_viewer = await conn.fetchval("SELECT id FROM control.roles WHERE name='Người xem'")
        r_editor = await conn.fetchval("SELECT id FROM control.roles WHERE name='Biên tập'")
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name='Quản trị'")
        assert r_viewer and r_editor and r_admin, "migration 0104/0105 phải đã seed 4 vai trò mẫu"

        nguoi = [
            ("u_q_owner", "owner"),
            ("u_q_viewer", "member"),
            ("u_q_editor", "member"),
            ("u_q_hethan", "member"),
            ("u_q_la", "member"),
        ]
        for uid, _vai in nguoi:
            await conn.execute(
                """INSERT INTO control.users (id, email, password_hash, name)
                   VALUES ($1, $1||'@q.vn', 'x', $1) ON CONFLICT (id) DO NOTHING""",
                uid,
            )

        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id)"
            " VALUES ('u_q_owner', $1, $2) ON CONFLICT DO NOTHING",
            ten,
            r_admin,
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id)"
            " VALUES ('u_q_viewer', $1, $2) ON CONFLICT DO NOTHING",
            ten,
            r_viewer,
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id)"
            " VALUES ('u_q_editor', $1, $2) ON CONFLICT DO NOTHING",
            ten,
            r_editor,
        )
        await conn.execute(
            """INSERT INTO control.memberships (user_id, tenant_id, role_id, expires_at)
               VALUES ('u_q_hethan', $1, $2, now() - interval '1 day')
               ON CONFLICT DO NOTHING""",
            ten,
            r_editor,
        )

    yield DuLieuQuyen(
        ten,
        "u_q_owner",
        "u_q_viewer",
        "u_q_editor",
        "u_q_hethan",
        "u_q_la",
        r_viewer,
        r_editor,
    )

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", ten)
        await conn.execute(
            "DELETE FROM control.users WHERE id IN ('u_q_owner','u_q_viewer','u_q_editor','u_q_hethan','u_q_la')"
        )
