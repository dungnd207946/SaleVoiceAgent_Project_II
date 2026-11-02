"""control.grant_agent_write() — cấp cả USAGE trên sequence, không chỉ quyền bảng

LỖI NÓ SỬA (tìm ra lúc kiểm chứng DB dùng chung với hệ agent, không phải suy luận):
`grant_agent_write()` của 0005 cấp `SELECT, INSERT, UPDATE` trên bảng + `USAGE` trên schema,
nhưng KHÔNG cấp gì trên sequence. Với bảng có cột `bigserial`, câu INSERT của agent gọi
`nextval('..._id_seq')` và đỏ với:

    permission denied for sequence conversations_id_seq

Postgres kiểm quyền sequence TÁCH RIÊNG khỏi quyền bảng, nên `has_table_privilege(INSERT)`
vẫn trả `true` trong khi agent không chèn được hàng nào. Đó là dạng lỗi tệ nhất của một hàm
cấp quyền: nó báo thành công, cổng kiểm quyền bảng cũng xanh, và chỉ vỡ ở câu INSERT thật.

VÌ SAO LỖI NÀY SỐNG ĐƯỢC TỪ 0005 ĐẾN GIỜ: hàm chưa từng được gọi. Chính header của 0005 ghi
"Hàm này KHÔNG được migration nào gọi cho tới khi một module thật sự cần — vậy là đúng, không
phải sót", và `AGENT_WRITABLE_TENANT_DATA_TABLES` rỗng. 0903 là caller đầu tiên, và hai trong
ba bảng của nó có `bigserial`.

VÌ SAO SỬA HÀM CHỨ KHÔNG GRANT THẲNG TRONG 0903: hợp đồng của hàm là "làm cho bảng này agent
GHI ĐƯỢC". Một hàm không giữ đúng hợp đồng của nó sẽ để lại đúng cái bẫy này cho caller thứ
hai, thứ ba. Vá ở chỗ gọi là biết lỗi mà để nguyên nguồn.

CHỈ `USAGE`, KHÔNG `SELECT`/`UPDATE` trên sequence: `nextval()` chỉ cần USAGE. `SELECT` cho
agent đọc `last_value` (rò tốc độ ghi của tenant khác — cùng sequence dùng chung cho mọi
tenant), `UPDATE` cho nó `setval()` và nhảy số. Không có nhu cầu nào cho hai quyền đó.

Quét cột serial bằng `pg_get_serial_sequence()` chứ không đoán tên `<bảng>_id_seq`: cột serial
có thể tên khác `id`, và tên sequence có thể bị đổi. Hàm catalog trả NULL cho cột không serial,
nên vòng lặp tự bỏ qua đúng chỗ cần bỏ.

Revision ID: 0905_grant_seq
Revises: 0904_config_live
"""

from alembic import op

revision = "0905_grant_seq"
down_revision = "0904_config_live"
branch_labels = None
depends_on = None

# Ba bảng đã đi qua grant_agent_write() ở 0903, trước khi hàm được sửa. CREATE OR REPLACE
# KHÔNG hồi tố quyền đã cấp, nên phải gọi lại cho từng bảng.
BANG_DA_CAP = ("tenant_data.contacts", "tenant_data.conversations", "tenant_data.appointments")

_THAN_HAM = """
CREATE OR REPLACE FUNCTION control.grant_agent_write(p_qualified_table text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_schema text;
    v_seq    text;
BEGIN
    SELECT n.nspname INTO v_schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.oid = p_qualified_table::regclass;
    IF v_schema <> 'tenant_data' THEN
        RAISE EXCEPTION 'agent chỉ được ghi bảng trong tenant_data, không phải %', v_schema;
    END IF;
    EXECUTE format('GRANT USAGE ON SCHEMA tenant_data TO agent_all');
    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %s TO agent_all', p_qualified_table);

    -- Sequence của MỌI cột serial trên bảng. Thiếu khối này thì quyền INSERT ở trên
    -- là vô nghĩa với bảng có bigserial — xem header.
    FOR v_seq IN
        SELECT pg_get_serial_sequence(p_qualified_table, a.attname)
          FROM pg_attribute a
         WHERE a.attrelid = p_qualified_table::regclass
           AND a.attnum > 0 AND NOT a.attisdropped
           AND pg_get_serial_sequence(p_qualified_table, a.attname) IS NOT NULL
    LOOP
        EXECUTE format('GRANT USAGE ON SEQUENCE %s TO agent_all', v_seq);
    END LOOP;
END $$
"""

_THAN_HAM_CU = """
CREATE OR REPLACE FUNCTION control.grant_agent_write(p_qualified_table text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE v_schema text;
BEGIN
    SELECT n.nspname INTO v_schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.oid = p_qualified_table::regclass;
    IF v_schema <> 'tenant_data' THEN
        RAISE EXCEPTION 'agent chỉ được ghi bảng trong tenant_data, không phải %', v_schema;
    END IF;
    EXECUTE format('GRANT USAGE ON SCHEMA tenant_data TO agent_all');
    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %s TO agent_all', p_qualified_table);
END $$
"""


def upgrade() -> None:
    op.execute(_THAN_HAM)
    for bang in BANG_DA_CAP:
        op.execute(f"SELECT control.grant_agent_write('{bang}')")


def downgrade() -> None:
    for bang in BANG_DA_CAP:
        op.execute(
            f"""
            DO $$
            DECLARE v_seq text;
            BEGIN
                FOR v_seq IN
                    SELECT pg_get_serial_sequence('{bang}', a.attname)
                      FROM pg_attribute a
                     WHERE a.attrelid = '{bang}'::regclass
                       AND a.attnum > 0 AND NOT a.attisdropped
                       AND pg_get_serial_sequence('{bang}', a.attname) IS NOT NULL
                LOOP
                    EXECUTE format('REVOKE USAGE ON SEQUENCE %s FROM agent_all', v_seq);
                END LOOP;
            END $$
            """
        )
    op.execute(_THAN_HAM_CU)
