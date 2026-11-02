"""content_hash_of phải khớp TỪNG BIT với hash mà index() ghi ra.

Lệch một bit là chế độ delta bỏ qua record thật sự đã đổi (hoặc nạp lại record
không đổi) — cả hai đều im lặng.
"""

from portal.modules.kb.clients.media import MediaClient
from portal.modules.kb.clients.rag import RagClient
from portal.modules.kb.contracts import ChunkSpec, MediaDirective, TextDirective


class _EmbedGia:
    """dense/sparse trả đúng số phần tử — index() kiểm độ dài tường minh."""

    async def dense(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]

    async def sparse(self, texts: list[str]) -> list[dict]:
        return [{"indices": [1], "values": [0.5]} for _ in texts]

    async def visual_image(self, urls: list[str]) -> list[list[float]]:
        return [[0.2] * 4 for _ in urls]


class _StoreGia:
    def __init__(self) -> None:
        self.upserted: list = []

    async def delete_by_record(self, name, *, record_id, doc_type="") -> int:
        return 1

    async def upsert(self, name, points) -> int:
        self.upserted.extend(points)
        return len(points)


def _chi_thi_text(text: str = "Nội dung dài vừa phải", anchor_name: str = "Dự án A") -> TextDirective:
    return TextDirective(
        workspace_slug="acme",
        record_id=7,
        doc_type="phan_khu",
        anchor_code="pa",
        anchor_name=anchor_name,
        section=f"{anchor_name} > Khu B",
        text=text,
        chunk=ChunkSpec(max_chars=800, overlap=150, min_chars=0),
        entity="zones",
    )


async def test_hash_text_khop_voi_hash_ma_index_ghi_ra():
    client = RagClient(embed=_EmbedGia(), store=_StoreGia())
    chi_thi = _chi_thi_text()

    truoc = client.content_hash_of(chi_thi)
    ket_qua = await client.index(chi_thi)

    assert truoc == ket_qua.content_hash != ""


async def test_doi_ten_du_an_KHONG_lam_doi_hash():
    """LẬT NGƯỢC hành vi trước 2026-08-14, và đó là cả mục đích của việc đổi.

    Cũ: tiền tố được prepend TRƯỚC khi băm, nên đổi tên dự án làm dấu tay của MỌI phân khu
    và MỌI tài liệu con đổi theo ⇒ nhúng lại cả cây (một dự án có thể 116 record) trong khi
    nội dung không đổi một chữ.

    Mới: băm nội dung THUẦN. Đổi tên chỉ cần cập nhật payload — xem hợp đồng payload §4.
    """
    client = RagClient(embed=_EmbedGia(), store=_StoreGia())
    a = client.content_hash_of(_chi_thi_text(anchor_name="Dự án A"))
    b = client.content_hash_of(_chi_thi_text(anchor_name="Dự án B ĐÃ ĐỔI TÊN"))
    assert a == b


async def test_doi_NOI_DUNG_van_lam_doi_hash():
    """Phép đo phải phân biệt được "nhãn đổi" với "nội dung đổi" — nếu không thì test trên
    xanh cả khi hàm băm trả một hằng số."""
    client = RagClient(embed=_EmbedGia(), store=_StoreGia())
    a = client.content_hash_of(_chi_thi_text(text="nội dung cũ"))
    b = client.content_hash_of(_chi_thi_text(text="nội dung mới"))
    assert a != b


async def test_doi_TIEU_DE_MUC_van_lam_doi_hash():
    """Tiêu đề `##` của chính section NẰM TRONG text (chunker giữ lại), khác với tên dự án
    và `section_path` — nên đổi tên một mục vẫn là thay đổi thật."""
    client = RagClient(embed=_EmbedGia(), store=_StoreGia())
    a = client.content_hash_of(_chi_thi_text(text="## Tổng quan\nnội dung"))
    b = client.content_hash_of(_chi_thi_text(text="## Giới thiệu\nnội dung"))
    assert a != b


async def test_noi_dung_rong_tra_hash_rong():
    client = RagClient(embed=_EmbedGia(), store=_StoreGia())
    assert client.content_hash_of(_chi_thi_text(text="   ")) == ""


async def test_hash_media_khop_voi_index():
    client = MediaClient(embed=_EmbedGia(), store=_StoreGia())
    chi_thi = MediaDirective(
        workspace_slug="acme",
        record_id=11,
        anchor_code="pa",
        content_type="image",
        category="tong_quan",
        media_url="tenants/acme/img/a.jpg",
        caption="Toàn cảnh khu căn hộ",
    )

    truoc = client.content_hash_of(chi_thi)
    ket_qua = await client.index(chi_thi)

    assert truoc == ket_qua.content_hash != ""


async def test_doi_caption_lam_doi_hash_media():
    client = MediaClient(embed=_EmbedGia(), store=_StoreGia())

    def _cua(caption: str) -> MediaDirective:
        return MediaDirective(
            workspace_slug="acme",
            record_id=11,
            anchor_code="pa",
            content_type="image",
            category="tong_quan",
            media_url="tenants/acme/img/a.jpg",
            caption=caption,
        )

    assert client.content_hash_of(_cua("mô tả cũ")) != client.content_hash_of(_cua("mô tả mới"))
