"""CỔNG PARITY — hợp đồng nạp khớp schema THẬT.

`modules/ingest/hop_dong.py` chép tay tên cột và giá trị enum từ
`migrations/versions/`. Bản chép tay không có cổng canh sẽ lệch — repo này đã trả
giá cho đúng lớp lỗi đó ít nhất hai lần (`lib/tools.ts` bên FE, và fake MSW mã hoá
luật NGƯỢC với backend).

Cổng này đọc `information_schema` + `pg_constraint` của DB thật rồi so từng thứ.
Thêm một trường vào hợp đồng mà DB không có (hoặc đổi enum ở migration mà quên đổi
ở hợp đồng) là CI đỏ — không phải một bản ghi bị từ chối ở nhà khách hàng.

⚠️ CHIỀU CANH LÀ MỘT CHIỀU, có chủ ý: mọi thứ hợp đồng KHAI phải tồn tại trong DB.
Chiều ngược lại (cột DB nào cũng phải có trong hợp đồng) KHÔNG canh — hợp đồng cố
ý hẹp hơn schema. `content_hash`, `uploaded_by`, `thumb_url` là việc nội bộ của
Portal; phơi chúng ra cho adapter bên khách là hứa một thứ mình không muốn nhận.
"""

import re

import pytest

from portal.modules.ingest.hop_dong import HOP_DONG, Truong

pytestmark = pytest.mark.integration

_BANG = {
    "project": "projects",
    "zone": "zones",
    "unit": "units",
    "document": "documents",
    "media": "media",
}


async def _cot_that(pool, bang: str) -> set[str]:
    hang = await pool.fetch(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'tenant_data' AND table_name = $1""",
        bang,
    )
    return {h["column_name"] for h in hang}


async def _gia_tri_check(pool, bang: str, cot: str) -> set[str] | None:
    """Giá trị trong `CHECK (<cot> IN (...))` của một bảng, hoặc `None` nếu không có.

    Đọc `pg_get_constraintdef` rồi bóc chuỗi trong ngoặc — thô, nhưng nó đọc ĐÚNG
    thứ Postgres đang cưỡng chế, không phải thứ ai đó nghĩ là đang cưỡng chế.
    """
    dinh_nghia = await pool.fetch(
        """SELECT pg_get_constraintdef(con.oid) AS d
             FROM pg_constraint con
             JOIN pg_class c ON c.oid = con.conrelid
             JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'tenant_data' AND c.relname = $1 AND con.contype = 'c'""",
        bang,
    )
    for d in dinh_nghia:
        s = d["d"]
        # Khớp cả `col = ANY (ARRAY[...])` (dạng Postgres chuẩn hoá `IN`) lẫn
        # `col IN (...)`. Bỏ qua constraint của cột khác.
        if not re.search(rf"\b{re.escape(cot)}\b", s):
            continue
        trong = re.findall(r"'([^']+)'::text", s)
        if trong:
            return set(trong)
    return None


@pytest.mark.parametrize("entity", sorted(HOP_DONG))
async def test_moi_truong_trong_hop_dong_deu_co_cot_that(pool, entity):
    """Tên cột trong hợp đồng phải tồn tại trong `tenant_data`.

    Đây là cổng bắt được đúng ba chỗ đã suýt sai lúc dựng FE: `link360` → cột
    `link_360`, `document.loai` không phải cột, và `media.contentType` không phải
    MIME type.
    """
    that = await _cot_that(pool, _BANG[entity])
    thieu = sorted({t.cot for t in HOP_DONG[entity]} - that)
    assert not thieu, (
        f"`hop_dong.HOP_DONG['{entity}']` khai cột không có trong tenant_data.{_BANG[entity]}: {', '.join(thieu)}"
    )


@pytest.mark.parametrize("entity", sorted(HOP_DONG))
async def test_enum_trong_hop_dong_khop_check_cua_db(pool, entity):
    """Giá trị enum phải khớp CHÍNH XÁC `CHECK` của cột.

    Hai chiều đều hỏng theo cách riêng:
      · Hợp đồng THỪA một giá trị ⇒ mình nhận rồi DB từ chối ⇒ `500` thay vì một
        câu nói rõ, và bản ghi mất mà bên khách tưởng đã vào.
      · Hợp đồng THIẾU một giá trị ⇒ mình từ chối một payload hoàn toàn hợp lệ, và
        dev bên kia đi tìm lỗi ở phía họ.
    """
    for t in HOP_DONG[entity]:
        if not t.gia_tri:
            continue
        if t.ten == "loai":
            continue  # không phải cột — nhập vào `title` thành tiền tố
        that = await _gia_tri_check(pool, _BANG[entity], t.cot)
        assert that is not None, (
            f"{_BANG[entity]}.{t.cot} không có CHECK nào — hợp đồng khai enum "
            f"{t.gia_tri} cho một cột DB không ràng buộc gì. Một trong hai chỗ sai."
        )
        assert set(t.gia_tri) == that, f"{_BANG[entity]}.{t.cot}: hợp đồng {sorted(t.gia_tri)} ≠ DB {sorted(that)}"


async def test_truong_bat_buoc_phu_het_cot_not_null_khong_default(pool):
    """Cột `NOT NULL` mà KHÔNG có DEFAULT thì hợp đồng PHẢI bắt buộc trường đó.

    Thiếu một cột như thế là `NotNullViolation` lúc chiếu — một `500` ở giữa lô,
    sau khi bản ghi đã được nhận và trả `accepted`. Bên khách thấy «nhận rồi» còn
    dữ liệu thì không tới đâu.

    Đây đúng là cách `units.product_type` bị bắt: nó `NOT NULL` không DEFAULT,
    còn hợp đồng bản đầu để tuỳ chọn.
    """
    # Cột do Portal tự điền lúc chiếu, không phải do khách gửi.
    # "zone_code" phải ở lại đây dù 0902 đã nới units.zone_code nullable — set này
    # áp cho MỌI bảng, và zones.zone_code vẫn NOT NULL không DEFAULT do projector tự
    # sinh (_ma_con_moi), không phải trường khách gửi.
    tu_dien = {"tenant_id", "external_id", "project_code", "zone_code", "id"}
    hong: list[str] = []
    for entity, bang in _BANG.items():
        hang = await pool.fetch(
            """SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'tenant_data' AND table_name = $1
                  AND is_nullable = 'NO' AND column_default IS NULL""",
            bang,
        )
        bat_buoc = {t.cot for t in HOP_DONG[entity] if t.bat_buoc}
        for h in hang:
            c = h["column_name"]
            if c in tu_dien or c in bat_buoc:
                continue
            hong.append(f"{bang}.{c}")
    assert not hong, "Cột NOT NULL không DEFAULT mà hợp đồng không bắt buộc — sẽ nổ lúc chiếu: " + ", ".join(
        sorted(hong)
    )


def test_khong_truong_nao_trung_ten_trong_mot_thuc_the():
    """Hai `Truong` cùng `ten` là một cái che cái kia trong `spec` của `kiem()`.

    `document` CÓ hai trường cùng `cot='title'` (`title` và `loai`) — đó là chủ ý
    và hợp lệ; cái bị cấm là trùng `ten`.
    """
    for entity, truong in HOP_DONG.items():
        ten = [t.ten for t in truong]
        assert len(ten) == len(set(ten)), f"{entity}: trùng tên trường {ten}"
        assert all(isinstance(t, Truong) for t in truong)
