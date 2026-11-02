"""Token đẩy dữ liệu — vòng đời, xác thực, và cách ly.

`control.ingest_tokens` KHÔNG có RLS (schema `control` chưa từng có). Thứ duy nhất
ngăn tenant A chạm token của tenant B là vị từ `tenant_id = $n` mà chính câu SQL
mang theo. Nên phần lớn file này là bài canh đúng vị từ đó.
"""

import json

import pytest

from portal.modules.ingest import bi_mat, nhip, repo, router, service
from portal.modules.ingest.contracts import LINH_VUC

pytestmark = pytest.mark.integration

_NHIP = {"cua": nhip.CUA_EVENTS, "so_lan": 1000, "giay": 60}
"""Nhịp rộng có chủ ý: các bài ở đây kiểm XÁC THỰC, không kiểm nhịp.

Để mặc định thì một bài gọi `xac_thuc` nhiều lần sẽ đỏ vì `429` — và nó đỏ ở một
assert nói về token, che mất việc token vẫn đúng. Nhịp có bộ bài riêng ở
`test_nhip.py`.
"""


async def test_tao_roi_liet_ke_thay_chuoi_tho(api_pool, hai_tenant):
    """Khác `agent_keys` bản đầu (chỉ hiện một lần): giao diện bày token tại chỗ
    trong bảng, che sẵn, bấm con mắt là mở — nên `liet_ke` phải trả chuỗi thô."""
    a, _ = hai_tenant
    moi = await service.tao_token(api_pool, a, "ERP đẩy quỹ căn", "u1")
    assert moi.token.startswith(bi_mat.TIEN_TO)

    tq = await service.tong_quan(api_pool, a, diem_nap="x", docs_url="y")
    assert [(t.label, t.token) for t in tq.tokens] == [("ERP đẩy quỹ căn", moi.token)]


async def test_token_cua_tenant_khac_khong_liet_ke_lan(api_pool, hai_tenant):
    a, b = hai_tenant
    await service.tao_token(api_pool, a, "của A", "u1")
    await service.tao_token(api_pool, b, "của B", "u2")

    assert [t.label for t in (await service.tong_quan(api_pool, a, diem_nap="x", docs_url="y")).tokens] == ["của A"]
    assert [t.label for t in (await service.tong_quan(api_pool, b, diem_nap="x", docs_url="y")).tokens] == ["của B"]


async def test_khong_xoa_duoc_token_cua_tenant_khac(api_pool, hai_tenant):
    """`id` là `bigserial` — ĐOÁN ĐƯỢC. Thiếu `tenant_id` trong `WHERE` thì một
    vòng lặp id là xoá sạch token của mọi khách hàng."""
    a, b = hai_tenant
    cua_b = await service.tao_token(api_pool, b, "của B", "u2")

    assert await service.xoa_token(api_pool, a, cua_b.id) is False
    con = await service.tong_quan(api_pool, b, diem_nap="x", docs_url="y")
    assert [t.id for t in con.tokens] == [cua_b.id], "token của B bị tenant A xoá mất"


async def test_xoa_la_xoa_han_khong_de_lai_hang_vo_hieu(api_pool, hai_tenant):
    """Không tồn tại trạng thái «đã thu hồi». Một hàng vô hiệu hoặc còn giữ chuỗi
    thô (bí mật vô dụng nằm chờ rò) hoặc rỗng (không trả lời câu hỏi nào)."""
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "bỏ đi", "u1")
    assert await service.xoa_token(api_pool, a, t.id) is True
    assert (await service.tong_quan(api_pool, a, diem_nap="x", docs_url="y")).tokens == []


async def test_xac_thuc_tra_dung_tenant_va_tu_choi_moi_dang_sai(api_pool, redis_client, hai_tenant):
    a, b = hai_tenant
    cua_a = await service.tao_token(api_pool, a, "của A", "u1")
    cua_b = await service.tao_token(api_pool, b, "của B", "u2")

    assert (await service.xac_thuc(api_pool, f"Bearer {cua_a.token}", vertical=LINH_VUC, redis=redis_client, **_NHIP))[
        "tenant_id"
    ] == a
    assert (await service.xac_thuc(api_pool, f"Bearer {cua_b.token}", vertical=LINH_VUC, redis=redis_client, **_NHIP))[
        "tenant_id"
    ] == b

    # Bốn dạng sai, tất cả cùng một đáp án — phân biệt chúng là cho không một máy
    # dò biết chuỗi nào tồn tại.
    for xau in (None, "", "Bearer ", cua_a.token, f"Basic {cua_a.token}", "Bearer ody_in_bia"):
        assert await service.xac_thuc(api_pool, xau, vertical=LINH_VUC, redis=redis_client, **_NHIP) is None, xau


async def test_token_lech_linh_vuc_bi_tu_choi(api_pool, redis_client, hai_tenant):
    """Token hợp lệ + endpoint của lĩnh vực KHÁC ⇒ từ chối.

    Đây là bài canh một lỗ hổng THẬT đã tồn tại tới 2026-08-14: `repo.tra_token`
    vẫn `SELECT vertical` nhưng không ai đọc nó, nên `/ingest/<bất kỳ>/v1/events`
    nhận mọi token còn sống. Nó vô hại chỉ vì `CHECK (vertical IN ('realestate'))`
    khiến giá trị thứ hai chưa tồn tại — không phải vì code đúng.

    Test truyền lĩnh vực của ENDPOINT chứ không tạo token lĩnh vực khác: CHECK
    không cho tạo, mà chờ tới ngày có `finance` mới viết bài canh này thì bài canh
    ra đời SAU lỗ hổng nó phải chặn. Ở đây `xac_thuc` đang bị hỏi đúng câu mà
    router lĩnh vực thứ hai sẽ hỏi.
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "của A", "u1")

    assert (
        await service.xac_thuc(api_pool, f"Bearer {t.token}", vertical=LINH_VUC, redis=redis_client, **_NHIP)
        is not None
    )
    assert (
        await service.xac_thuc(api_pool, f"Bearer {t.token}", vertical="finance", redis=redis_client, **_NHIP) is None
    )
    assert await service.xac_thuc(api_pool, f"Bearer {t.token}", vertical="", redis=redis_client, **_NHIP) is None


def test_hai_endpoint_nap_deu_truyen_dung_linh_vuc_cua_chinh_no():
    """Cổng quét TĨNH: mọi lời gọi `xac_thuc` phải khai `vertical=`.

    Phép kiểm ở `xac_thuc` chỉ có giá trị bằng đúng số chỗ gọi nhớ truyền tham số.
    Tham số là bắt buộc (không mặc định) nên quên hẳn thì `TypeError` — nhưng
    truyền một hằng lạ thì không gì kêu, và đó là dạng sai của một router lĩnh vực
    thứ hai viết bằng copy-paste.
    """
    import ast
    import pathlib

    nguon = pathlib.Path(router.__file__).read_text(encoding="utf-8")
    goi = [
        n
        for n in ast.walk(ast.parse(nguon))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "xac_thuc"
    ]
    assert len(goi) == 3, f"router.py có {len(goi)} lời gọi xac_thuc, chờ 3 (events + manifest + whoami)"
    for n in goi:
        kw = {k.arg: k for k in n.keywords}
        assert "vertical" in kw, f"lời gọi xac_thuc ở dòng {n.lineno} thiếu vertical="
        gt = kw["vertical"].value
        assert isinstance(gt, ast.Attribute) and gt.attr == "LINH_VUC", (
            f"dòng {n.lineno}: vertical phải là hằng LINH_VUC của chính module, "
            "không phải chuỗi viết tay — chuỗi viết tay lệch khỏi prefix router mà không ai thấy"
        )


async def test_token_da_xoa_thi_het_xac_thuc_duoc(api_pool, redis_client, hai_tenant):
    """Xoá phải có hiệu lực NGAY ở đường nạp, không chỉ trên giao diện."""
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "sắp xoá", "u1")
    assert (
        await service.xac_thuc(api_pool, f"Bearer {t.token}", vertical=LINH_VUC, redis=redis_client, **_NHIP)
        is not None
    )
    await service.xoa_token(api_pool, a, t.id)
    assert await service.xac_thuc(api_pool, f"Bearer {t.token}", vertical=LINH_VUC, redis=redis_client, **_NHIP) is None


async def test_trung_nhan_trong_cung_tenant_bi_chan(api_pool, hai_tenant):
    """Nhãn là thứ DUY NHẤT phân biệt hai token trên một bảng hai cột. Cho trùng
    tên là cho tạo ra một màn hình không dùng được."""
    import asyncpg

    a, b = hai_tenant
    await service.tao_token(api_pool, a, "ERP", "u1")
    with pytest.raises(asyncpg.UniqueViolationError):
        await service.tao_token(api_pool, a, "ERP", "u1")
    # Nhưng tenant KHÁC dùng lại tên đó thì bình thường — nhãn là chuyện nội bộ
    # của mỗi workspace.
    await service.tao_token(api_pool, b, "ERP", "u2")


def test_bam_on_dinh_va_tien_to_khac_khoa_agent():
    """Tiền tố khác `ody_ag_` có chủ đích: hai chuỗi này mở hai thứ hoàn toàn khác
    nhau, và người vận hành dán nhầm thì thông điệp lỗi phải nói được điều đó."""
    tho, bam = bi_mat.sinh_token()
    assert tho.startswith("ody_in_") and not tho.startswith("ody_ag_")
    assert bi_mat.bam(tho) == bam
    assert bi_mat.sinh_token()[0] != tho


# ─── Vòng đời token vào Nhật ký — §8 mục 5 ──────────────────────────────────
#
# `TokenOut` khai «siêu dữ liệu kiểm toán là việc của Nhật ký» và
# `router_tenant.xoa_token` khai «ai xoá token nào là việc của Nhật ký». Cả hai
# câu RỖNG cho tới 2026-08-15 — module chưa từng ghi một dòng nào cho vòng đời
# token. Ba bài dưới là thứ giữ chúng khỏi rỗng lại.


async def _dong_nhat_ky(pool, tenant_id: str, hanh_dong: str):
    return await pool.fetch(
        "SELECT actor, chi_tiet FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = $2",
        tenant_id,
        hanh_dong,
    )


async def test_tao_token_ghi_nhat_ky(api_pool, pool, hai_tenant):
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "ERP đêm", "u1")

    hang = await _dong_nhat_ky(pool, a, "ingest.token_tao")
    assert len(hang) == 1
    ct = json.loads(hang[0]["chi_tiet"]) if isinstance(hang[0]["chi_tiet"], str) else hang[0]["chi_tiet"]
    assert hang[0]["actor"] == "u1"
    assert ct == {"id": t.id, "label": "ERP đêm"}


async def test_xoa_token_ghi_nhat_ky_kem_NHAN(api_pool, pool, hai_tenant):
    """Nhãn phải nằm trong `chi_tiet`, vì sau khi xoá thì hàng không còn để tra.

    Ghi mỗi `id` là để lại một dòng nhật ký không trả lời được câu hỏi mà người ta
    mở nhật ký ra để hỏi: «token NÀO vừa bị xoá».
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "sắp xoá", "u1")
    assert await service.xoa_token(api_pool, a, t.id, "u2") is True

    hang = await _dong_nhat_ky(pool, a, "ingest.token_xoa")
    assert len(hang) == 1
    ct = json.loads(hang[0]["chi_tiet"]) if isinstance(hang[0]["chi_tiet"], str) else hang[0]["chi_tiet"]
    assert hang[0]["actor"] == "u2"
    assert ct == {"id": t.id, "label": "sắp xoá"}


async def test_xoa_hut_KHONG_ghi_nhat_ky(api_pool, pool, hai_tenant):
    """Id không tồn tại (hoặc của tenant khác) ⇒ không có sự kiện nào xảy ra.

    Ghi cho nó là dựng ra một dòng nhật ký kể một việc chưa từng diễn ra — và với
    id của tenant khác, đó còn là rò rỉ: dòng đó khẳng định id ấy tồn tại.
    """
    a, b = hai_tenant
    cua_b = await service.tao_token(api_pool, b, "của B", "u2")

    assert await service.xoa_token(api_pool, a, cua_b.id, "u1") is False
    assert await service.xoa_token(api_pool, a, 999_999, "u1") is False
    assert await _dong_nhat_ky(pool, a, "ingest.token_xoa") == []


async def test_chuoi_tho_KHONG_vao_nhat_ky(api_pool, pool, hai_tenant):
    """Nhật ký có nhiều người đọc hơn bảng token."""
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "bí mật", "u1")
    await service.xoa_token(api_pool, a, t.id, "u1")

    moi = await pool.fetch(
        "SELECT chi_tiet::text AS ct FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong LIKE 'ingest.token_%'",
        a,
    )
    assert moi
    assert all(t.token not in r["ct"] for r in moi)


def test_cot_last_used_at_da_bi_bo():
    """`repo.cham_da_dung` là code chết từ `0927` nên cột luôn NULL, và NULL ở đó
    đọc thành «token này chưa ai dùng» — sai, và sai theo hướng mời người ta xoá
    một token đang chạy. Bỏ ở `0930`; bài này chặn việc nó quay lại mà không có
    đường ghi."""
    assert not hasattr(repo, "cham_da_dung"), "hàm chết đã bỏ ở 0930"


# ─── Mã hoá at-rest — §8 mục 3 ──────────────────────────────────────────────


async def test_cot_token_trong_DB_khong_con_chuoi_tho(api_pool, pool, hai_tenant):
    """⚠️ BÀI CANH CHÍNH của cả bản vá, và nó đọc THẲNG cột bằng `pool` (migrator).

    Đi qua `service`/`repo` thì chỉ chứng minh vòng mã hoá–giải mã khớp nhau, tức
    một hàm `ma_hoa` trả nguyên văn cũng xanh. Thứ phải khẳng định là **thứ nằm
    trên đĩa**, và chỗ duy nhất nhìn thấy nó là một câu SELECT thô.
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "bí mật", "u1")

    luu = await pool.fetchval("SELECT token FROM control.ingest_tokens WHERE id = $1", t.id)
    assert luu != t.token, "cột vẫn là chuỗi thô"
    assert t.token not in luu
    assert luu.startswith("enc.v1."), luu[:20]


async def test_doc_lai_van_ra_chuoi_tho(api_pool, hai_tenant):
    """Giao diện bấm con mắt là phải thấy khoá thật, không phải `enc.v1.…`."""
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "xem lại", "u1")

    tq = await service.tong_quan(api_pool, a, diem_nap="x", docs_url="y")
    assert [x.token for x in tq.tokens] == [t.token]
    assert t.token.startswith("ody_in_")


async def test_hang_CU_chua_ma_hoa_van_doc_duoc(api_pool, pool, hai_tenant):
    """Deploy code TRƯỚC, backfill SAU — nên bản mới phải đọc được hàng plaintext.

    Bỏ tính chất này là buộc hai bước phải xảy ra cùng một giây, và trong khoảng
    lệch thì hoặc token cũ không đọc được, hoặc người dùng nhận `enc.v1.…`.
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "giả cổ", "u1")
    await pool.execute("UPDATE control.ingest_tokens SET token = $2 WHERE id = $1", t.id, "ody_in_plaintext_cu")

    tq = await service.tong_quan(api_pool, a, diem_nap="x", docs_url="y")
    assert [x.token for x in tq.tokens] == ["ody_in_plaintext_cu"]


async def test_xac_thuc_KHONG_di_qua_cot_ma_hoa(api_pool, redis_client, hai_tenant, pool):
    """Đường xác thực tra `token_sha256`, không tra cột đã mã hoá.

    Đó là điều làm bản vá này rẻ và ít rủi ro: mã hoá cột HIỂN THỊ không chạm một
    dòng nào của đường đăng nhập. Bài này đỏ nếu ai đó «dọn dẹp» bằng cách cho
    `tra_token` so trực tiếp cột `token`.
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "xác thực", "u1")
    assert (await service.xac_thuc(api_pool, f"Bearer {t.token}", vertical=LINH_VUC, redis=redis_client, **_NHIP))[
        "tenant_id"
    ] == a

    # Đập nát cột hiển thị — xác thực vẫn phải chạy, vì nó không đọc cột này.
    await pool.execute("UPDATE control.ingest_tokens SET token = 'rac' WHERE id = $1", t.id)
    assert (
        await service.xac_thuc(api_pool, f"Bearer {t.token}", vertical=LINH_VUC, redis=redis_client, **_NHIP)
    ) is not None


async def test_khong_cot_text_nao_cua_ingest_tokens_chua_chuoi_tho(api_pool, pool, hai_tenant):
    """Quét ĐỘNG mọi cột text của `control.ingest_tokens`.

    Bài `test_cot_token_trong_DB_khong_con_chuoi_tho` ở trên chỉ canh ĐÚNG cột
    `token`. Bài này bắt được người thêm `token_backup` hay `token_hien_thi` sáu
    tháng nữa — cùng khuôn `enrollment/test_runtime_credentials.py::
    test_khong_cot_text_nao_chua_bi_mat`, vốn có ngoại lệ cho `agent_keys.api_key`
    tới 2026-08-15 và nay đã rỗng.

    KHÔNG có danh sách ngoại lệ ở đây, và đừng thêm: đã có `bi_mat_luu.ma_hoa()`
    thì câu trả lời đúng cho một cột chứa bí mật là mã hoá nó.
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "quét động", "u1")

    cot = await pool.fetch(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'control' AND table_name = 'ingest_tokens'
              AND data_type IN ('text', 'character varying')"""
    )
    assert cot, "không quét được cột nào — truy vấn catalog sai, không phải bảng sạch"

    for r in cot:
        hit = await pool.fetchval(
            f'SELECT count(*) FROM control.ingest_tokens WHERE "{r["column_name"]}" = $1',  # noqa: S608
            t.token,
        )
        assert hit == 0, f"chuỗi thô rò vào control.ingest_tokens.{r['column_name']}"
