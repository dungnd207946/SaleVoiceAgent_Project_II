"""WebIndex — ghi/đọc collection `public_web` (Qdrant thật, collection riêng của test)."""

import logging
import uuid
from datetime import UTC, datetime

import pytest
from qdrant_client import AsyncQdrantClient

from portal.modules.kb.web.compose import card_id, digest_ids, dossier_ids
from portal.modules.kb.web.contracts import Item, Source
from portal.modules.kb.web.index import WebIndex

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 29, tzinfo=UTC)
SRC = (Source("https://cafef.vn/a", "CafeF", NOW),)


class FakeEmbed:
    def __init__(self):
        self.texts = []

    async def dense(self, texts):
        self.texts.extend(texts)
        return [[0.01 * (i + 1)] * 1024 for i, _ in enumerate(texts)]

    async def sparse(self, texts):
        return [{"indices": [1, 2], "values": [1.0, 0.5]} for _ in texts]


@pytest.fixture
async def web_index(qdrant_url):
    client = AsyncQdrantClient(url=qdrant_url, check_compatibility=False, timeout=60)
    idx = WebIndex(client=client, embed=FakeEmbed(), collection=f"test_web_{uuid.uuid4().hex[:8]}")
    await idx.ensure()
    await idx.ensure()
    yield idx
    await client.delete_collection(idx.collection)
    await client.close()


def _item(text, project="NPTTL", location=("Đan Phượng",)):
    return Item(text, SRC, (project,), location)


async def test_replace_ghi_de_va_xoa_muc_thua(web_index):
    ids = dossier_ids("NPTTL")
    await web_index.replace(ids, [_item("a [1]"), _item("b [1]"), _item("c [1]")], NOW)
    await web_index.replace(ids, [_item("a2 [1]"), _item("b2 [1]")], NOW)
    got = await web_index.get(ids)
    assert [i.text for i in got] == ["a2 [1]", "b2 [1]"]
    assert got[0].updated_at == NOW


async def test_cards_near_chi_lay_the_va_bo_chinh_minh(web_index):
    await web_index.replace([card_id("Wonder City")], [_item("thẻ WC [1]", "Wonder City")], NOW)
    await web_index.replace([card_id("NPTTL")], [_item("thẻ NPTTL [1]", "NPTTL")], NOW)
    await web_index.replace(dossier_ids("Riverside"), [_item("hồ sơ RS [1]", "Riverside")], NOW)
    got = await web_index.cards_near(["Đan Phượng"], exclude="NPTTL")
    assert [i.projects[0] for i in got] == ["wonder city"]


# ─── Edge case bổ sung ───────────────────────────────────────────────────────


async def test_ensure_tao_dung_bon_chi_muc_payload(web_index):
    info = await web_index._c.get_collection(web_index.collection)  # type: ignore[attr-defined]
    assert set(info.payload_schema.keys()) == {"kind", "location", "projects", "published_at", "updated_at"}


async def test_get_giu_thu_tu_va_bo_id_khong_co(web_index):
    ids = dossier_ids("NPTTL")
    await web_index.replace(ids[:2], [_item("a [1]"), _item("b [1]")], NOW)
    got = await web_index.get([ids[1], ids[0], ids[5]])
    assert [i.text for i in got] == ["b [1]", "a [1]"]


async def test_replace_khong_dung_qua_id_space_cua_muc_khac(web_index):
    """Rút số lượng của một dự án không được xoá dossier của dự án khác hay thẻ của chính nó."""
    other_ids = dossier_ids("Riverside")
    await web_index.replace(other_ids, [_item("rs1 [1]", "Riverside"), _item("rs2 [1]", "Riverside")], NOW)
    card = card_id("NPTTL")
    await web_index.replace([card], [_item("thẻ [1]")], NOW)

    ids = dossier_ids("NPTTL")
    await web_index.replace(ids, [_item("a [1]"), _item("b [1]"), _item("c [1]")], NOW)
    await web_index.replace(ids, [_item("a2 [1]")], NOW)

    assert [i.text for i in await web_index.get(other_ids)] == ["rs1 [1]", "rs2 [1]"]
    assert [i.text for i in await web_index.get([card])] == ["thẻ [1]"]


async def test_replace_voi_zero_item_xoa_ca_ho(web_index):
    ids = dossier_ids("NPTTL")
    await web_index.replace(ids, [_item("a [1]"), _item("b [1]")], NOW)
    n = await web_index.replace(ids, [], NOW)
    assert n == 0
    assert await web_index.get(ids) == []


async def test_payload_luu_dung_bay_khoa(web_index):
    ids = dossier_ids("NPTTL")
    await web_index.replace(ids[:1], [_item("a [1]")], NOW)
    point = (await web_index._c.retrieve(web_index.collection, ids=[ids[0]], with_payload=True))[0]  # type: ignore[attr-defined]
    keys = {"kind", "text", "location", "projects", "sources", "published_at", "updated_at"}
    assert set(point.payload.keys()) == keys


async def test_cards_near_bo_qua_ho_so_va_digest_cung_dia_diem(web_index):
    """Điểm dossier/digest có cùng location vẫn KHÔNG được coi là thẻ."""
    await web_index.replace(dossier_ids("Riverside"), [_item("hồ sơ RS [1]", "Riverside")], NOW)
    await web_index.replace([card_id("Wonder City")], [_item("thẻ WC [1]", "Wonder City")], NOW)
    got = await web_index.cards_near(["Đan Phượng"], exclude="")
    assert [i.projects[0] for i in got] == ["wonder city"]


async def test_cards_near_chuan_hoa_ten_loai_tru_giong_card_id(web_index):
    """`exclude` được chuẩn hoá cùng cách `card_id` — khác hoa/thường và khoảng trắng vẫn khớp."""
    await web_index.replace([card_id("NPTTL")], [_item("thẻ NPTTL [1]", "NPTTL")], NOW)
    await web_index.replace([card_id("Wonder City")], [_item("thẻ WC [1]", "Wonder City")], NOW)
    got = await web_index.cards_near(["Đan Phượng"], exclude="  npttl  ")
    assert [i.projects[0] for i in got] == ["wonder city"]


async def test_cards_near_gioi_han_limit(web_index):
    for i in range(3):
        await web_index.replace([card_id(f"P{i}")], [_item(f"thẻ {i} [1]", f"P{i}")], NOW)
    got = await web_index.cards_near(["Đan Phượng"], exclude="", limit=2)
    assert len(got) == 2


async def test_cards_near_khong_dia_diem_tra_rong(web_index):
    await web_index.replace([card_id("Wonder City")], [_item("thẻ WC [1]", "Wonder City")], NOW)
    assert await web_index.cards_near([], exclude="") == []


async def test_cards_near_lat_trang_khong_bo_sot_the(web_index):
    """Nhiều thẻ bị loại (cùng dự án với `exclude`) tràn qua nhiều trang quét —
    cả hai thẻ còn lại vẫn phải được tìm thấy, không rơi theo trang đầu."""
    for i in range(25):
        name = f"FillerProj Khu {'abcdefghij'[i // 10]}{'abcdefghij'[i % 10]}"
        await web_index.replace([card_id(name)], [_item(f"filler {i} [1]", name)], NOW)
    await web_index.replace([card_id("Card A")], [_item("thẻ A [1]", "Card A")], NOW)
    await web_index.replace([card_id("Card B")], [_item("thẻ B [1]", "Card B")], NOW)

    got = await web_index.cards_near(["Đan Phượng"], exclude="FillerProj", page_size=10)
    assert sorted(i.projects[0] for i in got) == ["card a", "card b"]


async def test_cards_near_cham_max_scan_dung_va_canh_bao(web_index, caplog):
    """`max_scan` chặn quét vô hạn khi một khu vực có quá nhiều thẻ bị loại (cùng dự án với `exclude`)."""
    for i in range(30):
        name = f"FillerProj Khu {'abcdefghij'[i // 10]}{'abcdefghij'[i % 10]}"
        await web_index.replace([card_id(name)], [_item(f"filler {i} [1]", name)], NOW)

    calls = 0
    orig_scroll = web_index._c.scroll  # type: ignore[attr-defined]

    async def counting_scroll(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await orig_scroll(*args, **kwargs)

    web_index._c.scroll = counting_scroll  # type: ignore[attr-defined]
    # `alembic.env.fileConfig` (chạy trong fixture `pool` của phiên test) tắt (`disabled`)
    # mọi logger đã tồn tại trước nó — bật lại để caplog bắt được cảnh báo bên dưới.
    logging.getLogger("portal.modules.kb.web.index").disabled = False
    with caplog.at_level("WARNING"):
        got = await web_index.cards_near(["Đan Phượng"], exclude="FillerProj", page_size=5, max_scan=12)

    assert got == []
    assert calls == 3  # 3 trang x 5 = 15 >= max_scan=12, dừng ngay sau lượt thứ 3, không quét hết 30
    assert "max_scan" in caplog.text


async def test_cards_near_so_cung_dang_chuan_hoa_hai_phia(web_index):
    await web_index.replace([card_id("Wonder City")], [_item("thẻ WC [1]", "Wonder City", ("Huyện Đan Phượng",))], NOW)
    (point,) = await web_index._c.retrieve(web_index.collection, ids=[card_id("Wonder City")], with_payload=True)
    assert point.payload["location"] == ["đan phượng"]
    got = await web_index.cards_near(["H.Đan Phượng"], exclude="")
    assert [i.projects[0] for i in got] == ["wonder city"]


# ─── tên dự án chuẩn hoá (lượt chạy 2026-10-01) ──────────────────────────────


async def test_payload_projects_luu_dang_chuan_hoa(web_index):
    cid = card_id("VINHOMES GLOBAL GATE (TMDV)")
    await web_index.replace([cid], [_item("thẻ [1]", "VINHOMES GLOBAL GATE (TMDV)")], NOW)
    (point,) = await web_index._c.retrieve(web_index.collection, ids=[cid], with_payload=True)
    assert point.payload["projects"] == ["vinhomes global gate"]
    assert cid == card_id("Vinhomes Global Gate")


async def test_cards_near_bo_the_cung_du_an_theo_tien_to_hau_to(web_index):
    for name in ("Royal Island", "Vinhomes Royal Island Phân Khu Mới", "Vinhomes Ocean Park 2", "Wonder City"):
        await web_index.replace([card_id(name)], [_item(f"thẻ {name} [1]", name)], NOW)
    got = await web_index.cards_near(["Đan Phượng"], exclude="VINHOMES ROYAL ISLAND")
    assert sorted(i.projects[0] for i in got) == ["vinhomes ocean park 2", "wonder city"]
    got = await web_index.cards_near(["Đan Phượng"], exclude="Vinhomes Ocean Park")
    assert "vinhomes ocean park 2" in {i.projects[0] for i in got}


async def test_cards_near_doc_duoc_the_cu_chua_chuan_hoa(web_index):
    """Point ghi trước khi chuẩn hoá (payload `projects` còn hoa/ngoặc) vẫn là thẻ và vẫn bị loại đúng."""
    from qdrant_client import models

    for name in ("Royal Island", "VINHOMES GOLDEN CITY (TMDV)"):
        await web_index._c.upsert(
            web_index.collection,
            points=[
                models.PointStruct(
                    id=card_id(name),
                    vector={"dense": [0.01] * 1024},
                    payload={
                        "kind": "du_an_lan_can",
                        "text": "thẻ [1]",
                        "projects": [name],
                        "location": ["đan phượng"],
                        "sources": [],
                    },
                )
            ],
            wait=True,
        )
    got = await web_index.cards_near(["Đan Phượng"], exclude="Vinhomes Royal Island")
    assert [i.projects[0] for i in got] == ["VINHOMES GOLDEN CITY (TMDV)"]


async def _payload(web_index, pid):
    return (await web_index._c.retrieve(web_index.collection, ids=[pid], with_payload=True))[0].payload  # type: ignore[attr-defined]


async def test_kind_ghi_theo_dai_id(web_index):
    vri = "Vinhomes Royal Island"
    await web_index.replace(dossier_ids(vri)[:1], [_item("hồ sơ [1]", vri)], NOW)
    await web_index.replace([card_id("Ecopark")], [_item("thẻ [1]", "Ecopark")], NOW)
    await web_index.replace(digest_ids("toan_quoc")[:1], [Item("tin [1]", SRC, (), ())], NOW)
    assert (await _payload(web_index, dossier_ids("Vinhomes Royal Island")[0]))["kind"] == "ho_so_du_an"
    assert (await _payload(web_index, card_id("Ecopark")))["kind"] == "du_an_lan_can"
    assert (await _payload(web_index, digest_ids("toan_quoc")[0]))["kind"] == "ban_tin_thi_truong"


async def test_tieu_de_nam_trong_text_va_duoc_embed(web_index):
    header = "Dự án VINHOMES ROYAL ISLAND — Đảo Vũ Yên, Hải Phòng"
    pid = dossier_ids("Vinhomes Royal Island")[0]
    await web_index.replace([pid], [_item("Hệ thống giao thông [1]", "Vinhomes Royal Island")], NOW, header=header)
    text = (await _payload(web_index, pid))["text"]
    assert text.splitlines()[1] == f"[{header}]"
    assert web_index._embed.texts[-1] == f"{header}\nHệ thống giao thông [1]"  # type: ignore[attr-defined]
    (back,) = await web_index.get([pid])
    assert back.text == "Hệ thống giao thông [1]"


async def test_cards_near_loc_theo_kind_khong_lay_ho_so(web_index):
    """Hồ sơ mang projects=[tên] cùng location vẫn không lẫn vào thẻ — lọc bằng `kind`."""
    await web_index.replace(dossier_ids("Ecopark"), [_item("hồ sơ Ecopark [1]", "Ecopark")], NOW)
    got = await web_index.cards_near(["Đan Phượng"], exclude="")
    assert got == []


async def test_don_du_an_xoa_ho_so_va_the_cua_dung_ten_do(web_index, monkeypatch, web_tenant, api_pool):
    from types import SimpleNamespace

    from portal.core.db.session import tenant_conn
    from portal.modules.kb.web import jobs

    from .conftest import TENANT

    await web_index.replace(dossier_ids("Dự án Cũ"), [_item("Tổng quan: A.", "Dự án Cũ")], NOW)
    await web_index.replace([card_id("Dự án Cũ")], [_item("Thẻ cũ.", "Dự án Cũ")], NOW)
    await web_index.replace(dossier_ids("NPTTL"), [_item("Tổng quan: B.")], NOW)

    class _Rt:
        async def for_tenant(self, tenant):
            return SimpleNamespace(index=web_index)

    monkeypatch.setattr(jobs, "_shared_runtime", _Rt())
    async with tenant_conn(api_pool, TENANT) as c:
        r = await jobs.handle_purge(c, {"project_name": "Dự án Cũ"})
    assert r.count == 2
    assert await web_index.get(dossier_ids("Dự án Cũ")) == [] and await web_index.get([card_id("Dự án Cũ")]) == []
    assert len(await web_index.get(dossier_ids("NPTTL"))) == 1, "dự án khác không bị đụng"
