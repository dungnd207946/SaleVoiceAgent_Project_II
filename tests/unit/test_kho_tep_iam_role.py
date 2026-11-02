"""S3 ở production xác thực bằng IAM role, không bằng khoá trong env.

Cách hỏng được canh: botocore nhận cả chuỗi rỗng và dựng credential rỗng, nên IAM
role không bao giờ được hỏi tới và mọi lời gọi S3 trả 403 — trong khi cấu hình trông
đúng (deploy/README.md §7.2 dặn để trống hai biến đó ở prod).
"""

from portal.core.storage import KhoTep


def test_khoa_rong_thi_khong_truyen_credential_xuong_botocore():
    kho = KhoTep(endpoint_url=None, bucket="odyssey", access_key="", secret_key="", region="ap-southeast-1")

    assert "aws_access_key_id" not in kho._cau_hinh
    assert "aws_secret_access_key" not in kho._cau_hinh
    assert kho._cau_hinh["region_name"] == "ap-southeast-1"


def test_khoa_co_gia_tri_thi_van_truyen_xuong():
    """Dev/MinIO: có khoá thì phải dùng đúng khoá đó, không rơi về IAM role."""
    kho = KhoTep(
        endpoint_url="http://localhost:9002",
        bucket="odyssey",
        access_key="minioadmin",
        secret_key="minioadmin",
    )

    assert kho._cau_hinh["aws_access_key_id"] == "minioadmin"
    assert kho._cau_hinh["aws_secret_access_key"] == "minioadmin"


def test_mot_nua_khoa_cung_khong_duoc_truyen():
    """Cấu hình nửa vời không được biến thành credential nửa vời."""
    kho = KhoTep(endpoint_url=None, bucket="odyssey", access_key="AKIA...", secret_key="")

    assert "aws_access_key_id" not in kho._cau_hinh
    assert "aws_secret_access_key" not in kho._cau_hinh
