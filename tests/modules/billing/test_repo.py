"""SQL của module billing. Đọc qua tenant_conn() — đó là seam cách ly."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import asyncpg
import pytest

from portal.api import loi
from portal.core.db.session import tenant_conn
from portal.modules.billing import repo
from tests.modules.billing.conftest import KEY_LABEL, MOC, SESSION, TENANT, TENANT_KHAC, USER_ID

# Brief gốc khai TU/DEN là chuỗi ("2026-08-01") — asyncpg từ chối chuỗi trần cho
# tham số so với cột `timestamptz` (`DataError: expected a datetime.date or
# datetime.datetime instance, got 'str'`), và mọi hàm khác trong repo (vd
# `ops/repo.py`) đều nhận `date` thật, không phải chuỗi. Đổi sang `date(...)`
# cho khớp chữ ký `repo.tong_quan(conn, tu_ngay: date, den_ngay: date)`.
TU = date(2026, 8, 1)
DEN = date(2026, 9, 1)


async def _da_dinh_gia(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
            TENANT,
        )


async def test_doc_ngoai_giao_dich_tra_0_hang(api_dsn: str, workspace_billing) -> None:
    """Chế độ hỏng IM LẶNG của Luật 1 — neo lại để không ai "sửa" bằng cách bỏ tenant_conn.

    Đo được trên DB dev: portal_api đọc billing.usage_events ngoài giao dịch trả 0,
    KHÔNG phải permission denied. Một repo quên tenant_conn() sẽ trả bảng rỗng và
    màn hình hiện "chưa có dữ liệu" — trông hoàn toàn hợp lý.
    """
    conn = await asyncpg.connect(api_dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM billing.usage_events") == 0
    finally:
        await conn.close()


async def test_tong_quan(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        r = await repo.tong_quan(conn, TU, DEN)
    assert r["so_phien"] == 1
    assert r["input_tokens"] == 113674
    # `voice_sec` = thời lượng CUỘC GỌI (component='call'), KHÔNG phải tổng
    # audio_sec mọi component (vad/stt/tts/speaker_verify/call đo CHỒNG LẤN
    # cùng khoảng audio — cộng thẳng ra 386.38, gấp ~2.7× cuộc gọi thật 142.44).
    # Xem docstring `repo.tong_quan` và `test_voice_sec_la_thoi_luong_call` dưới.
    assert r["voice_sec"] == pytest.approx(142.44, abs=0.01)
    assert r["chi_phi"] == Decimal("4145.2625000000")
    assert r["so_key"] == 1


async def test_tong_quan_nem_loi_khi_nhieu_don_vi_tien(
    pool: asyncpg.Pool, api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Hai bảng giá KHÁC đơn vị tiền cùng áp cho MỘT tenant trong MỘT khoảng —
    `tong_quan` phải NÉM lỗi rõ ràng, không cộng VND với USD thành một số.

    Đường tới được KHÔNG CẦN bug gì cả: đổi bảng giá cho tenant giữa kỳ (đúng
    việc `gan_cho_tenant` cho phép) sang một bảng giá khác đơn vị tiền là đủ.
    Trước bản vá, `min(currency)` chọn 'USD' (thua 'VND' theo alphabet) và gắn
    nhãn đó lên tổng đã cộng lẫn cả hai đơn vị — sai mà không lỗi nào phát ra.
    """
    moc_doi = datetime(2026, 8, 20, tzinfo=UTC)
    pv_usd = None
    try:
        async with pool.acquire() as conn, conn.transaction():
            # Đóng khoảng hiệu lực của bang_gia_vi_du (VND) TẠI một mốc TRONG
            # khoảng TU..DEN, rồi mở một bảng giá USD từ mốc đó.
            await conn.execute(
                "UPDATE billing.tenant_price_version SET effective_to = $2 "
                "WHERE tenant_id = $1 AND effective_to IS NULL",
                TENANT,
                moc_doi,
            )
            pv_usd = await conn.fetchval(
                "INSERT INTO billing.price_version (code, name, currency, status, is_default) "
                "VALUES ('pv_usd_test', 'usd', 'USD', 'active', false) RETURNING id"
            )
            await conn.execute(
                "INSERT INTO billing.price_item (price_version_id, component, metric, unit_price, per_units) "
                "VALUES ($1, 'llm', 'input_tokens', 1, 1000000)",
                pv_usd,
            )
            await conn.execute(
                "INSERT INTO billing.tenant_price_version (tenant_id, price_version_id, effective_from) "
                "VALUES ($1, $2, $3)",
                TENANT,
                pv_usd,
                moc_doi,
            )
            await conn.execute(
                """INSERT INTO billing.usage_events
                   (tenant_id, session_id, channel, seq, component, purpose, provider,
                    model, input_tokens, occurred_at)
                   VALUES ($1, $2, 'voice', 100, 'llm', 'conversation', 'gemini',
                           'gemini-2.5-flash', 1000000, $3)""",
                TENANT,
                SESSION,
                moc_doi + timedelta(days=1),
            )
        await _da_dinh_gia(api_pool)

        async with tenant_conn(api_pool, TENANT) as conn:
            with pytest.raises(loi.LoiPortal) as exc:
                await repo.tong_quan(conn, TU, DEN)
        assert exc.value.ma == "NHIEU_DON_VI_TIEN"
        assert exc.value.http == 409
    finally:
        if pv_usd is not None:
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute("DELETE FROM billing.rated_usage WHERE price_version_id = $1", pv_usd)
                await conn.execute("DELETE FROM billing.tenant_price_version WHERE price_version_id = $1", pv_usd)
                await conn.execute("DELETE FROM billing.price_version WHERE id = $1", pv_usd)


async def test_voice_sec_la_thoi_luong_call_khong_phai_tong_moi_component(
    api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Chốt ngữ nghĩa để không ai "đơn giản hoá" `voice_sec` về lại một `sum(audio_sec)`
    trần. `vad`/`stt`/`tts`/`speaker_verify` đo CHỒNG LẤN cùng khoảng audio của
    cuộc gọi — fixture của module này có tổng audio_sec của BỐN component đó
    (141.44+10.21+81.72+10.57 = 243.94s) đã LỚN HƠN audio_sec của `call`
    (142.44s), nên nếu ai thay `FILTER (WHERE component = 'call')` bằng một
    `sum` trần, `voice_sec` nhảy lên ~386s và bài này đỏ ngay.
    """
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        r = await repo.tong_quan(conn, TU, DEN)
        cac_component_khac = await conn.fetchval(
            "SELECT sum(audio_sec) FROM billing.usage_events "
            "WHERE tenant_id = portal.current_tenant() AND component <> 'call'"
        )
    assert cac_component_khac > r["voice_sec"], (
        "fixture phải có audio_sec NGOÀI `call` lớn hơn audio_sec của `call` để bài này canh được điều nó tuyên bố"
    )
    assert r["voice_sec"] == pytest.approx(142.44, abs=0.01)


async def test_theo_key_co_dong_chua_phan_loai(pool: asyncpg.Pool, api_pool, workspace_billing, bang_gia_vi_du) -> None:
    """Phiên không có agent_key_id phải hiện thành nhóm riêng, KHÔNG bị ẩn.

    Ẩn nó là làm tổng theo key lệch tổng hoá đơn — lỗi phổ biến nhất của dashboard
    usage, và nó lệch theo hướng THIẾU nên không ai thấy.

    Chèn dữ liệu bằng `pool` (`portal_migrator`), KHÔNG `api_pool`: `billing.
    usage_events` chỉ cấp INSERT cho `agent_all` (0942) — Portal không có, và
    không nên có, đường ghi vào bảng này. Cùng khuôn với `_chen_usage` trong
    conftest.py.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tenant_data.conversations (tenant_id, session_id, source) "
            "VALUES ($1, 'sess-khong-key', 'chat')",
            TENANT,
        )
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ($1, 'sess-khong-key', 'chat', 0, 'llm', 'conversation',
                       'gemini', 'gemini-2.5-flash', 400000, '2026-08-19T09:52Z')""",
            TENANT,
        )
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_key(conn, TU, DEN)
    theo_id = {r["agent_key_id"]: r for r in hang}
    assert None in theo_id, "thiếu nhóm 'chưa phân loại'"
    assert theo_id[None]["chi_phi"] == Decimal("1000.0000000000")
    co_key = [r for r in hang if r["agent_key_id"] is not None][0]
    assert co_key["label"] == KEY_LABEL
    assert co_key["so_phien"] == 1


async def test_theo_key_giu_usage_khi_chua_co_hang_conversations(
    pool: asyncpg.Pool, api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Agent có thể ghi usage TRƯỚC KHI hàng `tenant_data.conversations` tồn tại
    (không đảm bảo thứ tự ghi giữa hai bảng). Khác `test_theo_key_co_dong_chua_
    phan_loai` — phiên đó CÓ hàng conversations, chỉ thiếu `agent_key_id`; bài
    này KHÔNG chèn hàng conversations nào cho phiên mới.

    `theo_key` dùng LEFT JOIN đúng vì lý do này (xem docstring `repo.theo_key`);
    đổi thành INNER JOIN sẽ làm usage của phiên này biến mất KHỎI MỌI NHÓM,
    không riêng gì nhóm 'chưa phân loại' — hoá đơn nhỏ hơn thật mà không lỗi
    nào. Assert cả `theo_key` (rơi vào nhóm chưa phân loại) lẫn `tong_quan`
    (vẫn cộng vào tổng tenant) để bắt được cả hai chỗ INNER JOIN có thể lẻn vào.
    """
    session_moi = "sess-chua-co-conversations"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ($1, $2, 'chat', 0, 'llm', 'conversation',
                       'gemini', 'gemini-2.5-flash', 200000, $3)""",
            TENANT,
            session_moi,
            MOC,
        )
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_key(conn, TU, DEN)
        tong = await repo.tong_quan(conn, TU, DEN)

    theo_id = {r["agent_key_id"]: r for r in hang}
    assert None in theo_id, "phiên chưa có hàng conversations phải rơi vào nhóm 'chưa phân loại'"
    assert theo_id[None]["chi_phi"] > 0
    assert theo_id[None]["so_phien"] == 1
    # Fixture chính (SESSION) + phiên mới KHÔNG có hàng conversations = 2 phiên
    # trong tổng tenant. INNER JOIN sẽ làm con số này tụt về 1.
    assert tong["so_phien"] == 2


async def test_theo_key_khong_mat_tien_khi_gan_khoa_sau_khi_dinh_gia(
    pool: asyncpg.Pool, api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    """`rated_usage.agent_key_id` ĐÔNG CỨNG lúc định giá (trigger AFTER INSERT,
    `0950`) bằng cách LEFT JOIN `conversations` TẠI THỜI ĐIỂM ĐÓ. `theo_key()`
    thì suy `agent_key_id` SỐNG, join lại `conversations` MỖI LẦN query (CTE
    `ev`). `test_theo_key_giu_usage_khi_chua_co_hang_conversations` đã chứng
    minh usage ghi được TRƯỚC khi có hàng `conversations` — nên có một khoảng
    hở: nếu `conversations`/`agent_key_id` xuất hiện SAU khi usage đã định giá,
    hai nguồn agent_key_id lệch nhau, và outer query của `theo_key()` neo trên
    `ev` (`FROM ev LEFT JOIN tien t ON t.agent_key_id IS NOT DISTINCT FROM
    ev.agent_key_id`) — dòng `tien` mang agent_key_id CŨ (ở đây là NULL) không
    còn khớp được với BẤT KỲ dòng `ev` nào (mọi `ev` của phiên đó giờ mang khoá
    THẬT), nên bị loại khỏi kết quả HOÀN TOÀN, kể cả khỏi nhóm 'chưa phân loại'.
    Tiền đó vẫn nằm nguyên trong `chi_phi_tong` (`tien_tenant()`, không quan
    tâm agent_key_id) ⇒ Σ theo_key() < chi_phi_tong — đúng banner "lệch tổng"
    mà `BangLuotDung.tsx` (FE) đang cảnh báo.
    """
    session_moi = "sess-key-gan-sau"
    async with pool.acquire() as conn, conn.transaction():
        # 1. Usage ghi TRƯỚC — CHƯA có hàng conversations cho phiên này.
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ($1, $2, 'chat', 0, 'llm', 'conversation',
                       'gemini', 'gemini-2.5-flash', 200000, $3)""",
            TENANT,
            session_moi,
            MOC,
        )
    # 2. Định giá trong lúc conversations CHƯA tồn tại ⇒ rated_usage.agent_key_id = NULL.
    await _da_dinh_gia(api_pool)

    # 3. Conversations xuất hiện SAU, mang khoá THẬT (agent tạo phiên trễ hơn usage).
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tenant_data.conversations (tenant_id, session_id, source, agent_key_id, started_at) "
            "VALUES ($1, $2, 'chat', $3, $4)",
            TENANT,
            session_moi,
            workspace_billing["key_id"],
            MOC,
        )

    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_key(conn, TU, DEN)
        chi_phi_tong, _ = await repo.tien_tenant(conn, TU, DEN)

    tong_theo_key = sum((r["chi_phi"] for r in hang), Decimal(0))
    assert tong_theo_key == chi_phi_tong, (
        f"tổng theo khoá ({tong_theo_key}) lệch chi_phi_tong ({chi_phi_tong}) — "
        "tiền của phiên vừa gán khoá SAU khi định giá đã rơi mất khỏi theo_key()"
    )


async def test_theo_key_tach_tien_theo_component(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    """Bảy cột `chi_phi_<component>` (thay ba cột token in/out/cache read ở bảng
    «Lượt dùng theo khoá» phía FE) phải khớp CHÍNH XÁC công thức giá ví dụ §4,
    tính tay từ `_chen_usage()` — không so xấp xỉ, `Decimal` cộng/nhân là số học
    chính xác nên không có sai số làm tròn nào để cho phép `pytest.approx`.

    Số liệu (xem `conftest._chen_usage`/`bang_gia_vi_du`):
      llm            = Σ(in×2500 + out×10000 + cr×625)/1e6 của 7 dòng llm = 311,8725
      stt            = 10,21×10 (audio_sec) + 240×0,5 (text_units) + 0 (stream, giá 0) = 222,1
      tts            = 1115×2 (text_units)                                            = 2230
      vad            = 141,44×1 (audio_sec)                                           = 141,44
      speaker_verify = 10,57×5 (audio_sec)                                            = 52,85
      call           = 142,44×500/60 (audio_sec)                                      = 1187
      embed          = không có usage embed trong fixture                            = 0
    Tổng bảy cột = 4145,2625 = đúng `chi_phi` của hàng (và đúng `test_tong_quan`,
    vì fixture chỉ có một khoá duy nhất phát sinh tiền trong kỳ).
    """
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_key(conn, TU, DEN)
    co_key = next(r for r in hang if r["agent_key_id"] is not None)

    assert co_key["chi_phi_llm"] == Decimal("311.8725000000")
    assert co_key["chi_phi_stt"] == Decimal("222.1000000000")
    assert co_key["chi_phi_tts"] == Decimal("2230.0000000000")
    assert co_key["chi_phi_vad"] == Decimal("141.4400000000")
    assert co_key["chi_phi_speaker_verify"] == Decimal("52.8500000000")
    assert co_key["chi_phi_call"] == Decimal("1187.0000000000")
    assert co_key["chi_phi_embed"] == 0

    tong_bay_cot = (
        co_key["chi_phi_llm"]
        + co_key["chi_phi_tts"]
        + co_key["chi_phi_stt"]
        + co_key["chi_phi_embed"]
        + co_key["chi_phi_call"]
        + co_key["chi_phi_vad"]
        + co_key["chi_phi_speaker_verify"]
    )
    assert tong_bay_cot == co_key["chi_phi"] == Decimal("4145.2625000000")


async def test_theo_key_component_ngoai_bay_ma_khong_lam_vo_tong(
    pool: asyncpg.Pool, api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Một component NGOÀI bảy mã đã biết (`usage_events.component` là `text`
    không CHECK) vẫn phải cộng đúng vào `chi_phi_tong`/`chi_phi` của hàng —
    chỉ không lộ ra ở CỘT nào trong bảy cột (đúng docstring `repo.theo_key`).
    Bài này chặn regression "component lạ làm 500" hoặc "component lạ bị bỏ sót
    khỏi `chi_phi`" — cả hai còn tệ hơn việc nó không có cột riêng.
    """
    async with pool.acquire() as conn, conn.transaction():
        pb = await conn.fetchval(
            "SELECT price_version_id FROM billing.tenant_price_version WHERE tenant_id = $1", TENANT
        )
        await conn.execute(
            "INSERT INTO billing.price_item (price_version_id, component, metric, unit_price, per_units) "
            "VALUES ($1, 'component_la', 'units', 7, 1)",
            pb,
        )
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, units, occurred_at)
               VALUES ($1, $2, 'voice', 200, 'component_la', 'conversation', '', '', 3, $3)""",
            TENANT,
            SESSION,
            MOC,
        )
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_key(conn, TU, DEN)
    co_key = next(r for r in hang if r["agent_key_id"] is not None)

    # 3 × 7 = 21đ CỘNG vào tổng, dù không cột `chi_phi_<x>` nào tách được nó ra.
    assert co_key["chi_phi"] == Decimal("4166.2625000000")
    tong_bay_cot = (
        co_key["chi_phi_llm"]
        + co_key["chi_phi_tts"]
        + co_key["chi_phi_stt"]
        + co_key["chi_phi_embed"]
        + co_key["chi_phi_call"]
        + co_key["chi_phi_vad"]
        + co_key["chi_phi_speaker_verify"]
    )
    assert tong_bay_cot == Decimal("4145.2625000000")
    assert co_key["chi_phi"] - tong_bay_cot == Decimal("21.0000000000")


async def test_theo_owner_tach_tien_theo_component(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    """Bảy cột `chi_phi_<component>` của `theo_owner()` (2026-08-27, mirror
    `theo_key`) phải khớp CHÍNH XÁC cùng công thức giá ví dụ §4 đã neo ở
    `test_theo_key_tach_tien_theo_component` — fixture chỉ có MỘT khoá phát
    sinh tiền trong kỳ, và khoá đó thuộc `USER_ID`, nên hàng owner phải ra
    ĐÚNG những con số đó (không so xấp xỉ, cùng lý do `Decimal`).
    """
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_owner(conn, TU, DEN)
    dong = next(r for r in hang if r["user_id"] == USER_ID)

    assert dong["chi_phi_llm"] == Decimal("311.8725000000")
    assert dong["chi_phi_stt"] == Decimal("222.1000000000")
    assert dong["chi_phi_tts"] == Decimal("2230.0000000000")
    assert dong["chi_phi_vad"] == Decimal("141.4400000000")
    assert dong["chi_phi_speaker_verify"] == Decimal("52.8500000000")
    assert dong["chi_phi_call"] == Decimal("1187.0000000000")
    assert dong["chi_phi_embed"] == 0

    tong_bay_cot = (
        dong["chi_phi_llm"]
        + dong["chi_phi_tts"]
        + dong["chi_phi_stt"]
        + dong["chi_phi_embed"]
        + dong["chi_phi_call"]
        + dong["chi_phi_vad"]
        + dong["chi_phi_speaker_verify"]
    )
    assert tong_bay_cot == dong["chi_phi"] == Decimal("4145.2625000000")


async def test_theo_owner_khong_nhan_ban_qua_join(
    pool: asyncpg.Pool, api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Neo lại bug fan-out: `theo_owner` từng JOIN thẳng `billing.rated_usage`
    (hạt EVENT) với `tenant_data.conversations` (hạt PHIÊN) qua `agent_key_id`
    một mình — một khoá sở hữu N phiên thì mỗi hàng `rated_usage` của khoá đó bị
    nhân bản N lần trước khi `sum(amount)` cộng, thổi phồng `chi_phi` gấp N lần
    (đo được trước khi sửa: khoá 2 phiên ra `chi_phi` gấp đôi số thật).

    Cho khoá của `workspace_billing` sở hữu THÊM một phiên (tổng 2), rồi so
    `chi_phi` trả về với tổng ĐỘC LẬP tính trực tiếp từ `billing.rated_usage` —
    không hardcode một con số có thể trôi theo fixture.
    """
    session_2 = "bil-sess-voice-2"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tenant_data.conversations (tenant_id, session_id, source, agent_key_id) "
            "VALUES ($1, $2, 'voice', $3)",
            TENANT,
            session_2,
            workspace_billing["key_id"],
        )
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, audio_sec, occurred_at)
               VALUES ($1, $2, 'voice', 0, 'call', 'session', '', '', 60, $3)""",
            TENANT,
            session_2,
            MOC,
        )
    await _da_dinh_gia(api_pool)

    async with pool.acquire() as conn:
        tong_doc_lap = await conn.fetchval(
            "SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1",
            TENANT,
        )

    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_owner(conn, TU, DEN)
    dong = next(r for r in hang if r["user_id"] == USER_ID)
    assert dong["so_phien"] == 2
    assert dong["chi_phi"] == tong_doc_lap


async def test_theo_owner_giu_usage_chua_co_chu(
    pool: asyncpg.Pool, api_pool, workspace_billing, bang_gia_vi_du
) -> None:
    """Usage chưa gán được chủ (không có hàng `conversations`, đúng khuôn
    `test_theo_key_giu_usage_khi_chua_co_hang_conversations`) phải còn lại
    trong `theo_owner` với `user_id = NULL`, KHÔNG bị INNER JOIN nuốt mất.

    Đo được TRƯỚC bản vá: `by_key` khớp đủ (gồm nhóm `agent_key_id = NULL`)
    nhưng `by_owner` JOIN thẳng `control.agent_keys` bằng INNER — `NULL =
    NULL` không khớp trong SQL nên nhóm mồ côi biến mất khỏi tổng theo owner,
    thiếu đúng số tiền của nhóm đó, không lỗi nào phát ra. Cổng của bài này là
    so `sum(chi_phi)` của `theo_owner` với tổng ĐỘC LẬP từ `billing.rated_usage`
    — phải khớp bất kể fixture, không hardcode một con số.
    """
    session_moi = "sess-owner-mo-coi"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose, provider,
                model, input_tokens, occurred_at)
               VALUES ($1, $2, 'chat', 0, 'llm', 'conversation',
                       'gemini', 'gemini-2.5-flash', 400000, $3)""",
            TENANT,
            session_moi,
            MOC,
        )
    await _da_dinh_gia(api_pool)

    async with pool.acquire() as conn:
        tong_doc_lap = await conn.fetchval("SELECT sum(amount) FROM billing.rated_usage WHERE tenant_id = $1", TENANT)

    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.theo_owner(conn, TU, DEN)

    tong_theo_owner = sum((r["chi_phi"] or 0) for r in hang)
    assert tong_theo_owner == tong_doc_lap, (
        f"tổng theo_owner {tong_theo_owner} lệch tổng tenant độc lập {tong_doc_lap} — "
        "INNER JOIN đang làm mất nhóm không có chủ"
    )
    mo_coi = [r for r in hang if r["user_id"] is None]
    assert mo_coi, "thiếu dòng 'không có chủ' (user_id NULL) cho usage chưa gán được khoá"


async def test_cach_ly_tenant(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT_KHAC) as conn:
        assert await repo.theo_key(conn, TU, DEN) == []
        r = await repo.tong_quan(conn, TU, DEN)
    assert (r["chi_phi"] or 0) == 0


async def test_event_cua_phien_co_tien_tung_dong(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        ev = await repo.event_cua_phien(conn, SESSION)
    assert len(ev) == 13
    call = [e for e in ev if e["component"] == "call"][0]
    assert call["chi_phi"] == Decimal("1187.0000000000")


async def _khang_dinh_bay_cot_phien(dong) -> None:
    """Cùng công thức giá ví dụ §4 đã neo ở `test_theo_key_tach_tien_theo_component` —
    fixture chỉ có MỘT phiên (`SESSION`) phát sinh toàn bộ tiền của khoá duy nhất
    trong kỳ, nên hàng phiên phải ra ĐÚNG những con số đó."""
    assert dong["chi_phi_llm"] == Decimal("311.8725000000")
    assert dong["chi_phi_stt"] == Decimal("222.1000000000")
    assert dong["chi_phi_tts"] == Decimal("2230.0000000000")
    assert dong["chi_phi_vad"] == Decimal("141.4400000000")
    assert dong["chi_phi_speaker_verify"] == Decimal("52.8500000000")
    assert dong["chi_phi_call"] == Decimal("1187.0000000000")
    assert dong["chi_phi_embed"] == 0
    tong_bay_cot = (
        dong["chi_phi_llm"]
        + dong["chi_phi_tts"]
        + dong["chi_phi_stt"]
        + dong["chi_phi_embed"]
        + dong["chi_phi_call"]
        + dong["chi_phi_vad"]
        + dong["chi_phi_speaker_verify"]
    )
    assert tong_bay_cot == dong["chi_phi"] == Decimal("4145.2625000000")


async def test_liet_ke_phien_tach_tien_theo_component(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    """Bảy cột `chi_phi_<component>` của `liet_ke_phien()` (2026-08-27, mirror
    `theo_key`/`theo_owner`) — CTE `tien` ở đây đã ĐÚNG hạt `session_id` nên
    không cần tầng gộp thứ hai, khác `theo_owner()`.
    """
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        hang = await repo.liet_ke_phien(conn, TU, DEN, 50, 0)
    dong = next(r for r in hang if r["session_id"] == SESSION)
    await _khang_dinh_bay_cot_phien(dong)


async def test_doc_phien_tach_tien_theo_component(api_pool, workspace_billing, bang_gia_vi_du) -> None:
    """Cùng bảy cột ở `doc_phien()` (dùng CHUNG shape CTE với `liet_ke_phien`,
    qua `_phien_out()` ở tầng router) — lọc theo `session_id` thay vì khoảng
    ngày, phải ra CÙNG số.
    """
    await _da_dinh_gia(api_pool)
    async with tenant_conn(api_pool, TENANT) as conn:
        dong = await repo.doc_phien(conn, SESSION)
    assert dong is not None
    await _khang_dinh_bay_cot_phien(dong)
