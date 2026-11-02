"""Màn admin bảng giá. Xác thực bằng header X-Platform-Admin-Token, KHÔNG bằng
phiên — đặt giá là việc của NobleX, không của khách.

⚠️ Ba sửa so với task-9-brief.md (đo được, không phải suy đoán):
1. `_kiem_token` (`core/auth/quan_tri_nen_tang.py`) ném `LoiPortal(..., 401, ...)`
   khi thiếu/sai token — brief kỳ vọng 403. `tests/modules/enrollment/test_router.py`
   khoá cứng đúng 401 cho cùng cổng này (`test_admin_thieu_token_thi_401`), nên
   403 ở đây sẽ luôn đỏ; sửa thành 401 để khớp cổng THẬT thay vì bẻ code cho khớp
   một con số brief đoán sai.
2. Mọi lỗi đi qua `dang_ky_handler_loi` (`api/loi.py`) đều bọc trong
   `{"error": {...}}`, không phải một dict phẳng — `r.json()["message"]` /
   `r.json()["code"]` của brief luôn `KeyError`. Sửa thành `r.json()["error"][...]`.
3. Thêm bài canh preview-khớp-rated_usage mà DoD của task đòi (đối chiếu hai
   cách khớp giá — `rate_usage()` ghi tiền thật và `preview_price_version()` chỉ
   SELECT — không được phép trôi nhau).

Và một điều CHỦ Ý bỏ so với bản nháp `gan_cho_tenant` của brief: không đòi
`price_version.status == 'active'` trước khi gán cho tenant — xem docstring dài
ở đầu `service.py` để biết lý do (mâu thuẫn với chính test Step 5 của brief +
`status` không phải nguồn sự thật khi định giá).
"""

from datetime import UTC, datetime

from tests.modules.billing.conftest import MOC, SESSION, TENANT

BASE = "/api/v1/admin/billing"
TOKEN = {"X-Platform-Admin-Token": "test-admin-token"}


async def _don_rated_usage(pool) -> None:
    """Xoá tiền đã định giá của `TENANT` — BẮT BUỘC trước khi gán một bảng giá có
    `effectiveFrom` trong quá khứ.

    VÌ SAO (thêm 2026-08-21): `service` chặn `409 MOC_QUA_KHU_DA_DINH_GIA` nếu kỳ
    được gán đã có `rated_usage` — cổng bảo vệ hoá đơn đã chốt khỏi bị viết lại.
    Từ migration `0950`, trigger `usage_events_dinh_gia` định giá NGAY lúc insert,
    nên mọi kỳ có usage đều «đã định giá» và cổng đó bung ở gần như mọi lần gán lùi
    ngày. Hai bài dưới đây kiểm CHUYỆN KHÁC (đóng khoảng cũ đúng mốc · nhánh
    `MOC_TRUOC_KHOANG_DANG_MO`), nên chúng phải dọn tiền trước để đi qua được cổng
    đứng trước.

    Đây KHÔNG phải nới cổng: bản thân câu lỗi của cổng đó đang chỉ dẫn đúng việc
    này («hoặc xoá rated_usage của kỳ đó trước nếu thật sự muốn tính lại»).
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM billing.rated_usage WHERE tenant_id = $1", TENANT)


async def _don_price_version(pool, *ids: int) -> None:
    """Xoá sạch một hay nhiều `price_version` bài test tạo ra qua API — kèm mọi
    hàng phụ thuộc (`rated_usage`/`tenant_price_version`) để không vướng
    trigger bất biến `price_item_bat_bien` hay FK RESTRICT.

    Không gọi hàm này thì mỗi bài để lại một hàng `billing.price_version` với
    `code` cố định VĨNH VIỄN trong DB của phiên test — vô hại trên container
    dùng một lần (mỗi phiên pytest chỉ chạy các `code` này một lần), nhưng là
    rác tích luỹ nếu ai chạy lại module trên cùng một DB bền, và đúng lớp lỗi
    "rò price_version" mà `test_tinh_lai_ky_cu_khi_version_da_inactive` từng mắc.
    """
    ids_ = [i for i in ids if i is not None]
    if not ids_:
        return
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM billing.rated_usage WHERE price_version_id = ANY($1::bigint[])", ids_)
        await conn.execute("DELETE FROM billing.tenant_price_version WHERE price_version_id = ANY($1::bigint[])", ids_)
        await conn.execute("DELETE FROM billing.price_version WHERE id = ANY($1::bigint[])", ids_)


async def test_khong_token_thi_401(app_client) -> None:
    r = await app_client.get(f"{BASE}/price-versions")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_ADMIN_TOKEN"


async def test_tao_bang_gia_va_dong_gia(app_client, monkeypatch, pool) -> None:
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    r = await app_client.post(
        f"{BASE}/price-versions",
        headers=TOKEN,
        json={"code": "pv_api", "name": "qua API", "currency": "VND"},
    )
    assert r.status_code == 201, r.text
    pb = r.json()["id"]
    try:
        r = await app_client.post(
            f"{BASE}/price-versions/{pb}/items",
            headers=TOKEN,
            json={
                "component": "llm",
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "metric": "input_tokens",
                "unitPrice": "2500",
                "perUnits": 1000000,
            },
        )
        assert r.status_code == 201, r.text
    finally:
        await _don_price_version(pool, pb)


async def test_chan_hai_co_so_stt(app_client, monkeypatch, pool) -> None:
    """DB chặn bằng unique index; API phải dịch thành 409 có thông điệp đọc được,
    không phải 500 UniqueViolation."""
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    r = await app_client.post(
        f"{BASE}/price-versions", headers=TOKEN, json={"code": "pv_stt", "name": "stt", "currency": "VND"}
    )
    pb = r.json()["id"]
    try:
        for i, (purpose, metric, per) in enumerate((("conversation", "audio_sec", 1), ("stream", "wall_ms", 60000))):
            r = await app_client.post(
                f"{BASE}/price-versions/{pb}/items",
                headers=TOKEN,
                json={"component": "stt", "purpose": purpose, "metric": metric, "unitPrice": "10", "perUnits": per},
            )
            if i == 0:
                # Dòng ĐẦU phải thành công — nếu không, bài này có thể xanh vì CẢ HAI
                # insert đều thất bại vì một lý do không liên quan gì tới unique index,
                # và assert 409 ở cuối vẫn "đúng" một cách vô nghĩa.
                assert r.status_code == 201, f"dòng giá đầu phải tạo được, nhận {r.status_code}: {r.text}"
        assert r.status_code == 409, f"phải 409, nhận {r.status_code}: {r.text}"
        assert "STT" in r.json()["error"]["message"]
    finally:
        await _don_price_version(pool, pb)


async def _tao_bang_gia_day_du(app_client, code: str) -> int:
    """Tạo một bảng giá phủ ĐỦ 12 dòng `billing.pricing_basis` — điều kiện để
    `kich_hoat` chấp nhận. HAI dòng STT dùng `purpose` BỎ TRỐNG (wildcard) —
    KHÔNG khai đúng tên purpose cụ thể (`conversation`/`stream`) như
    `bang_gia_vi_du` hay dùng. Đây là ca review yêu cầu canh: một dòng giá
    `purpose=''` phải thoả được một basis khai purpose cụ thể, vì `kich_hoat`
    kiểm `(pi.purpose = '' OR pi.purpose = cs.purpose)` — nếu vế `pi.purpose = ''`
    không hoạt động, bảng giá này sẽ KHÔNG kích hoạt được dù đủ dữ liệu, và đó
    là một bug thật cần báo, không phải né bằng cách khai purpose cụ thể.
    """
    r = await app_client.post(f"{BASE}/price-versions", headers=TOKEN, json={"code": code, "name": code})
    assert r.status_code == 201, r.text
    pb = r.json()["id"]
    dong = [
        {"component": "llm", "metric": "input_tokens", "unitPrice": "2500", "perUnits": 1000000},
        {"component": "llm", "metric": "output_tokens", "unitPrice": "10000", "perUnits": 1000000},
        {"component": "llm", "metric": "cache_write_tokens", "unitPrice": "0", "perUnits": 1000000},
        {"component": "llm", "metric": "cache_read_tokens", "unitPrice": "625", "perUnits": 1000000},
        {"component": "embed", "metric": "text_units", "unitPrice": "0"},
        {"component": "stt", "metric": "audio_sec", "unitPrice": "10"},  # purpose bỏ trống = wildcard
        {"component": "stt", "metric": "wall_ms", "unitPrice": "0"},  # purpose bỏ trống = wildcard
        # vế text-ra của STT: ĐỘC LẬP với cặp thời lượng, nên có giá > 0 cùng lúc với
        # `audio_sec` mà KHÔNG vướng `price_item_stt_single_basis` (index đã nới ở 0948).
        {"component": "stt", "metric": "text_units", "unitPrice": "0.5"},
        {"component": "tts", "metric": "text_units", "unitPrice": "2"},
        {"component": "vad", "metric": "audio_sec", "unitPrice": "1"},
        {"component": "speaker_verify", "metric": "audio_sec", "unitPrice": "5"},
        {"component": "call", "metric": "audio_sec", "unitPrice": "500", "perUnits": 60},
        {"component": "search", "metric": "units", "unitPrice": "910"},
    ]
    for d in dong:
        r = await app_client.post(f"{BASE}/price-versions/{pb}/items", headers=TOKEN, json=d)
        assert r.status_code == 201, r.text
    return pb


async def test_kich_hoat_thanh_cong_khi_du_12_dong(app_client, monkeypatch, pool) -> None:
    """Đường THÀNH CÔNG của `kich_hoat` — chưa bài nào canh trước bản vá này.

    Cũng canh luôn ca wildcard-thoả-basis-cụ-thể (xem docstring
    `_tao_bang_gia_day_du`): nếu kích hoạt ở đây mà FAIL, đó là bug thật của
    `kich_hoat`, không phải của bài test.
    """
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    pb = await _tao_bang_gia_day_du(app_client, "pv_act_ok")
    try:
        r = await app_client.post(f"{BASE}/price-versions/{pb}/activate", headers=TOKEN)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"
        async with pool.acquire() as conn:
            trang_thai = await conn.fetchval("SELECT status FROM billing.price_version WHERE id = $1", pb)
        assert trang_thai == "active"
    finally:
        await _don_price_version(pool, pb)


async def test_kich_hoat_tu_choi_khi_thieu_dong_gia(app_client, monkeypatch, pool) -> None:
    """Đường TỪ CHỐI của `kich_hoat` — chưa bài nào canh trước bản vá này.

    Canh CẢ HAI vế: mã lỗi/409 (dễ), VÀ trạng thái DB vẫn `'inactive'` sau đó
    (vế quan trọng hơn — một cổng trả 409 mà vẫn lặng lẽ kích hoạt là kết quả
    tệ nhất có thể, tệ hơn cả không có cổng).
    """
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    r = await app_client.post(
        f"{BASE}/price-versions", headers=TOKEN, json={"code": "pv_act_lo", "name": "lỗ", "currency": "VND"}
    )
    pb = r.json()["id"]
    try:
        # Chỉ khai 4 dòng llm — bỏ hẳn 7 basis còn lại (embed/stt×2/tts/vad/speaker_verify/call).
        for metric, gia in (
            ("input_tokens", "2500"),
            ("output_tokens", "10000"),
            ("cache_write_tokens", "0"),
            ("cache_read_tokens", "625"),
        ):
            r = await app_client.post(
                f"{BASE}/price-versions/{pb}/items",
                headers=TOKEN,
                json={"component": "llm", "metric": metric, "unitPrice": gia, "perUnits": 1000000},
            )
            assert r.status_code == 201, r.text

        r = await app_client.post(f"{BASE}/price-versions/{pb}/activate", headers=TOKEN)
        assert r.status_code == 409, r.text
        assert "chưa có dòng giá cho" in r.json()["error"]["message"]

        async with pool.acquire() as conn:
            trang_thai = await conn.fetchval("SELECT status FROM billing.price_version WHERE id = $1", pb)
        assert trang_thai == "inactive", "409 nhưng vẫn kích hoạt — cửa chặn tệ nhất có thể"
    finally:
        await _don_price_version(pool, pb)


async def test_preview_khong_ghi_gi(app_client, monkeypatch, pool, workspace_billing) -> None:
    """Preview áp bảng giá nháp lên usage 30 ngày — phải KHÔNG để lại dòng nào."""
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    r = await app_client.post(
        f"{BASE}/price-versions", headers=TOKEN, json={"code": "pv_prev", "name": "preview", "currency": "VND"}
    )
    pb = r.json()["id"]
    try:
        r = await app_client.get(f"{BASE}/price-versions/{pb}/preview", headers=TOKEN, params={"tenant": "bilw"})
        assert r.status_code == 200, r.text
        assert "chiPhi" in r.json()
    finally:
        await _don_price_version(pool, pb)


async def test_preview_khop_rated_usage_khi_dang_hieu_luc(pool, workspace_billing, bang_gia_vi_du) -> None:
    """Cổng chống TRÔI (yêu cầu chính của Task 9 quanh `billing.preview_price_version`).

    `rate_usage()` (ghi tiền thật, SECURITY DEFINER) và `preview_price_version()`
    (chỉ SELECT, dùng cho màn admin) mirror CÙNG một khuôn khớp giá — CROSS JOIN
    `billing.metric` + LATERAL chọn dòng giá cụ thể nhất + lọc `billing.purpose`
    billable. Với đúng bảng giá ĐANG hiệu lực cho tenant, hai cách tính PHẢI ra
    cùng một số; lệch nhau nghĩa là một trong hai bản đã trôi khỏi bản kia và
    preview đang nói dối admin về số tiền thật trước khi họ bấm activate.

    ⚠️ ĐIỂM MÙ đã vá (review): fixture `workspace_billing` chỉ phát sinh purpose
    BILLABLE (`conversation`/`summary`/`stream`/`session`), nên vế
    `coalesce(pu.billable, true)` của cả hai hàm SQL không có dữ liệu nào để lọc
    — xoá hẳn vế đó khỏi `preview_price_version` mà bài canh vẫn xanh. Tự chèn
    MỘT event `llm` mang `purpose='warm_cache'` (billable=false theo seed
    `billing.purpose` của `0943`) với token thật > 0 và khớp đúng dòng giá
    wildcard-purpose của `bang_gia_vi_du` — nếu vế billable bị xoá ở MỘT bên,
    event này bị định giá ở bên đó mà không bên kia, và bài canh phải đỏ.
    """
    tu, den = datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, turn_idx, component, purpose,
                provider, model, input_tokens, output_tokens, cache_write_tokens,
                cache_read_tokens, audio_sec, wall_ms, units, exact, occurred_at)
               VALUES ($1,$2,'voice',99,99,'llm','warm_cache','gemini',
                       'gemini-2.5-flash',5000,200,0,0,0,0,0,true,$3)""",
            TENANT,
            SESSION,
            MOC,
        )
        await conn.execute("SELECT billing.rate_usage($1, $2, $3)", tu, den, TENANT)
        tien_that = await conn.fetchval(
            "SELECT coalesce(sum(amount), 0) FROM billing.rated_usage WHERE tenant_id = $1", TENANT
        )
        tien_preview = await conn.fetchval(
            "SELECT billing.preview_price_version($1, $2, $3, $4)", bang_gia_vi_du, TENANT, tu, den
        )
    assert tien_that > 0, "bảng giá ví dụ phải sinh ra tiền — nếu không bài canh này không canh gì cả"
    assert tien_preview == tien_that, (
        f"preview={tien_preview} nhưng rated_usage thật={tien_that} — hai khuôn khớp giá đã trôi nhau"
    )


async def test_preview_khop_rated_usage_khi_thuong_so_khong_chia_het(pool, workspace_billing, bang_gia_vi_du) -> None:
    """qty 100 / per_units 60 (call: 500đ/60s) = 833,333... KHÔNG chia hết trong
    10 chữ số thập phân.

    `rate_usage()` lưu TỪNG event vào cột `numeric(20,10)` (làm tròn ở đó)
    trước khi cộng ở nơi khác; `preview_price_version()` phải làm tròn TỪNG
    dòng đúng như vậy trước khi `sum()`, không phải cộng ở độ chính xác đầy đủ
    rồi ra một số khác `rated_usage` đúng một hạt làm tròn. Mọi thương số của
    fixture gốc chia hết gọn nên không bài nào trước đây bắt được lệch này.
    """
    tu, den = datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose,
                provider, model, audio_sec, occurred_at)
               VALUES ($1, $2, 'voice', 100, 'call', 'session', '', '', 100, $3)""",
            TENANT,
            SESSION,
            MOC,
        )
        await conn.execute("SELECT billing.rate_usage($1, $2, $3)", tu, den, TENANT)
        tien_that = await conn.fetchval(
            "SELECT coalesce(sum(amount), 0) FROM billing.rated_usage WHERE tenant_id = $1", TENANT
        )
        tien_preview = await conn.fetchval(
            "SELECT billing.preview_price_version($1, $2, $3, $4)", bang_gia_vi_du, TENANT, tu, den
        )
    assert tien_preview == tien_that, (
        f"preview={tien_preview} nhưng rated_usage thật={tien_that} — thương số không chia hết "
        "làm lộ lệch làm tròn giữa hai hàm (preview phải round(..., 10) TỪNG dòng trước khi sum)"
    )


async def test_gan_bo_gia_dong_khoang_cu_khong_ho_khong_chong(app_client, monkeypatch, pool, workspace_billing) -> None:
    """Đóng khoảng cũ và mở khoảng mới ở CÙNG MỘT MỐC.

    Lệch mốc theo hai chiều đều sai và đều im lặng:
    · để hở  ⇒ usage rơi vào khe không bộ giá nào phủ ⇒ rate_usage bỏ qua ⇒ MIỄN PHÍ
    · chồng  ⇒ hai bộ cùng hiệu lực ⇒ EXCLUDE constraint ném (đây là chiều AN TOÀN,
               nó ồn ào chứ không âm thầm)
    """
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    ids = []
    for code in ("pv_g1", "pv_g2"):
        r = await app_client.post(
            f"{BASE}/price-versions", headers=TOKEN, json={"code": code, "name": code, "currency": "VND"}
        )
        ids.append(r.json()["id"])

    try:
        await _don_rated_usage(pool)
        for pv, tu in zip(ids, ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"), strict=True):
            r = await app_client.post(
                f"{BASE}/tenants/{TENANT}/price-version",
                headers=TOKEN,
                json={"priceVersionId": pv, "effectiveFrom": tu},
            )
            assert r.status_code == 200, r.text

        async with pool.acquire() as conn:
            hang = await conn.fetch(
                "SELECT price_version_id, effective_from, effective_to FROM billing.tenant_price_version "
                "WHERE tenant_id = $1 ORDER BY effective_from",
                TENANT,
            )
        assert len(hang) == 2
        assert hang[0]["effective_to"] == hang[1]["effective_from"], (
            "khoảng cũ không đóng đúng mốc mở của khoảng mới — có hở hoặc có chồng"
        )
        assert hang[1]["effective_to"] is None, "khoảng đang chạy phải để NULL"
    finally:
        await _don_price_version(pool, *ids)


async def test_gan_moc_truoc_khoang_dang_mo_tra_409(app_client, monkeypatch, pool, workspace_billing) -> None:
    """Khoảng đang mở bắt đầu ở TƯƠNG LAI; gán một mốc mới TRƯỚC mốc đó bằng
    cách đóng khoảng kia mù quáng sẽ vi phạm CHECK(effective_to > effective_from)
    — phải thành 409 đọc được, không phải 500 CheckViolationError thô.
    """
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    ids = []
    for code in ("pv_fut1", "pv_fut2"):
        r = await app_client.post(
            f"{BASE}/price-versions", headers=TOKEN, json={"code": code, "name": code, "currency": "VND"}
        )
        ids.append(r.json()["id"])
    try:
        await _don_rated_usage(pool)
        # Mở một khoảng bắt đầu ở TƯƠNG LAI — vẫn "đang mở" (effective_to NULL).
        r = await app_client.post(
            f"{BASE}/tenants/{TENANT}/price-version",
            headers=TOKEN,
            json={"priceVersionId": ids[0], "effectiveFrom": "2027-01-01T00:00:00Z"},
        )
        assert r.status_code == 200, r.text

        # Gán một mốc TRƯỚC mốc tương lai đó.
        r = await app_client.post(
            f"{BASE}/tenants/{TENANT}/price-version",
            headers=TOKEN,
            json={"priceVersionId": ids[1], "effectiveFrom": "2026-08-01T00:00:00Z"},
        )
        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "MOC_TRUOC_KHOANG_DANG_MO"

        async with pool.acquire() as conn:
            so_dong = await conn.fetchval(
                "SELECT count(*) FROM billing.tenant_price_version WHERE tenant_id = $1", TENANT
            )
        assert so_dong == 1, "409 nhưng vẫn ghi thêm dòng — service phải bung TRƯỚC khi UPDATE/INSERT"
    finally:
        await _don_price_version(pool, *ids)


async def test_gan_moc_qua_khu_bi_chan(app_client, monkeypatch, pool, workspace_billing, bang_gia_vi_du) -> None:
    """Gán lùi vào một kỳ đã định giá là viết lại tiền quá khứ.

    ⚠️ Sửa so với brief: bản gốc không có `workspace_billing`/`bang_gia_vi_du` và
    không gọi `rate_usage()` trước — nếu chạy file này ĐỘC LẬP (không kế thừa
    dữ liệu sót lại từ bài chạy trước trong cùng phiên), tenant `bilw` chưa từng
    tồn tại VÀ `billing.rated_usage` rỗng, nên phép kiểm "đã định giá quá khứ"
    luôn False và request rơi thẳng vào `ForeignKeyViolationError` (500) thay vì
    409 — bài test phụ thuộc thứ tự chạy một cách âm thầm. Dựng dữ liệu tường
    minh: tenant thật + usage đã `rate_usage()` trước khi gán lùi.
    """
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "test-admin-token")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)", TENANT
        )
    r = await app_client.post(
        f"{BASE}/price-versions", headers=TOKEN, json={"code": "pv_g3", "name": "g3", "currency": "VND"}
    )
    pv = r.json()["id"]
    try:
        r = await app_client.post(
            f"{BASE}/tenants/{TENANT}/price-version",
            headers=TOKEN,
            json={"priceVersionId": pv, "effectiveFrom": "2020-01-01T00:00:00Z"},
        )
        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "MOC_QUA_KHU_DA_DINH_GIA"
    finally:
        await _don_price_version(pool, pv)
