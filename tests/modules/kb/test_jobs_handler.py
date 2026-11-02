"""Handler job trên Postgres thật + fake santa-models.

`dependencies()` chưa nối client thật nên test thay nó bằng fake — đó là seam duy
nhất giữa handler và thế giới ngoài.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs
from portal.modules.kb.state import repo
from tests.modules.kb.fake import FakeIndexClient, FakeObjectStore

from .conftest import TENANT


@pytest.fixture
def fakes(monkeypatch):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (rag, media, store))
    return rag, media, store


async def test_record_chuyen_sang_nhap_VAN_duoc_nap_voi_status_draft(api_pool, doc_ids, fakes):
    """LẬT hành vi trước 2026-08-14: chuyển sang nháp KHÔNG còn xoá point.

    Cũ: đường đọc lọc `status='published'` nên hàng nháp đọc ra `None` và caller chuyển sang
    xoá point. Mới: nháp CŨNG được nạp, trạng thái hiệu lực đi vào payload, và mệnh đề lọc
    của agent (`status == 'published'`) mới là chỗ ẩn nó. Nhờ vậy công bố lại chỉ cần cập
    nhật payload chứ không phải nhúng lại — xem docs/contracts/payload-qdrant.md §4.
    """
    rag, _media, _store = fakes
    record_id = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute("UPDATE tenant_data.documents SET status = 'draft' WHERE id = $1", record_id)
        result = await jobs.handle_index(
            conn,
            {"vertical": "real_estate", "entity": "documents", "doc_type": "tai_lieu", "record_id": record_id},
        )

    assert result.count > 0, "hàng nháp phải được nạp"
    assert rag.deleted == [], "chuyển sang nháp KHÔNG được xoá point"
    assert rag.indexed and rag.indexed[-1].status == "draft"


async def test_record_bi_XOA_HAN_thi_moi_xoa_point_dung_doc_type_cua_so(api_pool, doc_ids, fakes):
    """Chỉ DELETE mới xoá point. Và `payload["doc_type"]` từ backfill là ĐỊNH DANH SPEC
    (`tai_lieu`), không phải doc_type của point nào — chuyển tiếp nó vào lời gọi xoá thì
    `uuid5("tai_lieu:…")` không khớp point nào và point thật ở lại vĩnh viễn."""
    rag, _media, _store = fakes
    record_id = doc_ids["nplb"]
    async with tenant_conn(api_pool, TENANT) as conn:
        await repo.save_state(
            conn, entity="documents", record_id=record_id, doc_type="csbh", target="documents", state="indexed"
        )
        await conn.execute("DELETE FROM tenant_data.documents WHERE id = $1", record_id)
        result = await jobs.handle_index(
            conn,
            {"vertical": "real_estate", "entity": "documents", "doc_type": "tai_lieu", "record_id": record_id},
        )

    assert result.count == 0
    assert rag.deleted == [(TENANT, record_id, "csbh")]


async def test_khong_con_danh_muc_anh_nao_ngoai_pham_vi_nap(api_pool):
    """CHECK của `media.category` khớp ĐÚNG danh sách được nạp — nên nhánh "ngoài phạm vi"
    không còn tới được từ dữ liệu thật.

    Bản trước của test này chèn một ảnh `csbh` để kiểm message. Migration `0927` đã bỏ `csbh`
    khỏi CHECK (nó là loại TÀI LIỆU, không phải danh mục ảnh) và di trú 34 hàng sang bảng
    `documents`, nên chèn giá trị đó bây giờ nổ CheckViolation.

    Đo bằng hai tập BẰNG NHAU chứ không bằng "csbh không còn": nếu ai đó thêm một danh mục
    ảnh mới mà quên đưa vào `media_visual`, badge sẽ vàng vĩnh viễn cho mọi ảnh danh mục đó —
    đúng bug đã mất một vòng điều tra ngày 2026-08-14.
    """
    from portal.modules.kb.contracts import MEDIA_VISUAL_REAL_ESTATE

    async with tenant_conn(api_pool, TENANT) as conn:
        dinh_nghia = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'media_category_hop_le'"
        )
    trong_check = {c for c in MEDIA_VISUAL_REAL_ESTATE if f"'{c}'" in dinh_nghia}
    assert trong_check == set(MEDIA_VISUAL_REAL_ESTATE), (
        f"danh mục được nạp và danh mục CHECK cho phép đã lệch: {dinh_nghia}"
    )
    assert "'csbh'" not in dinh_nghia, "csbh là loại tài liệu, không phải danh mục ảnh"


def test_ly_do_bo_qua_noi_dung_danh_muc_khi_ngoai_pham_vi():
    """Nhánh message vẫn phải đúng: `media_visual` có thể co lại ở một vertical khác, và lúc
    đó nói "không còn published" sẽ đẩy người vận hành đi tìm một record đã ẩn không tồn tại.
    Kiểm ở tầng hàm thuần vì DB không còn cho phép dựng ca này."""
    from portal.modules.kb.directive import profiles
    from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE

    assert profiles.should_index_media(REAL_ESTATE, "tong_quan") is True
    assert profiles.should_index_media(REAL_ESTATE, "csbh") is False
