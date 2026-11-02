"""Cho phép dấu `-` trong control.tenants.id — đọc trước khi thêm chỗ thứ tư

BỐI CẢNH: `control.tenants.id` được import từ một hệ ngoài, và id ở đó mang dấu
`-` (vd `noble-homes_k3n7_retail`). Ba chỗ cưỡng chế `^[a-z][a-z0-9_]{1,30}$` đều
chặn `-`, nên tenant import vào rồi nhưng KHÔNG cấp phát được agent key:

    asyncpg.exceptions.RaiseError: tenant id không hợp lệ cho tên role: noble-homes_k3n7_retail

Migration này nới CHARSET (thêm `-`), KHÔNG nới vị trí và KHÔNG nới độ dài.

VÌ SAO `-` AN TOÀN Ở TÊN ROLE — đã kiểm từng đường, không phải suy đoán:
  · `create_agent_role()` (0005) ghép tên qua `format('CREATE ROLE %I ...')` và
    `format('GRANT agent_all TO %I', r)`; `dat_mat_khau_agent()` (0900) qua
    `format('ALTER ROLE %I PASSWORD %L')`. `%I` tự quote thành
    `"agent_noble-homes_k3n7_retail"` — KHÔNG có đường ghép chuỗi thô nào, nên nới
    charset không mở thêm lỗ injection.
  · `portal.current_tenant()` (0001) suy NGƯỢC bằng
    `substring(session_user from '^agent_(.+)$')`. `.+` ăn `-` bình thường, nên
    hợp đồng đặt tên hai chiều vẫn khép.
  · `ten_khoa_truy_cap()` -> `agent-<id>` (MinIO access key) và `ten_collection()`
    -> `kb_<id>` (Qdrant collection) đều nhận `-`.
  · `url_endpoint_agent()` -> `<id>.<domain>`: `-` HỢP CHUẨN nhãn DNS. Ngược lại
    `_` thì KHÔNG — đó là một khoảng hở CÓ TỪ TRƯỚC migration này (mọi tenant hiện
    có đều dùng `_`), không phải do nó gây ra. Ghi ở đây để lần sau ai đọc
    docstring "nó đã là nhãn subdomain hợp lệ sẵn" ở `endpoint.py` biết là câu đó
    chỉ đúng một nửa.

VÌ SAO KÝ TỰ ĐẦU VẪN PHẢI `[a-z]`: `agent_-x` là tên role đọc như một tuỳ chọn
dòng lệnh, và `-x.<domain>` là nhãn DNS sai chuẩn. Cả hai đều là loại sai không
có triệu chứng rõ. Nới charset không nới vị trí.

VÌ SAO KHÔNG NỚI `organizations_id_check` (0102) CÙNG LÚC: `org_id` không đi vào
tên role, đường dẫn kho tệp, hay nhãn subdomain nào — nó không nằm trên đường đã
nổ. Nới một constraint "cho đối xứng" là mở rộng phạm vi dữ liệu hợp lệ mà không
có ca dùng nào đòi. Nếu đường import sau này mang org_id có `-` thì đó là một
migration riêng, với lý do riêng.

VÌ SAO KHÔNG SỬA `slug_tenant()` ĐỂ SINH `-`: hàm đó vẫn fold mọi ký tự lạ về
`_`. Yêu cầu là CHẤP NHẬN `-` (từ import), không phải SINH ra `-`. Để nó sinh `-`
là tạo hai hình dạng id cho cùng một đường tạo workspace.

⚠️ DOWNGRADE KHÔNG TỰ DỌN DỮ LIỆU. Nếu đã có hàng `tenants.id` chứa `-`, câu
`ADD CONSTRAINT` ở downgrade() sẽ vỡ với `check constraint "tenants_id_check" is
violated by some row`. Đó là CỐ Ý: dọn im lặng ở đây nghĩa là đổi id của tenant
đang chạy — mà id ấy còn là tên role, tiền tố kho tệp và tên collection Qdrant.
Muốn hạ thì đổi id (và cấp phát lại hạ tầng) TRƯỚC, bằng tay, có chủ đích.

Revision ID: 0911_tenant_id_gach_ngang
Revises: 0910_agent_config
"""

from alembic import op

revision = "0911_tenant_id_gach_ngang"
down_revision = "0910_agent_config"
branch_labels = None
depends_on = None

# NGUỒN DUY NHẤT của biểu thức trong migration này — nó đi vào ĐÚNG 3 chỗ bên dưới.
# Viết `-` ở CUỐI lớp ký tự: `[a-z0-9_-]`. Đặt giữa (`[a-z0-9_-z]`) là một dải, và
# đó là kiểu lỗi regex vẫn hợp lệ về cú pháp nên không ai thấy.
_ID_CHECK_MOI = "^[a-z][a-z0-9_-]{1,30}$"
_ID_CHECK_CU = "^[a-z][a-z0-9_]{1,30}$"


def _dat_constraint(bieu_thuc: str) -> None:
    """DROP rồi ADD, không `ALTER CONSTRAINT`: Postgres không cho sửa biểu thức
    của một CHECK tại chỗ. Cùng tên constraint để thông báo lỗi giữ nguyên hình
    dạng mà mọi test và mọi tài liệu đang trích."""
    op.execute("ALTER TABLE control.tenants DROP CONSTRAINT tenants_id_check")
    op.execute(f"ALTER TABLE control.tenants ADD CONSTRAINT tenants_id_check CHECK (id ~ '{bieu_thuc}')")


def _dat_ham(bieu_thuc: str) -> None:
    """CREATE OR REPLACE cả hai hàm với `bieu_thuc`.

    VÌ SAO `CREATE OR REPLACE` CHỨ KHÔNG DROP + CREATE: `DROP FUNCTION` xoá luôn
    ACL, và `dat_mat_khau_agent` có `GRANT EXECUTE ... TO portal_api` do 0900 cấp
    — mất nó là API runtime không phát được khoá nữa, một lỗi 500 chỉ lộ ra lúc
    khách bấm nút. `CREATE OR REPLACE` giữ nguyên grant.

    VÌ SAO CHÉP LẠI TOÀN BỘ THÂN HÀM: Postgres không có "replace một dòng trong
    hàm". Thân hàm dưới đây PHẢI khớp bản gốc ở 0005/0900 trừ đúng biểu thức
    regex — kể cả `SECURITY DEFINER` và `SET search_path` của `dat_mat_khau_agent`,
    vì `CREATE OR REPLACE` thiếu chúng là ÂM THẦM hạ hàm về SECURITY INVOKER và
    lúc đó `portal_api` (không có CREATEROLE) hết tạo được role.
    """
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION control.create_agent_role(p_tenant text, p_password text)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE r text := 'agent_' || p_tenant;
        BEGIN
            IF p_tenant !~ '{bieu_thuc}' THEN
                RAISE EXCEPTION 'tenant id không hợp lệ cho tên role: %', p_tenant;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM control.tenants WHERE id = p_tenant) THEN
                RAISE EXCEPTION 'tenant chưa tồn tại: %', p_tenant;
            END IF;

            EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', r, p_password);
            -- Toàn bộ quyền đến từ nhóm. Hàm này KHÔNG có danh sách grant riêng
            -- nào — thêm view hay bảng mới thì grant cho agent_all, không sửa đây.
            EXECUTE format('GRANT agent_all TO %I', r);
        END $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION control.dat_mat_khau_agent(p_tenant text, p_password text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, control AS $$
        DECLARE r text := 'agent_' || p_tenant;
        BEGIN
            -- Cùng biểu thức với create_agent_role() của M1. Không nới lỏng: tên
            -- role đi thẳng vào format(%I), và tenant_id lạ là một lỗ.
            IF p_tenant !~ '{bieu_thuc}' THEN
                RAISE EXCEPTION 'tenant id không hợp lệ cho tên role: %', p_tenant;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM control.tenants WHERE id = p_tenant) THEN
                RAISE EXCEPTION 'tenant chưa tồn tại: %', p_tenant;
            END IF;
            IF length(p_password) < 20 THEN
                RAISE EXCEPTION 'mật khẩu agent quá ngắn';
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('ALTER ROLE %I PASSWORD %L', r, p_password);
            ELSE
                -- Gọi lại hàm của M1 thay vì chép logic: toàn bộ quyền đến từ
                -- nhóm `agent_all`, và M1 sở hữu định nghĩa đó.
                PERFORM control.create_agent_role(p_tenant, p_password);
            END IF;
        END $$
        """
    )


def upgrade() -> None:
    _dat_constraint(_ID_CHECK_MOI)
    _dat_ham(_ID_CHECK_MOI)


def downgrade() -> None:
    """Hàm TRƯỚC, constraint SAU — thứ tự ngược của upgrade().

    Không quan trọng về mặt phụ thuộc (ba đối tượng độc lập), nhưng để bản hạ đọc
    như một tấm gương của bản lên thì lần sau thêm đối tượng thứ tư khó quên hơn.
    """
    _dat_ham(_ID_CHECK_CU)
    _dat_constraint(_ID_CHECK_CU)
