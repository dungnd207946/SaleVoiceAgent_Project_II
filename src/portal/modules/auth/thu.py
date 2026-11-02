"""Nội dung hai thư đặt mật khẩu. KHÔNG biết SMTP, KHÔNG biết HTTP.

`core/mailer.py` biết cách gửi và không biết gửi gì; file này biết gửi gì và
không biết cách gửi. Docstring của mailer đã chỉ định chỗ này ("nội dung thư dựng
ở `modules/auth`") — đây là chỗ đó.

VÌ SAO TÁCH KHỎI `router.py`: trước 2026-08-22 hai thân thư là hai chuỗi một dòng
nhúng thẳng trong hai handler. Một thư HTML dùng được thật sự là ~40 dòng bảng
lồng bảng; nhân hai bản trong `router.py` thì phần routing biến mất dưới đống
`style=`. Và ở trong router thì muốn canh một dòng chữ cũng phải dựng cả app +
Postgres — trong khi hàm thuần thì `tests/modules/auth/test_thu.py` chạy trong
0.1 giây không cần Docker.

═══════════════════════════════════════════════════════════════════════════════
 HTML THƯ KHÔNG PHẢI HTML WEB
═══════════════════════════════════════════════════════════════════════════════
Ba luật chi phối mọi thứ dưới đây, và cả ba đều bị vi phạm bởi thói quen viết web:

1. KHÔNG `<style>`, KHÔNG `class` — Gmail cắt bỏ cả hai. Mọi trình bày phải là
   `style=` nội tuyến. Cái bẫy: Apple Mail GIỮ `<style>`, nên thư sai vẫn "trông
   ổn" ở máy người viết rồi vỡ ở nơi phần lớn người nhận đang đọc.
2. BẢNG, không flex/grid. Outlook trên Windows render bằng engine của Word —
   không có `display:flex`, `max-width` chỉ nghe lời một nửa.
3. NÚT PHẢI LÀ `<table><td bgcolor>` bọc `<a>`. Word engine bỏ qua `padding` trên
   thẻ inline, nên một `<a>` có `background-color` teo lại thành đúng một chữ có
   màu — trông như link, không như nút. `bgcolor` là thuộc tính HTML nên nó sống
   sót cả ở client lược bớt CSS.

Màu lấy từ token thật của FE (`src/styles/theme.css`) để thư và app không phải
hai thương hiệu: accent `#0d7a5f`, accent-deep `#0a5e49`, chữ chính `#14161a`,
chữ mờ `#5f656e`/`#666c76`. Sao chép giá trị chứ không import — backend không đọc
được CSS của FE, và một thư gửi đi rồi thì không đổi màu theo theme nữa.

═══════════════════════════════════════════════════════════════════════════════
 LOGO: PNG QUA `cid:`, VÀ `alt` LÀ LƯỚI CUỐI
═══════════════════════════════════════════════════════════════════════════════
Nguồn là `logo-nx-agent.svg` bên FE, nhưng **SVG vô dụng trong thư**: Gmail cắt
bỏ `<svg>`, Outlook không render. Nên nó được rasterize sẵn thành PNG 96px
(`tai_nguyen/logo-nx-agent-96.png`, hiện ở 48px ⇒ 2× cho màn retina) — tệp PNG là
bản chép, cùng lệ với `contracts/`. Đổi logo bên FE thì xuất lại PNG 96×96 bằng
công cụ bất kỳ (vd. `rsvg-convert -w 96 -h 96`).

Đi bằng `cid:` (ảnh nằm TRONG thư) chứ không bằng URL: ảnh remote bị chặn mặc
định ở phần lớn mail doanh nghiệp, nên một `<img src="https://…">` cho ra đúng
một ô vuông vỡ ở chỗ nhận diện thương hiệu. `data:` URI cũng bị Gmail và Outlook
chặn. Xem `mailer.gui()` về cấu trúc MIME mà `cid:` đòi.

⚠ `alt="NobleX Agent Portal"` KHÔNG phải cho trình đọc màn hình, nó là NỘI DUNG
DỰ PHÒNG: người nhận chặn ảnh vẫn phải đọc được tên hệ thống ở đúng chỗ đó. Đây
là lý do phần đầu thư còn giữ CẢ khối chữ bên cạnh logo — mất ảnh thì tên vẫn
còn nguyên, không hụt gì.

═══════════════════════════════════════════════════════════════════════════════
 BẢN TEXT LÀ MỘT LÁ THƯ, KHÔNG PHẢI MỘT BẢN DỰ PHÒNG
═══════════════════════════════════════════════════════════════════════════════
`mailer.gui()` gửi `multipart/alternative` — client CHỌN một trong hai bản, nên
bản text có người đọc thật. Ngoài ra HTML dày kèm text ba dòng là đúng hình dạng
bị bộ lọc chấm điểm spam cao, mà docstring `gui()` nói thư này PHẢI vào hộp thư
chính.

⚠ URL TRONG BẢN TEXT PHẢI NẰM RIÊNG MỘT DÒNG và là lần xuất hiện `/invite/` CUỐI
CÙNG. `mailer_stub` ở `tests/modules/auth/conftest.py` trích token bằng
`than_text.split("/invite/")[-1].split()[0]`. Dán URL giữa câu ("... tại {url}.")
làm dấu chấm dính vào token, và mọi test tròn vòng đăng ký đỏ với một thông báo
vô nghĩa. `test_ban_text_giu_duoc_phep_trich_token_cua_conftest` canh đúng điều
này.
"""

from dataclasses import dataclass
from functools import lru_cache
from html import escape
from importlib import resources
from typing import Final

CID_LOGO: Final = "logo-nx-agent"
"""Chỉ dùng ở HAI chỗ và phải khớp nhau: `src="cid:…"` trong thân HTML, và header
`Content-ID` mà `mailer.gui()` đặt (nơi nó được bọc trong `<>`). Lệch nhau thì ảnh
không hiện và KHÔNG lỗi nào phát ra — nên nó là một hằng, không phải hai chuỗi."""

_TEN_LOGO: Final = "logo-nx-agent-96.png"

_ACCENT: Final = "#0d7a5f"
_ACCENT_DEEP: Final = "#0a5e49"
_NEN: Final = "#f4f4f1"
_THAN: Final = "#ffffff"
_VIEN: Final = "#dcdad3"
_NGAN: Final = "#e6e3dc"
_CHU: Final = "#14161a"
_CHU_THAN: Final = "#2a2e35"
_CHU_MO: Final = "#5f656e"
_CHU_MO_HON: Final = "#666c76"

_FONT: Final = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"

_HAN_NGAY: Final = 7
"""Phải khớp `service.HAN_MOI`. KHÔNG import nó: `service` import `repo` import
`asyncpg`, và file này cố ý không có phụ thuộc nào để test chạy được không cần
Docker. Lệch nhau thì thư nói sai hạn — đổi `HAN_MOI` thì đổi cả đây."""


@dataclass(frozen=True, slots=True)
class Thu:
    """Ba phần khớp đúng ba tham số của `mailer.gui()`. Trả một object thay vì
    tuple ba chuỗi: ba chuỗi cùng kiểu đứng cạnh nhau thì gọi sai thứ tự không ai
    phát hiện — tiêu đề vào thân thư vẫn gửi được bình thường.
    """

    tieu_de: str
    than_text: str
    than_html: str
    anh_nhung: tuple[str, bytes] | None = None
    """Đi CÙNG nội dung, không để người gọi tự nhớ ghép vào.

    Thân HTML đã trỏ `cid:` tới ảnh này, nên một `Thu` không mang ảnh là một thư
    có ô vuông vỡ. Gắn ở đây thì `router.py` chỉ việc chuyển tiếp `t.anh_nhung`
    và không có chỗ nào để quên."""


@lru_cache(maxsize=1)
def _logo() -> bytes:
    """Đọc qua `importlib.resources`, KHÔNG qua đường dẫn tính từ `__file__`.

    Đường dẫn tương đối vỡ ngay khi ứng dụng chạy từ wheel đã cài — và nó vỡ ở
    production, nơi không ai chạy test. `lru_cache` vì tệp không đổi trong một
    tiến trình và mỗi thư gửi đi sẽ gọi lại hàm này.
    """
    return (resources.files("portal.modules.auth.tai_nguyen") / _TEN_LOGO).read_bytes()


def thu_dang_ky(*, ten: str, email: str, url: str) -> Thu:
    """Người TỰ đăng ký. Chào theo tên vì form đăng ký có tên trong tay.

    Câu chốt ở chân thư ("không có tài khoản nào hoạt động nếu mật khẩu chưa được
    đặt") là SỰ THẬT, không phải một lời an ủi: `tao_user_tu_dang_ky` sinh user ở
    `pending` với `password_hash = NULL`, và cửa đăng nhập chặn mọi lifecycle khác
    `active`. Nói được điều đó cho người nhận nhầm là lý do duy nhất thư này
    không cần một nút "không phải tôi".
    """
    return _dung(
        tieu_de="Đặt mật khẩu để hoàn tất đăng ký NobleX Agent Portal",
        tua="Hoàn tất đăng ký",
        loi_chao=f"Chào {ten}," if ten.strip() else "Chào bạn,",
        doan=[
            "Cảm ơn bạn đã đăng ký sử dụng NobleX Agent Portal. Tài khoản của bạn đã được "
            f"tạo với địa chỉ {email}, và việc còn lại chỉ là đặt một mật khẩu để "
            "bạn có thể đăng nhập.",
            "Bạn vui lòng bấm vào nút bên dưới để đặt mật khẩu.",
        ],
        ket="Nếu bạn không phải người đã đăng ký, bạn có thể bỏ qua thư này. Sẽ không "
        "có tài khoản nào hoạt động nếu mật khẩu chưa được đặt, và chúng tôi cũng "
        "sẽ không gửi thêm thư nào về việc này.",
        url=url,
    )


def thu_loi_moi_moi(*, email: str, ten_workspace: str, url: str) -> Thu:
    """Email CHƯA có tài khoản. Câu hỏi là "có tham gia không", không phải "đặt mật khẩu đi".

    KHÔNG hứa một tài khoản đã tồn tại. Bản trước viết «Một tài khoản đã được tạo
    sẵn cho địa chỉ …» và câu đó ĐÚNG lúc đó — `thanh_vien.moi` tạo user ngay lúc
    mời. Từ 2026-08-22 nó là lời nói dối: không có hàng `users` nào cho tới khi
    người nhận bấm nút và đặt mật khẩu (spec §5.5, nhánh `invite_new`).

    CÓ tên workspace — đảo lại quyết định 2026-08-15, xem test cùng tên ở
    `test_thu.py` cho lý lẽ đầy đủ.

    KHÔNG có tên người nhận: `thanh_vien.moi` chỉ có email trong tay, và ở luồng
    này thì đúng theo nghĩa đen — chưa có hàng `users` nào mang một cái tên.
    """
    return _dung(
        tieu_de=f"Lời mời tham gia workspace {ten_workspace} trên NobleX Agent Portal",
        tua="Lời mời tham gia",
        loi_chao="Chào bạn,",
        doan=[
            f"Bạn được mời tham gia workspace {ten_workspace} trên NobleX Agent Portal.",
            f"Nếu bạn đồng ý, hãy bấm nút bên dưới để tạo tài khoản cho địa chỉ {email} và đặt mật khẩu đăng nhập.",
        ],
        ket="Nếu bạn không muốn tham gia, bạn có thể bỏ qua thư này — sẽ không có tài "
        "khoản nào được tạo và chúng tôi cũng sẽ không gửi thêm thư nào về việc này.",
        url=url,
        nhan_nut="Tham gia workspace",
    )


def thu_loi_moi_da_co(*, email: str, ten_workspace: str, url: str) -> Thu:
    """Email ĐÃ có tài khoản `active`. Xin xác nhận, KHÔNG đặt lại mật khẩu.

    Trước 2026-08-22 nhánh này không gửi thư nào: `thanh_vien.moi` gọi thẳng
    `them_membership`. Nghĩa là một Quản trị của workspace bất kỳ kéo được người
    lạ vào workspace của mình, và người đó chỉ biết khi thấy nó trong switcher.

    NHẮC LẠI EMAIL trong thân thư vì người nhận có thể có nhiều tài khoản: câu hỏi
    là "tài khoản NÀO của bạn sẽ vào workspace này".

    Nút KHÔNG dẫn tới màn đặt mật khẩu — người này đã có mật khẩu. Phát một đường
    đặt lại mật khẩu mà không ai yêu cầu là một cửa sau, xem `thanh_vien.moi_lai`.
    """
    return _dung(
        tieu_de=f"Lời mời tham gia workspace {ten_workspace} trên NobleX Agent Portal",
        tua="Lời mời tham gia",
        loi_chao="Chào bạn,",
        doan=[
            f"Bạn được mời tham gia workspace {ten_workspace} trên NobleX Agent Portal, "
            f"với tài khoản {email} bạn đang dùng.",
            "Bạn vui lòng bấm vào nút bên dưới để xác nhận tham gia. Mật khẩu của bạn không thay đổi.",
        ],
        ket="Nếu bạn không muốn tham gia workspace này, bạn có thể bỏ qua thư này. "
        "Tài khoản của bạn không bị ảnh hưởng gì.",
        url=url,
        nhan_nut="Tham gia workspace",
    )


_HAN = (
    f"Vì lý do an toàn, liên kết này chỉ có hiệu lực trong {_HAN_NGAY} ngày. "
    "Nếu liên kết đã hết hạn, bạn vui lòng yêu cầu một liên kết mới."
)
_DAN_TAY = "Trường hợp nút bên trên không mở được, bạn vui lòng sao chép địa chỉ sau và dán vào trình duyệt:"
_KY = "Trân trọng,\nĐội ngũ NobleX Agent Portal"


def _dung(
    *, tieu_de: str, tua: str, loi_chao: str, doan: list[str], ket: str, url: str, nhan_nut: str = "Đặt mật khẩu"
) -> Thu:
    """Vỏ chung của cả hai thư. Hai thư chỉ khác đoạn mở đầu và câu chốt.

    Gộp phần còn lại vào đây vì bản trước của cặp thư này đã lệch nhau do được sửa
    rời: một bản nói hạn 7 ngày, bản kia không. Một vỏ chung thì không lệch được.
    """
    return Thu(
        tieu_de=tieu_de,
        than_text=_ban_text(loi_chao=loi_chao, doan=doan, ket=ket, url=url, nhan_nut=nhan_nut),
        than_html=_ban_html(tua=tua, loi_chao=loi_chao, doan=doan, ket=ket, url=url, nhan_nut=nhan_nut),
        anh_nhung=(CID_LOGO, _logo()),
    )


def _ban_text(*, loi_chao: str, doan: list[str], ket: str, url: str, nhan_nut: str) -> str:
    """URL RIÊNG MỘT DÒNG, không dấu câu bám theo — xem cảnh báo ở đầu file.

    Thụt hai dấu cách trước URL cho dễ đọc thì phá luôn phép trích của conftest
    (`.split()[0]` vẫn ra token, nhưng đừng thử vận may) — để nguyên đầu dòng.
    """
    phan = [loi_chao, "", *_xen_dong_trong(doan), f"{nhan_nut} tại địa chỉ sau:", "", url, "", _HAN, "", ket, "", _KY]
    return "\n".join(phan)


def _xen_dong_trong(doan: list[str]) -> list[str]:
    ra: list[str] = []
    for d in doan:
        ra += [d, ""]
    return ra


def _o(noi_dung: str, *, dem: str, co: str = "15px", mau: str | None = None, dam: str = "400") -> str:
    """Một hàng bảng. `dem` là `padding` — mọi khoảng cách dọc trong thư này là
    `padding` của `td`, KHÔNG phải `margin`: Outlook bỏ qua `margin` trên `p`/`div`
    và mọi khoảng trắng biến mất cùng một lúc.
    """
    return (
        f'<tr><td style="padding:{dem};font-family:{_FONT};font-size:{co};'
        f'line-height:1.65;font-weight:{dam};color:{mau or _CHU_THAN};">{noi_dung}</td></tr>'
    )


def _ngan(dem: str) -> str:
    """Đường ngăn: `div` có chiều cao + `line-height` KHỚP chiều cao đó.

    `<hr>` bị mỗi client vẽ một kiểu và Outlook thêm khoảng trắng quanh nó.
    `font-size:1px` cùng `&nbsp;` để một `div` cao 1px không bị chính chiều cao
    dòng của chữ bên trong đẩy phồng lên.
    """
    return (
        f'<tr><td style="padding:{dem};"><div style="height:1px;'
        f'background-color:{_NGAN};line-height:1px;font-size:1px;">&nbsp;</div></td></tr>'
    )


def _dau_thu() -> str:
    """Logo 48px + khối chữ hai dòng, trên MỘT hàng bảng — phương án ① đã chọn.

    Canh lề TRÁI, cùng trục với toàn bộ thân thư: không có trục thứ hai nào để
    lệch. Khớp đúng lockup của chính app (`components/shell/Rail.tsx`: logo cạnh
    tên), nên thư và ứng dụng đọc ra một thương hiệu.

    HAI Ô CỦA MỘT BẢNG, không phải `display:flex` — Word engine của Outlook không
    có flex, hai khối sẽ rơi xuống hai dòng.

    `width="48"` khai ở CẢ thuộc tính HTML lẫn `style`: Outlook đọc thuộc tính,
    phần còn lại đọc `style`. `display:block` để client không thêm khoảng trắng
    của baseline chữ bên dưới ảnh.

    Chữ "NobleX" đậm + "Agent Portal" mờ là cùng phép phân cấp với token
    `--color-brand-sub` của FE (chữ "Agent" cạnh logo).
    """
    return (
        '<tr><td style="padding:28px 32px 0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td width="48" style="padding-right:14px;">'
        f'<img src="cid:{CID_LOGO}" alt="NobleX Agent Portal" width="48" height="48" '
        'style="display:block;border:0;width:48px;height:48px;"></td>'
        f'<td style="font-family:{_FONT};">'
        f'<div style="font-size:16px;font-weight:700;line-height:1.25;color:{_CHU};">NobleX</div>'
        f'<div style="font-size:13.5px;font-weight:400;line-height:1.3;color:{_CHU_MO_HON};">Agent Portal</div>'
        "</td></tr></table></td></tr>"
    )


def _ban_html(*, tua: str, loi_chao: str, doan: list[str], ket: str, url: str, nhan_nut: str) -> str:
    """`escape()` MỌI thứ đi từ ngoài vào: `ten`, `email`, `url`.

    `ten` là input của form đăng ký. Trước 2026-08-22 thân thư không nội suy gì
    nên không có lỗ nào; thêm lời chào là tự mở ra một lỗ. Escape TẠI ĐÂY chứ
    không ở người gọi — người gọi thứ hai sẽ không biết mà escape.

    `url` do `mailer.url_tuyet_doi` dựng từ cấu hình + token base64url nên nó
    không mang ký tự cần escape hôm nay. Vẫn escape: cái "hôm nay" đó là một tính
    chất của hàm khác, ở file khác.
    """
    u = escape(url, quote=True)
    than = "".join(
        [
            _dau_thu(),
            _ngan("26px 32px 0"),
            _o(escape(tua), dem="22px 32px 0", co="20px", mau=_CHU, dam="600"),
            _o(escape(loi_chao), dem="16px 32px 0"),
            *[_o(escape(d), dem="12px 32px 0") for d in doan],
            _nut(u, nhan_nut),
            _o(
                f'{escape(_DAN_TAY)}<br><a href="{u}" style="color:{_ACCENT_DEEP};word-break:break-all;">{u}</a>',
                dem="22px 32px 0",
                co="13px",
                mau=_CHU_MO,
            ),
            _o(escape(_HAN), dem="18px 32px 0", co="14px", mau=_CHU_MO),
            _ngan("26px 32px 0"),
            _o(escape(ket), dem="18px 32px 0", co="13px", mau=_CHU_MO_HON),
            _o(
                escape(_KY).replace("\n", "<br>"),
                dem="20px 32px 30px",
                co="13px",
                mau=_CHU_MO_HON,
            ),
        ]
    )
    return (
        '<!doctype html><html lang="vi"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "</head>"
        # Nền khai TƯỜNG MINH trên cả `body` và bảng ngoài: client tối màu tô nền
        # của nó vào chỗ trống, và `#14161a` trên nền đen là thư không đọc được.
        f'<body style="margin:0;padding:0;background-color:{_NEN};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background-color:{_NEN};">'
        '<tr><td align="center" style="padding:32px 14px;">'
        # `width="100%"` + `max-width` cùng lúc: Word engine nghe `width`, phần
        # còn lại nghe `max-width`.
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:560px;background-color:{_THAN};border:1px solid {_VIEN};border-radius:10px;">'
        f"{than}"
        "</table></td></tr></table></body></html>"
    )


def _nut(url_da_escape: str, nhan: str) -> str:
    """Nút bấm — bảng bọc `<a>`, xem luật 3 ở đầu file.

    `border-radius` khai ở CẢ `td` và `a`: Outlook bỏ qua nó (nút ra vuông, chấp
    nhận được), còn client nào chỉ đọc một trong hai thì vẫn ra bo góc.

    `nhan` đi qua `escape()` như mọi thứ khác đi từ ngoài vào; hôm nay nó là hằng
    ở gọi-điểm, và cái "hôm nay" đó là tính chất của người gọi, không phải của
    hàm này.
    """
    return (
        '<tr><td style="padding:26px 32px 0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td bgcolor="{_ACCENT}" style="border-radius:6px;">'
        f'<a href="{url_da_escape}" style="display:inline-block;padding:13px 26px;'
        f"font-family:{_FONT};font-size:15px;font-weight:600;line-height:1.2;"
        f'color:#ffffff;text-decoration:none;border-radius:6px;">{escape(nhan)}</a>'
        "</td></tr></table></td></tr>"
    )
