"""CỔNG 7 — cách ly hàng Ở TẦNG APP, không nhờ RLS.

VÌ SAO CÓ CỔNG NÀY: migration `0909_bo_rls_toan_bo` đã dỡ RLS khỏi TOÀN BỘ
`tenant_data` (quyết định có chủ đích, xem docstring migration đó). Cổng 1
(`test_rls_isolation.py`) canh lưới ở tầng DB — lưới đó nay không còn. Từ sau
0909, thứ DUY NHẤT còn ngăn tenant A đọc dữ liệu tenant B là vị từ `tenant_id`
mà chính câu SQL trong `src/portal` mang theo.

Cổng này canh đúng vị từ đó, và nó canh QUA REPO/ROUTER thật — không phải qua
SQL tự viết trong test. Một hàm repo mới quên `tenant_id` thì CI đỏ ở đây,
không phải chờ một khách hàng nhìn thấy dữ liệu của khách hàng khác.

Mọi test dưới đây đọc bằng `tenant_conn(api_pool, "t1")` nhưng hỏi về hàng của
`t2` (id lấy sẵn khi còn ở `t2`). Đáp án đúng LUÔN là "không thấy gì".
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.state import repo as kb_state
from portal.modules.realestate import repo, router

pytestmark = pytest.mark.integration


@pytest.fixture
async def id_cua_t2(seeded, api_pool) -> dict[str, int]:
    """id các hàng của `t2` — lấy khi đang ở đúng `t2`, dùng lại khi đã sang `t1`.

    Thêm 1 document + 1 media cho `t2` vì fixture `seeded` chỉ dựng
    project/zone/unit; hai bảng còn lại cũng phải có hàng thật thì mới kiểm
    được `doc_tai_lieu`/`doc_media`/`dem_anh_theo_danh_muc`.
    """
    async with tenant_conn(api_pool, "t2") as conn:
        du_an = await conn.fetchval("SELECT id FROM tenant_data.projects WHERE tenant_id = 't2'")
        phan_khu = await conn.fetchval("SELECT id FROM tenant_data.zones WHERE tenant_id = 't2'")
        can = await conn.fetchval("SELECT id FROM tenant_data.units WHERE tenant_id = 't2'")
        tai_lieu = await conn.fetchval(
            """INSERT INTO tenant_data.documents (tenant_id, project_code, title, status)
               VALUES ('t2', 'P-t2', 'Tài liệu của t2', 'published') RETURNING id"""
        )
        media = await conn.fetchval(
            """INSERT INTO tenant_data.media
                   (tenant_id, project_code, content_type, category, media_url, status)
               VALUES ('t2', 'P-t2', 'image', 'tong_quan', 'https://x/y.jpg', 'published') RETURNING id"""
        )
    return {
        "project": du_an,
        "zone": phan_khu,
        "unit": can,
        "document": tai_lieu,
        "media": media,
    }


# ─── Đọc DANH SÁCH — chỉ được thấy hàng của chính mình ──────────────────────


async def test_liet_ke_khong_lan_hang_tenant_khac(seeded, api_pool, id_cua_t2):
    """Bốn danh sách CHO PORTAL: mỗi cái chỉ được trả hàng của `t1`."""
    async with tenant_conn(api_pool, "t1") as conn:
        du_an = await repo.liet_ke_du_an(conn)
        phan_khu = await repo.liet_ke_phan_khu(conn)
        can = await repo.liet_ke_can(conn)
        tai_lieu = await repo.liet_ke_tai_lieu(conn)
        media = await repo.liet_ke_media(conn)
        # `dem_*` (M-5/I-2, review vòng cuối): CÙNG lỗ hổng có thể ẩn ở câu ĐẾM
        # mà câu LẤY HÀNG không có — `_loc_*()` dùng chung cho cả hai, nhưng chỉ
        # test hành vi trên `liet_ke_*` không bắt được một `dem_*` bị viết tay
        # lại (hoặc sửa) mà quên `_cach_ly()`. `t2` có sẵn 1 project/zone/unit
        # (seeded) + 1 document + 1 media (`id_cua_t2`) — nếu bất kỳ `dem_*` nào
        # đếm lẫn hàng t2, số dưới đây tăng lên và test đỏ.
        so_du_an = await repo.dem_du_an(conn)
        so_phan_khu = await repo.dem_phan_khu(conn)
        so_can = await repo.dem_can(conn)
        so_tai_lieu = await repo.dem_tai_lieu(conn)
        so_media = await repo.dem_media(conn)

    assert [r["project_code"] for r in du_an] == ["P-t1"]
    assert [r["project_code"] for r in phan_khu] == ["P-t1"]
    assert [r["unit_code"] for r in can] == ["A-01"]
    assert tai_lieu == [], "tài liệu của t2 lọt sang danh sách của t1"
    assert media == [], "media của t2 lọt sang danh sách của t1"

    assert so_du_an == 1, "dem_du_an đếm lẫn dự án của t2"
    assert so_phan_khu == 1, "dem_phan_khu đếm lẫn phân khu của t2"
    assert so_can == 1, "dem_can đếm lẫn căn của t2"
    assert so_tai_lieu == 0, "dem_tai_lieu đếm lẫn tài liệu của t2"
    assert so_media == 0, "dem_media đếm lẫn media của t2"


async def test_liet_ke_cho_agent_khong_lan_hang_tenant_khac(seeded, api_pool, id_cua_t2):
    """Ba danh sách CHO AGENT — hỏi bằng ĐÚNG `project_code` của t2.

    Đây là ca hiểm nhất: `P-t2` là mã có thật, JOIN `p.tenant_id = z.tenant_id`
    tự khớp trong nội bộ t2, nên nếu không có vị từ `current_tenant()` thì agent
    của t1 đọc trọn dữ liệu t2 chỉ bằng cách biết mã dự án.
    """
    async with tenant_conn(api_pool, "t1") as conn:
        assert await repo.du_an_cho_agent(conn, "P-t2") is None
        assert await repo.liet_ke_phan_khu_cho_agent(conn, "P-t2") == []
        assert await repo.liet_ke_can_cho_agent(conn, "P-t2") == []
        assert await repo.liet_ke_tai_lieu_cho_agent(conn, "P-t2") == []
        assert await repo.liet_ke_media_cho_agent(conn, "P-t2") == []


# ─── Đọc MỘT hàng theo id — id của tenant khác phải là "không thấy" ─────────


async def test_doc_mot_hang_theo_id_cua_tenant_khac(seeded, api_pool, id_cua_t2):
    async with tenant_conn(api_pool, "t1") as conn:
        assert await repo.doc_du_an(conn, id_cua_t2["project"]) is None
        assert await repo.doc_phan_khu(conn, id_cua_t2["zone"]) is None
        assert await repo.doc_can(conn, id_cua_t2["unit"]) is None
        assert await repo.doc_tai_lieu(conn, id_cua_t2["document"]) is None
        assert await repo.doc_media(conn, id_cua_t2["media"]) is None


async def test_tra_theo_business_code_cua_tenant_khac(seeded, api_pool, id_cua_t2):
    """`router._tim_du_an`/`_tim_phan_khu` — đường mà mọi PATCH/DELETE theo mã đi qua."""
    async with tenant_conn(api_pool, "t1") as conn:
        assert await router._tim_du_an(conn, "P-t2") is None
        assert await router._tim_phan_khu(conn, "P-t2", "Z1") is None


# ─── GHI — sửa/xoá hàng tenant khác phải khớp 0 hàng ────────────────────────


async def test_sua_hang_tenant_khac_khong_an_thua(seeded, api_pool, id_cua_t2):
    async with tenant_conn(api_pool, "t1") as conn:
        assert await repo.sua_du_an(conn, id_cua_t2["project"], {"name": "BỊ CHIẾM"}) is None
        assert await repo.sua_phan_khu(conn, id_cua_t2["zone"], {"name": "BỊ CHIẾM"}) is None
        assert await repo.sua_can(conn, id_cua_t2["unit"], {"block": "BỊ CHIẾM"}) is None
        assert await repo.sua_tai_lieu(conn, id_cua_t2["document"], {"title": "BỊ CHIẾM"}) is None
        assert await repo.sua_media(conn, id_cua_t2["media"], {"caption": "BỊ CHIẾM"}) is None

    async with tenant_conn(api_pool, "t2") as conn:
        assert (await repo.doc_du_an(conn, id_cua_t2["project"]))["name"] == "P-t2"
        assert (await repo.doc_tai_lieu(conn, id_cua_t2["document"]))["title"] == "Tài liệu của t2"


async def test_xoa_hang_tenant_khac_khong_an_thua(seeded, api_pool, id_cua_t2):
    async with tenant_conn(api_pool, "t1") as conn:
        assert await repo.xoa_phan_khu(conn, id_cua_t2["zone"]) is False
        assert await repo.xoa_can(conn, id_cua_t2["unit"]) is False
        assert await repo.xoa_tai_lieu(conn, id_cua_t2["document"]) is False
        assert await repo.xoa_media(conn, id_cua_t2["media"]) is False
        # `projects` xoá SAU CÙNG: nó là anchor, CASCADE của nó dọn cả bốn bảng
        # trên — xoá nó trước thì bốn assert kia thành "0 hàng vì đã bị dọn",
        # không còn chứng minh được vị từ tenant.
        assert await repo.xoa_du_an(conn, id_cua_t2["project"]) is False

    async with tenant_conn(api_pool, "t2") as conn:
        assert await repo.doc_du_an(conn, id_cua_t2["project"]) is not None
        assert await repo.doc_can(conn, id_cua_t2["unit"]) is not None


async def test_dem_anh_khong_dem_anh_tenant_khac(seeded, api_pool, id_cua_t2):
    """Trần ≤6 ảnh/entity — đếm lẫn ảnh tenant khác vừa sai số vừa lộ tồn tại."""
    async with tenant_conn(api_pool, "t1") as conn:
        n = await repo.dem_anh_theo_danh_muc(
            conn, project_code="P-t2", zone_code=None, unit_code=None, category="tong_quan"
        )
    assert n == 0, "đếm phải bỏ qua ảnh của t2"


# ─── KB index state + write-back cache ──────────────────────────────────────


async def test_kb_state_khong_doc_ghi_sang_tenant_khac(seeded, api_pool, id_cua_t2):
    """`kb_index_state` đọc theo `(entity, record_id)` — `record_id` là id bảng
    nguồn, KHÔNG unique giữa các tenant, nên thiếu vị từ tenant là đọc nhầm chắc chắn."""
    async with tenant_conn(api_pool, "t2") as conn:
        await kb_state.save_state(
            conn,
            entity="documents",
            record_id=id_cua_t2["document"],
            doc_type="noi_dung",
            target="documents",
            state="indexed",
        )

    async with tenant_conn(api_pool, "t1") as conn:
        assert await kb_state.read_state(conn, entity="documents", record_id=id_cua_t2["document"]) == []
        # Write-back cache: ba hàm này ghi thẳng theo `id` bảng nguồn.
        await kb_state.cache_extracted_text(conn, record_id=id_cua_t2["document"], text="VĂN BẢN CHIẾM")
        await kb_state.cache_caption(conn, record_id=id_cua_t2["media"], caption="CHÚ THÍCH CHIẾM")
        await kb_state.save_thumb_and_hash(
            conn, record_id=id_cua_t2["media"], thumb_url="https://x/chiem.jpg", content_hash="deadbeef"
        )
        await kb_state.mark_deleted(conn, entity="documents", record_id=id_cua_t2["document"])

    async with tenant_conn(api_pool, "t2") as conn:
        tai_lieu = await repo.doc_tai_lieu(conn, id_cua_t2["document"])
        media = await repo.doc_media(conn, id_cua_t2["media"])
        trang_thai = await kb_state.read_state(conn, entity="documents", record_id=id_cua_t2["document"])

    assert tai_lieu["body"] == "", "cache_extracted_text ghi xuyên tenant"
    assert media["caption"] == "", "cache_caption ghi xuyên tenant"
    assert media["thumb_url"] != "https://x/chiem.jpg", "save_thumb_and_hash ghi xuyên tenant"
    assert [r["state"] for r in trang_thai] == ["indexed"], "mark_deleted ghi xuyên tenant"


# ─── Hai con số chẩn đoán của enrollment ────────────────────────────────────


async def test_san_sang_du_lieu_dem_dung_tenant(seeded, api_pool, id_cua_t2):
    """`san_sang_du_lieu(pool, 't1')` phải đếm dữ liệu của t1, không phải cả DB."""
    from portal.modules.enrollment.service import san_sang_du_lieu

    t1 = await san_sang_du_lieu(api_pool, "t1")
    assert t1.projects_published == 1, "đếm lẫn dự án published của t2"


# ─── Cổng chống hồi quy: quét SQL, không quét hành vi ───────────────────────


async def test_moi_cau_sql_cham_tenant_data_deu_mang_vi_tu_tenant():
    """Quét TĨNH `src/portal`: mọi câu SQL chạm `tenant_data.*` phải tự lọc tenant.

    Các cổng hành vi ở trên chỉ phủ những hàm ĐANG tồn tại. Cổng này phủ hàm
    VIẾT NGÀY MAI — thêm một SELECT quên vị từ tenant là đỏ ngay, kể cả khi chưa
    ai viết test hành vi cho nó.

    LUẬT ÁP:
      · INSERT  — chỉ cần nhắc cột `tenant_id` (giá trị đến từ `Principal` qua `$n`).
      · còn lại — PHẢI gọi `portal.current_tenant()`. Nhắc suông `tenant_id` KHÔNG
        đủ: `JOIN ... ON p.tenant_id = z.tenant_id` có nhắc, nhưng nó chỉ buộc hai
        bảng CÙNG một tenant chứ không buộc tenant đó là tenant ĐANG đăng nhập —
        đúng lỗ hổng mà `test_liet_ke_cho_agent_khong_lan_hang_tenant_khac` bắt.

    NHẬN DIỆN BẢNG theo HAI cách, vì chỉ tìm chữ `tenant_data.` là không đủ:
      · viết thẳng   — `FROM tenant_data.projects`
      · ghép bằng biến — `FROM {schema}.{table}` (`kb/source/query.py`). Đúng dạng
        này đã che một rò rỉ thật: 5 câu sinh ở đó đọc `tenant_data` mà không có
        vị từ tenant nào, và bản quét đầu (chỉ grep `tenant_data.`) bỏ qua sạch.
        Nên bất kỳ `FROM/JOIN/UPDATE/INTO {…}` nào cũng bị xét như bảng tenant.

    ĐIỂM MÙ CÒN LẠI (cố ý — cổng hành vi ở trên phủ nó): câu dựng hoàn toàn lúc
    chạy từ mảnh chuỗi rời rạc, không nằm trong một literal nào.
    """
    import ast
    import re
    from pathlib import Path

    goc = Path(__file__).resolve().parents[2] / "src" / "portal"
    # `{…}` ở vị trí tên bảng: schema/bảng ghép bằng biến (xem docstring).
    bang = re.compile(r"tenant_data\.\w+|(?:FROM|JOIN|UPDATE|INTO)\s+\{", re.I)
    lenh = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.I)
    # `control.*` là control-plane, chưa từng có RLS và code vốn đã lọc tường minh
    # bằng `$n` — không phải phạm vi của cổng này.
    mien = re.compile(r"\bcontrol\.\w+", re.I)

    def cau_sql(nut: ast.AST) -> str | None:
        """Chuỗi SQL của một literal — GỘP CẢ f-string.

        Phần lớn SQL của `realestate/repo.py` là f-string (ghép danh sách cột),
        nên nó tới đây dưới dạng `JoinedStr`: chuỗi bị CẮT thành nhiều mảnh
        `Constant` quanh mỗi `{...}`. Xét từng mảnh rời sẽ vừa bỏ sót vừa báo
        nhầm; nối lại mới đúng là câu SQL mà Postgres nhận.

        Mỗi `{...}` nối vào bằng MÃ NGUỒN của nó (`ast.unparse`), không phải
        khoảng trắng: vị từ cách ly ở `repo.py` đến từ helper `_cach_ly()` chứ
        không viết thẳng, nên bỏ phần trong ngoặc đi là xoá mất đúng thứ cổng này
        đi tìm — và mọi câu SQL của file đó bị báo nhầm là thiếu.
        """
        if isinstance(nut, ast.Constant) and isinstance(nut.value, str):
            return nut.value
        if isinstance(nut, ast.JoinedStr):
            return " ".join(
                p.value if isinstance(p, ast.Constant) and isinstance(p.value, str) else ast.unparse(p)
                for p in nut.values
            )
        return None

    thieu: list[str] = []
    for tep in sorted(goc.rglob("*.py")):
        cay = ast.parse(tep.read_text(encoding="utf-8"))
        # Bỏ qua thân của một `JoinedStr` đã xét — nếu không, các mảnh `Constant`
        # bên trong nó bị `ast.walk` trả lại lần nữa dưới dạng literal rời và sinh
        # đúng loại báo nhầm mà `cau_sql()` vừa tránh.
        trong_fstring = {id(p) for n in ast.walk(cay) if isinstance(n, ast.JoinedStr) for p in n.values}
        for nut in ast.walk(cay):
            if id(nut) in trong_fstring:
                continue
            sql = cau_sql(nut)
            if not (sql and bang.search(sql) and lenh.search(sql)):
                continue
            # Câu chỉ chạm `control.*` (và không chạm `tenant_data`) thì bỏ qua —
            # `{…}` ở dạng `FROM {bang_control}` cũng rơi vào đây.
            if mien.search(sql) and "tenant_data" not in sql.lower():
                continue
            la_insert = (lenh.search(sql).group(1) or "").upper() == "INSERT"
            # `_cach_ly` được chấp nhận ngang `current_tenant(` — cả helper
            # `repo._cach_ly()` lẫn hằng `query._CACH_LY` (khớp nhờ `re.I`, nên
            # KHÔNG đòi dấu ngoặc) đều không sinh ra gì ngoài đúng vị từ này.
            can = re.compile(r"tenant_id" if la_insert else r"current_tenant\s*\(|_cach_ly", re.I)
            if not can.search(sql):
                thieu.append(f"{tep.relative_to(goc)}:{nut.lineno}  {' '.join(sql.split())[:110]}")

    assert not thieu, "câu SQL chạm tenant_data mà không có vị từ tenant_id:\n" + "\n".join(thieu)
