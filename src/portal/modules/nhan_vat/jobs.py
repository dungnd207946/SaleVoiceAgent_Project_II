"""Job dựng nhân vật — MÁY TRẠNG THÁI, mỗi lượt một bước NGẮN rồi tự xếp lượt sau.

VÌ SAO KHÔNG MỘT JOB CHẠY TỪ ĐẦU TỚI CUỐI: sinh video từ ảnh mất vài phút, dựng trên
lipsync 1–2 phút. Handler chạy TRONG một giao dịch (`core/jobs.py`) ⇒ một job dài là giữ
giao dịch mở hàng phút, tiến độ ghi giữa chừng không ai thấy (chưa commit), và quá 15
phút thì bị thu hồi như việc treo. Nên mỗi lượt: đọc trạng thái → làm MỘT việc ngắn (gửi
yêu cầu / hỏi tiến độ / render một câu xem trước) → ghi trạng thái → `enqueue(cho_giay=…)`
lượt kế. Tiến độ commit sau mỗi lượt ⇒ FE thăm dò thấy thanh tiến độ chạy thật.

    tao_video  gửi ảnh (clip nói, chỉnh dáng) ─► hỏi mỗi 15s ─► tải video về kho ─► dung
    dung       đẩy video sang lipsync + xếp dựng ─► hỏi mỗi 5s ─► xem_truoc
               (tạo-từ-ảnh + clip tay: dựng xong ⇒ khung chờ ⇒ sinh clip tay ⇒ dựng lại — `_tay`)
    xem_truoc  poster + mỗi lượt MỘT câu demo (TTS → lip sync → mp4 vào kho) ─► san_sang
    (mọi bước) lỗi khách sửa được ─► loi (mã + hướng dẫn) · lỗi mạng tạm ─► thử lại có lùi

BẮT RỘNG có chủ ý (như `kb_file_index`): hàng kẹt ở trạng thái dở là spinner quay mãi —
mọi thất bại phải kết thúc ở `loi`. Phần việc chạy trong SAVEPOINT để lỗi giữa chừng
không đầu độc giao dịch ngoài (nơi ghi `loi`).
"""

from __future__ import annotations

import logging
import time

import asyncpg
import httpx

from portal.core.jobs import JobResult, enqueue, register
from portal.core.storage import kho_tep_tu_cai_dat, tien_to_tenant
from portal.modules.nhan_vat import nha_cung_cap as ncc_mod
from portal.modules.nhan_vat import repo, so
from portal.modules.nhan_vat.lipsync import LipsyncClient, LoiLipsync
from portal.modules.nhan_vat.settings import NhanVatEnv, get_env

log = logging.getLogger(__name__)

ACTOR = "nhan_vat"


class _LoiCoMa(Exception):
    def __init__(self, ma: str, chi_tiet: str = ""):
        super().__init__(f"{ma}: {chi_tiet}")
        self.ma, self.chi_tiet = ma, chi_tiet


def khoa_tep(tenant_id: str, nv_id: str, ten: str) -> str:
    """`tenants/<id>/nhan-vat/<nhân vật>/<tên>` — mọi tệp của một nhân vật, xoá theo tiền tố."""
    return f"{tien_to_tenant(tenant_id)}nhan-vat/{nv_id}/{ten}"


def mime_theo_khoa(khoa: str) -> str:
    duoi = khoa.rsplit(".", 1)[-1].lower()
    return so.LOAI_VIDEO.get(duoi) or so.LOAI_ANH.get(duoi) or "application/octet-stream"


async def xep_buoc(conn: asyncpg.Connection, tenant_id: str, nv_id: str, *, cho_giay: float = 0, lan_loi: int = 0):
    payload: dict = {"id": nv_id}
    if lan_loi:
        payload["lan_loi"] = lan_loi
    await enqueue(conn, tenant_id=tenant_id, kind=so.KIND_BUOC, actor=ACTOR, payload=payload, cho_giay=cho_giay)


# ─────────────────────────────────────────────────────────────── các bước


async def _tao_video(conn, tenant_id: str, nv: dict, env: NhanVatEnv) -> tuple[float | None, str]:
    ncc = ncc_mod.tao(env)
    if ncc is None:
        raise _LoiCoMa("CHUA_CAU_HINH_AI", "NHAN_VAT_VIDEO_PROVIDER rỗng")
    kho = kho_tep_tu_cai_dat()
    tv = dict(nv["tac_vu"])
    if not tv.get("chinh"):
        # Nới lề hai bên TRƯỚC clip nói (không phải ở clip tay): khung chờ cắt từ clip nói, clip tay
        # sinh từ khung chờ ⇒ cả hai cùng khung, mối nối F↔G giữ nguyên — xem `chua_le_ngang`.
        anh, mime = ncc_mod.chua_le_ngang(await kho.doc(nv["anh_key"]), mime_theo_khoa(nv["anh_key"]), env.le_ngang_anh)
        prompt = env.prompt_noi_chinh_dang + (f" {nv['mo_ta'].strip()}" if nv.get("mo_ta") else "")
        # Chỉnh dáng ⇒ KHÔNG khung cuối (= ảnh gốc, tức dáng chưa chuẩn). Clip đưa tay không gửi ở
        # đây: nó phải bắt đầu ở dáng ĐÃ chỉnh, nên sinh sau lần dựng đầu, từ khung chờ (`_tay`).
        tv["chinh"] = await ncc.gui(anh, mime, prompt, env.thoi_luong_s, giu_cuoi=False)
        tv["luc"] = time.time()
        tv["ncc"] = ncc.ten
        await repo.cap_nhat(conn, nv["id"], tac_vu=tv, buoc="gui_yeu_cau", tien_do=0.05)
        return so.CHO_NHA_CUNG_CAP_S, f"đã gửi {ncc.ten}"

    if time.time() - float(tv.get("luc", 0)) > env.timeout_phut * 60:
        raise _LoiCoMa("TAO_VIDEO_QUA_LAU", f"quá {env.timeout_phut} phút")
    kq = await ncc.kiem(tv["chinh"])
    if kq.trang_thai == "loi":
        raise _LoiCoMa("TAO_VIDEO_LOI", kq.loi)
    if kq.trang_thai == "xong":
        video = await ncc_mod.tai_video(kq, toi_da=so.VIDEO_MAX_BYTE)
        khoa = khoa_tep(tenant_id, nv["id"], "chinh.mp4")
        await kho.ghi(khoa, video, content_type="video/mp4")
        tv["chinh_key"] = khoa
        await repo.cap_nhat(conn, nv["id"], tac_vu=tv, video_key=khoa, trang_thai="dung", buoc=None, tien_do=0.3)
        return 0, "video đã sinh xong"
    da_cho = time.time() - float(tv["luc"])
    await repo.cap_nhat(conn, nv["id"], tac_vu=tv, buoc="dang_tao_video", tien_do=min(0.28, 0.05 + da_cho / 240 * 0.2))
    return so.CHO_NHA_CUNG_CAP_S, "chờ nhà cung cấp"


async def _dung(conn, tenant_id: str, nv: dict, env: NhanVatEnv) -> tuple[float | None, str]:
    lip = LipsyncClient(env)
    tv = dict(nv["tac_vu"])
    # Cờ «đã gửi sang lipsync» nằm trong `tac_vu`, KHÔNG suy từ `buoc`: `buoc` hiển thị bước
    # của lipsync (tach_nen, do_mat…) nên lấy nó làm cờ thì lượt sau tưởng chưa gửi và gửi
    # lại video — xếp dựng lại từ đầu, mãi không xong.
    if not tv.get("da_gui_lipsync"):
        kho = kho_tep_tu_cai_dat()
        for loai, khoa in (("chinh", nv["video_key"]), ("tay", nv["video_tay_key"])):
            if khoa:
                await lip.gui_video(nv["avatar_id"], loai, await kho.doc(khoa), mime_theo_khoa(khoa))
        await lip.dung(nv["avatar_id"], _cat_dau_s(nv, env))
        tv["da_gui_lipsync"] = True
        await repo.cap_nhat(conn, nv["id"], tac_vu=tv, buoc="cho_dung", tien_do=0.32)
        return so.CHO_DUNG_S, "đã xếp dựng"
    st = await lip.trang_thai(nv["avatar_id"])
    tt = (st or {}).get("trang_thai")
    if tt in (None, "chua_dung"):
        # Service mất nhân vật (volume bị xoá, restart trước khi nhận) ⇒ gửi lại từ đầu.
        tv.pop("da_gui_lipsync", None)
        await repo.cap_nhat(conn, nv["id"], tac_vu=tv, buoc=None)
        return 0, "lipsync không có nhân vật — gửi lại"
    if tt == "san_sang":
        if _can_clip_tay(nv, env, tv):
            return await _tay(conn, tenant_id, nv, env, tv, lip)
        await repo.cap_nhat(conn, nv["id"], trang_thai="xem_truoc", buoc=None, tien_do=0.85)
        return 0, "dựng xong"
    if tt == "loi":
        loi = st.get("loi") or {}
        raise _LoiCoMa(loi.get("ma") or "LOI_HE_THONG", loi.get("chi_tiet") or "")
    # Có clip tay: dựng lần 1 0,32→0,55 · sinh tay 0,55→0,65 · dựng lại 0,65→0,85.
    tu, den = (0.32, 0.55) if _can_clip_tay(nv, env, tv) else (0.65, 0.85) if tv.get("dung_lai") else (0.32, 0.85)
    await repo.cap_nhat(
        conn, nv["id"], buoc=st.get("buoc") or tt, tien_do=tu + (den - tu) * float(st.get("tien_do") or 0)
    )
    return so.CHO_DUNG_S, f"đang dựng: {st.get('buoc')}"


def _cat_dau_s(nv: dict, env: NhanVatEnv) -> float:
    return env.cat_dau_anh_s if nv["nguon"] == "anh" else 0.0


def _can_clip_tay(nv: dict, env: NhanVatEnv, tv: dict) -> bool:
    """Nhân vật tạo-từ-ảnh còn thiếu clip đưa tay và chưa bỏ nó. Video khách tự quay thì không:
    clip tay (nếu có) là do khách upload, không sinh gì bằng AI."""
    return nv["nguon"] == "anh" and env.tao_clip_tay and not nv["video_tay_key"] and not tv.get("tay_bo")


async def _bo_tay(conn, nv: dict, tv: dict, ly_do: str) -> tuple[float | None, str]:
    """Clip tay là phần PHỤ: hỏng thì nhân vật vẫn dùng được với bản đã dựng (không đưa tay)."""
    log.warning("nhân vật %s: bỏ clip đưa tay: %s", nv["id"], ly_do)
    tv["tay_bo"] = True
    await repo.cap_nhat(conn, nv["id"], tac_vu=tv, buoc=None)
    return 0, f"bỏ clip đưa tay: {ly_do}"


async def _tay(
    conn, tenant_id: str, nv: dict, env: NhanVatEnv, tv: dict, lip: LipsyncClient
) -> tuple[float | None, str]:
    """Clip đưa tay sinh TỪ KHUNG CHỜ lipsync đã chọn ở lần dựng không-tay, khung đó làm cả khung
    đầu lẫn khung cuối ⇒ G0 = G_cuối = khung chờ = F0 sau khi lipsync cắt đoạn chuyển dáng. Sinh từ
    ảnh gốc thì clip tay bắt đầu ở dáng ẢNH (chưa chỉnh) ⇒ giật ở mối nối. Xong ⇒ đẩy sang lipsync
    và dựng lại có G (lipsync cắt clip nói đúng tại khung chờ đã lưu)."""
    try:
        ncc = ncc_mod.tao(env)
    except ncc_mod.LoiNhaCungCap as e:
        return await _bo_tay(conn, nv, tv, str(e))
    if ncc is None:
        return await _bo_tay(conn, nv, tv, "NHAN_VAT_VIDEO_PROVIDER rỗng")
    kho = kho_tep_tu_cai_dat()
    if not tv.get("tay"):
        khung = await lip.khung_cho(nv["avatar_id"])
        if khung is None:
            return await _bo_tay(conn, nv, tv, "service lipsync chưa có khung chờ")
        await kho.ghi(khoa_tep(tenant_id, nv["id"], "khung-cho.jpg"), khung, content_type="image/jpeg")
        try:
            tv["tay"] = await ncc.gui(khung, "image/jpeg", env.prompt_tay, env.thoi_luong_tay_s, giu_cuoi=True)
        except ncc_mod.LoiNhaCungCap as e:  # handler ngoài coi lỗi này là chết — ở đây chỉ bỏ tay
            return await _bo_tay(conn, nv, tv, str(e))
        tv["luc_tay"] = time.time()
        await repo.cap_nhat(conn, nv["id"], tac_vu=tv, buoc="dang_tao_tay", tien_do=0.55)
        return so.CHO_NHA_CUNG_CAP_S, "đã gửi clip đưa tay"

    da_cho = time.time() - float(tv.get("luc_tay", 0))
    if da_cho > env.timeout_phut * 60:
        return await _bo_tay(conn, nv, tv, f"quá {env.timeout_phut} phút")
    try:
        kq = await ncc.kiem(tv["tay"])
    except ncc_mod.LoiNhaCungCap as e:
        return await _bo_tay(conn, nv, tv, str(e))
    if kq.trang_thai == "loi":
        return await _bo_tay(conn, nv, tv, kq.loi)
    if kq.trang_thai != "xong":
        await repo.cap_nhat(conn, nv["id"], buoc="dang_tao_tay", tien_do=min(0.64, 0.55 + da_cho / 240 * 0.1))
        return so.CHO_NHA_CUNG_CAP_S, "chờ clip đưa tay"
    try:
        video = await ncc_mod.tai_video(kq, toi_da=so.VIDEO_MAX_BYTE)
    except ncc_mod.LoiNhaCungCap as e:
        return await _bo_tay(conn, nv, tv, str(e))
    khoa = khoa_tep(tenant_id, nv["id"], "tay.mp4")
    await kho.ghi(khoa, video, content_type="video/mp4")
    # Ghi `video_tay_key` CÙNG lượt với đẩy + xếp dựng: lỗi mạng giữa chừng ⇒ savepoint lùi cả
    # cột này ⇒ lượt sau làm lại từ đầu (tải lại, đẩy lại). Ghi trước thì lượt sau tưởng xong và
    # đi thẳng sang xem trước với bản dựng KHÔNG tay.
    await lip.gui_video(nv["avatar_id"], "tay", video, "video/mp4")
    await lip.dung(nv["avatar_id"], _cat_dau_s(nv, env))
    tv["dung_lai"] = True
    await repo.cap_nhat(conn, nv["id"], tac_vu=tv, video_tay_key=khoa, buoc="cho_dung", tien_do=0.65)
    return so.CHO_DUNG_S, "đã xếp dựng lại có clip đưa tay"


async def _xem_truoc(conn, tenant_id: str, nv: dict, env: NhanVatEnv, lan_loi: int) -> tuple[float | None, str]:
    lip = LipsyncClient(env)
    kho = kho_tep_tu_cai_dat()
    if not nv["poster_key"]:
        khoa = khoa_tep(tenant_id, nv["id"], "poster.png")
        await kho.ghi(khoa, await lip.poster(nv["avatar_id"]), content_type="image/png")
        await repo.cap_nhat(conn, nv["id"], poster_key=khoa)
    da = list(nv["xem_truoc"])
    if len(da) < len(so.CAU_DEMO):
        cau = so.CAU_DEMO[len(da)]
        try:
            mp4 = await lip.xem_truoc(nv["avatar_id"], cau, so.NEN_XEM_TRUOC)
        except LoiLipsync as e:
            if lan_loi < 2:
                raise
            # Video xem trước là phần PHỤ (TTS có thể đang tắt) — nhân vật vẫn dùng được.
            log.warning("nhân vật %s: bỏ video xem trước: %s", nv["id"], e)
            await repo.cap_nhat(conn, nv["id"], trang_thai="san_sang", buoc="khong_co_xem_truoc", tien_do=1.0)
            return None, "sẵn sàng (không có xem trước)"
        khoa = khoa_tep(tenant_id, nv["id"], f"xem-truoc-{len(da)}.mp4")
        await kho.ghi(khoa, mp4, content_type="video/mp4")
        da.append({"cau": cau, "key": khoa})
        await repo.cap_nhat(
            conn, nv["id"], xem_truoc=da, buoc="xem_truoc", tien_do=0.85 + 0.15 * len(da) / len(so.CAU_DEMO)
        )
        return 0, f"xem trước {len(da)}/{len(so.CAU_DEMO)}"
    await repo.cap_nhat(conn, nv["id"], trang_thai="san_sang", buoc=None, tien_do=1.0)
    return None, "sẵn sàng"


# ─────────────────────────────────────────────────────────────── handler


async def handle_buoc(conn: asyncpg.Connection, payload: dict) -> JobResult:
    nv_id = str(payload["id"])
    lan_loi = int(payload.get("lan_loi", 0))
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    nv = await repo.doc(conn, nv_id, khoa=True)
    if nv is None:
        return JobResult(0, f"nhân vật {nv_id} đã xoá")
    tt = nv["trang_thai"]
    if tt in ("san_sang", "loi"):
        return JobResult(0, f"bỏ qua — đã {tt}")
    env = get_env()
    try:
        async with conn.transaction():
            if tt == "tao_video":
                cho, msg = await _tao_video(conn, tenant_id, nv, env)
            elif tt == "dung":
                cho, msg = await _dung(conn, tenant_id, nv, env)
            else:
                cho, msg = await _xem_truoc(conn, tenant_id, nv, env, lan_loi)
    except _LoiCoMa as e:
        await _ghi_loi(conn, nv_id, e.ma, e.chi_tiet)
        return JobResult(0, f"{nv_id}: {e}")
    except ncc_mod.LoiNhaCungCap as e:
        await _ghi_loi(conn, nv_id, "TAO_VIDEO_LOI", str(e))
        return JobResult(0, f"{nv_id}: nhà cung cấp: {e}")
    except (LoiLipsync, httpx.HTTPError, OSError) as e:
        # Tạm thời (service đang khởi động, mạng chập chờn) ⇒ thử lại, lùi dần tới 60s.
        if lan_loi + 1 >= so.LOI_TAM_TOI_DA:
            await _ghi_loi(conn, nv_id, "MAT_KET_NOI", f"{type(e).__name__}: {e}")
            return JobResult(0, f"{nv_id}: bỏ cuộc sau {lan_loi + 1} lượt lỗi")
        await xep_buoc(conn, tenant_id, nv_id, cho_giay=min(60, 5 * 2**lan_loi), lan_loi=lan_loi + 1)
        return JobResult(0, f"{nv_id}: tạm lỗi ({type(e).__name__}: {e}) — thử lại")
    except Exception as e:  # noqa: BLE001 — xem docstring: không để hàng kẹt
        log.exception("nhân vật %s: lỗi hệ thống ở bước %s", nv_id, tt)
        await _ghi_loi(conn, nv_id, "LOI_HE_THONG", f"{type(e).__name__}: {e}")
        return JobResult(0, f"{nv_id}: {type(e).__name__}: {e}")
    if cho is not None:
        await xep_buoc(conn, tenant_id, nv_id, cho_giay=cho)
    return JobResult(1, f"{nv_id}: {msg}")


async def _ghi_loi(conn: asyncpg.Connection, nv_id: str, ma: str, chi_tiet: str) -> None:
    await repo.cap_nhat(conn, nv_id, trang_thai="loi", buoc=None, loi_ma=ma, loi_chi_tiet=(chi_tiet or "")[:1000])


async def handle_don_lipsync(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Xoá nhân vật trên service lipsync sau khi hàng đã xoá (service bận dựng ⇒ thử lại)."""
    avatar_id = str(payload["avatar_id"])
    lan = int(payload.get("lan", 0))
    try:
        xong = await LipsyncClient(get_env()).xoa(avatar_id)
    except LoiLipsync as e:
        xong, ly_do = False, str(e)
    else:
        ly_do = "đang dựng"
    if xong:
        return JobResult(1, f"đã xoá {avatar_id} trên lipsync")
    if lan + 1 >= 30:
        return JobResult(0, f"bỏ dọn {avatar_id}: {ly_do}")
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    await enqueue(
        conn,
        tenant_id=tenant_id,
        kind=so.KIND_DON,
        actor=ACTOR,
        payload={"avatar_id": avatar_id, "lan": lan + 1},
        cho_giay=60,
    )
    return JobResult(0, f"chưa xoá được {avatar_id} ({ly_do}) — thử lại sau 60s")


register(so.KIND_BUOC, handle_buoc, max_concurrency=2)
register(so.KIND_DON, handle_don_lipsync)
