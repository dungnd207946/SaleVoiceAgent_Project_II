"""Test `lipsync_musetalk/weights.py` — chọn UNet qua env + dọn cache nhân vật khi đổi UNet.

Không tải gì từ HF: chỉ test cấu hình và `don_cache_theo_unet` trên thư mục tạm.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_DUONG = Path(__file__).resolve().parent.parent / "lipsync_musetalk" / "weights.py"
SHA_VI = "6db22374831890150c908235817354dfe312b97e9c469293e39cada48a726244"
SHA_GOC = "7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007"


def _nap(monkeypatch, **env):
    for k in ("LIPSYNC_UNET_REPO", "LIPSYNC_UNET_FILE", "LIPSYNC_UNET_SHA256"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("lipsync_weights", str(_DUONG))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_mac_dinh_la_unet_tieng_viet(monkeypatch):
    w = _nap(monkeypatch)
    assert w.WEIGHTS[0] == ("NobleX-AI/santa-lipsync-musetalk", "unet.pth", w.UNET_DICH, SHA_VI)
    assert w.UNET_DICH == "models/musetalkV15/unet.pth"


def test_env_rong_roi_ve_mac_dinh(monkeypatch):
    # compose truyền `LIPSYNC_UNET_REPO=` (rỗng) khi .env không khai
    w = _nap(monkeypatch, LIPSYNC_UNET_REPO="", LIPSYNC_UNET_FILE="", LIPSYNC_UNET_SHA256="")
    assert w.UNET_SHA256 == SHA_VI and w.UNET_REPO == "NobleX-AI/santa-lipsync-musetalk"


def test_env_ve_unet_goc(monkeypatch):
    w = _nap(monkeypatch, LIPSYNC_UNET_REPO="TMElyralab/MuseTalk", LIPSYNC_UNET_FILE="musetalkV15/unet.pth",
             LIPSYNC_UNET_SHA256=SHA_GOC)
    assert w.WEIGHTS[0] == ("TMElyralab/MuseTalk", "musetalkV15/unet.pth", w.UNET_DICH, SHA_GOC)
    # đích không đổi theo model ⇒ musetalk (đường dẫn tương đối cố định) vẫn nạp đúng file
    assert sum(1 for r in w.WEIGHTS if r[2] == "models/musetalkV15/unet.pth") == 1


def _nhan_vat(goc: Path, ten: str, moc: str | None) -> Path:
    d = goc / "avatars" / ten
    d.mkdir(parents=True)
    for f in ("im_lang.pkl", "poster.png", "latents.pt", "frames.npy", "info.json"):
        (d / f).write_bytes(b"x")
    if moc is not None:
        (d / "unet.sha256").write_text(moc)
    return d


def test_don_cache_bo_cache_render_bang_unet_khac(monkeypatch, tmp_path):
    w = _nap(monkeypatch)
    cu = _nhan_vat(tmp_path, "nguoi_dan", None)         # dựng trước khi có mốc = UNet gốc
    khac = _nhan_vat(tmp_path, "nv-a", SHA_GOC)
    khop = _nhan_vat(tmp_path, "nv-b", SHA_VI)
    assert w.don_cache_theo_unet(str(tmp_path)) == 2
    for d in (cu, khac):
        assert not (d / "im_lang.pkl").exists() and not (d / "poster.png").exists()
        assert (d / "unet.sha256").read_text() == SHA_VI
    # dữ liệu không phụ thuộc UNet giữ nguyên ⇒ không phải dựng lại nhân vật
    for d in (cu, khac, khop):
        assert all((d / f).exists() for f in ("latents.pt", "frames.npy", "info.json"))
    assert (khop / "im_lang.pkl").exists() and (khop / "poster.png").exists()


def test_don_cache_idempotent_va_khong_co_avatars(monkeypatch, tmp_path):
    w = _nap(monkeypatch)
    assert w.don_cache_theo_unet(str(tmp_path)) == 0
    _nhan_vat(tmp_path, "nv-a", None)
    assert w.don_cache_theo_unet(str(tmp_path)) == 1
    assert w.don_cache_theo_unet(str(tmp_path)) == 0


@pytest.mark.parametrize("sha", [SHA_VI, SHA_GOC])
def test_moi_sha_unet_dung_64_hex(monkeypatch, sha):
    w = _nap(monkeypatch, LIPSYNC_UNET_SHA256=sha)
    assert len(w.UNET_SHA256) == 64 and int(w.UNET_SHA256, 16) >= 0
