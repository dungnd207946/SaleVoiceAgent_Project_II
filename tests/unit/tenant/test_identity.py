"""`identity.py` — chỉ còn validate hình dạng tenant id + slugify.

Khái niệm org đã bỏ 2026-08-15. Bản cũ canh `org_<rand8>_<slug>`: `new_org_id`,
`new_tenant_id`, `org_of`, `is_valid_org_id`. Scheme đó chưa bao giờ nằm trên
đường serving — id thật do Portal sinh là `slug(tên)` + hậu tố `_2`..`_50`.
"""

import noble_agent.tenant.identity as idy


def test_khong_con_khai_niem_org():
    """Nếu ai đó dựng lại một trong bốn hàm này, test đỏ trước khi nó kịp lan ra."""
    for ten in ("ORG_RE", "is_valid_org_id", "new_org_id", "org_of", "new_tenant_id"):
        assert not hasattr(idy, ten), f"{ten} còn sót"


def test_tenant_id_that_cua_portal_la_hop_le():
    """Đúng những id Portal sinh ra — `slug_tenant()` + hậu tố trùng."""
    for tid in ("noble", "anphu", "bao-ngoc", "san_dong_nam", "ws_test_2"):
        assert idy.is_valid_tenant_id(tid), tid


def test_ky_tu_dau_phai_la_chu_hoac_so():
    """Migration 0911 nới charset cho gạch ngang nhưng CỐ Ý không nới vị trí đầu."""
    for tid in ("-noble", "_noble", "", "Noble", "có dấu"):
        assert not idy.is_valid_tenant_id(tid), tid


def test_slugify_fold_dau_va_khong_bao_gio_rong():
    assert idy.slugify("Sàn Đông Nam") == "s-n-ng-nam"
    assert idy.slugify("  ") == "t"
    assert idy.slugify("!!!") == "t"
