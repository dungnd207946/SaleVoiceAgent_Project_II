"""Suy dẫn bí mật — HÀM THUẦN, không cần Postgres/MinIO/Qdrant.

Đây là phần dễ sai nhất của M10, cùng lý do `bundle.render()` của M3 là hàm thuần.
"""

import re

import pytest

from portal.modules.enrollment.bi_mat import LOAI_PG, LOAI_S3, bam_khoa, dan_xuat, sinh_khoa

MASTER = b"x" * 32
MASTER_KHAC = b"y" * 32


def test_tat_dinh():
    """CỐT LÕI: hai pod của cùng tenant phải suy ra CÙNG mật khẩu.

    Vỡ tính chất này thì pod voice khởi động lại sẽ đá văng pod chat — vì
    portal.current_tenant() parse tenant TỪ TÊN ROLE nên hai pod dùng chung một
    role agent_<slug>.
    """
    assert dan_xuat(LOAI_PG, "anphu", 1, MASTER) == dan_xuat(LOAI_PG, "anphu", 1, MASTER)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ((LOAI_PG, "anphu", 1), (LOAI_S3, "anphu", 1)),  # khác loại
        ((LOAI_PG, "anphu", 1), (LOAI_PG, "bcland", 1)),  # khác tenant
        ((LOAI_PG, "anphu", 1), (LOAI_PG, "anphu", 2)),  # khác version = xoay khoá
    ],
)
def test_doi_dau_vao_thi_doi_ket_qua(a, b):
    assert dan_xuat(*a, MASTER) != dan_xuat(*b, MASTER)


def test_khac_master_khac_ket_qua():
    assert dan_xuat(LOAI_PG, "anphu", 1, MASTER) != dan_xuat(LOAI_PG, "anphu", 1, MASTER_KHAC)


def test_dinh_dang_dung_duoc_lam_mat_khau():
    """base64url không padding: an toàn trong DSN, policy JSON, và shell."""
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", dan_xuat(LOAI_PG, "anphu", 1, MASTER))


def test_khong_hai_dau_vao_nao_va_nhau():
    """Không hai `(loai, tenant, version)` khác nhau nào cho ra cùng bí mật.

    Danh sách cố ý có tenant_id chứa dấu hai chấm và tenant_id là tiền tố của
    nhau: nối chuỗi ngây thơ f"{loai}:{tenant}:{ver}" làm ('a:1', 2) và ('a', ...)
    va vào không gian của nhau, tức hai tenant khác nhau suy ra cùng mật khẩu.
    Độ dài có tiền tố loại hẳn khả năng đó.

    Hôm nay regex của `dat_mat_khau_agent()` chặn tenant_id có dấu hai chấm —
    nhưng hàm thuần không được dựa vào một ràng buộc nằm ở file khác.
    """
    dau_vao = [
        (loai, tenant, version)
        for loai in (LOAI_PG, LOAI_S3)
        for tenant in ("a", "ab", "a:1", "a:12", "a1", "")
        for version in (1, 2, 12)
    ]
    ra = {dan_xuat(*d, MASTER) for d in dau_vao}
    assert len(ra) == len(dau_vao), "có hai đầu vào khác nhau cho cùng một bí mật"


def test_master_qua_ngan_bi_tu_choi():
    with pytest.raises(ValueError, match="32 byte"):
        dan_xuat(LOAI_PG, "anphu", 1, b"ngan")


def test_loai_la_bi_tu_choi():
    """Gõ sai 'pgg' không được âm thầm sinh ra một mật khẩu hợp lệ khác."""
    with pytest.raises(ValueError, match="loai"):
        dan_xuat("pgg", "anphu", 1, MASTER)


def test_sinh_khoa_dung_dinh_dang():
    tho, sha, prefix = sinh_khoa()
    assert tho.startswith("ody_ag_")
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", tho.removeprefix("ody_ag_"))
    assert sha == bam_khoa(tho)
    assert prefix == tho[:12]
    assert prefix in tho


def test_sinh_khoa_khong_lap():
    """256 bit entropy — 500 lần sinh không được trùng."""
    assert len({sinh_khoa()[0] for _ in range(500)}) == 500
