"""Ghi Qdrant thật bằng testcontainers.

Hình dạng collection là hợp đồng với repo agent: dense 1024 + sparse bm25 cho
_documents, text 1024 + visual 768 cho _media. Test này là chỗ DUY NHẤT ở repo
backend bắt được một lần đổi số chiều.
"""

import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

from portal.modules.kb.index.store import PointIn, QdrantStore, point_id_of


@pytest.fixture
async def store(qdrant_url):
    s = QdrantStore(url=qdrant_url)
    yield s
    await s.aclose()


def test_point_id_on_dinh_va_khac_nhau_theo_doc_type():
    """point-id = uuid5(doc_type:record_id:idx) — đổi loại tài liệu sinh point MỚI."""
    a = point_id_of("csbh", 12, 0)
    assert a == point_id_of("csbh", 12, 0)
    assert a != point_id_of("phap_ly", 12, 0)
    assert a != point_id_of("csbh", 12, 1)


async def test_dung_collection_documents_dung_hinh_dang(store):
    await store.ensure_collection("t_documents", media=False)
    info = await store.describe("t_documents")
    assert info["dense"] == 1024
    assert "bm25" in info["sparse"]


async def test_dung_collection_media_dung_hinh_dang(store):
    await store.ensure_collection("t_media", media=True)
    info = await store.describe("t_media")
    assert info["text"] == 1024
    assert info["visual"] == 768


async def test_ensure_collection_goi_hai_lan_khong_hong(store):
    """Job retry gọi lại — lần hai không được xoá dữ liệu lần một."""
    await store.ensure_collection("t_idem", media=False)
    await store.upsert("t_idem", [PointIn(point_id_of("tai_lieu", 1, 0), {"dense": [0.1] * 1024}, {"record_id": 1})])
    await store.ensure_collection("t_idem", media=False)
    assert await store.count("t_idem") == 1


async def test_upsert_cung_point_id_ghi_de_khong_nhan_doi(store):
    await store.ensure_collection("t_up", media=False)
    pid = point_id_of("tai_lieu", 7, 0)
    await store.upsert("t_up", [PointIn(pid, {"dense": [0.1] * 1024}, {"record_id": 7, "caption": "cũ"})])
    await store.upsert("t_up", [PointIn(pid, {"dense": [0.2] * 1024}, {"record_id": 7, "caption": "mới"})])
    assert await store.count("t_up") == 1


async def test_delete_by_record_chi_xoa_dung_doc_type(store):
    await store.ensure_collection("t_del", media=False)
    await store.upsert(
        "t_del",
        [
            PointIn(point_id_of("csbh", 5, 0), {"dense": [0.1] * 1024}, {"record_id": 5, "doc_type": "csbh"}),
            PointIn(point_id_of("phap_ly", 5, 0), {"dense": [0.1] * 1024}, {"record_id": 5, "doc_type": "phap_ly"}),
        ],
    )
    await store.delete_by_record("t_del", record_id=5, doc_type="csbh")
    assert await store.count("t_del") == 1


async def test_delete_by_record_khong_loc_gi_xoa_moi_point_cua_record(store):
    """`doc_type=""` + `entity=""` = "mọi point mang record_id này".

    Chỉ ĐÚNG ở collection `_media`, nơi một record đúng một point (`MediaClient._DOC_TYPE`
    cố ý rỗng). Ở `_documents` thì ba bảng dùng chung collection và mỗi bảng có sequence
    riêng, nên nhánh này xoá cả point của entity khác — xem test ngay dưới.
    """
    await store.ensure_collection("t_del_all", media=False)
    await store.upsert(
        "t_del_all",
        [
            PointIn(point_id_of("csbh", 6, 0), {"dense": [0.1] * 1024}, {"record_id": 6, "doc_type": "csbh"}),
            PointIn(point_id_of("phap_ly", 6, 0), {"dense": [0.1] * 1024}, {"record_id": 6, "doc_type": "phap_ly"}),
        ],
    )
    await store.delete_by_record("t_del_all", record_id=6, doc_type="")
    assert await store.count("t_del_all") == 0


async def test_delete_by_record_theo_doc_type_khong_cham_point_bang_khac(store):
    """`projects#5`, `zones#5`, `documents#5` cùng sống trong `<slug>_documents`.

    Ba bảng ba sequence riêng nên `record_id` trùng nhau là chuyện thường. Vị từ thứ hai
    là `doc_type` — khoá `entity` từng gánh việc này nhưng đã bị bỏ khỏi payload
    2026-08-14 (nó suy được từ `doc_type`, xem hợp đồng payload §6). Tính RỜI NHAU của ba
    tập doc_type là điều kiện để phép thay đó đúng, và
    `test_doc_type_roi_nhau.py` canh nó.
    """
    await store.ensure_collection("t_del_dt", media=False)
    await store.upsert(
        "t_del_dt",
        [
            PointIn(
                point_id_of("tong_quan", 5, 0),
                {"dense": [0.1] * 1024},
                {"record_id": 5, "doc_type": "tong_quan"},
            ),
            PointIn(
                point_id_of("phan_khu", 5, 0),
                {"dense": [0.1] * 1024},
                {"record_id": 5, "doc_type": "phan_khu"},
            ),
            PointIn(
                point_id_of("csbh", 5, 0),
                {"dense": [0.1] * 1024},
                {"record_id": 5, "doc_type": "csbh"},
            ),
        ],
    )

    await store.delete_by_record("t_del_dt", record_id=5, doc_type="phan_khu")

    assert await store.payload_of("t_del_dt", point_id=point_id_of("phan_khu", 5, 0)) == {}
    assert await store.payload_of("t_del_dt", point_id=point_id_of("tong_quan", 5, 0)), (
        "xoá zones#5 đã cuốn theo point của projects#5"
    )
    assert await store.payload_of("t_del_dt", point_id=point_id_of("csbh", 5, 0)), (
        "xoá zones#5 đã cuốn theo point của documents#5"
    )


async def test_delete_khong_co_doc_type_o_documents_thi_NO_chu_khong_xoa_mu(store):
    """Chỗ chặn thay cho khoá `entity` đã bỏ.

    Không có `doc_type` thì vị từ duy nhất còn lại là `record_id`, và nó cuốn theo point
    của hai bảng kia — im lặng. `service.delete_index` đã biết tra doc_type từ sổ, nên
    caller nào tới đây mà không có nó là một bug, và bug phải NỔ.
    """
    import pytest

    from portal.modules.kb.clients.rag import RagClient

    c = RagClient(embed=None, store=store)
    with pytest.raises(ValueError, match="doc_type"):
        await c.delete(workspace_slug="ws_mu", record_id=5)


async def test_delete_by_record_van_xoa_point_he_cu_thieu_khoa_entity(store):
    """Point ghi trước đợt 2026-08-10 KHÔNG có khoá `entity`, và point ghi từ 2026-08-14
    cũng không (khoá đã bỏ). Vị từ `record_id + doc_type` không nhắc tới `entity` nên cả
    ba thế hệ point đều xoá được — đó là lý do phép thay này an toàn."""
    await store.ensure_collection("t_del_cu", media=False)
    await store.upsert(
        "t_del_cu",
        [PointIn(point_id_of("csbh", 8, 0), {"dense": [0.1] * 1024}, {"record_id": 8, "doc_type": "csbh"})],
    )
    await store.delete_by_record("t_del_cu", record_id=8, doc_type="csbh")
    assert await store.count("t_del_cu") == 0


async def test_delete_by_record_collection_chua_ton_tai_khong_nem(store):
    """Xoá một ảnh TRƯỚC lần nạp đầu tiên: collection chưa có, và đó là chuyện bình thường.

    Qdrant trả 404 `Collection … doesn't exist!`, và để nó bay lên là job `kb_delete`
    failed hiện trên màn hình người dùng cho một thao tác đã thành công (đo trên dev
    2026-08-12: 2 job failed vì đúng lý do này).
    """
    assert await store.delete_by_record("t_chua_co", record_id=1, doc_type="csbh") == 0


async def test_scroll_khong_loc_anchor_tra_ca_point_he_cu(store):
    """Point hệ cũ KHÔNG có khoá `anchor_code`, và point mới cũng không (khoá đã bỏ —
    `scroll_points` nay lọc theo `project_id`, khoá duy nhất có ở cả ba thế hệ point).

    Job thu hồi caption quét cả collection `_media` (spec §9); lọc theo anchor ở đó
    nghĩa là thu hồi 0 caption và vẫn trả tiền VLM cho toàn bộ ảnh cũ.
    """
    await store.ensure_collection("t_sc_all", media=False)
    await store.upsert(
        "t_sc_all",
        [
            PointIn(point_id_of("", 960, 0), {"dense": [0.1] * 1024}, {"record_id": 960, "project_id": "MPP"}),
            PointIn(
                point_id_of("", 961, 0),
                {"dense": [0.1] * 1024},
                {"record_id": 961, "anchor_code": "nplb", "project_id": "nplb"},
            ),
        ],
    )
    pts = await store.scroll_points("t_sc_all")
    assert sorted(p.record_id for p in pts) == [960, 961]


async def test_scroll_tra_record_id_va_content_hash(store):
    await store.ensure_collection("t_sc", media=False)
    await store.upsert(
        "t_sc",
        [
            PointIn(
                point_id_of("tai_lieu", 9, 0),
                {"dense": [0.1] * 1024},
                # Lọc theo `project_id`: `anchor_code` đã bỏ khỏi payload 2026-08-14.
                {"record_id": 9, "project_id": "nplb", "content_hash": "abc"},
            )
        ],
    )
    pts = await store.scroll_points("t_sc", anchor_code="nplb")
    assert [(p.record_id, p.content_hash) for p in pts] == [(9, "abc")]


async def test_payload_of_tra_dung_payload_da_ghi(store):
    """`payload_of` phục vụ test hợp đồng payload (Task 9) và job thu hồi caption (Task 11)."""
    await store.ensure_collection("t_pl", media=False)
    pid = point_id_of("tai_lieu", 3, 0)
    await store.upsert("t_pl", [PointIn(pid, {"dense": [0.1] * 1024}, {"record_id": 3, "caption": "chú thích"})])
    assert await store.payload_of("t_pl", point_id=pid) == {"record_id": 3, "caption": "chú thích"}


async def test_aclose_goi_hai_lan_khong_no(qdrant_url):
    """`rag` và `media` dùng chung một `QdrantStore`; khối dọn của worker đóng cả hai."""
    s = QdrantStore(url=qdrant_url)
    await s.aclose()
    await s.aclose()


async def test_drop_collection_xoa_han(store):
    await store.ensure_collection("t_drop", media=False)
    await store.drop_collection("t_drop")
    with pytest.raises(UnexpectedResponse):
        await store.count("t_drop")


# ─── ghi lại tiền tố tên dự án trong `text` (đổi nhãn) ──────────────────────
# LLM đọc `text`. Chỉ đổi `project_name` trong payload là tiêu đề khối mang tên mới
# trong khi thân bài vẫn nói tên cũ — và đó là thứ khách nghe được.


def _diem(idx: int, *, text: str, section_path: list[str]) -> PointIn:
    return PointIn(
        point_id_of("tai_lieu", 1, idx),
        {"dense": [0.1] * 1024},
        {"record_id": 1, "project_id": "P1", "text": text, "section_path": section_path},
    )


async def _text_cua(store: QdrantStore, name: str) -> list[str]:
    diem = await store._scroll_payload(name, "P1")  # noqa: SLF001 — chỉ đọc, không có API công khai
    return sorted(str(pl.get("text")) for _, pl in diem)


async def test_doi_ten_ghi_lai_tien_to_theo_tung_section(store):
    """Tiền tố mỗi point khác nhau (tên + cấp cuối `section_path`) nên một lời gọi
    `set_payload` phẳng không làm được — phải sửa từng point."""
    await store.ensure_collection("t_nhan", media=False)
    await store.upsert(
        "t_nhan",
        [
            _diem(0, text="Tên Cũ — Tổng quan\n\nNội dung A", section_path=["Tổng quan"]),
            _diem(1, text="Tên Cũ — Tiện ích\n\nNội dung B", section_path=["Gốc", "Tiện ích"]),
        ],
    )

    n = await store.doi_ten_trong_text("t_nhan", anchor_code="P1", ten_cu="Tên Cũ", ten_moi="Tên Mới")

    assert n == 2
    assert await _text_cua(store, "t_nhan") == [
        "Tên Mới — Tiện ích\n\nNội dung B",
        "Tên Mới — Tổng quan\n\nNội dung A",
    ]


async def test_doi_ten_khong_cham_point_co_tien_to_khong_khop(store):
    """So khớp NGUYÊN VĂN, không đoán theo hình dạng: một chunk hoàn toàn có thể mở
    đầu bằng một dòng ngắn rồi dòng trống, và đoán sai ở đó là ghi đè nội dung khách."""
    await store.ensure_collection("t_nhan2", media=False)
    await store.upsert(
        "t_nhan2",
        [
            _diem(0, text="Một dòng mở đầu bình thường\n\nThân bài", section_path=["Tổng quan"]),
            _diem(1, text="Tên Khác Hẳn — Tổng quan\n\nThân bài", section_path=["Tổng quan"]),
        ],
    )

    n = await store.doi_ten_trong_text("t_nhan2", anchor_code="P1", ten_cu="Tên Cũ", ten_moi="Tên Mới")

    assert n == 0
    assert "Tên Mới" not in " ".join(await _text_cua(store, "t_nhan2"))


async def test_doi_ten_khong_co_dong_trong_thi_bo_qua(store):
    """Không có `\\n\\n` nghĩa là point không mang tiền tố — cắt bừa là mất nội dung."""
    await store.ensure_collection("t_nhan3", media=False)
    await store.upsert("t_nhan3", [_diem(0, text="Tên Cũ — Tổng quan", section_path=["Tổng quan"])])

    assert await store.doi_ten_trong_text("t_nhan3", anchor_code="P1", ten_cu="Tên Cũ", ten_moi="Tên Mới") == 0


async def test_doi_ten_trung_ten_cu_thi_khong_lam_gi(store):
    await store.ensure_collection("t_nhan4", media=False)
    await store.upsert("t_nhan4", [_diem(0, text="T — Tổng quan\n\nX", section_path=["Tổng quan"])])

    assert await store.doi_ten_trong_text("t_nhan4", anchor_code="P1", ten_cu="T", ten_moi="T") == 0


async def test_doi_ten_collection_chua_ton_tai_khong_nem(store):
    assert await store.doi_ten_trong_text("t_chua_co", anchor_code="P1", ten_cu="A", ten_moi="B") == 0


def test_doi_ten_doc_tien_to_tu_text_khong_can_section_path():
    """Payload không còn `section_path` ⇒ tiền tố cũ phải suy từ chính dòng đầu của `text`."""
    from portal.modules.kb.index.store import tach_tien_to

    assert tach_tien_to("Dự án 1 — Phân khu\n\nnội dung", "Dự án 1") == ("Dự án 1 — Phân khu", "nội dung")
    assert tach_tien_to("Dự án 1\n\nnội dung", "Dự án 1") == ("Dự án 1", "nội dung")
    # Tên khác ⇒ không đụng.
    assert tach_tien_to("Dự án 2 — Phân khu\n\nnội dung", "Dự án 1") is None
    # Tên là TIỀN TỐ của tên khác, không có dấu phân cách ⇒ không đụng.
    assert tach_tien_to("Dự án 12 — Phân khu\n\nnội dung", "Dự án 1") is None
    # Không có dòng trống ngăn cách ⇒ không đụng.
    assert tach_tien_to("Dự án 1 — Phân khu", "Dự án 1") is None


def _vec(*head: float) -> list[float]:
    v = [0.0] * 1024
    v[: len(head)] = head
    return v


def _point(doc_type: str, record_id: int, project: str, text: str, vec: list[float]) -> PointIn:
    payload = {"project_id": project, "project_name": "Dự án", "doc_type": doc_type, "record_id": record_id}
    payload["text"] = f"Dự án — Mục\n\n{text}"
    return PointIn(point_id_of(doc_type, record_id, 0), {"dense": vec}, payload)


@pytest.fixture
async def du_an_co_vector(store):
    name = "t_similar"
    await store.ensure_collection(name, media=False)
    await store.upsert(
        name,
        [
            _point("csbh", 1, "p", "chiết khấu 2%", _vec(1.0, 0.1)),
            _point("csbh", 2, "p", "chiết khấu 3%", _vec(1.0, 0.2)),
            _point("tong_quan", 9, "p", "chủ đầu tư Noble", _vec(0.9, 0.3)),
            _point("csbh", 5, "q", "dự án khác", _vec(1.0, 0.1)),
        ],
    )
    return name


async def test_lay_doan_kem_vector_theo_ban_ghi(store, du_an_co_vector):
    pts = await store.points_with_vectors(du_an_co_vector, anchor_code="p", record_id=1)
    assert [(p.record_id, p.doc_type) for p in pts] == [(1, "csbh")]
    assert len(pts[0].vector) == 1024
    assert pts[0].text == "chiết khấu 2%"


async def test_lay_doan_loc_theo_doc_type(store, du_an_co_vector):
    pts = await store.points_with_vectors(du_an_co_vector, anchor_code="p", doc_types={"tong_quan"})
    assert [p.record_id for p in pts] == [9]


async def test_collection_chua_co_thi_rong(store):
    assert await store.points_with_vectors("t_khong_co", anchor_code="p") == []


async def test_tim_tuong_dong_cung_du_an_bo_chinh_no(store, du_an_co_vector):
    hits = await store.similar(
        du_an_co_vector,
        vector=_vec(1.0, 0.1),
        anchor_code="p",
        exclude_record_id=1,
        doc_types={"csbh", "tong_quan"},
        limit=3,
        min_score=0.5,
    )
    assert [h.record_id for h in hits] == [2, 9]
    assert hits[0].score >= hits[1].score


async def test_bo_chinh_no_chi_trong_doc_type_cho_truoc(store, du_an_co_vector):
    hits = await store.similar(
        du_an_co_vector,
        vector=_vec(1.0, 0.1),
        anchor_code="p",
        exclude_record_id=9,
        exclude_doc_types={"csbh"},
        doc_types={"csbh", "tong_quan"},
        limit=3,
        min_score=0.5,
    )
    assert [(h.record_id, h.doc_type) for h in hits] == [(1, "csbh"), (2, "csbh"), (9, "tong_quan")]


async def test_nguong_cao_hon_diem_thi_rong(store, du_an_co_vector):
    hits = await store.similar(
        du_an_co_vector,
        vector=_vec(0.0, 0.0, 1.0),
        anchor_code="p",
        exclude_record_id=None,
        doc_types={"csbh"},
        limit=3,
        min_score=0.75,
    )
    assert hits == []
