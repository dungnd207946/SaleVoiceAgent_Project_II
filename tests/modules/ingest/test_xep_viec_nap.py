"""Cổng nạp đặt việc lên Qdrant — bảng luật theo entity.

Cùng khuôn `test_nap.py`: gọi THẲNG `service.nap_lo` bằng `api_pool` (role `portal_api`),
không qua HTTP. Kiểm ở tầng `control.jobs` vì đó là ranh giới thật giữa cổng nạp và
pipeline nhúng — cổng nạp không nhúng gì, nó chỉ đặt việc.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.ingest import contracts, service

pytestmark = pytest.mark.integration

LUC = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


def _bg(entity: str, ma: str, data: dict, *, luc: datetime = LUC, op: str = "upsert"):
    return contracts.BanGhiIn(entity=entity, externalId=ma, op=op, occurredAt=luc, data=data)


def _lo(*bg):
    return contracts.LoNapIn(records=list(bg), syncId="test-viec")


DU_AN = {"name": "Khu đô thị Thử", "region": "Hà Nội", "category": ["chung_cu"]}
PHAN_KHU = {"projectExternalId": "P1", "name": "Phân khu A"}
CAN = {
    "projectExternalId": "P1",
    "zoneExternalId": "Z1",
    "unitCode": "A-1203",
    "saleStatus": "available",
    "productType": "chung_cu",
    "priceVnd": 4850000000,
}
ANH = {
    "projectExternalId": "P1",
    "mediaUrl": "https://cdn.thu.vn/phoi-canh.jpg",
    "contentType": "image",
    "category": "tong_quan",
}
TAI_LIEU_CO_CHU = {"projectExternalId": "P1", "title": "Bảng giá tháng 8", "body": "Giá từ 45 triệu/m²"}
TAI_LIEU_CHI_TEP = {"projectExternalId": "P1", "title": "Chính sách bán hàng", "fileUrl": "tenants/x/csbh.docx"}


async def _viec(pool, tenant_id: str, kind: str) -> list[dict]:
    """Payload mọi việc `kind` của tenant, cũ → mới."""
    rows = await pool.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id",
        tenant_id,
        kind,
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"] for r in rows]


async def test_du_an_va_phan_khu_gop_thanh_mot_viec_cua_du_an(api_pool, hai_tenant):
    """Phân khu là khối con của doc dự án (spec 2026-08-19) — hai bản ghi, MỘT việc nạp."""
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("zone", "Z1", PHAN_KHU)),
        dry_run=False,
    )
    assert ra.accepted == 2, ra.results

    viec = await _viec(api_pool, a, "kb_index")
    assert sorted(v["entity"] for v in viec) == ["projects"], viec


async def test_can_khong_dat_viec_nao(api_pool, hai_tenant):
    """`units` không nhúng — agent lọc căn bằng SQL trên cột thật."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("zone", "Z1", PHAN_KHU), _bg("unit", "U1", CAN)),
        dry_run=False,
    )
    viec = await _viec(api_pool, a, "kb_index")
    assert all(v["entity"] != "units" for v in viec), viec


async def test_anh_dat_viec_thumb_chu_khong_dat_viec_nap(api_pool, hai_tenant):
    """Đặt nạp thẳng thì point mang `thumb_url` rỗng vĩnh viễn và không gì kích hoạt lại."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN), _bg("media", "M1", ANH)), dry_run=False
    )
    thumb = await _viec(api_pool, a, "kb_thumb")
    nap = await _viec(api_pool, a, "kb_index")
    assert [v["entity"] for v in thumb] == ["media"], thumb
    assert all(v["entity"] != "media" for v in nap), nap


async def test_tai_lieu_co_body_dat_viec_nap(api_pool, hai_tenant):
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("document", "D1", TAI_LIEU_CO_CHU)),
        dry_run=False,
    )
    nap = await _viec(api_pool, a, "kb_index")
    assert any(v["entity"] == "documents" for v in nap), nap
    assert await _viec(api_pool, a, "kb_thumb") == []


async def test_tai_lieu_chi_co_tep_dat_viec_thumb_va_tu_duyet(api_pool, hai_tenant):
    """Chuỗi thumb → bóc chữ → nạp. `tu_duyet` bỏ van duyệt OCR vì tenant dùng API
    không có ai ngồi trong portal để duyệt (quyết định #3 của spec)."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("document", "D2", TAI_LIEU_CHI_TEP)),
        dry_run=False,
    )
    thumb = await _viec(api_pool, a, "kb_thumb")
    assert len(thumb) == 1, thumb
    assert thumb[0]["entity"] == "documents"
    assert thumb[0]["tu_duyet"] is True, thumb[0]
    assert await _viec(api_pool, a, "kb_index") != [], "dự án vẫn phải có việc nạp"


async def test_payload_viec_mang_project_code(api_pool, hai_tenant):
    """Chỉ báo tiến độ đếm theo khoá này; việc thiếu nó không đếm vào dự án nào."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("zone", "Z1", PHAN_KHU), _bg("media", "M1", ANH)),
        dry_run=False,
    )
    moi = await _viec(api_pool, a, "kb_index") + await _viec(api_pool, a, "kb_thumb")
    assert moi, "không có việc nào được đặt"
    assert all(v.get("project_code") for v in moi), moi


async def test_day_lai_y_het_khong_nhan_doi_viec(api_pool, hai_tenant):
    """Hai hàm đặt việc tự gộp khi record đã có việc cùng loại đang `queued`."""
    a, _ = hai_tenant
    lo = _lo(_bg("project", "P1", DU_AN))
    await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)
    await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)
    assert len(await _viec(api_pool, a, "kb_index")) == 1


async def test_viec_thuoc_dung_tenant(api_pool, hai_tenant):
    a, b = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)
    assert len(await _viec(api_pool, a, "kb_index")) == 1
    assert await _viec(api_pool, b, "kb_index") == []


async def test_stale_khong_dat_viec(api_pool, hai_tenant):
    """Bản ghi cũ hơn không được chiếu, nên không có việc nào — `chieu_mot` không chạy."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN, luc=LUC)), dry_run=False)
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN | {"region": "Đà Nẵng"}, luc=LUC - timedelta(hours=1))),
        dry_run=False,
    )
    assert len(await _viec(api_pool, a, "kb_index")) == 1, "lượt stale không được đặt việc thứ hai"


async def test_con_cho_cha_dat_viec_dung_luc_cha_toi(api_pool, hai_tenant):
    """Con tới trước cha nằm chờ, KHÔNG có việc. Cha chiếu xong thì lan truyền đặt việc
    cho cả con — đường `_chieu_con_dang_cho`, đường mà mọi bản ghi tới trước cha đi qua."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("zone", "Z9", {"projectExternalId": "P9", "name": "PK"})),
        dry_run=False,
    )
    assert await _viec(api_pool, a, "kb_index") == [], "con đang chờ cha không được đặt việc"

    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P9", DU_AN, luc=LUC + timedelta(minutes=1))), dry_run=False
    )
    bang = sorted(v["entity"] for v in await _viec(api_pool, a, "kb_index"))
    assert bang == ["projects"], bang


async def test_op_delete_khong_dat_viec_nap(api_pool, hai_tenant):
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("document", "D1", TAI_LIEU_CO_CHU)),
        dry_run=False,
    )
    truoc = len(await _viec(api_pool, a, "kb_index"))
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("document", "D1", {}, op="delete", luc=LUC + timedelta(hours=1))),
        dry_run=False,
    )
    assert len(await _viec(api_pool, a, "kb_index")) == truoc, "op:delete không được đặt việc nạp"
    assert await _viec(api_pool, a, "kb_delete") != [], "op:delete vẫn phải xếp việc xoá point"


async def test_roi_published_chi_xoa_point_khong_nap(api_pool, hai_tenant):
    """Hai việc chống nhau: nạp-rồi-xoá tiêu một lượt embed cho point bị xoá ngay sau đó.

    ⚠️ PHẢI cho worker «chạy xong» việc của lô đầu trước khi đẩy lô thứ hai. Không làm
    vậy thì phép gộp việc-đang-chờ (`_CAU_DA_CHO` chỉ gộp `queued`) hấp thụ luôn việc nạp
    thừa, phép đếm không thấy gì, và test XANH kể cả khi guard không tồn tại — đúng thứ
    đã xảy ra ở bản đầu của bài này.
    """
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("document", "D1", TAI_LIEU_CO_CHU)),
        dry_run=False,
    )
    truoc = [v for v in await _viec(api_pool, a, "kb_index") if v["entity"] == "documents"]
    # Đúng như `core/jobs._finish` làm. `state` chỉ nhận queued|running|success|failed
    # (CHECK của `0006`), và `_CAU_DA_CHO` chỉ gộp `queued` — nên đây là cách mô phỏng
    # «worker đã chạy xong» mà không phải dựng cả một worker.
    await api_pool.execute("UPDATE control.jobs SET state = 'success', finished_at = now() WHERE tenant_id = $1", a)

    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("document", "D1", TAI_LIEU_CO_CHU | {"status": "archived"}, luc=LUC + timedelta(hours=1))),
        dry_run=False,
    )
    sau = [v for v in await _viec(api_pool, a, "kb_index") if v["entity"] == "documents"]
    assert len(sau) == len(truoc), "lượt rời published không được đặt thêm việc nạp"
    assert await _viec(api_pool, a, "kb_delete") != [], "rời published phải xếp việc xoá point"


LINK_360 = "https://kuula.co/share/collection/7MgHS?logo=1&fs=1"


async def test_link360_dat_viec_nap_cho_hang_media_tour(api_pool, hai_tenant):
    """Hàng media tour sinh ra mà không có point ⇒ `send_media` không bao giờ gửi được tour."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P360", DU_AN | {"link360": LINK_360})), dry_run=False
    )
    async with tenant_conn(api_pool, a) as conn:
        mid = await conn.fetchval(
            "SELECT id FROM tenant_data.media WHERE tenant_id = portal.current_tenant()  AND content_type = 'tour_360'"
        )
    assert mid is not None, "chưa sinh hàng media tour"
    nap = await _viec(api_pool, a, "kb_index")
    assert any(v["entity"] == "media" and v["record_id"] == mid for v in nap), nap
    assert await _viec(api_pool, a, "kb_thumb") == [], "tour là một link, không có ảnh để thu nhỏ"


async def test_bo_link360_xep_viec_xoa_point_cua_hang_tour(api_pool, hai_tenant):
    """Hàng bị DELETE thật. Point cũ sống sót ⇒ agent gửi cho khách một link tour đã chết."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P360", DU_AN | {"link360": LINK_360})), dry_run=False
    )
    async with tenant_conn(api_pool, a) as conn:
        mid = await conn.fetchval(
            "SELECT id FROM tenant_data.media WHERE tenant_id = portal.current_tenant()  AND content_type = 'tour_360'"
        )
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P360", DU_AN | {"link360": ""}, luc=LUC + timedelta(minutes=1))),
        dry_run=False,
    )
    xoa = await _viec(api_pool, a, "kb_delete")
    assert any(v.get("entity") == "media" and v.get("record_id") == mid for v in xoa), xoa


async def _so_viec(pool, tenant_id: str, kind: str) -> int:
    return await pool.fetchval("SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = $2", tenant_id, kind)


async def test_lo_dau_tien_xep_viec_dung_collection(api_pool, hai_tenant):
    """Không có bước này thì job index bắn vào collection chưa tồn tại và chết 404.

    Trước 2026-08-18, đường DUY NHẤT dựng collection là nút «Đồng bộ tri thức», nên một
    khách vừa onboard đẩy dữ liệu lên sẽ thấy mọi job hỏng — đã sập thật trên EC2 với
    tenant mới, và trên dev với `sunrise`.
    """
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)
    assert await _so_viec(api_pool, a, "kb_provision") == 1


async def test_viec_dung_collection_xep_TRUOC_viec_nap(api_pool, hai_tenant):
    """Thứ tự id quyết định thứ tự worker nhấc. Xếp sau việc nạp thì lô đầu vẫn 404."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)

    id_dung = await api_pool.fetchval(
        "SELECT min(id) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_provision'", a
    )
    id_nap = await api_pool.fetchval("SELECT min(id) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", a)
    assert id_dung < id_nap, f"provision #{id_dung} phải đứng trước index #{id_nap}"


async def test_lo_sau_khong_xep_lai_viec_dung_collection(api_pool, hai_tenant):
    """Một workspace chỉ cần dựng một lần. Xếp mỗi lô là rác hàng đợi cho khách đẩy liên tục."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P2", DU_AN)), dry_run=False)
    assert await _so_viec(api_pool, a, "kb_provision") == 1


async def test_dry_run_khong_xep_viec_dung_collection(api_pool, hai_tenant):
    """`dryRun` không được ghi GÌ — kể cả một hàng hàng đợi."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=True)
    assert await _so_viec(api_pool, a, "kb_provision") == 0
