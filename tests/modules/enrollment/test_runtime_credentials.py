"""`/runtime-credentials` end-to-end trên hạ tầng thật — sáu cổng của M10.

Pool là `portal_api`, đúng role production dùng. Nếu dùng owner thì
`dat_mat_khau_agent()` chạy được nhờ CREATEROLE của owner, và ta sẽ không phát
hiện ra runtime thật không có nó.
"""

import asyncpg
import pytest

from portal.api.loi import LoiPortal
from portal.modules.enrollment import repo, service
from tests.conftest import dsn_as
from tests.modules.enrollment.conftest import MASTER_KEY


async def _cap(api_pool, ha_tang, tenant_id: str, label: str = ""):
    return await service.cap_phat(api_pool, ha_tang, tenant_id, label, "platform_admin")


def _dsn(pg_dsn: str, ra) -> str:
    """Ghép DSN nối được từ `postgres_role`/`postgres_password` của response.

    Response từ `0917`+ KHÔNG còn `postgres_dsn` gộp sẵn (cố ý — xem
    `contracts.RuntimeCredentialsOut`); host/port/database lấy từ `pg_dsn` của
    CHÍNH TEST (giống nhau cho mọi role trên cùng cluster test), chỉ role/password
    đổi theo response."""
    return dsn_as(pg_dsn, ra.postgres_role, ra.postgres_password.get_secret_value())


# ─── Cổng 1: cách ly xuyên tenant qua đường M10 vừa mở ──────────────────────


async def test_dsn_cua_A_khong_thay_du_an_cua_B(api_pool, redis_client, ha_tang, hai_tenant, pg_dsn):
    """⚠️ Cổng này CHỈ CÓ NGHĨA khi CẢ HAI tenant có dữ liệu. Với bảng rỗng nó vẫn
    xanh — 0 hàng của B là đúng ngay cả khi A cũng 0 hàng. Fixture seed cả hai."""
    a, b = hai_tenant
    khoa = await _cap(api_pool, ha_tang, a)
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    c = await asyncpg.connect(_dsn(pg_dsn, ra))
    try:
        codes = {r["project_code"] for r in await c.fetch("SELECT project_code FROM tenant_data.projects")}
    finally:
        await c.close()

    assert f"DA-{a}" in codes, "phải thấy dữ liệu của chính mình — nếu không, cổng này vô nghĩa"
    assert f"DA-{b}" not in codes
    assert codes == {f"DA-{a}"}


async def test_agent_doc_duoc_tenant_data_nhung_khong_cham_duoc_control(
    api_pool, redis_client, ha_tang, hai_tenant, pg_dsn
):
    """G-6 (đã đổi từ `0917`): agent đọc thẳng `tenant_data.*` — KHÔNG còn qua view
    `agent_api` (đã bỏ). Cách ly còn lại dựa vào RLS FORCE (`0913`), không phải
    "zero quyền trên bảng gốc" như thiết kế `0005` ban đầu. `control.*` thì vẫn
    chặn tuyệt đối: PUBLIC đã bị revoke (`0917`), `agent_all` chỉ còn
    `agent_heartbeats`."""
    khoa = await _cap(api_pool, ha_tang, hai_tenant[0])
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    c = await asyncpg.connect(_dsn(pg_dsn, ra))
    try:
        assert await c.fetch("SELECT * FROM tenant_data.projects") is not None
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.fetch("SELECT * FROM control.agent_keys")
    finally:
        await c.close()


# ─── Cổng 2: thu hồi phải im lặng như khoá không tồn tại ────────────────────


async def test_khoa_thu_hoi_va_khoa_khong_co_cung_cau_chu(api_pool, redis_client, ha_tang, hai_tenant):
    """Khác `message` là máy dò biết khoá nào từng có thật."""
    khoa = await _cap(api_pool, ha_tang, hai_tenant[0])
    await repo.thu_hoi_khoa(api_pool, khoa.id)

    with pytest.raises(LoiPortal) as thu_hoi:
        await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)
    with pytest.raises(LoiPortal) as khong_co:
        await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, "ody_ag_khong-co-that")

    assert thu_hoi.value.ma == khong_co.value.ma == "INVALID_AGENT_KEY"
    assert thu_hoi.value.thong_diep == khong_co.value.thong_diep
    assert thu_hoi.value.http == 401


# ─── Cổng 3: hai pod cùng tenant nhận cùng mật khẩu ────────────────────────


async def test_pod_chat_va_voice_khong_da_nhau(api_pool, redis_client, ha_tang, hai_tenant, pg_dsn):
    """Chúng dùng chung role agent_<slug> vì current_tenant() parse tenant từ tên
    role. Mật khẩu khác nhau = pod khởi động sau đá văng pod trước."""
    a = hai_tenant[0]
    k1 = await _cap(api_pool, ha_tang, a)
    k2 = await _cap(api_pool, ha_tang, a)

    r1 = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, k1.api_key)
    r2 = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, k2.api_key)

    assert r1.postgres_role == r2.postgres_role
    assert r1.postgres_password.get_secret_value() == r2.postgres_password.get_secret_value()
    # Hai lượt cấp phát = HAI khoá khác nhau. Trước `0940` bài này so
    # `deployment_id`; khoá không treo vào deployment nữa nên dấu hiệu "hai lượt
    # thật sự khác nhau" giờ là `agent_key_id`.
    assert r1.agent_key_id != r2.agent_key_id

    # Cả hai nối được cùng lúc — đây là điều test này thực sự bảo vệ.
    c1 = await asyncpg.connect(_dsn(pg_dsn, r1))
    c2 = await asyncpg.connect(_dsn(pg_dsn, r2))
    await c1.close()
    await c2.close()


# ─── Cổng 4: xoay bí mật có tác dụng thật ──────────────────────────────────


async def test_xoay_bi_mat_thi_mat_khau_cu_het_dung_duoc(api_pool, redis_client, ha_tang, hai_tenant, pg_dsn):
    a = hai_tenant[0]
    khoa = await _cap(api_pool, ha_tang, a)
    truoc = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    assert await service.xoay_bi_mat(api_pool, ha_tang, a, "platform_admin") == 2

    sau = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)
    assert truoc.postgres_password.get_secret_value() != sau.postgres_password.get_secret_value()

    c = await asyncpg.connect(_dsn(pg_dsn, sau))
    await c.close()
    with pytest.raises(asyncpg.InvalidPasswordError):
        await asyncpg.connect(_dsn(pg_dsn, truoc))


# ─── Cổng 5: workspace không hoạt động thì không cấp credential ─────────────


async def test_tenant_suspended_thi_403(api_pool, redis_client, ha_tang, hai_tenant, pool):
    a = hai_tenant[0]
    khoa = await _cap(api_pool, ha_tang, a)
    await pool.execute("UPDATE control.tenants SET lifecycle = 'suspended' WHERE id = $1", a)

    with pytest.raises(LoiPortal) as e:
        await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)
    assert (e.value.ma, e.value.http) == ("TENANT_SUSPENDED", 403)


# ─── Cổng 6: không bí mật nào ở trạng thái nghỉ, không bí mật nào vào log ───


_NGOAI_LE_CO_CHU_Y: set[tuple[str, str]] = set()
"""RỖNG từ 2026-08-15 — và việc nó rỗng lại là điểm của cả bản mã hoá at-rest.

Từ `0918` tới 2026-08-15 nó chứa `("agent_keys", "api_key")`: cột đó CỐ Ý lưu khoá
thô (cạnh `key_sha256` không đổi) để `/thu-agent` dựng được `<select>` chọn khoá
theo tên. Nay cột lưu ciphertext `enc.v1.…` (`core/bi_mat_luu.py`) nên cổng dưới
đây quét nó như mọi cột khác và KHÔNG tìm thấy gì — tức ngoại lệ tự hết, không phải
được tha.

⚠️ ĐỪNG thêm dòng nào vào đây để «cho qua» một cột mới chứa bí mật. Ngoại lệ trước
tồn tại vì chưa có đường mã hoá; giờ đã có, nên câu trả lời đúng cho một cột như thế
là `bi_mat_luu.ma_hoa()`, không phải một dòng ở đây."""


async def test_khong_cot_text_nao_chua_bi_mat(api_pool, ha_tang, hai_tenant, pool):
    """Quét ĐỘNG mọi cột text của hai bảng. Nó bắt được người thêm cột
    `password_cache` sáu tháng nữa — cùng hạng với cổng 5/6 của M1.

    TRỪ `_NGOAI_LE_CO_CHU_Y` — một ngoại lệ, không phải nới lỏng cổng: mọi cột
    khác (gồm `key_sha256` chính nó, và mọi cột tương lai) vẫn bị quét như cũ.
    """
    from portal.modules.enrollment.bi_mat import LOAI_PG, LOAI_S3, dan_xuat

    a = hai_tenant[0]
    khoa = await _cap(api_pool, ha_tang, a)
    master = MASTER_KEY.encode()
    bi_mat = {
        dan_xuat(LOAI_PG, a, 1, master),
        dan_xuat(LOAI_S3, a, 1, master),
        khoa.api_key,
    }

    cot = await pool.fetch(
        """SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'control'
              AND table_name IN ('agent_keys', 'agent_credentials')
              AND data_type IN ('text', 'character varying')"""
    )
    assert cot, "không quét được cột nào — truy vấn catalog sai, không phải bảng sạch"

    for r in cot:
        if (r["table_name"], r["column_name"]) in _NGOAI_LE_CO_CHU_Y:
            continue
        for bm in bi_mat:
            hit = await pool.fetchval(
                f'SELECT count(*) FROM control."{r["table_name"]}" WHERE "{r["column_name"]}" = $1',  # noqa: S608
                bm,
            )
            assert hit == 0, f"bí mật rò vào control.{r['table_name']}.{r['column_name']}"


async def test_repr_khong_lo_mat_khau(api_pool, redis_client, ha_tang, hai_tenant):
    """Một f-string vô ý trong except là đủ để lộ. Chặn ở tầng model (SecretStr)."""
    khoa = await _cap(api_pool, ha_tang, hai_tenant[0])
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    for thuc in (ra.postgres_password.get_secret_value(), ra.storage.secret_key.get_secret_value()):
        assert thuc not in repr(ra)
        assert thuc not in str(ra)


async def test_json_van_co_gia_tri_that(api_pool, redis_client, ha_tang, hai_tenant):
    """Mặt còn lại của SecretStr: pod PHẢI nhận được mật khẩu thật.
    Thiếu `field_serializer` thì response là '**********' và pod không nối được."""
    khoa = await _cap(api_pool, ha_tang, hai_tenant[0])
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    d = ra.model_dump(mode="json")
    assert d["postgres_password"] == ra.postgres_password.get_secret_value()
    assert d["storage"]["secret_key"] == ra.storage.secret_key.get_secret_value()
    assert "*" not in d["postgres_password"]


# ─── Rate-limit ────────────────────────────────────────────────────────────


async def test_vuot_nhip_thi_429(api_pool, redis_client, ha_tang, hai_tenant):
    khoa = await _cap(api_pool, ha_tang, hai_tenant[0])
    for _ in range(service.NHIP_SO_LAN):
        await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    with pytest.raises(LoiPortal) as e:
        await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)
    assert (e.value.ma, e.value.http) == ("RATE_LIMITED", 429)


# ─── Nội dung runtime-credentials response ───────────────────────────────────────────


async def test_runtime_credentials_tra_du_bon_khoi(api_pool, redis_client, ha_tang, hai_tenant):
    """Bốn khối của hợp đồng §2. Đổi tên khoá ở đây là bên agent code theo tài
    liệu sai — docs/contracts/dau-noi-agent.md §2 phải khớp."""
    a = hai_tenant[0]
    khoa = await _cap(api_pool, ha_tang, a)
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    assert ra.tenant_id == a
    assert ra.postgres_role == f"agent_{a}"
    assert ra.postgres_password.get_secret_value()
    assert ra.storage.access_key == f"agent-{a}"
    assert ra.storage.prefix == f"tenants/{a}/"
    assert ra.kb.collection == f"kb_{a}"
    assert ra.expires_at is not None
    assert ra.agent_key_id == khoa.id


async def test_agent_key_id_la_khoa_da_goi_chu_khong_phai_khoa_khac_cua_tenant(
    api_pool, redis_client, ha_tang, hai_tenant
):
    """Cổng của `0939`: hai khoá CÙNG tenant phải ra HAI `agent_key_id`.

    Đây là bài duy nhất phân biệt được cài đặt đúng với cài đặt "trả một khoá bất
    kỳ của tenant" (vd `SELECT id ... WHERE tenant_id = $1 LIMIT 1`) — với một
    khoá duy nhất thì hai cách cho cùng kết quả và bug đi thẳng ra production.

    Hai khoá phải CÙNG tenant, nếu không bài này xanh vì một lý do sai. Trước
    `0940` điều kiện đó viết là `k1.deployment_id == k2.deployment_id`.
    """
    a = hai_tenant[0]
    k1 = await service.phat_khoa_cho_tenant(api_pool, ha_tang, a, "pod-1", "owner")
    k2 = await service.phat_khoa_cho_tenant(api_pool, ha_tang, a, "pod-2", "owner")

    r1 = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, k1.api_key)
    r2 = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, k2.api_key)

    assert r1.tenant_id == r2.tenant_id == a, "hai khoá phải cùng tenant, nếu không bài này vô nghĩa"
    assert r1.agent_key_id == k1.id
    assert r2.agent_key_id == k2.id
    assert r1.agent_key_id != r2.agent_key_id


async def test_fk_agent_key_id_canh_duoc_du_agent_khong_doc_noi_bang_khoa(
    api_pool, redis_client, ha_tang, hai_tenant, pg_dsn
):
    """FK `conversations.agent_key_id -> control.agent_keys(id)` (0939) cưỡng chế
    được BẰNG CHÍNH role agent, dù role đó có ZERO quyền trên `control.agent_keys`
    (`0917` revoke PUBLIC).

    ⚠️ Bài này neo lại một sự thật ĐÃ BỊ HIỂU SAI một lần: bản nháp đầu của `0939`
    từ chối FK vì tưởng Postgres kiểm ràng buộc bằng quyền của NGƯỜI GHI. Không
    phải — trigger RI chạy với quyền của CHỦ bảng. Nếu ai đó gỡ FK đi vì lại tin
    lý lẽ cũ, bài này đỏ.
    """
    a = hai_tenant[0]
    khoa = await _cap(api_pool, ha_tang, a)
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    conn = await asyncpg.connect(_dsn(pg_dsn, ra))
    try:
        assert await conn.fetchval("SELECT session_user") == f"agent_{a}"
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.fetchval("SELECT 1 FROM control.agent_keys LIMIT 1")

        tx = conn.transaction()
        await tx.start()
        try:
            # Khoá CÓ THẬT đi qua, dù người ghi không đọc nổi bảng được trỏ tới.
            assert await conn.fetchval(
                "INSERT INTO tenant_data.conversations (tenant_id, session_id, agent_key_id)"
                " VALUES ($1, 'fk-probe', $2) RETURNING id",
                a,
                ra.agent_key_id,
            )
            # Khoá KHÔNG có thật bị chặn — đây mới là vế chứng minh FK đang cưỡng chế.
            with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
                await conn.fetchval(
                    "INSERT INTO tenant_data.conversations (tenant_id, session_id, agent_key_id)"
                    " VALUES ($1, 'fk-bad', 999999999) RETURNING id",
                    a,
                )
        finally:
            await tx.rollback()
    finally:
        await conn.close()


async def test_kho_tep_chi_mo_dung_tien_to_cua_minh(api_pool, redis_client, ha_tang, hai_tenant, kho_tep):
    """Cách ly kho tệp: khoá của A không đọc được object dưới `tenants/B/`.
    Postgres từ chối câu truy vấn; kho tệp chỉ kiểm "khoá này vào được tiền tố
    này không" — một lỗi ghép đường dẫn là A đọc được bản ghi hội thoại của B."""
    from portal.core.storage import KhoTep
    from tests.conftest import MINIO_BUCKET

    a, b = hai_tenant
    await kho_tep.ghi(f"tenants/{b}/LIVE", b"cua-B")

    khoa = await _cap(api_pool, ha_tang, a)
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    kho_cua_a = KhoTep(
        endpoint_url=ra.storage.endpoint,
        bucket=MINIO_BUCKET,
        access_key=ra.storage.access_key,
        secret_key=ra.storage.secret_key.get_secret_value(),
    )
    with pytest.raises(Exception):  # noqa: B017 — botocore ném ClientError/AccessDenied
        await kho_cua_a.doc(f"tenants/{b}/LIVE")


# ─── Cấp phát idempotent ───────────────────────────────────────────────────


async def test_cap_phat_hai_lan_khong_vo(api_pool, ha_tang, hai_tenant):
    """Tenant đã có role và access key ⇒ deployment thứ hai vẫn cấp phát được.
    Cấp phát chạm hai hệ ngoài Postgres-thuần nên không thể trong một transaction;
    chịu được gọi lại là cách duy nhất để hỏng-giữa-chừng không thành nửa vời."""
    a = hai_tenant[0]
    await _cap(api_pool, ha_tang, a)
    await _cap(api_pool, ha_tang, a)


async def test_san_sang_du_lieu_dem_dung(api_pool, ha_tang, hai_tenant):
    """Chưa publish gì thì phải báo 0, không báo sẵn sàng — hỏng im lặng của
    kiến trúc này là pod chạy sạch mà agent tư vấn bằng kết quả rỗng."""
    a = hai_tenant[0]
    d = await service.san_sang_du_lieu(api_pool, a)
    assert d.projects_published == 1  # fixture seed đúng 1 dự án published
    assert d.kb_chunks == 0


# ─── Cổng 7: token Qdrant chỉ mở ĐÚNG collection của tenant ─────────────────
#
# Qdrant KHÔNG có RLS. Với Postgres, hỏi sai tenant trả 0 hàng; với Qdrant, hỏi
# sai tenant TRẢ DỮ LIỆU — trước 2026-08-15 không gì ngăn cả. Ba bài dưới canh
# lớp thay thế: một JWT chỉ-đọc, chỉ-một-collection, có hạn.


def _payload(token: str) -> dict:
    """Bóc thân JWT bằng tay — không dùng lại hàm của module đang test."""
    import base64
    import json

    than = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(than + "=" * (-len(than) % 4)))


async def test_token_qdrant_chi_mo_collection_cua_chinh_tenant(
    api_pool, redis_client, ha_tang, hai_tenant, monkeypatch
):
    """Hai tenant ⇒ hai token, mỗi cái khoá vào đúng kho của mình.

    Đây là bài canh THẬT của bản vá: một token mở được kho tenant khác thì mọi
    thứ còn lại của cơ chế này vô nghĩa.
    """
    monkeypatch.setenv("QDRANT_API_KEY", "khoa-ky-qdrant-test")
    a, b = hai_tenant

    ra = await service.lay_runtime_credentials(
        api_pool, redis_client, ha_tang, (await _cap(api_pool, ha_tang, a)).api_key
    )
    rb = await service.lay_runtime_credentials(
        api_pool, redis_client, ha_tang, (await _cap(api_pool, ha_tang, b)).api_key
    )

    pa = _payload(ra.kb.api_key.get_secret_value())
    pb = _payload(rb.kb.api_key.get_secret_value())

    assert pa["access"] == [
        {"collection": ra.kb.collection, "access": "r"},
        {"collection": ra.kb.public_web_collection, "access": "r"},
    ]
    assert pb["access"] == [
        {"collection": rb.kb.collection, "access": "r"},
        {"collection": rb.kb.public_web_collection, "access": "r"},
    ]
    assert ra.kb.collection != rb.kb.collection, "hai tenant phải khác collection"
    assert ra.kb.public_web_collection == f"{a}_public_web" and rb.kb.public_web_collection == f"{b}_public_web"
    # Không token nào nhắc tới kho của bên kia, dù chỉ trong một chuỗi.
    assert rb.kb.collection not in ra.kb.api_key.get_secret_value()


async def test_token_qdrant_het_han_cung_luc_voi_ca_bo_credential(
    api_pool, redis_client, ha_tang, hai_tenant, monkeypatch
):
    """`exp` của token và `expires_at` của response là CÙNG một mốc.

    Lệch nhau nghĩa là pod làm mới đúng lúc `expires_at` nhưng token Qdrant đã
    chết trước đó vài giây — một khoảng 401 mà không log nào của portal giải
    thích được.
    """
    monkeypatch.setenv("QDRANT_API_KEY", "khoa-ky-qdrant-test")
    khoa = await _cap(api_pool, ha_tang, hai_tenant[0])
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    assert _payload(ra.kb.api_key.get_secret_value())["exp"] == int(ra.expires_at.timestamp())


async def test_chua_cau_hinh_khoa_thi_api_key_None_va_phan_con_lai_van_chay(
    api_pool, redis_client, ha_tang, hai_tenant, monkeypatch
):
    """⚠️ Đây là bài canh cho việc BẬT KHOÁ KHÔNG GIÁN ĐOẠN, không phải một ca lỗi.

    Pod bản mới phải chạy được ở môi trường Qdrant chưa bật `service.api_key` —
    nếu không, portal và Qdrant buộc phải deploy cùng một giây. Và `None` không
    được kéo sập cả endpoint: mật khẩu Postgres nằm cùng response này, nên ném
    ở đây là chặn pod khởi động vì một kho hoàn toàn khác chưa cấu hình.
    """
    monkeypatch.setenv("QDRANT_API_KEY", "")
    khoa = await _cap(api_pool, ha_tang, hai_tenant[0])
    ra = await service.lay_runtime_credentials(api_pool, redis_client, ha_tang, khoa.api_key)

    assert ra.kb.api_key is None
    assert ra.kb.collection, "collection vẫn phải trả về"
    assert ra.postgres_password.get_secret_value(), "phần Postgres không được ảnh hưởng"
