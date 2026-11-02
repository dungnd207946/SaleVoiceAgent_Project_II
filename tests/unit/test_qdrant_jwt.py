"""Token Qdrant — hàm thuần, không cần Docker.

Bài canh ở đây có một đặc điểm: chúng VERIFY chữ ký bằng code độc lập trong chính
test, không gọi lại hàm ký. So bằng cách gọi lại hàm ký là kiểm hàm khớp với chính
nó — luôn xanh, kể cả khi cả hai cùng sai.
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from portal.modules.enrollment import qdrant_jwt

KHOA = "khoa-ky-thu-nghiem-khong-phai-that"
HET_HAN = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _tach(token: str) -> tuple[dict, dict, str]:
    """Bóc JWT bằng tay — KHÔNG dùng lại hàm của module đang test."""
    h, p, s = token.split(".")
    dem = lambda x: x + "=" * (-len(x) % 4)  # noqa: E731 — bù đệm base64url
    return (
        json.loads(base64.urlsafe_b64decode(dem(h))),
        json.loads(base64.urlsafe_b64decode(dem(p))),
        s,
    )


def test_ba_phan_va_tieu_de_hs256():
    token = qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA)
    assert token.count(".") == 2
    tieu_de, _, _ = _tach(token)
    assert tieu_de == {"alg": "HS256", "typ": "JWT"}


def test_chu_ky_dung_hmac_sha256_tren_hai_phan_dau():
    """Verify độc lập: tự tính lại HMAC từ `header.payload`."""
    token = qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA)
    than, chu_ky = token.rsplit(".", 1)
    mong_doi = hmac.new(KHOA.encode(), than.encode(), hashlib.sha256).digest()
    assert chu_ky == base64.urlsafe_b64encode(mong_doi).decode().rstrip("=")


def test_chi_mo_dung_mot_collection_va_chi_doc():
    """Trái tim của cả bản vá. Sai claim này là mất toàn bộ tác dụng cách ly."""
    _, payload, _ = _tach(qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA))
    assert payload["access"] == [{"collection": "kb_anphu", "access": "r"}]


def test_khong_co_quyen_toan_cuc_trong_payload():
    """Qdrant hiểu `access: "m"`/`"r"` dạng CHUỖI là quyền TOÀN INSTANCE.

    Nên payload không được chứa dạng chuỗi ở bất kỳ đâu — một lần viết nhầm
    `access="r"` thay vì danh sách là cấp quyền đọc MỌI collection, và token đó
    vẫn chạy nên không gì báo.
    """
    _, payload, _ = _tach(qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA))
    assert isinstance(payload["access"], list)
    assert all(isinstance(m, dict) for m in payload["access"])


def test_exp_dung_bang_moc_truyen_vao():
    """`exp` phải là CHÍNH mốc người gọi đưa, không phải now()+ttl tính lại."""
    _, payload, _ = _tach(qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA))
    assert payload["exp"] == int(HET_HAN.timestamp())


def test_hai_tenant_ra_hai_token_khac_nhau():
    a = qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA)
    b = qdrant_jwt.ky_token_doc(collection="kb_sunrise", het_han=HET_HAN, khoa_ky=KHOA)
    assert a != b
    _, pa, _ = _tach(a)
    _, pb, _ = _tach(b)
    assert pa["access"][0]["collection"] == "kb_anphu"
    assert pb["access"][0]["collection"] == "kb_sunrise"


def test_doi_khoa_ky_thi_doi_chu_ky():
    """Xoay `service.api_key` của Qdrant phải làm mọi token cũ mất hiệu lực."""
    a = qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA)
    b = qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA + "-moi")
    assert a.rsplit(".", 1)[0] == b.rsplit(".", 1)[0], "thân giống nhau"
    assert a != b, "chữ ký phải khác"


def test_khoa_rong_bi_tu_choi():
    """Ký bằng chuỗi rỗng ra một token ai cũng giả được — phải nổ, không im lặng."""
    with pytest.raises(ValueError, match="khoá ký"):
        qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky="")


def test_khong_co_dau_bang_dem_trong_token():
    """RFC 7515 §2: base64url trong JWS KHÔNG đệm `=`. Qdrant từ chối token có nó."""
    token = qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA)
    assert "=" not in token


def test_them_collection_cung_quyen_doc_theo_thu_tu():
    _, payload, _ = _tach(
        qdrant_jwt.ky_token_doc(collection="kb_anphu", het_han=HET_HAN, khoa_ky=KHOA, them=("anphu_public_web",))
    )
    assert payload["access"] == [
        {"collection": "kb_anphu", "access": "r"},
        {"collection": "anphu_public_web", "access": "r"},
    ]
