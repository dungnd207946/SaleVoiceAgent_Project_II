"""Kiểm chứng DB dùng chung bằng ĐÚNG credential mà pod agent sẽ dùng.

    AGENT_DSN=postgresql://odyssey_agent:...@host:5433/odyssey_portal \
    uv run python scripts/kiem_chung_db_dung_chung.py

CHẠY LẠI ĐƯỢC, KHÔNG ĐỂ LẠI RÁC: mọi hàng thử đều nằm trong giao dịch bị rollback.

Không kiểm "bảng có tồn tại" — kiểm HÀNH VI: fail-closed, cách ly tenant, đường đọc, đường
ghi, những cửa phải đóng. Chạy sau mỗi lần đổi schema hoặc đổi quyền trên DB dùng chung.

Từ `0917`: KHÔNG còn cần `MIGRATOR_DSN` — mục quay lui con trỏ `config_live` (dùng
`portal_migrator`) đã bỏ, agent không còn đường nào đọc config qua Postgres để đo bằng.
"""

import os

import psycopg

AGENT = os.environ["AGENT_DSN"]

TENANT = os.environ.get("TENANT_KIEM_CHUNG", "noble")
MOI_TENANT = os.environ.get("MOI_TENANT", "noble,acme,du_test,legacy_unassigned,org_f1d72eac_demo_sales_5d74").split(
    ","
)

DAU = "kiem-chung"
SDT_THU = "0912345678"
loi: list[str] = []


class _DungLai(Exception):
    """Ném ra để buộc `with conn.transaction()` ROLLBACK.

    `with conn.transaction()` COMMIT khi thoát bình thường — nên một `conn.rollback()` đặt
    SAU khối là vô nghĩa. Bản đầu của script này mắc đúng lỗi đó và để lại rác thật trên DB.
    Ném exception là cách duy nhất khiến psycopg quay lui khối.
    """


def ok(dieu_kien: bool, nhan: str, chi_tiet: str = "") -> None:
    print(f"  {'✔' if dieu_kien else '✘'} {nhan}{('  — ' + chi_tiet) if chi_tiet else ''}")
    if not dieu_kien:
        loi.append(nhan)


with psycopg.connect(AGENT) as c:
    c.autocommit = False

    print("\n=== 1. FAIL-CLOSED: chưa khai tenant ===")
    with c.transaction():
        ok(c.execute("SELECT portal.current_tenant()").fetchone()[0] is None, "current_tenant() = NULL")
        for bang in ("tenant_data.units", "tenant_data.projects"):
            n = c.execute(f"SELECT count(*) FROM {bang}").fetchone()[0]
            ok(n == 0, f"{bang} trả 0 hàng khi chưa khai tenant", f"đọc được {n}")

    # Mục 2 cũ ("gọi view không kèm schema") đã bỏ: `0917` bỏ schema `agent_api` VÀ reset
    # search_path của `odyssey_agent` (từng trỏ `agent_api, public`) — agent giờ BẮT BUỘC
    # schema-qualify mọi câu (`tenant_data.units`, không phải `units`). Không còn config đọc
    # được qua Postgres ở bất kỳ hình thức nào (agent_published_config đã xoá cùng đợt).

    print("\n=== 3. CÁCH LY: đổi tenant thì đổi dữ liệu ===")
    thay = {}
    for t in MOI_TENANT:
        with c.transaction():
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (t,))
            thay[t] = (
                c.execute("SELECT count(*) FROM tenant_data.units").fetchone()[0],
                c.execute("SELECT count(*) FROM tenant_data.projects").fetchone()[0],
            )
    for t, (u, p) in thay.items():
        print(f"    {t:<30} units={u:<5} projects={p:<4}")
    ok(len({v for v in thay.values()}) >= 1, "đọc được số liệu cho từng tenant")

    print("\n=== 4. KHÔNG KẾ THỪA tenant qua ranh giới giao dịch (cùng 1 kết nối) ===")
    with c.transaction():
        c.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT,))
        c.execute("SELECT count(*) FROM tenant_data.units")
    with c.transaction():
        n = c.execute("SELECT count(*) FROM tenant_data.units").fetchone()[0]
        ok(n == 0, "giao dịch sau KHÔNG kế thừa tenant của giao dịch trước", f"đọc được {n}")

    print("\n=== 5. ĐƯỜNG GHI: 3 bảng write-back (rollback, không để lại rác) ===")
    try:
        with c.transaction():
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT,))
            # So sánh TƯƠNG ĐỐI (trước/sau), không hardcode con số: số hàng là dữ liệu thật
            # và sẽ đổi. Một con số cứng ở đây làm cổng đỏ vì lý do sai.
            BANG = ("contacts", "conversations", "appointments", "escalations")
            truoc = tuple(c.execute(f"SELECT count(*) FROM tenant_data.{b}").fetchone()[0] for b in BANG)
            c.execute(
                "INSERT INTO tenant_data.contacts (tenant_id, phone, snapshot) VALUES (%s, %s, 'thử')",
                (TENANT, SDT_THU),
            )
            c.execute(
                "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES (%s, %s)",
                (TENANT, f"{DAU}-1"),
            )
            c.execute(
                "INSERT INTO tenant_data.appointments (tenant_id, appointment_id) VALUES (%s, %s)",
                (TENANT, f"{DAU}-1"),
            )
            # escalations (0924): agent INSERT lúc chuyển sale rồi UPDATE summary khi
            # bản LLM về. Thiếu quyền ở đây là mất ca IM LẶNG — wrapper nuốt lỗi.
            c.execute(
                "INSERT INTO tenant_data.escalations (tenant_id, session_id, summary) VALUES (%s, %s, 'thử')",
                (TENANT, f"{DAU}-1"),
            )
            c.execute(
                "UPDATE tenant_data.escalations SET summary = 'thử 2', summary_at = now() "
                "WHERE tenant_id = %s AND session_id = %s",
                (TENANT, f"{DAU}-1"),
            )
            sau = tuple(c.execute(f"SELECT count(*) FROM tenant_data.{b}").fetchone()[0] for b in BANG)
            ok(
                all(s == t + 1 for s, t in zip(sau, truoc, strict=True)),
                "INSERT được cả 4 bảng write-back (mỗi bảng +1 hàng)",
                f"trước={truoc} sau={sau}",
            )
            raise _DungLai
    except _DungLai:
        pass

    print("\n=== 6. NHỮNG CỬA PHẢI ĐÓNG (control.* — tenant_data.units/projects đã CỐ Ý mở từ 0917) ===")
    # ⚠ Cột trong mỗi câu phải TỒN TẠI THẬT. Agent có USAGE trên schema `control` (để ghi
    # agent_heartbeats) và `tenant_data` (đọc 5 bảng KB + ghi 4 bảng write-back), nên Postgres
    # phân giải được tên bảng và báo UndefinedColumn TRƯỚC khi kiểm quyền bảng — một cột gõ
    # sai làm phép kiểm này không chạm tới tầng quyền, và "xanh" mà không chứng minh gì.
    for sql, nhan in (
        ("SELECT id FROM control.tenants", "KHÔNG đọc được control.tenants"),
        ("SELECT tenant_id FROM control.config_versions", "KHÔNG đọc được control.config_versions"),
        ("SELECT tenant_id FROM control.config_live", "KHÔNG đọc được control.config_live"),
        ("SELECT key_sha256 FROM control.agent_keys", "KHÔNG đọc được control.agent_keys"),
        # `control.deployments` BỎ khỏi danh sách ở `0941` (bảng đã DROP). Giữ lại thì
        # Postgres ném `UndefinedTable` chứ không phải `InsufficientPrivilege`, và phép kiểm
        # rơi khỏi tầng quyền — đúng chế độ hỏng mà comment đầu vòng lặp này cảnh báo.
        ("SELECT id FROM control.users", "KHÔNG đọc được control.users"),
        ("SELECT tenant_id FROM control.memberships", "KHÔNG đọc được control.memberships"),
    ):
        try:
            with c.transaction():
                c.execute(sql)
            ok(False, nhan, "ĐỌC ĐƯỢC — cách ly hở")
        except psycopg.errors.InsufficientPrivilege:
            ok(True, nhan)
        except Exception as e:
            ok(False, nhan, f"lỗi khác: {type(e).__name__} (cột trong câu probe có tồn tại không?)")

    # Mục 7 cũ ("tra deployment_id qua agent_api.deployments rồi heartbeat") đã bỏ: view đó
    # xoá cùng `0917` — agent giờ lấy `deployment_id` từ response `/runtime-credentials`
    # (không tra ngược DB), xem `docs/contracts/dau-noi-agent.md` G-6/G-8.

# Mục 8 cũ ("quay lui: con trỏ thắng max(version), đo bằng agent_published_config") đã bỏ:
# agent không còn đường nào đọc `config_live`/`config_versions` qua Postgres — bất biến quay
# lui giờ chỉ còn ý nghĩa cho Portal tự dùng (`doc_version_dang_live()`), không phải hợp đồng
# với agent nữa. Đo bằng test nội bộ (`tests/modules/agent_seam/test_dung_chung_db.py` mục
# "0904 · con trỏ config_live"), không phải script kiểm chứng chéo repo này.

print()
if loi:
    print(f"❌ {len(loi)} kiểm chứng THẤT BẠI: {loi}")
    raise SystemExit(1)
print("✅ TẤT CẢ KIỂM CHỨNG ĐẠT")
