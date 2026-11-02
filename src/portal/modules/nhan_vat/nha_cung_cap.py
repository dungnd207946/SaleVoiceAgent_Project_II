"""Nhà cung cấp SINH VIDEO TỪ ẢNH — một giao diện, nhiều bản cài, chọn bằng env.

Mọi nhà cung cấp đều bất đồng bộ (gửi yêu cầu → vài phút sau mới có video), nên giao
diện chỉ có hai bước, khớp với job thăm dò của module (`jobs.py`):

    gui(anh, mime, prompt)  → mã tác vụ (lưu vào `nhan_vat.tac_vu`)
    kiem(ma)                → KetQua: dang | xong (url hoặc bytes) | loi (thông điệp)

Thêm nhà cung cấp = thêm một lớp + một dòng trong `tao()`. Ảnh gửi dạng base64 / data URI
(không cần kho tệp công khai cho nhà cung cấp đọc).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from portal.modules.nhan_vat.settings import NhanVatEnv

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


@dataclass(frozen=True)
class KetQua:
    trang_thai: str  # dang | xong | loi
    url: str | None = None
    noi_dung: bytes | None = None
    loi: str = ""


class LoiNhaCungCap(Exception):
    """Lỗi KHÔNG thử lại được (sai khoá, tham số, ảnh bị từ chối…) — nhân vật chuyển `loi`."""


class NhaCungCap:
    """`giu_cuoi=False`: KHÔNG gửi ảnh làm khung cuối dù cấu hình `*_TAIL` bật — chế độ chỉnh
    dáng (video phải KẾT THÚC ở dáng đã chỉnh, không quay về dáng trong ảnh)."""

    ten = ""

    async def gui(
        self, anh: bytes, mime: str, prompt: str, thoi_luong: int | None = None
    ) -> str:  # pragma: no cover — giao diện
        raise NotImplementedError

    async def kiem(self, ma: str) -> KetQua:  # pragma: no cover
        raise NotImplementedError


# ───────────────────────────────────────────────────────────── Kling (chính chủ)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt_hs256(iss: str, bi_mat: str, *, bay_gio: float | None = None, song_s: int = 1800) -> str:
    """JWT HS256 tối giản theo tài liệu Kling (iss = access key, ký bằng secret key)."""
    t = int(bay_gio if bay_gio is not None else time.time())
    dau = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    than = _b64url(json.dumps({"iss": iss, "exp": t + song_s, "nbf": t - 5}, separators=(",", ":")).encode())
    ky = hmac.new(bi_mat.encode(), f"{dau}.{than}".encode(), hashlib.sha256).digest()
    return f"{dau}.{than}.{_b64url(ky)}"


class Kling(NhaCungCap):
    ten = "kling"

    def __init__(self, env: NhanVatEnv):
        if not (env.kling_access_key and env.kling_secret_key):
            raise LoiNhaCungCap("thiếu NHAN_VAT_KLING_ACCESS_KEY / NHAN_VAT_KLING_SECRET_KEY")
        self.env = env

    def _hdr(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {jwt_hs256(self.env.kling_access_key, self.env.kling_secret_key)}"}

    async def gui(
        self, anh: bytes, mime: str, prompt: str, thoi_luong: int | None = None, giu_cuoi: bool = True
    ) -> str:
        e = self.env
        b64 = base64.b64encode(anh).decode()
        body: dict = {
            "model_name": e.kling_model,
            "mode": e.kling_mode,
            "image": b64,
            "prompt": prompt,
            "negative_prompt": e.prompt_tranh,
            # Kling chỉ nhận 5 hoặc 10 giây.
            "duration": "10" if (thoi_luong or e.thoi_luong_s) > 7 else "5",
        }
        if e.kling_tail and giu_cuoi:
            body["image_tail"] = b64
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            r = await http.post(f"{e.kling_base_url}/v1/videos/image2video", json=body, headers=self._hdr())
        j = _json(r)
        if r.status_code >= 400 or j.get("code") not in (0, None):
            raise LoiNhaCungCap(f"Kling từ chối ({r.status_code}): {j.get('message') or r.text[:300]}")
        return str(j["data"]["task_id"])

    async def kiem(self, ma: str) -> KetQua:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            r = await http.get(f"{self.env.kling_base_url}/v1/videos/image2video/{ma}", headers=self._hdr())
        j = _json(r)
        if r.status_code >= 500:
            return KetQua("dang")  # trục trặc tạm thời phía Kling — lượt sau hỏi lại
        if r.status_code >= 400 or j.get("code") not in (0, None):
            return KetQua("loi", loi=f"Kling ({r.status_code}): {j.get('message') or r.text[:300]}")
        d = j.get("data") or {}
        tt = d.get("task_status")
        if tt == "succeed":
            vids = (d.get("task_result") or {}).get("videos") or []
            if not vids:
                return KetQua("loi", loi="Kling báo xong nhưng không có video")
            return KetQua("xong", url=vids[0]["url"])
        if tt == "failed":
            return KetQua("loi", loi=f"Kling: {d.get('task_status_msg') or 'tạo video thất bại'}")
        return KetQua("dang")


# ───────────────────────────────────────────────────────────── fal.ai (nhiều model)


class Fal(NhaCungCap):
    ten = "fal"

    def __init__(self, env: NhanVatEnv):
        if not env.fal_key:
            raise LoiNhaCungCap("thiếu NHAN_VAT_FAL_KEY")
        self.env = env

    def _hdr(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.env.fal_key}"}

    async def gui(
        self, anh: bytes, mime: str, prompt: str, thoi_luong: int | None = None, giu_cuoi: bool = True
    ) -> str:
        e = self.env
        data_uri = f"data:{mime};base64,{base64.b64encode(anh).decode()}"
        body: dict = {
            "prompt": prompt,
            "image_url": data_uri,
            "duration": str(thoi_luong or e.thoi_luong_s),
            "negative_prompt": e.prompt_tranh,
        }
        if e.fal_tail_field and giu_cuoi:
            body[e.fal_tail_field] = data_uri
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            r = await http.post(f"https://queue.fal.run/{e.fal_model}", json=body, headers=self._hdr())
        j = _json(r)
        if r.status_code >= 400 or "request_id" not in j:
            raise LoiNhaCungCap(f"fal từ chối ({r.status_code}): {j.get('detail') or r.text[:300]}")
        # Lưu cả hai URL fal trả — chúng là cách hỏi trạng thái/kết quả ĐÚNG cho model đó.
        return json.dumps({"status": j["status_url"], "response": j["response_url"]})

    async def kiem(self, ma: str) -> KetQua:
        u = json.loads(ma)
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            r = await http.get(u["status"], headers=self._hdr())
            if r.status_code >= 500:
                return KetQua("dang")
            st = _json(r).get("status")
            if st in ("IN_QUEUE", "IN_PROGRESS"):
                return KetQua("dang")
            r = await http.get(u["response"], headers=self._hdr())
        j = _json(r)
        if r.status_code >= 400:
            return KetQua("loi", loi=f"fal ({r.status_code}): {json.dumps(j.get('detail'))[:300] or r.text[:300]}")
        url = ((j.get("video") or {}).get("url")) or ((j.get("videos") or [{}])[0].get("url"))
        return KetQua("xong", url=url) if url else KetQua("loi", loi="fal báo xong nhưng không có video")


# ───────────────────────────────────────────────────────────── Wan (Alibaba Model Studio)

TRANG_THAI_WAN_LOI = {"FAILED", "CANCELED", "UNKNOWN"}


def goc_url(u: str) -> str:
    """`https://host/compatible-mode/v1` → `https://host` (API video là `/api/v1` gốc)."""
    p = httpx.URL(u.strip() or "https://dashscope-intl.aliyuncs.com")
    return f"{p.scheme}://{p.host}" + (f":{p.port}" if p.port else "")


def anh_cho_wan(anh: bytes) -> tuple[bytes, str]:
    """Ảnh khách → JPEG RGB mà Wan nhận: Wan KHÔNG nhận PNG có kênh alpha (ảnh chân dung
    đã tách nền thường đúng là thế) ⇒ trải lên nền trắng. Cạnh ngắn < 240px bị Wan từ chối
    ⇒ báo lỗi sớm, rõ ràng hơn mã lỗi của API."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(anh)) as im:
        im.load()
        if min(im.size) < 240:
            raise LoiNhaCungCap(f"ảnh quá nhỏ ({im.size[0]}×{im.size[1]}) — Wan cần mỗi cạnh ≥ 240px")
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            nen = Image.new("RGB", im.size, (255, 255, 255))
            nen.paste(im, mask=im.split()[-1])
            im = nen
        else:
            im = im.convert("RGB")
        ra = io.BytesIO()
        im.save(ra, "JPEG", quality=92)
    return ra.getvalue(), "image/jpeg"


def chua_le_ngang(anh: bytes, mime: str, ti_le: float) -> tuple[bytes, str]:
    """Nới ảnh sang HAI BÊN mỗi bên `ti_le` × bề ngang, trả PNG.

    Vì sao: ảnh khách thường bán thân CHẬT (người ~70% bề ngang, mỗi bên trống ~15% — đo
    2026-10-09), máy quay khoá và clip đưa tay lấy khung chờ làm khung đầu + cuối ⇒ model không
    lùi máy được, tay mở ra là đầu ngón lẹm ra ngoài mép. Prompt bóp động tác tới giới hạn rồi
    (bóp nữa thì Wan bỏ luôn động tác). Nới ở ảnh GỐC của clip nói ⇒ khung chờ, rồi clip tay sinh
    từ nó, đều có sẵn chỗ; service lipsync tách nền nên phần nới không lên sân khấu.

    Phần nới là MÀU TRUNG BÌNH THEO TỪNG HÀNG của dải sát mép, kéo giãn ra — nền liền với nền thật,
    không phải một viền màu trơn (Wan từng vẽ viền/khung ảnh khi thấy lề tách biệt). Giữ kênh alpha
    nếu có (`anh_cho_wan` trải nền trắng sau). `ti_le <= 0` hoặc không đọc được ảnh ⇒ trả NGUYÊN
    ảnh + `mime` gốc (hành vi y như trước khi có bước này — nhà cung cấp tự báo ảnh hỏng).
    """
    import io

    from PIL import Image, ImageFilter

    if ti_le <= 0:
        return anh, mime
    try:
        with Image.open(io.BytesIO(anh)) as goc:
            goc.load()
            im = goc.convert("RGBA" if goc.mode in ("RGBA", "LA", "P") else "RGB")
    except (OSError, ValueError):
        return anh, mime
    w, h = im.size
    le = max(1, round(w * ti_le))
    # Mẫu lấy LÙI VÀO 3–7% bề ngang, và phủ đè luôn 3% sát mép ảnh gốc: ảnh tải lên hay là ảnh
    # chụp màn hình có viền trắng/bo góc ở đúng mép — lấy mẫu sát mép là kéo giãn chính cái viền đó
    # thành một dải sáng tách biệt (đã thấy trên ảnh thật). Người cách mép ~15% nên 3% là an toàn.
    vao = max(1, round(w * 0.03))
    dai = max(2, round(w * 0.04))
    ra = Image.new(im.mode, (w + 2 * le, h))
    ra.paste(im, (le, 0))
    for x_mau, x_dan in ((vao, 0), (w - vao - dai, w + le - vao)):
        mau = im.crop((x_mau, 0, x_mau + dai, h)).resize((1, h), Image.Resampling.BOX)
        mau = mau.filter(ImageFilter.GaussianBlur(radius=max(1, h // 100)))
        ra.paste(mau.resize((le + vao, h), Image.Resampling.NEAREST), (x_dan, 0))
    buf = io.BytesIO()
    ra.save(buf, "PNG")
    return buf.getvalue(), "image/png"


class Wan(NhaCungCap):
    """DashScope video-synthesis, bất đồng bộ (header `X-DashScope-Async: enable` BẮT BUỘC —
    thiếu là lỗi «does not support synchronous calls»). Ảnh gửi Base64 data URI — cả hai giao
    thức đều nhận, nên không cần kho tệp công khai. `video_url` kết quả sống 24 giờ: job tải về
    kho ngay lượt thấy SUCCEEDED.

    Hai giao thức, chọn theo tên model:
      • `wan2.7*`: `input.media=[{type:first_frame,url}, {type:last_frame,url}]`, duration 2–15s,
        resolution 720P|1080P. Không gửi audio ⇒ model tự thêm nhạc nền — vô hại, service
        lipsync bỏ tiếng (`-an`).
      • còn lại (2.1–2.6): `input.img_url` (chỉ frame đầu — bản «đầu + cuối» 2.2 đòi URL
        công khai nên không dùng), `audio=false` cho `wan2.6-i2v-flash` (rẻ hơn, khỏi tiếng thừa).
    """

    ten = "wan"

    def __init__(self, env: NhanVatEnv):
        if not env.wan_api_key:
            raise LoiNhaCungCap("thiếu NHAN_VAT_WAN_API_KEY (hoặc MODEL_STUDIO_API_KEY)")
        self.env = env
        self.goc = goc_url(env.wan_base_url)

    def _hdr(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.env.wan_api_key}", "X-DashScope-Async": "enable"}

    def body(self, anh: bytes, mime: str, prompt: str, thoi_luong: int | None = None, giu_cuoi: bool = True) -> dict:
        e = self.env
        giay = thoi_luong or e.thoi_luong_s
        anh, mime = anh_cho_wan(anh)
        uri = f"data:{mime};base64,{base64.b64encode(anh).decode()}"
        tham_so: dict = {"resolution": e.wan_resolution, "prompt_extend": False, "watermark": False}
        if e.wan_model.startswith("wan2.7"):
            media = [{"type": "first_frame", "url": uri}]
            if e.wan_tail and giu_cuoi:
                media.append({"type": "last_frame", "url": uri})
            inp: dict = {"prompt": prompt, "negative_prompt": e.prompt_tranh, "media": media}
            tham_so["duration"] = min(15, max(2, giay))
        else:
            inp = {"prompt": prompt, "negative_prompt": e.prompt_tranh, "img_url": uri}
            if e.wan_model.startswith("wan2.6") or e.wan_model.startswith("wan2.5"):
                tham_so["duration"] = min(15, max(2, giay))
            if e.wan_model == "wan2.6-i2v-flash":
                tham_so["audio"] = False
        return {"model": e.wan_model, "input": inp, "parameters": tham_so}

    async def gui(
        self, anh: bytes, mime: str, prompt: str, thoi_luong: int | None = None, giu_cuoi: bool = True
    ) -> str:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            r = await http.post(
                f"{self.goc}/api/v1/services/aigc/video-generation/video-synthesis",
                json=self.body(anh, mime, prompt, thoi_luong, giu_cuoi),
                headers=self._hdr(),
            )
        j = _json(r)
        task = (j.get("output") or {}).get("task_id")
        if r.status_code >= 400 or not task:
            raise LoiNhaCungCap(
                f"Wan từ chối ({r.status_code}): {j.get('code', '')} {j.get('message') or r.text[:300]}"
            )
        return str(task)

    async def kiem(self, ma: str) -> KetQua:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            r = await http.get(f"{self.goc}/api/v1/tasks/{ma}", headers={"Authorization": self._hdr()["Authorization"]})
        if r.status_code >= 500 or r.status_code == 429:
            return KetQua("dang")  # tạm thời phía DashScope (quá tải / giới hạn tần suất)
        j = _json(r)
        if r.status_code >= 400:
            return KetQua("loi", loi=f"Wan ({r.status_code}): {j.get('code', '')} {j.get('message') or r.text[:300]}")
        out = j.get("output") or {}
        tt = out.get("task_status")
        if tt == "SUCCEEDED":
            url = out.get("video_url")
            return KetQua("xong", url=url) if url else KetQua("loi", loi="Wan báo xong nhưng không có video_url")
        if tt in TRANG_THAI_WAN_LOI:
            return KetQua("loi", loi=f"Wan {tt}: {out.get('code', '')} {out.get('message', '')}".strip())
        return KetQua("dang")  # PENDING | RUNNING


# ───────────────────────────────────────────────────────────── giả lập (dev/test)


class Gia(NhaCungCap):
    """Không gọi mạng: «sinh» ra đúng file video cấu hình sẵn. Prompt có chữ `raises one
    hand` (prompt clip đưa tay) ⇒ trả `NHAN_VAT_GIA_VIDEO_TAY` nếu có."""

    ten = "gia"

    def __init__(self, env: NhanVatEnv):
        if not env.gia_video:
            raise LoiNhaCungCap("thiếu NHAN_VAT_GIA_VIDEO (đường dẫn file mp4)")
        self.env = env

    async def gui(
        self, anh: bytes, mime: str, prompt: str, thoi_luong: int | None = None, giu_cuoi: bool = True
    ) -> str:
        tay = "raises one hand" in prompt and self.env.gia_video_tay
        return self.env.gia_video_tay if tay else self.env.gia_video

    async def kiem(self, ma: str) -> KetQua:
        p = Path(ma)
        if not p.is_file():
            return KetQua("loi", loi=f"không thấy file giả lập {ma}")
        return KetQua("xong", noi_dung=p.read_bytes())


_LOP: dict[str, type[NhaCungCap]] = {"kling": Kling, "fal": Fal, "wan": Wan, "gia": Gia}


def ten_nha_cung_cap(env: NhanVatEnv) -> str:
    return env.video_provider.strip().lower()


def tao(env: NhanVatEnv) -> NhaCungCap | None:
    """Nhà cung cấp đang cấu hình, hoặc None (tắt «tạo từ ảnh»). Ném `LoiNhaCungCap` nếu
    chọn nhà cung cấp mà thiếu khoá — cấu hình sai phải lộ ra, không lặng lẽ tắt."""
    ten = ten_nha_cung_cap(env)
    if not ten:
        return None
    if ten not in _LOP:
        raise LoiNhaCungCap(f"NHAN_VAT_VIDEO_PROVIDER={ten!r} không hỗ trợ (có: {', '.join(_LOP)})")
    return _LOP[ten](env)


async def tai_video(kq: KetQua, *, toi_da: int) -> bytes:
    """Bytes video của một KetQua `xong` (tải từ URL có hạn của nhà cung cấp)."""
    if kq.noi_dung is not None:
        return kq.noi_dung
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=True) as http:
        r = await http.get(kq.url or "")
        r.raise_for_status()
        if len(r.content) > toi_da:
            raise LoiNhaCungCap(f"video nhà cung cấp trả về quá lớn ({len(r.content) >> 20} MB)")
        return r.content


def _json(r: httpx.Response) -> dict:
    try:
        j = r.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    return j if isinstance(j, dict) else {}
