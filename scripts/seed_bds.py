"""Seed dữ liệu mẫu Bất động sản — Task 5.

HAI VIỆC, MỖI TENANT TRONG `control.tenants`:

1. **Row anchor hệ thống `__ALL__`** (`docs/build_module_knowledgebase/02 §2`,
   `02a §4b`): `project_code="__ALL__"`, `status="published"`, không có zones/units
   con. Đây là việc CHẶN THẬT — thiếu row này thì `POST /projects/__ALL__/documents`
   404 (tài liệu/media cấp tenant không có FK cha nào để trỏ vào). LUÔN
   `published` và LUÔN thoát khỏi luật completeness (`router.py:
   _bo_qua_completeness_du_an`) — nó không có `region`/`overview` thật, chỉ là
   điểm neo FK.
2. **Dữ liệu mẫu**: vài dự án thật (`DU_AN_MAU`), mỗi dự án có zones/units/
   documents, ĐỦ completeness (`name`+`region`+`overview`+`investor`+
   `product_scale` ở project, spec 2026-08-21 §3.5;
   `price_vnd`+`area_built_m2`+`sale_status` ở unit — `02a §7`) và đã
   `status="published"` — nếu không đủ thì demo dựng ra không dự án nào agent
   đọc được (task-5-brief.md).

VÌ SAO GHI SQL THÔ, KHÔNG GỌI `repo.py`: `tests/test_module_boundaries.py::
test_seed_bds_import_qua_mat_tien_khong_choc_vao_ruot` cấm `scripts/seed_bds.py`
import bất cứ gì của `portal.modules.realestate` NGOÀI `contracts.py` (mặt tiền).
`repo.py` không phải mặt tiền — script phải tự viết INSERT, cùng nếp
`scripts/dev_seed.py` viết thẳng SQL cho `control.*`.

VÌ SAO PHẢI `SET LOCAL app.tenant_id` TRƯỚC MỖI TENANT: DSN chạy script này là
`database_url` (role `portal_api`, xem `core/config.py`) — KHÔNG phải owner,
KHÔNG superuser, nên bảng `tenant_data.*` (FORCE RLS, migration `0003`/`0400`)
áp policy `USING/WITH CHECK (tenant_id = portal.current_tenant())` cho MỌI câu
lệnh của kết nối này, y hệt một request HTTP thật. `portal.current_tenant()`
(migration `0001`) coalesce `session_user` (dạng `agent_<tenant>`, không khớp ở
đây) rồi tới GUC `app.tenant_id` — nên phải tự đặt GUC đó, đúng cơ chế
`portal.core.db.session.tenant_conn()` dùng cho request thật, chỉ khác là gọi
tay `set_config(..., true)` thay vì qua context manager (script này không đi
qua HTTP nên không có `tenant_conn`).

IDEMPOTENT THEO CÂY, KHÔNG THEO HÀNG: `projects`/`zones` có UNIQUE
`(tenant_id, project_code[, zone_code])` nên `ON CONFLICT DO NOTHING` bảo vệ
trực tiếp — chạy lại không đè tên/region tenant đã sửa tay. `units`/`documents`
KHÔNG có khoá nghiệp vụ unique (`02a §4.3`/`§4.4`, cùng lý do `repo.py` không
có `_KHOA_DUY_NHAT` cho hai bảng này) nên `ON CONFLICT` không giúp được — thay
vào đó, cây con (zones/units/documents của MỘT dự án) chỉ được ghi khi INSERT
`projects` của dự án đó THẬT SỰ tạo hàng mới (`RETURNING id` có kết quả). Dự án
đã tồn tại (từ lần seed trước, hoặc do tenant tự tạo trùng `project_code` mẫu)
⇒ bỏ qua TOÀN BỘ cây con của nó — không chỉ né trùng `units`, mà còn không đè
bất cứ gì tenant đã sửa trên cây đó.

Chạy: make seed-bds   (sau make migrate && make dev-seed)
"""

import asyncio
import json
import sys
from typing import NamedTuple
from urllib.parse import urlparse

import asyncpg

from portal.core.config import get_settings
from portal.modules.realestate.contracts import SENTINEL_TENANT
from scripts.dev_seed import HOST_CHO_PHEP

VERTICAL = "bds"


class CanMau(NamedTuple):
    """Một căn mẫu. TRƯỚC ĐÂY là `tuple` 15 phần tử giải nén theo VỊ TRÍ, kèm một
    comment liệt kê thứ tự cột ngay phía trên danh sách (review vòng cuối, Minor
    F4 — sửa cùng lượt với `ruff format`, vì format sẽ nổ mỗi tuple thành 15 dòng
    và làm thứ tự vị trí càng khó đọc hơn).

    Vì sao đổi: một comment không phải cơ chế. Chèn/đổi chỗ một cột ở INSERT mà
    quên sửa 20 tuple (hoặc ngược lại) cho ra dữ liệu sai LẶNG LẼ — `direction`
    lưu vào `area_built_m2` chỉ vỡ nếu tình cờ sai kiểu, còn hai cột cùng kiểu
    (`zone_code`/`unit_code`, `area_wall_m2`/`area_land_m2`) thì seed chạy xanh
    với dữ liệu đảo chỗ. Với `NamedTuple`, tên field là thứ đi tới INSERT, nên
    lỗi loại đó thành `AttributeError` ngay lần chạy đầu.

    Default cho các field NULLABLE (`02a §4.3`): mỗi căn mẫu chỉ khai những gì
    CÓ NGHĨA với nó — biệt thự không có `block`/`floor`, chung cư không có
    `area_land_m2`. `sale_status`/`status` mang default KHỚP ĐÚNG default của DB
    (`'available'`) và chủ đích của seed (`'published'` — seed ra dữ liệu không
    dự án nào agent đọc được là seed vô dụng, xem docstring module).
    """

    zone_code: str
    unit_code: str
    product_type: str
    bedrooms: int | None = None
    block: str | None = None
    floor: int | None = None
    num_floors: int | None = None
    direction: str | None = None
    area_built_m2: float | None = None
    area_wall_m2: float | None = None
    area_land_m2: float | None = None
    price_vnd: int | None = None
    price_per_m2_vnd: int | None = None
    sale_status: str = "available"
    status: str = "published"


# ─── Dữ liệu mẫu — 2 dự án thật, mỗi dự án 2 zone + 10 unit + 2 document ────
# Giá nhập THẲNG bằng VND (`02a §1`: "Số về đúng kiểu numeric" — không còn
# `doi_don_vi_gia()`/nhập bằng tỷ của bản M4a cũ). Mọi project/unit dưới đây
# ĐỦ completeness (`02a §7`) VÀ `status="published"` — seed ra dữ liệu mà
# không dự án/căn nào agent đọc được là seed vô dụng (task-5-brief.md).

DU_AN_MAU: list[dict] = [
    {
        "project_code": "NPLB",
        "name": "Noble Palace Long Biên",
        "category": ["biet_thu", "lien_ke"],
        "region": "Long Biên, Hà Nội",
        "address": "Số 1 đường Ngô Gia Tự, Long Biên, Hà Nội",
        "investor": "Tập đoàn Noble",
        "developer": "Noble Developer",
        "total_land_area_m2": 120000,
        "floor_area_m2": 450000,
        "build_density_pct": 21,
        "product_scale": "2.400 sản phẩm thấp tầng",
        "amenities": "Bể bơi ven sông, công viên trung tâm, trung tâm thương mại, trường liên cấp",
        "ownership_form": "Lâu dài / Sổ hồng",
        "handover_standard": [{"item": "Tiêu chuẩn chung", "note": "Thô, giãn xây"}],
        "total_investment_vnd": 35_000_000_000_000,
        "sale_phase": "dang_ban",
        "overview": "Đại đô thị ven sông Hồng, hệ sinh thái tiện ích khép kín, kết nối trung tâm Hà Nội qua cầu "
        "Vĩnh Tuy.",
        "status": "published",
        "zones": [
            {
                "zone_code": "RIVER",
                "name": "Phân khu River Villas",
                "category": "biet_thu",
                "product_scale": "120 căn đơn lập",
                "overview": "Phân khu biệt thự ven sông, view trực diện mặt nước.",
                "status": "published",
            },
            {
                "zone_code": "PARK",
                "name": "Phân khu Park Row",
                "category": "lien_ke",
                "product_scale": "260 căn liền kề",
                "overview": "Phân khu liền kề mặt công viên trung tâm dự án.",
                "status": "published",
            },
        ],
        "units": [
            CanMau(
                "RIVER",
                "RV-01",
                "biet_thu",
                bedrooms=4,
                num_floors=3,
                direction="dong_nam",
                area_built_m2=220,
                area_wall_m2=235,
                area_land_m2=240,
                price_vnd=18_500_000_000,
                price_per_m2_vnd=84_090_000,
            ),
            CanMau(
                "RIVER",
                "RV-02",
                "biet_thu",
                bedrooms=4,
                num_floors=3,
                direction="dong",
                area_built_m2=220,
                area_wall_m2=235,
                area_land_m2=240,
                price_vnd=18_200_000_000,
                price_per_m2_vnd=82_727_000,
            ),
            CanMau(
                "RIVER",
                "RV-03",
                "biet_thu",
                bedrooms=5,
                num_floors=3,
                direction="nam",
                area_built_m2=260,
                area_wall_m2=278,
                area_land_m2=280,
                price_vnd=22_000_000_000,
                price_per_m2_vnd=84_615_000,
                sale_status="booked",
            ),
            CanMau(
                "RIVER",
                "RV-04",
                "biet_thu",
                bedrooms=4,
                num_floors=3,
                direction="tay_nam",
                area_built_m2=235,
                area_wall_m2=250,
                area_land_m2=250,
                price_vnd=19_800_000_000,
                price_per_m2_vnd=84_255_000,
            ),
            CanMau(
                "RIVER",
                "RV-05",
                "biet_thu",
                bedrooms=5,
                num_floors=3,
                direction="bac",
                area_built_m2=260,
                area_wall_m2=278,
                area_land_m2=280,
                price_vnd=21_500_000_000,
                price_per_m2_vnd=82_692_000,
                sale_status="sold",
            ),
            CanMau(
                "PARK",
                "PK-01",
                "lien_ke",
                bedrooms=3,
                num_floors=4,
                direction="tay_nam",
                area_built_m2=105,
                area_wall_m2=112,
                area_land_m2=90,
                price_vnd=9_800_000_000,
                price_per_m2_vnd=93_333_000,
            ),
            CanMau(
                "PARK",
                "PK-02",
                "lien_ke",
                bedrooms=3,
                num_floors=4,
                direction="tay",
                area_built_m2=105,
                area_wall_m2=112,
                area_land_m2=90,
                price_vnd=9_600_000_000,
                price_per_m2_vnd=91_428_000,
            ),
            CanMau(
                "PARK",
                "PK-03",
                "lien_ke",
                bedrooms=4,
                num_floors=4,
                direction="bac",
                area_built_m2=120,
                area_wall_m2=128,
                area_land_m2=95,
                price_vnd=11_200_000_000,
                price_per_m2_vnd=93_333_000,
                sale_status="sold",
            ),
            CanMau(
                "PARK",
                "PK-04",
                "lien_ke",
                bedrooms=3,
                num_floors=4,
                direction="dong",
                area_built_m2=108,
                area_wall_m2=115,
                area_land_m2=90,
                price_vnd=9_900_000_000,
                price_per_m2_vnd=91_666_000,
            ),
            CanMau(
                "PARK",
                "PK-05",
                "lien_ke",
                bedrooms=4,
                num_floors=4,
                direction="dong_nam",
                area_built_m2=122,
                area_wall_m2=130,
                area_land_m2=95,
                price_vnd=11_500_000_000,
                price_per_m2_vnd=94_262_000,
                sale_status="booked",
            ),
        ],
        "documents": [
            {
                "title": "Chính sách bán hàng Q3 2026",
                "body": "## Tiến độ thanh toán\n| Đợt | Tỷ lệ | Thời điểm |\n|---|---|---|\n| 1 | 30% | Ký HĐMB |\n"
                "| 2 | 50% | Bàn giao |\n| 3 | 20% | Cấp sổ |",
                "status": "published",
            },
            {
                "title": "Pháp lý dự án",
                "body": "Dự án đã hoàn thiện pháp lý, cấp sổ hồng lâu dài cho toàn bộ sản phẩm thấp tầng.",
                "status": "published",
            },
        ],
    },
    {
        "project_code": "SRC",
        "name": "Sunrise City",
        "category": ["chung_cu"],
        "region": "Quận 7, TP.HCM",
        "address": "Số 88 đường Nguyễn Văn Linh, Quận 7, TP.HCM",
        "investor": "Sunrise Group",
        "developer": "Sunrise Land",
        "total_land_area_m2": 45000,
        "floor_area_m2": 320000,
        "build_density_pct": 35,
        "product_scale": "1.800 căn hộ",
        "amenities": "Hồ bơi vô cực, gym, sân chơi trẻ em, khu BBQ ngoài trời",
        "ownership_form": "Lâu dài / Sổ hồng",
        "handover_standard": [{"item": "Tiêu chuẩn chung", "note": "Hoàn thiện cơ bản"}],
        "total_investment_vnd": 12_000_000_000_000,
        "sale_phase": "dang_ban",
        "overview": "Khu đô thị phức hợp ven sông Sài Gòn, view trực diện trung tâm Quận 7.",
        "status": "published",
        "zones": [
            {
                "zone_code": "TOWER-A",
                "name": "Tháp A",
                "category": "chung_cu",
                "product_scale": "900 căn hộ",
                "overview": "Tháp căn hộ view sông, 35 tầng.",
                "status": "published",
            },
            {
                "zone_code": "TOWER-B",
                "name": "Tháp B",
                "category": "chung_cu",
                "product_scale": "900 căn hộ",
                "overview": "Tháp căn hộ view thành phố, 35 tầng.",
                "status": "published",
            },
        ],
        "units": [
            CanMau(
                "TOWER-A",
                "A-0501",
                "chung_cu",
                bedrooms=2,
                block="A",
                floor=5,
                direction="dong_nam",
                area_built_m2=68.5,
                area_wall_m2=74.0,
                price_vnd=4_200_000_000,
                price_per_m2_vnd=61_313_000,
            ),
            CanMau(
                "TOWER-A",
                "A-0502",
                "chung_cu",
                bedrooms=2,
                block="A",
                floor=5,
                direction="dong",
                area_built_m2=68.5,
                area_wall_m2=74.0,
                price_vnd=4_150_000_000,
                price_per_m2_vnd=60_583_000,
            ),
            CanMau(
                "TOWER-A",
                "A-1203",
                "chung_cu",
                bedrooms=3,
                block="A",
                floor=12,
                direction="nam",
                area_built_m2=92.0,
                area_wall_m2=99.0,
                price_vnd=5_800_000_000,
                price_per_m2_vnd=63_043_000,
                sale_status="booked",
            ),
            CanMau(
                "TOWER-A",
                "A-1204",
                "chung_cu",
                bedrooms=3,
                block="A",
                floor=12,
                direction="bac",
                area_built_m2=92.0,
                area_wall_m2=99.0,
                price_vnd=5_650_000_000,
                price_per_m2_vnd=61_413_000,
            ),
            CanMau(
                "TOWER-A",
                "A-2001",
                "chung_cu",
                bedrooms=1,
                block="A",
                floor=20,
                direction="tay_nam",
                area_built_m2=45.0,
                area_wall_m2=49.0,
                price_vnd=3_100_000_000,
                price_per_m2_vnd=68_888_000,
                sale_status="sold",
            ),
            CanMau(
                "TOWER-B",
                "B-0301",
                "chung_cu",
                bedrooms=2,
                block="B",
                floor=3,
                direction="dong",
                area_built_m2=68.5,
                area_wall_m2=74.0,
                price_vnd=4_050_000_000,
                price_per_m2_vnd=59_124_000,
            ),
            CanMau(
                "TOWER-B",
                "B-0302",
                "chung_cu",
                bedrooms=2,
                block="B",
                floor=3,
                direction="tay",
                area_built_m2=68.5,
                area_wall_m2=74.0,
                price_vnd=4_000_000_000,
                price_per_m2_vnd=58_394_000,
            ),
            CanMau(
                "TOWER-B",
                "B-1501",
                "chung_cu",
                bedrooms=3,
                block="B",
                floor=15,
                direction="dong_nam",
                area_built_m2=92.0,
                area_wall_m2=99.0,
                price_vnd=6_000_000_000,
                price_per_m2_vnd=65_217_000,
            ),
            CanMau(
                "TOWER-B",
                "B-1502",
                "chung_cu",
                bedrooms=3,
                block="B",
                floor=15,
                direction="tay_bac",
                area_built_m2=92.0,
                area_wall_m2=99.0,
                price_vnd=5_900_000_000,
                price_per_m2_vnd=64_130_000,
                sale_status="booked",
            ),
            CanMau(
                "TOWER-B",
                "B-2801",
                "chung_cu",
                bedrooms=1,
                block="B",
                floor=28,
                direction="nam",
                area_built_m2=45.0,
                area_wall_m2=49.0,
                price_vnd=3_300_000_000,
                price_per_m2_vnd=73_333_000,
            ),
        ],
        "documents": [
            {
                "title": "Chính sách bán hàng đợt 1",
                "body": "Chiết khấu 3% thanh toán sớm 95%. Hỗ trợ vay ngân hàng 70% giá trị căn hộ.",
                "status": "published",
            },
            {
                "title": "Hướng dẫn nhận nhà",
                "body": "Quy trình nghiệm thu, bàn giao căn hộ và các giấy tờ cần chuẩn bị.",
                "status": "published",
            },
        ],
    },
]

TAI_LIEU_CHUNG: list[dict] = [
    {
        "title": "Giới thiệu công ty",
        "body": "Giới thiệu năng lực, lịch sử phát triển của chủ đầu tư.",
        "status": "published",
    },
    {"title": "Quy trình mua nhà", "body": "5 bước từ đặt cọc tới nhận sổ hồng.", "status": "published"},
]
"""Tài liệu cấp TENANT (`project_code = SENTINEL_TENANT`) — gắn vào row `__ALL__`,
không thuộc dự án nào (`02 §2`/`02a §4b`)."""


async def _seed_all_anchor(conn: asyncpg.Connection, tenant_id: str) -> int:
    """Row anchor hệ thống `__ALL__` — LUÔN `published`, LUÔN KHÔNG `region`/
    `overview` thật (nó không phải một dự án). `ON CONFLICT DO NOTHING`:
    KHÔNG đè nếu tenant đã có (tự tạo tay, hoặc lần seed trước)."""
    hang = await conn.fetchrow(
        """
        INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)
        VALUES ($1, $2, 'Chung / toàn tenant', 'published')
        ON CONFLICT (tenant_id, project_code) DO NOTHING
        RETURNING id
        """,
        tenant_id,
        SENTINEL_TENANT,
    )
    them = 0
    if hang is not None:
        them += 1
        for tl in TAI_LIEU_CHUNG:
            await conn.execute(
                """INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, status)
                   VALUES ($1, $2, $3, $4, $5)""",
                tenant_id,
                SENTINEL_TENANT,
                tl["title"],
                tl["body"],
                tl["status"],
            )
            them += 1
    return them


async def _seed_du_an(conn: asyncpg.Connection, tenant_id: str, du_an: dict) -> int:
    """Ghi MỘT cây dự án mẫu (project + zones + units + documents). Trả `0` và
    KHÔNG ghi gì thêm nếu `project_code` đã tồn tại — xem "IDEMPOTENT THEO CÂY"
    ở docstring module: không có khoá unique nào bảo vệ `units`/`documents`
    khỏi bị nhân đôi, nên toàn bộ cây con chỉ ghi cùng lúc với project MỚI."""
    hang = await conn.fetchrow(
        """
        INSERT INTO tenant_data.projects (
            tenant_id, project_code, name, category, region, address, investor, developer,
            total_land_area_m2, floor_area_m2, build_density_pct, product_scale, amenities,
            ownership_form, handover_standard, total_investment_vnd, sale_phase, overview, status
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
        ON CONFLICT (tenant_id, project_code) DO NOTHING
        RETURNING id
        """,
        tenant_id,
        du_an["project_code"],
        du_an["name"],
        du_an["category"],
        du_an["region"],
        du_an["address"],
        du_an["investor"],
        du_an["developer"],
        du_an["total_land_area_m2"],
        du_an["floor_area_m2"],
        du_an["build_density_pct"],
        du_an["product_scale"],
        du_an["amenities"],
        du_an["ownership_form"],
        json.dumps(du_an["handover_standard"], ensure_ascii=False),
        du_an["total_investment_vnd"],
        du_an["sale_phase"],
        du_an["overview"],
        du_an["status"],
    )
    if hang is None:
        return 0  # dự án đã tồn tại (seed trước, hoặc tenant tự tạo trùng mã) — bỏ qua cả cây

    them = 1
    ma = du_an["project_code"]

    for z in du_an["zones"]:
        await conn.execute(
            """INSERT INTO tenant_data.zones (
                   tenant_id, project_code, zone_code, name, category, product_scale, overview, status
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, project_code, zone_code) DO NOTHING""",
            tenant_id,
            ma,
            z["zone_code"],
            z["name"],
            z["category"],
            z["product_scale"],
            z["overview"],
            z["status"],
        )
        them += 1

    for u in du_an["units"]:
        # Đọc theo TÊN FIELD (`u.zone_code`), không giải nén 15 vị trí — xem
        # docstring `CanMau`.
        await conn.execute(
            """INSERT INTO tenant_data.units (
                   tenant_id, project_code, zone_code, unit_code, product_type, bedrooms, block, floor,
                   num_floors, direction, area_built_m2, area_wall_m2, area_land_m2, price_vnd,
                   price_per_m2_vnd, sale_status, status
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
            tenant_id,
            ma,
            u.zone_code,
            u.unit_code,
            u.product_type,
            u.bedrooms,
            u.block,
            u.floor,
            u.num_floors,
            u.direction,
            u.area_built_m2,
            u.area_wall_m2,
            u.area_land_m2,
            u.price_vnd,
            u.price_per_m2_vnd,
            u.sale_status,
            u.status,
        )
        them += 1

    for d in du_an["documents"]:
        await conn.execute(
            """INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, status)
               VALUES ($1,$2,$3,$4,$5)""",
            tenant_id,
            ma,
            d["title"],
            d["body"],
            d["status"],
        )
        them += 1

    return them


async def seed(conn: asyncpg.Connection, tenant_id: str) -> int:
    """Seed một tenant: anchor `__ALL__` + cây dự án mẫu. Trả tổng số hàng MỚI
    (không tính hàng đã có từ trước — `ON CONFLICT DO NOTHING`/gate cây con).

    `SET LOCAL app.tenant_id` TRƯỚC MỌI GHI — xem docstring module "VÌ SAO PHẢI
    SET LOCAL": kết nối này chạy bằng role `portal_api`, chịu RLS đầy đủ như
    một request thật, không phải superuser bỏ qua RLS."""
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
    them = await _seed_all_anchor(conn, tenant_id)
    for du_an in DU_AN_MAU:
        them += await _seed_du_an(conn, tenant_id, du_an)
    return them


async def _main() -> None:
    """CHỈ CHẠY TRÊN CONTAINER DEV — cùng rào chắn `scripts/dev_seed.py`.

    Dùng lại đúng `HOST_CHO_PHEP` của `dev_seed` (không tự chế một danh sách host
    khác rồi hy vọng nó luôn khớp).
    """
    dsn = get_settings().database_url
    host = urlparse(dsn).hostname or ""
    if host not in HOST_CHO_PHEP:
        sys.exit(
            f"TỪ CHỐI: seed_bds chỉ chạy trên container dev, DSN đang trỏ {host!r}.\n"
            f"Script này duyệt qua MỌI tenant trong control.tenants và ghi thẳng vào\n"
            f"DB bằng kết nối role runtime (portal_api), bỏ qua mọi quy trình\n"
            f"onboarding/kiểm duyệt của production."
        )

    conn = await asyncpg.connect(dsn)
    try:
        # MỖI TENANT MỘT GIAO DỊCH RIÊNG (khác bản trước gộp cả vòng lặp vào MỘT
        # transaction): tenant sau lỗi (vd project_code mẫu trùng constraint lạ)
        # không cuốn theo rollback dữ liệu tenant trước đã ghi xong trong CÙNG
        # lần chạy — mỗi tenant thành công/thất bại độc lập.
        ids = [r["id"] for r in await conn.fetch("SELECT id FROM control.tenants")]
        for t in ids:
            async with conn.transaction():
                n = await seed(conn, t)
            print(f"  {t}: thêm {n} hàng")
        print(f"xong — {len(ids)} workspace, vertical {VERTICAL}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(_main())
