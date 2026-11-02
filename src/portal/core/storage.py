"""Kho tệp — S3 ở production, MinIO ở dev/test. Cùng một giao thức.

VÌ SAO ASYNC (`aioboto3`, không `boto3`): publish có upload nằm trên đường người
dùng đang chờ. `boto3` đồng bộ sẽ chặn event loop của uvicorn suốt lượt upload —
một tenant publish là mọi request khác đứng im.

VÌ SAO CÁCH LY BẰNG TIỀN TỐ, KHÔNG BẰNG BUCKET RIÊNG: một bucket mỗi tenant nghĩa
là thêm tenant phải tạo tài nguyên hạ tầng, và số bucket của một tài khoản AWS có
trần. Tiền tố `tenants/<id>/*` cộng policy theo access key cho cùng mức cách ly mà
thêm tenant chỉ là thêm một hàng. Cổng 5 kiểm đúng cơ chế này.

MỌI đường dẫn phải đi qua `duong_dan_*()`. Ghép chuỗi tại chỗ gọi là cách chắc
chắn để một ngày nào đó có một key nằm ngoài tiền tố của tenant — và policy chỉ
bảo vệ được thứ nằm trong tiền tố nó biết.
"""

from contextlib import asynccontextmanager
from functools import lru_cache

import aioboto3
from botocore.exceptions import ClientError

from portal.core.ten_tai_nguyen import ten_khoa_truy_cap

__all__ = [
    "KhoTep",
    "KhongTimThay",
    "chinh_sach_tien_to",
    "kho_tep_tu_cai_dat",
    "ten_khoa_truy_cap",
    "tien_to_tenant",
]


class KhongTimThay(Exception):
    """Khoá không tồn tại trong kho.

    Là lớp riêng chứ không để `ClientError` lọt ra: tầng gọi cần phân biệt "chưa
    publish lần nào" (bình thường) với "kho tệp hỏng" (sự cố), và mã lỗi của S3
    không phải thứ router nên biết.
    """


def tien_to_tenant(tenant_id: str) -> str:
    """`tenants/<id>/` — MỌI thứ của một tenant trên kho tệp nằm dưới đây.

    Kho tệp KHÔNG có RLS, nên với nó **tiền tố chính là cơ chế cách ly** (xem
    `core/ten_tai_nguyen.py`). Chuỗi này trước bản xoá-cứng được ghép tay ở BỐN
    chỗ trong chính file này; thêm chỗ thứ năm cho đường xoá là thêm một cơ hội để
    một bản lệch — và lệch ở đây nghĩa là hoặc policy mở rộng hơn ý muốn, hoặc lệnh
    xoá quét sang tenant khác.
    """
    return f"tenants/{tenant_id}/"


def chinh_sach_tien_to(tenant_id: str, bucket: str) -> dict:
    """Policy S3 cho pod một tenant: CHỈ `tenants/<id>/*`.

    Ở dev là policy gắn vào access key của MinIO; ở production là IAM policy gắn
    vào role của task. Cùng một tài liệu JSON — đó là lý do nó là hàm ở đây chứ
    không phải một file YAML của devops: cổng 5 kiểm được đúng thứ prod dùng.

    ⚠️ `ListBucket` phải kèm điều kiện `s3:prefix`, KHÔNG cấp trần. Không có điều
    kiện thì pod liệt kê được toàn bộ bucket — và danh sách đường dẫn của khách
    khác đã là rò rỉ: tên tệp mang tên dự án, số lần publish nói họ hoạt động
    mạnh cỡ nào. Đây là chỗ dễ sót nhất khi viết policy S3 vì `GetObject` bị chặn
    đúng còn `ListBucket` thì không, và triệu chứng là không có triệu chứng nào.
    """
    tien_to = tien_to_tenant(tenant_id)
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/{tien_to}*"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
                "Condition": {"StringLike": {"s3:prefix": [f"{tien_to}*"]}},
            },
        ],
    }


class KhoTep:
    """Client kho tệp. Rẻ để tạo — nó chỉ giữ cấu hình, không giữ kết nối."""

    def __init__(
        self, endpoint_url: str | None, bucket: str, access_key: str, secret_key: str, region: str = "us-east-1"
    ):
        self._bucket = bucket
        self._cau_hinh: dict[str, object] = {
            "endpoint_url": endpoint_url,
            "region_name": region,
        }
        # Khoá rỗng ⇒ không truyền gì, để botocore tự đi chuỗi credential mặc định
        # (IAM role) — cách xác thực ở production. Phải là `and`, không phải
        # `is not None`: botocore nhận cả chuỗi rỗng và dựng credential rỗng, nên IAM
        # role không bao giờ được hỏi tới và mọi lời gọi S3 trả 403.
        if access_key and secret_key:
            self._cau_hinh["aws_access_key_id"] = access_key
            self._cau_hinh["aws_secret_access_key"] = secret_key
        self._session = aioboto3.Session()

    @asynccontextmanager
    async def _client(self):
        async with self._session.client("s3", **self._cau_hinh) as c:
            yield c

    async def ghi(self, khoa: str, noi_dung: bytes, *, content_type: str | None = None) -> None:
        them: dict[str, object] = {"ContentType": content_type} if content_type else {}
        async with self._client() as c:
            await c.put_object(Bucket=self._bucket, Key=khoa, Body=noi_dung, **them)

    async def xoa(self, khoa: str) -> None:
        """Xoá một khoá. `delete_object` của S3 không lỗi nếu khoá không tồn tại —
        khớp đúng ngữ nghĩa "đảm bảo không còn" mà nơi gọi (xoá tài liệu, dọn rác)
        cần, nên không phải kiểm tồn tại trước khi xoá."""
        async with self._client() as c:
            await c.delete_object(Bucket=self._bucket, Key=khoa)

    async def presign_get(self, khoa: str, *, ttl_sec: int = 300) -> str:
        """URL tải trực tiếp, có chữ ký, hết hạn sau `ttl_sec` giây.

        `generate_presigned_url` KHÔNG gọi mạng — nó chỉ ký cục bộ bằng credential
        hiện có — nên hàm này không xác nhận khoá tồn tại. Gọi cho khoá không tồn
        tại vẫn trả một URL hợp lệ; tải về URL đó mới nhận 404 từ S3, không phải
        từ đây.
        """
        async with self._client() as c:
            return await c.generate_presigned_url(
                "get_object", Params={"Bucket": self._bucket, "Key": khoa}, ExpiresIn=ttl_sec
            )

    async def doc(self, khoa: str) -> bytes:
        async with self._client() as c:
            try:
                r = await c.get_object(Bucket=self._bucket, Key=khoa)
            except ClientError as e:
                if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                    raise KhongTimThay(khoa) from e
                raise
            return await r["Body"].read()

    async def co(self, khoa: str) -> bool:
        async with self._client() as c:
            try:
                await c.head_object(Bucket=self._bucket, Key=khoa)
            except ClientError as e:
                if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                    return False
                raise
            return True

    async def liet_ke(self, tien_to: str) -> list[str]:
        """Mọi khoá dưới một tiền tố, đã sắp xếp.

        Phân trang tường minh: `list_objects_v2` trả tối đa 1000 khoá một lượt và
        **không báo lỗi** khi cắt bớt. Một bundle vài tệp thì không chạm trần, nhưng
        `liet_ke("tenants/<id>/")` sau vài trăm lần publish thì có — và triệu chứng
        là "bundle cũ biến mất", không phải một exception.
        """
        khoa: list[str] = []
        async with self._client() as c:
            token: str | None = None
            while True:
                them = {"ContinuationToken": token} if token else {}
                r = await c.list_objects_v2(Bucket=self._bucket, Prefix=tien_to, **them)
                khoa += [o["Key"] for o in r.get("Contents", [])]
                if not r.get("IsTruncated"):
                    break
                token = r.get("NextContinuationToken")
        return sorted(khoa)

    # ─── Chỉ dùng ở dev/test ─────────────────────────────────────────────────

    async def xoa_tien_to(self, tien_to: str) -> int:
        """Xoá MỌI object dưới một tiền tố. Trả số object đã xoá.

        Đường xoá cứng workspace gọi nó với `tien_to_tenant(tenant_id)`.

        `delete_objects` theo lô 1000 — trần của S3 API, và cũng là trần trả về của
        một lượt `list_objects_v2`. Xoá từng khoá một là N round-trip cho một
        workspace có vài nghìn tệp, đủ lâu để một request `DELETE` chạm timeout.

        ⚠️ TIỀN TỐ PHẢI KẾT THÚC BẰNG `/`. Không có nó thì `tenants/abc` cũng khớp
        `tenants/abcd/...` — tức xoá workspace `abc` cuốn theo dữ liệu của `abcd`.
        `tien_to_tenant()` luôn thêm dấu đó; phép kiểm ở đây là lưới thứ hai cho
        người gọi tự ghép chuỗi.

        KHÔNG dung thứ lỗi. Người gọi (`workspace.service.don_ha_tang_ngoai`) quyết
        định nuốt hay không — ở đây mà `except` thì "đã xoá 0 tệp" và "kho tệp hỏng"
        đọc ra cùng một con số.
        """
        if not tien_to.endswith("/"):
            raise ValueError(f"tiền tố phải kết thúc bằng '/': {tien_to!r}")
        khoa = await self.liet_ke(tien_to)
        if not khoa:
            return 0
        async with self._client() as c:
            for i in range(0, len(khoa), 1000):
                lo = khoa[i : i + 1000]
                await c.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": k} for k in lo], "Quiet": True},
                )
        return len(khoa)

    async def tao_bucket_neu_chua_co(self) -> None:
        """Dev/test. Ở production bucket do devops tạo cùng IAM policy của nó."""
        async with self._client() as c:
            try:
                await c.head_bucket(Bucket=self._bucket)
            except ClientError:
                await c.create_bucket(Bucket=self._bucket)

    async def xoa_sach(self) -> None:
        """Dev/test. KHÔNG có đường gọi từ router — nó xoá cả kho."""
        async with self._client() as c:
            for khoa in await self.liet_ke(""):
                await c.delete_object(Bucket=self._bucket, Key=khoa)


@lru_cache(maxsize=1)
def kho_tep_dung_chung() -> KhoTep:
    """Một `KhoTep` cho cả tiến trình. Dùng cái này ở đường phát tệp.

    Tab Media nạp tới 42 ảnh mỗi lần mở, và `kho_tep_tu_cai_dat()` dựng đối tượng MỚI mỗi
    request — 42 lần dựng session cho một lần mở tab. Test đổi cấu hình thì gọi `.cache_clear()`.
    """
    return kho_tep_tu_cai_dat()


def kho_tep_tu_cai_dat() -> KhoTep:
    """Dựng `KhoTep` từ `Settings`. CHỖ DUY NHẤT làm việc đó.

    Cả API lẫn worker gọi hàm này. Vì sao quan trọng: handler job `publish` chạy
    trong tiến trình worker, nơi **không có app nào** để lấy `app.state`. Nếu API
    lấy kho từ `app.state` còn worker tự dựng theo cách khác thì hai bên có thể
    trỏ vào hai bucket khác nhau, và triệu chứng là "publish báo thành công nhưng
    agent không thấy bundle" — không có lỗi nào ở đâu cả.
    """
    from portal.core.config import get_settings

    c = get_settings()
    return KhoTep(
        endpoint_url=c.s3_endpoint_url or None,
        bucket=c.s3_bucket,
        access_key=c.s3_access_key,
        secret_key=c.s3_secret_key,
        region=c.s3_region,
    )
