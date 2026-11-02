"""Cửa Google, phần nói chuyện với Google. Không DB, không Redis, không app.

`httpx.MockTransport` thay Google — nên bộ test này chạy được ở `tests/unit`,
tức không cần Docker.
"""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from portal.core.auth import oauth_google as og

CLIENT_ID = "abc.apps.googleusercontent.com"


def _id_token(**ghi_de) -> str:
    """Dựng một id_token GIẢ: header/payload base64url, chữ ký là rác.

    Chữ ký là rác CÓ CHỦ Ý — code không verify chữ ký, và test này neo đúng điều
    đó. Xem docstring `_doc_claims` cho lý lẽ (OIDC Core §3.1.3.7).
    """
    payload = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": int(time.time()) + 600,
        "sub": "104287",
        "email": "Ai.Do@NobleX.VN",
        "email_verified": True,
        "name": "Ai Đó",
    }
    payload.update(ghi_de)

    def b64(d: dict) -> str:
        raw = json.dumps(d).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{b64({'alg': 'RS256'})}.{b64(payload)}.chu-ky-la-rac"


def _google(id_token: str, *, status: int = 200) -> httpx.MockTransport:
    def xu_ly(req: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"id_token": id_token, "access_token": "at"})

    return httpx.MockTransport(xu_ly)


async def _doi(id_token: str, **kw) -> og.ClaimsGoogle:
    return await og.doi_code_lay_claims(
        code="c",
        verifier="v",
        client_id=CLIENT_ID,
        client_secret="s",
        redirect_uri="https://x/api/v1/auth/google/callback",
        transport=_google(id_token, **kw),
    )


def test_thach_thuc_la_s256_cua_verifier():
    v = "abc123"
    mong = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    assert og.thach_thuc(v) == mong


def test_duong_uy_quyen_mang_du_tham_so_bat_buoc():
    u = og.duong_uy_quyen(client_id=CLIENT_ID, redirect_uri="https://x/cb", state="st", challenge="ch")
    q = parse_qs(urlparse(u).query)
    assert u.startswith(og.DIA_CHI_AUTH)
    assert q["client_id"] == [CLIENT_ID]
    assert q["response_type"] == ["code"]
    assert q["scope"] == ["openid email profile"]
    assert q["state"] == ["st"]
    assert q["code_challenge"] == ["ch"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["prompt"] == ["select_account"]


async def test_doc_duoc_claims_va_chuan_hoa_email():
    c = await _doi(_id_token())
    assert c.sub == "104287"
    assert c.email == "ai.do@noblex.vn", "lower() ở biên nhập — users.email có CHECK lower"
    assert c.email_verified is True
    assert c.name == "Ai Đó"


async def test_aud_sai_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(aud="cua-ai-khac"))
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_iss_sai_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(iss="https://ke-gia-mao.vn"))
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_het_han_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(exp=int(time.time()) - 10))
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_thieu_sub_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(sub=""))
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_google_tra_loi_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(), status=400)
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_email_chua_xac_thuc_van_doc_duoc_claims():
    """Module này KHÔNG quyết định chính sách — nó chỉ đọc. Việc từ chối
    `email_verified=false` là của `dang_nhap_google.py`, nơi biết nhánh nào đang
    chạy. Trộn hai việc là để một module không có DB đi quyết định chuyện của DB."""
    c = await _doi(_id_token(email_verified=False))
    assert c.email_verified is False


@pytest.mark.parametrize("than_json", ["null", "[1,2,3]", "42", '"chuoi-tran"'])
async def test_payload_khong_phai_object_thi_tu_choi_chu_khong_no(than_json):
    """`json.loads` trả None/list/int/str cho những payload này. Trước bản sửa,
    `_doc_claims` gọi `.get()` trên chúng và ăn AttributeError — tức 500 ở đường
    đăng nhập thay vì một redirect `?loi=` gọn gàng."""

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    id_token = f"{b64(b'{"alg":"RS256"}')}.{b64(than_json.encode())}.chu-ky-la-rac"
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(id_token)
    assert e.value.ma == "GOOGLE_TU_CHOI"
