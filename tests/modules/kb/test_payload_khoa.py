"""Payload documents — 11 khoá. `section`/`section_path`/`page` đã bỏ (spec 2026-08-19 §D3).

Bằng chứng: quét 136 point thật trên 4 collection, 136/136 có `text` mở đầu đúng bằng
`"<project_name> — <section_path[-1]>"`. Ba khoá nói cùng một chuyện.
"""

from portal.modules.kb.clients.rag import RagClient
from portal.modules.kb.contracts import ChunkSpec, TextDirective

KHOA_MONG_DOI = {
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
}


class _StoreGia:
    def __init__(self) -> None:
        self.points: list = []

    async def delete_by_record(self, name, *, record_id, doc_type=""):
        return 0

    async def upsert(self, name, points):
        self.points.extend(points)
        return len(points)


class _EmbedGia:
    async def dense(self, texts):
        return [[0.0] * 4 for _ in texts]

    async def sparse(self, texts):
        return [{"indices": [1], "values": [1.0]} for _ in texts]


async def _index(text: str):
    store = _StoreGia()
    client = RagClient(embed=_EmbedGia(), store=store)
    await client.index(
        TextDirective(
            workspace_slug="ws",
            record_id=426,
            doc_type="tong_quan",
            anchor_code="P1",
            anchor_name="Dự án 1",
            section="bỏ đi",
            text=text,
            chunk=ChunkSpec(1000, 100, 300),
            status="published",
            anchor_status="published",
            entity="projects",
        )
    )
    return store.points


async def test_payload_dung_11_khoa():
    points = await _index("## Khu vực\nQuảng Ninh")
    assert set(points[0].payload) == KHOA_MONG_DOI


async def test_khong_con_ba_khoa_da_bo():
    points = await _index("## Khu vực\nQuảng Ninh")
    for khoa in ("section", "section_path", "page"):
        assert khoa not in points[0].payload


async def test_nhan_muc_van_con_trong_text():
    """Bỏ khoá được vì `_tien_to()` đã gắn nhãn vào đầu MỌI chunk."""
    points = await _index("## Cơ cấu sản phẩm\n### Phân khu\n- **A**")
    assert points[0].payload["text"].startswith("Dự án 1 — Phân khu\n\n")


def test_chuoi_nhung_bo_url_giu_alt():
    from portal.modules.kb.clients.rag import _text_de_nhung
    from portal.modules.kb.contracts import ChunkSpec, TextDirective
    from portal.modules.kb.index.chunker import Chunk

    d = TextDirective(
        workspace_slug="ws",
        record_id=1,
        doc_type="kb_file",
        anchor_code="__ALL__",
        anchor_name="Sổ tay",
        section="",
        text="",
        chunk=ChunkSpec(),
    )
    c = Chunk("Bấm Quên mật khẩu.\n\n![Màn đăng nhập AINA](https://portal.vn/x/a.png)", ())

    out = _text_de_nhung(d, c)

    assert "https://" not in out
    assert "Màn đăng nhập AINA" in out  # alt là thứ DUY NHẤT mang nghĩa của ảnh
    assert "Bấm Quên mật khẩu." in out


def test_chunk_text_van_giu_markdown_day_du():
    """`payload["text"]` lấy từ `chunk.text`, KHÔNG từ chuỗi nhúng — agent đọc nó để
    dựng `items`, bỏ URL ở đó là mất luôn ảnh. Bài này canh hai chuỗi ĐÃ TÁCH ĐÔI."""
    from portal.modules.kb.clients.rag import _text_de_nhung
    from portal.modules.kb.contracts import ChunkSpec, TextDirective
    from portal.modules.kb.index.chunker import Chunk

    d = TextDirective(
        workspace_slug="ws",
        record_id=1,
        doc_type="kb_file",
        anchor_code="__ALL__",
        anchor_name="",
        section="",
        text="",
        chunk=ChunkSpec(),
    )
    c = Chunk("![Màn đăng nhập](https://portal.vn/x/a.png)", ())

    assert "![" in c.text and "https://" in c.text  # nguồn của payload: nguyên vẹn
    assert "![" not in _text_de_nhung(d, c)  # chuỗi nhúng: đã bỏ


def test_chuoi_nhung_khong_dinh_manh_vun_khi_url_co_ngoac_tron():
    """`_IMG_MD` cũ cắt cụt tại dấu `)` đầu tiên trong URL — với `file(1).png` đó là
    ngoặc GIỮA URL, nên phần đuôi (`.png)`) còn sót lại và dính vào alt ảnh kế tiếp
    (`'Alt.png) sau đó Alt2'`). Chuỗi nhúng phải dùng cùng regex cân bằng ngoặc với
    `external_images.IMG_MD_RE`, không phải một bản chép tay ngây thơ."""
    from portal.modules.kb.clients.rag import _text_de_nhung
    from portal.modules.kb.contracts import ChunkSpec, TextDirective
    from portal.modules.kb.index.chunker import Chunk

    d = TextDirective(
        workspace_slug="ws",
        record_id=1,
        doc_type="kb_file",
        anchor_code="__ALL__",
        anchor_name="",
        section="",
        text="",
        chunk=ChunkSpec(),
    )
    c = Chunk("![Alt](https://x.com/a(1).png) sau đó ![Alt2](https://y.com/b.png)", ())

    out = _text_de_nhung(d, c)

    assert "https://" not in out
    assert ".png)" not in out
    assert out == "Alt sau đó Alt2"


async def test_payload_text_giu_URL_embedding_thi_khong():
    """Round-trip qua `index()`: `payload["text"]` giữ URL, chuỗi đưa vào embed thì không.

    Hai bài trên chỉ canh `_text_de_nhung`/`c.text` riêng lẻ — bài này canh chỗ dễ vỡ
    thật: `index()` phải dùng HAI chuỗi khác nhau cho payload và cho embed, không phải
    dùng chung một biến `texts`.
    """

    class _EmbedGhiNhan(_EmbedGia):
        def __init__(self) -> None:
            self.nhan: list[str] = []

        async def dense(self, texts):
            self.nhan.extend(texts)
            return await super().dense(texts)

    store = _StoreGia()
    embed = _EmbedGhiNhan()
    client = RagClient(embed=embed, store=store)
    await client.index(
        TextDirective(
            workspace_slug="ws",
            record_id=426,
            doc_type="tong_quan",
            anchor_code="P1",
            anchor_name="Dự án 1",
            section="bỏ đi",
            text="![Màn đăng nhập](https://portal.vn/x/a.png)",
            chunk=ChunkSpec(1000, 100, 300),
            status="published",
            anchor_status="published",
            entity="projects",
            images_mirrored=True,
        )
    )

    assert "https://" in store.points[0].payload["text"]
    assert embed.nhan and all("https://" not in t for t in embed.nhan)
