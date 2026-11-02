"""Chủ đề nền tảng bị ẩn khỏi màn «Dữ liệu ngoài».

Bộ nguồn/chủ đề mặc định đầy đủ nằm ở migration `0971_kbweb_theo_tenant` (seed tenant mới)
và bản test `tests/modules/kb/web/mac_dinh.py`.
"""

# Chủ đề vẫn chạy khi dựng hồ sơ nhưng không hiện ở màn «Dữ liệu ngoài», không sửa/xoá được qua API.
HIDDEN_TOPIC_CODES: frozenset[str] = frozenset({"road", "bridge", "area_development", "investor"})
# Nhãn mục hồ sơ của các chủ đề đó: agent vẫn đọc, màn chi tiết dự án thì không hiện.
HIDDEN_HEADINGS: tuple[str, ...] = (
    "Hạ tầng giao thông – Đường bộ",
    "Hạ tầng giao thông – Cầu",
    "Dự án lớn trong khu vực",
    "Chủ đầu tư",
)
