"""Seed kho tệp dev: bucket + một access key CHỈ-tiền-tố cho mỗi workspace. Idempotent.

CHỈ CHẠY TRÊN MINIO DEV. Ở production việc này là IAM: bucket do devops tạo, và
mỗi pod nhận một IAM role gắn đúng `chinh_sach_tien_to()`. Cùng một tài liệu
policy — đó là lý do nó là hàm trong `core/storage.py` chứ không phải YAML của
devops, và là lý do cổng 5 kiểm được đúng thứ production dùng.

VÌ SAO CẦN SEED NÀY: không có nó thì ở dev mọi pod dùng chung `minioadmin`, tức
là **không có cách ly kho tệp nào cả**. Cổng 5 vẫn xanh vì nó tự tạo key riêng
trong test — nên khoảng hở này không có triệu chứng cho tới lúc chạy hai agent
thật trên cùng máy dev và một cái đọc được bundle của cái kia.

Chạy: make seed-kho-tep   (sau make dev && make dev-seed)
"""

import asyncio
import contextlib
import sys
from urllib.parse import urlparse

from minio import MinioAdmin
from minio.credentials import StaticProvider

from portal.core.config import get_settings
from portal.core.storage import chinh_sach_tien_to, kho_tep_tu_cai_dat, ten_khoa_truy_cap
from portal.modules.enrollment.bi_mat import LOAI_S3, dan_xuat
from scripts.dev_seed import WORKSPACE


def _chan_ngoai_localhost(endpoint: str) -> None:
    host = urlparse(endpoint).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1", "minio"):
        sys.exit(f"TỪ CHỐI: kho tệp {host!r} không phải localhost. Script này chỉ dành cho MinIO dev.")


async def main() -> None:
    c = get_settings()
    endpoint = c.s3_endpoint_url or ""
    if not endpoint:
        sys.exit("TỪ CHỐI: S3_ENDPOINT_URL trống nghĩa là đang trỏ vào Amazon S3 thật.")
    _chan_ngoai_localhost(endpoint)

    await kho_tep_tu_cai_dat().tao_bucket_neu_chua_co()

    admin = MinioAdmin(
        endpoint=endpoint.removeprefix("http://").removeprefix("https://"),
        credentials=StaticProvider(c.s3_access_key, c.s3_secret_key),
        secure=endpoint.startswith("https://"),
    )

    # `WORKSPACE` của `dev_seed.py` là `(tenant_id, tên, org_id)` — ba phần tử kể
    # từ khi M2a thêm tenancy hai tầng. Tách theo tên có nghĩa thay vì đếm phần
    # tử: thêm cột thứ tư ở đó thì dòng này vẫn chạy, còn `for a, b in ...` thì
    # vỡ với `too many values to unpack` — đúng thứ vừa xảy ra và nó chặn hẳn
    # `make up` ở bước dựng kho tệp.
    # Bí mật SUY DẪN, không phải một chuỗi cố định (M10). Vì sao bỏ MAT_KHAU_DEV:
    # dev và production phải đi CÙNG một đường code sinh bí mật. Một mật khẩu cứng
    # ở dev nghĩa là `bi_mat.dan_xuat()` chỉ được chạy thật lần đầu ở production —
    # chỗ tệ nhất để phát hiện nó sai. Version 1 vì seed là lần cấp phát đầu tiên;
    # xoay khoá về sau đi qua POST /agent/admin/tenants/<id>/rotate-secrets.
    master = c.master_key_bytes()

    for ws in WORKSPACE:
        tenant_id = ws[0]
        khoa = ten_khoa_truy_cap(tenant_id)
        # Idempotent: xoá rồi tạo lại. `user_add` trên key đã có sẽ đổi mật khẩu
        # chứ không lỗi, nhưng policy thì không tự cập nhật — nên gỡ hẳn cho chắc.
        with contextlib.suppress(Exception):  # chưa có key là trường hợp bình thường
            admin.user_remove(khoa)
        admin.user_add(khoa, dan_xuat(LOAI_S3, tenant_id, 1, master))
        admin.policy_add(khoa, policy=chinh_sach_tien_to(tenant_id, c.s3_bucket))
        admin.policy_set(khoa, user=khoa)
        print(f"  {khoa}  ->  tenants/{tenant_id}/*")

    print(f"Xong. Bucket {c.s3_bucket!r}, {len(WORKSPACE)} access key (bí mật suy dẫn, không in ra).")


if __name__ == "__main__":
    asyncio.run(main())
