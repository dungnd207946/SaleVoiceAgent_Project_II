"""Nhà cung cấp sinh video từ ảnh — hàm thuần + hình dạng HTTP (MockTransport), không mạng."""

import base64
import hashlib
import hmac
import json

import httpx
import pytest

from portal.modules.nhan_vat import nha_cung_cap as ncc
from portal.modules.nhan_vat.settings import NhanVatEnv


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_jwt_kling_ky_dung_va_dung_truong():
    tok = ncc.jwt_hs256("AK", "SK", bay_gio=1_000_000)
    dau, than, ky = tok.split(".")
    # Verify ĐỘC LẬP (không gọi lại hàm ký): HMAC-SHA256 trên "dau.than".
    assert _b64d(ky) == hmac.new(b"SK", f"{dau}.{than}".encode(), hashlib.sha256).digest()
    assert json.loads(_b64d(dau)) == {"alg": "HS256", "typ": "JWT"}
    assert json.loads(_b64d(than)) == {"iss": "AK", "exp": 1_001_800, "nbf": 999_995}


def test_tao_theo_env():
    assert ncc.tao(NhanVatEnv(_env_file=None, video_provider="")) is None
    with pytest.raises(ncc.LoiNhaCungCap):
        ncc.tao(NhanVatEnv(_env_file=None, video_provider="kling"))  # thiếu khoá ⇒ lộ ra, không lặng lẽ tắt
    with pytest.raises(ncc.LoiNhaCungCap):
        ncc.tao(NhanVatEnv(_env_file=None, video_provider="sora"))
    assert ncc.tao(NhanVatEnv(_env_file=None, video_provider="FAL", fal_key="k")).ten == "fal"


def _mock(monkeypatch, handler):
    goc = httpx.AsyncClient

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return goc(*a, **k)

    monkeypatch.setattr(ncc.httpx, "AsyncClient", factory)


async def test_kling_gui_anh_dau_va_cuoi_roi_kiem(monkeypatch):
    nhan = {}

    def handler(req: httpx.Request):
        if req.method == "POST":
            nhan["body"] = json.loads(req.content)
            nhan["auth"] = req.headers["authorization"]
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "T1", "task_status": "submitted"}})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "https://v/1.mp4"}]}},
            },
        )

    _mock(monkeypatch, handler)
    k = ncc.Kling(NhanVatEnv(_env_file=None, kling_access_key="AK", kling_secret_key="SK"))
    assert await k.gui(b"IMG", "image/png", "nói") == "T1"
    b64 = base64.b64encode(b"IMG").decode()
    assert nhan["body"]["image"] == b64 and nhan["body"]["image_tail"] == b64
    assert nhan["body"]["duration"] == "5" and nhan["auth"].startswith("Bearer ")
    kq = await k.kiem("T1")
    assert kq.trang_thai == "xong" and kq.url == "https://v/1.mp4"


async def test_kling_that_bai_va_loi_tam(monkeypatch):
    tra = iter(
        [
            httpx.Response(200, json={"code": 0, "data": {"task_status": "failed", "task_status_msg": "ảnh vi phạm"}}),
            httpx.Response(503, text="bận"),
        ]
    )
    _mock(monkeypatch, lambda req: next(tra))
    k = ncc.Kling(NhanVatEnv(_env_file=None, kling_access_key="AK", kling_secret_key="SK"))
    kq = await k.kiem("T1")
    assert kq.trang_thai == "loi" and "ảnh vi phạm" in kq.loi
    assert (await k.kiem("T1")).trang_thai == "dang"  # 5xx = tạm thời, hỏi lại lượt sau


async def test_fal_dung_model_trong_env_va_doc_ket_qua(monkeypatch):
    nhan = {}

    def handler(req: httpx.Request):
        u = str(req.url)
        if req.method == "POST":
            nhan["url"] = u
            nhan["body"] = json.loads(req.content)
            return httpx.Response(
                200, json={"request_id": "R", "status_url": "https://q/s", "response_url": "https://q/r"}
            )
        if u == "https://q/s":
            return httpx.Response(200, json={"status": "COMPLETED"})
        return httpx.Response(200, json={"video": {"url": "https://cdn/v.mp4"}})

    _mock(monkeypatch, handler)
    f = ncc.Fal(NhanVatEnv(_env_file=None, fal_key="k", fal_model="fal-ai/veo3/image-to-video", fal_tail_field=""))
    ma = await f.gui(b"IMG", "image/jpeg", "nói")
    assert nhan["url"] == "https://queue.fal.run/fal-ai/veo3/image-to-video"
    assert nhan["body"]["image_url"].startswith("data:image/jpeg;base64,")
    assert "tail_image_url" not in nhan["body"]  # model không có ảnh cuối ⇒ không gửi
    kq = await f.kiem(ma)
    assert kq.trang_thai == "xong" and kq.url == "https://cdn/v.mp4"


# ── Wan (Alibaba Model Studio / DashScope) — hình dạng theo tài liệu chính thức:
#    help/en/model-studio/image-to-video-general-api-reference (wan2.7) và
#    image-to-video-api-reference (2.1–2.6, `img_url`).


def _png(w=320, h=480, alpha=False) -> bytes:
    import io

    from PIL import Image

    im = Image.new("RGBA" if alpha else "RGB", (w, h), (10, 20, 30, 0) if alpha else (10, 20, 30))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _wan_env(**kw):
    return NhanVatEnv(_env_file=None, wan_api_key="sk-x", **kw)


def test_wan_doc_khoa_tu_bien_model_studio(monkeypatch):
    """Khách đã có MODEL_STUDIO_API_KEY/_BASE cho chat ⇒ dùng lại được, base `compatible-mode`
    vẫn ra đúng origin của API gốc."""
    monkeypatch.setenv("MODEL_STUDIO_API_KEY", "sk-tu-model-studio")
    monkeypatch.setenv("MODEL_STUDIO_API_BASE", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    env = NhanVatEnv(_env_file=None, video_provider="wan")
    w = ncc.tao(env)
    assert w.ten == "wan" and env.wan_api_key == "sk-tu-model-studio"
    assert w.goc == "https://dashscope-intl.aliyuncs.com"


async def test_wan27_gui_dau_cuoi_base64_async_va_kiem(monkeypatch):
    nhan = {}

    def handler(req: httpx.Request):
        if req.method == "POST":
            nhan.update(url=str(req.url), hdr=dict(req.headers), body=json.loads(req.content))
            return httpx.Response(200, json={"output": {"task_status": "PENDING", "task_id": "T9"}, "request_id": "r"})
        nhan["poll"] = str(req.url)
        return httpx.Response(
            200, json={"output": {"task_id": "T9", "task_status": "SUCCEEDED", "video_url": "https://oss/v.mp4"}}
        )

    _mock(monkeypatch, handler)
    w = ncc.Wan(_wan_env())
    assert await w.gui(_png(alpha=True), "image/png", "nói") == "T9"
    assert nhan["url"] == "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
    assert nhan["hdr"]["x-dashscope-async"] == "enable" and nhan["hdr"]["authorization"] == "Bearer sk-x"
    b = nhan["body"]
    assert b["model"] == "wan2.7-i2v-2026-04-25"
    media = b["input"]["media"]
    assert [m["type"] for m in media] == ["first_frame", "last_frame"]
    # PNG có alpha ⇒ đã đổi sang JPEG (Wan không nhận alpha), cùng một ảnh ở cả hai đầu.
    assert media[0]["url"].startswith("data:image/jpeg;base64,") and media[0]["url"] == media[1]["url"]
    assert b["parameters"] == {"resolution": "720P", "prompt_extend": False, "watermark": False, "duration": 5}
    kq = await w.kiem("T9")
    assert nhan["poll"] == "https://dashscope-intl.aliyuncs.com/api/v1/tasks/T9"
    assert kq.trang_thai == "xong" and kq.url == "https://oss/v.mp4"


def test_wan_model_cu_dung_img_url_va_tat_tieng():
    b = ncc.Wan(_wan_env(wan_model="wan2.6-i2v-flash")).body(_png(), "image/png", "nói")
    assert "media" not in b["input"] and b["input"]["img_url"].startswith("data:image/jpeg;base64,")
    assert b["parameters"]["audio"] is False and b["parameters"]["duration"] == 5
    b = ncc.Wan(_wan_env(wan_model="wan2.2-i2v-flash")).body(_png(), "image/png", "nói")
    assert "duration" not in b["parameters"]  # 2.2/2.1: cố định 5s, gửi duration là lỗi tham số


async def test_wan_that_bai_tam_thoi_va_tu_choi(monkeypatch):
    tra = iter(
        [
            httpx.Response(200, json={"output": {"task_status": "RUNNING"}}),
            httpx.Response(429, json={"code": "Throttling"}),
            httpx.Response(
                200, json={"output": {"task_status": "FAILED", "code": "DataInspectionFailed", "message": "ảnh"}}
            ),
        ]
    )
    _mock(monkeypatch, lambda req: next(tra))
    w = ncc.Wan(_wan_env())
    assert (await w.kiem("T")).trang_thai == "dang"
    assert (await w.kiem("T")).trang_thai == "dang"  # 429 = giới hạn tần suất, hỏi lại lượt sau
    kq = await w.kiem("T")
    assert kq.trang_thai == "loi" and "DataInspectionFailed" in kq.loi


async def test_wan_khoa_sai_bao_loi_khong_thu_lai(monkeypatch):
    w = ncc.Wan(_wan_env())
    _mock(monkeypatch, lambda req: httpx.Response(401, json={"code": "InvalidApiKey", "message": "Invalid API-key"}))
    with pytest.raises(ncc.LoiNhaCungCap, match="InvalidApiKey"):
        await w.gui(_png(), "image/png", "nói")


def test_wan_anh_qua_nho_bao_som():
    with pytest.raises(ncc.LoiNhaCungCap, match="240"):
        ncc.Wan(_wan_env()).body(_png(200, 400), "image/png", "nói")


def test_do_dai_rieng_cho_clip_noi_va_clip_tay():
    """Clip nói dài tới 8s được; clip đưa tay giữ 5s (lipsync cắt ở 5s — dài hơn là mất đoạn hạ tay)."""
    w = ncc.Wan(_wan_env(thoi_luong_s=8))
    assert w.body(_png(), "image/png", "nói", 8)["parameters"]["duration"] == 8
    assert w.body(_png(), "image/png", "tay", 5)["parameters"]["duration"] == 5
    assert w.body(_png(), "image/png", "nói", 40)["parameters"]["duration"] == 15  # kẹp theo giới hạn Wan 2.7


async def test_kling_chi_nhan_5_hoac_10(monkeypatch):
    nhan = []

    def handler(req: httpx.Request):
        nhan.append(json.loads(req.content)["duration"])
        return httpx.Response(200, json={"code": 0, "data": {"task_id": "T"}})

    _mock(monkeypatch, handler)
    k = ncc.Kling(NhanVatEnv(_env_file=None, kling_access_key="AK", kling_secret_key="SK"))
    await k.gui(b"IMG", "image/png", "nói", 8)
    await k.gui(b"IMG", "image/png", "tay", 5)
    assert nhan == ["10", "5"]


def test_wan_khong_gui_khung_cuoi_khi_chinh_dang():
    b = ncc.Wan(_wan_env()).body(_png(), "image/png", "nói", 8, giu_cuoi=False)
    assert [m["type"] for m in b["input"]["media"]] == ["first_frame"]


def _anh_nen(w, h, mau=(120, 130, 140), mode="RGB"):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new(mode, (w, h), mau).save(buf, "PNG")
    return buf.getvalue()


def test_chua_le_ngang_noi_hai_ben_giu_nguyen_phan_giua():
    """Clip đưa tay lẹm đầu ngón ra ngoài mép (2026-10-09) ⇒ nới ảnh gốc clip nói mỗi bên 12%."""
    import io

    from PIL import Image

    goc = Image.new("RGB", (400, 300), (120, 130, 140))
    goc.paste((255, 0, 0), (180, 100, 220, 200))  # «người» ở giữa
    buf = io.BytesIO()
    goc.save(buf, "PNG")
    ra, mime = ncc.chua_le_ngang(buf.getvalue(), "image/png", 0.12)
    im = Image.open(io.BytesIO(ra)).convert("RGB")
    assert mime == "image/png" and im.size == (400 + 2 * 48, 300)
    assert im.getpixel((48 + 200, 150)) == (255, 0, 0)  # phần giữa không xê dịch
    # phần nới cùng màu nền (liền nền, không phải viền trắng/đen)
    for x in (0, 20, 495):
        assert max(abs(a - b) for a, b in zip(im.getpixel((x, 150)), (120, 130, 140), strict=True)) <= 2


def test_chua_le_ngang_xoa_vien_trang_sat_mep():
    """Ảnh chụp màn hình có viền trắng sát mép ⇒ không được kéo giãn viền đó thành dải sáng."""
    import io

    from PIL import Image

    goc = Image.new("RGB", (400, 300), (120, 130, 140))
    goc.paste((255, 255, 255), (0, 0, 6, 300))
    buf = io.BytesIO()
    goc.save(buf, "PNG")
    im = Image.open(io.BytesIO(ncc.chua_le_ngang(buf.getvalue(), "image/png", 0.12)[0])).convert("RGB")
    for x in (0, 30, 48 + 3):
        assert im.getpixel((x, 150))[0] < 140


def test_chua_le_ngang_0_la_tat_va_giu_alpha():
    goc = _anh_nen(300, 300)
    assert ncc.chua_le_ngang(goc, "image/jpeg", 0) == (goc, "image/jpeg")  # mime gốc, không đổi
    assert ncc.chua_le_ngang(b"JPEG", "image/jpeg", 0.12) == (b"JPEG", "image/jpeg")  # hỏng ⇒ nguyên
    import io

    from PIL import Image

    ra = Image.open(io.BytesIO(ncc.chua_le_ngang(_anh_nen(300, 300, (0, 0, 0, 0), "RGBA"), "image/png", 0.1)[0]))
    assert ra.mode == "RGBA" and ra.size == (360, 300)
