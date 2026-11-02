"""Bảng giá mặc định do migration `0954` seed — cổng canh cái mà KHÔNG AI vận hành.

⚠️ TRƯỚC `0954` FILE NÀY SOI BẢN `0949` (`mac-dinh-vnd-2026`). `0954` tạo một
price_version MỚI và chuyển cờ `is_default` sang nó — bản `0949` vẫn còn trong DB
nhưng `is_default = false`, `status = 'inactive'`, và các dòng giá của nó KHÔNG bị
sửa (bất biến sau khi đã viện dẫn, xem `0943` mục 3d). Mọi bài dưới đây soi bản
ĐANG là mặc định, vì đó là bản duy nhất còn sinh ra tiền.

VÌ SAO CẦN CỔNG NÀY: từ 2026-08-21 portal không cho user đặt giá nữa (mục nav
«Bảng giá» đã ẩn), nên bảng giá đến từ migration chứ không từ một người bấm
«Tạo bộ giá». Không ai bấm nghĩa là không ai PHÁT HIỆN khi nó sai: thiếu một
dòng giá thì `rate_usage()` chỉ âm thầm không tính tiền phần đó — portal vẫn
hiện một con số trông hợp lý, chỉ là thiếu. Đây là chỗ duy nhất còn đỏ được.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import asyncpg
import pytest

from tests.modules.billing.conftest import TENANT

MIGRATION = Path(__file__).resolve().parents[3] / "migrations/versions/0954_bang_gia_vendor_2026.py"

CODE = "vendor-vnd-2026-08"
"""Phải khớp `CODE` của `0954_bang_gia_vendor_2026.py`. Không import trực tiếp
được: tên module bắt đầu bằng chữ số nên `from ... import 0949_...` là syntax
error — `importlib` chỉ để lấy một chuỗi thì đắt hơn giá trị. Đổi bên kia thì
`test_code_khop_migration` dưới đây đỏ, nên bản sao này CÓ cổng canh."""

CODE_MAC_DINH = "vendor-vnd-2026-10"
"""Bảng giá mặc định hiện hành (`0975`): như bản `0954`, chỉ khác giá tra Google (364 đ/lượt)."""

CODE_CU = "mac-dinh-vnd-2026"
"""Bản giá seed của `0949`. Giữ tên ở đây để `test_ban_cu_bi_ha_co_va_giu_nguyen_gia`
chứng minh `0954` KHÔNG sửa và KHÔNG xoá nó."""


def _nap_migration() -> ModuleType:
    """Nạp file migration như một module để lấy khối SQL `_UP`.

    KHÔNG qua alembic: `alembic upgrade` sẽ đụng `alembic_version` của một DB
    test dùng chung, và ta chỉ cần kiểm SQL có idempotent hay không.
    """
    spec = importlib.util.spec_from_file_location("_m0954", MIGRATION)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


async def test_code_khop_migration() -> None:
    """Chốt bản sao `CODE` ở trên với chuỗi thật trong file migration."""
    assert f'CODE = "{CODE}"' in MIGRATION.read_text(encoding="utf-8"), (
        f"`CODE` trong test ({CODE}) đã trôi khỏi migration 0954"
    )


async def test_seed_ton_tai_va_la_mac_dinh(pool: asyncpg.Pool) -> None:
    """DB nào chạy `alembic upgrade head` cũng phải có bảng giá này, và nó phải
    là `is_default` — đó là CƠ CHẾ duy nhất phủ tenant mới (`resolve_price_version`
    fallback về `is_default` khi tenant không có hàng `tenant_price_version`).
    """
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT currency, status, is_default FROM billing.price_version WHERE code = $1", CODE)
        mac_dinh = await conn.fetchrow("SELECT code, status FROM billing.price_version WHERE is_default")
    assert r is not None, "migration 0954 chưa seed bảng giá — DB mới sẽ hiện 0 ₫ khắp nơi"
    assert r["currency"] == "VND"
    assert mac_dinh is not None, "không có bảng giá mặc định thì tenant mới không có giá nào"
    assert (mac_dinh["code"], mac_dinh["status"]) == (CODE_MAC_DINH, "active")


async def test_phu_tron_pricing_basis(pool: asyncpg.Pool) -> None:
    """Mỗi hàng `billing.pricing_basis` phải có ĐÚNG một dòng giá — kể cả dòng 0.

    Đây là cổng đắt giá nhất của file: ngày BE thêm một cơ sở tính tiền
    (`pricing_basis`) mà quên thêm dòng giá vào seed, `rate_usage()` bỏ qua
    component đó, `price_coverage_gap` kêu, và không ai đang xem view đó. Bài
    này đỏ ngay tại CI.
    """
    async with pool.acquire() as conn:
        thieu = await conn.fetch(
            """
            SELECT pb.component, pb.purpose, pb.metric
              FROM billing.pricing_basis pb
             WHERE NOT EXISTS (
                   SELECT 1 FROM billing.price_item pi
                     JOIN billing.price_version pv ON pv.id = pi.price_version_id
                    WHERE pv.code = $1
                      AND pi.component = pb.component
                      AND pi.metric    = pb.metric
                      AND pi.purpose   = pb.purpose)
             ORDER BY 1, 2, 3
            """,
            CODE,
        )
        du = await conn.fetch(
            """
            SELECT pi.component, pi.purpose, pi.metric
              FROM billing.price_item pi
              JOIN billing.price_version pv ON pv.id = pi.price_version_id
             WHERE pv.code = $1
               AND NOT EXISTS (
                   SELECT 1 FROM billing.pricing_basis pb
                    WHERE pb.component = pi.component
                      AND pb.metric    = pi.metric
                      AND pb.purpose IN (pi.purpose, ''))
             ORDER BY 1, 2, 3
            """,
            CODE,
        )
    assert not thieu, f"cơ sở tính tiền KHÔNG có dòng giá (sẽ âm thầm miễn phí): {[dict(r) for r in thieu]}"
    assert not du, f"dòng giá không khớp cơ sở nào (không bao giờ áp): {[dict(r) for r in du]}"


async def test_stt_chi_mot_ve_thoi_luong_co_gia(pool: asyncpg.Pool) -> None:
    """Đặt giá cả `audio_sec` và `wall_ms` = tính tiền STT hai lần.

    Index `price_item_stt_single_basis` (bản `0948`) đã chặn ở tầng DB, nhưng
    bài này nói ra Ý ĐỊNH: từ `0954` seed chọn `wall_ms` (thời gian stream mở),
    ĐẢO LẠI so với `0949` vốn chọn `audio_sec`. Index xanh cho CẢ HAI cấu hình
    (vẫn chỉ một vế > 0), nên đây là chỗ duy nhất phát hiện nếu ai đó lật ngược
    — giá vẫn hợp lệ về hình thức mà đổi nghĩa hẳn.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT pi.metric, pi.unit_price
                 FROM billing.price_item pi
                 JOIN billing.price_version pv ON pv.id = pi.price_version_id
                WHERE pv.code = $1 AND pi.component = 'stt'
                  AND pi.metric IN ('audio_sec', 'wall_ms')""",
            CODE,
        )
    gia = {r["metric"]: r["unit_price"] for r in rows}
    assert gia["wall_ms"] > 0, "seed phải thu STT theo thời gian stream mở (wall_ms)"
    assert gia["audio_sec"] == 0, "vế audio_sec phải là 0 tường minh, không phải bỏ trống"


async def test_chay_lai_migration_khong_nhan_ban(pool: asyncpg.Pool) -> None:
    """`upgrade()` phải idempotent: chạy lại trên DB đã seed là no-op.

    Quan trọng vì `ON CONFLICT DO NOTHING` chỉ an toàn nhờ trigger
    `price_item_bat_bien` bắt `BEFORE UPDATE OR DELETE` chứ KHÔNG bắt INSERT —
    ngày ai đó thêm INSERT vào trigger đó, bài này đỏ thay vì một lần deploy vỡ.
    """
    m = _nap_migration()
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        truoc = await conn.fetchval(
            "SELECT count(*) FROM billing.price_item pi JOIN billing.price_version pv "
            "ON pv.id = pi.price_version_id WHERE pv.code = $1",
            CODE,
        )
        # Chạy lại đúng khối SQL của migration, không qua alembic (không muốn
        # đụng bảng version của một DB test dùng chung).
        await conn.execute(m._UP)
        sau = await conn.fetchval(
            "SELECT count(*) FROM billing.price_item pi JOIN billing.price_version pv "
            "ON pv.id = pi.price_version_id WHERE pv.code = $1",
            CODE,
        )
        so_ban = await conn.fetchval("SELECT count(*) FROM billing.price_version WHERE code = $1", CODE)
        await tx.rollback()  # `_UP` chuyển cờ mặc định về bản 0954 — không để lọt sang bài khác
    assert truoc == sau, f"chạy lại seed nhân bản dòng giá: {truoc} → {sau}"
    assert so_ban == 1


async def test_gianh_co_mac_dinh_khong_vo_index(pool: asyncpg.Pool) -> None:
    """`0954` CỐ Ý chuyển cờ mặc định về mình — và không được vỡ index khi làm thế.

    ⚠️ ĐẢO Ý ĐỊNH SO VỚI BẢN TRƯỚC CỦA BÀI NÀY: bài cũ (`test_ton_trong_mac_dinh_da_co`)
    chốt rằng seed `0949` KHÔNG tranh cờ mặc định của bảng giá đang chạy — đúng cho
    một seed lần-đầu, sai cho `0954`. `0954` là một lần ĐỔI GIÁ: `tenant_price_version`
    rỗng nên `is_default` là cơ chế DUY NHẤT phủ tenant, thêm bảng giá mà không chuyển
    cờ thì giá mới không áp cho một ai — đúng loại bug im lặng mà file này canh.

    Cái còn phải chứng minh là chuyển cờ KHÔNG vỡ `price_version_single_default`
    (UNIQUE trên `((true)) WHERE is_default`): phải HẠ cờ cũ trước rồi DỰNG cờ mới,
    hai câu lệnh riêng. Dựng lại cảnh "có một bản mặc định khác" rồi chạy lại `_UP`.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute("UPDATE billing.price_version SET is_default = false WHERE is_default")
            khac = await conn.fetchval(
                "INSERT INTO billing.price_version (code, name, currency, status, is_default) "
                "VALUES ('pv_mac_dinh_khac', 'khác', 'VND', 'active', true) RETURNING id"
            )
            await conn.execute(_nap_migration()._UP)  # không được ném

            moi = await conn.fetchval("SELECT id FROM billing.price_version WHERE code = $1", CODE)
            dang_mac_dinh = await conn.fetch("SELECT id FROM billing.price_version WHERE is_default")
        finally:
            await tx.rollback()
    assert len(dang_mac_dinh) == 1, f"nhiều hơn một bảng giá mặc định: {[r['id'] for r in dang_mac_dinh]}"
    assert dang_mac_dinh[0]["id"] == moi, (
        f"cờ mặc định không về bản 0954 (đang ở {dang_mac_dinh[0]['id']}, khác={khac})"
    )


async def test_ban_cu_bi_ha_co_va_giu_nguyen_gia(pool: asyncpg.Pool) -> None:
    """`0954` hạ cờ bản `0949` nhưng KHÔNG được sửa/xoá một dòng giá nào của nó.

    Đây là cổng bảo vệ tính giải-thích-được của `rated_usage` cũ: mỗi dòng tiền đã
    tính trỏ về `price_version_id` của bản `0949`, và nếu ai đó "dọn dẹp" bằng cách
    xoá bản cũ hay UPDATE đơn giá của nó thì số tiền đã chốt mất chỗ dựa — hoặc tệ
    hơn, một lần tính lại ra số khác mà không lỗi nào phát ra.
    """
    async with pool.acquire() as conn:
        cu = await conn.fetchrow("SELECT id, status, is_default FROM billing.price_version WHERE code = $1", CODE_CU)
        assert cu is not None, "bản giá 0949 đã bị xoá — rated_usage cũ mất chỗ dựa"
        gia_cu = await conn.fetch(
            """SELECT pi.component, pi.metric, pi.unit_price, pi.per_units
                 FROM billing.price_item pi
                WHERE pi.price_version_id = $1 ORDER BY 1, 2""",
            cu["id"],
        )
    assert cu["is_default"] is False, "bản 0949 vẫn giữ cờ mặc định — giá mới không áp cho ai"
    assert cu["status"] == "inactive", f"bản 0949 phải mang nhãn 'inactive', đang là {cu['status']}"
    # Ba mốc của bản CŨ, nguyên văn 0949 — không phải giá mới.
    goc = {
        ("llm", "input_tokens"): (Decimal("78000"), 1_000_000),
        ("llm", "output_tokens"): (Decimal("390000"), 1_000_000),
        ("call", "audio_sec"): (Decimal("600"), 60),
    }
    thuc = {(r["component"], r["metric"]): (r["unit_price"], r["per_units"]) for r in gia_cu}
    for khoa, mong_doi in goc.items():
        assert thuc.get(khoa) == mong_doi, f"dòng giá cũ {khoa} đã bị sửa: {thuc.get(khoa)} ≠ {mong_doi}"


async def test_dinh_gia_ra_tien_that(pool: asyncpg.Pool, workspace_billing) -> None:
    """Cổng đầu-cuối: một tenant KHÔNG được gán bảng giá nào vẫn ra tiền > 0.

    Đây là cả lý do migration `0949` tồn tại. `workspace_billing` chèn usage cho
    `TENANT` nhưng KHÔNG dùng `bang_gia_vi_du`, nên `resolve_price_version()`
    buộc phải rơi về `is_default` — đúng đường mà mọi tenant production sẽ đi.
    """
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            n = await conn.fetchval(
                "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
                TENANT,
            )
            tong = await conn.fetchval("SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)
            dung_ban_seed = await conn.fetchval(
                """SELECT bool_and(pv.code = $2) FROM billing.rated_usage ru
                     JOIN billing.price_version pv ON pv.id = ru.price_version_id
                    WHERE ru.tenant_id = $1""",
                TENANT,
                CODE_MAC_DINH,
            )
        finally:
            await tx.rollback()
    assert n and n > 0, "không dòng usage nào được định giá — bảng giá seed không khớp gì"
    assert tong is not None and tong > Decimal(0), f"định giá xong mà tổng tiền vẫn {tong}"
    assert dung_ban_seed is True, "tiền được tính bằng một bảng giá khác bảng seed"


@pytest.mark.parametrize(
    ("component", "metric", "gia", "per"),
    [
        # LLM — $0,75 / $3,75 / $0,075 / $0,075 mỗi 1M token, ×26.000
        ("llm", "input_tokens", Decimal("19500"), 1_000_000),
        ("llm", "output_tokens", Decimal("97500"), 1_000_000),
        ("llm", "cache_write_tokens", Decimal("1950"), 1_000_000),
        ("llm", "cache_read_tokens", Decimal("1950"), 1_000_000),
        # Text — $0,15/1M và $50/1M text_units
        ("embed", "text_units", Decimal("3900"), 1_000_000),
        ("tts", "text_units", Decimal("1300000"), 1_000_000),
        # STT — vế thời lượng là wall_ms ($0,12/giờ = 3.120 đ, per_units = 1 giờ tính bằng ms)
        ("stt", "wall_ms", Decimal("3120"), 3_600_000),
        ("stt", "text_units", Decimal("104000"), 1_000_000),
        ("stt", "audio_sec", Decimal("0"), 1),
        # Không thu
        ("vad", "audio_sec", Decimal("0"), 1),
        ("speaker_verify", "audio_sec", Decimal("0"), 1),
        ("call", "audio_sec", Decimal("0"), 60),
    ],
)
async def test_don_gia_dung_nhu_da_chot(
    pool: asyncpg.Pool, component: str, metric: str, gia: Decimal, per: int
) -> None:
    """Khoá cứng từng đơn giá của bản `0954` (VND, tỉ giá 26.000 đ/USD, không markup).

    Đổi giá là một quyết định NGHIỆP VỤ — nó phải đi qua việc sửa bài test này,
    không được lọt vào bằng một sửa đổi migration trông vô hại.
    """
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """SELECT pi.unit_price, pi.per_units
                 FROM billing.price_item pi
                 JOIN billing.price_version pv ON pv.id = pi.price_version_id
                WHERE pv.code = $1 AND pi.component = $2 AND pi.metric = $3""",
            CODE,
            component,
            metric,
        )
    assert r is not None, f"thiếu dòng giá {component}/{metric}"
    assert r["unit_price"] == gia, f"{component}/{metric}: {r['unit_price']} ≠ {gia}"
    assert r["per_units"] == per
