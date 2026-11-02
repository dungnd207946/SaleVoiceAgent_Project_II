"""Tài liệu OpenAPI của cổng nạp — SINH từ `HOP_DONG`, không chép tay.

Khoảng hở DX lớn nhất đo được khi đóng vai dev bên khách (2026-08-16): `data`
trong OpenAPI chỉ là `object` trần — tên trường, trường bắt buộc, giá trị enum
đều vô hình với người cầm Swagger. Mà `docsUrl` của màn quản trị lại trỏ thẳng
khách vào đúng trang đó.

Tài liệu SINH từ sổ (`HOP_DONG` + `QUAN_HE` — hai thứ đã có cổng parity với DB
thật) nên không drift được theo cách chép tay drift. Bộ bài này canh phần còn
lại: phép sinh có ĐỦ không, và văn bản sinh ra có THẬT SỰ gắn vào route không —
một `description=` bị xoá khỏi decorator là tài liệu biến mất không lỗi nào.
"""

import pytest

from portal.modules.ingest import contracts, hop_dong, tai_lieu

# ─── Phép sinh đủ — thuần, không cần Docker ──────────────────────────────────


def test_mo_ta_events_chua_moi_truong_cua_moi_thuc_the():
    van_ban = tai_lieu.mo_ta_events()
    for entity, cac_truong in hop_dong.HOP_DONG.items():
        assert f"### `{entity}`" in van_ban, f"thiếu mục cho thực thể {entity}"
        for t in cac_truong:
            assert f"`{t.ten}`" in van_ban, f"trường {entity}.{t.ten} rơi khỏi tài liệu"


def test_mo_ta_events_chua_moi_gia_tri_enum():
    """Dev bên khách sửa adapter theo danh sách giá trị — thiếu một giá trị là
    một vòng thử-sai nữa cho họ."""
    van_ban = tai_lieu.mo_ta_events()
    for cac_truong in hop_dong.HOP_DONG.values():
        for t in cac_truong:
            for gia_tri in t.gia_tri:
                assert f"`{gia_tri}`" in van_ban, f"giá trị enum {t.ten}={gia_tri} rơi khỏi tài liệu"


def test_mo_ta_events_chua_moi_khoa_cha():
    van_ban = tai_lieu.mo_ta_events()
    for entity, quan_he in hop_dong.QUAN_HE.items():
        for ten, _cha, _bat_buoc in quan_he:
            assert f"`{ten}`" in van_ban, f"khoá cha {entity}.{ten} rơi khỏi tài liệu"


def test_vi_du_events_du_nam_thuc_the_va_hop_le():
    """Ví dụ trong Swagger là thứ dev copy làm điểm xuất phát — một ví dụ trượt
    chính phép kiểm của mình là dạy họ bắt đầu từ một payload hỏng."""
    vi_du = tai_lieu.vi_du_events()
    khoi = vi_du["requestBody"]["content"]["application/json"]["examples"]
    assert set(khoi) >= set(hop_dong.HOP_DONG), "mỗi thực thể phải có một ví dụ"
    for entity in hop_dong.HOP_DONG:
        ban_ghi = khoi[entity]["value"]["records"][0]
        assert ban_ghi["entity"] == entity
        _cot, loi = hop_dong.kiem(entity, ban_ghi["data"])
        assert loi == [], f"ví dụ {entity} phải qua được kiem(): {[(e.truong, e.ly_do) for e in loi]}"


def test_mo_ta_manifest_neu_du_ba_canh_sac():
    """Ba cạnh sắc đã đo được là chỗ 8/10 adapter sẽ đứt tay: thứ tự BYTE,
    `afterExternalId` = đã GỬI, và `isLastPage` quên đặt false. Tài liệu manifest
    thiếu một trong ba là coi như chưa viết."""
    van_ban = tai_lieu.mo_ta_manifest()
    assert "thứ tự byte" in van_ban.lower()
    assert "afterExternalId" in van_ban
    assert "isLastPage" in van_ban
    assert "dryRun" in van_ban, "diễn tập an toàn là đường thoát cho cả ba cạnh sắc — phải được nhắc"


# ─── Văn bản sinh ra gắn THẬT vào route — cần app, đi đường integration ──────


@pytest.mark.integration
async def test_openapi_events_mang_tai_lieu_sinh(app_client):
    spec = (await app_client.get("/openapi.json")).json()
    duong = f"/api/v1/ingest/{contracts.LINH_VUC}/{contracts.PHIEN_BAN}/events"
    op = spec["paths"][duong]["post"]
    assert "### `unit`" in op["description"], "description sinh không gắn vào route"
    assert "productType" in op["description"]
    vi_du = op["requestBody"]["content"]["application/json"]["examples"]
    assert set(vi_du) >= set(hop_dong.HOP_DONG), "openapi_extra examples không gắn vào route"


@pytest.mark.integration
async def test_openapi_manifest_mang_tai_lieu_sinh(app_client):
    spec = (await app_client.get("/openapi.json")).json()
    op = spec["paths"]["/api/v1/ingest/realestate/v1/manifest"]["post"]
    assert "thứ tự byte" in op["description"].lower()


# ─── Swagger riêng của cổng nạp + spec tải được (2026-08-21) ─────────────────
# `docsUrl` cũ trỏ `/docs#/ingest/nap` — Swagger của CẢ portal: ở dev nó còn
# không mở được từ origin FE (vite chỉ proxy `^/api/`), và nó bày mọi endpoint
# nội bộ cho dev bên thứ ba. Nay cổng nạp tự phục vụ docs + spec CỦA RIÊNG NÓ
# dưới `/api/v1/…` — ba bài dưới canh đúng ba lời hứa đó.


def test_spec_cong_khai_chi_chua_ba_route_hop_dong():
    """Spec scoped: đủ ba route hợp đồng, KHÔNG lộ control-plane, đường dẫn
    mang tiền tố `/api/v1` đầy đủ (nó là thứ bàn giao cho khách)."""
    from portal.modules.ingest import router

    spec = router._spec_cong_khai()  # noqa: SLF001 — test nội bộ module
    goc = f"/api/v1/ingest/{contracts.LINH_VUC}/{contracts.PHIEN_BAN}"
    assert set(spec["paths"]) == {f"{goc}/events", f"{goc}/whoami", f"{goc}/manifest"}
    # Tài liệu sinh từ HOP_DONG phải gắn vào CẢ spec scoped, không chỉ spec cả app
    assert "### `unit`" in spec["paths"][f"{goc}/events"]["post"]["description"]


def test_docs_url_tra_ve_duong_scoped():
    from portal.modules.ingest import router_tenant

    assert router_tenant._docs_url().endswith(  # noqa: SLF001 — test nội bộ module
        f"/api/v1/ingest/{contracts.LINH_VUC}/{contracts.PHIEN_BAN}/docs"
    )


@pytest.mark.integration
async def test_trang_docs_va_spec_phuc_vu_that(app_client):
    """Hai endpoint sống thật qua app: trang HTML nhúng Swagger UI trỏ spec
    TƯƠNG ĐỐI (`openapi.json` — tự phân giải theo URL trang, module không phải
    biết tiền tố), spec mang `Content-Disposition` có tên tệp cho `<a download>`."""
    docs = await app_client.get("/api/v1/ingest/realestate/v1/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert "openapi.json" in docs.text

    spec = await app_client.get("/api/v1/ingest/realestate/v1/openapi.json")
    assert spec.status_code == 200
    assert "filename=" in spec.headers["content-disposition"]
    assert "/api/v1/ingest/realestate/v1/events" in spec.json()["paths"]
    # Thiếu `charset` là mojibake trên trình duyệt: Starlette chỉ tự thêm nó cho
    # media type `text/*`, và `Content-Disposition: inline` ngay trên đẩy trình
    # duyệt sang chế độ hiển thị-tệp, nơi nó sniff encoding theo locale. Mọi bài
    # đọc `.json()` vẫn xanh vì httpx decode UTF-8 bất kể header.
    assert "charset=utf-8" in spec.headers["content-type"].lower()
