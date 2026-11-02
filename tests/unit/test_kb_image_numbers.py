from noble_agent.agent import facade
from noble_agent.agent.rag import kb_service_adapter as kb
from noble_agent.agent.rag import noble_kb
from noble_agent.agent.tools import noble_search

U1 = "https://portal.vn/api/v1/public/files/tenants/t/kb/anh/aaa.png"
U2 = "https://portal.vn/api/v1/public/files/tenants/t/kb/anh/bbb.png"


def _hit(text):
    return {"text": text, "project_name": "", "section_path": [], "updated_at": ""}


def test_url_khong_bao_gio_vao_ngu_canh():
    numbers = {}
    out = kb._format_kb_hits([_hit(f"Bấm Quên mật khẩu.\n\n![Màn đăng nhập]({U1})")], numbers)
    assert "https://" not in out
    assert "[ảnh 1 — Màn đăng nhập]" in out


def test_so_giu_nguyen_qua_luot():
    """Sổ mang sang lượt sau: cùng ảnh phải cùng số, ảnh mới lấy số kế tiếp."""
    numbers = {}
    kb._format_kb_hits([_hit(f"![a]({U1})")], numbers)
    out = kb._format_kb_hits([_hit(f"![a]({U1})\n\n![b]({U2})")], numbers)
    assert "[ảnh 1 — a]" in out and "[ảnh 2 — b]" in out


def test_anh_moi_o_luot_sau_khong_dung_lai_so_cu():
    numbers = {}
    kb._format_kb_hits([_hit(f"![a]({U1})")], numbers)
    out = kb._format_kb_hits([_hit(f"![b]({U2})")], numbers)
    assert "[ảnh 2 — b]" in out
    assert "[ảnh 1" not in out


def test_dinh_kem_tra_item_anh_co_so():
    numbers = {}
    kb._format_kb_hits([_hit(f"![Màn đăng nhập]({U1})")], numbers)
    items = kb._dinh_kem([_hit(f"![Màn đăng nhập]({U1})")], numbers)
    # Hợp đồng gateway (đã ship, xem gateway-protocol.json §tool_results.kb_search)
    # đòi field "index", không phải "so" — client strict-typed loại item thiếu nó.
    assert items == [{"kind": "image", "url": U1, "label": "Màn đăng nhập", "index": 1}]


def test_cung_anh_hai_chunk_chi_mot_item():
    numbers = {}
    hits = [_hit(f"![a]({U1})"), _hit(f"Nhắc lại.\n\n![a]({U1})")]
    kb._format_kb_hits(hits, numbers)
    assert len(kb._dinh_kem(hits, numbers)) == 1


def test_so_bom_vao_prompt_chan_o_sau_muc():
    """Sổ dài kéo mô hình khỏi tài liệu — đo được: 20 mục làm tỉ lệ nhắc ảnh của chính
    lượt đó tụt còn 2/3, chặn ở 6 đưa lại 3/3."""
    numbers = {f"u{i}": i + 1 for i in range(20)}
    line = kb.earlier_image_lines(numbers, in_use=set())
    assert len(line) == 6
    assert line[0].startswith("- ảnh 15")  # sáu số LỚN NHẤT, tức gần nhất


def test_co_moc_anh_thi_co_dan_do_trich_so():
    """Phần 4 của kế hoạch: có mốc [ảnh N] thì phải có câu dặn trích số đó."""
    numbers = {}
    out = kb._format_kb_hits([_hit(f"![Màn đăng nhập]({U1})")], numbers)
    assert kb._IMAGE_CITATION_INSTRUCTION in out


def test_khong_anh_thi_khong_co_dan_do():
    numbers = {}
    out = kb._format_kb_hits([_hit("Chỉ có chữ, không ảnh nào.")], numbers)
    assert kb._IMAGE_CITATION_INSTRUCTION not in out


def test_nhieu_anh_van_chi_mot_cau_dan_do():
    numbers = {}
    out = kb._format_kb_hits(
        [_hit(f"![a]({U1})"), _hit(f"![b]({U2})")],
        numbers,
    )
    assert out.count(kb._IMAGE_CITATION_INSTRUCTION) == 1


# ── đường THẬT: noble_search.run → facade._NobleKBAdapter → noble_kb.query_noble_kb
# → noble_kb._query_via_kb_service → kb_service_adapter.query_kb_service_for_noble_kb.
# Một stub RAG tay viết nhận mọi keyword không đo được lớp lỗi này: adapter thật của
# production (`_NobleKBAdapter.search`) không có tham số `numbers`, nên nếu sổ không
# được xâu chuỗi hết đường, `except TypeError` sẽ rơi xuống bậc thiếu `numbers` và mỗi
# lượt lại dựng một sổ rỗng mới.


class _State:
    def __init__(self) -> None:
        self.scratchpad: dict = {}


class _Customer:
    project_interest = None


class _DispatcherThat:
    def __init__(self) -> None:
        self.customer = _Customer()
        self.state = _State()

    def mark_customer_dirty(self) -> None:
        pass


def _wire_kb_service_that(monkeypatch, luot_hits: list[list[dict]]) -> None:
    """Trỏ backend `kb_service` vào embed/Qdrant giả, một danh sách hit cho mỗi lượt gọi."""
    monkeypatch.setattr(noble_kb.settings, "noble_rag_backend", "kb_service")
    monkeypatch.setattr(kb.settings, "kb_search_attach_source_files", True)
    monkeypatch.setattr(kb.settings, "qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(kb.settings, "qdrant_api_key", "qkey")
    monkeypatch.setattr(kb, "current_tenant", lambda: "t")

    async def fake_dense(texts, **kw):
        return [[0.1, 0.2]]

    async def fake_sparse(texts, **kw):
        return [{"indices": [1], "values": [1.0]}]

    async def fake_exists(*a, **kw):
        return True

    hang_doi = list(luot_hits)

    async def fake_search(**kw):
        return hang_doi.pop(0)

    monkeypatch.setattr(kb.embed_client, "embed_dense", fake_dense)
    monkeypatch.setattr(kb.embed_client, "embed_sparse", fake_sparse)
    monkeypatch.setattr(kb.qdrant_client, "collection_exists", fake_exists)
    monkeypatch.setattr(kb.qdrant_client, "search_hybrid", fake_search)


async def test_so_anh_giu_nguyen_qua_hai_luot_qua_duong_that(monkeypatch):
    """Ảnh B ở lượt hai PHẢI lấy số 2, không phải số 1 — chỉ đúng khi sổ của lượt một
    (đã ghi vào `state.scratchpad`) sống sót tới lời gọi Qdrant của lượt hai."""
    _wire_kb_service_that(
        monkeypatch,
        [
            [_hit(f"![a]({U1})")],
            [_hit(f"![b]({U2})")],
        ],
    )
    rag = facade._NobleKBAdapter()
    dispatcher = _DispatcherThat()

    ra1 = await noble_search.run(rag, dispatcher, {"query": "ảnh a"})
    ra2 = await noble_search.run(rag, dispatcher, {"query": "ảnh b"})

    assert "[ảnh 1 — a]" in ra1
    assert "[ảnh 2 — b]" in ra2
    assert "[ảnh 1" not in ra2
