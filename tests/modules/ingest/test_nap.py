"""Đường nạp — hợp đồng, thứ tự tới, idempotency, dryRun, cách ly.

Gọi THẲNG `service.nap_lo` bằng `api_pool` (role `portal_api`) chứ không qua HTTP:
lớp router chỉ làm hai việc — đổi Bearer lấy tenant, và chuyển tham số. Test qua
HTTP cho toàn bộ nghiệp vụ sẽ phải dựng phiên + token cho mỗi bài, đổi lấy đúng
hai dòng độ phủ. Đường HTTP có bài riêng ở `test_router.py`.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.ingest import contracts, repo, service

pytestmark = pytest.mark.integration

LUC = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


def _bg(entity: str, ma: str, data: dict, *, luc: datetime = LUC, op: str = "upsert"):
    return contracts.BanGhiIn(entity=entity, externalId=ma, op=op, occurredAt=luc, data=data)


def _lo(*bg):
    return contracts.LoNapIn(records=list(bg), syncId="test")


DU_AN = {"name": "Vinhomes Thử", "region": "Hà Nội", "category": ["chung_cu"]}
PHAN_KHU = {"projectExternalId": "P1", "name": "Phân khu A"}
CAN = {
    "projectExternalId": "P1",
    "zoneExternalId": "Z1",
    "unitCode": "A-1203",
    "saleStatus": "sold",
    "productType": "chung_cu",
    "priceVnd": 4850000000,
}


async def test_con_toi_truoc_cha_van_chieu_duoc_trong_cung_lo(api_pool, hai_tenant):
    """Căn đứng ĐẦU lô, dự án đứng cuối — cả ba vẫn vào bảng.

    Đây là hành vi trung tâm của cổng nạp: hệ thống bên khách bắn sự kiện theo thứ
    tự của NÓ, không theo cây phụ thuộc của mình. Bắt họ sắp xếp trước khi gửi là
    đẩy một việc khó sang phía không có đủ thông tin để làm.
    """
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("unit", "U1", CAN), _bg("zone", "Z1", PHAN_KHU), _bg("project", "P1", DU_AN)),
        dry_run=False,
    )
    assert ra.accepted == 3, ra.results

    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.projects WHERE tenant_id = $1", a) == 1
        can = await conn.fetchrow("SELECT * FROM tenant_data.units WHERE tenant_id = $1", a)
    assert can is not None, "căn không được chiếu — cha tới sau đáng lẽ vẫn giải được"
    assert can["sale_status"] == "sold"
    assert can["external_id"] == "U1"
    # `zone_code` lấy từ CHÍNH phân khu, không từ payload của căn.
    assert can["zone_code"] == "Z1"


async def test_truong_la_di_qua_khong_bi_tu_choi(api_pool, hai_tenant):
    """Quyết định #3 của spec. Hệ thống bên khách sẽ mọc thêm cột theo thời gian;
    biến mỗi lần như thế thành một sự cố bên mình là làm hợp đồng giòn tới mức
    không dùng được."""
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", {**DU_AN, "cot_moi_ben_khach": "gì đó", "them_nua": 42})),
        dry_run=False,
    )
    assert ra.accepted == 1 and ra.rejected == 0


async def test_day_lai_y_het_ra_stale_khong_phai_accepted(api_pool, hai_tenant):
    """Retry của khách là hành vi ĐÚNG, không phải lỗi — nhưng cũng không phải
    một lần ghi mới. Coi nó là `accepted` sẽ reset `cho_cha_*` mỗi lần và tốn
    một lượt chiếu lại vô ích."""
    a, _ = hai_tenant
    lo = _lo(_bg("project", "P1", DU_AN))
    assert (await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)).accepted == 1
    lai = await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)
    assert lai.stale == 1 and lai.accepted == 0


async def test_su_kien_cu_hon_khong_de_len_ban_moi(api_pool, hai_tenant):
    """`occurredAt` là trọng tài, KHÔNG phải giờ nhận.

    Sự kiện về lệch thứ tự là chuyện bình thường của đẩy bất đồng bộ. Lấy giờ nhận
    làm chuẩn thì một sự kiện cũ tới muộn sẽ ghi đè trạng thái mới — đúng cách một
    căn đã bán quay lại «còn hàng».
    """
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P1", DU_AN),
            _bg("zone", "Z1", PHAN_KHU),
            _bg("unit", "U1", {**CAN, "saleStatus": "sold"}),
        ),
        dry_run=False,
    )
    cu = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("unit", "U1", {**CAN, "saleStatus": "available"}, luc=LUC - timedelta(hours=1))),
        dry_run=False,
    )
    assert cu.stale == 1

    async with tenant_conn(api_pool, a) as conn:
        assert (await conn.fetchval("SELECT sale_status FROM tenant_data.units WHERE tenant_id = $1", a)) == "sold"


async def test_payload_sai_bi_tu_choi_va_vao_bang_loi(api_pool, hai_tenant):
    """Lý do phải đủ để bên khách TỰ SỬA — dưới schema cố định đây là đường phản
    hồi duy nhất họ có."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("zone", "Z1", PHAN_KHU),
            _bg("unit", "U1", {**CAN, "saleStatus": "giu_cho", "priceVnd": "4,85 tỷ"}),
        ),
        dry_run=False,
    )
    assert ra.rejected == 1
    trang = await service.liet_ke_loi(api_pool, a)
    theo_truong = {e.truong: e.lyDo for e in trang.loi}
    assert "giu_cho" in theo_truong["saleStatus"]
    # Liệt kê giá trị hợp lệ NGAY trong câu: bắt họ mở tài liệu để biết ba chữ là
    # thêm một vòng lặp không cần thiết.
    assert "available" in theo_truong["saleStatus"]
    assert "4,85 tỷ" in theo_truong["priceVnd"]


async def test_thieu_truong_bat_buoc_bao_dung_mot_lan(api_pool, hai_tenant):
    """Gửi SAI GIÁ TRỊ không được đọc thành THIẾU TRƯỜNG.

    Bản đầu xét «thiếu» theo cột đã dựng được, nên một `saleStatus` sai giá trị ăn
    hai lỗi — và dev bên khách đi thêm một trường vốn đã có sẵn.
    """
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("zone", "Z1", PHAN_KHU)), dry_run=False)
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("unit", "U1", {**CAN, "saleStatus": "giu_cho"})),
        dry_run=False,
    )
    trang = await service.liet_ke_loi(api_pool, a)
    truong = [e.truong for e in trang.loi]
    assert truong.count("saleStatus") == 1, truong


async def test_dry_run_khong_ghi_gi(api_pool, hai_tenant):
    """Ba bảng và một cột, không thứ nào được đổi.

    Vế này mới là bài quan trọng: một `dryRun` ghi lén trông y hệt một `dryRun`
    đúng cho tới lúc ai đó đọc số liệu.
    """
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("unit", "U1", {**CAN, "saleStatus": "giu_cho"})),
        dry_run=True,
    )
    assert ra.dryRun is True and ra.accepted == 1 and ra.rejected == 1

    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_records WHERE tenant_id=$1", a) == 0
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_errors WHERE tenant_id=$1", a) == 0
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.projects WHERE tenant_id=$1", a) == 0


async def test_dry_run_canh_bao_cha_chua_toi_nhung_van_accepted(api_pool, hai_tenant):
    """Cha chưa tới là CẢNH BÁO, không phải lỗi — nó thường nghĩa là ghép sai
    `externalId`, và biết trước điều đó là đúng thứ một lượt thử để làm."""
    a, _ = hai_tenant
    ra = await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("unit", "U1", CAN)), dry_run=True)
    assert ra.results[0].status == "accepted"
    assert "projectExternalId" in ra.results[0].reason


async def test_xoa_la_xoa_MEM(api_pool, hai_tenant):
    """`op: delete` ⇒ `status='archived'`, không `DELETE` cứng: bản ghi có thể đã
    lên Qdrant và cần đường gỡ."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", {}, luc=LUC + timedelta(hours=1), op="delete")),
        dry_run=False,
    )
    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetchrow("SELECT status FROM tenant_data.projects WHERE tenant_id = $1", a)
    assert hang is not None, "xoá cứng — mất đường gỡ khỏi Qdrant"
    assert hang["status"] == "archived"


async def test_token_cua_tenant_A_khong_ghi_duoc_sang_tenant_B(api_pool, hai_tenant):
    """CÁCH LY. Nạp cho A rồi đọc bằng kết nối của B — đáp án đúng luôn là «không
    thấy gì»."""
    a, b = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)

    async with tenant_conn(api_pool, b) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.projects WHERE tenant_id=$1", a) == 0
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_records") == 0


async def test_hai_tenant_dung_cung_external_id_khong_dam_nhau(api_pool, hai_tenant):
    """`external_id` là mã BÊN KHÁCH — hai khách khác nhau trùng mã là chuyện
    thường, không phải xung đột."""
    a, b = hai_tenant
    for t in (a, b):
        ra = await service.nap_lo(api_pool, tenant_id=t, lo=_lo(_bg("project", "P1", DU_AN)), dry_run=False)
        assert ra.accepted == 1, (t, ra.results)

    for t in (a, b):
        async with tenant_conn(api_pool, t) as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM tenant_data.projects WHERE tenant_id=$1 AND external_id='P1'", t
                )
                == 1
            )


async def test_thong_ke_dem_dung_tenant(api_pool, hai_tenant):
    a, b = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P1", DU_AN), _bg("project", "P2", {**DU_AN, "name": "Hai"})),
        dry_run=False,
    )
    # Một bản ghi đang chờ cha — ĐÃ nhận nhưng CHƯA vào kho, không được tính vào
    # `soGhiDuoc24h` (finding #3: bản cũ đếm cả hàng chưa-thật-vào-kho).
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("zone", "Z-CHO-TK", {"projectExternalId": "P-CHUA-CO", "name": "Khu chờ"})),
        dry_run=False,
    )
    await service.nap_lo(api_pool, tenant_id=b, lo=_lo(_bg("project", "P9", DU_AN)), dry_run=False)

    tq_a = await service.tong_quan(api_pool, a, diem_nap="x", docs_url="y")
    tq_b = await service.tong_quan(api_pool, b, diem_nap="x", docs_url="y")
    assert tq_a.thongKe.soNhan24h == 3
    assert tq_b.thongKe.soNhan24h == 1
    assert tq_a.thongKe.soGhiDuoc24h == 2, "bản ghi đang chờ cha chưa vào kho — không được đếm"


# ─── Review MR !55 — hai ca «accepted nhưng không bao giờ vào bảng» ──────────
#
# Cả hai đều lọt qua `kiem()` rồi chết ở tầng dưới, và cả hai đều KHÔNG hiện ra ở
# đối soát §7: `ingest_records` có bản ghi với đúng `occurred_at` khớp bản kê
# khách gửi, nên `so_ban_ke` không thấy lệch cũng không thấy mất tích. Đúng loại
# «im lặng vĩnh viễn» mà cả cơ chế đối soát được dựng ra để chặn.


async def test_truong_bat_buoc_gui_null_bi_tu_choi_khong_lam_hong_ca_lo(api_pool, hai_tenant):
    """`productType: null` — CÓ MẶT trong payload nhưng rỗng.

    `kiem()` xét «thiếu» bằng `t.ten not in data` nên null lọt; rồi `_enum(None)`
    trả None nên cột không được dựng; rồi `_upsert` INSERT thiếu một cột NOT NULL
    KHÔNG DEFAULT ⇒ `NotNullViolationError` ném từ TRONG `tenant_conn` ⇒ rollback
    CẢ LÔ, kể cả những bản ghi đã báo `accepted`.

    Đó là vi phạm trực tiếp lời hứa §3.1: «một bản ghi hỏng không được làm rớt
    499 bản còn lại».
    """
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P1", DU_AN),
            _bg("zone", "Z1", PHAN_KHU),
            _bg("unit", "U-NULL", {**CAN, "productType": None}),
        ),
        dry_run=False,
    )

    xau = next(k for k in ra.results if k.externalId == "U-NULL")
    assert xau.status == "rejected", "trường bắt buộc gửi null phải bị TỪ CHỐI"
    assert xau.field == "productType"

    # Và quan trọng hơn: hai bản ghi hợp lệ trong CÙNG lô phải sống sót.
    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.projects WHERE tenant_id=$1", a) == 1
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.zones WHERE tenant_id=$1", a) == 1


async def test_thieu_han_khoa_cha_bi_tu_choi_chu_khong_ket_vinh_vien(api_pool, hai_tenant):
    """Zone KHÔNG có `projectExternalId` — khác hẳn «cha chưa tới».

    `QUAN_HE` bị loại khỏi vòng kiểm của `kiem()` (nó là khoá giải, không phải
    cột), nên sự hiện diện của nó chưa từng được kiểm. Ở chiếu, `_giai_cha` ném
    `ChuaGiaiDuocCha` và bản trước `_chieu()` nuốt để «thử lại lượt sau» — nhưng
    payload không hề chứa mã cha nên lượt sau KHÔNG BAO GIỜ tới.

    Hai ca phải tách bạch: thiếu hẳn khoá = lỗi của khách, báo ngay; có khoá mà
    cha chưa nạp = bình thường, chờ được.
    """
    a, _ = hai_tenant
    ra = await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("zone", "Z-MO-COI", {"name": "Khu A"})), dry_run=False)

    assert ra.results[0].status == "rejected"
    assert ra.results[0].field == "projectExternalId"

    async with tenant_conn(api_pool, a) as conn:
        ket = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.ingest_records WHERE tenant_id=$1 AND cho_cha_ma IS NOT NULL", a
        )
    assert ket == 0, "không được để lại bản ghi kẹt vĩnh viễn ở trạng thái chờ cha"


async def test_khoa_cha_co_nhung_cha_chua_toi_thi_VAN_cho_duoc(api_pool, hai_tenant):
    """Mặt còn lại của bài trên — đừng sửa quá tay.

    Có `projectExternalId` nhưng dự án chưa nạp ⇒ KHÔNG phải lỗi, phải nằm chờ.
    Bài này đỏ nếu ai đó sửa bài trên bằng cách từ chối mọi ca chưa giải được cha.
    """
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("zone", "Z-CHO", {"projectExternalId": "P-CHUA-CO", "name": "Khu B"})),
        dry_run=False,
    )
    assert ra.results[0].status == "accepted", "cha chưa tới là chuyện bình thường của đẩy bất đồng bộ"

    async with tenant_conn(api_pool, a) as conn:
        cho = await conn.fetchrow(
            "SELECT cho_cha_entity, cho_cha_ma FROM tenant_data.ingest_records "
            "WHERE tenant_id=$1 AND external_id='Z-CHO'",
            a,
        )
    assert cho is not None, "phải nằm chờ lượt sau, không bị vứt"
    assert (cho["cho_cha_entity"], cho["cho_cha_ma"]) == ("project", "P-CHUA-CO"), "cờ phải trỏ đúng cha còn thiếu"


async def test_ban_ghi_hong_san_trong_bang_khong_lam_chet_lo_moi(api_pool, hai_tenant):
    """Bản ghi thô ĐÃ NẰM SẴN, đang chờ đúng cha này, mà payload không qua được
    phép kiểm hiện hành.

    Cha (`P-HONG`) chiếu xong ⇒ `_chieu_con_dang_cho` nhặt hàng đang chờ nó ⇒
    `chieu_mot` kiểm lại và ném `RuntimeError` (payload hỏng, không phải thiếu
    cha) ⇒ nhánh `except Exception` của `_chieu_con_dang_cho` ghi một dòng
    `ingest_errors` và GIỮ NGUYÊN cờ chờ — không kéo lô đang nạp `P-HONG` theo,
    đúng lời hứa §3.1 ở tầng chiếu thay vì tầng nhận.
    """
    a, _ = hai_tenant
    async with tenant_conn(api_pool, a) as conn:
        # Chèn thẳng, KHÔNG qua `nap_lo` — mô phỏng hàng đang chờ cha với payload
        # hỏng (thiếu `projectExternalId` dù đã được đánh dấu chờ đúng cha đó).
        await conn.execute(
            """INSERT INTO tenant_data.ingest_records
                   (tenant_id, entity, external_id, op, occurred_at, payload,
                    cho_cha_entity, cho_cha_ma)
               VALUES ($1, 'zone', 'Z-RAC-CU', 'upsert', $2, '{"name": "mồ côi"}'::jsonb,
                       'project', 'P-HONG')""",
            a,
            LUC,
        )

    ra = await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P-HONG", DU_AN)), dry_run=False)
    assert ra.accepted == 1, "lô mới phải sống sót bất chấp hàng rác đang chờ nó"

    async with tenant_conn(api_pool, a) as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM tenant_data.projects WHERE tenant_id=$1 AND external_id='P-HONG'", a
            )
            == 1
        )
        # Hàng rác phải được ghi nhận, không nuốt lặng.
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM tenant_data.ingest_errors WHERE tenant_id=$1 AND external_id='Z-RAC-CU'", a
            )
            >= 1
        ), "phải để lại dấu vết ở bảng lỗi, không nuốt lặng"
        cho = await conn.fetchrow(
            "SELECT cho_cha_entity, cho_cha_ma FROM tenant_data.ingest_records "
            "WHERE tenant_id=$1 AND external_id='Z-RAC-CU'",
            a,
        )
    assert (cho["cho_cha_entity"], cho["cho_cha_ma"]) == ("project", "P-HONG"), (
        "phải GIỮ cờ chờ — lỗi khác thiếu-cha không được xoá cờ"
    )


async def test_code_dat_ma_du_an_luc_tao(api_pool, hai_tenant):
    """`data.code` (tuỳ chọn) quyết định `project_code` lúc TẠO — thay cho suy từ
    `externalId`. Ca thật (AINA 2026-08-18): externalId là UUID nên mã thành chuỗi
    hex 36 ký tự — agent phải chép nguyên văn vào mọi tool call (tốn ~20 token/lần
    trên đường nóng TTFA của voice) và người trực đọc report không nhận ra dự án
    nào. Khách gửi slug của chính họ thì mã thành TỪ THẬT, rẻ và chép không sai."""
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "dcac8a12-705d-42c7-bc7c-715dac569093", {**DU_AN, "code": "sunshine-city-hanoi"})),
        dry_run=False,
    )
    assert ra.accepted == 1, ra
    async with tenant_conn(api_pool, a) as conn:
        ma = await conn.fetchval(
            "SELECT project_code FROM tenant_data.projects WHERE tenant_id=$1 AND external_id=$2",
            a,
            "dcac8a12-705d-42c7-bc7c-715dac569093",
        )
    assert ma == "SUNSHINE_CITY_HANOI", ma


async def test_code_trung_thi_hau_to_nhu_ma_suy(api_pool, hai_tenant):
    """Hai externalId khác nhau cùng `code` → cái sau mang hậu tố `_2`, cùng luật
    chống đụng của mã suy từ externalId — `code` là GỢI Ý, không phải quyền ghi đè
    tính duy nhất."""
    a, _ = hai_tenant
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "uuid-mot", {**DU_AN, "code": "eco-park"}),
            _bg("project", "uuid-hai", {**DU_AN, "code": "eco-park"}),
        ),
        dry_run=False,
    )
    assert ra.accepted == 2, ra
    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetch(
            "SELECT external_id, project_code FROM tenant_data.projects "
            "WHERE tenant_id=$1 AND external_id IN ('uuid-mot','uuid-hai') ORDER BY external_id",
            a,
        )
    ma = {h["external_id"]: h["project_code"] for h in hang}
    assert ma == {"uuid-mot": "ECO_PARK_2", "uuid-hai": "ECO_PARK"} or ma == {
        "uuid-mot": "ECO_PARK",
        "uuid-hai": "ECO_PARK_2",
    }, ma


async def test_code_bi_bo_qua_khi_update(api_pool, hai_tenant):
    """`project_code` là khoá neo lan rộng (units trỏ theo, payload Qdrant mang nó,
    `project_interest` trong phiên agent đang sống) — đổi nó khi update là re-link
    cả cây. Nên `code` CHỈ có tác dụng lúc tạo; update mang code khác bị bỏ qua."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P-CODE", {**DU_AN, "code": "ten-dau"})), dry_run=False
    )
    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P-CODE", {**DU_AN, "code": "ten-moi"}, luc=LUC + timedelta(minutes=1))),
        dry_run=False,
    )
    assert ra.accepted == 1, ra
    async with tenant_conn(api_pool, a) as conn:
        ma = await conn.fetchval(
            "SELECT project_code FROM tenant_data.projects WHERE tenant_id=$1 AND external_id='P-CODE'", a
        )
    assert ma == "TEN_DAU", f"update không được đổi mã: {ma}"


async def test_unit_khong_co_zone_van_nap_duoc(api_pool, hai_tenant):
    """0902 đã nới `units.zone_code` nullable vì một tenant THẬT có 3015/3015 căn
    không phân khu — hợp đồng bắt buộc `zoneExternalId` là quyết định trên schema
    đã chết 25 revision trước (review finding #13). ERP không có khái niệm phân
    khu phải nạp được, không phải đi bịa zone placeholder."""
    a, _ = hai_tenant
    lo = _lo(
        _bg("project", "P-NOZONE", {"name": "Dự án không phân khu"}),
        _bg(
            "unit",
            "U-NOZONE",
            {
                "projectExternalId": "P-NOZONE",
                "unitCode": "A101",
                "saleStatus": "available",
                "productType": "biet_thu",
            },
        ),
    )
    ra = await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)
    assert [k.status for k in ra.results] == ["accepted", "accepted"]

    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetchrow(
            "SELECT zone_code, status FROM tenant_data.units WHERE tenant_id = $1 AND external_id = 'U-NOZONE'",
            a,
        )
    assert hang is not None and hang["zone_code"] is None


async def test_delete_cung_moc_thoi_gian_van_thang_upsert(api_pool, hai_tenant):
    """ERP giữ MỘT updated_at mỗi dòng thường export tombstone delete với đúng mốc
    cuối cùng đã biết. Guard strict `<` mù op từng drop nó thành `stale` — căn đã
    bán ở lại `published` vĩnh viễn (review finding #10). Luật tie-break: cùng mốc
    thì tombstone thắng; chiều ngược (upsert hồi sinh delete cùng mốc) vẫn stale."""
    a, _ = hai_tenant

    moc = datetime.fromisoformat("2026-08-15T09:00:00+00:00")
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-TIE", {"name": "X"}, luc=moc),
        ),
        dry_run=False,
    )

    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-TIE", {}, op="delete", luc=moc),
        ),
        dry_run=False,
    )
    assert ra.results[0].status == "accepted", "delete cùng mốc phải thắng upsert"

    ra = await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-TIE", {"name": "X"}, luc=moc),
        ),
        dry_run=False,
    )
    assert ra.results[0].status == "stale", "upsert cùng mốc KHÔNG hồi sinh bản đã xoá"


# ─── Task 5 — chiếu đồng bộ per-record, pending set `cho_cha` ────────────────


async def test_chieu_hong_thi_ban_tho_cung_khong_ghi_va_day_lai_nguyen_van_duoc(api_pool, hai_tenant):
    """Finding #3 — lớp «projected dù hỏng, kẹt vĩnh viễn» phải chết theo thiết kế:
    chiếu hỏng ⇒ rollback cả bản thô ⇒ đẩy lại CÙNG occurredAt vẫn được nhận."""
    a, _ = hai_tenant
    lo = _lo(_bg("project", "P-FAIL", {"name": "X"}))
    with patch("portal.modules.ingest.chieu._upsert", side_effect=RuntimeError("nổ giả lập")):
        ra = await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)
    assert ra.results[0].status == "rejected"

    async with tenant_conn(api_pool, a) as conn:
        so = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.ingest_records WHERE tenant_id=$1 AND external_id='P-FAIL'", a
        )
    assert so == 0, "bản thô phải rollback cùng savepoint"

    ra = await service.nap_lo(api_pool, tenant_id=a, lo=lo, dry_run=False)  # nguyên văn
    assert ra.results[0].status == "accepted", "không còn guard nào chặn lần đẩy lại"


async def test_cha_toi_sau_mo_khoa_lan_truyen_zone_roi_unit(api_pool, hai_tenant):
    """unit chờ project; project tới ⇒ unit dời sang chờ zone; zone tới ⇒ unit vào kho."""
    a, _ = hai_tenant
    du_lieu_unit = {
        "projectExternalId": "P-LT",
        "zoneExternalId": "Z-LT",
        "unitCode": "A1",
        "saleStatus": "available",
        "productType": "chung_cu",
    }
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("unit", "U-LT", du_lieu_unit)), dry_run=False)
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P-LT", {"name": "X"})), dry_run=False)

    async with tenant_conn(api_pool, a) as conn:
        cho = await conn.fetchrow(
            "SELECT cho_cha_entity, cho_cha_ma FROM tenant_data.ingest_records "
            "WHERE tenant_id=$1 AND external_id='U-LT'",
            a,
        )
    assert (cho["cho_cha_entity"], cho["cho_cha_ma"]) == ("zone", "Z-LT"), "cờ phải DỜI sang cha thứ hai"

    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("zone", "Z-LT", {"name": "PK", "projectExternalId": "P-LT"})),
        dry_run=False,
    )
    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetchrow(
            "SELECT unit_code FROM tenant_data.units WHERE tenant_id=$1 AND external_id='U-LT'", a
        )
    assert hang is not None, "zone chiếu xong phải lan truyền mở khoá unit"


async def test_hang_cho_khong_lien_quan_khong_bi_dung_va_khong_chan_ban_ghi_moi(api_pool, hai_tenant):
    """Finding #7 — pending set tra TRÚNG ĐÍCH theo `(cha_entity, cha_ma)`, không
    quét backlog: một đống hàng chờ cha KHÔNG liên quan (`P-KHONG-BAO-GIO-TOI`,
    cha không bao giờ tới) không được ĐỤNG TỚI, và không chặn một bản ghi mới
    hoàn toàn khác (`P-TUOI`) vào kho ngay."""
    a, _ = hai_tenant
    async with tenant_conn(api_pool, a) as conn:
        for i in range(30):
            await conn.execute(
                """INSERT INTO tenant_data.ingest_records
                       (tenant_id, entity, external_id, op, occurred_at, payload,
                        cho_cha_entity, cho_cha_ma)
                   VALUES ($1, 'zone', $2, 'upsert', $3, '{}'::jsonb, 'project', 'P-KHONG-BAO-GIO-TOI')""",
                a,
                f"Z-CHO-{i}",
                LUC - timedelta(days=1),
            )
    ra = await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P-TUOI", {"name": "Mới"})), dry_run=False)
    assert ra.results[0].status == "accepted"
    async with tenant_conn(api_pool, a) as conn:
        co = await conn.fetchval("SELECT 1 FROM tenant_data.projects WHERE tenant_id=$1 AND external_id='P-TUOI'", a)
        assert co == 1
        con_cho = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.ingest_records WHERE tenant_id=$1 AND cho_cha_ma = 'P-KHONG-BAO-GIO-TOI'",
            a,
        )
    assert con_cho == 30, "hàng chờ không liên quan không được đụng tới"


async def test_lan_truyen_qua_tran_giu_co_va_bao_mot_dong_loi(api_pool, hai_tenant, monkeypatch):
    """Vượt `TRAN_LAN_TRUYEN`: con còn lại GIỮ NGUYÊN cờ chờ (trạng thái (b), an
    toàn) và có ĐÚNG MỘT dòng lỗi cho CHA GỐC nói lý do dừng — không phải một
    dòng cho mỗi con còn kẹt lại.

    5 con chờ, ngân sách 2 — cũng phủ luôn `LIMIT` của `repo.con_dang_cho`
    (`gioi_han = TRAN_LAN_TRUYEN - da_xu_ly + 1 = 3`): câu SELECT chỉ kéo 3/5
    hàng vào RAM, và phép kiểm quá-trần vẫn phải dừng đúng ở 2 con xử lý — 3 con
    còn lại giữ cờ (1 hàng đã fetch-nhưng-chưa-xử-lý + 2 hàng chưa hề fetch)."""
    a, _ = hai_tenant
    monkeypatch.setattr(service, "TRAN_LAN_TRUYEN", 2)

    async with tenant_conn(api_pool, a) as conn:
        for i in range(5):
            await conn.execute(
                """INSERT INTO tenant_data.ingest_records
                       (tenant_id, entity, external_id, op, occurred_at, payload,
                        cho_cha_entity, cho_cha_ma)
                   VALUES ($1, 'zone', $2, 'upsert', $3, $4::jsonb, 'project', 'P-CAP')""",
                a,
                f"Z-CAP-{i}",
                LUC,
                json.dumps({"name": f"Khu {i}", "projectExternalId": "P-CAP"}),
            )

    ra = await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P-CAP", {"name": "Dự án CAP"})), dry_run=False
    )
    assert ra.results[0].status == "accepted"

    async with tenant_conn(api_pool, a) as conn:
        so_zone = await conn.fetchval("SELECT count(*) FROM tenant_data.zones WHERE tenant_id=$1", a)
        con_cho = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.ingest_records WHERE tenant_id=$1 AND cho_cha_ma IS NOT NULL", a
        )
        so_loi = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.ingest_errors "
            "WHERE tenant_id=$1 AND external_id='P-CAP' AND reason LIKE '%Lan truyền dừng%'",
            a,
        )
    assert so_zone == 2, "chỉ đúng NGÂN SÁCH con được xử lý"
    assert con_cho == 3, "3 con còn lại (đã fetch lẫn chưa fetch) đều phải GIỮ cờ"
    assert so_loi == 1, "đúng MỘT dòng lỗi cho CHA GỐC, không phải một dòng mỗi con kẹt lại"


# ─── Task 6 — latest-wins là THAY THẾ CẢ BẢN GHI, không phải merge cột ───────


async def test_upsert_moi_hon_xoa_duoc_truong_da_set(api_pool, hai_tenant):
    """Finding #6 — `DO UPDATE SET` từng chỉ dựng từ cột CÓ MẶT, còn `kiem()` drop
    None: giá đã rút (`priceVnd: null` hoặc bỏ hẳn key) không bao giờ xoá được,
    agent báo giá cũ vĩnh viễn. Latest-wins nghĩa là BẢN GHI LÀ ẢNH CHỤP."""
    a, _ = hai_tenant
    goc = {
        "projectExternalId": "P-GIA",
        "zoneExternalId": "Z-GIA",
        "unitCode": "B1",
        "saleStatus": "available",
        "productType": "chung_cu",
        "priceVnd": 4850000000,
        "direction": "dong",
    }
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-GIA", {"name": "X"}),
            _bg("zone", "Z-GIA", {"name": "PK", "projectExternalId": "P-GIA"}),
            _bg("unit", "U-GIA", goc),
        ),
        dry_run=False,
    )

    rut_gia = {k: v for k, v in goc.items() if k not in ("priceVnd", "direction")}
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("unit", "U-GIA", rut_gia, luc=LUC + timedelta(hours=1))),
        dry_run=False,
    )

    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetchrow(
            "SELECT price_vnd, direction, unit_code FROM tenant_data.units "
            "WHERE tenant_id = $1 AND external_id = 'U-GIA'",
            a,
        )
    assert hang["price_vnd"] is None and hang["direction"] is None
    assert hang["unit_code"] == "B1", "trường bắt buộc vẫn nguyên"


async def test_media_bo_zone_thi_zone_code_ve_null(api_pool, hai_tenant):
    """Cột khoá cha TUỲ CHỌN (`media.zone_code`/`unit_code`) cùng luật ảnh chụp:
    payload sau bỏ hẳn `zoneExternalId` phải xoá được `zone_code` đã set trước đó,
    không phải giữ nguyên giá trị cũ."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-MZ", {"name": "X"}),
            _bg("zone", "Z-MZ", {"name": "PK", "projectExternalId": "P-MZ"}),
            _bg(
                "media",
                "M-MZ",
                {
                    "projectExternalId": "P-MZ",
                    "zoneExternalId": "Z-MZ",
                    "mediaUrl": "https://cdn.example.com/a.jpg",
                    "contentType": "image",
                    "category": "tong_quan",
                },
            ),
        ),
        dry_run=False,
    )
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg(
                "media",
                "M-MZ",
                {
                    "projectExternalId": "P-MZ",
                    "mediaUrl": "https://cdn.example.com/a.jpg",
                    "contentType": "image",
                    "category": "tong_quan",
                },
                luc=LUC + timedelta(hours=1),
            )
        ),
        dry_run=False,
    )
    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetchrow(
            "SELECT zone_code FROM tenant_data.media WHERE tenant_id = $1 AND external_id = 'M-MZ'", a
        )
    assert hang["zone_code"] is None


async def test_re_push_khong_co_sale_phase_overview_thi_ve_dung_default_cot(api_pool, hai_tenant):
    """THAY-THẾ-TRỌN-BẢN-GHI nghĩa là bản ghi sau upsert phải Y HỆT một INSERT MỚI
    từ cùng payload. `sale_phase` là `NOT NULL DEFAULT 'sap_mo_ban'` — không phải
    một cột nullable như `price_vnd`/`zone_code` — nên vắng mặt phải quay về
    DEFAULT CỦA CHÍNH CỘT (`'sap_mo_ban'`/`''`), không phải `NULL` (sẽ vi phạm
    NOT NULL) và không phải giữ nguyên giá trị cũ (đúng bug finding #6)."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P-DEFAULT", {"name": "X", "salePhase": "dang_ban", "overview": "abc"})),
        dry_run=False,
    )
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P-DEFAULT", {"name": "X"}, luc=LUC + timedelta(hours=1))),
        dry_run=False,
    )
    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetchrow(
            "SELECT sale_phase, overview FROM tenant_data.projects WHERE tenant_id = $1 AND external_id = 'P-DEFAULT'",
            a,
        )
    assert hang["sale_phase"] == "sap_mo_ban"
    assert hang["overview"] == ""


async def test_lan_truyen_hong_khong_giet_lo(api_pool, hai_tenant, monkeypatch):
    """Một câu SQL của tầng lan truyền hỏng (SELECT tra con-đang-chờ) KHÔNG được
    kéo theo cả `nap_lo` — bản ghi gốc vừa chiếu xong vẫn phải `accepted`, đúng
    lời hứa §3.1 ở một tầng sâu hơn."""
    a, _ = hai_tenant

    async def _hong(*args, **kwargs):
        raise RuntimeError("nổ giả lập ở tầng lan truyền")

    monkeypatch.setattr(repo, "con_dang_cho", _hong)

    ra = await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P-CASCADE-HONG", {"name": "X"})), dry_run=False
    )
    assert ra.results[0].status == "accepted"

    async with tenant_conn(api_pool, a) as conn:
        co = await conn.fetchval(
            "SELECT 1 FROM tenant_data.projects WHERE tenant_id=$1 AND external_id='P-CASCADE-HONG'", a
        )
    assert co == 1


async def test_media_tro_unit_cua_du_an_khac_van_ra_dia_chi_nhat_quan(api_pool, hai_tenant):
    """Finding #14 — nhánh unitExternalId từng chỉ lấy `unit_code` (không FK, không
    unique) nên media mang project_code của P1 + unit_code của P2: asset nổi trên
    căn bất kỳ trùng mã. Luật: cha CỤ THỂ NHẤT thắng — trọn bộ địa chỉ lấy từ
    CHÍNH unit, như nhánh zone đã làm từ đầu (docstring repo.zone_theo_ma_ngoai)."""
    a, _ = hai_tenant

    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-A", {"name": "A"}),
            _bg("project", "P-B", {"name": "B"}),
            _bg("zone", "Z-B", {"name": "PK B", "projectExternalId": "P-B"}),
            _bg(
                "unit",
                "U-B",
                {
                    "projectExternalId": "P-B",
                    "zoneExternalId": "Z-B",
                    "unitCode": "B7",
                    "saleStatus": "available",
                    "productType": "chung_cu",
                },
            ),
            _bg(
                "media",
                "M-CHEO",
                {
                    "projectExternalId": "P-A",  # trỏ NHẦM dự án khác
                    "unitExternalId": "U-B",
                    "mediaUrl": "https://cdn.example.com/b7.jpg",
                    "contentType": "image",
                    "category": "noi_that",
                },
            ),
        ),
        dry_run=False,
    )

    async with tenant_conn(api_pool, a) as conn:
        media = await conn.fetchrow(
            "SELECT project_code, zone_code, unit_code FROM tenant_data.media "
            "WHERE tenant_id = portal.current_tenant() AND external_id = 'M-CHEO'"
        )
        unit = await conn.fetchrow(
            "SELECT project_code, zone_code, unit_code FROM tenant_data.units "
            "WHERE tenant_id = portal.current_tenant() AND external_id = 'U-B'"
        )
    assert dict(media) == dict(unit), "media phải mang đúng địa chỉ của unit nó trỏ tới"


# ─── Task 8 — nối vào vòng đời KB: purge Qdrant khi rời `published`, public_url ──


async def test_delete_document_published_xep_job_purge_qdrant(api_pool, hai_tenant):
    """Finding #5 — NT2-1408: xoá qua gateway mà point Qdrant sống sót thì agent
    tiếp tục chào bán thứ đã xoá. Đường manual đã enqueue KIND_DELETE_INDEX ở mọi
    transition rời published; đường ingest phải cùng một luật."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-QD", {"name": "X"}),
            _bg("document", "D-QD", {"projectExternalId": "P-QD", "title": "Bảng giá"}),
        ),
        dry_run=False,
    )
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("document", "D-QD", {}, op="delete", luc=LUC + timedelta(hours=1))),
        dry_run=False,
    )

    async with tenant_conn(api_pool, a) as conn:
        doc_id = await conn.fetchval(
            "SELECT id FROM tenant_data.documents WHERE tenant_id = portal.current_tenant() AND external_id = 'D-QD'"
        )
    job = await api_pool.fetchrow(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete' ORDER BY id DESC LIMIT 1",
        a,
    )
    assert job is not None, "op:delete rời published phải xếp job purge"
    payload = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]
    assert payload.get("entity") == "documents" and payload.get("record_id") == doc_id


async def test_delete_project_purge_theo_anchor_code(api_pool, hai_tenant):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo(_bg("project", "P-ANCHOR", {"name": "X"})), dry_run=False)
    async with tenant_conn(api_pool, a) as conn:
        ma = await conn.fetchval(
            "SELECT project_code FROM tenant_data.projects "
            "WHERE tenant_id = portal.current_tenant() AND external_id = 'P-ANCHOR'"
        )
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P-ANCHOR", {}, op="delete", luc=LUC + timedelta(hours=1))),
        dry_run=False,
    )
    job = await api_pool.fetchrow(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete' ORDER BY id DESC LIMIT 1",
        a,
    )
    payload = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]
    assert payload.get("anchor_code") == ma, "project purge theo anchor_code — cascade cả cây con"


async def test_media_nap_qua_gateway_co_public_url(api_pool, hai_tenant):
    """Finding #9 — public_url='' bị agent contract đọc là «không có ảnh»: mọi ảnh
    qua gateway vô hình. URL ngoài (http/https) đi qua public_url_of nguyên văn."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-IMG", {"name": "X"}),
            _bg(
                "media",
                "M-IMG",
                {
                    "projectExternalId": "P-IMG",
                    "mediaUrl": "https://cdn.example.com/anh.jpg",
                    "contentType": "image",
                    "category": "tong_quan",
                },
            ),
        ),
        dry_run=False,
    )
    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetchrow(
            "SELECT public_url FROM tenant_data.media "
            "WHERE tenant_id = portal.current_tenant() AND external_id = 'M-IMG'"
        )
    assert hang["public_url"] == "https://cdn.example.com/anh.jpg"


async def test_delete_zone_published_purge_cascade_media(api_pool, hai_tenant):
    """Worker KB CHỈ tự cascade purge theo `anchor_code` (project); zone thì KHÔNG.

    Từ spec 2026-08-19 zone không còn point riêng nên chính nó không cần purge — nhưng
    media neo vào nó thì vẫn phải purge từng cái, nếu không media bị archived (ẩn khỏi
    agent) mà point Qdrant sống sót — đúng lớp NT2-1408."""
    a, _ = hai_tenant
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(
            _bg("project", "P-ZPURGE", {"name": "X"}),
            _bg("zone", "Z-PURGE", {"name": "PK", "projectExternalId": "P-ZPURGE"}),
            _bg(
                "media",
                "M-Z1",
                {
                    "projectExternalId": "P-ZPURGE",
                    "zoneExternalId": "Z-PURGE",
                    "mediaUrl": "https://cdn.example.com/1.jpg",
                    "contentType": "image",
                    "category": "tong_quan",
                },
            ),
            _bg(
                "media",
                "M-Z2",
                {
                    "projectExternalId": "P-ZPURGE",
                    "zoneExternalId": "Z-PURGE",
                    "mediaUrl": "https://cdn.example.com/2.jpg",
                    "contentType": "image",
                    "category": "tong_quan",
                },
            ),
        ),
        dry_run=False,
    )
    async with tenant_conn(api_pool, a) as conn:
        m1 = await conn.fetchval(
            "SELECT id FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND external_id = 'M-Z1'"
        )
        m2 = await conn.fetchval(
            "SELECT id FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND external_id = 'M-Z2'"
        )

    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("zone", "Z-PURGE", {}, op="delete", luc=LUC + timedelta(hours=1))),
        dry_run=False,
    )

    jobs = await api_pool.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete' ORDER BY id DESC LIMIT 3",
        a,
    )
    payloads = [json.loads(j["payload"]) if isinstance(j["payload"], str) else j["payload"] for j in jobs]
    media_purge_ids = {p["record_id"] for p in payloads if p.get("entity") == "media"}
    assert not [p for p in payloads if p.get("entity") == "zones"], "zone không còn point riêng để purge"
    assert media_purge_ids == {m1, m2}, "cascade phải purge ĐÚNG hai media neo vào zone, không thiếu không thừa"

    nap = await api_pool.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index' ORDER BY id DESC LIMIT 5", a
    )
    nap_payloads = [json.loads(j["payload"]) if isinstance(j["payload"], str) else j["payload"] for j in nap]
    assert any(p.get("entity") == "projects" for p in nap_payloads), "zone rời published phải nạp lại dự án cha"


async def test_link360_qua_cong_nap_sinh_hang_media_tour(api_pool, hai_tenant):
    """Cổng nạp ghi `link_360` thẳng vào bảng `projects`, và trước 2026-08-17 KHÔNG gọi sync —
    nên 25 dự án trên dev có link mà không hàng media nào, khách hỏi tour 360 thì `send_media`
    tìm không ra (D16 coi như chưa chạy)."""
    a, _ = hai_tenant
    link = "https://kuula.co/share/collection/7MgHS?logo=1&fs=1"
    ra = await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P360", DU_AN | {"link360": link})), dry_run=False
    )
    assert ra.accepted == 1, ra.results

    async with tenant_conn(api_pool, a) as conn:
        m = await conn.fetchrow(
            "SELECT content_type, category, caption, media_url, status FROM tenant_data.media "
            " WHERE tenant_id = portal.current_tenant() AND content_type = 'tour_360'"
        )
    assert m is not None, "không sinh hàng media cho tour 360"
    assert (m["media_url"], m["category"], m["status"]) == (link, "tong_quan", "published")
    assert m["caption"].startswith("Tour tham quan thực tế ảo 360 độ — ")


async def test_bo_link360_qua_cong_nap_thi_xoa_hang_tour(api_pool, hai_tenant):
    a, _ = hai_tenant
    link = "https://kuula.co/share/collection/7MgHS"
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P360", DU_AN | {"link360": link})), dry_run=False
    )
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P360", DU_AN | {"link360": ""}, luc=LUC + timedelta(minutes=1))),
        dry_run=False,
    )
    async with tenant_conn(api_pool, a) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.media WHERE tenant_id = portal.current_tenant() "
            " AND content_type = 'tour_360'"
        )
    assert n == 0, "khách bỏ link mà hàng tour vẫn còn ⇒ agent gửi một tour đã rút"


async def test_hang_tour_360_cua_adapter_khong_bi_sync_link360_ghi_de_hay_xoa(api_pool, hai_tenant):
    """Bug 2026-08-25: `sync_tour_360` chọn hàng `tour_360` BẤT KỲ của dự án theo
    `project_code`, không phân biệt hàng nền tảng tự sinh (từ `link_360`) với hàng adapter
    đẩy qua cổng nạp. Hệ quả: dự án KHÔNG có `link360` mà adapter gửi media `tour_360` thì
    lượt upsert project kế tiếp XOÁ hàng đó; có `link360` thì ghi đè `media_url` của họ.
    Luật đúng: nền tảng chỉ đụng hàng do mình sinh (`external_id IS NULL`)."""
    a, _ = hai_tenant
    link_adapter = "https://kuula.co/share/collection/ADAPTER"
    link_portal = "https://kuula.co/share/collection/PORTAL"

    async def _tours() -> list[tuple[str | None, str]]:
        async with tenant_conn(api_pool, a) as conn:
            rows = await conn.fetch(
                "SELECT external_id, media_url FROM tenant_data.media "
                " WHERE tenant_id = portal.current_tenant() AND content_type = 'tour_360' ORDER BY id"
            )
        return [(r["external_id"], r["media_url"]) for r in rows]

    tour = {"projectExternalId": "P360A", "mediaUrl": link_adapter, "contentType": "tour_360", "category": "tong_quan"}
    ra = await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P360A", DU_AN), _bg("media", "T360A", tour)), dry_run=False
    )
    assert ra.accepted == 2, ra.results
    assert await _tours() == [("T360A", link_adapter)]

    # Upsert lại project (vẫn không link360) — trước bản vá: hàng tour của adapter bị DELETE.
    await service.nap_lo(
        api_pool, tenant_id=a, lo=_lo(_bg("project", "P360A", DU_AN, luc=LUC + timedelta(minutes=1))), dry_run=False
    )
    assert await _tours() == [("T360A", link_adapter)], "upsert project không link360 xoá mất tour của adapter"

    # Đặt link360 — nền tảng sinh hàng RIÊNG (external_id NULL), không ghi đè hàng adapter.
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P360A", DU_AN | {"link360": link_portal}, luc=LUC + timedelta(minutes=2))),
        dry_run=False,
    )
    assert await _tours() == [("T360A", link_adapter), (None, link_portal)]

    # Bỏ link360 — chỉ hàng nền tảng bị xoá.
    await service.nap_lo(
        api_pool,
        tenant_id=a,
        lo=_lo(_bg("project", "P360A", DU_AN | {"link360": ""}, luc=LUC + timedelta(minutes=3))),
        dry_run=False,
    )
    assert await _tours() == [("T360A", link_adapter)]
