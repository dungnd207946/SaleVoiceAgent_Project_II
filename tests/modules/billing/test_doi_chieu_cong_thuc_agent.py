"""CỔNG VÀNG — engine bảng giá phải ra CÙNG SỐ với công thức bên agent bàn giao.

Nguồn công thức: docs/build_module_usage&billing/portal-billing-pricing-guide-handoff-from-agent.md §4
Query dưới đây chép từ §4 đó, chỉ bỏ GROUP BY để lấy một tổng.

VÌ SAO BÀI NÀY TỒN TẠI: Portal không tính tiền bằng khối CASE của họ, mà bằng bảng
giá + độ ưu tiên khớp. Hai cách hoàn toàn khác nhau về cấu trúc, nên "trông có vẻ
đúng" là không đủ — cần một phép so số học trên cùng dữ liệu. Bài này đã chạy thật
và ra CÙNG một số ở cả hai bên trước khi được viết vào plan.

Hai phép so, khác vai:
· `cua_portal == cua_agent` — phép so CHÍNH, tự kiểm, đúng bất kể fixture đổi.
· `cua_portal == TIEN_MONG_DOI` — cổng chống fixture trôi. Nếu ai sửa số trong
  `_chen_usage` mà quên sửa hằng thì bài này đỏ, đúng như mong muốn.

Nó đỏ nếu ai: đổi thứ tự ưu tiên khớp giá · đổi nghĩa per_units (per_units THẬT SỰ
được canh, qua llm 1e6 và call 60) · bật billable cho một nhãn giá vốn · vô tình
cộng audio_sec chéo component.

⚠️ KHÔNG đỏ nếu bỏ metric `wall_ms`: dòng giá `(stt,'stream')/wall_ms` trong
`bang_gia_vi_du` có `unit_price = 0` (STT thu theo giây, không theo wall_ms —
xem docstring fixture đó), nên xoá metric này chỉ đổi SỐ DÒNG `rated_usage`,
không đổi TỔNG tiền mà bài này canh. Một bản trước của docstring này khẳng định
sai điều ngược lại — sửa lại cho khớp cái bài thật sự bắt được.
"""

from decimal import Decimal

import asyncpg

from tests.modules.billing.conftest import TENANT

TIEN_MONG_DOI = Decimal("4145.26")

_QUERY_BEN_AGENT = """
WITH gia_audio AS (
  SELECT 10::numeric stt_per_sec, 0::numeric stt_per_stream_min,
         0.5::numeric stt_per_char_out, 2::numeric tts_per_char,
         1::numeric vad_per_sec, 5::numeric sv_per_sec, 500::numeric call_per_min),
gia_llm(provider, model, in_1m, out_1m, cw_1m, cr_1m) AS (
  VALUES ('gemini', 'gemini-2.5-flash', 2500::numeric, 10000::numeric, 0::numeric, 625::numeric)),
nhan_tinh(purpose) AS (
  VALUES ('conversation'), ('summary'), ('suggestions'), ('embed'), ('stream'), ('session'))
SELECT round(sum(CASE u.component
    WHEN 'llm' THEN (u.input_tokens * l.in_1m + u.output_tokens * l.out_1m
                   + u.cache_write_tokens * l.cw_1m + u.cache_read_tokens * l.cr_1m) / 1e6
    WHEN 'stt' THEN CASE u.purpose
                        WHEN 'conversation' THEN u.audio_sec * a.stt_per_sec
                                                 + u.text_units * a.stt_per_char_out
                        WHEN 'stream'       THEN u.wall_ms / 60000.0 * a.stt_per_stream_min
                    END
    WHEN 'tts'            THEN u.text_units * a.tts_per_char
    WHEN 'vad'            THEN u.audio_sec * a.vad_per_sec
    WHEN 'speaker_verify' THEN u.audio_sec * a.sv_per_sec
    WHEN 'call'           THEN u.audio_sec / 60.0 * a.call_per_min
  END)::numeric, 2)
FROM billing.usage_events u
CROSS JOIN gia_audio a
LEFT JOIN gia_llm l ON u.component = 'llm' AND l.provider = u.provider AND l.model = u.model
WHERE u.tenant_id = $1 AND u.purpose IN (SELECT purpose FROM nhan_tinh)
"""


async def test_engine_khop_cong_thuc_ben_agent(pool: asyncpg.Pool, workspace_billing, bang_gia_vi_du) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
            TENANT,
        )
        cua_portal = await conn.fetchval(
            "SELECT round(sum(amount), 2) FROM billing.rated_usage WHERE tenant_id = $1",
            TENANT,
        )
        cua_agent = await conn.fetchval(_QUERY_BEN_AGENT, TENANT)

    assert cua_portal == cua_agent, f"engine Portal ra {cua_portal}, công thức bên agent ra {cua_agent}"
    assert cua_portal == TIEN_MONG_DOI, f"ra {cua_portal}, mong đợi {TIEN_MONG_DOI} — dữ liệu fixture đã đổi?"


async def test_khong_cong_audio_sec_cheo_component(pool: asyncpg.Pool, workspace_billing, bang_gia_vi_du) -> None:
    """Bẫy §5.1 của bên agent: vad/call/stt đo những quãng audio CHỒNG LẤN.

    Cấu trúc rated_usage làm việc cộng gộp đó bất khả thi — mỗi dòng gắn một
    component. Bài này neo bất biến đó: tổng audio_sec của call KHÔNG được bằng
    tổng audio_sec toàn bảng.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT billing.rate_usage('2000-01-01'::timestamptz, '2100-01-01'::timestamptz, $1)",
            TENANT,
        )
        theo_component = await conn.fetch(
            "SELECT component, sum(quantity) q FROM billing.rated_usage "
            "WHERE tenant_id = $1 AND metric = 'audio_sec' GROUP BY 1",
            TENANT,
        )
    d = {r["component"]: r["q"] for r in theo_component}
    assert d["call"] < d["vad"] + d["stt"] + d["speaker_verify"], (
        "call phải NHỎ HƠN tổng các đồng hồ con — nếu không, giả định chồng lấn đã sai"
    )
