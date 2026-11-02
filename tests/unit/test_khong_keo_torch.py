"""Cổng cân nặng image: không thư viện ML nặng nào được vào môi trường production.

Repo đã thử Docling cho việc bóc chữ rồi bỏ (2026-08-10): ruột nó 9 MB nhưng kéo theo
1.35 GB phụ thuộc — torch 734M · scipy 86M · opencv 81M · transformers 58M · pandas 50M.
API và worker dùng chung một image, nên bản API cũng mang toàn bộ số đó mà không bao giờ
chạm tới. Xem comment ở `pyproject.toml` để có lý lẽ đầy đủ.

Cổng này tồn tại vì cách hỏng là ÂM THẦM: ai đó thêm một thư viện tiện tay, image phình
1.4 GB, và không lệnh nào báo — chỉ có build CI chậm dần và pull lâu hơn mà không ai truy
ra nguyên nhân.
"""

import importlib.util

NANG = ("torch", "torchvision", "docling", "transformers", "cv2", "scipy")


def test_khong_goi_ml_nang_nao_trong_moi_truong():
    co_mat = [ten for ten in NANG if importlib.util.find_spec(ten) is not None]
    assert co_mat == [], (
        f"gói ML nặng đã quay lại môi trường: {co_mat}. Nếu đây là chủ ý, sửa hằng NANG và ghi lý do — đừng xoá cổng."
    )


def test_ba_thu_vien_boc_chu_deu_co_mat():
    """Đối chứng: cổng trên không được xanh chỉ vì môi trường trống rỗng."""
    for ten in ("pypdf", "docx", "openpyxl", "pypdfium2"):
        assert importlib.util.find_spec(ten) is not None, f"thiếu {ten} — đường bóc chữ sẽ nổ lúc chạy"
