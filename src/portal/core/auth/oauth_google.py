"""Nói chuyện với Google, và CHỈ nói chuyện với Google.

Module này không biết `control.users`, không biết Redis, không biết nhánh nào
đang chạy. Nó nhận `code` và trả về claims. Chính sách («email chưa xác thực thì
sao», «user đình chỉ thì sao») nằm ở `modules/auth/dang_nhap_google.py`.

Chia vậy để test được cả hai bên mà không phải kéo nhau: bộ test của file này
chạy ở `tests/unit` với `httpx.MockTransport` và không cần Docker.

═══════════════════════════════════════════════════════════════════════════════
 VÌ SAO KHÔNG VERIFY CHỮ KÝ CỦA id_token
═══════════════════════════════════════════════════════════════════════════════
`id_token` ở đây đến TRỰC TIẾP từ Google qua TLS trong lượt POST /token dưới
đây — nó không đi qua trình duyệt, không qua tay ai. OIDC Core §3.1.3.7 miễn
verify chữ ký đúng trường hợp này: kênh đã được xác thực rồi.

ĐÂY LÀ MỘT QUYẾT ĐỊNH, KHÔNG PHẢI MỘT THIẾU SÓT. Tự viết verify RS256 là mở lại
hố `alg confusion` — đúng cái hố mà `core/auth/session.py` đã cố ý tránh khi từ
chối JWT cho phiên. Nếu ngày nào đó `id_token` được nhận từ FE (Google Identity
Services / One-Tap) thì lời miễn trừ này TAN BIẾN và verify chữ ký thành bắt
buộc — nhưng lúc đó cả kiến trúc đã khác, xem spec §5.

`aud` · `iss` · `exp` vẫn kiểm đủ: chúng chặn một token thật của Google nhưng
phát cho một ứng dụng khác, tức thứ mà TLS không nói gì về.
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlencode

import httpx

DIA_CHI_AUTH: Final = "https://accounts.google.com/o/oauth2/v2/auth"
DIA_CHI_TOKEN: Final = "https://oauth2.googleapis.com/token"
_ISS_HOP_LE: Final = frozenset({"accounts.google.com", "https://accounts.google.com"})
_HAN_GOI_GIAY: Final = 10.0


class LoiGoogle(Exception):
    """`ma` đi thẳng vào `?loi=` của FE — xem `modules/auth/router.py`.

    KHÔNG dùng `LoiPortal`: callback là điều hướng trình duyệt và trả 302, không
    trả JSON, nên envelope `{error:{code,message}}` không có chỗ để đi.
    """

    def __init__(self, ma: str) -> None:
        super().__init__(ma)
        self.ma = ma


@dataclass(frozen=True, slots=True)
class ClaimsGoogle:
    sub: str
    """Định danh BẤT BIẾN của tài khoản Google. Đây là khoá, không phải email."""
    email: str
    email_verified: bool
    name: str


def sinh_verifier() -> str:
    """43-128 ký tự theo RFC 7636. `token_urlsafe(48)` cho 64 ký tự."""
    return secrets.token_urlsafe(48)


def thach_thuc(verifier: str) -> str:
    """S256, KHÔNG `plain`. `plain` gửi thẳng verifier trong URL của trình duyệt
    và biến PKCE thành một thủ tục rỗng."""
    bam = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(bam).decode().rstrip("=")


def duong_uy_quyen(*, client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """`prompt=select_account`: buộc màn chọn tài khoản hiện MỖI lượt.

    Cố ý chịu thêm một cú bấm. Máy dùng chung mà tự đăng nhập bằng tài khoản
    Google đang mở sẵn là một bất ngờ tệ hơn nhiều so với một màn chọn.
    """
    tham_so = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{DIA_CHI_AUTH}?{urlencode(tham_so)}"


def _giai_ma_phan_than(id_token: str) -> dict[str, Any]:
    try:
        than = id_token.split(".")[1]
        # base64url không đệm '='; thêm đủ đệm trước khi giải mã.
        than += "=" * (-len(than) % 4)
        than = json.loads(base64.urlsafe_b64decode(than))
    except Exception as e:  # noqa: BLE001 — mọi kiểu hỏng đều là một câu trả lời
        raise LoiGoogle("GOOGLE_TU_CHOI") from e

    # `json.loads` trả `None`/`list`/`int`/`str` cho payload `null`/`[]`/`42`/`"x"` —
    # tất cả đều qua được khối trên, rồi `_doc_claims` gọi `.get()` và ăn
    # AttributeError. Một AttributeError ở đây là 500 trên đường đăng nhập chứ
    # không phải một redirect `?loi=`. Kiểu khai `dict[str, Any]` không tự ép gì cả.
    if not isinstance(than, dict):
        raise LoiGoogle("GOOGLE_TU_CHOI")
    return than


def _doc_claims(id_token: str, *, client_id: str) -> ClaimsGoogle:
    than = _giai_ma_phan_than(id_token)

    if than.get("iss") not in _ISS_HOP_LE:
        raise LoiGoogle("GOOGLE_TU_CHOI")
    if than.get("aud") != client_id:
        raise LoiGoogle("GOOGLE_TU_CHOI")
    if not isinstance(than.get("exp"), int) or than["exp"] <= time.time():
        raise LoiGoogle("GOOGLE_TU_CHOI")

    sub = than.get("sub") or ""
    email = than.get("email") or ""
    if not sub or not email:
        raise LoiGoogle("GOOGLE_TU_CHOI")

    return ClaimsGoogle(
        sub=sub,
        # lower() Ở ĐÂY, tại biên nhập: `users.email` có CHECK `email = lower(email)`
        # và mọi đường ghi phải chuẩn hoá trước — 0100 đã ghi lý lẽ đó.
        email=email.strip().lower(),
        email_verified=bool(than.get("email_verified")),
        name=(than.get("name") or email).strip(),
    )


async def doi_code_lay_claims(
    *,
    code: str,
    verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ClaimsGoogle:
    """Lượt máy-chủ-tới-máy-chủ DUY NHẤT của cả luồng.

    `transport` chỉ để test tiêm `MockTransport` — production truyền None. Tiêm
    qua tham số chứ không monkeypatch module: monkeypatch rò sang test khác chạy
    song song, và cái rò đó biểu hiện thành một test đỏ ở file không liên quan.
    """
    async with httpx.AsyncClient(transport=transport, timeout=_HAN_GOI_GIAY) as client:
        try:
            res = await client.post(
                DIA_CHI_TOKEN,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
        except httpx.HTTPError as e:
            raise LoiGoogle("GOOGLE_TU_CHOI") from e

    if res.status_code != 200:
        raise LoiGoogle("GOOGLE_TU_CHOI")

    id_token = res.json().get("id_token")
    if not id_token:
        raise LoiGoogle("GOOGLE_TU_CHOI")

    return _doc_claims(id_token, client_id=client_id)
