import json
from datetime import UTC, datetime, timedelta

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.web.signal import asked_codes, load_projects

from .conftest import NPTTL, OTHER, TENANT

pytestmark = pytest.mark.integration


async def _msg(pool, tenant, seq, *, role="assistant", content="", tool=None, args=None, created_at=None):
    meta = (
        {"tool_calls": [{"function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}]}
        if tool
        else {}
    )
    async with tenant_conn(pool, tenant) as c:
        await c.execute(
            """INSERT INTO tenant_data.conversation_messages
                   (tenant_id, session_id, seq, role, content, created_at, meta)
               VALUES ($1, 's1', $2, $3, $4, $5, $6::jsonb)""",
            tenant,
            seq,
            role,
            content,
            created_at or datetime.now(UTC),
            json.dumps(meta),
        )


async def test_load_projects_chi_published_cua_tenant(web_tenant, api_pool):
    async with tenant_conn(api_pool, TENANT) as c:
        rows = await load_projects(c)
    assert [(r.code, r.name) for r in rows] == [("NPTTL", NPTTL)]
    assert "Đan Phượng" in rows[0].facts


async def test_khong_co_log_thi_coi_moi_du_an_la_duoc_hoi(web_tenant, api_pool):
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == {"NPTTL"}


async def test_nhan_tu_tham_so_tool_va_khong_lan_tenant_khac(web_tenant, api_pool, pool):
    await _msg(pool, OTHER, 0, tool="find_project", args={"name": "Noble Palace Tây Thăng Long"})
    await _msg(pool, TENANT, 0, tool="find_project", args={"name": "Vinhomes Smart City"})
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == set()
    await _msg(pool, TENANT, 1, tool="kb_search", args={"query": "hạ tầng", "project_filter": "NPTTL"})
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == {"NPTTL"}


async def test_nhan_tu_cau_cua_khach(web_tenant, api_pool, pool):
    await _msg(pool, TENANT, 0, role="user", content="cho mình hỏi về noble palace tây thăng long")
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == {"NPTTL"}


# ─── Edge case bổ sung ngoài brief ──────────────────────────────────────────


async def test_qua_han_cua_so_thi_khong_tinh(web_tenant, api_pool, pool):
    """Một hàng lệch cửa sổ (mới hơn `days` ngày, không nằm trong window) không được tính,
    nhưng vẫn phải có mặt đủ để `total` > 0 — nếu không thì rơi vào nhánh "không log" và
    lại trả về TRUE cho mọi dự án, che mất chính điều đang canh."""
    old = datetime.now(UTC) - timedelta(days=40)
    await _msg(pool, TENANT, 0, tool="find_project", args={"name": NPTTL}, created_at=old)
    # một hàng TRONG cửa sổ, không liên quan tới NPTTL — đẩy total > 0 mà không tự khớp.
    await _msg(pool, TENANT, 1, role="user", content="xin chào")
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c), days=28) == set()


async def test_tool_ngoai_ASK_TOOLS_bi_bo_qua(web_tenant, api_pool, pool):
    await _msg(pool, TENANT, 0, tool="book_appointment", args={"name": NPTTL, "project_code": "NPTTL"})
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == set()


async def test_loi_assistant_khong_tinh_chi_loi_khach(web_tenant, api_pool, pool):
    """Chỉ câu chữ của KHÁCH (`role='user'`) được đối chiếu — lời AGENT nhắc tên dự án
    (vd đọc lại kết quả tìm kiếm) không phải là tín hiệu khách đang hỏi về nó."""
    await _msg(pool, TENANT, 0, role="assistant", content=f"Dạ, {NPTTL} đang mở bán giai đoạn 2 ạ.")
    # một hàng khách để total > 0 mà không khớp dự án nào.
    await _msg(pool, TENANT, 1, role="user", content="giá bao nhiêu vậy")
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == set()


async def test_khong_khop_bua_vao_tu_dai_hon(web_tenant, api_pool, pool):
    """`NPTTLX` chứa `NPTTL` làm tiền tố nhưng là một từ khác — không được khớp theo mã."""
    await _msg(pool, TENANT, 0, tool="find_project", args={"project_filter": "NPTTLX"})
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == set()


async def test_khop_theo_hot_word(web_tenant, api_pool, pool):
    async with tenant_conn(pool, TENANT) as c:
        pid = await c.fetchval("SELECT id FROM tenant_data.projects WHERE tenant_id = $1", TENANT)
        await c.execute(
            "INSERT INTO tenant_data.project_hot_words (tenant_id, project_id, hot_word) VALUES ($1, $2, 'MAGNOLIA')",
            TENANT,
            pid,
        )
    await _msg(pool, TENANT, 0, role="user", content="bên mình có căn nào ở magnolia không ạ")
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == {"NPTTL"}


async def test_hot_word_qua_ngan_bi_bo_qua(web_tenant, api_pool, pool):
    """Hot word dưới `MIN_HOT_WORD` (5 ký tự) không được dùng làm needle — tránh khớp bừa
    trên một từ ngắn phổ biến."""
    async with tenant_conn(pool, TENANT) as c:
        pid = await c.fetchval("SELECT id FROM tenant_data.projects WHERE tenant_id = $1", TENANT)
        await c.execute(
            "INSERT INTO tenant_data.project_hot_words (tenant_id, project_id, hot_word) VALUES ($1, $2, 'THE')",
            TENANT,
            pid,
        )
    await _msg(pool, TENANT, 0, role="user", content="the gia dinh toi muon hoi gia")
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == set()


async def test_arguments_hong_khong_lam_vo(web_tenant, api_pool, pool):
    """`arguments` không phải JSON hợp lệ (agent gửi lỗi/half-stream) không được ném lỗi —
    chỉ là một chuỗi không khớp gì."""
    async with tenant_conn(pool, TENANT) as c:
        await c.execute(
            """INSERT INTO tenant_data.conversation_messages
                   (tenant_id, session_id, seq, role, content, created_at, meta)
               VALUES ($1, 's1', 0, 'assistant', '', $2,
                       '{"tool_calls": [{"function": {"name": "find_project", "arguments": "{not json"}}]}'::jsonb)""",
            TENANT,
            datetime.now(UTC),
        )
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == set()


async def test_khong_co_hang_meta_tool_calls_khong_phai_mang_khong_vo(web_tenant, api_pool, pool):
    """`meta.tool_calls` là object thay vì mảng (dữ liệu dị dạng) không được làm vỡ
    `jsonb_array_elements` — phải rơi về không có tool call nào."""
    async with tenant_conn(pool, TENANT) as c:
        await c.execute(
            """INSERT INTO tenant_data.conversation_messages
                   (tenant_id, session_id, seq, role, content, created_at, meta)
               VALUES ($1, 's1', 0, 'assistant', '', $2, '{"tool_calls": {"oops": true}}'::jsonb)""",
            TENANT,
            datetime.now(UTC),
        )
    async with tenant_conn(api_pool, TENANT) as c:
        assert await asked_codes(c, await load_projects(c)) == set()
