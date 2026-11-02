"""Mã hoá at-rest cho hai cột khoá THÔ. AES-256-GCM.

Ở `core/` chứ không trong một module, vì HAI module cần nó và Luật 3 cấm chúng
import ruột nhau:

    control.agent_keys.api_key    (`0918`, module enrollment)  — NGUY HIỂM HƠN:
                                   đổi được lấy `/runtime-credentials`, tức mật
                                   khẩu Postgres của tenant
    control.ingest_tokens.token   (`0927`, module ingest)      — ghi được dữ liệu
                                   vào workspace

⚠️ Cả hai cột lưu chuỗi thô CÓ CHỦ ĐÍCH — giao diện cho xem lại (`/thu-agent` dựng
`<select>` theo tên khoá; bảng token của cổng nạp bấm con mắt là mở). Nên KHÔNG
thể chỉ lưu băm; băm đã có ở cột riêng (`key_sha256`/`token_sha256`) và **đường xác
thực vẫn dùng băm, không đụng gì tới file này**. Đó là điều làm bản vá này rẻ: mã
hoá cột hiển thị không chạm một dòng nào của đường đăng nhập.

── PHỦ CẢ HAI CÙNG LÚC, KHÔNG PHẢI MỘT ─────────────────────────────────────
`0927` đã ghi rõ lý do hoãn hồi đó: mã hoá bảng mới rồi để nguyên bảng nguy hiểm
hơn là **dời rủi ro chứ không giảm**. Nên đây là một lượt, hai cột.

── VÌ SAO VẪN CÓ GIÁ TRỊ DÙ Ổ ĐĨA ĐÃ MÃ HOÁ ────────────────────────────────
Mã hoá tầng lưu trữ (Aurora/KMS) chặn được mất ổ đĩa và mất snapshot. Nó KHÔNG
chặn được thứ hay xảy ra hơn nhiều: một `pg_dump` ai đó lấy ra để gỡ lỗi rồi để
quên, một read replica, một câu `SELECT` từ một lỗ hổng đọc. Ở những đường đó dữ
liệu đã được giải mã xong rồi. Lớp này chặn đúng chúng.

Nó KHÔNG chặn được ứng dụng bị chiếm — app có khoá. Đừng bán nó như thế.

── ĐỌC ĐƯỢC CẢ HÀNG CŨ CHƯA MÃ HOÁ ─────────────────────────────────────────
`giai_ma()` trả nguyên văn chuỗi không mang tiền tố. Nhờ vậy bản vá này KHÔNG cần
một migration dữ liệu chạy cùng lúc với deploy: hàng cũ đọc vẫn ra, hàng mới ghi ra
đã mã hoá, và backfill hàng cũ (`cli/ma_hoa_bi_mat_cu.py`, gỡ 2026-10-06 — lấy lại
từ git) chạy sau lúc nào cũng được.

Thứ tự an toàn là hệ quả trực tiếp: deploy code TRƯỚC, backfill SAU. Đảo lại thì
giữa hai bước có một khoảng mà bản cũ đang chạy đọc phải ciphertext và trả về cho
người dùng một chuỗi `enc.v1.…` như thể đó là khoá.

── ĐỊNH DẠNG ──────────────────────────────────────────────────────────────
    enc.v1.<base64url(nonce‖ciphertext‖tag)>

`v1` là phiên bản ĐỊNH DẠNG, và nó có mặt từ ngày đầu để việc xoay khoá sau này
không phải là một cuộc migrate định dạng: thêm `enc.v2.` với một chùm khoá (giải mã
bằng khoá nào cũng được, mã hoá bằng khoá mới nhất) là thêm một nhánh, không phải
viết lại. Ship mã hoá mà không chừa đường xoay khoá là đặt sẵn một quả mìn — ngày
khoá rò thì không có cách nào đổi mà không mất dữ liệu.
"""

import base64
import hashlib
import hmac
import os
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TIEN_TO: Final = "enc.v1."

_NONCE_BYTE: Final = 12
"""96 bit — kích thước nonce khuyến nghị của GCM. Đổi số này là phá mọi ciphertext
đã ghi, vì `giai_ma` cắt đúng bấy nhiêu byte đầu."""

_AAD: Final = b"odyssey.bi_mat_luu.v1"
"""Dữ liệu xác thực kèm theo — buộc ciphertext vào ĐỊNH DẠNG này.

Không buộc vào tên bảng: kẻ đổi được ciphertext giữa hai bảng thì đã có quyền GHI
vào `control`, và lúc đó việc hoán đổi hai khoá không phải là thứ tệ nhất họ làm
được. Một AAD theo bảng sẽ mua rất ít mà làm mọi lời gọi phải mang thêm một tham
số ai cũng có thể truyền nhầm."""


def ma_hoa(tho: str) -> str:
    """Chuỗi thô → `enc.v1.…`. Nonce NGẪU NHIÊN mỗi lần gọi.

    Dùng lại một nonce với cùng khoá là mất TOÀN BỘ bảo đảm của GCM — không chỉ
    lộ bản rõ mà còn lộ khoá xác thực. Nên nonce lấy từ `os.urandom`, không phải
    một bộ đếm, và không bao giờ suy từ nội dung.
    """
    if not tho:
        return tho
    nonce = os.urandom(_NONCE_BYTE)
    ct = AESGCM(_khoa()).encrypt(nonce, tho.encode(), _AAD)
    return TIEN_TO + base64.urlsafe_b64encode(nonce + ct).decode()


def giai_ma(luu: str | None) -> str | None:
    """`enc.v1.…` → chuỗi thô. Chuỗi KHÔNG mang tiền tố trả về nguyên văn.

    Nhánh «nguyên văn» là chủ đích, không phải phòng thủ lỏng: nó là thứ cho phép
    deploy code trước và backfill sau. Xem docstring đầu tệp.

    KHÔNG nuốt lỗi giải mã. Khoá sai hoặc dữ liệu hỏng phải NỔ, vì cách hỏng im
    lặng duy nhất còn lại — trả chuỗi rỗng hay chính ciphertext — sẽ hiện lên
    giao diện như một khoá thật, và người vận hành sẽ đi dán nó vào đâu đó.
    """
    if luu is None or not luu.startswith(TIEN_TO):
        return luu
    goi = base64.urlsafe_b64decode(luu.removeprefix(TIEN_TO))
    return AESGCM(_khoa()).decrypt(goi[:_NONCE_BYTE], goi[_NONCE_BYTE:], _AAD).decode()


def _khoa() -> bytes:
    """32 byte, dẫn xuất bằng HMAC từ chuỗi cấu hình.

    Dẫn xuất chứ không dùng thẳng: `TOKEN_ENC_KEY` là thứ người vận hành gõ/dán,
    nên nó là một chuỗi độ dài bất kỳ chứ không phải đúng 32 byte ngẫu nhiên. HMAC
    đưa mọi chuỗi về đúng kích thước AES-256 cần mà không cắt cụt entropy.
    """
    from portal.core.config import get_settings

    return hmac.new(get_settings().token_enc_key_bytes(), b"aes256-gcm", hashlib.sha256).digest()
