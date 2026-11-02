"""odyssey_agent — role runtime DÙNG CHUNG cho agent hội thoại

VẤN ĐỀ NÓ GIẢI: agent hội thoại chạy MỘT process phục vụ N tenant và yêu cầu MỘT
credential Postgres duy nhất (hợp đồng `docs/contracts/agent-postgres-read-contract.md`
§0). Toàn bộ nền cách ly hôm nay lại suy tenant TỪ TÊN ROLE — `portal.current_tenant()`
(0001:41) đọc `session_user` khớp `^agent_(.+)$`, và 0900 cấp đúng một role
`agent_<slug>` mỗi tenant. Một role dùng chung không khớp regex đó.

VÌ SAO CHỈ CẦN BA CÂU: đường "suy tenant từ lời khai" ĐÃ CÓ SẴN từ migration đầu —
`current_tenant()` rơi về GUC `app.tenant_id` khi tên role không khớp. Và mọi quyền
agent cần đã nằm ở role nhóm `agent_all` (SELECT `agent_api.*` từ 0005, RW
`control.agent_heartbeats` từ 0007, cộng `ALTER DEFAULT PRIVILEGES` nên view thêm về
sau cũng tự có). Nên migration này không tạo bảng, không tạo view, không sửa hàm nào:
nó chỉ dựng một role và cắm nó vào nhóm đã có.

VÌ SAO KHÔNG BỎ ROLE THEO TENANT: role này là CỘNG THÊM, không thay thế. 0900 và luồng
enrollment/bootstrap giữ nguyên, `agent_<slug>` vẫn hoạt động. Đổi ý thì `DROP ROLE
odyssey_agent` là xong — không có migration dữ liệu nào phải quay lui. Bỏ đường cũ
trước khi đường mới chạy thật là tự khoá mình vào một quyết định chưa được kiểm chứng.

⚠️ ĐÂY LÀ MỘT ĐÁNH ĐỔI CÁCH LY, KHÔNG PHẢI MỘT TIỆN ÍCH. Với `agent_<slug>`, một pod
KHÔNG THỂ đọc tenant khác — nó không có credential của role đó, Postgres cưỡng chế.
Với role dùng chung, rào chắn duy nhất là agent khai đúng `app.tenant_id` mỗi giao
dịch. Hai hệ quả phải nói thẳng:

  · Một mật khẩu lộ = MỌI tenant, thay vì một. Không sửa được bằng kỷ luật; chỉ hạn
    được bằng cách giữ bề mặt hẹp (`test_quyen_khong_rong_hon_agent_all`) và xoay khoá.
  · Quên khai, hoặc khai bằng `SET` trần thay vì `SET LOCAL`, là rò chéo tenant KHÔNG
    có lỗi nào phát ra. Vì sao `SET` trần là lỗ hổng thật: tests/isolation/
    test_pool_leak.py::test_set_tran_song_qua_ranh_gioi_giao_dich_tren_cung_ket_noi.
    Nghĩa vụ đó thuộc phía agent — Portal không kiểm được từ đây.

Cái CÒN cưỡng chế được, và vì vậy có cổng canh: không khai tenant thì đọc ra 0 hàng
(`current_setting(..., true)` → NULL → `WHERE tenant_id = NULL` không khớp gì).
tests/isolation/test_role_agent_dung_chung.py canh cả hai tính chất trên.

NOLOGIN VÀ KHÔNG MẬT KHẨU — CỐ Ý, ĐỪNG "SỬA" LẠI. Cùng lý lẽ với `portal_api` (0003:51)
và nặng hơn một bậc: role này đọc được dữ liệu của MỌI tenant, nên một mật khẩu nằm
trong git là toàn bộ khách hàng cho bất kỳ ai với tới được cổng Postgres. Để NOLOGIN
làm hệ fail-closed: quên bước cấp mật khẩu ở môi trường thật thì agent KHÔNG NỐI ĐƯỢC
(lỗi to, thấy ngay lúc deploy). Cấp quyền đăng nhập là việc của người vận hành
(deploy/README.md §3) và của tests/conftest.py.

VÌ SAO CÓ `search_path` Ở MỨC ROLE: hợp đồng §1.1 nói reader agent gọi view KHÔNG kèm
schema (`FROM agent_published_config`), và Portal chịu trách nhiệm cho nó resolve.
Một dòng, chấp nhận được — nhưng biết giới hạn: `search_path` ở mức role là trạng thái
ẩn, nó im lặng đổi nghĩa mọi tên không kèm schema mà role này viết. Cách bền hơn là
agent tự ghi rõ schema (SQL heartbeat của chính họ, §2, đã ghi rõ `control.` —
nên đây là bất đối xứng không có lý do kỹ thuật nào).

Revision ID: 0901_role_chung
Revises: 0104_vai_tro_dong
"""

from alembic import op

revision = "0901_role_chung"
down_revision = "0104_vai_tro_dong"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IDEMPOTENT — KHÔNG phải "cho chắc", mà vì đã biết chắc nó trùng.
    #
    # Role trong Postgres thuộc phạm vi CLUSTER, không phải phạm vi database. Khảo sát
    # cluster đích (`docs/contracts/danh-gia-dung-chung-db.md` §1) cho thấy `odyssey_agent`
    # ĐÃ tồn tại ở đó với LOGIN + mật khẩu do team agent đặt, và pod agent đang dùng nó.
    # `CREATE ROLE` trần sẽ vỡ với "role already exists" — trên cluster đích, không phải
    # trên máy dev, tức lỗi chỉ hiện ra lúc deploy.
    #
    # VÌ SAO KHÔNG `DROP ROLE ... IF EXISTS` RỒI TẠO LẠI: role đang được một tiến trình
    # sống dùng. Xoá nó là ngắt agent giữa giờ, và `DROP ROLE` cũng sẽ vỡ vì còn ACL tham
    # chiếu. Nhận role sẵn có rồi cấp đúng thứ nó cần là đường ít gây hại nhất.
    #
    # NHÁNH TẠO MỚI VẪN GIỮ `NOLOGIN` (fail-closed — xem header). Nên trên một DB sạch,
    # hành vi không đổi: role không đăng nhập được cho tới khi người vận hành cấp mật khẩu.
    # Migration KHÔNG cố đổi LOGIN/mật khẩu của role sẵn có — đó là bí mật của bên khác.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'odyssey_agent') THEN
                CREATE ROLE odyssey_agent NOLOGIN;
            END IF;
        END $$
        """
    )

    # Mọi quyền đến từ ĐÂY, không từ GRANT riêng. Giữ đúng một đường vào nghĩa là
    # cổng canh `agent_all` cũng canh luôn role này — và một GRANT thẳng cho
    # odyssey_agent sau này sẽ làm test_quyen_khong_rong_hon_agent_all đỏ.
    op.execute("GRANT agent_all TO odyssey_agent")

    # KHÔNG có `control`/`portal` ở đây, có chủ ý: đường ghi duy nhất
    # (control.agent_heartbeats) được agent gọi kèm schema, và thêm `control` vào
    # search_path là mời một câu truy vấn không kèm schema chạm bảng control ngoài ý muốn.
    op.execute("ALTER ROLE odyssey_agent SET search_path = agent_api, public")


def downgrade() -> None:
    # Đối xứng với upgrade: `DROP ROLE` thất bại nếu role còn bị bất cứ ACL hay thuộc
    # tính nào tham chiếu (0003:120 đã phải học bài này một lần). Role này không sở hữu
    # object nào và không có GRANT trực tiếp nào, nên RESET search_path + REVOKE tư cách
    # thành viên là đủ.
    #
    # KHÔNG `DROP ROLE`: upgrade() có thể đã NHẬN một role có sẵn của bên khác (xem
    # nhánh idempotent ở trên) — xoá nó ở downgrade là phá credential của một hệ mà
    # migration này không sở hữu. Trả lại đúng những gì đã cấp, rồi dừng. Trên DB sạch,
    # hệ quả là còn lại một role NOLOGIN không quyền gì: vô hại, và `DROP ROLE
    # odyssey_agent` bằng tay là một câu nếu thật sự muốn dọn.
    op.execute("ALTER ROLE odyssey_agent RESET search_path")
    op.execute("REVOKE agent_all FROM odyssey_agent")
