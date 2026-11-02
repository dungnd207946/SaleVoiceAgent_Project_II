"""`core/avatar.py` — avatar DiceBear (style initials), hàm thuần, không I/O.

Avatar là SVG TẤT ĐỊNH theo seed, sinh LOCAL bằng `dicebear-core` — không gọi
API ngoài. Giao cho FE dưới dạng data URI NHÚNG trong response sẵn có
(`UserOut.avatar`, `KhachOut.avatar`…) thay vì một endpoint ảnh riêng: endpoint
mới kéo theo một action mới trong hợp đồng PQ_01, còn dưới MSW của FE thì một
đường ảnh không có fake sẽ vỡ.

MẶC ĐỊNH là **initials** (người dùng chốt 2026-08-22 lần hai, đảo thumbs cùng
ngày — "thumbs cợt nhả quá"): seed trần (tên user/khách, `avatar_seed` chưa
chọn) ra chữ cái đầu trên nền màu, nghiêm túc. Style KHÁC chỉ đến qua seed có
TIỀN TỐ `style:seed` — do lưới «Đổi avatar» phát (`GET /me/avatar-goi-y` trộn
nhiều style), lưu nguyên chuỗi vào `avatar_seed`. Tiền tố lạ rơi về initials
với TRỌN chuỗi làm seed — một cái tên chứa dấu hai chấm không được nổ.

Bài test neo cả hai chiều qua `<dc:title>`/`<text>` trong SVG — đổi luật parse
mà quên đổi test là đỏ ngay.
"""

from urllib.parse import unquote

from portal.core.avatar import avatar_data_uri


def test_tra_ve_data_uri_svg() -> None:
    uri = avatar_data_uri("Trần Hải Đăng")
    assert uri.startswith("data:image/svg+xml")


def test_cung_seed_ra_cung_mot_chuoi() -> None:
    assert avatar_data_uri("user-123") == avatar_data_uri("user-123")


def test_hai_seed_khac_ra_hai_avatar_khac() -> None:
    assert avatar_data_uri("Nguyễn Văn An") != avatar_data_uri("Trần Hải Đăng")


def test_seed_tran_ra_initials_tu_dau_cong_tu_cuoi() -> None:
    """Trùng đúng luật `suy_initials` của auth: từ ĐẦU + từ CUỐI → "TĐ"."""
    svg = unquote(avatar_data_uri("Trần Hải Đăng"))
    assert ">TĐ</text>" in svg


def test_ten_mot_tu_lay_dung_mot_chu_cai() -> None:
    """DiceBear tự suy "Hùng" → "HÙ" (2 ký tự đầu) — người dùng bắt được trên
    màn thật 2026-08-22: đọc như tiếng hù doạ. Luật của mình: tên một từ lấy
    MỘT chữ, nên phải suy chữ TRƯỚC khi đưa seed vào DiceBear."""
    svg = unquote(avatar_data_uri("Hùng"))
    assert ">H</text>" in svg
    assert "HÙ" not in svg


def test_seed_co_tien_to_style_dung_dung_style_do() -> None:
    svg = unquote(avatar_data_uri("thumbs:xK3fQ2"))
    assert "<dc:title>Thumbs</dc:title>" in svg
    assert "<text" not in svg


def test_tien_to_la_roi_ve_initials_voi_tron_chuoi_lam_seed() -> None:
    """Một cái tên chứa `:` không được nổ và không được mất nửa đầu."""
    svg = unquote(avatar_data_uri("abc:xyz"))
    assert "<text" in svg  # vẫn là initials, không phải một style lạ
    assert avatar_data_uri("abc:xyz") != avatar_data_uri("xyz")
