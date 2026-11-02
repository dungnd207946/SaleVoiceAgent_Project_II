"""CỔNG 5 — quyền role. Canh điều kiện 2 và 3 của cách ly.

Cả hai hỏng ÂM THẦM: app chạy bình thường, chỉ dữ liệu là rò.
"""

import pytest

pytestmark = pytest.mark.integration

RUNTIME_ROLES = ("portal_api", "agent_all", "agent_t1", "agent_t2", "odyssey_agent")

# BẢNG `tenant_data` MÀ AGENT ĐƯỢC PHÉP GHI — RỖNG Ở M1, CÓ CHỦ Ý.
#
# `control.grant_agent_write('tenant_data.<bảng>')` là hàm M1 xuất ra (spec §8.1) để
# module sau mở đường GHI cho agent. Nó cấp SELECT/INSERT/UPDATE trên bảng đó cho role
# nhóm `agent_all`, và — bắt buộc, vì không có nó thì quyền bảng vô nghĩa — cấp cả
# USAGE trên schema `tenant_data`.
#
# VÌ SAO CÓ DANH SÁCH NÀY: bản trước của cổng này assert cứng
#     has_schema_privilege('agent_t1', 'tenant_data', 'USAGE') is False
# và quét đúng hai bảng `units` + `projects` viết cứng trong test. Hai hệ quả, cả hai xấu:
#   · module ĐẦU TIÊN gọi grant_agent_write() (M7, cho appointments/contacts) làm cổng
#     này đỏ — dù nó dùng đúng hàm mà spec §4 và docs/contracts/isolation.md §6.1 hứa
#     là cách chính thống. Test và hợp đồng đã mâu thuẫn nhau ngay từ hôm nay;
#   · quyền agent trên bảng `tenant_data` TƯƠNG LAI thì cổng không thấy — nó chỉ nhìn
#     hai cái tên viết cứng, nên một GRANT lỡ tay trên bảng của M4 đi qua không ai biết.
#
# Nên: quét ĐỘNG mọi bảng `tenant_data`, và mỗi module gọi grant_agent_write() thêm
# tên bảng của nó vào đây kèm lý do vì sao agent cần GHI bảng đó. Danh sách rỗng =
# đúng trạng thái M1: chưa module nào gọi hàm đó.
#
# LƯU Ý cho người thêm dòng đầu tiên: grant_agent_write() cho agent SELECT TRỰC TIẾP
# trên bảng gốc, tức bảng đó KHÔNG đi qua gate cột của `agent_api` nữa. Đó là chủ ý cho
# bảng write-back (agent ghi thì phải đọc lại được cái nó ghi), nhưng phải biết mà chọn.
AGENT_WRITABLE_TENANT_DATA_TABLES: set[str] = {
    # 0903 — ba bảng WRITE-BACK: agent tạo ra chính dữ liệu này trong lúc hội thoại
    # (hồ sơ số điện thoại · phiên hội thoại · lịch hẹn chốt được), nên nó phải ghi
    # được, và ghi rồi thì phải đọc lại được cái vừa ghi.
    #
    # HỆ QUẢ PHẢI BIẾT: ba bảng này agent có SELECT TRỰC TIẾP trên bảng gốc. Chấp nhận
    # được vì chúng không mang dữ liệu catalog của khách — không có cột nào ở đây mà
    # agent lẽ ra không được thấy. Nếu sau này thêm cột nhạy cảm (giá vốn, hoa hồng)
    # vào một trong ba bảng, thì phải tách bảng, không phải thêm cột.
    #
    # Cách ly vẫn nguyên: cả ba đều `enforce_tenant_isolation()` (RLS + FORCE RLS), nên
    # agent chỉ thấy hàng của tenant hiệu lực — cổng
    # `test_moi_bang_tenant_data_da_bat_cach_ly` quét động và canh đúng chỗ đó.
    "contacts",
    "conversations",
    "conversation_messages",
    "appointments",
    # 0924 — bảng WRITE-BACK thứ 5. Agent INSERT một hàng mỗi lần chuyển khách cho
    # sale rồi UPDATE `summary` khi bản LLM về; nó SELECT lại đúng hàng đó để biết
    # phiên đã chuyển chưa. Bốn cột `status`/`handled_*` là của Portal — agent có
    # quyền UPDATE cả bảng nên ranh giới đó do CODE giữ, không phải DB.
    "escalations",
}

# SELECT TRÊN TOÀN BỘ `tenant_data` LÀ PUBLIC — CỐ Ý, KHÔNG PHẢI SÓT.
#
# Di sản của `0909_bo_rls_toan_bo` (`GRANT SELECT ON ALL TABLES IN SCHEMA tenant_data
# TO PUBLIC`, kèm default privileges cho bảng tạo sau), mà `0913` bật lại RLS không hề
# revoke. Khi `0917` bỏ `agent_api` (view DEFINER, agent trước đó ZERO quyền trên bảng
# gốc — thiết kế gốc của `0005`), người vận hành xác nhận GIỮ NGUYÊN PUBLIC này thay vì
# siết lại: mọi role SELECT được mọi bảng `tenant_data`, cách ly hoàn toàn dựa vào RLS
# FORCE (`0913`). Nên bài kiểm ở đây không còn allow-list cho SELECT — chỉ còn WRITE.
#
# Đúng ba quyền mà grant_agent_write() cấp cho bảng WRITABLE — không hơn.
AGENT_WRITE_PRIVS = ("SELECT", "INSERT", "UPDATE")
MOI_QUYEN_GHI = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


async def test_khong_role_runtime_nao_co_dac_quyen(agent_roles, pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
            "FROM pg_roles WHERE rolname = ANY($1::text[])",
            list(RUNTIME_ROLES),
        )
    assert {r["rolname"] for r in rows} == set(RUNTIME_ROLES)
    for r in rows:
        assert r["rolsuper"] is False, f"{r['rolname']} là superuser"
        assert r["rolbypassrls"] is False, f"{r['rolname']} có BYPASSRLS"
        assert r["rolcreaterole"] is False
        assert r["rolcreatedb"] is False


async def test_role_runtime_khong_so_huu_bang_nao(agent_roles, pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.relname, pg_get_userbyid(c.relowner) AS owner
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('control', 'tenant_data', 'portal')
                  AND c.relkind IN ('r', 'v', 'm', 'p')
                  AND pg_get_userbyid(c.relowner) = ANY($1::text[])""",
            list(RUNTIME_ROLES),
        )
    assert [(r["relname"], r["owner"]) for r in rows] == []


async def test_agent_khong_co_quyen_ghi_ngoai_khai_bao_tren_tenant_data(agent_roles, pool):
    """Điều kiện 3 (đã đổi từ `0917`): SELECT không còn là allow-list (PUBLIC trên toàn
    `tenant_data`, xác nhận cố ý — xem khối bình luận đầu file). Cái còn canh được, và
    PHẢI canh, là QUYỀN GHI: chỉ bảng trong `AGENT_WRITABLE_TENANT_DATA_TABLES` được
    INSERT/UPDATE; "Zero" cho quyền ghi nghĩa là zero thật — cả TRUNCATE/REFERENCES/
    TRIGGER, không chỉ DELETE.

    Quét ĐỘNG mọi bảng trong `tenant_data`, không phải một danh sách tên viết cứng:
    bảng mà module sau thêm cũng bị canh, không cần ai nhớ cập nhật test này.
    """
    async with pool.acquire() as conn:
        bang = [
            r["relname"]
            for r in await conn.fetch(
                """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'tenant_data' AND c.relkind IN ('r', 'p')
                    ORDER BY c.relname"""
            )
        ]
        assert bang, "schema tenant_data không có bảng nào — migration 0004 chưa chạy?"

        vi_pham: list[str] = []
        for table in bang:
            assert await conn.fetchval(
                "SELECT has_table_privilege('agent_t1', $1, 'SELECT')", f"tenant_data.{table}"
            ), f"tenant_data.{table} thiếu SELECT cho PUBLIC — 0909/0913 lệch khỏi trạng thái xác nhận"

            duoc_ghi = table in AGENT_WRITABLE_TENANT_DATA_TABLES
            for priv in MOI_QUYEN_GHI:
                got = await conn.fetchval(
                    "SELECT has_table_privilege('agent_t1', $1, $2)", f"tenant_data.{table}", priv
                )
                nen_co = duoc_ghi and priv in AGENT_WRITE_PRIVS
                if got is not nen_co:
                    vi_pham.append(f"tenant_data.{table}:{priv} = {got} (mong đợi {nen_co})")
        assert vi_pham == [], (
            "Quyền GHI của agent trên tenant_data lệch khỏi khai báo:\n  "
            + "\n  ".join(vi_pham)
            + "\nBảng agent ĐƯỢC ghi phải nằm trong AGENT_WRITABLE_TENANT_DATA_TABLES ở đầu file "
            "(kèm lý do), và chỉ có đúng INSERT/UPDATE. Bảng còn lại: zero quyền ghi."
        )

        co_usage = await conn.fetchval("SELECT has_schema_privilege('agent_t1', 'tenant_data', 'USAGE')")
        if AGENT_WRITABLE_TENANT_DATA_TABLES:
            assert co_usage is True, (
                "có bảng khai trong AGENT_WRITABLE_TENANT_DATA_TABLES nhưng agent_t1 thiếu USAGE "
                "trên schema tenant_data — quyền bảng đã cấp sẽ không dùng được"
            )


async def test_agent_co_usage_tren_sequence_cua_bang_duoc_ghi(agent_roles, pool):
    """Quyền INSERT trên bảng có `bigserial` là VÔ NGHĨA nếu thiếu USAGE trên sequence.

    Postgres kiểm quyền sequence riêng: `INSERT INTO t (a) VALUES (...)` mà `t.id` là
    bigserial sẽ gọi `nextval('t_id_seq')`, và thiếu USAGE thì đỏ với "permission denied
    for sequence" — DÙ has_table_privilege(INSERT) trả true. Nên một cổng chỉ kiểm quyền
    BẢNG sẽ báo "agent ghi được" trong khi agent không ghi được hàng nào.

    Lỗi này có thật, tìm ra lúc kiểm chứng DB dùng chung: `grant_agent_write()` của 0005
    cấp đúng ba quyền bảng và USAGE trên schema, nhưng KHÔNG cấp gì trên sequence. Nó
    không lộ ra trước vì `AGENT_WRITABLE_TENANT_DATA_TABLES` rỗng cho tới 0903.

    Quét ĐỘNG mọi cột serial của mọi bảng đã khai — bảng nào thêm về sau cũng bị canh.
    """
    async with pool.acquire() as conn:
        thieu: list[str] = []
        for table in sorted(AGENT_WRITABLE_TENANT_DATA_TABLES):
            seqs = await conn.fetch(
                """SELECT pg_get_serial_sequence($1, a.attname) AS seq
                     FROM pg_attribute a
                    WHERE a.attrelid = $1::regclass AND a.attnum > 0 AND NOT a.attisdropped
                      AND pg_get_serial_sequence($1, a.attname) IS NOT NULL""",
                f"tenant_data.{table}",
            )
            for r in seqs:
                if not await conn.fetchval("SELECT has_sequence_privilege('agent_all', $1, 'USAGE')", r["seq"]):
                    thieu.append(r["seq"])
        assert thieu == [], (
            "agent_all thiếu USAGE trên sequence: "
            + ", ".join(thieu)
            + "\nBảng đã cấp INSERT cho agent mà thiếu USAGE trên sequence của cột serial thì "
            "agent KHÔNG chèn được hàng nào — `control.grant_agent_write()` phải cấp cả hai."
        )


async def test_agent_chi_doc_duoc_bang_control_duy_nhat_la_heartbeat(agent_roles, pool):
    """Agent cần USAGE trên control để ghi agent_heartbeats (nó ở schema control).

    Nhưng KHÔNG được có quyền nào trên bảng control khác. Đây là chỗ dễ nới lỏng
    "cho tiện" nhất, nên có test canh.

    agent_heartbeats do migration 0007 tạo — trước đó danh sách cho phép là rỗng.
    Bảng này ĐƯỢC phép, nhưng chỉ với đúng ba quyền (SELECT/INSERT/UPDATE cho
    upsert nhịp tim) — không DELETE/TRUNCATE/REFERENCES/TRIGGER. Một allow-list
    mà bỏ qua hẳn bảng nó cho phép thì không phải là một phép kiểm tra: assert
    rõ ràng ở đây thay vì `continue` là để chính bảng ngoại lệ cũng bị canh.

    Quét bằng pg_class (relkind 'r','v','m','p'), KHÔNG phải pg_tables: pg_tables
    bỏ sót view, nên một view control lộ dữ liệu tenant về sau sẽ né được test này
    nếu chỉ quét bảng. Cùng lý do với bản vá gate 6 ở Task 4.
    """
    allowed = {"agent_heartbeats"}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.relname AS tablename
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'control' AND c.relkind IN ('r', 'v', 'm', 'p')
                ORDER BY c.relname"""
        )
        vi_pham = []
        for r in rows:
            if r["tablename"] in allowed:
                continue
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if await conn.fetchval(
                    "SELECT has_table_privilege('agent_t1', $1, $2)",
                    f"control.{r['tablename']}",
                    priv,
                ):
                    vi_pham.append(f"control.{r['tablename']}:{priv}")
        assert vi_pham == [], f"agent_t1 có quyền không được phép: {vi_pham}"

        # Bảng ngoại lệ: kiểm đúng ba quyền được cấp, không hơn không kém.
        for priv in ("SELECT", "INSERT", "UPDATE"):
            got = await conn.fetchval("SELECT has_table_privilege('agent_t1', 'control.agent_heartbeats', $1)", priv)
            assert got is True, f"agent_t1 thiếu {priv} trên control.agent_heartbeats"
        for priv in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            got = await conn.fetchval("SELECT has_table_privilege('agent_t1', 'control.agent_heartbeats', $1)", priv)
            assert got is False, f"agent_t1 có {priv} thừa trên control.agent_heartbeats"


# — portal.pol()/gated_extras() (0005) đã DROP ở 0959, cùng bảng chúng đọc
#   (control.field_policy_live) — cơ chế gate cột mồ côi từ 0917, không còn gì
#   để canh SECURITY DEFINER ở đây.


async def test_create_agent_role_tu_choi_slug_khong_hop_le(pool):
    """Slug đi thẳng vào câu CREATE ROLE — validate ở cả DB và hàm.

    Không chèn tenant 'okslug': không nhánh raises nào bên dưới cần một tenant có
    sẵn ('bad;slug' hỏng ở bước regex trước khi chạm bảng tenants, 'nosuch' cố
    tình không tồn tại) — nên bản gốc chèn rồi không dùng, chỉ để lại rác phải
    dọn. Bỏ hẳn insert thay vì thêm try/finally quanh một thứ không cần có.
    """
    async with pool.acquire() as conn:
        with pytest.raises(Exception, match="tenant id không hợp lệ"):
            await conn.execute("SELECT control.create_agent_role('bad;slug', 'p')")
        with pytest.raises(Exception, match="tenant chưa tồn tại"):
            await conn.execute("SELECT control.create_agent_role('nosuch', 'p')")
