"""Phân trang bản kê đối soát — §8 mục 1, mục cuối cùng.

Đây là phần dễ hỏng nhất của cả cổng nạp, và nó hỏng ÂM THẦM: kết quả vẫn trông
hợp lý, chỉ thiếu hoặc thừa. Bộ bài này canh đúng ba tính chất, xếp theo mức nguy
hiểm giảm dần:

  ① Trang sau KHÔNG được gỡ cờ mà trang trước vừa đặt.
  ② Bản ghi nằm giữa hai trang phải được kiểm (không có khe).
  ③ Bản ghi ngoài khoảng một trang phủ KHÔNG được gắn cờ.

Cái ③ là chiều nguy hiểm — gắn cờ sai. Cái ② hỏng về phía an toàn (không kiểm),
nhưng nó làm cả cơ chế nói dối về độ phủ nên vẫn phải canh.
"""

from datetime import UTC, datetime

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.ingest import contracts, doi_soat, service

pytestmark = pytest.mark.integration

LUC = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)


def _bg(ma: str):
    return contracts.BanGhiIn(entity="project", externalId=ma, op="upsert", occurredAt=LUC, data={"name": ma})


async def _nap(api_pool, tenant_id: str, *ma: str):
    await service.nap_lo(
        api_pool, tenant_id=tenant_id, lo=contracts.LoNapIn(records=[_bg(m) for m in ma]), dry_run=False
    )


def _ke(*ma: str, sau: str | None = None, cuoi: bool = True):
    return contracts.BanKeIn(
        entity="project",
        records=[contracts.MucBanKe(externalId=m, updatedAt=LUC) for m in ma],
        afterExternalId=sau,
        isLastPage=cuoi,
    )


async def _co(api_pool, tenant_id: str) -> set[str]:
    """Tập mã ĐANG bị gắn cờ nghi mất tích."""
    async with tenant_conn(api_pool, tenant_id) as conn:
        return {
            r["external_id"]
            for r in await conn.fetch(
                "SELECT external_id FROM tenant_data.ingest_records "
                "WHERE tenant_id = $1 AND nghi_mat_tich_tu IS NOT NULL",
                tenant_id,
            )
        }


# ─── Hàm thuần: khoảng mà một trang tự khai ─────────────────────────────────


def test_khoang_trang_dau_va_trang_cuoi():
    assert doi_soat.khoang(["A", "M"], None, True) == (None, None), "một trang = toàn bộ"
    assert doi_soat.khoang(["A", "M"], None, False) == (None, "M"), "trang đầu, chưa cuối"
    assert doi_soat.khoang(["N", "Z"], "M", True) == ("M", None), "trang cuối kéo tới +∞"
    assert doi_soat.khoang(["N", "Z"], "M", False) == ("M", "Z")


def test_can_tren_suy_TU_NOI_DUNG_khong_tu_loi_khai():
    """Nếu để khách khai cận trên, một trang khai rộng hơn thứ nó chứa sẽ gắn cờ
    cho phần chênh — chế độ hỏng nguy hiểm nhất của cả cơ chế. Suy từ chính nội
    dung thì lời khai không thể rộng hơn bằng chứng."""
    assert doi_soat.khoang(["B", "D", "C"], "A", False) == ("A", "D")


def test_trang_giua_RONG_phu_khong_gi():
    """Không bản ghi nào và cũng không tự nhận là cuối ⇒ không khẳng định được gì.

    Trả `None` (phủ KHÔNG GÌ) chứ KHÔNG phải một tuple. Bản đầu trả `(tu_ma, tu_ma)`
    — đúng khi `tu_ma` có giá trị, nhưng ở trang ĐẦU nó thành `(None, None)` tức
    `(-∞, +∞)`: một trang rỗng phủ toàn bộ và gỡ sạch mọi cờ. Hai nghĩa trái nhau
    trong cùng một giá trị.
    """
    assert doi_soat.khoang([], "M", False) is None
    assert doi_soat.khoang([], None, False) is None


# ─── Ba tính chất, chạy trên DB thật ───────────────────────────────────────


async def test_trang_sau_KHONG_go_co_ma_trang_truoc_vua_dat(api_pool, hai_tenant):
    """⚠️ BÀI QUAN TRỌNG NHẤT.

    Câu gỡ cờ trước bản phân trang quét TOÀN thực thể. Giữ nguyên nó thì mỗi trang
    lần lượt xoá công của trang trước, và cuối cuộc chỉ còn cờ của trang cuối cùng
    — kết quả vẫn hợp lý nên không ai thấy, cho tới lúc một `delete` bị rơi ở đầu
    bảng chữ cái không bao giờ được báo.
    """
    a, _ = hai_tenant
    await _nap(api_pool, a, "A1", "A2", "B1", "B2")

    # Trang 1 gửi [A1, A2] ⇒ phủ (-∞, A2], khách còn cả hai ⇒ chưa cờ nào.
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("A1", "A2", cuoi=False))
    assert await _co(api_pool, a) == set()

    # Trang 2 gửi [B1], sau = mã LỚN NHẤT ĐÃ GỬI ở trang 1 = "A2" ⇒ phủ (A2, +∞).
    # Khách còn B1 ⇒ B2 nghi mất tích.
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("B1", sau="A2", cuoi=True))
    assert await _co(api_pool, a) == {"B2"}

    # Đợt sau: khách đã xoá A2. Trang 1 giờ chỉ gửi [A1] ⇒ phủ (-∞, A1], A2 CHƯA
    # bị kiểm ở đây — nó thuộc trang sau, và đó là lý do con trỏ phải là «mã lớn
    # nhất ĐÃ GỬI» chứ không phải «đã quét».
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("A1", cuoi=False))
    assert await _co(api_pool, a) == {"B2"}, "A2 chưa tới lượt, B2 giữ nguyên cờ"

    # Trang 2 với sau="A1" ⇒ phủ (A1, +∞) ⇒ A2 bị bắt ở đây. B2 KHÔNG được gỡ cờ.
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("B1", sau="A1", cuoi=True))
    assert await _co(api_pool, a) == {"A2", "B2"}


async def test_ban_ghi_NGOAI_khoang_khong_bi_gan_co(api_pool, hai_tenant):
    """Chiều nguy hiểm: gắn cờ sai. Một trang chỉ phủ đoạn nó khai, và mọi thứ sau
    `max(records)` thuộc về trang chưa tới."""
    a, _ = hai_tenant
    await _nap(api_pool, a, "A1", "Z9")

    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("A1", cuoi=False))
    assert ra.soNghiMatTich == 0
    assert await _co(api_pool, a) == set(), "Z9 nằm ngoài khoảng, không được gắn cờ"


async def test_khong_co_KHE_giua_hai_trang(api_pool, hai_tenant):
    """`afterExternalId` là thứ làm hai trang liền nhau khít nhau.

    M5 nằm giữa trang 1 (kết ở M1) và trang 2 (bắt đầu ở M9). Thiếu vế «bắt đầu
    đúng chỗ trang trước kết thúc» thì nó không thuộc trang nào và vĩnh viễn không
    được kiểm — cơ chế nói dối về độ phủ.
    """
    a, _ = hai_tenant
    await _nap(api_pool, a, "M1", "M5", "M9")

    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("M1", cuoi=False))
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("M9", sau="M1", cuoi=True))
    assert await _co(api_pool, a) == {"M5"}


async def test_mot_trang_van_dung_nhu_truoc(api_pool, hai_tenant):
    """Mặc định `isLastPage=True` + `afterExternalId=None` ⇒ toàn bộ không gian mã.

    Adapter viết trước 2026-08-15 không gửi hai trường này và phải chạy y nguyên —
    phân trang là phần THÊM, không phải hợp đồng mới.
    """
    a, _ = hai_tenant
    await _nap(api_pool, a, "P1", "P2", "P3")

    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=contracts.BanKeIn(entity="project", records=[]))
    assert ra.soNghiMatTich == 3


async def test_nhip_tim_CHI_dong_dau_o_trang_cuoi(api_pool, hai_tenant):
    """Nhịp tim nói «một lượt đối soát ĐÃ XONG», và phân trang chết giữa chừng thì
    chưa xong.

    Đóng dấu ở mọi trang là để trang đầu tiên làm im cảnh báo «tenant im lặng» —
    một adapter hỏng sau trang một sẽ trông y hệt một adapter chạy trọn vẹn.
    """
    a, _ = hai_tenant
    await _nap(api_pool, a, "P1", "P2")

    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("P1", cuoi=False))
    async with tenant_conn(api_pool, a) as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_manifest_runs WHERE tenant_id = $1", a) == 0
        ), "trang giữa KHÔNG được đóng dấu"

    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("P2", sau="P1", cuoi=True))
    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_manifest_runs WHERE tenant_id = $1", a) == 1
