"""Tài nguyên đi kèm package — hôm nay đúng một tệp: catalog giao thức gateway.

LÀ MỘT PACKAGE, không phải thư mục trần: `gateway_docs.py` đọc tệp qua
`importlib.resources.files("portal.modules.enrollment.tai_nguyen")`, cách duy
nhất đúng khi app chạy từ wheel đã cài.

VÌ SAO KHÔNG Ở `contracts/`, dù nó LÀ một artefact hợp đồng: `Dockerfile` build
bằng `uv sync --no-editable` rồi runtime stage chỉ copy `.venv`, `alembic.ini`
và `migrations` — `contracts/` không bao giờ vào image. Bản đầu đặt ở đó và đọc
bằng `Path(__file__).parents[4]`; nó chạy trong repo, qua hết test, rồi trả 500
trên UAT vì tệp không tồn tại ở đó. Cùng bài học `tai_nguyen` của module auth đã
ghi lại một lần.
"""
