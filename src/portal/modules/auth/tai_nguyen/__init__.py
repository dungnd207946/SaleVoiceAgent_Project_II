"""Tài sản tĩnh của thư — hôm nay đúng một tệp: logo dạng PNG.

LÀ MỘT PACKAGE, không phải một thư mục trần: `thu.py` đọc tệp qua
`importlib.resources.files("portal.modules.auth.tai_nguyen")`, cách duy nhất
đúng khi ứng dụng chạy từ wheel đã cài (đường dẫn tương đối tính từ `__file__`
vỡ ngay khi có ai đóng gói lại, và nó vỡ ở production chứ không ở test).

VÌ SAO PNG mà không phải SVG: xem docstring `thu.py`. Gmail cắt bỏ `<svg>`.
"""
