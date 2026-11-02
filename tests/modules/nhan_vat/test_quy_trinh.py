"""Vòng đời nhân vật — router + máy trạng thái job, lipsync/nhà cung cấp giả, DB + MinIO thật.

Gọi thẳng handler (khuôn `linh_vuc`): `require()` không chạy khi gọi thẳng — phép kiểm
«route nào khai action nào» thuộc tests/api/test_moi_route_khai_action.py.
Job chạy bằng cách gọi `jobs.handle_buoc` trong `tenant_conn` như worker làm (lượt kế
tiếp được xếp với `run_after` tương lai nên `run_once` sẽ không nhặt ngay).
"""

import io

import pytest
from starlette.datastructures import UploadFile

from portal.api.loi import LoiPortal
from portal.core.auth.principal import Principal
from portal.core.db.session import tenant_conn
from portal.modules.nhan_vat import jobs, repo, router, so
from portal.modules.nhan_vat.contracts import ChonIn

from .conftest import OTHER_TENANT, TENANT

_P = Principal(user_id="u_seed_test", tenant_id=TENANT, role="Quản trị", actions=frozenset())
_P_KHAC = Principal(user_id="u_seed_test", tenant_id=OTHER_TENANT, role="Quản trị", actions=frozenset())


def _tep(ten: str, noi_dung: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(noi_dung), filename=ten)


async def _tao(api_pool, *, nguon="video", p=_P, ten="Lan", tep=None, tay=None):
    return await router.tao(
        ten=ten,
        nguon=nguon,
        dongY=True,
        tep=tep or _tep("chinh.mp4", b"VIDEO-CHINH"),
        tepTay=tay,
        moTa=None,
        p=p,
        pool=api_pool,
    )


async def _chay_job(api_pool, nv_id, tenant=TENANT, toi_da=20):
    """Chạy các lượt job tới khi nhân vật dừng (san_sang/loi). Trả số lượt."""
    for i in range(toi_da):
        async with tenant_conn(api_pool, tenant) as conn:
            nv = await repo.doc(conn, nv_id)
            if nv["trang_thai"] in ("san_sang", "loi"):
                return i
            await jobs.handle_buoc(conn, {"id": nv_id})
    raise AssertionError("job không dừng")


async def test_video_upload_di_het_vong_doi(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia):
    nv = await _tao(api_pool, tay=_tep("tay.mov", b"VIDEO-TAY"))
    assert nv.trangThai == "dung" and nv.avatarId is None  # chưa sẵn sàng thì không lộ avatarId
    await _chay_job(api_pool, nv.id)

    o = await router.doc(nv_id=nv.id, p=_P, pool=api_pool)
    assert o.trangThai == "san_sang" and o.tienDo == 1.0
    assert o.avatarId and o.avatarId.startswith("nv-")
    assert o.posterUrl == f"/api/v1/nhan-vat/{nv.id}/poster"
    assert [x.cau for x in o.xemTruoc] == list(so.CAU_DEMO)
    # Gửi đúng hai video sang lipsync, đúng loại, đúng bytes khách upload.
    gui = [(g[2], g[3]) for g in lipsync_gia.goi if g[0] == "gui_video"]
    assert gui == [("chinh", b"VIDEO-CHINH"), ("tay", b"VIDEO-TAY")]
    # Video khách tự quay: không sinh gì bằng AI ⇒ không lấy khung chờ, chỉ dựng một lần.
    assert not any(g[0] == "khung_cho" for g in lipsync_gia.goi)
    assert [g[0] for g in lipsync_gia.goi].count("dung") == 1
    assert lipsync_gia.cat_dau == [0.0]  # video tự quay: không sàn cắt đầu
    # Tệp phát lại được qua route (đọc từ kho tệp thật).
    r = await router.video_xem_truoc(nv_id=nv.id, i=0, p=_P, pool=api_pool)
    assert r.body == b"MP4-" + so.CAU_DEMO[0].encode()
    r = await router.poster(nv_id=nv.id, p=_P, pool=api_pool)
    assert r.body.startswith(b"\x89PNG")


def _ghi_gui(monkeypatch):
    """Ghi lại mọi lời gửi nhà cung cấp `gia`: (ảnh, prompt, thời lượng, giữ khung cuối)."""
    from portal.modules.nhan_vat import nha_cung_cap as ncc_mod

    goi = []
    goc = ncc_mod.Gia.gui

    async def gui(self, anh, mime, prompt, thoi_luong=None, giu_cuoi=True):
        goi.append((anh, prompt, thoi_luong, giu_cuoi))
        return await goc(self, anh, mime, prompt, thoi_luong, giu_cuoi)

    monkeypatch.setattr(ncc_mod.Gia, "gui", gui)
    return goi


async def test_anh_clip_tay_sinh_tu_khung_cho_roi_dung_lai(
    api_pool, seed_nv, kho_tep, env_nv, lipsync_gia, monkeypatch
):
    """Clip nói chỉnh dáng (không khung cuối) ⇒ dựng ⇒ lấy KHUNG CHỜ ⇒ sinh clip tay với khung
    đó làm khung đầu + cuối ⇒ dựng lại có tay. G0 = khung chờ = F0 sau cắt ⇒ mối nối liền."""
    goi = _ghi_gui(monkeypatch)
    env_nv.thoi_luong_s = 8
    nv = await _tao(api_pool, nguon="anh", tep=_tep("mat.jpg", b"JPEG"))
    assert nv.trangThai == "tao_video"
    await _chay_job(api_pool, nv.id)
    o = await router.doc(nv_id=nv.id, p=_P, pool=api_pool)
    assert o.trangThai == "san_sang" and o.videoTayUrl

    assert len(goi) == 2
    anh, prompt, giay, giu_cuoi = goi[0]
    assert anh == b"JPEG" and prompt == env_nv.prompt_noi_chinh_dang and giay == 8 and giu_cuoi is False
    anh, prompt, giay, giu_cuoi = goi[1]
    assert anh == b"KHUNG-CHO-JPG" and prompt == env_nv.prompt_tay and giu_cuoi is True
    assert giay == env_nv.thoi_luong_tay_s

    # Thứ tự với lipsync: dựng clip nói ⇒ khung chờ ⇒ đẩy clip tay ⇒ dựng lại ⇒ xem trước.
    viec = [g[0] if g[0] != "gui_video" else f"gui_{g[2]}" for g in lipsync_gia.goi if g[0] != "trang_thai"]
    assert viec[:5] == ["gui_chinh", "dung", "khung_cho", "gui_tay", "dung"]
    # Cả hai lần dựng đều mang sàn cắt đầu (đoạn AI chỉnh dáng không lên sân khấu).
    assert lipsync_gia.cat_dau == [env_nv.cat_dau_anh_s] * 2 and env_nv.cat_dau_anh_s > 0
    assert viec[5:] and all(v == "xem_truoc" for v in viec[5:])
    tay = [g[3] for g in lipsync_gia.goi if g[0] == "gui_video" and g[2] == "tay"]
    assert tay == [b"MP4-TAY"]


async def test_clip_tay_loi_van_san_sang_khong_dung_lai(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia, monkeypatch):
    """Clip tay là phần PHỤ: nhà cung cấp hỏng ⇒ nhân vật vẫn sẵn sàng (không đưa tay)."""
    from portal.modules.nhan_vat import nha_cung_cap as ncc_mod

    goc = ncc_mod.Gia.kiem

    async def kiem(self, ma):
        if ma == env_nv.gia_video_tay:
            return ncc_mod.KetQua("loi", loi="nội dung bị từ chối")
        return await goc(self, ma)

    monkeypatch.setattr(ncc_mod.Gia, "kiem", kiem)
    nv = await _tao(api_pool, nguon="anh", tep=_tep("mat.jpg", b"JPEG"))
    await _chay_job(api_pool, nv.id)
    o = await router.doc(nv_id=nv.id, p=_P, pool=api_pool)
    assert o.trangThai == "san_sang" and o.videoTayUrl is None
    assert [g[0] for g in lipsync_gia.goi].count("dung") == 1


async def test_lipsync_chua_co_khung_cho_thi_bo_clip_tay(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia, monkeypatch):
    goi = _ghi_gui(monkeypatch)
    lipsync_gia.khung = None
    nv = await _tao(api_pool, nguon="anh", tep=_tep("mat.jpg", b"JPEG"))
    await _chay_job(api_pool, nv.id)
    o = await router.doc(nv_id=nv.id, p=_P, pool=api_pool)
    assert o.trangThai == "san_sang" and o.videoTayUrl is None
    assert len(goi) == 1


async def test_tat_clip_tay_khong_lay_khung_cho(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia, monkeypatch):
    goi = _ghi_gui(monkeypatch)
    env_nv.tao_clip_tay = False
    nv = await _tao(api_pool, nguon="anh", tep=_tep("mat.jpg", b"JPEG"))
    await _chay_job(api_pool, nv.id)
    assert (await router.doc(nv_id=nv.id, p=_P, pool=api_pool)).trangThai == "san_sang"
    assert len(goi) == 1 and not any(g[0] == "khung_cho" for g in lipsync_gia.goi)


async def test_anh_khi_chua_cau_hinh_nha_cung_cap_bi_tu_choi(api_pool, seed_nv, kho_tep, env_nv):
    env_nv.video_provider = ""
    with pytest.raises(LoiPortal) as e:
        await _tao(api_pool, nguon="anh", tep=_tep("mat.jpg", b"JPEG"))
    assert e.value.ma == "NHAN_VAT_CHUA_CAU_HINH_AI" and e.value.http == 409
    ds = await router.liet_ke(p=_P, pool=api_pool)
    assert ds.taoTuAnh is False and ds.nhaCungCap is None


async def test_chua_dong_y_bi_tu_choi(api_pool, seed_nv, kho_tep, env_nv):
    with pytest.raises(LoiPortal) as e:
        await router.tao(
            ten="X", nguon="video", dongY=False, tep=_tep("a.mp4", b"V"), tepTay=None, moTa=None, p=_P, pool=api_pool
        )
    assert e.value.ma == "NHAN_VAT_CHUA_DONG_Y"


async def test_loai_tep_sai_bi_tu_choi(api_pool, seed_nv, kho_tep, env_nv):
    with pytest.raises(LoiPortal) as e:
        await _tao(api_pool, tep=_tep("a.exe", b"MZ"))
    assert e.value.ma == "NHAN_VAT_LOAI_TEP"


async def test_loi_dung_co_ma_va_huong_dan_roi_thu_lai(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia):
    lipsync_gia.chuoi = [{"trang_thai": "loi", "loi": {"ma": "KHONG_THAY_MAT", "chi_tiet": "12 frame"}}]
    nv = await _tao(api_pool)
    await _chay_job(api_pool, nv.id)
    o = await router.doc(nv_id=nv.id, p=_P, pool=api_pool)
    assert o.trangThai == "loi" and o.loi.ma == "KHONG_THAY_MAT"
    assert o.loi.huongDan == so.HUONG_DAN_LOI["KHONG_THAY_MAT"] and o.loi.chiTiet == "12 frame"

    lipsync_gia.chuoi = [{"trang_thai": "san_sang"}]
    o = await router.thu_lai(nv_id=nv.id, p=_P, pool=api_pool)
    assert o.trangThai == "dung" and o.loi is None
    await _chay_job(api_pool, nv.id)
    assert (await router.doc(nv_id=nv.id, p=_P, pool=api_pool)).trangThai == "san_sang"


async def test_xem_truoc_hong_khong_chan_nhan_vat(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia):
    """TTS tắt ⇒ thử lại 2 lượt rồi vẫn `san_sang` (không có video xem trước) — nhân vật dùng được."""
    lipsync_gia.loi_xem_truoc = True
    nv = await _tao(api_pool)
    for _ in range(10):
        async with tenant_conn(api_pool, TENANT) as conn:
            hang = await repo.doc(conn, nv.id)
            if hang["trang_thai"] in ("san_sang", "loi"):
                break
            lan = await conn.fetchval(
                """SELECT coalesce(max((payload->>'lan_loi')::int), 0) FROM control.jobs
                    WHERE tenant_id = $1 AND kind = $2 AND payload->>'id' = $3""",
                TENANT,
                so.KIND_BUOC,
                nv.id,
            )
            await jobs.handle_buoc(conn, {"id": nv.id, "lan_loi": lan})
    o = await router.doc(nv_id=nv.id, p=_P, pool=api_pool)
    assert o.trangThai == "san_sang" and o.xemTruoc == [] and o.buoc == "khong_co_xem_truoc"


async def test_chon_nhan_vat_va_ve_mac_dinh(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia):
    nv = await _tao(api_pool)
    with pytest.raises(LoiPortal) as e:  # chưa dựng xong ⇒ không chọn được
        await router.chon(body=ChonIn(id=nv.id), p=_P, pool=api_pool)
    assert e.value.ma == "NHAN_VAT_CHUA_SAN_SANG"
    await _chay_job(api_pool, nv.id)

    dd = await router.chon(body=ChonIn(id=nv.id), p=_P, pool=api_pool)
    assert dd.id == nv.id and dd.avatarId and dd.posterUrl
    assert (await router.liet_ke(p=_P, pool=api_pool)).dangDung == nv.id
    # Tenant khác không bị ảnh hưởng và không chọn được nhân vật của tenant này.
    assert (await router.dang_dung(p=_P_KHAC, pool=api_pool)).id is None
    with pytest.raises(LoiPortal):
        await router.chon(body=ChonIn(id=nv.id), p=_P_KHAC, pool=api_pool)

    dd = await router.chon(body=ChonIn(id=None), p=_P, pool=api_pool)
    assert dd.id is None and dd.avatarId is None


async def test_chi_mot_nhan_vat_dang_dung(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia):
    a = await _tao(api_pool, ten="A")
    b = await _tao(api_pool, ten="B")
    await _chay_job(api_pool, a.id)
    await _chay_job(api_pool, b.id)
    await router.chon(body=ChonIn(id=a.id), p=_P, pool=api_pool)
    await router.chon(body=ChonIn(id=b.id), p=_P, pool=api_pool)
    ds = await router.liet_ke(p=_P, pool=api_pool)
    assert [x.ten for x in ds.nhanVat if x.dangDung] == ["B"]


async def test_cach_ly_tenant(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia):
    nv = await _tao(api_pool)
    assert (await router.liet_ke(p=_P_KHAC, pool=api_pool)).nhanVat == []
    for goi in (
        router.doc(nv_id=nv.id, p=_P_KHAC, pool=api_pool),
        router.poster(nv_id=nv.id, p=_P_KHAC, pool=api_pool),
        router.xoa(nv_id=nv.id, p=_P_KHAC, pool=api_pool),
    ):
        with pytest.raises(LoiPortal) as e:
            await goi
        assert e.value.http == 404


async def test_xoa_don_kho_tep_va_xep_don_lipsync(api_pool, pool, seed_nv, kho_tep, env_nv, lipsync_gia):
    nv = await _tao(api_pool)
    await _chay_job(api_pool, nv.id)
    avatar_id = (await router.doc(nv_id=nv.id, p=_P, pool=api_pool)).avatarId
    assert await kho_tep.liet_ke(jobs.khoa_tep(TENANT, nv.id, ""))
    await router.xoa(nv_id=nv.id, p=_P, pool=api_pool)
    assert await kho_tep.liet_ke(jobs.khoa_tep(TENANT, nv.id, "")) == []
    async with pool.acquire() as conn:
        don = await conn.fetchval(
            "SELECT payload->>'avatar_id' FROM control.jobs WHERE tenant_id = $1 AND kind = $2",
            TENANT,
            so.KIND_DON,
        )
        hd = await conn.fetch("SELECT hanh_dong FROM control.audit_log WHERE tenant_id = $1 ORDER BY id", TENANT)
    assert don == avatar_id
    assert [r["hanh_dong"] for r in hd] == ["nhan_vat.tao", "nhan_vat.xoa"]
    async with tenant_conn(api_pool, TENANT) as conn:
        r = await jobs.handle_don_lipsync(conn, {"avatar_id": avatar_id})
    assert r.count == 1 and ("xoa", avatar_id) in lipsync_gia.goi


async def test_gioi_han_so_nhan_vat(api_pool, seed_nv, kho_tep, env_nv, monkeypatch):
    monkeypatch.setattr(so, "TOI_DA_MOI_WORKSPACE", 1)
    await _tao(api_pool)
    with pytest.raises(LoiPortal) as e:
        await _tao(api_pool)
    assert e.value.ma == "NHAN_VAT_QUA_SO_LUONG"


async def test_lipsync_mat_ket_noi_thu_lai_roi_bo_cuoc(api_pool, seed_nv, kho_tep, env_nv, monkeypatch):
    from portal.modules.nhan_vat.lipsync import LipsyncClient, LoiLipsync

    async def hong(self, *a, **k):
        raise LoiLipsync("ConnectError")

    monkeypatch.setattr(LipsyncClient, "gui_video", hong)
    nv = await _tao(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        r = await jobs.handle_buoc(conn, {"id": nv.id})
        assert "thử lại" in r.message
        assert (await repo.doc(conn, nv.id))["trang_thai"] == "dung"
        r = await jobs.handle_buoc(conn, {"id": nv.id, "lan_loi": so.LOI_TAM_TOI_DA - 1})
        assert (await repo.doc(conn, nv.id))["loi_ma"] == "MAT_KET_NOI"


async def test_xem_lai_video_nguon_ai_sinh(api_pool, seed_nv, kho_tep, env_nv, lipsync_gia):
    """Video AI sinh xem lại được ngay khi về kho — trước cả lúc dựng xong."""
    nv = await _tao(api_pool, nguon="anh", tep=_tep("mat.jpg", b"JPEG"))
    assert nv.videoUrl is None  # chưa sinh
    async with tenant_conn(api_pool, TENANT) as conn:  # lượt 1: gửi; lượt 2: tải video về kho
        await jobs.handle_buoc(conn, {"id": nv.id})
        await jobs.handle_buoc(conn, {"id": nv.id})
    o = await router.doc(nv_id=nv.id, p=_P, pool=api_pool)
    assert o.trangThai == "dung" and o.videoUrl == f"/api/v1/nhan-vat/{nv.id}/video/chinh"
    r = await router.video_nguon(nv_id=nv.id, loai="chinh", p=_P, pool=api_pool)
    assert r.body == b"MP4-CHINH" and r.media_type == "video/mp4"
    with pytest.raises(LoiPortal):  # clip tay chỉ sinh SAU lần dựng đầu (cần khung chờ)
        await router.video_nguon(nv_id=nv.id, loai="tay", p=_P, pool=api_pool)
    await _chay_job(api_pool, nv.id)
    r = await router.video_nguon(nv_id=nv.id, loai="tay", p=_P, pool=api_pool)
    assert r.body == b"MP4-TAY"
    with pytest.raises(LoiPortal):
        await router.video_nguon(nv_id=nv.id, loai="khac", p=_P, pool=api_pool)
    with pytest.raises(LoiPortal):
        await router.video_nguon(nv_id=nv.id, loai="chinh", p=_P_KHAC, pool=api_pool)
