"""`kb/web/service.py` — nghiệp vụ màn «Dữ liệu ngoài» trên DB thật (role `portal_api`), Qdrant thật, Redis giả."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from qdrant_client import AsyncQdrantClient

from portal.api.loi import LoiPortal
from portal.core.db.session import tenant_conn
from portal.modules.kb.web import config, probe_job, repo, service
from portal.modules.kb.web.compose import dossier_ids, near_id
from portal.modules.kb.web.config import SourceSite
from portal.modules.kb.web.contracts import KIND_PROBE, KIND_PROJECT, KIND_RUN, Item, Source
from portal.modules.kb.web.index import WebIndex
from portal.modules.kb.web.probe import ProbeResult
from portal.modules.kb.web.schemas import (
    GioiHanIn,
    LichIn,
    LichTongIn,
    SuaChuDeIn,
    SuaNguonIn,
    ThemChuDeIn,
    ThemNguonIn,
    ThuNguonOut,
)

from .conftest import NPTTL, OTHER, TENANT

pytestmark = pytest.mark.integration
U = "u_seed_test"


class FakeRedis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None):
        self.kv[k] = v


@pytest.fixture(autouse=True)
async def _env(monkeypatch, qdrant_url, pool):
    monkeypatch.setenv("QDRANT_URL", qdrant_url)
    monkeypatch.setenv("QDRANT_API_KEY", "")
    await pool.execute("DELETE FROM control.jobs WHERE kind = ANY($1::text[])", [KIND_RUN, KIND_PROJECT, KIND_PROBE])
    yield
    await pool.execute("DELETE FROM control.jobs WHERE kind = ANY($1::text[])", [KIND_RUN, KIND_PROJECT, KIND_PROBE])


async def _audit(pool, prefix):
    rows = await pool.fetch(
        "SELECT hanh_dong FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong LIKE $2 ORDER BY id", TENANT, prefix
    )
    return [r["hanh_dong"] for r in rows]


# ─── tổng quan ───────────────────────────────────────────────────────────────


async def test_overview_tenant_moi(web_pool, api_pool):
    o = await service.overview(api_pool, FakeRedis(), TENANT)
    assert (o.soDuAn, o.soDuAnCoHoSo, o.hoSoCuNhat, o.baiBayNgay) == (1, 0, None, 0)
    assert o.soNguonBat == 16 and o.groundingTran == 1000 and o.trinhDuyetTran == 300
    assert o.dangChay == [] and o.loiGanDay == [] and o.lanKeTiep is None


async def test_overview_dem_bai_va_bo_dem_redis(web_pool, api_pool):
    async with tenant_conn(web_pool, TENANT) as c:
        await repo.save_page(
            c,
            url="https://test.kbweb/ov1",
            source_url="",
            domain="test.kbweb",
            title="t",
            published_at=None,
            content_text="x",
            content_hash="h",
            found_via="sitemap",
            status="ok",
            projects=[],
            location=[],
        )
    r = FakeRedis()
    now = datetime.now(UTC).astimezone(service.VN)
    r.kv[f"kbweb:grounding:{TENANT}:{now:%Y-%m}"] = "42"
    r.kv[f"kbweb:browser:{TENANT}:{now:%Y-%m-%d}"] = "7"
    o = await service.overview(api_pool, r, TENANT)
    assert (o.baiBayNgay, o.baiBaMuoiNgay, o.groundingThang, o.trinhDuyetHomNay) == (1, 1, 42, 7)
    assert not await service.worker_alive(r)
    r.kv["kbweb:worker:alive"] = "x"
    assert await service.worker_alive(r)


# ─── nguồn ───────────────────────────────────────────────────────────────────


async def test_nguon_mac_dinh_tat_duoc_va_xoa_duoc(web_pool, api_pool, pool):
    ds = await service.list_sources(api_pool, TENANT)
    assert len(ds) == 16 and all(s.macDinh for s in ds)
    cafef = next(s for s in ds if s.domain == "cafef.vn")
    o = await service.update_source(api_pool, TENANT, U, cafef.id, SuaNguonIn(bat=False))
    assert o.bat is False
    await service.delete_source(api_pool, TENANT, U, cafef.id)
    assert "cafef.vn" not in {s.domain for s in await service.list_sources(api_pool, TENANT)}
    assert await _audit(pool, "kb_web.nguon%") == ["kb_web.nguon_sua", "kb_web.nguon_xoa"]


async def test_them_nguon_roi_xoa_va_khong_trung(web_pool, api_pool, pool):
    body = ThemNguonIn(domain="https://bao.vn/", ten="Báo Vui", rss=["https://bao.vn/rss"], tinhTrang="ok")
    o = await service.add_source(api_pool, TENANT, U, body)
    assert (o.domain, o.ten, o.macDinh, o.tinhTrang, o.bat) == ("bao.vn", "Báo Vui", False, "ok", True)
    with pytest.raises(LoiPortal) as e:
        await service.add_source(api_pool, TENANT, U, body)
    assert e.value.ma == "KB_WEB_NGUON_DA_CO"
    assert all(s.domain != "bao.vn" for s in await service.list_sources(api_pool, OTHER)), "nguồn là của riêng tenant"
    await service.delete_source(api_pool, TENANT, U, o.id)
    assert all(s.id != o.id for s in await service.list_sources(api_pool, TENANT))
    assert await _audit(pool, "kb_web.nguon%") == ["kb_web.nguon_them", "kb_web.nguon_xoa"]


async def test_thu_nguon_xep_job_va_doc_ket_qua_tu_redis(web_pool, api_pool, pool):
    token, job_id = await service.start_probe(api_pool, TENANT, U, " bao.vn ")
    row = await pool.fetchrow("SELECT kind, state, payload FROM control.jobs WHERE id = $1", job_id)
    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
    assert (row["kind"], row["state"], payload) == (KIND_PROBE, "queued", {"url": "bao.vn", "token": token})
    r = FakeRedis()
    assert await service.probe_result(api_pool, r, TENANT, token) == ("dang_chay", None)
    site = SourceSite("bao.vn", "Báo Vui", True, "browser", "news", ("https://bao.vn/rss",), "", "", (), (), "", ())
    r.kv[probe_job.result_key(TENANT, token)] = probe_job.to_json(
        ProbeResult("https://bao.vn/", "ok", site=site, articles=3, pages_tested=2, pages_ok=2, note="n")
    )
    state, out = await service.probe_result(api_pool, r, TENANT, token)
    assert state == "xong" and out.trangThai == "ok" and out.soBai == 3 and out.daCo is False
    assert out.deXuat.cheDo == "browser" and out.deXuat.rss == ["https://bao.vn/rss"]
    with pytest.raises(LoiPortal):
        await service.probe_result(api_pool, r, TENANT, "khong-co")


async def test_thu_lai_nguon_va_ghi_ket_qua(web_pool, api_pool):
    ds = await service.list_sources(api_pool, TENANT)
    cafef = next(s for s in ds if s.domain == "cafef.vn")
    token, _ = await service.retry_source(api_pool, TENANT, U, cafef.id)
    assert token
    out = ThuNguonOut(trangThai="blocked", ghiChu="chặn", soBai=0, soTrangThu=2, soTrangDoc=0)
    o = await service.apply_probe_to_source(api_pool, TENANT, cafef.id, out)
    assert (o.tinhTrang, o.ghiChu) == ("blocked", "chặn") and o.thuLuc is not None


# ─── chủ đề ──────────────────────────────────────────────────────────────────


async def test_them_sua_xoa_chu_de(web_pool, api_pool, pool):
    body = ThemChuDeIn(ten="Phong thuỷ", moTa="hướng nhà", cauTim=["{project} phong thuỷ hướng"], tuKhoa=["Phong Thuỷ"])
    o = await service.add_topic(api_pool, TENANT, U, body)
    assert (o.code, o.ten, o.nhan, o.macDinh, o.tuKhoa, o.thuTu) == (
        "phong_thuy",
        "Phong thuỷ",
        "Phong thuỷ",
        False,
        ["phong thuỷ"],
        20,
    )
    o2 = await service.add_topic(api_pool, TENANT, U, body)
    assert o2.code == "phong_thuy_2"
    o = await service.update_topic(api_pool, TENANT, U, o.id, SuaChuDeIn(ten="Phong thủy nhà", bat=False))
    assert (o.ten, o.nhan, o.bat) == ("Phong thủy nhà", "Phong thủy nhà", False)
    await service.delete_topic(api_pool, TENANT, U, o.id)
    assert all(t.id != o.id for t in await service.list_topics(api_pool, TENANT))
    assert await _audit(pool, "kb_web.chu_de%") == [
        "kb_web.chu_de_them",
        "kb_web.chu_de_them",
        "kb_web.chu_de_sua",
        "kb_web.chu_de_xoa",
    ]


async def test_chu_de_mac_dinh_doi_ten_khong_doi_nhan_va_xoa_duoc(web_pool, api_pool):
    transit = next(t for t in await service.list_topics(api_pool, TENANT) if t.code == "transit")
    o = await service.update_topic(api_pool, TENANT, U, transit.id, SuaChuDeIn(ten="Xe buýt"))
    assert (o.ten, o.nhan) == ("Xe buýt", transit.nhan), "nhãn mục hồ sơ mặc định giữ nguyên"
    await service.delete_topic(api_pool, TENANT, U, transit.id)
    assert "transit" not in {t.code for t in await service.list_topics(api_pool, TENANT)}


async def test_chu_de_an_khong_hien_nhung_van_chay(web_pool, api_pool, pool):
    hien = {t.code for t in await service.list_topics(api_pool, TENANT)}
    assert hien.isdisjoint({"road", "bridge", "area_development", "investor"})
    road_id = await pool.fetchval(
        "SELECT id FROM tenant_data.kbweb_topics WHERE tenant_id = $1 AND code = 'road'", TENANT
    )
    with pytest.raises(LoiPortal) as e:
        await service.update_topic(api_pool, TENANT, U, road_id, SuaChuDeIn(bat=False))
    assert e.value.http == 404
    with pytest.raises(LoiPortal):
        await service.delete_topic(api_pool, TENANT, U, road_id)
    async with tenant_conn(api_pool, TENANT) as c:
        cfg = await config.load_for_tenant(c)
    assert "road" in {t.code for t in cfg.topics}


async def test_chu_de_cau_tim_phai_co_bien_va_tran_20(web_pool, api_pool):
    with pytest.raises(LoiPortal) as e:
        await service.add_topic(api_pool, TENANT, U, ThemChuDeIn(ten="X", cauTim=["không có biến"]))
    assert e.value.ma == "KB_WEB_CHU_DE_CAU_TIM_THIEU_BIEN"
    with pytest.raises(LoiPortal) as e:
        await service.add_topic(api_pool, TENANT, U, ThemChuDeIn(ten="X", cauTim=["{project} {la}"]))
    assert e.value.ma == "KB_WEB_CHU_DE_CAU_TIM_SAI"
    for i in range(4):
        await service.add_topic(api_pool, TENANT, U, ThemChuDeIn(ten=f"T{i}", cauTim=["{project} x"]))
    with pytest.raises(LoiPortal) as e:
        await service.add_topic(api_pool, TENANT, U, ThemChuDeIn(ten="T9", cauTim=["{project} x"]))
    assert e.value.ma == "KB_WEB_CHU_DE_QUA_GIOI_HAN"


def test_sinh_code_chu_de():
    assert service.topic_code("Tiện ích – Y tế", set()) == "tien_ich_y_te"
    assert service.topic_code("123", set()) == "t_123"
    assert service.topic_code("A", {"a", "a_2"}) == "a_3"


async def test_soan_chu_de_thieu_khoa_llm(monkeypatch):
    monkeypatch.setenv("KB_VLM_API_KEY", "")
    with pytest.raises(LoiPortal) as e:
        await service.draft_topic(None, "t", "X", "y")
    assert e.value.http == 503


# ─── lịch ────────────────────────────────────────────────────────────────────


async def test_sua_lich_tinh_lan_ke_tiep_va_gioi_han(web_pool, api_pool, pool):
    body = LichTongIn(
        lich=[
            LichIn(mode="nightly", bat=True, gio="02:30"),
            LichIn(mode="weekly", bat=True, gio="05:00", ngayTrongTuan=[6, 2], latCat=2),
            LichIn(mode="rebuild", bat=False, gio="06:00", soThang=2, ngayTrongChuKy="d15"),
        ],
        gioiHan=GioiHanIn(groundingThang=500, trinhDuyetNgay=50, ngayHoi=14),
    )
    o = await service.put_schedules(api_pool, TENANT, U, body)
    by = {li.mode: li for li in o.lich}
    assert by["nightly"].gio == "02:30" and by["nightly"].lanKeTiep is not None
    assert by["weekly"].ngayTrongTuan == [2, 6] and by["weekly"].latCat == 2
    assert by["rebuild"].bat is False and by["rebuild"].soThang == 2
    assert by["rebuild"].lanKeTiep.astimezone(service.VN).day == 15
    assert (o.gioiHan.groundingThang, o.gioiHan.trinhDuyetNgay, o.gioiHan.ngayHoi) == (500, 50, 14)
    assert await _audit(pool, "kb_web.%sua") == ["kb_web.lich_sua", "kb_web.gioi_han_sua"]
    other = await service.get_schedules(api_pool, OTHER)
    assert next(li for li in other.lich if li.mode == "nightly").gio == "01:10"


async def test_lich_tuan_bat_ma_khong_ngay_thi_422(web_pool, api_pool):
    with pytest.raises(LoiPortal) as e:
        await service.put_schedules(
            api_pool, TENANT, U, LichTongIn(lich=[LichIn(mode="weekly", bat=True, gio="04:00", ngayTrongTuan=[])])
        )
    assert e.value.ma == "KB_WEB_LICH_THIEU_NGAY"


async def test_chay_ngay_xep_job_va_khong_xep_trung(web_pool, api_pool, pool):
    j = await service.run_now(api_pool, TENANT, U, "weekly")
    assert (j.loai, j.mode, j.trangThai, j.nguoi) == (KIND_RUN, "weekly", "queued", U)
    row = await pool.fetchrow("SELECT payload FROM control.jobs WHERE id = $1", j.id)
    assert (json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"])["slices"] == 3
    with pytest.raises(LoiPortal) as e:
        await service.run_now(api_pool, TENANT, U, "weekly")
    assert e.value.ma == "KB_WEB_DANG_CHAY"
    with pytest.raises(LoiPortal):
        await service.run_now(api_pool, TENANT, U, "init")
    assert [x.id for x in await service.list_jobs(api_pool, TENANT, 10)] == [j.id]
    assert (await service.get_job(api_pool, TENANT, j.id)).id == j.id
    with pytest.raises(LoiPortal):
        await service.get_job(api_pool, OTHER, j.id)


async def test_nhat_ky_mang_ten_nguoi_ten_du_an_va_tinh_trang_kiem_tra(web_pool, api_pool, pool):
    ten_nguoi = await pool.fetchval("SELECT name FROM control.users WHERE id = $1", U)
    du_an = await service.refresh_project(api_pool, TENANT, U, "NPTTL", "init")
    _, probe_id = await service.start_probe(api_pool, TENANT, U, "bao.vn")
    await pool.execute(
        "UPDATE control.jobs SET state = 'success', message = 'https://bao.vn/: timeout' WHERE id = $1", probe_id
    )
    by = {j.id: j for j in await service.list_jobs(api_pool, TENANT, 10)}
    assert (by[du_an.id].duAnTen, by[du_an.id].nguoiTen) == (NPTTL, ten_nguoi)
    assert (by[probe_id].tinhTrangNguon, by[probe_id].duAnTen) == ("timeout", None)


async def test_nhat_ky_chi_lay_trong_so_ngay(web_pool, api_pool, pool):
    j = await service.run_now(api_pool, TENANT, U, "weekly")
    await pool.execute("UPDATE control.jobs SET created_at = now() - interval '8 days' WHERE id = $1", j.id)
    assert j.id not in [x.id for x in await service.list_jobs(api_pool, TENANT, 10, days=7)]
    assert j.id in [x.id for x in await service.list_jobs(api_pool, TENANT, 10)]


async def test_nhat_ky_mang_chi_phi_khi_co_quyen_xem(web_pool, api_pool, pool):
    from decimal import Decimal

    j = await service.run_now(api_pool, TENANT, U, "weekly")
    await pool.execute("DELETE FROM billing.usage_events WHERE session_id = $1", f"kbweb:{j.id}")
    await pool.execute(
        """INSERT INTO billing.usage_events (tenant_id, session_id, channel, seq, component, purpose,
                                             provider, model, units)
           VALUES ($1, $2, 'kb_web', 0, 'search', 'kb_web', 'google', 'gemini-2.5-flash', 3)""",
        TENANT,
        f"kbweb:{j.id}",
    )
    try:
        co = {x.id: x for x in await service.list_jobs(api_pool, TENANT, 10, show_cost=True)}
        assert co[j.id].chiPhi == Decimal(3 * 364)
        khong = {x.id: x for x in await service.list_jobs(api_pool, TENANT, 10)}
        assert khong[j.id].chiPhi is None
        assert (await service.get_job(api_pool, TENANT, j.id, show_cost=True)).chiPhi == Decimal(3 * 364)
    finally:
        await pool.execute("DELETE FROM billing.usage_events WHERE session_id = $1", f"kbweb:{j.id}")


# ─── dự án ───────────────────────────────────────────────────────────────────


class FakeEmbed:
    async def dense(self, texts):
        return [[0.01] * 1024 for _ in texts]

    async def sparse(self, texts):
        return [{"indices": [1], "values": [1.0]} for _ in texts]


@pytest.fixture
async def ho_so(qdrant_url):
    client = AsyncQdrantClient(url=qdrant_url, check_compatibility=False, timeout=60)
    idx = WebIndex(client=client, embed=FakeEmbed(), collection=f"{TENANT}_public_web")
    await idx.ensure()
    src = (Source("https://test.kbweb/ho-so-1", "CafeF", datetime(2026, 9, 1, tzinfo=UTC)),)
    items = [
        Item("Tổng quan: Dự án lớn [1].", src, (NPTTL,), ("đan phượng",)),
        Item("Tiện ích – Y tế: Bệnh viện gần [1].", src, (NPTTL,), ("đan phượng",)),
        Item("Chủ đầu tư: Tập đoàn lớn [1].", src, (NPTTL,), ("đan phượng",)),
        Item("Hạ tầng giao thông – Đường bộ: Vành đai 4 [1].", src, (NPTTL,), ("đan phượng",)),
    ]
    stamp = datetime.now(UTC) - timedelta(days=3)
    await idx.replace(dossier_ids(NPTTL), items, stamp)
    near = Item(f"Các dự án gần {NPTTL}:\n- Dự án B (gần {NPTTL}): Cách 2 km [1].", src, (NPTTL,), ("đan phượng",))
    await idx.replace([near_id(NPTTL)], [near], stamp)
    yield idx
    await client.delete_collection(idx.collection)
    await client.close()


async def test_du_an_chua_co_ho_so(web_pool, api_pool):
    (d,) = await service.list_projects(api_pool, TENANT)
    assert (d.code, d.soMuc, d.capNhatLuc, d.dangChay, d.viecGanNhat) == ("NPTTL", 0, None, False, None)
    ct = await service.project_detail(api_pool, TENANT, "NPTTL")
    assert d.soChuDe == len(ct.muc) == len(await service.list_topics(api_pool, TENANT))
    assert all(m.noiDung == "" and not m.nguon for m in ct.muc) and ct.bai == [] and ct.mucAn == []
    with pytest.raises(LoiPortal) as e:
        await service.project_detail(api_pool, TENANT, "KHONGCO")
    assert e.value.http == 404


async def test_du_an_co_ho_so_an_muc_loai_bai(web_pool, api_pool, pool, ho_so):
    async with tenant_conn(web_pool, TENANT) as c:
        await repo.save_page(
            c,
            url="https://test.kbweb/ho-so-1",
            source_url="",
            domain="test.kbweb",
            title="Bài 1",
            published_at=None,
            content_text="Noble Palace",
            content_hash="h1",
            found_via="sitemap",
            status="ok",
            projects=[NPTTL],
            location=[],
        )
    (d,) = await service.list_projects(api_pool, TENANT)
    assert d.soMuc == 2 and d.capNhatLuc is not None
    o = await service.overview(api_pool, FakeRedis(), TENANT)
    assert o.soDuAnCoHoSo == 1 and o.hoSoCuNhat == d.capNhatLuc
    await service.set_item_hidden(api_pool, TENANT, U, "NPTTL", "Tiện ích – Y tế", True)
    await service.set_page_excluded(api_pool, TENANT, U, "NPTTL", "https://test.kbweb/ho-so-1", True)
    ct = await service.project_detail(api_pool, TENANT, "NPTTL")
    assert [m.ten for m in ct.muc if m.noiDung] == ["Y tế", "Dự án lân cận"]
    assert [m.nhan for m in ct.muc if m.an] == ["Tiện ích – Y tế"] and ct.mucAn == ["Tiện ích – Y tế"]
    assert next(m for m in ct.muc if m.noiDung).nguon[0].ten == "CafeF"
    assert [(b.url, b.loai) for b in ct.bai] == [("https://test.kbweb/ho-so-1", True)]
    await service.set_item_hidden(api_pool, TENANT, U, "NPTTL", "Tiện ích – Y tế", False)
    await service.set_page_excluded(api_pool, TENANT, U, "NPTTL", "https://test.kbweb/ho-so-1", False)
    ct = await service.project_detail(api_pool, TENANT, "NPTTL")
    assert ct.mucAn == [] and ct.bai[0].loai is False
    assert await _audit(pool, "kb_web.ho_so_sua") == ["kb_web.ho_so_sua"] * 4


async def test_muc_ho_so_theo_dung_tab_chu_de(web_pool, api_pool, ho_so):
    topics = await service.list_topics(api_pool, TENANT)
    ct = await service.project_detail(api_pool, TENANT, "NPTTL")
    assert [m.ten for m in ct.muc] == [t.ten for t in topics if t.bat]
    y_te = next(t for t in topics if t.code == "healthcare")
    await service.update_topic(api_pool, TENANT, U, y_te.id, SuaChuDeIn(bat=False))
    ct = await service.project_detail(api_pool, TENANT, "NPTTL")
    assert "Y tế" not in [m.ten for m in ct.muc]
    assert [m.ten for m in ct.muc if m.noiDung] == ["Dự án lân cận"]
    (d,) = await service.list_projects(api_pool, TENANT)
    assert (d.soMuc, d.soChuDe) == (1, len(ct.muc))


async def test_lam_moi_ho_so_xep_job_va_dang_chay(web_pool, api_pool):
    j = await service.refresh_project(api_pool, TENANT, U, "NPTTL", "rebuild")
    assert (j.loai, j.mode, j.duAn) == (KIND_PROJECT, "rebuild", "NPTTL")
    (d,) = await service.list_projects(api_pool, TENANT)
    assert d.dangChay is True and d.viecGanNhat.id == j.id
    assert (await service.project_detail(api_pool, TENANT, "NPTTL")).dangChay is True
    with pytest.raises(LoiPortal) as e:
        await service.refresh_project(api_pool, TENANT, U, "NPTTL", "rebuild")
    assert e.value.ma == "KB_WEB_DANG_CHAY"
    with pytest.raises(LoiPortal):
        await service.refresh_project(api_pool, TENANT, U, "NPTTL", "nightly")
