"""`GET /billing/usage-by-day` + sáu cột lượng mới của `/billing/by-owner`.

Nguồn của thẻ biểu đồ màn `/usage` (spec `2026-08-24-man-usage-bay-tab-design.md`).

Bài quan trọng nhất là `test_khong_nhan_ban_so_do_qua_rated_usage`: nó là bài
DUY NHẤT ở đây đỏ khi ai đó "tối ưu" hai CTE thành một JOIN. Và nó tự chứng
minh tiền đề của chính nó — đếm `rated_usage` của một event LLM để cho thấy hệ
số nhân bản là THẬT chứ không phải giả định của người viết test.
"""

from datetime import date, timedelta

import asyncpg

from portal.modules.billing import repo
from tests.modules.billing.conftest import MAT_KHAU, MOC, TENANT, USER_ID

BASE = "/api/v1/billing"

TU = date(2026, 8, 1)
DEN = date(2026, 9, 1)
NGAY_CO = MOC.date()  # 2026-08-19 — mọi event của fixture nằm trong đúng ngày này
SO_NGAY = (DEN - TU).days  # 31

# Số đo mong đợi của NGÀY CÓ DỮ LIỆU, cộng tay từ `conftest._chen_usage`.
# Đừng "tính lại bằng SQL" trong test — làm thế là để cùng một câu SQL vừa là
# thứ được kiểm vừa là thước đo, và bug nhân bản sẽ đi qua cả hai vế.
LLM_IN = 113_674
LLM_OUT = 547
LLM_CACHE = 35_548
CALL_GIAY = 142.44
VAD_GIAY = 141.44
TTS_KY_TU = 1115
# Tổng `audio_sec` cộng CHÉO mọi component — con số KHÔNG TỒN TẠI, để đối chứng.
AUDIO_CONG_CHEO = CALL_GIAY + VAD_GIAY + 81.72 + 10.21 + 10.57


async def _dang_nhap(client) -> None:
    """Đăng nhập RỒI chuyển sang đúng `TENANT` — xem docstring cùng tên ở
    `test_router.py`: `workspace_billing` dựng membership ở CẢ HAI tenant và
    `dang_nhap()` chọn theo alphabet, tức mặc định rơi vào tenant SAI."""
    r = await client.post("/api/v1/auth/login", json={"email": "bil@noblex.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r2 = await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT})
    assert r2.status_code == 200, r2.text


def _ngay(d: dict, iso: str) -> dict:
    return next(x for x in d["theo_ngay"] if x["ngay"] == iso)


def _phan(ngay: dict, component: str) -> dict:
    return next(x for x in ngay["phan"] if x["component"] == component)


async def test_moi_ngay_cua_ky_deu_co_hang(app_client, workspace_billing) -> None:
    """Bất biến số 2 của `repo.usage_theo_ngay()`: ngày KHÔNG có usage vẫn phải
    có một phần tử, với `phan` rỗng và `so_phien = 0`.

    Trả thưa thì FE nối thẳng hai điểm hai bên chỗ trũng — ngày agent không chạy
    được vẽ thành một đoạn dốc ĐI QUA mức dương, tức biểu đồ nói sai đúng cái nó
    sinh ra để nói.
    """
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/usage-by-day", params={"from": TU.isoformat(), "to": DEN.isoformat()})
    assert r.status_code == 200, r.text
    d = r.json()

    assert len(d["theo_ngay"]) == SO_NGAY, "thiếu ngày — generate_series bị bỏ?"
    assert [x["ngay"] for x in d["theo_ngay"]] == [(TU + timedelta(days=i)).isoformat() for i in range(SO_NGAY)], (
        "ngày không liên tục hoặc không sắp tăng"
    )

    trong = _ngay(d, NGAY_CO.isoformat())
    assert trong["so_phien"] == 1
    assert len(trong["phan"]) == 6, "6 component của fixture (không có embed)"

    ngoai = [x for x in d["theo_ngay"] if x["ngay"] != NGAY_CO.isoformat()]
    assert all(x["phan"] == [] for x in ngoai), "ngày rỗng lại có component?"
    assert all(x["so_phien"] == 0 for x in ngoai)


async def test_khong_nhan_ban_so_do_qua_rated_usage(app_client, pool: asyncpg.Pool, workspace_billing) -> None:
    """Bất biến số 1: đọc `usage_events` một mình, KHÔNG `JOIN rated_usage`.

    Một event LLM sinh NHIỀU hàng `rated_usage` (một hàng mỗi metric có giá),
    nên JOIN rồi `sum(input_tokens)` nhân số đo lên đúng số hàng đó. Bài này
    trước hết ĐO hệ số nhân bản thật trên DB (không giả định 4), rồi khẳng định
    số đo trả về vẫn là số cộng tay từ fixture.

    ⚠️ KHÔNG gọi `billing.rate_usage()` — trigger `usage_events_dinh_gia`
    (`0950`) đã định giá ngay trong câu INSERT của fixture. Gọi thêm là kiểm mất
    chính đường đang chạy ở production.
    """
    async with pool.acquire() as conn:
        nhan_ban = await conn.fetchval(
            """SELECT count(*) FROM billing.rated_usage r
                WHERE r.tenant_id = $1
                  AND r.event_id = (SELECT min(event_id) FROM billing.usage_events
                                     WHERE tenant_id = $1 AND component = 'llm')""",
            TENANT,
        )
    assert nhan_ban >= 2, (
        f"tiền đề của bài này không còn đúng: một event LLM chỉ sinh {nhan_ban} hàng rated_usage, "
        "nên phép JOIN sai sẽ không còn nhân bản và bài này thôi bảo vệ được gì"
    )

    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/usage-by-day", params={"from": TU.isoformat(), "to": DEN.isoformat()})
    llm = _phan(_ngay(r.json(), NGAY_CO.isoformat()), "llm")

    assert llm["input_tokens"] == LLM_IN, f"số đo bị nhân bản ×{llm['input_tokens'] / LLM_IN:.2f}?"
    assert llm["output_tokens"] == LLM_OUT
    assert llm["cache_read_tokens"] == LLM_CACHE
    assert llm["so_event"] == 7


async def test_so_do_dung_don_vi_cua_tung_component(app_client, workspace_billing) -> None:
    """Mỗi component chở đúng số đo của cơ sở tính tiền của nó, và KHÔNG có chỗ
    nào cộng `audio_sec` chéo component.

    `AUDIO_CONG_CHEO` (386,38s) là con số sai đã đo được thật khi cộng chéo — nó
    ở đây làm đối chứng: `call` phải là 142,44s, không phải nó.
    """
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/usage-by-day", params={"from": TU.isoformat(), "to": DEN.isoformat()})
    ngay = _ngay(r.json(), NGAY_CO.isoformat())

    assert abs(_phan(ngay, "call")["audio_sec"] - CALL_GIAY) < 0.01
    assert abs(_phan(ngay, "vad")["audio_sec"] - VAD_GIAY) < 0.01
    assert _phan(ngay, "tts")["text_units"] == TTS_KY_TU, "TTS tính theo KÝ TỰ (0948), không theo giây"

    tong = sum(p["audio_sec"] for p in ngay["phan"])
    assert abs(tong - AUDIO_CONG_CHEO) < 0.05, "tiền đề đổi: các component của fixture không còn cộng chéo ra 386,38s"
    assert abs(_phan(ngay, "call")["audio_sec"] - AUDIO_CONG_CHEO) > 1, (
        "voice_sec/`call` đang mang tổng cộng chéo — đúng bug BE đã gỡ ở 9d78d04"
    )


async def test_so_phien_cung_dinh_nghia_voi_summary(app_client, workspace_billing) -> None:
    """Bất biến số 4. Tooltip biểu đồ và dải KPI đọc hai endpoint khác nhau; nếu
    hai chỗ đếm phiên theo hai định nghĩa thì chúng in hai số khác nhau về cùng
    một thứ và người đọc kết luận cả hai đều sai.

    So trên cửa sổ MỘT NGÀY để hai con số nói về đúng cùng một tập.
    """
    await _dang_nhap(app_client)
    mot_ngay = {"from": NGAY_CO.isoformat(), "to": (NGAY_CO + timedelta(days=1)).isoformat()}

    r1 = await app_client.get(f"{BASE}/summary", params=mot_ngay)
    r2 = await app_client.get(f"{BASE}/usage-by-day", params=mot_ngay)
    assert r1.status_code == 200 and r2.status_code == 200

    theo_ngay = r2.json()["theo_ngay"]
    assert len(theo_ngay) == 1
    assert theo_ngay[0]["so_phien"] == r1.json()["so_phien"]


async def test_khong_tra_truong_tien_nao(app_client, workspace_billing) -> None:
    """`/usage` là màn LƯỢNG — endpoint này không được chở một đồng nào.

    Canh chiều NGƯỢC (thứ KHÔNG được có), vì thêm `chi_phi` vào đây là thứ trông
    như một tiện ích vô hại: nó sẽ không làm bài nào đỏ, và sáu tháng sau ai đó
    vẽ tiền lên `/usage` vì "dữ liệu có sẵn rồi".
    """
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/usage-by-day", params={"from": TU.isoformat(), "to": DEN.isoformat()})
    assert not any(k in r.text for k in ("chi_phi", "currency", "amount")), (
        "endpoint của màn LƯỢNG đang trả trường tiền"
    )


async def test_khoang_khong_hop_le_422(app_client, workspace_billing) -> None:
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/usage-by-day", params={"from": "2026-09-01", "to": "2026-08-01"})
    assert r.status_code == 422, r.text


async def test_khong_dang_nhap_thi_401(app_client, workspace_billing) -> None:
    r = await app_client.get(f"{BASE}/usage-by-day")
    assert r.status_code == 401


async def test_cach_ly_tenant(api_dsn: str, workspace_billing) -> None:
    """Đọc NGOÀI `tenant_conn()` trả 0 hàng — chế độ hỏng im lặng của Luật 1.

    Ở đây nó có hình dạng riêng đáng neo: `generate_series` vẫn sinh đủ 31 ngày,
    nên endpoint trả một chuỗi ngày ĐẦY ĐỦ mà mọi ngày đều rỗng — «tenant này
    chưa dùng gì», không phải một lỗi.
    """
    conn = await asyncpg.connect(api_dsn)
    try:
        hang = await repo.usage_theo_ngay(conn, TU, DEN)
    finally:
        await conn.close()
    assert len(hang) == SO_NGAY
    assert all(r["component"] is None for r in hang)


async def test_by_owner_co_du_cot_luong_va_khop_by_key(app_client, pool: asyncpg.Pool, workspace_billing) -> None:
    """Sáu cột lượng mới của `by-owner` phải khớp TỔNG của `by-key`.

    Phép so chéo này bắt được CẢ HAI lớp lỗi cùng lúc: nhân bản số đo (owner lớn
    hơn key) và mất hàng vì bảng dẫn sai (owner nhỏ hơn key — `theo_owner` từng
    `FROM tien`, nên owner có usage chưa được định giá biến mất khỏi bảng).
    """
    await _dang_nhap(app_client)
    kw = {"from": TU.isoformat(), "to": DEN.isoformat()}
    rk = await app_client.get(f"{BASE}/by-key", params=kw)
    ro = await app_client.get(f"{BASE}/by-owner", params=kw)
    assert rk.status_code == 200 and ro.status_code == 200, ro.text
    keys, owners = rk.json()["items"], ro.json()

    for cot in ("input_tokens", "output_tokens", "cache_read_tokens", "so_event", "so_phien"):
        assert sum(o[cot] for o in owners) == sum(k[cot] for k in keys), f"cột `{cot}` lệch giữa hai chiều gộp"
    assert abs(sum(o["voice_sec"] for o in owners) - sum(k["voice_sec"] for k in keys)) < 0.01


async def test_by_owner_voice_sec_chi_dem_component_call(app_client, workspace_billing) -> None:
    """`voice_sec` = thời lượng CUỘC GỌI, không phải tổng `audio_sec` mọi component.

    Cộng chéo ra 386,38s cho một cuộc gọi thật 142,44s (đo được, BE gỡ ở
    `9d78d04`) — bốn quãng audio chồng lấn nhau trong thời gian.
    """
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/by-owner", params={"from": TU.isoformat(), "to": DEN.isoformat()})
    dong = next(o for o in r.json() if o["user_id"] == USER_ID)
    assert abs(dong["voice_sec"] - CALL_GIAY) < 0.01, (
        f"voice_sec = {dong['voice_sec']}; cộng chéo mọi component ra {AUDIO_CONG_CHEO:.2f}"
    )


async def test_by_owner_giu_owner_chua_co_gia(app_client, pool: asyncpg.Pool, workspace_billing) -> None:
    """Owner có SỐ ĐO mà chưa có TIỀN vẫn phải hiện, với `chi_phi = 0`.

    `theo_owner` từng lấy `billing.rated_usage` làm bảng dẫn, nên một component
    không nằm trong bảng giá (`usage_events.component` là `text`, không CHECK)
    làm owner đó biến khỏi bảng CÙNG toàn bộ số đo của họ — ẩn đúng phần đang
    mất doanh thu, đúng lỗi `theo_component()` phải đảo vế để tránh.

    Dựng bằng một component lạ trong một session KHÔNG có `conversations` (nhóm
    `agent_key_id IS NULL`) để không phụ thuộc bảng giá seed.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO billing.usage_events
               (tenant_id, session_id, channel, seq, component, purpose,
                input_tokens, units, occurred_at)
               VALUES ($1, 'bil-sess-la', 'chat', 0, 'thanh_phan_la', 'conversation', 4242, 1, $2)""",
            TENANT,
            MOC,
        )
        con_gia = await conn.fetchval(
            "SELECT count(*) FROM billing.rated_usage WHERE tenant_id = $1 AND component = 'thanh_phan_la'",
            TENANT,
        )
    assert con_gia == 0, "component lạ lại có giá — bài này mất tiền đề"

    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/by-owner", params={"from": TU.isoformat(), "to": DEN.isoformat()})
    assert sum(o["input_tokens"] for o in r.json()) >= LLM_IN + 4242, (
        "số đo của component chưa có giá bị ẩn khỏi bảng theo owner"
    )


# ── Hai vế LỌC THEO `purpose` của tab STT (dòng phụ + đường thứ hai) ──────────
# Bất biến 5 của `repo.usage_theo_ngay()`.


async def test_wall_ms_stream_khong_gom_purpose_khac(app_client, workspace_billing) -> None:
    """`wall_ms_stream` chỉ đếm `purpose='stream'` — KHÔNG cộng cả component.

    Đây là bài đỏ khi ai đó bỏ mệnh đề `FILTER`. Bên agent ghi `wall_ms` cho
    MỌI event như một độ trễ xử lý, nên `stt` có wall_ms ở cả hai purpose
    (fixture: 142.776,8 ms ở `stream` + 335,0 ms ở `conversation`). Cộng cả hai
    rồi gắn nhãn «stream» là bày một con số không có nghĩa nào trong
    `billing.pricing_basis` — ở đó `wall_ms` chỉ được khai cho (`stt`,`stream`).

    Bài KHÔNG chỉ so với 142.776,8: nó còn khẳng định con số ĐÚNG khác con số
    SAI. Không có vế đó thì fixture đổi về wall_ms = 0 ở dòng conversation là
    bài xanh trở lại mà chẳng canh gì nữa.
    """
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/usage-by-day", params={"from": TU.isoformat(), "to": DEN.isoformat()})
    assert r.status_code == 200, r.text
    stt = _phan(_ngay(r.json(), NGAY_CO.isoformat()), "stt")

    assert stt["wall_ms_stream"] == 142_776.8, "gộp cả purpose khác vào vế `stream`?"
    assert stt["wall_ms_stream"] != 142_776.8 + 335.0, "đúng con số của phép cộng SAI — mệnh đề FILTER bị bỏ"


async def test_text_units_hoi_thoai_la_ve_doc_lap_cua_stt(app_client, workspace_billing) -> None:
    """`text_units_hoi_thoai` = ký tự transcript của `purpose='conversation'`.

    Vế ký tự của `stt` là ĐỘC LẬP với vế thời lượng (migration `0948`): vendor
    kiểu Soniox thu hai đồng hồ. Nó KHÔNG thay `text_units` — cột đó vẫn là số
    đo chính của `tts`/`embed`, và với `tts` hai cột phải bằng nhau vì mọi dòng
    `tts` đều mang `purpose='conversation'`.
    """
    await _dang_nhap(app_client)
    r = await app_client.get(f"{BASE}/usage-by-day", params={"from": TU.isoformat(), "to": DEN.isoformat()})
    ngay = _ngay(r.json(), NGAY_CO.isoformat())

    assert _phan(ngay, "stt")["text_units_hoi_thoai"] == 240
    assert _phan(ngay, "tts")["text_units_hoi_thoai"] == TTS_KY_TU == _phan(ngay, "tts")["text_units"]
    # `call` không có purpose nào trong hai cái trên ⇒ 0, KHÔNG phải null:
    # `sum() FILTER` không khớp hàng nào trả NULL, và NULL ra tới response là
    # `ValidationError` ở tầng Pydantic.
    call = _phan(ngay, "call")
    assert (call["wall_ms_stream"], call["text_units_hoi_thoai"]) == (0.0, 0)
