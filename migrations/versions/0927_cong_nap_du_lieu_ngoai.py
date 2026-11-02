"""Cổng nạp dữ liệu ngoài — token, bản ghi thô, lỗi nạp, và mã ngoài trên 5 bảng KB

Revision ID: 0927_cong_nap_ngoai
Revises: 0926_escalation_notes

Thiết kế: `docs/superpowers/specs/2026-08-14-cong-nap-du-lieu-ngoai-design.md`.

Hệ thống của tenant ĐẨY dữ liệu sang qua một endpoint, theo một schema CỐ ĐỊNH.
Migration này dựng ba bảng mới và mở một cột trên năm bảng KB sẵn có.

── VÌ SAO `external_id` LÀ CỘT MỚI, KHÔNG PHẢI BẢNG TRA RIÊNG ────────────────
Khách trỏ bản ghi con về cha bằng mã của CHÍNH HỌ (`projectExternalId`), còn
`project_code` thì Odyssey sinh — nó đi vào SQL của agent và vào tên chunk trên
Qdrant nên mình phải kiểm soát định dạng. Cần một phép tra `external_id → khoá
nội bộ`.

Một bảng tra riêng làm mọi lần chiếu phải JOIN thêm một bảng, và làm nguồn gốc
của một hàng thành thứ phải đi tìm. Cột trên chính bảng thì phép tra là một
`ON CONFLICT`, và mở một hàng ra là thấy ngay nó tới từ đâu.

`NULL` = hàng nhập tay từ portal. Hai đường vào sống chung trong một bảng, đúng
như giao diện đã hứa: `/projects` hiện MỌI dự án bất kể vào bằng đường nào.

── VÌ SAO `ingest_records` LÀ LATEST-WINS, KHÔNG PHẢI SỔ NHẬT KÝ ────────────
`UNIQUE (tenant_id, entity, external_id)` — mỗi bản ghi ngoài đúng một hàng.

Một sổ append-only trả lời được «họ đã gửi gì lúc 9h sáng thứ Ba», nhưng cái giá
là một bảng lớn vô hạn cần chính sách lưu trữ riêng, và câu hỏi người ta thật sự
hỏi là «HIỆN GIỜ họ đang gửi cái gì». Latest-wins trả lời đúng câu đó, bị chặn về
kích thước bởi chính số bản ghi bên khách, và vẫn đủ để chiếu lại toàn bộ khi mình
sửa một lỗi projector.

⚠️ Hệ quả phải biết: mất khả năng truy vết một giá trị đã bị đè. Lịch sử thay đổi
là việc của Nhật ký, không phải bảng này.

── TOKEN LƯU THÔ, VÀ ĐÓ LÀ QUYẾT ĐỊNH CÓ CHỦ ĐÍCH ───────────────────────────
Giao diện cho xem lại token bất cứ lúc nào (che sẵn, bấm con mắt là mở), nên
không thể chỉ lưu băm.

Đã cân nhắc mã hoá at-rest và BỎ ở migration này, vì nó sẽ là an ninh hình thức:
`control.agent_keys.api_key` đã lưu plaintext từ `0918`, và khoá đó nguy hiểm HƠN
— nó đổi được lấy `runtime-credentials`, tức mật khẩu Postgres của tenant. Mã hoá
bảng mới rồi để nguyên bảng nguy hiểm hơn là dời rủi ro chứ không giảm.

Mã hoá at-rest là một việc riêng và phải phủ CẢ HAI bảng cùng lúc (§8 của spec).
"""

from alembic import op

revision = "0927_cong_nap_ngoai"
down_revision = "0926_escalation_notes"
branch_labels = None
depends_on = None

_BANG_KB = ("projects", "zones", "units", "documents", "media")


def upgrade() -> None:
    # ── 1. control.ingest_tokens ─────────────────────────────────────────────
    # `control` KHÔNG có RLS (chưa từng có) — cách ly ở đây do câu SQL tự mang
    # `tenant_id = $n`, giống mọi bảng control-plane khác.
    op.execute(
        """
        CREATE TABLE control.ingest_tokens (
            id            bigserial PRIMARY KEY,
            tenant_id     text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            -- Lĩnh vực nằm TRÊN token, không suy từ đường dẫn lúc chạy: đó là thứ
            -- làm lời hứa «token của BĐS không với sang lĩnh vực khác» thành một
            -- ràng buộc của dữ liệu chứ không phải của code định tuyến.
            vertical      text NOT NULL CONSTRAINT ingest_tokens_vertical_hop_le
                          CHECK (vertical IN ('realestate')),
            label         text NOT NULL CONSTRAINT ingest_tokens_label_hop_le
                          CHECK (label <> '' AND length(label) <= 60),
            -- Bản THÔ — xem docstring đầu tệp. Đây là thứ giao diện bày ra khi
            -- người dùng bấm con mắt.
            token         text NOT NULL,
            -- Đường tra lúc xác thực. UNIQUE toàn cục, không theo tenant: hai
            -- tenant trùng token là va chạm phải nổ, không phải phân xử.
            token_sha256  text NOT NULL UNIQUE,
            created_by    text,
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_used_at  timestamptz,
            -- Nhãn là thứ DUY NHẤT phân biệt hai token trên giao diện (bảng chỉ
            -- có hai cột). Cho trùng tên là cho tạo ra một màn hình không dùng được.
            CONSTRAINT ingest_tokens_nhan_duy_nhat UNIQUE (tenant_id, vertical, label)
        )
        """
    )
    op.execute("CREATE INDEX ingest_tokens_tenant_idx ON control.ingest_tokens (tenant_id, vertical)")

    # ── 2. tenant_data.ingest_records — bản thô, latest-wins ────────────────
    op.execute(
        """
        CREATE TABLE tenant_data.ingest_records (
            id            bigserial PRIMARY KEY,
            tenant_id     text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            entity        text NOT NULL CONSTRAINT ingest_records_entity_hop_le
                          CHECK (entity IN ('project', 'zone', 'unit', 'document', 'media')),
            external_id   text NOT NULL CONSTRAINT ingest_records_external_id_khong_rong
                          CHECK (external_id <> ''),
            op            text NOT NULL CONSTRAINT ingest_records_op_hop_le
                          CHECK (op IN ('upsert', 'delete')),
            -- Lúc thay đổi xảy ra BÊN KHÁCH. Đây là trọng tài của thứ tự, KHÔNG
            -- phải `received_at`: sự kiện về lệch thứ tự là chuyện bình thường
            -- của đẩy bất đồng bộ, và giờ nhận thì nói về mạng chứ không nói về
            -- dữ liệu.
            occurred_at   timestamptz NOT NULL,
            sync_id       text,
            payload       jsonb NOT NULL,
            received_at   timestamptz NOT NULL DEFAULT now(),
            -- NULL = chưa chiếu được (thường vì cha chưa tới). Projector quét
            -- đúng cột này để biết còn nợ gì.
            projected_at  timestamptz,
            CONSTRAINT ingest_records_ban_ghi_duy_nhat UNIQUE (tenant_id, entity, external_id)
        )
        """
    )
    # Projector quét "chưa chiếu" — index một phần, vì hàng đã chiếu là đa số
    # tuyệt đối và không bao giờ bị quét theo cách này.
    op.execute(
        """
        CREATE INDEX ingest_records_cho_chieu_idx
            ON tenant_data.ingest_records (tenant_id, entity)
         WHERE projected_at IS NULL
        """
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.ingest_records')")

    # ── 3. tenant_data.ingest_errors ────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE tenant_data.ingest_errors (
            id            bigserial PRIMARY KEY,
            tenant_id     text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            entity        text NOT NULL,
            external_id   text NOT NULL DEFAULT '',
            -- Rỗng = lỗi ở cấp BẢN GHI (thiếu trường vỏ, `op` sai), không cấp
            -- trường. Giao diện phân biệt hai ca này — xem `NguonLoi.tsx`.
            field         text NOT NULL DEFAULT '',
            -- Phải đủ để dev BÊN KHÁCH tự sửa: nêu cả giá trị gây lỗi, và với
            -- enum thì liệt kê giá trị hợp lệ ngay trong câu. Dưới schema cố
            -- định, đây là đường phản hồi duy nhất họ có.
            reason        text NOT NULL CHECK (reason <> ''),
            received_at   timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ingest_errors_tenant_moi_nhat_idx ON tenant_data.ingest_errors (tenant_id, received_at DESC)"
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.ingest_errors')")

    # ── 4. external_id trên 5 bảng KB ───────────────────────────────────────
    #
    # ⚠️ IDEMPOTENT CÓ CHỦ ĐÍCH, và đây là lý do — không phải thói quen phòng thủ:
    # DB dev đo được 2026-08-14 ĐÃ CÓ SẴN `tenant_data.units.external_id` cùng
    # constraint `units_tenant_external_id_key`, mà KHÔNG migration nào trong
    # `migrations/versions/` tạo ra chúng. Tức schema thật đã trôi khỏi lịch sử
    # migration — ai đó `ALTER TABLE` bằng tay. Một DB dựng mới từ `make up` sẽ
    # KHÔNG có, còn máy đã trôi thì `ADD COLUMN` trần làm gãy cả chuỗi upgrade.
    #
    # `UNIQUE` thường chứ KHÔNG index một phần `WHERE external_id IS NOT NULL`:
    #   · Postgres mặc định NULLS DISTINCT, nên nhiều hàng `NULL` (dự án nhập
    #     tay) vẫn sống chung — đúng thứ index một phần định mua.
    #   · `ON CONFLICT (tenant_id, external_id)` chỉ suy ra được index MỘT PHẦN
    #     khi mệnh đề mang đúng vị từ của nó. Một hình dạng ít tinh tế hơn ở đây
    #     đổi lấy một `ON CONFLICT` không có bẫy — xem `chieu._upsert`.
    #   · Và nó KHỚP với constraint đã trôi vào DB dev, nên hai môi trường hội tụ
    #     về cùng một hình dạng thay vì mang hai loại index cùng tên khác kiểu.
    for bang in _BANG_KB:
        op.execute(f"ALTER TABLE tenant_data.{bang} ADD COLUMN IF NOT EXISTS external_id text")
        # KIỂM CATALOG TƯỜNG MINH, KHÔNG `EXCEPTION WHEN duplicate_object`.
        #
        # Bản đầu dùng khối EXCEPTION và nó NUỐT một lỗi thật: `units` đã mang sẵn
        # một unique index MỘT PHẦN cùng tên (`WHERE external_id IS NOT NULL`, do
        # DDL tay), nên `ADD CONSTRAINT` ném `duplicate_table` và bị bắt im lặng.
        # Kết quả: bốn bảng có constraint, `units` thì không — và `ON CONFLICT
        # (tenant_id, external_id)` trần không khớp được index một phần, nên nó
        # nổ lúc CHẠY chứ không lúc migrate. Bắt-mọi-thứ ở migration là cách biến
        # một lỗi to thành một lỗi nhỏ ở chỗ khác.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint con
                      JOIN pg_class c ON c.oid = con.conrelid
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                     WHERE n.nspname = 'tenant_data' AND c.relname = '{bang}'
                       AND con.conname = '{bang}_tenant_external_id_key'
                ) THEN
                    RETURN;
                END IF;

                -- Index rời cùng tên (không phải constraint) ⇒ di sản DDL tay.
                -- Dỡ để cả năm bảng hội tụ về MỘT hình dạng: `ON CONFLICT` trần.
                IF EXISTS (
                    SELECT 1 FROM pg_indexes
                     WHERE schemaname = 'tenant_data'
                       AND indexname = '{bang}_tenant_external_id_key'
                ) THEN
                    RAISE NOTICE 'dỡ index trôi: {bang}_tenant_external_id_key';
                    EXECUTE 'DROP INDEX tenant_data.{bang}_tenant_external_id_key';
                END IF;

                ALTER TABLE tenant_data.{bang}
                  ADD CONSTRAINT {bang}_tenant_external_id_key UNIQUE (tenant_id, external_id);
            END $$;
            """
        )


def downgrade() -> None:
    for bang in _BANG_KB:
        # `DROP COLUMN` kéo theo constraint, nên không cần gỡ riêng.
        op.execute(f"ALTER TABLE tenant_data.{bang} DROP COLUMN IF EXISTS external_id")
    op.execute("DROP TABLE IF EXISTS tenant_data.ingest_errors")
    op.execute("DROP TABLE IF EXISTS tenant_data.ingest_records")
    op.execute("DROP TABLE IF EXISTS control.ingest_tokens")
