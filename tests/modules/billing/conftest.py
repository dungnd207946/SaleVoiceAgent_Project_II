"""Fixture module billing — cùng nếp tests/modules/ops/conftest.py.

KHÔNG mock `tenant_conn()`: nó là seam của cách ly, mock nó thì test xanh cho cả
một truy vấn quên vị từ tenant.

Dữ liệu usage được chèn TRỰC TIẾP vào `billing.usage_events` bằng `pool`
(`portal_migrator`) chứ không qua đường agent — Portal không có đường ghi vào bảng
đó, và dựng một agent giả chỉ để chèn 8 hàng là đắt mà không kiểm thêm được gì.
"""

from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import pytest

TENANT = "bilw"
TENANT_KHAC = "bilx"
USER_ID = "u_bil"
MAT_KHAU = "MatKhauDaiVaManh!1"
KEY_LABEL = "khoá dev"
SESSION = "bil-sess-voice-1"
MOC = datetime(2026, 8, 19, 9, 52, tzinfo=UTC)


@pytest.fixture
async def api_pool(api_dsn: str):
    """Pool nối bằng `portal_api`, chịu RLS — dùng `pool` (superuser) là mọi
    cổng cách ly thành cổng không bao giờ đỏ."""
    p = await asyncpg.create_pool(api_dsn, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest.fixture
async def workspace_billing(pool: asyncpg.Pool):
    """Hai tenant · một key mỗi tenant · một phiên voice có usage đầy đủ.

    Trả dict có `key_id` và `key_id_khac` để test cách ly dùng.
    """
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        # User TRƯỚC tenants: `control.tenants.created_by` là FK NOT NULL DEFERRABLE
        # KHÔNG khai (migration 0106) nên Postgres kiểm ràng buộc ngay lúc INSERT,
        # không đợi hết giao dịch — chèn tenant trỏ tới một user chưa tồn tại ném
        # ForeignKeyViolationError ngay tại câu đó, dù cùng transaction sẽ tạo user
        # ở câu kế tiếp.
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, 'Dũng', 'bil@noblex.vn', $2)",
            USER_ID,
            bam(MAT_KHAU),
        )
        for t, ten in ((TENANT, "Billing WS"), (TENANT_KHAC, "Billing Khac")):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, $3)",
                t,
                ten,
                USER_ID,
            )
        # Vai trò mẫu là TOÀN CỤC từ 0105 — id KHÔNG phải chuỗi 'owner' mà một mã
        # sinh (md5), nên fixture phải TRA theo tên, đúng khuôn
        # tests/modules/workspace/conftest.py::to_chuc_ws. 'Quản trị' là vai trò có
        # mọi action, tương đương "owner" của tài liệu handoff bên agent.
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        assert r_admin, "migration 0104/0105 chưa seed vai trò 'Quản trị' — fixture không dựng thay được"
        for t in (TENANT, TENANT_KHAC):
            await conn.execute(
                "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)",
                USER_ID,
                t,
                r_admin,
            )
        key_id = await conn.fetchval(
            "INSERT INTO control.agent_keys "
            "(tenant_id, key_sha256, key_prefix, label, created_by) "
            "VALUES ($1, 'sha_bil_a', 'ody_ag_aaa', $2, $3) RETURNING id",
            TENANT,
            KEY_LABEL,
            USER_ID,
        )
        key_khac = await conn.fetchval(
            "INSERT INTO control.agent_keys "
            "(tenant_id, key_sha256, key_prefix, label, created_by) "
            "VALUES ($1, 'sha_bil_b', 'ody_ag_bbb', 'khoá tenant khác', $2) RETURNING id",
            TENANT_KHAC,
            USER_ID,
        )
        await conn.execute(
            "INSERT INTO tenant_data.conversations "
            "(tenant_id, session_id, source, agent_key_id, started_at) "
            "VALUES ($1, $2, 'voice', $3, $4)",
            TENANT,
            SESSION,
            key_id,
            MOC,
        )
        await _chen_usage(conn, TENANT, SESSION)

    yield {"key_id": key_id, "key_id_khac": key_khac, "session": SESSION}

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM billing.usage_events WHERE tenant_id = ANY($1::text[])",
            [TENANT, TENANT_KHAC],
        )
        # rated_usage đi theo event_id (cascade), price_version dọn riêng ở fixture giá.
        await conn.execute("DELETE FROM control.audit_log WHERE tenant_id = ANY($1::text[])", [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.users WHERE id = $1", USER_ID)


async def _chen_usage(conn: asyncpg.Connection, tenant: str, session: str) -> None:
    """Một phiên voice thật, số liệu chép từ DB dev 2026-08-19.

    Tổng tiền với bảng giá ví dụ §4 của bên agent = 4025,2625 đ (đã đo thật:
    23 dòng rated_usage). Đừng đổi số ở đây mà không đổi hằng TIEN_MONG_DOI.

    ⚠️ FIXTURE PHẢI TỰ CHÈN DỮ LIỆU CỦA NÓ, không đọc dữ liệu có sẵn trong
    billing.usage_events. Agent vẫn đang ghi vào bảng đó — trong lúc viết plan này
    nó đi từ 20 → 34 → 43 event, và tổng tiền đi theo. Một cổng neo vào dữ liệu
    sống là một cổng đỏ ngẫu nhiên vào hôm sau.
    """
    hang = [
        # component, purpose, provider, model, in, out, cw, cr, audio_sec, wall_ms,
        # units, text_units, exact
        #
        # LAYOUT 2026-08-20 của bên agent: `units` = SỐ LẦN GỌI cho mọi component;
        # `text_units` = LƯỢNG TEXT theo ký tự. Trước đó ký tự TTS nằm trong `units` —
        # nếu thấy 1115 ở cột `units` thì đó là layout cũ, đã chuyển sang `text_units`.
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 11663, 42, 0, 0, 0.0, 2800.0, 2, 0, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 12856, 76, 0, 10878, 0.0, 2900.0, 2, 0, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 37443, 196, 0, 0, 0.0, 3000.0, 2, 0, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 25224, 71, 0, 12335, 0.0, 2600.0, 2, 0, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 12891, 34, 0, 12335, 0.0, 2500.0, 2, 0, True),
        ("llm", "conversation", "gemini", "gemini-2.5-flash", 12694, 42, 0, 0, 0.0, 2900.0, 1, 0, True),
        ("llm", "summary", "gemini", "gemini-2.5-flash", 903, 86, 0, 0, 0.0, 1400.0, 1, 0, True),
        # stt/conversation nay có HAI cơ sở tính tiền, CỘNG NHAU: giây audio gửi lên
        # (10,21 s) và ký tự transcript trả về (240) — vendor kiểu Soniox thu cả hai.
        # ⚠️ `wall_ms = 335.0` Ở DÒNG NÀY LÀ CÓ CHỦ Ý, đừng "dọn về 0". Bên agent
        # ghi `wall_ms` cho MỌI event như một độ trễ xử lý, nên `stt` có wall_ms
        # ở CẢ HAI purpose (đo trên DB dev 2026-08-25: 177.564,9 ms ở `stream`
        # và 10.380,0 ms ở `conversation`). Để 0 thì cột `wall_ms_stream` của
        # `usage-by-day` xanh dù có lọc `purpose` hay không — tức bài
        # `test_wall_ms_stream_khong_gom_purpose_khac` mất đối tượng đo.
        # KHÔNG ảnh hưởng tiền: `pricing_basis` chỉ khai `wall_ms` cho
        # (`stt`, `stream`), nên không dòng giá nào khớp cặp này.
        ("stt", "conversation", "", "", 0, 0, 0, 0, 10.21, 335.0, 0, 240, True),
        ("stt", "stream", "", "", 0, 0, 0, 0, 0.0, 142776.8, 1, 0, True),
        # tts: 1115 ký tự ĐƯA VÀO (text_units, cơ sở tính tiền) qua 7 clause (units)
        ("tts", "conversation", "", "", 0, 0, 0, 0, 81.72, 9900.0, 7, 1115, True),
        ("vad", "conversation", "", "", 0, 0, 0, 0, 141.44, 7700.0, 0, 0, True),
        ("speaker_verify", "conversation", "", "", 0, 0, 0, 0, 10.57, 200.0, 7, 0, True),
        ("call", "session", "", "", 0, 0, 0, 0, 142.44, 0.0, 1, 0, True),
    ]
    for seq, r in enumerate(hang):
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, turn_idx, component, purpose,
                provider, model, input_tokens, output_tokens, cache_write_tokens,
                cache_read_tokens, audio_sec, wall_ms, units, text_units, exact, occurred_at)
               VALUES ($1,$2,'voice',$3,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
            tenant,
            session,
            seq,
            r[0],
            r[1],
            r[2],
            r[3],
            r[4],
            r[5],
            r[6],
            r[7],
            r[8],
            r[9],
            r[10],
            r[11],
            r[12],
            MOC,
        )


@pytest.fixture
async def bang_gia_vi_du(pool: asyncpg.Pool):
    """Bảng giá VND đúng theo ví dụ §4 của bên agent. STT thu theo GIÂY."""
    async with pool.acquire() as conn, conn.transaction():
        pb = await conn.fetchval(
            "INSERT INTO billing.price_version (code, name, currency, status, is_default) "
            "VALUES ('pv_vd_test', 'ví dụ §4', 'VND', 'active', false) RETURNING id"
        )
        llm = [("input_tokens", 2500), ("output_tokens", 10000), ("cache_write_tokens", 0), ("cache_read_tokens", 625)]
        for metric, gia in llm:
            await conn.execute(
                "INSERT INTO billing.price_item (price_version_id, component, provider, "
                "model, metric, unit_price, per_units) "
                "VALUES ($1, 'llm', 'gemini', 'gemini-2.5-flash', $2, $3, 1000000)",
                pb,
                metric,
                gia,
            )
        audio = [
            ("stt", "conversation", "audio_sec", 10, 1),
            ("stt", "stream", "wall_ms", 0, 60000),
            # vế text-ra của STT: ĐỘC LẬP, cộng thêm vào vế thời lượng (Soniox thu cả hai)
            ("stt", "conversation", "text_units", Decimal("0.5"), 1),
            ("tts", "", "text_units", 2, 1),
            ("vad", "", "audio_sec", 1, 1),
            ("speaker_verify", "", "audio_sec", 5, 1),
            ("call", "", "audio_sec", 500, 60),
        ]
        for comp, purpose, metric, gia, per in audio:
            await conn.execute(
                "INSERT INTO billing.price_item (price_version_id, component, purpose, "
                "metric, unit_price, per_units) VALUES ($1, $2, $3, $4, $5, $6)",
                pb,
                comp,
                purpose,
                metric,
                gia,
                per,
            )
        await conn.execute(
            "INSERT INTO billing.tenant_price_version "
            "(tenant_id, price_version_id, effective_from) "
            "VALUES ($1, $2, '2000-01-01'::timestamptz)",
            TENANT,
            pb,
        )
    yield pb
    async with pool.acquire() as conn, conn.transaction():
        # `billing.rated_usage.price_version_id` FK về price_version KHÔNG cascade,
        # và trigger `price_item_bat_bien` chặn cascade DELETE của price_item một khi
        # rated_usage đã trỏ tới version này (bất biến "giá đã dùng thì không sửa"
        # — xem 0943_billing_pricing §3d). Mọi bài gọi `rate_usage()` bằng bảng giá
        # này để lại đúng dấu vết đó, nên phải dọn rated_usage TRƯỚC khi xoá version,
        # nếu không teardown tự ném ngay ở bài xanh đầu tiên.
        await conn.execute("DELETE FROM billing.rated_usage WHERE price_version_id = $1", pb)
        # `tenant_price_version.price_version_id` cũng KHÔNG cascade (RESTRICT mặc
        # định) — dòng gán ở trên phải dọn trước, nếu không FK chặn DELETE version.
        await conn.execute("DELETE FROM billing.tenant_price_version WHERE price_version_id = $1", pb)
        await conn.execute("DELETE FROM billing.price_version WHERE id = $1", pb)
