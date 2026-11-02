"""CỔNG 6 — catalog test. Quét pg_catalog để canh những luật mà module SAU phải giữ.

Đây là cổng làm cho "mỗi module tự sở hữu bảng của nó" an toàn: module sau thêm
bảng mà quên gọi control.enforce_tenant_isolation() thì CI đỏ ngay, không phải
chờ ai review nhớ ra.

Hai seam được quét ở đây, vì cả hai hỏng theo cùng một kiểu — không có triệu chứng:
  · bảng `tenant_data` thiếu RLS/FORCE/policy        -> hàng của tenant khác đọc được
  · bảng `control` mang cột tenant_id không khai báo  -> dữ liệu tenant ở nơi không có RLS

(Seam thứ ba — view `agent_api` thiếu vị từ tenant — không còn nữa: `0917` bỏ hẳn
schema `agent_api`, agent đọc thẳng bảng `tenant_data` dưới RLS FORCE.)

Chạy cho MỌI pull request, không path-filter.
"""

import pytest

pytestmark = pytest.mark.integration

# BẢNG `control` ĐƯỢC PHÉP MANG CỘT `tenant_id` — DANH SÁCH ĐÓNG, KÈM LÝ DO.
#
# Schema `control` KHÔNG có RLS, và migration 0003 đặt
#     ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT,INSERT,UPDATE,DELETE ... TO portal_api
# nên `portal_api` có DML trọn gói trên MỌI bảng control tạo về sau. Hệ quả: dữ liệu
# phạm vi-tenant đặt ở `control` được bảo vệ bởi ĐÚNG KHÔNG GÌ CẢ — không policy, không
# FORCE, và cổng RLS ở trên không quét tới. Luật "dữ liệu tenant không nằm ở control"
# trước đây chỉ tồn tại trong docstring của migration 0007; đây là chỗ nó thành cổng.
#
# Module sau thêm bảng control có `tenant_id` thì phải chọn tường minh MỘT trong hai:
#   (a) bảng đó thuộc `tenant_data` -> chuyển sang đó và gọi enforce_tenant_isolation();
#   (b) nó thật sự là control-plane -> thêm một dòng vào đây kèm lý do vì sao an toàn.
CONTROL_TABLES_DUOC_MANG_TENANT_ID = {
    # 0002 — cấu hình control-plane: lĩnh vực nào của workspace đang bật. Không phải dữ
    # liệu nghiệp vụ của tenant; Portal đọc để dựng UI, agent không có quyền nào ở đây.
    "tenant_verticals",
    # "field_policy_live" (0002) đã DROP ở 0959, cùng portal.pol()/gated_extras()
    # phụ thuộc nó — cơ chế gate cột mồ côi từ 0917, xem migration đó.
    # 0006 — hàng đợi job: phạm vi-tenant nhưng là control-plane (worker đọc TRƯỚC khi
    # biết tenant nào, nên không đặt dưới RLS được). Bù lại: handler chạy trong
    # tenant_conn(tenant_id của job), và enqueue() suy tenant từ kết nối chứ không tin
    # tham số — xem portal.core.jobs.
    "jobs",
    # 0006 — view giám sát trên `jobs` (job running > 15 phút). Không phải chỗ chứa dữ
    # liệu mới: nó thừa hưởng đúng phạm vi của `jobs`, và chỉ portal_api đọc được.
    "jobs_stuck",
    # 0101 — control-plane theo đúng nghĩa: nó CHÍNH LÀ thứ quyết định phạm vi tenant
    # của một request. Đặt nó dưới RLS của tenant_data là vòng tròn — muốn đọc
    # membership để biết tenant thì đã phải biết tenant trước. Cùng dạng với `jobs`
    # (worker đọc TRƯỚC khi biết tenant nào). Agent có ZERO quyền trên bảng này: nó
    # không nằm trong AGENT_WRITABLE_TENANT_DATA_TABLES và không có view agent_api nào
    # đọc nó. Cái canh chỗ này không phải RLS mà là require() — xem core/auth/require.py.
    "memberships",
    # 0107 — lời mời tham gia workspace: hash sha256 của token, hạn dùng, ai tạo,
    # và (từ đây) workspace mà lời mời trỏ tới. Cùng hạng với `memberships`, vì cùng
    # một lý do: chính bảng này QUYẾT ĐỊNH quyền truy cập, nên đặt nó dưới RLS của
    # tenant_data là vòng tròn — muốn đọc lời mời để biết tenant thì đã phải biết
    # tenant trước. `tenant_id` ở đây là ĐÍCH của lời mời ("token này cho vào
    # workspace nào"), không phải nhãn phân vùng dữ liệu. Đường đọc duy nhất là
    # `doc_loi_moi_con_hieu_luc(token_hash)` — tra theo hash của một token 256-bit,
    # không phải liệt kê theo tenant; không có token thì không đọc được hàng nào,
    # bất kể quyền DML trọn gói của portal_api.
    "invites",
    # 0007 — chiều GHI của seam agent. Bảng này CÓ RLS riêng với hai policy theo role
    # (agent chỉ hàng của mình · portal_api đọc hết), nên nó không dựa vào ngoại lệ này
    # để an toàn; nó ở `control` vì theo dõi tiến trình agent là việc control-plane.
    "agent_heartbeats",
    # 0940 — khoá API của agent. `tenant_id` ở đây là CHỦ SỞ HỮU khoá ("khoá này mở
    # workspace nào"), không phải nhãn phân vùng dữ liệu nghiệp vụ. Trước 0940 nó suy
    # qua `deployment_id` → `deployments` (bảng đã bỏ ở 0941); rút tầng trung gian đó
    # không đổi hạng của bảng, chỉ rút một chặng JOIN. Cùng lập luận với `invites`: đường đọc nóng là
    # `tra_khoa(key_sha256)` — tra theo băm của một bí mật, không phải liệt kê theo
    # tenant. Đường liệt kê theo tenant (`liet_ke_khoa_cua_tenant`) chỉ gọi được sau
    # require(WORKSPACE_ADMIN) với tenant lấy TỪ PHIÊN, không từ request.
    # Agent có ZERO quyền trên bảng này — view `agent_api.tenant_keys` đã xoá cùng 0917.
    "agent_keys",
    # 0900 — thế hệ bí mật của một workspace. Control-plane, và nó KHÔNG CHỨA bí mật:
    # chỉ một `secret_version` kiểu int. Bí mật được SUY DẪN từ AGENT_MASTER_KEY lúc cần
    # (modules/enrollment/bi_mat.py), nên một `SELECT *` trên toàn schema control không
    # lộ được mật khẩu nào — cổng `test_khong_cot_text_nao_chua_bi_mat` canh đúng điều đó.
    # Agent có ZERO quyền ở đây: 0900 chỉ GRANT cho portal_api.
    "agent_credentials",
    # `config_drafts`/`config_versions` (0200) · `config_live` (0904): DROP ở `0966`.
    # 0201 — nhật ký hoạt động. Control-plane: nó ghi AI làm gì trên control plane,
    # không phải dữ liệu nghiệp vụ của khách. Cùng tính chất bất biến với
    # config_versions (0201 REVOKE UPDATE, DELETE), nên hại tối đa của một lỗi
    # phạm vi tenant ở tầng API là đọc, không phải ghi đè hay xoá dấu vết.
    "audit_log",
    # 0927 — token để hệ thống BÊN KHÁCH đẩy dữ liệu vào cổng nạp. Control-plane
    # theo đúng nghĩa: nó là một khoá API, cùng hạng `agent_credentials`/`agent_keys`
    # — ai được ghi, phát lúc nào. Không mang dữ liệu nghiệp vụ nào.
    #
    # Vì sao mang `tenant_id` TRỰC TIẾP (khác `agent_keys` TRƯỚC 0940, vốn trỏ qua
    # `deployment_id`): token này không gắn với một pod nào cả, nó gắn với một cặp
    # (workspace, lĩnh vực). Thêm một bảng trung gian chỉ để tránh một cột là làm mọi
    # lượt xác thực
    # phải JOIN.
    #
    # Cái canh chỗ này KHÔNG phải RLS mà là hai thứ: `require(WORKSPACE_ADMIN)` ở
    # cả bốn endpoint control-plane, và vị từ `tenant_id = $n` viết tường minh
    # trong MỌI câu SQL của `modules/ingest/repo.py` — kể cả `DELETE`, nơi thiếu
    # nó thì một `id` đoán được là xoá được token của tenant khác. Agent có ZERO
    # quyền ở đây (đo được: `has_table_privilege('odyssey_agent', …) = false`).
    #
    # Cột `token` lưu chuỗi cho xem lại được (quyết định 2026-08-14) nhưng từ
    # 2026-08-15 nó nằm dưới dạng **ciphertext** `enc.v1.…` (`core/bi_mat_luu.py`),
    # cùng lượt với `agent_keys.api_key` — `0927` đã ghi rõ vì sao phải phủ cả hai
    # một lần: mã hoá bảng này rồi để nguyên bảng kia là dời rủi ro chứ không giảm.
    # Có cổng quét động riêng ở `tests/modules/ingest/test_token.py`.
    "ingest_tokens",
}


async def test_moi_bang_tenant_data_da_bat_cach_ly(pool):
    async with pool.acquire() as conn:
        # relkind IN ('r', 'p'): bảng phân mảnh (partitioned, 'p') cũng phải bật
        # cách ly — chỉ xét 'r' (bảng thường) sẽ bỏ sót nó, cổng mất tác dụng
        # với đúng loại bảng module sau nhiều khả năng dùng cho dữ liệu lớn.
        rows = await conn.fetch(
            """
            SELECT c.relname,
                   c.relrowsecurity,
                   c.relforcerowsecurity,
                   EXISTS (
                       SELECT 1 FROM pg_policy p
                        WHERE p.polrelid = c.oid AND p.polname = 'tenant_isolation'
                   ) AS has_policy
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'tenant_data' AND c.relkind IN ('r', 'p')
             ORDER BY c.relname
            """
        )

    assert rows, "schema tenant_data không có bảng nào — migration 0004 chưa chạy?"
    thieu = [
        f"{r['relname']}: rls={r['relrowsecurity']} force={r['relforcerowsecurity']} policy={r['has_policy']}"
        for r in rows
        if not (r["relrowsecurity"] and r["relforcerowsecurity"] and r["has_policy"])
    ]
    assert not thieu, (
        "Bảng tenant_data thiếu cách ly. Trong migration của module bạn, thêm:\n"
        "    op.execute(\"SELECT control.enforce_tenant_isolation('tenant_data.<bảng>')\")\n" + "\n".join(thieu)
    )

    async with pool.acquire() as conn:
        # Không chỉ xét TÊN policy — policy tenant_isolation ON x USING (true) vẫn
        # có tên đúng nhưng không cách ly gì cả. Phải xét ĐÚNG biểu thức: cả USING
        # (qual) và WITH CHECK (with_check) đều phải tham chiếu current_tenant().
        policies = await conn.fetch(
            """
            SELECT tablename, qual, with_check
              FROM pg_policies
             WHERE schemaname = 'tenant_data' AND policyname = 'tenant_isolation'
            """
        )
    sai_bieu_thuc = [
        f"{p['tablename']}: qual={p['qual']!r} with_check={p['with_check']!r}"
        for p in policies
        if "current_tenant" not in (p["qual"] or "") or "current_tenant" not in (p["with_check"] or "")
    ]
    assert not sai_bieu_thuc, (
        "Policy tenant_isolation tồn tại nhưng biểu thức không tham chiếu "
        "portal.current_tenant() — cách ly hình thức, không có tác dụng:\n" + "\n".join(sai_bieu_thuc)
    )


async def test_moi_bang_tenant_data_co_cot_tenant_id(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'tenant_data' AND c.relkind IN ('r', 'p')
               AND NOT EXISTS (
                   SELECT 1 FROM pg_attribute a
                    WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                      AND a.attnum > 0 AND NOT a.attisdropped
               )
            """
        )
    assert [r["relname"] for r in rows] == []


async def test_bang_control_mang_tenant_id_phai_duoc_khai_bao(pool):
    """Dữ liệu phạm vi-tenant không được âm thầm đáp xuống schema `control`.

    Lý do đầy đủ + cách xử lý ở CONTROL_TABLES_DUOC_MANG_TENANT_ID đầu file.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.relname
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'control' AND c.relkind IN ('r', 'v', 'm', 'p')
               AND EXISTS (
                   SELECT 1 FROM pg_attribute a
                    WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                      AND a.attnum > 0 AND NOT a.attisdropped
               )
             ORDER BY c.relname
            """
        )

    co_tenant_id = {r["relname"] for r in rows}
    assert co_tenant_id, "không bảng control nào có cột tenant_id — schema control chưa được tạo?"

    chua_khai = sorted(co_tenant_id - CONTROL_TABLES_DUOC_MANG_TENANT_ID)
    assert not chua_khai, (
        "Bảng trong schema `control` mang cột tenant_id mà không được khai báo: "
        + ", ".join(chua_khai)
        + "\nSchema `control` KHÔNG có RLS, và portal_api có DML trọn gói ở đó qua "
        "ALTER DEFAULT PRIVILEGES (migration 0003) — nên dữ liệu tenant đặt ở đây không "
        "được BẤT CỨ GÌ bảo vệ. Chọn tường minh một trong hai:\n"
        "  (a) nó là dữ liệu nghiệp vụ của tenant -> chuyển sang schema tenant_data và gọi\n"
        "      op.execute(\"SELECT control.enforce_tenant_isolation('tenant_data.<bảng>')\")\n"
        "  (b) nó thật sự là control-plane -> thêm tên bảng vào "
        "CONTROL_TABLES_DUOC_MANG_TENANT_ID ở đầu file này, KÈM lý do vì sao an toàn."
    )


async def test_khong_co_cot_nao_ten_duoi_ty(pool):
    """Giá lưu bigint VND. Đổi đơn vị (tỷ -> VND) làm ở biên nhập, không ở tầng đọc."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            r"""SELECT table_name, column_name FROM information_schema.columns
                 WHERE table_schema = 'tenant_data' AND column_name LIKE '%\_ty'"""
        )
    assert [(r["table_name"], r["column_name"]) for r in rows] == []


# BẢNG `billing` — schema thứ ba mang dữ liệu phạm vi-tenant.
# `usage_events` (0942) và `rated_usage` (0943) đều có cột `tenant_id`, và cổng RLS
# ở trên chỉ quét `tenant_data` nên KHÔNG với tới đây. Danh sách đóng dưới đây buộc
# người thêm bảng billing mới phải chọn tường minh một trong hai chỗ.
BILLING_TABLES_CO_RLS: frozenset[str] = frozenset(
    {
        "usage_events",  # 0942 — sổ ghi usage, agent INSERT, policy agent_read/agent_insert
        "rated_usage",  # 0943 — tiền từng event; policy tenant_read
        "tenant_price_version",  # 0943 — tenant nào dùng bảng giá nào; policy tenant_all
        # "invoice" (0943) đã DROP ở 0959 — schema "giai đoạn 2" chưa từng có
        # code nào chạm tới, xem migration đó.
    }
)

# Bảng billing KHÔNG mang tenant_id — danh mục giá cấp nền tảng, dùng chung mọi tenant.
BILLING_TABLES_KHONG_TENANT_ID: frozenset[str] = frozenset(
    {
        "metric",
        "pricing_basis",
        "purpose",
        "price_version",
        "price_item",
        # "invoice_line" (0943) đã DROP ở 0959, cùng "invoice" ở trên.
    }
)


async def test_bang_billing_mang_tenant_id_phai_co_rls(pool) -> None:
    """Bảng `billing` có cột tenant_id thì phải có RLS + ít nhất MỘT policy mà
    biểu thức của nó THẬT SỰ tham chiếu `portal.current_tenant()`.

    Chế độ hỏng nếu thiếu: `portal_api` đọc được tiền của MỌI tenant, và không
    query nào báo lỗi — chỉ trả nhiều hàng hơn mức được phép.

    ⚠️ SỬA (review cuối đợt billing): bản trước chỉ đếm `so_policy > 0` — một
    policy `USING (true)` (cho qua MỌI hàng, tức KHÔNG cách ly gì cả) có tên
    đúng, đúng bảng, và đếm được là "có policy", nên cổng này sẽ xanh dù cách
    ly đã bị vô hiệu hoàn toàn. Cùng bài học với `test_moi_bang_tenant_data_da_
    bat_cach_ly` ở trên (nó đã xét `qual`/`with_check` từ đầu) — áp lại đúng
    cách đó cho schema `billing`.
    """
    async with pool.acquire() as conn:
        hang = await conn.fetch(
            """SELECT c.relname,
                      c.relrowsecurity,
                      EXISTS (SELECT 1 FROM information_schema.columns col
                               WHERE col.table_schema = 'billing'
                                 AND col.table_name = c.relname
                                 AND col.column_name = 'tenant_id') AS co_tenant_id
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'billing' AND c.relkind IN ('r', 'p')
                ORDER BY c.relname"""
        )
        assert hang, "không thấy bảng nào trong schema billing — 0943 chưa áp?"

        policies = await conn.fetch(
            """SELECT tablename, qual, with_check FROM pg_policies WHERE schemaname = 'billing'"""
        )
    theo_bang: dict[str, list] = {}
    for p in policies:
        theo_bang.setdefault(p["tablename"], []).append(p)

    def _co_vi_tu_tenant(ten_bang: str) -> bool:
        return any(
            "current_tenant" in (p["qual"] or "") or "current_tenant" in (p["with_check"] or "")
            for p in theo_bang.get(ten_bang, [])
        )

    thieu = [r["relname"] for r in hang if r["co_tenant_id"] and not r["relrowsecurity"]]
    assert not thieu, f"bảng billing mang tenant_id nhưng chưa ENABLE RLS: {thieu}"

    sai_bieu_thuc = [r["relname"] for r in hang if r["co_tenant_id"] and not _co_vi_tu_tenant(r["relname"])]
    assert not sai_bieu_thuc, (
        "bảng billing mang tenant_id nhưng KHÔNG có policy nào tham chiếu "
        f"portal.current_tenant() — cách ly hình thức, không có tác dụng: {sai_bieu_thuc}"
    )

    chua_khai = {
        r["relname"]
        for r in hang
        if r["relname"] not in BILLING_TABLES_CO_RLS and r["relname"] not in BILLING_TABLES_KHONG_TENANT_ID
    }
    assert not chua_khai, (
        f"bảng billing mới chưa khai vào catalog: {chua_khai}. "
        "Thêm vào BILLING_TABLES_CO_RLS (nếu mang tenant_id) hoặc "
        "BILLING_TABLES_KHONG_TENANT_ID (kèm lý do vì sao an toàn)."
    )
