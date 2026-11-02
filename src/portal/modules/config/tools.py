"""Sổ 10 kỹ năng — NGUỒN DUY NHẤT cho cả prompt lẫn giao diện.

Nguồn: `santa-hotline-agent/src/noble_agent/tenants/noble/manifest.toml` `[tools].enabled`.
`SCHEMAS` trong repo agent có 11 tool; một cái (`no_lookup_needed`) không nằm ở
đây — van xả nội bộ (chỉ chào khi `LLM_FORCE_TOOL_FIRST_ROUND=true`), không phải
kỹ năng nghiệp vụ để tenant bật/tắt. (Ba tool "reserved" cũ — `crm_lookup`,
`verify_identity`, `support_ticket` — đã bị xoá hẳn bên agent 2026-08-18, không
còn tồn tại để liệt kê.) Bật thêm là **thêm một dòng vào bảng này**, không sửa
template cơ chế — đúng yêu cầu bảo trì của AG_01.

CẢ BA CỘT DÙNG CHUNG MỘT NGUỒN, CỐ Ý:
  · `mo_ta` đi vào danh mục kỹ năng của `RULES.md` — người đọc là **LLM**
  · `nhan` đi vào toggle của màn Agent Studio — người đọc là **trưởng phòng kinh doanh**
  · `PHU_THUOC` vừa hiện cảnh báo ở FE vừa validate ở BE

Tách chúng ra hai file là cách chắc chắn để một ngày nào đó prompt dạy gọi một
tool mà UI đã tắt — đúng lỗi AG_01 §6 đang bắt sửa.

⚠️ `nhan` là bản tạm. AG_01 để ngỏ "đặt tên nghiệp vụ cho đủ kỹ năng, kèm một
dòng giải thích" — việc của M5 và của người viết nội dung, không phải của M3.
"""

from typing import NamedTuple


class KyNang(NamedTuple):
    ten: str
    """Tên tool đúng như agent đăng ký. Đây là khoá — đổi là vỡ hợp đồng."""
    nhan: str
    """Tên nghiệp vụ hiện trên toggle. AG_01: KHÔNG hiện tên hàm cho người dùng."""
    mo_ta: str
    """Một dòng dạy LLM khi nào gọi. Đi vào danh mục kỹ năng của RULES.md."""


MUOI_HAI_KY_NANG: tuple[KyNang, ...] = (
    KyNang(
        "find_project", "Nhận diện tên dự án", "Tra mã dự án từ tên khách nói, chịu được nói tắt hoặc sai chính tả."
    ),
    KyNang(
        "discover_projects",
        "Khám phá & giới thiệu dự án",
        "Danh sách dự án theo tiêu chí (khu vực/ngân sách/loại hình/CĐT) và tổng quan chi tiết một dự án.",
    ),
    KyNang(
        "get_document",
        "Gửi tài liệu của dự án",
        "Lấy file CSBH, pháp lý, brochure của một dự án khi khách xin file.",
    ),
    KyNang(
        "search_units",
        "Tìm & gợi ý căn",
        "Tra căn trong một dự án hoặc gợi ý xuyên dự án theo ngân sách; kèm tư vấn phong thuỷ "
        "khi khách hỏi hướng hợp mệnh.",
    ),
    KyNang(
        "kb_search", "Tra tài liệu của workspace", "Tìm trong tài liệu khách đã nạp: chính sách, quy trình, phí, FAQ."
    ),
    KyNang("booking", "Đặt lịch tham quan", "Chốt lịch xem nhà. Theo giao thức ba bước, có code guard đi kèm."),
    KyNang("update_customer", "Ghi nhận thông tin khách", "Lưu nhu cầu và thông tin liên hệ khách vừa cung cấp."),
    KyNang("send_media", "Gửi ảnh và video dự án", "Gửi hình ảnh minh hoạ qua kênh khách đang dùng."),
    KyNang("escalate", "Chuyển người thật", "Bàn giao cho nhân viên khi ngoài phạm vi hoặc khách yêu cầu."),
    KyNang(
        "tinh_tra_gop",
        "Tính trả góp",
        "Tính số tiền vay, vốn tự có và số phải trả mỗi tháng theo chính sách vay của dự án.",
    ),
    # ⚠️ CHƯA AN TOÀN ĐỂ BẬT CHO TENANT THẬT (2026-09-07) — xem
    # docs/superpowers/specs/2026-09-07-analyze-projects-sql-ro-portal-design.md §0:
    # role sandbox `agent_sql_ro` phía Postgres không chặn được contacts/conversations/
    # dữ liệu chưa published do GRANT SELECT ... TO PUBLIC trên tenant_data (0909).
    # Entry catalog này để sẵn cho lúc lỗ hổng đóng — đừng publish "skills" có tên
    # này cho tenant thật trước đó.
    KyNang(
        "analyze_projects",
        "Thống kê & tồn kho",
        "Đếm/so sánh/xếp hạng/min-max-trung bình trên toàn bộ dự án và quỹ căn, kiêm câu hỏi tồn kho "
        "(còn bao nhiêu căn, loại nào, hướng nào) — sinh một câu SQL SELECT read-only trên 2 view "
        "published-only.",
    ),
)

TEN_KY_NANG: frozenset[str] = frozenset(k.ten for k in MUOI_HAI_KY_NANG)

PHU_THUOC: dict[str, tuple[str, ...]] = {
    "booking": ("find_project",),
    "get_document": ("find_project",),
    "send_media": ("find_project",),
}
"""Kỹ năng nào cần kỹ năng nào mới chạy đúng.

LÀ DỮ LIỆU, KHÔNG PHẢI `if`: FE đọc để hiện cảnh báo, BE đọc để từ chối. Một
nguồn, hai nơi dùng. Cảnh báo chỉ có ở FE là cảnh báo bỏ qua được bằng một curl.

Tất cả các tool nhận `project_code` đều phụ thuộc `find_project`, vì mã dự án chỉ
có một đường lấy: LLM hỏi `find_project` rồi truyền lại chuỗi nhận được.
"""


def thieu_phu_thuoc(dang_bat: list[str]) -> list[tuple[str, str]]:
    """Trả các cặp (kỹ năng, thứ nó cần mà đang tắt). Rỗng nghĩa là hợp lệ."""
    bat = set(dang_bat)
    return [(ten, can) for ten in sorted(bat) for can in PHU_THUOC.get(ten, ()) if can not in bat]
