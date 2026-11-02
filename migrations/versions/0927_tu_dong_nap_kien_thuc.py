"""Tự động nạp kiến thức: cờ chờ duyệt, retry hàng đợi, bỏ csbh khỏi danh mục ảnh

Ba việc, cùng một đợt (spec `2026-08-14-tu-dong-nap-kien-thuc-design.md`):

**(a) `documents.body_cho_duyet`** — van duyệt cho chữ bóc bằng OCR. Chỉ áp cho OCR (PDF
scan, ảnh CSBH) chứ không cho mọi chữ bóc: PDF có lớp chữ / docx / xlsx do THƯ VIỆN bóc nên
chính xác, còn OCR là model đọc ảnh nên có thể sai. Nguyên tắc: *model sinh ⇒ người xem;
thư viện bóc ⇒ tự động.*

KHÔNG backfill cờ. Nội dung `body` có sẵn coi như đã duyệt — bật hết lên là hàng loạt mục
"chờ duyệt" hiện ra sau deploy cho thứ người dùng đã quen thấy và một phần đã nằm trong kho.

**(b) `control.jobs.attempts` + `run_after`** — retry theo loại việc, và thu hồi việc kẹt.
Hàng đợi ghi `state='running'` trong một giao dịch RIÊNG rồi mới gọi handler, không có cột
số lần thử, không có thời hạn. Nên một việc bị giết giữa đường (SIGTERM lúc deploy trong khi
handler đang chặn) kẹt `running` VĨNH VIỄN — và chỉ báo mới của tab kiến thức suy "đang nạp"
từ đúng những hàng `queued|running`, nên nó sẽ xoay mãi mà người dùng không có nút nào bấm.

`run_after` mặc định `now()` để mọi hàng cũ nhặt được ngay như trước.

**(c) bỏ `csbh` khỏi CHECK danh mục ảnh** — csbh là một loại TÀI LIỆU, không phải danh mục
ảnh. Thiết kế đã quyết chuyển nó từ `media` sang `documents` (`verticals/real_estate.py`:
"7 category, không phải 9") nhưng làm nửa đường: 34 ảnh `csbh` trên dev không có đường nào
tới agent (không point ảnh, không OCR, không nằm trong documents) và badge vàng vĩnh viễn.

Di trú dữ liệu chạy TRƯỚC khi siết CHECK, trong cùng migration: mỗi ảnh csbh thành một hàng
`documents` mang `file_url` = khoá ảnh và tiêu đề có tiền tố `CSBH — `, rồi hàng ảnh bị xoá.
Không đảo thứ tự — siết CHECK trước là migration nổ trên đúng 34 hàng đó.

VÀ PHẦN DI TRÚ PHẢI TẮT `FORCE ROW LEVEL SECURITY` (luật ở header `0003`). Bản đầu quên,
nên deploy dev chết đúng ở câu ADD CONSTRAINT: `check constraint media_category_hop_le is
violated by some row`. Chuỗi nhân quả: `FORCE` áp RLS cả cho CHỦ BẢNG, migrator không set
`app.tenant_id` ⇒ policy `tenant_isolation` lọc ra 0 hàng ⇒ INSERT chép 0 hàng, DELETE xoá
0 hàng, cả hai báo THÀNH CÔNG ⇒ ADD CONSTRAINT (không đi qua RLS) vẫn thấy 34 hàng csbh.
Không lộ ở local vì testcontainer đặt `portal_migrator` làm bootstrap superuser — superuser
bỏ qua RLS bất kể FORCE; ở môi trường thật nó là owner-KHÔNG-superuser.

Revision ID: 0927_tu_dong_nap_kien_thuc
Revises: 0926_escalation_notes
"""

from alembic import op

revision = "0927_tu_dong_nap_kien_thuc"
down_revision = "0926_escalation_notes"
branch_labels = None
depends_on = None

# Bảy danh mục ảnh sau khi bỏ `csbh`. Khai ở đây chứ không import từ `kb/contracts.py`:
# migration là ảnh chụp schema tại một thời điểm, nó phải chạy được cả khi hằng số trong code
# đổi tiếp về sau.
_DANH_MUC_ANH = ("tong_quan", "ngoai_that", "noi_that", "tien_ich", "mat_bang", "vi_tri", "tien_do")

# Ba bảng phần di trú đọc/ghi. Tắt FORCE quanh đúng đoạn đó rồi bật lại — cách thứ hai
# trong hai cách mà `0003` cho phép (cách kia là SET LOCAL app.tenant_id cho TỪNG tenant,
# mà ở đây không liệt kê được: tenant nào có ảnh csbh chính là thứ RLS đang giấu).
_BANG_DI_TRU = ("tenant_data.media", "tenant_data.documents", "tenant_data.kb_index_state")


def _force_rls(bat: bool) -> None:
    for bang in _BANG_DI_TRU:
        op.execute(f"ALTER TABLE {bang} {'FORCE' if bat else 'NO FORCE'} ROW LEVEL SECURITY")


def upgrade() -> None:
    # ── (a) cờ chờ duyệt ────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE tenant_data.documents ADD COLUMN IF NOT EXISTS body_cho_duyet boolean NOT NULL DEFAULT false"
    )

    # ── (b) retry + thu hồi ─────────────────────────────────────────────────
    op.execute("ALTER TABLE control.jobs ADD COLUMN IF NOT EXISTS attempts int NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE control.jobs ADD COLUMN IF NOT EXISTS run_after timestamptz NOT NULL DEFAULT now()")
    # Câu nhặt việc lọc `state='queued' AND run_after <= now()` rồi ORDER BY id. Index cũ
    # `jobs_queued_idx (id) WHERE state='queued'` vẫn dùng được cho phần ORDER BY; thêm
    # `run_after` vào index bộ phận để không phải đọc hàng mới biết đã tới lúc chạy chưa.
    op.execute(
        "CREATE INDEX IF NOT EXISTS jobs_queued_run_after_idx ON control.jobs (run_after, id) WHERE state = 'queued'"
    )

    # ── (c) di trú csbh: media → documents, RỒI mới siết CHECK ──────────────
    #
    # `title` mang tiền tố `CSBH — ` vì loại tài liệu suy TỪ tiền tố tiêu đề
    # (`kb/contracts.py::TITLE_PREFIXES`), không có cột doc_type riêng.
    #
    # `body` để rỗng: chữ chưa bóc. Việc bóc là của job OCR, và nó sẽ bật cờ chờ duyệt —
    # đúng đường của (a). Ghi một `body` bịa ở đây là đưa chữ chưa ai đọc tới khách.
    #
    # `status` giữ nguyên của hàng ảnh: một ảnh csbh đang nháp phải thành một tài liệu đang
    # nháp, không được âm thầm công bố.
    #
    # Không try/finally quanh cặp NO FORCE / FORCE: câu nào nổ thì giao dịch migration
    # rollback, kéo theo chính lệnh NO FORCE.
    _force_rls(False)
    op.execute(
        """
        INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, file_url, status)
        SELECT m.tenant_id,
               m.project_code,
               'CSBH — ' || NULLIF(btrim(coalesce(m.file_name, '')), '')::text,
               '',
               m.media_url,
               m.status
          FROM tenant_data.media m
         WHERE m.category = 'csbh'
           AND NULLIF(btrim(coalesce(m.file_name, '')), '') IS NOT NULL
        """
    )
    # Ảnh csbh KHÔNG có `file_name` (cột thêm ở 0922 với DEFAULT '') thì tiêu đề lấy từ khoá
    # ảnh — xấu nhưng đọc ra được, và tiêu đề là NOT NULL CHECK <> '' nên không được để rỗng.
    op.execute(
        """
        INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, file_url, status)
        SELECT m.tenant_id,
               m.project_code,
               'CSBH — ' || regexp_replace(m.media_url, '^.*/', ''),
               '',
               m.media_url,
               m.status
          FROM tenant_data.media m
         WHERE m.category = 'csbh'
           AND NULLIF(btrim(coalesce(m.file_name, '')), '') IS NULL
        """
    )
    # Sổ nạp của những hàng ảnh vừa chuyển: đánh dấu đã xoá để job dọn point cũ có đường đi.
    # `kb_index_state` không có FK tới bảng nguồn nên dòng sổ sống sót sau DELETE — đó là
    # tính chất mà cascade cấp dự án dựa vào (quyết định D10 của spec 2026-08-11).
    op.execute(
        """
        UPDATE tenant_data.kb_index_state s
           SET state = 'deleted', updated_at = now()
          FROM tenant_data.media m
         WHERE s.entity = 'media' AND s.tenant_id = m.tenant_id AND s.record_id = m.id
           AND m.category = 'csbh'
        """
    )
    op.execute("DELETE FROM tenant_data.media WHERE category = 'csbh'")

    # Còn danh mục lạ thì nói TÊN nó ra, lúc RLS còn đang tắt nên câu này nhìn thấy mọi hàng.
    # `ADD CONSTRAINT` cũng nổ, nhưng chỉ nói "violated by some row" — một vòng pipeline nữa
    # mà vẫn không biết hàng nào.
    op.execute(
        f"""
        DO $$
        DECLARE la text;
        BEGIN
            SELECT string_agg(DISTINCT category, ', ') INTO la
              FROM tenant_data.media
             WHERE category <> ALL (ARRAY[{", ".join(repr(c) for c in _DANH_MUC_ANH)}]);
            IF la IS NOT NULL THEN
                RAISE EXCEPTION 'media còn danh mục ngoài bảy giá trị: % — di trú tay rồi chạy lại', la;
            END IF;
        END $$;
        """
    )
    _force_rls(True)

    op.execute("ALTER TABLE tenant_data.media DROP CONSTRAINT IF EXISTS media_category_hop_le")
    op.execute(
        "ALTER TABLE tenant_data.media ADD CONSTRAINT media_category_hop_le "
        f"CHECK (category IN ({', '.join(repr(c) for c in _DANH_MUC_ANH)}))"
    )


def downgrade() -> None:
    # KHÔNG hoàn được phần di trú csbh: hàng ảnh đã bị xoá và id của chúng do sequence cấp,
    # nên dựng lại là bịa id mới. Chỉ hoàn phần schema, và nới CHECK để dữ liệu csbh (nếu ai
    # đó chèn lại bằng tay) không làm downgrade nổ.
    op.execute("ALTER TABLE tenant_data.media DROP CONSTRAINT IF EXISTS media_category_hop_le")
    op.execute(
        "ALTER TABLE tenant_data.media ADD CONSTRAINT media_category_hop_le "
        f"CHECK (category IN ({', '.join(repr(c) for c in (*_DANH_MUC_ANH, 'csbh'))}))"
    )
    op.execute("DROP INDEX IF EXISTS control.jobs_queued_run_after_idx")
    op.execute("ALTER TABLE control.jobs DROP COLUMN IF EXISTS run_after")
    op.execute("ALTER TABLE control.jobs DROP COLUMN IF EXISTS attempts")
    op.execute("ALTER TABLE tenant_data.documents DROP COLUMN IF EXISTS body_cho_duyet")
