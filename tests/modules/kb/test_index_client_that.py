"""IndexClient thật: directive → point trong Qdrant.

Bộ khoá payload là HỢP ĐỒNG với repo agent — 381 point đang sống có đúng bộ này.
Test cuối là chỗ duy nhất bắt được một lần đổi tên khoá.
"""

import uuid
from dataclasses import replace

import pytest

from portal.modules.kb.clients.media import MediaClient
from portal.modules.kb.clients.media import collection_name as media_collection_name
from portal.modules.kb.clients.rag import RagClient, collection_name
from portal.modules.kb.contracts import ChunkSpec, MediaDirective, TextDirective
from portal.modules.kb.index.store import PointIn, QdrantStore, point_id_of

KHOA_PAYLOAD_CU = {
    "project_id",
    "content_type",
    "category",
    "caption",
    "media_url",
    "content_hash",
    "record_id",
    "thumb_url",
}


class EmbedGia:
    async def dense(self, texts):
        return [[0.1] * 1024 for _ in texts]

    async def sparse(self, texts):
        return [{"indices": [1], "values": [0.5]} for _ in texts]

    async def visual_image(self, urls):
        return [[0.2] * 768 for _ in urls]


@pytest.fixture
async def store(qdrant_url):
    s = QdrantStore(url=qdrant_url)
    yield s
    await s.aclose()


def _text_directive(text: str = "Nội dung tài liệu", workspace_slug: str = "ws") -> TextDirective:
    # Brief gốc khoá cứng workspace_slug="ws": mọi test dùng slug khác ("ws2", "ws3", ...)
    # cho collection thật lại gửi directive trỏ về "ws", nên ghi nhầm collection và
    # `store.count` của collection vừa tạo luôn ra 0. Tham số hoá lại cho khớp collection
    # mỗi test tự tạo.
    return TextDirective(
        workspace_slug=workspace_slug,
        record_id=11,
        entity="documents",
        doc_type="csbh",
        anchor_code="nplb",
        anchor_name="Noble Palace",
        section="Bảng giá",
        text=text,
        chunk=ChunkSpec(max_chars=800, overlap=150, min_chars=0),
    )


async def test_index_text_tao_point_va_tra_content_hash(store):
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws")
    ra = await c.index(_text_directive())
    assert ra.points_upserted >= 1
    assert len(ra.content_hash) == 64
    assert await store.count(collection_name("ws")) == ra.points_upserted


async def test_index_hai_lan_cung_noi_dung_khong_nhan_doi_point(store):
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws2")
    d = _text_directive(workspace_slug="ws2")
    a = await c.index(d)
    b = await c.index(d)
    assert a.content_hash == b.content_hash
    assert await store.count(collection_name("ws2")) == a.points_upserted


async def test_delete_xoa_dung_point(store):
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws3")
    await c.index(_text_directive(workspace_slug="ws3"))
    await c.delete(workspace_slug="ws3", record_id=11, doc_type="csbh")
    assert await store.count(collection_name("ws3")) == 0


async def test_media_payload_giu_nguyen_bo_khoa_cu(store):
    c = MediaClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws4")
    await c.index(
        MediaDirective(
            workspace_slug="ws4",
            record_id=960,
            anchor_code="MPP",
            content_type="image",
            category="mat_bang",
            media_url="https://cdn.test/mb.jpg",
            caption="Bản đồ mặt bằng tầng điển hình.",
            thumb_url="tenants/ws4/kb-bds/x.webp",
        )
    )
    pts = await store.scroll_points("ws4_media", anchor_code="MPP")
    assert len(pts) == 1

    payload = await store.payload_of("ws4_media", point_id=pts[0].point_id)
    assert set(payload) >= KHOA_PAYLOAD_CU, "thiếu khoá payload mà agent đang đọc"


# ─── Dọn point thừa trước khi upsert ────────────────────────────────────────
# Brief gốc chỉ yêu cầu upsert. Thiếu bước xoá trước, hai lỗi thật xảy ra: chunk
# đã rút khỏi tài liệu vẫn sống trong Qdrant (test dưới), và point của hệ cũ (id
# theo công thức khác) không bị đè mà nhân đôi thành hai point cho cùng một ảnh
# (test cuối, dựng lại đúng ca đo được trên hệ thật với record 960).


async def test_index_lai_ngan_hon_khong_con_point_thua(store):
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws5")
    dai = replace(
        _text_directive(
            text="Đoạn văn dài lặp lại nhiều lần để chunk thành nhiều mảnh. " * 10,
            workspace_slug="ws5",
        ),
        chunk=ChunkSpec(max_chars=50, overlap=10, min_chars=0),
    )
    a = await c.index(dai)
    assert a.points_upserted > 1

    ngan = replace(dai, text="Một câu ngắn.")
    b = await c.index(ngan)
    assert b.points_upserted == 1
    assert await store.count(collection_name("ws5")) == 1, "point của lần index dài trước còn sót lại"


async def test_index_noi_dung_bi_xoa_trang_thi_point_cu_khong_song_sot(store):
    """`zones` embed đúng một field (`overview`). Xoá trắng nó → `chunker.split` trả `[]`.

    Thoát sớm ở nhánh rỗng để lại point cũ trong Qdrant trong khi sổ ghi `indexed,
    points=0` và `kb-sync-status` báo "đã đồng bộ" — agent tiếp tục trả lời bằng nội
    dung biên tập viên đã xoá.
    """
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws7")
    dai = replace(
        _text_directive(text="Đoạn văn dài lặp lại nhiều lần để chunk thành nhiều mảnh. " * 10, workspace_slug="ws7"),
        chunk=ChunkSpec(max_chars=50, overlap=10, min_chars=0),
    )
    a = await c.index(dai)
    assert a.points_upserted > 1

    b = await c.index(replace(dai, text=""))

    assert b.points_upserted == 0
    assert await store.count(collection_name("ws7")) == 0, "nội dung đã xoá mà point vẫn sống"


class EmbedThieuPhanTu(EmbedGia):
    """Trả ĐÚNG hình dạng nhưng THIẾU phần tử — `_parse_embeddings` không bắt được."""

    async def sparse(self, texts):
        return [{"indices": [1], "values": [0.5]}]


class EmbedTraRong(EmbedGia):
    async def dense(self, texts):
        return []


async def test_embed_tra_thieu_phan_tu_thi_no_chu_khong_index_thieu(store):
    """`for i, s in enumerate(sparse)` lấy số point theo `len(sparse)`, không theo số chunk.

    Cộng với bước xoá-trước-khi-ghi, phần chunk hụt biến mất khỏi Qdrant trong khi sổ
    vẫn ghi `indexed`. Hình dạng response thật chưa đo được nên phép kiểm phải tường minh.
    """
    c = RagClient(embed=EmbedThieuPhanTu(), store=store)
    await c.create_collection(workspace_slug="ws8")
    nhieu_chunk = replace(
        _text_directive(text="Đoạn văn dài lặp lại nhiều lần để chunk thành nhiều mảnh. " * 10, workspace_slug="ws8"),
        chunk=ChunkSpec(max_chars=50, overlap=10, min_chars=0),
    )
    with pytest.raises(ValueError, match="embed trả thiếu"):
        await c.index(nhieu_chunk)


async def test_media_embed_tra_rong_thi_no_chu_khong_index_point_khong_vector(store):
    c = MediaClient(embed=EmbedTraRong(), store=store)
    await c.create_collection(workspace_slug="ws9")
    with pytest.raises(ValueError, match="embed dense trả"):
        await c.index(
            MediaDirective(
                workspace_slug="ws9",
                record_id=1,
                anchor_code="nplb",
                content_type="image",
                category="mat_bang",
                media_url="https://cdn.test/a.jpg",
                caption="x",
            )
        )


async def test_client_dong_ca_embed_lan_store():
    """`rag` và `media` dùng CHUNG một cặp embed/store (xem `jobs.dependencies`), nên
    `aclose()` phải chịu được lời gọi thứ hai thay vì nổ ở nửa sau của khối `finally`."""

    class _DemLuotDong:
        def __init__(self) -> None:
            self.so_lan = 0

        async def aclose(self) -> None:
            self.so_lan += 1

    embed, kho = _DemLuotDong(), _DemLuotDong()
    c = RagClient(embed=embed, store=kho)
    await c.aclose()
    await c.aclose()
    assert (embed.so_lan, kho.so_lan) == (2, 2)


async def test_payload_documents_dung_bo_khoa_da_chot(store):
    """Payload là HỢP ĐỒNG hai đầu (docs/contracts/payload-qdrant.md §3).

    Test đúng BỘ khoá, không chỉ vài khoá có mặt: đợt 2026-08-14 bỏ 6 khoá và thêm 10, và
    phía agent test KHÔNG ghim tên khoá được render (nó tự dựng dict hit) — nên đây là chỗ
    duy nhất bắt được payload phình lại hay hụt đi.
    """
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws10")
    await c.index(_text_directive(workspace_slug="ws10"))
    pts = await store.scroll_points(collection_name("ws10"), anchor_code="nplb")
    payload = await store.payload_of(collection_name("ws10"), point_id=pts[0].point_id)

    assert set(payload) == {
        "project_id",
        "project_name",
        "record_id",
        "doc_type",
        "text",
        "content_hash",
        "updated_at",
        "status",
        "file_public_url",
        "file_name",
        "thumb_url",
    }, sorted(payload)
    assert "entity" not in payload, "khoá entity đã bỏ — vị từ xoá nay là doc_type"
    assert "anchor_code" not in payload, "trùng đúng giá trị project_id"
    assert "chunk_index" not in payload, "đã nằm trong id point"
    assert "anchor_status" not in payload, "Postgres là nguồn sự thật để soi"
    assert "section" not in payload and "section_path" not in payload, "trùng nội dung text"
    assert "page" not in payload, "hardcode 0 từ ngày đầu, chưa từng có giá trị khác"


async def test_payload_status_hieu_luc_gop_ca_trang_thai_du_an_cha(store):
    """Ảnh/tài liệu `published` dưới một dự án `draft` phải ra `draft` — luật thật cần
    trạng thái của cha, mà cha KHÔNG có mặt trong point của con."""
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws_st")

    async def _status(cua_no: str, cua_cha: str) -> str:
        d = _text_directive(workspace_slug="ws_st")
        d = replace(d, status=cua_no, anchor_status=cua_cha)
        await c.index(d)
        pts = await store.scroll_points(collection_name("ws_st"), anchor_code="nplb")
        payload = await store.payload_of(collection_name("ws_st"), point_id=pts[0].point_id)
        return payload["status"]

    assert await _status("published", "published") == "published"
    assert await _status("published", "draft") == "draft"
    assert await _status("draft", "published") == "draft"
    assert await _status("published", "archived") == "archived"


async def test_index_media_de_len_point_kieu_he_cu(store):
    c = MediaClient(embed=EmbedGia(), store=store)
    ten = media_collection_name("ws6")
    await c.create_collection(workspace_slug="ws6")

    point_kieu_cu = str(uuid.uuid4())
    await store.upsert(
        ten,
        [
            PointIn(
                point_id=point_kieu_cu,
                vectors={"text": [0.1] * 1024, "visual": [0.2] * 768},
                payload={"record_id": 960, "media_url": "https://cdn.test/anh-cu.jpg"},
            )
        ],
    )
    assert await store.count(ten) == 1

    await c.index(
        MediaDirective(
            workspace_slug="ws6",
            record_id=960,
            anchor_code="MPP",
            content_type="image",
            category="mat_bang",
            media_url="https://cdn.test/mb.jpg",
            caption="Chú thích mới",
        )
    )

    assert await store.count(ten) == 1, "point mới phải thay thế, không cộng thêm vào point hệ cũ"
    assert await store.payload_of(ten, point_id=point_kieu_cu) == {}, "point hệ cũ phải bị xoá"


async def test_payload_media_mang_URL_DAY_DU_khong_mang_khoa(store, monkeypatch):
    """Agent đặt thẳng `media_url` vào card chat — khoá S3 ở đó là ảnh vỡ phía khách."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.test")
    client = MediaClient(embed=EmbedGia(), store=store)
    await client.create_collection(workspace_slug="ws_pub")
    await client.index(
        MediaDirective(
            workspace_slug="ws_pub",
            record_id=71,
            anchor_code="NPLB",
            content_type="image",
            category="tong_quan",
            media_url="tenants/ws_pub/kb-bds/sha/a.jpg",
            thumb_url="tenants/ws_pub/kb-bds/sha/a.thumb.webp",
            caption="Toà A ven sông",
        )
    )
    pl = await store.payload_of("ws_pub_media", point_id=point_id_of("", 71, 0))
    assert pl["media_url"] == "https://portal.test/api/v1/public/files/tenants/ws_pub/kb-bds/sha/a.jpg"
    assert pl["thumb_url"].startswith("https://portal.test/api/v1/public/files/")


async def test_url_ngoai_trong_payload_giu_nguyen_van(store, monkeypatch):
    """Ảnh dán từ CDN của khách: nối base vào là ra một URL không tồn tại."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.test")
    client = MediaClient(embed=EmbedGia(), store=store)
    await client.create_collection(workspace_slug="ws_ngoai")
    await client.index(
        MediaDirective(
            workspace_slug="ws_ngoai",
            record_id=72,
            anchor_code="NPLB",
            content_type="image",
            category="tong_quan",
            media_url="https://cdn.khach.vn/a.jpg",
            caption="x",
        )
    )
    pl = await store.payload_of("ws_ngoai_media", point_id=point_id_of("", 72, 0))
    assert pl["media_url"] == "https://cdn.khach.vn/a.jpg"


# ─── tệp gửi kèm câu trả lời: hai khoá từng RỖNG VĨNH VIỄN ──────────────────
# Cả hai lỗi dưới đây chỉ lộ ra khi chạy pipeline thật (2026-08-15): cột có dữ liệu,
# payload có khoá, nhưng khoá rỗng — không lỗi ở đâu cả, chỉ là tệp gửi kèm thành một
# link trần và tên hiện cho khách là một mã nội bộ.


async def test_thumb_url_cua_tai_lieu_di_duoc_vao_payload(store):
    """`thumb_url` phải nằm trong `extra_cols` của spec `documents`.

    Thiếu nó thì đường đọc không select cột, `row.get("thumb_url")` trả None, và khoá
    payload rỗng mãi mãi — dù `0928` đã thêm cột và việc thumb đã ghi vào đó.
    """
    from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE

    spec = next(s for s in REAL_ESTATE.embed_sources if s.table == "documents")
    assert "thumb_url" in spec.extra_cols, "thumb_url không được select ⇒ payload rỗng vĩnh viễn"


async def test_file_name_bo_tien_to_loai_tai_lieu(store):
    """`documents.title` lưu "CSBH — Bảng giá Q3". Đưa nguyên chuỗi đó cho khách là hiện
    một mã nội bộ — giao diện cũng tách nó ra, người dùng chưa từng thấy tiền tố."""
    from portal.modules.kb.directive.resolve import _ten_hien

    assert _ten_hien({"title": "CSBH — Bảng giá Q3"}) == "Bảng giá Q3"
    assert _ten_hien({"title": "Ghi chú không tiền tố"}) == "Ghi chú không tiền tố"
    # Cột thật thắng: `media` CÓ `file_name` (0922), và tên gốc là thứ khách cần thấy.
    assert _ten_hien({"file_name": "goc.pdf", "title": "CSBH — X"}) == "goc.pdf"


async def test_payload_mang_URL_CONG_KHAI_cua_tep_va_thumb(store, monkeypatch):
    """Khoá kho KHÔNG được lọt vào payload — agent cần URL mở được, không cần khoá."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.test")
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="wsfile")
    d = _text_directive(workspace_slug="wsfile")
    d = replace(d, file_url="tenants/x/kb-bds/abc/csbh.pdf", thumb_url="tenants/x/kb-bds/abc/csbh.thumb.webp")
    await c.index(d)

    pts = await store.scroll_points(collection_name("wsfile"), anchor_code="nplb")
    payload = await store.payload_of(collection_name("wsfile"), point_id=pts[0].point_id)

    assert payload["file_public_url"] == "https://portal.test/api/v1/public/files/tenants/x/kb-bds/abc/csbh.pdf"
    assert payload["thumb_url"] == "https://portal.test/api/v1/public/files/tenants/x/kb-bds/abc/csbh.thumb.webp"
    assert not payload["file_public_url"].startswith("tenants/"), "khoá kho lọt vào payload"
