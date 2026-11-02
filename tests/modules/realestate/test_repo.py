"""Test `repo.py` — CRUD 5 bảng KB BĐS, cascade `status`, gộp `__ALL__`, phân trang
cursor, cách ly chéo tenant qua vai trò runtime thật.

Nguồn sự thật: `docs/build_module_knowledgebase/02` (khung chung) + `02a` (template
`real_estate`). Test tự dựng dữ liệu bằng chính các hàm `chen_*` đang kiểm — không
viết SQL riêng để seed — trừ khi bản thân việc ghi SQL thô là thứ đang test.
"""

import uuid

import asyncpg
import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from portal.modules.realestate import repo
from portal.modules.realestate.contracts import LoiConTro, LoiTruongLa, doc_con_tro, ma_con_tro

pytestmark = pytest.mark.integration

# `control.tenants.org_id` NOT NULL từ migration `0102_organizations` (M2a, NGOÀI
# phạm vi module này) — 'noble' là org mặc định migration đó seed sẵn. Xem cùng
# hằng số ở `test_schema.py`.
_ORG = "noble"


def _tenant_moi() -> str:
    # Tiền tố CHỮ (CHECK id ~ '^[a-z][a-z0-9_]{1,30}$' của control.tenants) + hex
    # ngẫu nhiên để test chạy song song không đụng mã tenant.
    return f"kbr{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def tenant(pool: asyncpg.Pool):
    """Một tenant rỗng — không seed sẵn project/zone/unit (khác `kb_tenant` của
    `test_schema.py`): mỗi test ở đây tự tạo đúng dữ liệu nó cần qua `repo.chen_*`,
    vì chính các hàm đó là đối tượng đang kiểm."""
    tid = _tenant_moi()
    await pool.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", tid)
    yield tid
    await pool.execute("DELETE FROM control.tenants WHERE id = $1", tid)


@pytest.fixture
async def conn(pool: asyncpg.Pool, tenant: str):
    """Kết nối đã SET LOCAL `app.tenant_id` qua `tenant_conn` THẬT (không tự
    `set_config` tay) — nếu `tenant_conn` đổi cách đặt biến thì test phải đỏ."""
    async with tenant_conn(pool, tenant) as c:
        yield c


# ─── CRUD từng thực thể ─────────────────────────────────────────────────────


async def test_du_an_chen_doc_sua_xoa(conn: asyncpg.Connection, tenant: str):
    tao = await repo.chen_du_an(conn, tenant, {"project_code": "P1", "name": "Dự án 1", "region": "HN"})
    assert tao is not None
    assert tao["project_code"] == "P1"
    assert tao["category"] == []  # DEFAULT '{}' — text[] map thẳng sang list, KHÔNG phải chuỗi
    id_ = tao["id"]

    doc = await repo.doc_du_an(conn, id_)
    assert doc is not None
    assert doc["name"] == "Dự án 1"

    sua = await repo.sua_du_an(conn, id_, {"name": "Dự án 1 (sửa)", "category": ["biet_thu", "lien_ke"]})
    assert sua is not None
    assert sua["name"] == "Dự án 1 (sửa)"
    assert sua["category"] == ["biet_thu", "lien_ke"]
    # `>` chứ KHÔNG `>=` (review vòng cuối, Minor F1): test này tồn tại để canh
    # quyết định `clock_timestamp()`-không-`now()` của `repo._upsert` (bài học đã
    # trả giá một lần ở M4a — `now()` trả giờ BẮT ĐẦU giao dịch, nên nhiều lần ghi
    # trong CÙNG một transaction nhận CÙNG một mốc và rào chắn độ tươi hỏng lặng
    # lẽ). `>=` cũng ĐÚNG dưới `now()`, nên nó không thể đỏ khi ai đó đổi ngược
    # lại — một test không thể đỏ thì tệ hơn không có test.
    assert sua["updated_at"] > doc["updated_at"]

    assert await repo.xoa_du_an(conn, id_) is True
    assert await repo.doc_du_an(conn, id_) is None
    assert await repo.xoa_du_an(conn, id_) is False  # xoá lần 2 — không còn gì để xoá


async def test_chen_du_an_trung_ma_tra_none(conn: asyncpg.Connection, tenant: str):
    """`ON CONFLICT (tenant_id, project_code) DO NOTHING` — double-POST cùng mã
    không âm thầm ghi đè, trả `None` để router (Task 4) dịch sang 409."""
    dau = await repo.chen_du_an(conn, tenant, {"project_code": "DUP", "name": "A"})
    assert dau is not None
    trung = await repo.chen_du_an(conn, tenant, {"project_code": "DUP", "name": "B"})
    assert trung is None
    # Dữ liệu KHÔNG bị ghi đè bởi lượt "trùng" — vẫn là "A"
    van_con = await repo.doc_du_an(conn, dau["id"])
    assert van_con is not None
    assert van_con["name"] == "A"


async def test_phan_khu_chen_doc_sua_xoa(conn: asyncpg.Connection, tenant: str):
    await repo.chen_du_an(conn, tenant, {"project_code": "PZ", "name": "P"})
    z = await repo.chen_phan_khu(conn, tenant, {"project_code": "PZ", "zone_code": "Z1", "name": "Zone1"})
    assert z is not None
    assert z["zone_code"] == "Z1"

    doc = await repo.doc_phan_khu(conn, z["id"])
    assert doc is not None and doc["name"] == "Zone1"

    sua = await repo.sua_phan_khu(conn, z["id"], {"name": "Zone1b"})
    assert sua is not None and sua["name"] == "Zone1b"

    assert await repo.xoa_phan_khu(conn, z["id"]) is True


async def test_chen_phan_khu_trung_ma_trong_cung_du_an_tra_none(conn: asyncpg.Connection, tenant: str):
    await repo.chen_du_an(conn, tenant, {"project_code": "PZ2", "name": "P"})
    dau = await repo.chen_phan_khu(conn, tenant, {"project_code": "PZ2", "zone_code": "Z1", "name": "A"})
    assert dau is not None
    trung = await repo.chen_phan_khu(conn, tenant, {"project_code": "PZ2", "zone_code": "Z1", "name": "B"})
    assert trung is None


async def test_can_khong_unique_ma_can_tao_duoc_hai_lan(conn: asyncpg.Connection, tenant: str):
    """`units.unit_code` KHÔNG unique (`02a §4.3`) — `chen_can` LUÔN tạo hàng mới,
    khác `chen_du_an`/`chen_phan_khu` (có ON CONFLICT)."""
    await repo.chen_du_an(conn, tenant, {"project_code": "PU", "name": "P"})
    await repo.chen_phan_khu(conn, tenant, {"project_code": "PU", "zone_code": "ZU", "name": "Z"})
    payload = {"project_code": "PU", "zone_code": "ZU", "unit_code": "U1", "product_type": "chung_cu"}
    u1 = await repo.chen_can(conn, tenant, payload)
    u2 = await repo.chen_can(conn, tenant, payload)
    assert u1["id"] != u2["id"]

    doc = await repo.doc_can(conn, u1["id"])
    assert doc is not None and doc["unit_code"] == "U1"

    sua = await repo.sua_can(conn, u1["id"], {"price_vnd": 5620000000, "floor": 6, "num_floors": 1})
    assert sua is not None
    assert int(sua["price_vnd"]) == 5620000000
    assert sua["floor"] == 6

    assert await repo.xoa_can(conn, u1["id"]) is True
    assert await repo.xoa_can(conn, u2["id"]) is True


async def test_tai_lieu_chen_doc_sua_xoa(conn: asyncpg.Connection, tenant: str):
    await repo.chen_du_an(conn, tenant, {"project_code": "PD", "name": "P"})
    d = await repo.chen_tai_lieu(conn, tenant, {"project_code": "PD", "title": "CSBH", "body": "nội dung"})
    assert d["title"] == "CSBH"

    doc = await repo.doc_tai_lieu(conn, d["id"])
    assert doc is not None and doc["body"] == "nội dung"

    sua = await repo.sua_tai_lieu(conn, d["id"], {"body": "nội dung mới"})
    assert sua is not None and sua["body"] == "nội dung mới"

    assert await repo.xoa_tai_lieu(conn, d["id"]) is True


async def test_media_chen_doc_sua_xoa(conn: asyncpg.Connection, tenant: str):
    await repo.chen_du_an(conn, tenant, {"project_code": "PM", "name": "P"})
    m = await repo.chen_media(
        conn,
        tenant,
        {"project_code": "PM", "content_type": "image", "category": "tong_quan", "media_url": "https://x/1.webp"},
    )
    assert m["media_url"] == "https://x/1.webp"

    doc = await repo.doc_media(conn, m["id"])
    assert doc is not None and doc["category"] == "tong_quan"

    sua = await repo.sua_media(conn, m["id"], {"caption": "Ảnh tổng quan"})
    assert sua is not None and sua["caption"] == "Ảnh tổng quan"

    assert await repo.xoa_media(conn, m["id"]) is True


async def test_chen_truong_la_raise(conn: asyncpg.Connection, tenant: str):
    """Payload có khoá ngoài danh sách trắng `COT_*` — raise, KHÔNG lọc-bỏ-âm-thầm."""
    with pytest.raises(LoiTruongLa):
        await repo.chen_du_an(conn, tenant, {"project_code": "PX", "name": "X", "commission": 5})


async def test_sua_rong_la_no_op_hop_le(conn: asyncpg.Connection, tenant: str):
    """PATCH rỗng — hợp lệ (mọi field của `*_In` sẽ Optional ở Task 4), KHÔNG
    ghép một mệnh đề SET rỗng."""
    tao = await repo.chen_du_an(conn, tenant, {"project_code": "PE", "name": "E"})
    lai = await repo.sua_du_an(conn, tao["id"], {})
    assert lai is not None
    assert lai["name"] == "E"


async def test_sua_xoa_id_khong_ton_tai_tra_none_hoac_false(conn: asyncpg.Connection, tenant: str):
    assert await repo.sua_du_an(conn, 9_999_999_999, {"name": "x"}) is None
    assert await repo.xoa_du_an(conn, 9_999_999_999) is False


# ─── Cascade status (02 §3) ─────────────────────────────────────────────────


async def test_cascade_status_anchor_draft_an_het_con(conn: asyncpg.Connection, tenant: str):
    """Anchor (`projects`) `draft` ⇒ TOÀN BỘ cây con biến mất khỏi kết quả AGENT,
    dù bản thân zone/unit/document/media đã tự `published`. Đọc CHO PORTAL thì
    KHÔNG bị ảnh hưởng — `liet_ke_phan_khu` (không lọc status) vẫn thấy zone."""
    p = await repo.chen_du_an(conn, tenant, {"project_code": "PC", "name": "P", "status": "draft"})
    z = await repo.chen_phan_khu(
        conn, tenant, {"project_code": "PC", "zone_code": "ZC", "name": "Z", "status": "published"}
    )

    assert await repo.liet_ke_phan_khu_cho_agent(conn, "PC") == []
    # Portal vẫn thấy — người dùng phải sửa được bản draft của chính mình
    portal_view = await repo.liet_ke_phan_khu(conn, project_code="PC")
    assert [r["id"] for r in portal_view] == [z["id"]]

    await repo.sua_du_an(conn, p["id"], {"status": "published"})
    sau_publish = await repo.liet_ke_phan_khu_cho_agent(conn, "PC")
    assert [r["id"] for r in sau_publish] == [z["id"]]


async def test_cascade_status_con_draft_an_du_anchor_published(conn: asyncpg.Connection, tenant: str):
    """Chiều ngược lại: anchor `published` nhưng CHÍNH zone `draft` ⇒ agent vẫn
    không thấy zone đó — cascade là AND cả hai chiều, không phải chỉ một chiều."""
    await repo.chen_du_an(conn, tenant, {"project_code": "PC2", "name": "P", "status": "published"})
    z = await repo.chen_phan_khu(
        conn, tenant, {"project_code": "PC2", "zone_code": "ZC2", "name": "Z", "status": "draft"}
    )
    assert await repo.liet_ke_phan_khu_cho_agent(conn, "PC2") == []
    await repo.sua_phan_khu(conn, z["id"], {"status": "published"})
    assert [r["id"] for r in await repo.liet_ke_phan_khu_cho_agent(conn, "PC2")] == [z["id"]]


async def test_cascade_status_ap_dung_cho_can(conn: asyncpg.Connection, tenant: str):
    p = await repo.chen_du_an(conn, tenant, {"project_code": "PCU", "name": "P", "status": "draft"})
    await repo.chen_phan_khu(conn, tenant, {"project_code": "PCU", "zone_code": "ZCU", "name": "Z"})
    u = await repo.chen_can(
        conn,
        tenant,
        {
            "project_code": "PCU",
            "zone_code": "ZCU",
            "unit_code": "UCU",
            "product_type": "chung_cu",
            "status": "published",
        },
    )
    assert await repo.liet_ke_can_cho_agent(conn, "PCU") == []
    await repo.sua_du_an(conn, p["id"], {"status": "published"})
    assert [r["id"] for r in await repo.liet_ke_can_cho_agent(conn, "PCU")] == [u["id"]]


async def test_du_an_cho_agent_chi_thay_ban_published(conn: asyncpg.Connection, tenant: str):
    draft = await repo.chen_du_an(conn, tenant, {"project_code": "PDR", "name": "Draft"})
    assert await repo.du_an_cho_agent(conn, "PDR") is None
    await repo.sua_du_an(conn, draft["id"], {"status": "published"})
    got = await repo.du_an_cho_agent(conn, "PDR")
    assert got is not None and got["project_code"] == "PDR"


# ─── Sentinel `__ALL__` (02 §2, 02a §4b) ────────────────────────────────────


async def test_tai_lieu_cho_agent_gop_ALL(conn: asyncpg.Connection, tenant: str):
    """Truy hồi CHO AGENT gộp `project_code IN {dự_án, "__ALL__"}` — tài liệu cấp
    tenant (`__ALL__`) luôn đi kèm tài liệu riêng của dự án đang hỏi."""
    await repo.chen_du_an(conn, tenant, {"project_code": "PD2", "name": "P", "status": "published"})
    # Row anchor hệ thống `__ALL__` — Task 5 (seed provisioning) sẽ tự seed sẵn
    # mỗi tenant; test này tự tạo vì Task 5 ngoài phạm vi Task 3.
    await repo.chen_du_an(conn, tenant, {"project_code": "__ALL__", "name": "Chung", "status": "published"})

    await repo.chen_tai_lieu(conn, tenant, {"project_code": "PD2", "title": "Rieng", "status": "published"})
    await repo.chen_tai_lieu(conn, tenant, {"project_code": "__ALL__", "title": "Chung tenant", "status": "published"})
    # Tài liệu của dự án KHÁC không được lẫn vào
    await repo.chen_du_an(conn, tenant, {"project_code": "PD3", "name": "P3", "status": "published"})
    await repo.chen_tai_lieu(conn, tenant, {"project_code": "PD3", "title": "Cua du an khac", "status": "published"})

    ket_qua = await repo.liet_ke_tai_lieu_cho_agent(conn, "PD2")
    tieu_de = {r["title"] for r in ket_qua}
    assert tieu_de == {"Rieng", "Chung tenant"}


async def test_media_cho_agent_gop_ALL(conn: asyncpg.Connection, tenant: str):
    await repo.chen_du_an(conn, tenant, {"project_code": "PM2", "name": "P", "status": "published"})
    await repo.chen_du_an(conn, tenant, {"project_code": "__ALL__", "name": "Chung", "status": "published"})
    await repo.chen_media(
        conn,
        tenant,
        {
            "project_code": "PM2",
            "content_type": "image",
            "category": "tong_quan",
            "media_url": "https://x/rieng.webp",
            "status": "published",
        },
    )
    await repo.chen_media(
        conn,
        tenant,
        {
            "project_code": "__ALL__",
            "content_type": "image",
            "category": "tong_quan",
            "media_url": "https://x/chung.webp",
            "status": "published",
        },
    )
    ket_qua = await repo.liet_ke_media_cho_agent(conn, "PM2")
    url = {r["media_url"] for r in ket_qua}
    assert url == {"https://x/rieng.webp", "https://x/chung.webp"}


async def test_media_cho_agent_mang_caption_auto(conn: asyncpg.Connection, tenant: str):
    """Đường agent JOIN nên mọi cột phải qua `_voi_tien_to` — thiếu `caption_auto` ở đó
    là ảnh về bằng cổng nạp lại không có mô tả, đúng lỗi đã đo trên prod 2026-08-19."""
    await repo.chen_du_an(conn, tenant, {"project_code": "PM4", "name": "P", "status": "published"})
    hang = await repo.chen_media(
        conn,
        tenant,
        {
            "project_code": "PM4",
            "content_type": "image",
            "category": "tong_quan",
            "media_url": "https://x/may.webp",
            "status": "published",
        },
    )
    await conn.execute("UPDATE tenant_data.media SET caption_auto = 'Mô tả máy sinh' WHERE id = $1", hang["id"])

    ket_qua = await repo.liet_ke_media_cho_agent(conn, "PM4")
    assert [r["caption_auto"] for r in ket_qua] == ["Mô tả máy sinh"]


async def test_tai_lieu_portal_khong_tu_gop_ALL(conn: asyncpg.Connection, tenant: str):
    """Đọc CHO PORTAL (`liet_ke_tai_lieu`) lọc ĐÚNG `project_code` truyền vào —
    KHÔNG tự gộp `__ALL__` như đường agent (CMS có tab riêng cho tài liệu chung,
    người biên tập tự chọn phạm vi)."""
    await repo.chen_du_an(conn, tenant, {"project_code": "PP1", "name": "P"})
    await repo.chen_du_an(conn, tenant, {"project_code": "__ALL__", "name": "Chung"})
    await repo.chen_tai_lieu(conn, tenant, {"project_code": "PP1", "title": "Rieng"})
    await repo.chen_tai_lieu(conn, tenant, {"project_code": "__ALL__", "title": "Chung tenant"})

    chi_rieng = await repo.liet_ke_tai_lieu(conn, project_code="PP1")
    assert [r["title"] for r in chi_rieng] == ["Rieng"]


# ─── Phân trang keyset ──────────────────────────────────────────────────────


async def test_phan_trang_cursor_khong_trung_khong_sot(conn: asyncpg.Connection, tenant: str):
    await repo.chen_du_an(conn, tenant, {"project_code": "PP", "name": "P"})
    tao = []
    for i in range(5):
        z = await repo.chen_phan_khu(conn, tenant, {"project_code": "PP", "zone_code": f"Z{i}", "name": f"Zone{i}"})
        tao.append(z["id"])

    trang1 = await repo.liet_ke_phan_khu(conn, project_code="PP", limit=2)
    assert len(trang1) == 2
    # Thứ tự id DESC — mới nhất trước
    assert trang1[0]["id"] > trang1[1]["id"]

    cur = ma_con_tro(trang1[-1]["id"])
    trang2 = await repo.liet_ke_phan_khu(conn, project_code="PP", limit=2, cursor=cur)
    assert len(trang2) == 2
    assert trang1[-1]["id"] > trang2[0]["id"]

    cur2 = ma_con_tro(trang2[-1]["id"])
    trang3 = await repo.liet_ke_phan_khu(conn, project_code="PP", limit=2, cursor=cur2)
    assert len(trang3) == 1  # 5 hàng: 2 + 2 + 1

    tat_ca = {r["id"] for r in (*trang1, *trang2, *trang3)}
    assert tat_ca == set(tao)  # không trùng, không sót


def test_con_tro_hong_raise_loi_doc_duoc():
    with pytest.raises(LoiConTro):
        doc_con_tro("***khong-phai-base64-so***")


# ─── Cách ly chéo tenant qua vai trò RUNTIME thật (KHÔNG dùng `pool`) ──────
# `pool` là `portal_migrator` (rolsuper=t rolbypassrls=t trong container test) —
# một test cách ly chạy qua nó XANH CẢ KHI RLS TẮT HẲN, vì owner không chịu FORCE
# RLS theo cách role thường phải chịu... trừ khi enforce_tenant_isolation() bật
# FORCE (nó có bật — nhưng minh chứng cách ly phải qua đúng vai trò production
# dùng, không phải qua một role có toàn quyền). Nên test này tự mở pool riêng
# bằng DSN của `api_dsn` (role `portal_api`, đúng role Portal API/worker dùng).


@pytest.fixture
async def api_pool(api_dsn: str):
    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


async def test_cross_tenant_qua_portal_api(pool: asyncpg.Pool, api_pool: asyncpg.Pool):
    ta, tb = _tenant_moi(), _tenant_moi()
    await pool.execute(
        "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test'), ($2, $2, 'u_seed_test')",
        ta,
        tb,
    )
    try:
        async with tenant_conn(api_pool, ta) as ca:
            tao = await repo.chen_du_an(ca, ta, {"project_code": "SECRET", "name": "Của A"})
            assert tao is not None

        async with tenant_conn(api_pool, tb) as cb:
            # B liệt kê theo cùng mã — 0 hàng, KHÔNG phải lỗi, KHÔNG thấy dữ liệu A.
            thay_qua_liet_ke = await repo.liet_ke_du_an(cb, tim="SECRET")
            assert thay_qua_liet_ke == []
            # B đọc thẳng theo id của A — vẫn 0 (RLS lọc ở USING, không phải ở app).
            thay_qua_doc = await repo.doc_du_an(cb, tao["id"])
            assert thay_qua_doc is None
    finally:
        await pool.execute("DELETE FROM control.tenants WHERE id IN ($1, $2)", ta, tb)
