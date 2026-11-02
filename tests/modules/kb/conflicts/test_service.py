import re
import uuid

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.conflicts import repo
from portal.modules.kb.conflicts.service import check_project, check_record
from portal.modules.kb.index.store import PointIn, QdrantStore, point_id_of

CSBH_A = "Hiệu lực đến hết 30/11/2026, chiết khấu 2% khi thanh toán đúng hạn."
CSBH_B = "Áp dụng đến hết 31/12/2026, chiết khấu 3% khi thanh toán đúng hạn."
BROCHURE = "Dự án do Công ty CP Bách Giang làm chủ đầu tư, tổng 172 sản phẩm trên 4,3 ha."
QUANG_CAO = "Không gian sống đẳng cấp, hài hoà cùng thiên nhiên."


def _vec(*head: float) -> list[float]:
    v = [0.0] * 1024
    v[: len(head)] = head
    return v


def refs(user_text: str) -> dict[str, str]:
    """`[D1] nhãn\\nchữ` → {"D1": "chữ"}; `[field:...] nhãn: giá trị` → {"field:...": "giá trị"}."""
    out = {m[0]: m[1] for m in re.findall(r"^\[([DC]\d+)\][^\n]*\n([^\n]*)", user_text, re.M)}
    out |= {m[0]: m[1] for m in re.findall(r"^\[(field:[^\]]+)\][^:]*: (.*)$", user_text, re.M)}
    return out


class FakeLlm:
    def __init__(self, decide):
        self.decide = decide
        self.calls: list[str] = []

    async def ask(self, profile: str, user_text: str) -> dict:
        self.calls.append(user_text)
        return self.decide(refs(user_text))


def _ref_of(r: dict[str, str], needle: str, prefix: str = "") -> str | None:
    return next((k for k, v in r.items() if needle in v and k.startswith(prefix)), None)


def han_csbh(r):
    """Trả mâu thuẫn hạn CSBH nếu hai đoạn cùng có mặt."""
    a, b = _ref_of(r, "30/11/2026"), _ref_of(r, "31/12/2026")
    if not a or not b:
        return {"conflicts": []}
    return {
        "conflicts": [
            {
                "summary": "Hai chính sách bán hàng khác thời hạn",
                "attribute": "x",
                "left": {"ref": a, "quote": "đến hết 30/11/2026", "value": "đến hết 30/11/2026"},
                "right": {"ref": b, "quote": "đến hết 31/12/2026", "value": "đến hết 31/12/2026"},
            }
        ]
    }


@pytest.fixture
async def store(qdrant_url):
    s = QdrantStore(url=qdrant_url)
    yield s
    await s.aclose()


@pytest.fixture
async def du_an(pool, seed_conflict_tenant, store):
    tenant = seed_conflict_tenant
    async with tenant_conn(pool, tenant) as c:
        pid = await c.fetchval(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status, investor)"
            " VALUES (portal.current_tenant(), 'nplb', 'Noble Palace', 'published', 'Noble') RETURNING id"
        )
        ids = []
        for title in ("CSBH — Tháng 7", "CSBH — Số 617", "Brochure", "Giới thiệu"):
            ids.append(
                await c.fetchval(
                    "INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, status)"
                    " VALUES (portal.current_tenant(), 'nplb', $1, 'x', 'published') RETURNING id",
                    title,
                )
            )
    coll = f"t_{uuid.uuid4().hex[:8]}_documents"
    await store.ensure_collection(coll, media=False)

    def pt(doc_type, rid, text, vec):
        payload = {
            "project_id": "nplb",
            "project_name": "Noble Palace",
            "doc_type": doc_type,
            "record_id": rid,
            "text": f"Noble Palace — Mục\n\n{text}",
        }
        return PointIn(point_id_of(doc_type, rid, 0), {"dense": vec}, payload)

    await store.upsert(
        coll,
        [
            pt("csbh", ids[0], CSBH_A, _vec(1.0, 0.1)),
            pt("csbh", ids[1], CSBH_B, _vec(1.0, 0.15)),
            pt("khac", ids[2], BROCHURE, _vec(0.0, 1.0, 0.1)),
            pt("khac", ids[3], QUANG_CAO, _vec(1.0, 0.12)),
            pt("tong_quan", pid, "Chủ đầu tư: Noble", _vec(0.0, 1.0, 0.12)),
        ],
    )
    yield tenant, coll, pid, ids
    await store.drop_collection(coll)


async def _run(pool, tenant, store, llm, coll, rid, entity="documents"):
    async with tenant_conn(pool, tenant) as c:
        return await check_record(
            c, store=store, llm=llm, collection=coll, project_code="nplb", entity=entity, record_id=rid
        )


async def _open(pool, tenant):
    async with tenant_conn(pool, tenant) as c:
        return await repo.list_open(c, "nplb")


async def test_hai_csbh_lech_han_thanh_mot_canh_bao(pool, store, du_an):
    tenant, coll, _, ids = du_an
    llm = FakeLlm(han_csbh)
    res = await _run(pool, tenant, store, llm, coll, ids[0])
    rows = await _open(pool, tenant)
    assert res.opened == 1 and len(rows) == 1
    r = rows[0]
    assert r["summary"] == "Hai chính sách bán hàng khác thời hạn"
    assert {r["left_label"], r["right_label"]} == {"CSBH — Tháng 7", "CSBH — Số 617"}
    assert {r["left_quote"], r["right_quote"]} == {"đến hết 30/11/2026", "đến hết 31/12/2026"}


async def test_chay_lai_khong_goi_llm(pool, store, du_an):
    tenant, coll, _, ids = du_an
    llm = FakeLlm(han_csbh)
    await _run(pool, tenant, store, llm, coll, ids[0])
    n = len(llm.calls)
    res = await _run(pool, tenant, store, llm, coll, ids[0])
    assert len(llm.calls) == n and res.calls == 0
    res = await _run(pool, tenant, store, llm, coll, ids[1])
    assert res.calls == 0


async def test_doan_quang_cao_khong_gui_llm(pool, store, du_an):
    tenant, coll, _, ids = du_an
    llm = FakeLlm(han_csbh)
    await _run(pool, tenant, store, llm, coll, ids[3])
    assert llm.calls == []


async def test_trich_dan_bia_bi_loai_nhung_cap_van_ghi_da_phan(pool, store, du_an):
    tenant, coll, _, ids = du_an

    def bia(r):
        out = han_csbh(r)
        for f in out["conflicts"]:
            f["right"]["quote"] = "đến hết 15/01/2027"
        return out

    llm = FakeLlm(bia)
    await _run(pool, tenant, store, llm, coll, ids[0])
    assert await _open(pool, tenant) == []
    await _run(pool, tenant, store, llm, coll, ids[0])
    assert len(llm.calls) == 1


def chu_dau_tu(r):
    d = _ref_of(r, "Bách Giang", "D")
    f = _ref_of(r, "Noble", "field:")
    if not d or not f:
        return {"conflicts": []}
    return {
        "conflicts": [
            {
                "summary": "Chủ đầu tư khác nhau",
                "attribute": "x",
                "left": {"ref": d, "quote": "Công ty CP Bách Giang", "value": "Công ty CP Bách Giang"},
                "right": {"ref": f, "quote": "Noble", "value": "Noble"},
            }
        ]
    }


async def test_doan_lech_truong_mang_ten_truong(pool, store, du_an):
    tenant, coll, pid, ids = du_an
    await _run(pool, tenant, store, FakeLlm(chu_dau_tu), coll, ids[2])
    rows = await _open(pool, tenant)
    assert len(rows) == 1
    r = rows[0]
    side = "right" if r["right_field"] else "left"
    assert (r[f"{side}_entity"], r[f"{side}_record_id"], r[f"{side}_field"]) == ("projects", pid, "investor")
    assert r[f"{side}_label"] == "Chủ đầu tư"


async def test_doan_lech_hai_truong_ra_hai_canh_bao(pool, store, du_an):
    tenant, coll, _, ids = du_an
    async with tenant_conn(pool, tenant) as c:
        await c.execute("UPDATE tenant_data.projects SET product_scale = '200 sản phẩm' WHERE project_code = 'nplb'")

    def hai(r):
        d = _ref_of(r, "Bách Giang", "D")
        fi, fs = _ref_of(r, "Noble", "field:"), _ref_of(r, "200 sản phẩm", "field:")
        return {
            "conflicts": [
                {
                    "summary": "Chủ đầu tư khác nhau",
                    "attribute": "x",
                    "left": {"ref": d, "quote": "Công ty CP Bách Giang", "value": "Công ty CP Bách Giang"},
                    "right": {"ref": fi, "quote": "Noble", "value": "Noble"},
                },
                {
                    "summary": "Số sản phẩm khác nhau",
                    "attribute": "x",
                    "left": {"ref": d, "quote": "tổng 172 sản phẩm", "value": "tổng 172 sản phẩm"},
                    "right": {"ref": fs, "quote": "200 sản phẩm", "value": "200 sản phẩm"},
                },
            ]
        }

    await _run(pool, tenant, store, FakeLlm(hai), coll, ids[2])
    assert {r["summary"] for r in await _open(pool, tenant)} == {"Chủ đầu tư khác nhau", "Số sản phẩm khác nhau"}


async def test_trich_dan_truong_kem_nhan_van_khop(pool, store, du_an):
    tenant, coll, _, ids = du_an

    def kem_nhan(r):
        d, f = _ref_of(r, "Bách Giang", "D"), _ref_of(r, "Noble", "field:")
        return {
            "conflicts": [
                {
                    "summary": "Chủ đầu tư khác nhau",
                    "attribute": "chủ đầu tư",
                    "left": {"ref": d, "quote": "Công ty CP Bách Giang", "value": "Bách Giang"},
                    "right": {"ref": f, "quote": "Chủ đầu tư: Noble", "value": "Noble"},
                }
            ]
        }

    await _run(pool, tenant, store, FakeLlm(kem_nhan), coll, ids[2])
    rows = await _open(pool, tenant)
    assert [r["right_quote"] if r["right_field"] else r["left_quote"] for r in rows] == ["Noble"]


async def test_bo_muc_hai_gia_tri_khac_loai_dai_luong(pool, store, du_an):
    tenant, coll, _, ids = du_an

    def lech_loai(r):
        d, f = _ref_of(r, "Bách Giang", "D"), _ref_of(r, "Noble", "field:")
        return {
            "conflicts": [
                {
                    "summary": "Quy mô khác nhau",
                    "attribute": "quy mô",
                    "left": {"ref": d, "quote": "trên 4,3 ha", "value": "4,3 ha"},
                    "right": {"ref": f, "quote": "Noble", "value": "Noble"},
                }
            ]
        }

    await _run(pool, tenant, store, FakeLlm(lech_loai), coll, ids[2])
    assert await _open(pool, tenant) == []


async def test_sua_truong_thi_canh_bao_cu_dong(pool, store, du_an):
    tenant, coll, pid, ids = du_an
    await _run(pool, tenant, store, FakeLlm(chu_dau_tu), coll, ids[2])
    async with tenant_conn(pool, tenant) as c:
        await c.execute("UPDATE tenant_data.projects SET investor = 'Bách Giang' WHERE project_code = 'nplb'")
    res = await _run(pool, tenant, store, FakeLlm(lambda r: {"conflicts": []}), coll, pid, entity="projects")
    assert res.resolved == 1
    assert await _open(pool, tenant) == []


async def test_dismissed_giu_nguyen_sau_quet_ca_du_an(pool, store, du_an):
    tenant, coll, _, ids = du_an
    await _run(pool, tenant, store, FakeLlm(han_csbh), coll, ids[0])
    cid = (await _open(pool, tenant))[0]["id"]
    async with tenant_conn(pool, tenant) as c:
        await repo.dismiss(c, cid, "u_1")
    async with tenant_conn(pool, tenant) as c:
        await check_project(c, store=store, llm=FakeLlm(han_csbh), collection=coll, project_code="nplb")
        status = await c.fetchval("SELECT status FROM tenant_data.data_conflicts WHERE id = $1", cid)
    assert status == "dismissed"
    assert await _open(pool, tenant) == []


async def test_json_hong_hai_lan_thi_nem_va_khong_ghi(pool, store, du_an):
    tenant, coll, _, ids = du_an

    class Hong:
        calls = 0

        async def ask(self, profile, user_text):
            Hong.calls += 1
            raise ValueError("không thấy JSON")

    with pytest.raises(ValueError):
        await _run(pool, tenant, store, Hong(), coll, ids[0])
    assert Hong.calls == 2
    async with tenant_conn(pool, tenant) as c:
        assert await c.fetchval("SELECT count(*) FROM tenant_data.data_conflicts") == 0
