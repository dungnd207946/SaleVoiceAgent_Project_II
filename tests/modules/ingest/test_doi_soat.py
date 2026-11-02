"""Đối soát — cơ chế DUY NHẤT phát hiện sự kiện `delete` bị rơi.

Không có nó, một sự kiện rơi là im lặng vĩnh viễn và im theo hướng nguy hiểm
nhất: căn đã bán ở lại «còn hàng», agent nói với khách là còn. Nên file này canh
kỹ hai chiều lệch, và canh cả những cách đối soát có thể tự làm hỏng dữ liệu.
"""

from datetime import UTC, datetime, timedelta

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.ingest import contracts, doi_soat, service

pytestmark = pytest.mark.integration

LUC = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
DU_AN = {"name": "X"}


def _bg(ma: str, *, luc: datetime = LUC, op: str = "upsert"):
    return contracts.BanGhiIn(
        entity="project",
        externalId=ma,
        op=op,
        occurredAt=luc,
        data={} if op == "delete" else DU_AN,
    )


def _ke(*muc: tuple[str, datetime]):
    return contracts.BanKeIn(
        entity="project",
        records=[contracts.MucBanKe(externalId=m, updatedAt=t) for m, t in muc],
    )


async def _dang_nghi_mat_tich(conn):
    """Mọi bản ghi đang bị nghi, mọi thực thể."""
    return await conn.fetch(
        """SELECT entity, external_id, nghi_mat_tich_tu
             FROM tenant_data.ingest_records
            WHERE tenant_id = portal.current_tenant() AND nghi_mat_tich_tu IS NOT NULL
            ORDER BY nghi_mat_tich_tu, entity, external_id"""
    )


async def _nap(pool, tenant, *bg):
    return await service.nap_lo(pool, tenant_id=tenant, lo=contracts.LoNapIn(records=list(bg)), dry_run=False)


async def test_hai_ben_khop_thi_khong_bao_gi(api_pool, hai_tenant):
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))
    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC), ("P2", LUC)))
    assert ra.soLech == 0 and ra.soNghiMatTich == 0


async def test_khach_moi_hon_thi_vao_danh_sach_day_lai(api_pool, hai_tenant):
    """Mình hụt một lần cập nhật. Biết chính xác thiếu cái nào nên trả danh sách
    về — response CHÍNH LÀ yêu cầu đẩy lại, không cần webhook."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))
    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC + timedelta(hours=1)), ("P2", LUC)))
    assert ra.externalIdLech == ["P1"]
    assert ra.soNghiMatTich == 0


async def test_khach_co_ma_minh_chua_tung_nhan_cung_la_lech(api_pool, hai_tenant):
    """Không phân biệt «mình có bản cũ» với «mình chưa từng nhận» — cả hai đều
    dẫn tới cùng một hành động: bảo họ đẩy lại mã đó."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"))
    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC), ("P_MOI", LUC)))
    assert ra.externalIdLech == ["P_MOI"]


async def test_minh_co_khach_khong_thi_NGHI_mat_tich_va_khong_bi_xoa(api_pool, hai_tenant):
    """Đánh dấu, KHÔNG xoá.

    Một `delete` bị rơi và một bản ghi khách thật sự xoá trông GIỐNG HỆT NHAU ở
    phía mình. Đoán sai theo chiều xoá là mất dữ liệu không lấy lại được; đoán sai
    theo chiều giữ là một hàng thừa mà ai đó nhìn thấy. Hai sai lầm không cùng hạng.
    """
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))
    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    assert ra.externalIdNghiMatTich == ["P2"]

    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_records WHERE tenant_id=$1", a) == 2, (
            "bản ghi bị xoá — đối soát không được tự xoá gì"
        )
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.projects WHERE tenant_id=$1", a) == 2, (
            "dự án đã chiếu bị xoá theo"
        )
        nghi = await _dang_nghi_mat_tich(conn)
    assert [h["external_id"] for h in nghi] == ["P2"]


async def test_xuat_hien_lai_thi_tu_go_co(api_pool, hai_tenant):
    """Cờ phải tự gỡ — nếu không, một lần bản kê thiếu sót sẽ để lại cảnh báo
    vĩnh viễn và người vận hành học cách bỏ qua chúng."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC), ("P2", LUC)))
    assert ra.soNghiMatTich == 0

    async with tenant_conn(api_pool, a) as conn:
        assert await _dang_nghi_mat_tich(conn) == []


async def test_moc_nghi_giu_lan_dau_khong_bi_de_moi_dem(api_pool, hai_tenant):
    """`nghi_mat_tich_tu` trả lời «đã nghi bao lâu rồi» — thứ quyết định có đi
    điều tra hay không. Đè `now()` mỗi lần đối soát làm mọi hàng trông như vừa
    mới bị nghi, và câu hỏi đó hết trả lời được."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    async with tenant_conn(api_pool, a) as conn:
        lan_dau = (await _dang_nghi_mat_tich(conn))[0]["nghi_mat_tich_tu"]

    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    async with tenant_conn(api_pool, a) as conn:
        lan_hai = (await _dang_nghi_mat_tich(conn))[0]["nghi_mat_tich_tu"]
    assert lan_dau == lan_hai


async def test_ban_ghi_da_xoa_khong_bi_tinh_la_mat_tich(api_pool, hai_tenant):
    """Bản kê của khách đương nhiên không liệt kê thứ họ vừa xoá. Tính nó là mất
    tích sẽ tạo ra một cảnh báo cho đúng thứ hệ thống đang chạy ĐÚNG."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))
    await _nap(api_pool, a, _bg("P2", luc=LUC + timedelta(hours=1), op="delete"))
    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    assert ra.soNghiMatTich == 0


async def test_doi_soat_chi_nhin_dung_thuc_the_duoc_ke(api_pool, hai_tenant):
    """Bản kê của `project` không được làm `unit` bị nghi mất tích. Trộn phạm vi
    ở đây là gắn cờ cho toàn bộ dữ liệu của một thực thể chưa hề được đối soát."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"))
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=contracts.LoNapIn(
            records=[
                contracts.BanGhiIn(
                    entity="zone",
                    externalId="Z1",
                    op="upsert",
                    occurredAt=LUC,
                    data={"projectExternalId": "P1", "name": "PK"},
                )
            ]
        ),
        dry_run=False,
    )
    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    assert ra.soNghiMatTich == 0

    async with tenant_conn(api_pool, a) as conn:
        assert await _dang_nghi_mat_tich(conn) == []


async def test_ban_ke_cua_tenant_A_khong_cham_du_lieu_tenant_B(api_pool, hai_tenant):
    """CÁCH LY. Đối soát ghi (`UPDATE` cờ) nên nó nguy hiểm hơn một đường đọc:
    thiếu vị từ tenant thì một bản kê của A gắn cờ mất tích cho toàn bộ dữ liệu
    của B."""
    a, b = hai_tenant
    await _nap(api_pool, a, _bg("P1"))
    await _nap(api_pool, b, _bg("P9"))

    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    assert ra.soNghiMatTich == 0, "thấy dữ liệu của tenant khác"

    async with tenant_conn(api_pool, b) as conn:
        assert await _dang_nghi_mat_tich(conn) == [], "dữ liệu B bị bản kê của A gắn cờ"


async def test_ban_ke_co_ma_trung_bi_tu_choi_truoc_khi_cham_du_lieu(api_pool, hai_tenant):
    """Mã trùng làm phép so ra kết quả tuỳ mục nào thắng — không tái lập được.
    Và nó phải bị chặn TRƯỚC khi chạm dữ liệu, không phải sau."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))
    with pytest.raises(service.BanKeKhongHopLe, match="trùng"):
        await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC), ("P1", LUC)))
    async with tenant_conn(api_pool, a) as conn:
        assert await _dang_nghi_mat_tich(conn) == [], "đã gắn cờ dù bản kê bị từ chối"


def test_ban_ke_qua_tran_bi_tu_choi_va_CHI_DUONG_phan_trang():
    """Trần là trần MỘT TRANG (từ 2026-08-15), không phải trần cả cuộc đối soát.

    Thông điệp phải chỉ đúng đường ra — tên hai trường và luật sắp xếp — chứ không
    phải «payload quá lớn». Người đọc nó là dev bên khách đang bị chặn, và họ không
    có tài liệu nào khác mở sẵn."""
    qua = contracts.BanKeIn(
        entity="project",
        records=[contracts.MucBanKe(externalId=f"P{i}", updatedAt=LUC) for i in range(doi_soat.TRAN_BAN_KE + 1)],
    )
    ly_do = doi_soat.kiem_ban_ke(qua)
    assert ly_do is not None
    assert "afterExternalId" in ly_do and "isLastPage" in ly_do, "phải chỉ tên trường"
    assert "byte" in ly_do, "phải nói luật sắp xếp — sai thứ tự là gắn cờ SAI"


async def test_ghi_nhat_ky_khi_co_co_MOI_va_khong_ghi_lai(api_pool, hai_tenant, pool):
    """Nhật ký là kênh vận hành DUY NHẤT cho việc này — giao diện cố ý không bày
    kết quả đối soát. Nên nó phải kêu, và phải kêu ĐÚNG MỘT LẦN.

    Một bản ghi nghi mất tích ba tuần liền mà đêm nào cũng sinh một dòng là cách
    dạy người trực bỏ qua chính dòng đó.
    """
    a, _ = hai_tenant
    await pool.execute("DELETE FROM control.audit_log WHERE tenant_id = $1", a)
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))

    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    hang = await pool.fetch(
        "SELECT hanh_dong, chi_tiet FROM control.audit_log WHERE tenant_id=$1 AND hanh_dong=$2",
        a,
        "ingest.nghi_mat_tich",
    )
    assert len(hang) == 1
    import json

    assert json.loads(hang[0]["chi_tiet"])["externalId"] == ["P2"]

    # Lần đối soát thứ hai, CÙNG kết quả — không được sinh dòng thứ hai.
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    assert (
        len(
            await pool.fetch(
                "SELECT 1 FROM control.audit_log WHERE tenant_id=$1 AND hanh_dong=$2",
                a,
                "ingest.nghi_mat_tich",
            )
        )
        == 1
    )


async def test_khong_ghi_nhat_ky_khi_hai_ben_khop(api_pool, hai_tenant, pool):
    """Im lặng khi mọi thứ ổn. Ghi một dòng «đã đối soát, không có gì» mỗi đêm cho
    mỗi tenant là làm nhật ký thành thứ không ai đọc."""
    a, _ = hai_tenant
    await pool.execute("DELETE FROM control.audit_log WHERE tenant_id = $1", a)
    await _nap(api_pool, a, _bg("P1"))
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    assert (
        await pool.fetch(
            "SELECT 1 FROM control.audit_log WHERE tenant_id=$1 AND hanh_dong=$2", a, "ingest.nghi_mat_tich"
        )
        == []
    )


def test_ban_ke_rong_hop_le():
    """Thực thể chưa có dữ liệu nào bên khách là trạng thái ĐÚNG, không phải lỗi —
    và nó phải làm mọi bản ghi phía mình của thực thể đó bị nghi, vì đúng là vậy."""
    assert doi_soat.kiem_ban_ke(contracts.BanKeIn(entity="project", records=[])) is None


# ─── Phân trang bản kê — §8 mục 1 ───────────────────────────────────────────
#
# Mỗi trang TỰ KHAI khoảng nó phủ; phép so chỉ chạm đúng đoạn đó. Không phiên,
# không trạng thái giữa các request. Bộ bài này canh đúng ba chỗ hỏng được, và cả
# ba đều hỏng ÂM THẦM: kết quả vẫn hợp lý, chỉ sai.


def _trang(*ma: str, sau: str | None = None, cuoi: bool = False) -> contracts.BanKeIn:
    """Một TRANG bản kê. `sau` = mã cuối của trang trước; `cuoi` = trang cuối cùng."""
    return contracts.BanKeIn(
        entity="project",
        records=[contracts.MucBanKe(externalId=m, updatedAt=LUC) for m in ma],
        afterExternalId=sau,
        isLastPage=cuoi,
    )


def test_khoang_suy_tu_chinh_noi_dung():
    """Cận trên là `max(ma)`, KHÔNG phải giá trị khách khai.

    Để khách khai thì một trang khai rộng hơn thứ nó chứa sẽ gắn cờ cho phần
    chênh — chế độ hỏng nguy hiểm nhất của cả cơ chế. Suy từ nội dung thì lời khai
    không thể rộng hơn bằng chứng.
    """
    assert doi_soat.khoang(["b", "d", "c"], "a", False) == ("a", "d")
    assert doi_soat.khoang(["b", "d"], "a", True) == ("a", None), "trang cuối kéo tới +∞"
    assert doi_soat.khoang(["b"], None, False) == (None, "b"), "trang đầu từ -∞"
    assert doi_soat.khoang([], "a", False) is None, "trang giữa rỗng phủ KHÔNG GÌ"
    assert doi_soat.khoang([], None, False) is None, "và trang ĐẦU rỗng cũng vậy — không phải (-∞,+∞)"


async def test_trang_giua_khong_gan_co_ngoai_khoang_cua_no(api_pool, hai_tenant):
    """Bản ghi nằm NGOÀI đoạn trang này phủ thì không được đụng tới.

    Không có vị từ khoảng, trang đầu của một cuộc phân trang sẽ gắn cờ mọi bản ghi
    phía sau nó — tức toàn bộ phần chưa được đối soát bị báo là mất tích.
    """
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P5"), _bg("P9"))

    # Trang phủ (-∞, P5]; P1 có trong kê, P5 không ⇒ chỉ P5 bị nghi. P9 ngoài khoảng.
    ra = await service.doi_soat_ban_ke(
        api_pool,
        tenant_id=a,
        ban_ke=_trang("P1", "P5x"),
    )
    assert ra.externalIdNghiMatTich == ["P5"], "P9 nằm ngoài khoảng, không được gắn cờ"


async def test_trang_sau_KHONG_go_co_trang_truoc_vua_dat(api_pool, hai_tenant):
    """⚠️ Chỗ dễ sai nhất của cả bản phân trang.

    Câu gỡ cờ vốn quét TOÀN thực thể. Giữ nguyên nó thì mỗi trang lần lượt xoá công
    của trang trước, và cuối cuộc chỉ còn cờ của trang cuối cùng — kết quả vẫn hợp
    lý, chỉ thiếu, nên không ai thấy.
    """
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P9"))

    t1 = await service.doi_soat_ban_ke(
        api_pool,
        tenant_id=a,
        ban_ke=_trang("P2"),
    )
    assert t1.externalIdNghiMatTich == ["P1"]

    t2 = await service.doi_soat_ban_ke(
        api_pool,
        tenant_id=a,
        ban_ke=_trang(sau="P2", cuoi=True),
    )
    assert t2.externalIdNghiMatTich == ["P9"]

    async with tenant_conn(api_pool, a) as conn:
        nghi = sorted(r["external_id"] for r in await _dang_nghi_mat_tich(conn))
    assert nghi == ["P1", "P9"], "cờ của trang đầu phải còn nguyên sau trang cuối"


async def test_chi_trang_CUOI_dong_dau_nhip_tim(api_pool, hai_tenant):
    """Nhịp tim nói «một lượt đối soát ĐÃ XONG», và phân trang chết giữa chừng thì
    chưa xong. Đóng dấu ở mọi trang là để trang đầu làm im cảnh báo «tenant im
    lặng» — một adapter hỏng sau trang một sẽ trông y hệt một adapter chạy trọn."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"))

    await service.doi_soat_ban_ke(
        api_pool,
        tenant_id=a,
        ban_ke=_trang("P1"),
    )
    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_manifest_runs WHERE tenant_id=$1", a) == 0

    await service.doi_soat_ban_ke(
        api_pool,
        tenant_id=a,
        ban_ke=_trang(sau="P1", cuoi=True),
    )
    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_manifest_runs WHERE tenant_id=$1", a) == 1


async def test_ban_ke_mot_trang_van_dung_nhu_cu(api_pool, hai_tenant):
    """Mặc định `isLastPage=True`, `afterExternalId=None` ⇒ nguyên hành vi trước
    2026-08-15. Adapter đang chạy không phải sửa một dòng nào."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))

    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))
    assert ra.externalIdNghiMatTich == ["P2"]


# ─── dryRun: diễn tập đối soát — so thật, KHÔNG chạm cờ ─────────────────────


async def test_dry_run_bao_dung_ket_qua_nhung_khong_gan_co(api_pool, pool, hai_tenant):
    """Một adapter đang dev phải diễn tập được đối soát mà không sợ gắn cờ nhầm
    cả catalog — cùng lý lẽ `?dryRun=true` của `/events`. Kết quả so phải THẬT
    (khác nó là vô dụng), chỉ phần GHI là không xảy ra."""
    a, _ = hai_tenant
    await pool.execute("DELETE FROM control.audit_log WHERE tenant_id = $1", a)
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))

    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)), dry_run=True)
    assert ra.dryRun is True
    assert ra.externalIdNghiMatTich == ["P2"], "kết quả so phải THẬT như lượt chạy thật"

    async with tenant_conn(api_pool, a) as conn:
        assert await _dang_nghi_mat_tich(conn) == [], "dryRun không được gắn cờ"
    nhat_ky = await pool.fetch(
        "SELECT 1 FROM control.audit_log WHERE tenant_id=$1 AND hanh_dong=$2", a, "ingest.nghi_mat_tich"
    )
    assert nhat_ky == [], "dryRun không được ghi nhật ký"


async def test_dry_run_khong_go_co_da_co(api_pool, hai_tenant):
    """Chiều ngược cũng phải bất động: một cờ do lượt chạy THẬT đặt không được
    biến mất chỉ vì ai đó bấm thử một bản kê đầy đủ ở chế độ diễn tập."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"), _bg("P2"))
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)))

    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC), ("P2", LUC)), dry_run=True)
    assert ra.soNghiMatTich == 0, "bản kê đầy đủ thì không còn gì mất tích"
    async with tenant_conn(api_pool, a) as conn:
        con_co = await _dang_nghi_mat_tich(conn)
    assert [h["external_id"] for h in con_co] == ["P2"], "cờ của lượt THẬT phải còn nguyên sau dryRun"


async def test_dry_run_khong_dong_dau_nhip_tim(api_pool, hai_tenant):
    """Dấu bản kê nuôi cảnh báo «tenant im lặng». Một lượt diễn tập mà đóng dấu
    là làm im cảnh báo cho đúng ca adapter thật đã chết — dryRun phải vô hình
    với nhịp tim, kể cả khi nó là trang cuối."""
    a, _ = hai_tenant
    await _nap(api_pool, a, _bg("P1"))
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke(("P1", LUC)), dry_run=True)
    async with tenant_conn(api_pool, a) as conn:
        dau = await conn.fetch(
            "SELECT 1 FROM tenant_data.ingest_manifest_runs WHERE tenant_id = portal.current_tenant()"
        )
    assert dau == [], "dryRun không được đóng dấu ingest_manifest_runs"
