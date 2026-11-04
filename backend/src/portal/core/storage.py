"""Kho tệp — S3 ở production, MinIO ở dev/test. Cùng một giao thức.

VÌ SAO ASYNC (`aioboto3`, không `boto3`): upload nằm trên đường người dùng đang chờ.
`boto3` đồng bộ chặn event loop của uvicorn suốt lượt upload — mọi request khác đứng im.

Một cửa hàng, một bucket. Module tự đặt thư mục của nó
(`kb/` cho kho tri thức) — đường phát tệp công khai chỉ mở đúng những thư mục khai tường minh.
"""

from contextlib import asynccontextmanager
from functools import lru_cache

import aioboto3
from botocore.exceptions import ClientError

__all__ = ["KhoTep", "KhongTimThay", "kho_tep_dung_chung", "kho_tep_tu_cai_dat"]


class KhongTimThay(Exception):
    """Khoá không tồn tại trong kho.

    Lớp riêng chứ không để `ClientError` lọt ra: tầng gọi cần phân biệt "không có tệp"
    (404 bình thường) với "kho tệp hỏng" (sự cố), và mã lỗi S3 không phải thứ router nên biết.
    """


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
        **không báo lỗi** khi cắt bớt — thiếu vòng lặp thì tệp thứ 1001 "biến mất"
        mà không có exception nào.
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

        `delete_objects` theo lô 1000 (trần của S3 API) — xoá từng khoá là N round-trip.

        ⚠️ TIỀN TỐ PHẢI KẾT THÚC BẰNG `/`: không có nó thì `kb` khớp cả `kb-cu/...`.
        KHÔNG dung thứ lỗi — "đã xoá 0 tệp" và "kho hỏng" không được ra cùng một con số.
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

    Một trang nhiều ảnh là nhiều request phát tệp; `kho_tep_tu_cai_dat()` dựng đối tượng MỚI
    mỗi lần gọi. Test đổi cấu hình thì gọi `.cache_clear()`.
    """
    return kho_tep_tu_cai_dat()


def kho_tep_tu_cai_dat() -> KhoTep:
    """Dựng `KhoTep` từ `Settings`. CHỖ DUY NHẤT làm việc đó.

    Cả API lẫn worker gọi hàm này: worker không có `app.state`, và nếu hai bên dựng kho
    theo hai cách thì có thể trỏ vào hai bucket — "upload thành công nhưng job không thấy
    tệp", không có lỗi nào ở đâu cả.
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
