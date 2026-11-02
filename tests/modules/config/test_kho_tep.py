"""Kho tệp — seam thứ hai của M3 (Postgres là seam thứ nhất).

Chạy trên MinIO thật, không mock: cổng 2 của M3 là **thứ tự ghi** và cổng 5 là
**policy theo tiền tố**. Mock S3 nhận mọi thứ tự ghi và không biết policy là gì.
"""

import pytest

from portal.core.storage import KhongTimThay

pytestmark = pytest.mark.integration


async def test_ghi_roi_doc_lai_dung_byte(kho_tep):
    await kho_tep.ghi("tenants/anphu/LIVE", b'{"version": 1}')

    assert await kho_tep.doc("tenants/anphu/LIVE") == b'{"version": 1}'


async def test_doc_khoa_khong_ton_tai_thi_bao_loi(kho_tep):
    """Fail loud (quy ước §6.2): thiếu bundle phải nổi lên thành lỗi.

    Trả `None` hay `b""` ở đây nghĩa là agent nhận một bundle rỗng và boot với
    persona trống — hỏng im lặng, đúng thứ khó chẩn nhất.
    """
    with pytest.raises(KhongTimThay):
        await kho_tep.doc("tenants/anphu/LIVE")


async def test_co_tra_ve_false_khi_chua_ghi(kho_tep):
    assert await kho_tep.co("tenants/anphu/LIVE") is False

    await kho_tep.ghi("tenants/anphu/LIVE", b"x")

    assert await kho_tep.co("tenants/anphu/LIVE") is True


async def test_liet_ke_theo_tien_to_khong_lan_sang_tenant_khac(kho_tep):
    await kho_tep.ghi("tenants/anphu/bundles/abc/manifest.toml", b"a")
    await kho_tep.ghi("tenants/sunrise/bundles/xyz/manifest.toml", b"b")

    assert await kho_tep.liet_ke("tenants/anphu/") == ["tenants/anphu/bundles/abc/manifest.toml"]


async def test_ghi_de_cung_khoa_ra_noi_dung_moi(kho_tep):
    """Con trỏ LIVE là một object bị ghi đè mỗi lần publish — phải đọc ra bản mới.

    Đây là chỗ rollback dựa vào: ghi lại LIVE trỏ sha cũ, không render lại gì.
    """
    await kho_tep.ghi("tenants/anphu/LIVE", b'{"version": 1}')
    await kho_tep.ghi("tenants/anphu/LIVE", b'{"version": 2}')

    assert await kho_tep.doc("tenants/anphu/LIVE") == b'{"version": 2}'
