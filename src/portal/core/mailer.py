"""Gửi thư SMTP. KHÔNG biết nghiệp vụ — nội dung thư dựng ở `modules/auth`.

VÌ SAO Ở `core/`: luật 3 của repo (module chỉ import `portal.core.*`). Đặt ở
`modules/` thì module thứ hai cần gửi thư sẽ phải import ruột module thứ nhất.

VÌ SAO KHÔNG HÀNG ĐỢI / KHÔNG RETRY: xem spec §5.4. Thư hỏng ⇒ log + trả False,
và đường phục hồi là người dùng đăng ký lại (nhánh `pending` phát token mới).
Một hàng đợi ở đây là một hệ thống phải vận hành, cho một tính năng chưa ai đo
được tần suất hỏng.
"""

import logging
from email.message import EmailMessage

import aiosmtplib

from portal.core.config import get_settings

log = logging.getLogger(__name__)


def dang_bat() -> bool:
    """Đủ điều kiện gửi chưa. Đọc cấu hình MỖI lần — test đổi được mà không nạp lại module."""
    c = get_settings()
    return bool(c.smtp_host and c.smtp_from and c.public_base_url)


def url_tuyet_doi(duong_dan: str) -> str:
    """`/invite/abc` -> `https://portal.noblex.vn/invite/abc`.

    API cố ý trả `invitePath` TƯƠNG ĐỐI (docstring `TaoUserRaOut.invitePath`), nên
    chỗ ghép origin có hai người: FE dùng `location.origin`, mailer dùng cấu hình.

    Dùng `public_base_url` — CÙNG biến với link ảnh công khai, xem docstring của
    trường đó ở `core/config.py` về việc vì sao chỉ có một địa chỉ ở đây. Ở đây
    KHÔNG gọi `public_url.kiem_base()`: `localhost` là giá trị ĐÚNG cho link mời ở
    dev (admin mở trên chính máy mình), trong khi với link ảnh thì không.
    """
    return f"{get_settings().public_base_url.rstrip('/')}/{duong_dan.lstrip('/')}"


async def gui(
    *, den: str, tieu_de: str, than_text: str, than_html: str, anh_nhung: tuple[str, bytes] | None = None
) -> bool:
    """True = đã gửi. False = mailer tắt HOẶC lỗi (đã log). KHÔNG BAO GIỜ ném.

    Người gọi đã commit giao dịch trước khi tới đây (spec §5.3) — ném ra ngoài
    cho người dùng một 500 trong khi tài khoản của họ ĐÃ tồn tại, tức mô tả sai
    trạng thái hệ thống.

    `multipart/alternative` (cả text lẫn html): thư chỉ có HTML bị nhiều bộ lọc
    chấm điểm spam cao hơn, và đây là thư PHẢI tới hộp thư chính.

    ═══════════════════════════════════════════════════════════════════════════
     `anh_nhung` — ẢNH ĐI TRONG THƯ, KHÔNG PHẢI MỘT LINK RA NGOÀI
    ═══════════════════════════════════════════════════════════════════════════
    `(cid, byte)`. Thân HTML trỏ tới nó bằng `src="cid:<cid>"` — KHÔNG có dấu
    `<>` ở phía HTML, nhưng CÓ ở header `Content-ID`; lệch một trong hai chỗ là
    ảnh không hiện và không lỗi nào phát ra.

    KHÔNG dùng `<img src="https://...">` cho logo: ảnh remote bị chặn MẶC ĐỊNH ở
    phần lớn mail doanh nghiệp, nên thứ người nhận thấy là một ô vuông vỡ ở đúng
    chỗ nhận diện thương hiệu. Cũng KHÔNG dùng `data:` URI — Gmail và Outlook
    đều chặn nó trong `<img>`. `cid:` là đường duy nhất còn lại.

    ⚠ CẤU TRÚC MIME PHẢI LÀ `alternative > [text, related > [html, ảnh]]`, nên
    `add_related` gọi trên CHÍNH PHẦN HTML (`get_payload()[1]`), không gọi trên
    `msg`. Gọi trên `msg` biến thư thành `mixed` và ảnh rơi xuống thành một tệp
    ĐÍNH KÈM — bản text thì mất người đọc, còn người nhận thấy một thư có
    attachment lạ. `disposition="inline"` giữ nó khỏi danh sách đính kèm.

    Ảnh KHÔNG được in ở nhánh mailer-tắt bên dưới: stdout không hiện được ảnh, và
    thứ lập trình viên cần copy từ console là cái link.

    ⚠ TRẢ VỀ `False` KHI TẮT — giữ nguyên, ĐỪNG đổi thành `True`. Giá trị này điều
    khiển `invitePath` phía gọi (`None` khi đã gửi thật, đường dẫn khi chưa) —
    xem `TaoUserRaOut.invitePath`.
    """
    c = get_settings()
    if not (c.smtp_host and c.smtp_from and c.public_base_url):
        # Spec §5.2: cấu hình chưa đủ ⇒ mailer IN THƯ RA STDOUT thay vì gửi, để
        # `make up` ở máy dev chạy được ngay — lập trình viên copy link từ console
        # thay vì cấu hình SMTP thật. In THÂN TEXT ĐẦY ĐỦ (có link), không chỉ log
        # cảnh báo suông.
        print(
            "\n".join(
                [
                    "─" * 70,
                    "[mailer] SMTP chưa cấu hình đủ (thiếu SMTP_HOST/SMTP_FROM/PUBLIC_BASE_URL)"
                    " — in thư ra đây thay vì gửi:",
                    f"Đến:    {den}",
                    f"Tiêu đề: {tieu_de}",
                    "-" * 70,
                    than_text,
                    "─" * 70,
                ]
            )
        )
        log.warning("mailer tắt (thiếu SMTP_HOST/SMTP_FROM/PUBLIC_BASE_URL) — đã in thư ra stdout cho %s", den)
        return False

    try:
        msg = EmailMessage()
        msg["From"] = f"{c.smtp_from_name} <{c.smtp_from}>"
        msg["To"] = den
        msg["Subject"] = tieu_de
        msg.set_content(than_text)
        msg.add_alternative(than_html, subtype="html")
        if anh_nhung:
            cid, du_lieu = anh_nhung
            msg.get_payload()[1].add_related(  # type: ignore[union-attr]
                du_lieu, maintype="image", subtype="png", cid=f"<{cid}>", disposition="inline"
            )

        await aiosmtplib.send(
            msg,
            hostname=c.smtp_host,
            port=c.smtp_port,
            username=c.smtp_user or None,
            password=c.smtp_pass or None,
            start_tls=c.smtp_starttls,
        )
    except Exception:
        # Nuốt CÓ CHỦ Ý — xem docstring. `exception()` giữ traceback để còn dò được.
        log.exception("gửi thư tới %s thất bại", den)
        return False
    return True
