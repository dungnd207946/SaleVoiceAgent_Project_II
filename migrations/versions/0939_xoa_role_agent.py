"""`control.xoa_role_agent()` — helper SECURITY DEFINER để xoá role `agent_<id>`

Revision ID: 0939_xoa_role_agent
Revises: 0938_hop_nhat_hai_head

⚠️ ĐÁNH SỐ LẠI TỪ `0936` SANG `0939` LÚC MERGE `develop`, có chủ ý. Bản đầu nhận
`0935_hop_nhat_hai_head` làm cha, viết trên một checkout chưa có chuỗi
`0108_dang_nhap_google` · `0936_media_caption_auto` · `0937_documents_body_auto` ·
`0938_hop_nhat_hai_head_0937` của develop. Tên tệp khác nhau nên **git merge sạch
tuyệt đối** — chỉ `alembic upgrade head` gãy với hai head, đúng kịch bản đã sập năm
lần ở repo này (xem Change Log `0920`).

VÌ SAO ĐỔI CHA CHỨ KHÔNG THÊM MIGRATION HỢP NHẤT — luật `0920` nói ngược lại, và
ngoại lệ ở đây có điều kiện rõ: migration này **chưa từng được push**, nên không DB
nào ngoài máy người viết đã áp nó. Cái mà luật đó chống là "alembic coi tổ tiên mới
là đã áp trong khi thật ra chưa" — điều kiện để tránh nó là hạ migration khỏi DB dev
TRƯỚC khi đổi cha, và việc đó đã làm (`alembic downgrade -1` → `0935`, hàm
`control.xoa_role_agent` đã gỡ, đo được). Ngày nào migration đã lên develop thì luật
`0920` áp trở lại không có ngoại lệ.

Cặp còn thiếu của `control.create_agent_role()` (`0005`, viết lại ở `0911`). Đường
xoá workspace là XOÁ CỨNG, và role Postgres của pod là một trong ba tài nguyên
NGOÀI giao dịch phải dọn cùng — hai cái kia là collection Qdrant và tiền tố
`tenants/<id>/` trên kho tệp.

── VÌ SAO PHẢI LÀ MỘT HÀM SQL, KHÔNG PHẢI MỘT CÂU `DROP ROLE` Ở PYTHON ─────
`portal_api` KHÔNG có `CREATEROLE` — cố ý, và `0911` đã ghi lý do cho chiều tạo.
Chiều xoá cũng vậy: không `CREATEROLE` thì không `DROP ROLE`. `SECURITY DEFINER`
là cách duy nhất mở đúng một hành động cho `portal_api` mà không cấp cho nó quyền
tạo/xoá role bất kỳ.

── HAI KHÁC BIỆT CÓ CHỦ Ý SO VỚI `create_agent_role` ───────────────────────
① **KHÔNG kiểm `control.tenants` còn hàng hay không.** `create_agent_role` đòi
   tenant phải tồn tại; hàm này thì ngược lại — nó được gọi ĐÚNG SAU khi hàng
   `tenants` đã bị xoá. Giữ phép kiểm đó ở đây là làm hàm không bao giờ chạy được.
② **`IF EXISTS`.** Phần lớn workspace chưa từng cấp phát pod nào, nên role không
   tồn tại là đường THƯỜNG, không phải lỗi.

── PHÉP KIỂM BIỂU THỨC THÌ KHÔNG ĐƯỢC BỎ ──────────────────────────────────
`p_tenant` đi thẳng vào `format('%I')`. `%I` chống được dấu nháy nhưng KHÔNG chống
được việc gọi hàm với một chuỗi tuỳ ý: không có phép kiểm này thì
`xoa_role_agent('all')` xoá NHÓM `agent_all` — nguồn duy nhất của mọi quyền mà mọi
pod đang sống dựa vào. Vì thế có HAI lớp: cùng biểu thức `tenants_id_check` của
`0911`, VÀ một phép kiểm tường minh rằng tên role bắt đầu bằng `agent_` và không
phải đúng chuỗi `agent_all`.

── KHÔNG CẦN `DROP OWNED BY` ──────────────────────────────────────────────
Đã đối chiếu `create_agent_role` của `0911`: role nhận toàn bộ quyền QUA NHÓM
(`GRANT agent_all TO %I`), không có một grant trực tiếp nào trên đối tượng, và nó
không bao giờ tạo đối tượng nào (chỉ SELECT + INSERT/UPDATE). Nên không có phụ
thuộc nào chặn `DROP ROLE`; membership trong `pg_auth_members` tự đi theo. Nếu về
sau ai đó grant thẳng cho `agent_<id>` thì `DROP ROLE` sẽ nổ với "role cannot be
dropped because some objects depend on it" — đó là tín hiệu đúng: thêm
`DROP OWNED BY` vào đây, đừng nuốt lỗi ở tầng gọi.
"""

from alembic import op

revision = "0939_xoa_role_agent"
down_revision = "0938_hop_nhat_hai_head"
branch_labels = None
depends_on = None

# Cùng biểu thức `tenants_id_check` (0002, nới ở 0911 cho dấu gạch ngang) — sao lại
# ở đây vì migration phải đóng băng theo thời điểm, không import `portal.*`.
_BIEU_THUC = "^[a-z][a-z0-9_-]{1,30}$"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION control.xoa_role_agent(p_tenant text)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, control AS $$
        DECLARE r text := 'agent_' || p_tenant;
        BEGIN
            IF p_tenant !~ '{_BIEU_THUC}' THEN
                RAISE EXCEPTION 'tenant id không hợp lệ cho tên role: %', p_tenant;
            END IF;
            -- Lớp thứ hai. Biểu thức trên đã chặn 'all' vì nó dài 3 ký tự và khớp
            -- pattern — nên KHÔNG được dựa vào nó một mình. Xoá nhóm agent_all là
            -- gỡ quyền của MỌI pod đang sống, cùng một câu lệnh.
            IF r = 'agent_all' OR r NOT LIKE 'agent\\_%' THEN
                RAISE EXCEPTION 'từ chối xoá role %: hàm này chỉ xoá role của MỘT tenant', r;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                RETURN false;  -- chưa từng cấp phát pod: đường THƯỜNG
            END IF;
            EXECUTE format('DROP ROLE %I', r);
            RETURN true;
        END $$
        """
    )
    # `portal_api` là người gọi (qua modules/enrollment/ha_tang.py). GRANT tường
    # minh chứ không dựa vào PUBLIC: `0003` đặt DEFAULT PRIVILEGES cho bảng trong
    # schema `control`, không cho hàm.
    op.execute("GRANT EXECUTE ON FUNCTION control.xoa_role_agent(text) TO portal_api")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS control.xoa_role_agent(text)")
