"""Công thức ENDPOINT_URL — hàm thuần, không container nào.

VÌ SAO CÓ CỔNG NÀY: chuỗi mà `url_endpoint_agent()` trả về được COPY RA NGOÀI TỔ
CHỨC — nó đi vào `.env` của đối tác. Một lỗi chính tả ở đây không làm gì đỏ; nó
làm bên agent nối vào một hostname không tồn tại và mất một buổi để tìm.
"""

from portal.core.config import Settings
from portal.modules.enrollment.endpoint import KIND_CHAT, url_endpoint_agent

DOMAIN = "agents-dev.noble.vn"


def test_cong_thuc_dung_nguyen_van():
    """Neo TỪNG KÝ TỰ. `wss` không phải `ws`/`https`, `/v1/chat` một lần không hai.

    `wss://` KHÔNG `ws://` — gateway đứng sau TLS termination; đây là chỗ một lần
    tuột chữ `s` lộ ra. Bản đầu của yêu cầu viết `/v1/v1/chat` (lặp `v1`) — test
    này cũng là chỗ điều đó lộ ra nếu ai chép lại bản nháp ấy.
    """
    assert url_endpoint_agent("anphu", DOMAIN) == "wss://anphu.agents-dev.noble.vn/v1/chat"


def test_tenant_id_co_gach_duoi_giu_nguyen():
    """`slug_tenant()` sinh id có `_` (vd `san_dong_nam`). Dấu gạch dưới hợp lệ
    trong nhãn subdomain theo RFC 1123 mở rộng mà mọi resolver thực tế đều nhận."""
    assert url_endpoint_agent("san_dong_nam", DOMAIN) == "wss://san_dong_nam.agents-dev.noble.vn/v1/chat"


def test_khong_doi_hoa_thuong_va_khong_url_encode():
    """CHECK của control.tenants đã ràng `^[a-z][a-z0-9_]{1,30}$`, nên hàm KHÔNG
    tự gọt. Nếu một ngày tenant_id sai định dạng thì nó phải HIỆN RA ở URL, không
    bị `.lower()` che đi — che là biến lỗi dữ liệu thành lỗi kết nối khó truy."""
    assert url_endpoint_agent("AnPhu", DOMAIN) == "wss://AnPhu.agents-dev.noble.vn/v1/chat"


def test_kind_mac_dinh_la_chat_va_doi_duoc():
    """MVP chỉ dùng `chat`, nhưng chữ ký nhận `kind` sẵn để mở `voice` không phải
    sửa chữ ký — hàm này THUẦN suy URL, không đọc cột DB nào. `control.deployments.kind`
    đã bỏ hẳn (migration 0919); `kind` ở đây chỉ còn là tham số hình thức của công thức URL."""
    assert url_endpoint_agent("anphu", DOMAIN) == url_endpoint_agent("anphu", DOMAIN, KIND_CHAT)
    assert url_endpoint_agent("anphu", DOMAIN, "voice") == "wss://anphu.agents-dev.noble.vn/v1/voice"


def test_mac_dinh_cua_config_la_domain_that():
    """Cổng chống lệch: hàm thuần nhận domain làm tham số, nên chỉ test này neo
    được giá trị mặc định. Đổi `gateway_base_domain` mà không cố ý sẽ đỏ ở đây."""
    assert Settings().gateway_base_domain == DOMAIN
