"""Schema control + hàm current_tenant. M1 tạo 3 bảng lõi + jobs (hạ tầng chung) — module sau tự tạo bảng của nó."""

import pytest

pytestmark = pytest.mark.integration

# Quan hệ trong schema `control` mà M1 sở hữu. MỖI migration của M1 thêm bảng thì
# thêm một dòng vào đây kèm lý do — danh sách này là thứ giữ lời hứa "M1 không
# tạo bảng của module khác" (users/memberships -> M2a; config_drafts/
# config_versions -> M3; `deployments` đã bỏ ở 0941). Assert bằng == chứ không phải >= : nếu một
# bảng của module khác lọt vào `control`, test này phải đỏ.
#
# Gồm CẢ VIEW, vì phép quét bên dưới là pg_class chứ không phải pg_tables: pg_tables
# bỏ sót view, nên một view `control` do module sau thêm — kể cả view lộ dữ liệu
# tenant — sẽ lọt qua phép so `==` mà không ai thấy. Đúng khiếm khuyết đã vá ở
# tests/isolation/test_role_privileges.py, ở đây thì còn sót lại.
M1_OWNED_CONTROL_TABLES = {
    "tenants",  # 0002 — neo danh tính
    "tenant_verticals",  # 0002
    # "field_policy_live" (0002) đã DROP ở 0959 — cơ chế gate cột mồ côi từ
    # 0917 (view agent_api tiêu thụ nó đã xoá), quyết định sản phẩm đảo ở 0400.
    "jobs",  # 0006 — hàng đợi job dùng chung
    "jobs_stuck",  # 0006 — VIEW giám sát: job running > 15 phút
    "agent_heartbeats",  # 0007 — chiều GHI của seam agent (chiều ĐỌC nay là tenant_data thẳng, từ 0917)
}

# Quan hệ `control` mà M2a sở hữu (migration 0100-0101).
#
# GIỮ HAI SET RIÊNG, KHÔNG GỘP MỘT: phép so `==` vẫn là cổng, và "ai sở hữu bảng
# nào" vẫn đọc được từ file này. Gộp một set là mất đúng thông tin mà cổng này
# tồn tại để giữ. Module sau (M3, M7) thêm set của nó theo đúng khuôn này.
M2A_OWNED_CONTROL_TABLES = {
    "users",  # 0100 — neo danh tính người
    "memberships",  # 0101 — người × workspace × vai trò; NGUỒN của tenant_id
}

# Quan hệ `control` mà tầng tổ chức sở hữu (migration 0102) và M2b (0103).
M2B_OWNED_CONTROL_TABLES = {
    # 0103 — thư mời một-lần. Ở `control` chứ không `tenant_data` vì nó tồn tại
    # TRƯỚC khi user có tenant nào, nên đặt dưới RLS của tenant là vòng tròn (cùng
    # lý lẽ 0101 đã ghi cho memberships). Lưu sha256(token), không lưu token thô.
    "invites",
}

# Quan hệ `control` mà M3 sở hữu (migration 0200).
# `config_drafts`/`config_versions` (0200) và `config_live` (0904) DROP ở `0966`.
M3_OWNED_CONTROL_TABLES = {
    "audit_log",  # 0201 — nhật ký; M8 sẽ tiếp quản, xem header của migration
}

# Quan hệ `control` mà M10 sở hữu (migration 0900) — đấu nối pod agent ngoài.
M10_OWNED_CONTROL_TABLES = {
    "agent_keys",  # 0900 — api_key của deployment; lưu sha256, KHÔNG lưu khoá thô
    "agent_credentials",  # 0900 — chỉ `secret_version`; bí mật được suy dẫn, không lưu
}

# Quan hệ `control` mà phân quyền động sở hữu (migration 0104).
# Giữ set riêng theo khuôn của 0102/0103: phép so `==` vẫn là cổng, và "ai sở hữu
# bảng nào" vẫn đọc được từ file này.
BANG_0104 = {"actions", "roles", "role_actions"}

# Quan hệ `control` sinh ra để DÙNG CHUNG DB với hệ agent (migration 0904).
# Giữ set riêng chứ không nhét vào M3: bảng này không thuộc M3, và "ai sở hữu bảng nào"
# là thứ duy nhất file này còn đọc được sau khi phép so `==` đã xanh.
BANG_DUNG_CHUNG_AGENT: set[str] = set()
"""`config_live` (0904) từng là bảng duy nhất ở đây — DROP ở `0966`. Giữ set rỗng thay vì
xoá để lịch sử "ai sở hữu bảng nào" còn đọc được."""

# Quan hệ `control` mà module ingest sở hữu (migration 0927) — cổng nạp dữ liệu ngoài.
# Không phải M1-M10 (kiến trúc gốc không có nó): giữ set riêng theo đúng khuôn của
# BANG_0104/BANG_DUNG_CHUNG_AGENT.
BANG_INGEST = {
    "ingest_tokens",  # 0927 — token nạp; lưu chuỗi THÔ có chủ đích, giao diện xem lại được
}

# Quan hệ `control` sinh ra cho ĐĂNG NHẬP GOOGLE (migration 0108). Không phải
# M1-M10 (kiến trúc gốc không có nó), và không thuộc M2a (0100-0101, users/
# memberships) hay M2b (0102-0103, tầng tổ chức/invites): giữ set riêng theo
# đúng khuôn của BANG_0104/BANG_DUNG_CHUNG_AGENT/BANG_INGEST.
BANG_DANG_NHAP_GOOGLE = {
    # 0108 — nối một tài khoản Google với một `control.users`. Khoá là
    # `(provider, subject)` chứ không phải email, vì Google cho đổi email của
    # tài khoản còn `sub` thì bất biến — khớp theo email là để người đổi email
    # mất sạch workspace. Spec: 2026-08-18-dang-nhap-google-oauth-design.md §4.1.
    "identities",
}

CONTROL_TABLES_DA_KHAI = (
    M1_OWNED_CONTROL_TABLES
    | M2A_OWNED_CONTROL_TABLES
    | M2B_OWNED_CONTROL_TABLES
    | M3_OWNED_CONTROL_TABLES
    | M10_OWNED_CONTROL_TABLES
    | BANG_0104
    | BANG_DUNG_CHUNG_AGENT
    | BANG_INGEST
    | BANG_DANG_NHAP_GOOGLE
)


@pytest.fixture(autouse=True)
async def _don_tenant_cua_module(pool):
    """Dọn tenant do module này tạo.

    pg_dsn là fixture scope session — một container Postgres dùng chung cho cả
    lượt chạy. Hàng không dọn sẽ sống tới hết session và đụng fixture của task
    sau. Tiền tố cs_ giới hạn phạm vi dọn đúng module này.
    """
    yield
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cs\\_%'")


async def test_quan_he_control_loi_ton_tai(pool):
    """Đối chiếu với CONTROL_TABLES_DA_KHAI — xem khai báo và lý do ở đầu file."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'control' AND c.relkind IN ('r', 'v', 'm', 'p')
                ORDER BY c.relname"""
        )
    assert {r["relname"] for r in rows} == CONTROL_TABLES_DA_KHAI


def test_cac_set_khong_chong_nhau():
    """Một bảng khai ở hai set là hai module cùng tưởng mình sở hữu nó — và phép
    hợp ở trên sẽ che mất, vì hợp của hai set chồng nhau vẫn ra đúng kết quả.

    So tổng số phần tử thay vì giao từng cặp: thêm set mới thì chỉ phải thêm MỘT
    dòng ở đây, không phải thêm một dòng giao cho mỗi cặp.

    ⚠ Sửa 2026-08-03: bản trước ghi "cổng tự phủ, không phải nhớ thêm dòng nào" —
    KHÔNG đúng, `cac_set` là tuple viết tay. M10 thêm set thứ năm và test này đỏ
    đúng như vậy. Câu chữ đã sửa cho khớp việc phải làm.
    """
    cac_set = (
        M1_OWNED_CONTROL_TABLES,
        M2A_OWNED_CONTROL_TABLES,
        M2B_OWNED_CONTROL_TABLES,
        M3_OWNED_CONTROL_TABLES,
        M10_OWNED_CONTROL_TABLES,
        BANG_0104,
        BANG_DUNG_CHUNG_AGENT,
        BANG_INGEST,
        BANG_DANG_NHAP_GOOGLE,
    )

    assert sum(len(s) for s in cac_set) == len(CONTROL_TABLES_DA_KHAI)


async def test_tenants_khong_co_cot_plan(pool):
    """Hoá đơn không gắn vào khoá cách ly — nó thuộc tầng tổ chức, không thuộc tenant.

    Tầng đó đã bỏ 2026-08-15. Gói cước, nếu có, treo ở một bảng `accounts` mới — thêm
    `plan` vào đây là gắn hoá đơn vào đúng cái khoá mà RLS và agent pod đang dùng.
    """
    async with pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'control' AND table_name = 'tenants'"
        )
    names = {r["column_name"] for r in cols}
    assert names == {"id", "name", "lifecycle", "created_at", "created_by"}


async def test_lifecycle_chi_nhan_ba_gia_tri(pool):
    async with pool.acquire() as conn:
        with pytest.raises(Exception, match="tenants_lifecycle_check"):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, lifecycle, created_by) "
                "VALUES ('cs_x', 'X', 'ready', 'u_seed_test')"
            )


async def test_slug_phai_hop_le_vi_no_di_vao_ten_role(pool):
    """id đi vào tên role agent_<id>, đường dẫn tenants/<id>/, tên collection kb_<id>.

    `an-phu` KHÔNG còn trong danh sách xấu: migration 0911 nới charset cho dấu `-`
    (tenant_id import từ hệ ngoài). Ký tự đầu vẫn phải `[a-z]`, nên `-anphu` vào
    thay chỗ nó — nới charset không nới vị trí.
    """
    async with pool.acquire() as conn:
        for bad in ("Anphu", "-anphu", "1anphu", "an phu", "an;drop", "an.phu"):
            with pytest.raises(Exception, match="tenants_id_check"):
                await conn.execute(
                    "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, 'X', 'u_seed_test')", bad
                )
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_an_phu2', 'OK', 'u_seed_test')"
        )


async def test_current_tenant_lay_tu_guc_khi_role_khong_phai_agent(pool):
    """portal_migrator không khớp ^agent_ nên rơi về GUC app.tenant_id."""
    async with pool.acquire() as conn, conn.transaction():
        assert await conn.fetchval("SELECT portal.current_tenant()") is None
        await conn.execute("SELECT set_config('app.tenant_id', 'anphu', true)")
        assert await conn.fetchval("SELECT portal.current_tenant()") == "anphu"


async def test_current_tenant_chuoi_rong_thanh_null(pool):
    """Fail-closed: GUC rỗng phải ra NULL, không phải chuỗi rỗng khớp tenant_id = ''."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', '', true)")
        assert await conn.fetchval("SELECT portal.current_tenant()") is None


# — ba CHECK của control.field_policy_live (match_op/filterable/enum) đã BỎ
#   cùng bảng ở 0959; các test canh chúng ở đây cũng bỏ theo, không còn gì để
#   canh.
