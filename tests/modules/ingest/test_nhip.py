"""Giới hạn tốc độ theo token — §8 mục 2.

Token nạp nằm trong hệ thống BÊN THỨ BA: mình không xem được cron của họ và không
sửa được vòng lặp của họ. Bộ bài này canh bốn tính chất, và ba trong bốn là về
việc KHÔNG chặn nhầm — một giới hạn chặn nhầm sẽ bị nới ra rồi bỏ hẳn.
"""

import pytest

from portal.api.loi import LoiPortal
from portal.modules.ingest import bi_mat, nhip, service
from portal.modules.ingest.contracts import LINH_VUC

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _don_nhip(redis_client):
    """Bộ đếm sống 60–3600 giây, dài hơn hẳn một lượt chạy test.

    Không dọn thì bài sau thừa hưởng bộ đếm của bài trước và đỏ TUỲ THỨ TỰ CHẠY —
    cùng lớp lỗi mà `conftest.py` cạnh bên đã cảnh báo cho `tenant_data`.
    """
    async for k in redis_client.scan_iter(f"{nhip.TIEN_TO}*"):
        await redis_client.delete(k)
    yield
    async for k in redis_client.scan_iter(f"{nhip.TIEN_TO}*"):
        await redis_client.delete(k)


async def _thu(api_pool, redis_client, tho: str, *, so_lan: int, cua: str = nhip.CUA_EVENTS):
    return await service.xac_thuc(
        api_pool, f"Bearer {tho}", vertical=LINH_VUC, redis=redis_client, cua=cua, so_lan=so_lan, giay=60
    )


async def test_duoi_tran_thi_qua_het(api_pool, redis_client, hai_tenant):
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "nhip", "u1")
    for i in range(5):
        assert await _thu(api_pool, redis_client, t.token, so_lan=5) is not None, f"lượt {i + 1}"


async def test_vuot_tran_nem_429_chu_khong_401(api_pool, redis_client, hai_tenant):
    """⚠️ `429` và `401` phải TÁCH BẠCH.

    `401` nghĩa là «đổi token đi», `429` nghĩa là «token đúng rồi, chậm lại». Gộp
    chúng là đẩy một dev đang bị chặn nhịp đi phát lại token — thao tác vô ích, và
    họ sẽ lặp lại nó mỗi lần gặp.
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "nhip", "u1")
    for _ in range(3):
        await _thu(api_pool, redis_client, t.token, so_lan=3)

    with pytest.raises(LoiPortal) as e:
        await _thu(api_pool, redis_client, t.token, so_lan=3)
    assert e.value.http == 429
    assert e.value.ma == "RATE_LIMITED"
    assert "3" in e.value.thong_diep, "ngưỡng phải nằm trong câu — dev bên khách cần con số để sửa"


async def test_hai_token_dem_rieng(api_pool, redis_client, hai_tenant):
    """Một khách đẩy hỏng KHÔNG được làm khách khác bị chặn.

    Đếm chung là biến một giới hạn bảo vệ thành một đường DoS xuyên tenant: ai
    cũng đánh sập được đường nạp của mọi người bằng chính token của mình.
    """
    a, b = hai_tenant
    ta = await service.tao_token(api_pool, a, "cua A", "u1")
    tb = await service.tao_token(api_pool, b, "cua B", "u2")

    for _ in range(3):
        await _thu(api_pool, redis_client, ta.token, so_lan=3)
    with pytest.raises(LoiPortal):
        await _thu(api_pool, redis_client, ta.token, so_lan=3)

    assert await _thu(api_pool, redis_client, tb.token, so_lan=3) is not None, "token B phải còn nguyên hạn mức"


async def test_hai_cua_dem_rieng(api_pool, redis_client, hai_tenant):
    """`/events` và `/manifest` có hạn mức riêng.

    Chung bộ đếm thì một lượt nạp bình thường (nhịp cao, hợp lệ) sẽ ăn hết hạn mức
    của đối soát — và đối soát là thứ chỉ chạy mỗi đêm, tức nó mất lượt mà không ai
    thấy cho tới khi cần.
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "nhip", "u1")
    for _ in range(3):
        await _thu(api_pool, redis_client, t.token, so_lan=3, cua=nhip.CUA_EVENTS)
    with pytest.raises(LoiPortal):
        await _thu(api_pool, redis_client, t.token, so_lan=3, cua=nhip.CUA_EVENTS)

    assert await _thu(api_pool, redis_client, t.token, so_lan=3, cua=nhip.CUA_MANIFEST) is not None, (
        "cửa manifest phải còn nguyên hạn mức"
    )


async def test_dem_theo_BAM_khong_phai_chuoi_tho(api_pool, redis_client, hai_tenant):
    """Redis không phải chỗ cho bí mật đi qua — kể cả trong TÊN key."""
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "nhip", "u1")
    await _thu(api_pool, redis_client, t.token, so_lan=5)

    keys = [k async for k in redis_client.scan_iter(f"{nhip.TIEN_TO}*")]
    assert keys, "phải có bộ đếm"
    hop = "".join(k if isinstance(k, str) else k.decode() for k in keys)
    assert t.token not in hop, "chuỗi thô lọt vào tên key Redis"
    assert bi_mat.bam(t.token) in hop


async def test_token_sai_van_bi_dem(api_pool, redis_client, hai_tenant):
    """Nhịp kiểm TRƯỚC khi tra DB, nên token BỊA cũng ăn hạn mức.

    Đó là chủ đích: không có nó thì một máy dò token bắt portal chạy một truy vấn
    cho mỗi lần đoán, và phép kiểm nhịp lại thành thứ chỉ đếm sau khi hại đã xảy
    ra.
    """
    for _ in range(3):
        assert await _thu(api_pool, redis_client, "ody_in_bia_dat", so_lan=3) is None
    with pytest.raises(LoiPortal) as e:
        await _thu(api_pool, redis_client, "ody_in_bia_dat", so_lan=3)
    assert e.value.http == 429


async def test_khong_co_token_thi_khong_dem(api_pool, redis_client, hai_tenant):
    """Request không kèm token không có gì để quy trách nhiệm ⇒ không khoá nào để
    đếm. Nó trả `None` (401) chứ không bao giờ 429 — chặn dạng đó là việc của tầng
    vào, không phải tầng ứng dụng. Ghi ra để không ai tưởng đây là chỗ bịt."""
    for xau in (None, "", "Bearer ", "Basic gi_do"):
        assert (
            await service.xac_thuc(
                api_pool, xau, vertical=LINH_VUC, redis=redis_client, cua=nhip.CUA_EVENTS, so_lan=1, giay=60
            )
            is None
        )
    assert [k async for k in redis_client.scan_iter(f"{nhip.TIEN_TO}*")] == []


async def test_bo_dem_mat_han_thi_duoc_va_lai(redis_client):
    """Bộ đếm không có TTL là token bị chặn VĨNH VIỄN.

    Xảy ra khi một tiến trình chết đúng giữa `incr` và `expire`. Không có vế vá
    thì cách khỏi duy nhất là ai đó tìm ra một key trong Redis — mà không ai biết
    để đi tìm.
    """
    key = f"{nhip.TIEN_TO}{nhip.CUA_EVENTS}:bam_gia"
    await redis_client.set(key, 1)  # cố ý KHÔNG đặt hạn
    assert await redis_client.ttl(key) == -1

    await nhip.cho_qua(redis_client, bam_token="bam_gia", cua=nhip.CUA_EVENTS, so_lan=10, giay=60)
    assert await redis_client.ttl(key) > 0, "phải vá lại hạn cho bộ đếm mồ côi"


async def test_429_mang_header_retry_after(api_pool, redis_client, hai_tenant):
    """Backoff logic của adapter đọc HEADER, không parse câu tiếng Việt.

    Số giây vẫn nằm trong câu chữ (cho người đọc), nhưng máy thì đọc
    `Retry-After` — chuẩn HTTP mà mọi thư viện retry đều hiểu sẵn.
    """
    a, _ = hai_tenant
    t = await service.tao_token(api_pool, a, "nhip", "u1")
    for _ in range(2):
        await _thu(api_pool, redis_client, t.token, so_lan=2)

    with pytest.raises(LoiPortal) as e:
        await _thu(api_pool, redis_client, t.token, so_lan=2)
    retry = e.value.headers.get("Retry-After", "")
    assert retry.isdigit() and 1 <= int(retry) <= 60, f"Retry-After phải là số giây còn lại, nhận {retry!r}"
