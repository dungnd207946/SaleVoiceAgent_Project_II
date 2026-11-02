"""CỔNG 5 — cách ly kho tệp bằng policy theo tiền tố.

Sáu cổng cách ly của M1 chỉ phủ Postgres. Kho tệp là kho THỨ HAI và nó có lỗ
riêng: agent của mọi tenant nói chuyện với cùng một bucket. Cái duy nhất chặn
`agent_anphu` đọc `tenants/sunrise/` là policy gắn vào access key của nó.

Test bằng access key THẬT trên MinIO THẬT. Kiểm "hàm sinh policy trả đúng JSON"
thôi thì chưa phải cổng — nó chứng minh ta viết đúng thứ ta định viết, không
chứng minh S3 hiểu nó như ta tưởng. Chỗ này đã có tiền lệ trong dự án: cổng
SKIP LOCKED của M1 từng tự khai lại câu SQL trong chính file test.
"""

import pytest
from botocore.exceptions import ClientError

from portal.core.storage import KhoTep, chinh_sach_tien_to, ten_khoa_truy_cap

pytestmark = pytest.mark.integration

BUCKET = "odyssey-test"


def test_chinh_sach_chi_mo_dung_tien_to_cua_tenant():
    ch = chinh_sach_tien_to("anphu", BUCKET)

    tai_nguyen = [r for st in ch["Statement"] for r in st["Resource"]]
    assert any("tenants/anphu/*" in r for r in tai_nguyen)
    assert not any("sunrise" in r for r in tai_nguyen)
    assert not any(r.endswith(f"{BUCKET}/*") for r in tai_nguyen), "mở cả bucket là không cách ly gì"


def test_ten_khoa_suy_tu_tenant_id():
    """Suy trong code, không cấu hình tay: một tenant bị đặt nhầm tên khoá là một
    tenant dùng khoá của tenant khác."""
    assert ten_khoa_truy_cap("anphu") == "agent-anphu"


@pytest.fixture
def minio_admin(minio_endpoint: str):
    from minio import MinioAdmin
    from minio.credentials import StaticProvider

    host = minio_endpoint.removeprefix("http://")
    return MinioAdmin(endpoint=host, credentials=StaticProvider("minioadmin", "minioadmin"), secure=False)


@pytest.fixture
async def kho_hai_tenant(kho_tep: KhoTep, minio_admin, minio_endpoint: str):
    """Hai tenant có dữ liệu, và một access key CHỈ cho `anphu`."""
    await kho_tep.ghi("tenants/anphu/LIVE", b'{"version": 1}')
    await kho_tep.ghi("tenants/sunrise/LIVE", b'{"version": 9}')

    ten = ten_khoa_truy_cap("anphu")
    minio_admin.user_add(ten, "matkhaudai123")
    minio_admin.policy_add(ten, policy=chinh_sach_tien_to("anphu", BUCKET))
    minio_admin.policy_set(ten, user=ten)

    yield KhoTep(endpoint_url=minio_endpoint, bucket=BUCKET, access_key=ten, secret_key="matkhaudai123")

    minio_admin.user_remove(ten)
    minio_admin.policy_remove(ten)


async def test_khoa_cua_tenant_doc_duoc_tep_cua_chinh_no(kho_hai_tenant: KhoTep):
    """Mặt kia của cổng: cách ly KHÔNG được là "khoá sạch". Agent phải pull được
    bundle của chính nó, nếu không thì pod không boot."""
    assert await kho_hai_tenant.doc("tenants/anphu/LIVE") == b'{"version": 1}'


async def test_khoa_cua_tenant_KHONG_doc_duoc_tep_tenant_khac(kho_hai_tenant: KhoTep):
    """CỔNG 5. Đỏ khi policy nới ra cả bucket, hoặc khi ai đó quên gắn policy."""
    with pytest.raises(ClientError) as e:
        await kho_hai_tenant.doc("tenants/sunrise/LIVE")

    assert e.value.response["Error"]["Code"] in ("AccessDenied", "403")


async def test_khoa_cua_tenant_KHONG_liet_ke_duoc_tenant_khac(kho_hai_tenant: KhoTep):
    """Liệt kê cũng phải chặn, không chỉ đọc.

    Danh sách đường dẫn của workspace khác đã là rò rỉ: tên tệp mang tên dự án,
    và số lần publish nói khách kia hoạt động mạnh cỡ nào.
    """
    with pytest.raises(ClientError):
        await kho_hai_tenant.liet_ke("tenants/sunrise/")


async def test_khoa_cua_tenant_KHONG_ghi_duoc_sang_tenant_khac(kho_hai_tenant: KhoTep):
    with pytest.raises(ClientError):
        await kho_hai_tenant.ghi("tenants/sunrise/LIVE", b'{"version": 666}')
