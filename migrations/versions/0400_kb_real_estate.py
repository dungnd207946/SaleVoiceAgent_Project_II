"""KB BĐS — viết lại theo template `real_estate` (docs/build_module_knowledgebase/)

VÌ SAO VIẾT LẠI TẠI CHỖ, KHÔNG CHỒNG MIGRATION THÁO GỠ: M4a hôm qua (bản này từng
là `0400_bds_full_fields.py`) thi công theo đặc tả CŨ (`DL_01`, prototype). Chủ
sản phẩm vừa thay bằng bộ tài liệu MỚI (`docs/build_module_knowledgebase/`) và bộ
mới đảo BA quyết định lớn của bản cũ:

  1. **Gate cột → bỏ hẳn.** Bản cũ gate `commission`/`bank_support`/`csbh_full`
     qua `field_policy_live` + view `agent_api`. Tài liệu mới (`02 §1`): "không lưu
     trường nội bộ nhạy cảm thì không cần che" — ba cột đó (và toàn bộ cơ chế nhạy
     cảm hoa hồng/giá net/chiết khấu) BỎ HẲN, không lưu ở đâu trong KB.
  2. **`agent_enabled` (cờ riêng) → gộp về `status`.** Bản cũ tách visibility biên
     tập (`status`) khỏi công tắc phục vụ agent (`agent_enabled`). Tài liệu mới
     (`02 §3`): một cột `status` (`draft·published·archived`) làm cả hai việc,
     cascade theo anchor.
  3. **3 bảng con hẹp (`project_highlights`/`project_progress`/`project_documents`)
     + `import_jobs` (nhập 2 bước) → gộp về 1 bảng `documents` (title+body) +
     `zones`/`media` đúng hình dạng template, nhập tay từng dòng** (không còn
     import CSV 2 bước ở phase này).

Bản cũ CHƯA release (dev DB), nên xoá sạch rồi dựng lại đúng theo `02a §4`, thay
vì viết một migration tháo gỡ riêng rồi một migration dựng riêng. Dev DB dựng lại
bằng `make reset && make dev && uv run alembic upgrade head`.

NGOẠI LỆ ĐÃ HẸN TRƯỚC (spec tổng §4④) VẪN CÒN HIỆU LỰC: `0004_tenant_data_core.py`
viết thẳng "M4 ALTER thêm cột cho projects và units" — ở đây M4 (module KB) còn đi
xa hơn ALTER: DROP rồi CREATE lại `projects`/`units` với hình dạng hoàn toàn khác,
vì tài liệu mới đổi cả field lẫn kiểu (vd `overview` từ `jsonb` sang `text`,
`code` → `project_code`/`unit_code`). `control.enforce_tenant_isolation()` gọi
lại cho cả 5 bảng — cổng 6 của M1 quét mọi bảng `tenant_data`, không phân biệt
bảng đó do module nào tạo.

CỘT `form_visible`/`required_for_agent` TRÊN `control.field_policy_live`: bản
CŨ (`0400_bds_full_fields.py`, đã xoá) từng ADD hai cột này ở chính migration
này để phục vụ gate đọc. Vì file này VIẾT LẠI TẠI CHỖ (cùng revision id, chưa
release) chứ không chồng thêm migration, hai cột đó KHÔNG BAO GIỜ được tạo nữa
— không có "rút" nào để làm ở đây, và một `ALTER ... DROP COLUMN` cho cột chưa
từng tồn tại sẽ nổ ngay ở `alembic upgrade head`. Tài liệu `01 §6` (`field_definitions`
KHÔNG dùng cho `real_estate`) vẫn đúng — nó chỉ xác nhận hai cột này ĐÚNG LÀ
không nên có, và bản viết lại này đạt điều đó bằng cách không tạo ra chúng,
không phải bằng cách tạo rồi xoá. `control.field_policy_live` (bảng của M1,
migration 0002) không bị đụng vào ở đây.

VÒNG FK `projects.cover_media_id/map_media_id ↔ media.project_code`: `projects`
neo cả cây (`02 §2`), nhưng ảnh cover/mặt bằng của nó lại là MỘT ROW của `media`
— mà `media` lại trỏ ngược về `projects` bằng `project_code`. Không bảng nào có
thể tạo trước bảng kia nếu cả hai cột đều NOT NULL FK ngay từ đầu. Cách gỡ: tạo
`projects`/`zones` KHÔNG có `cover_media_id`/`map_media_id`, tạo `media` (trỏ về
`projects`/`zones` đã có), rồi `ALTER TABLE ... ADD COLUMN ... REFERENCES media`
sau cùng. Áp dụng cho CẢ `projects` LẪN `zones` — cả hai bảng đều có hai cột ảnh
cover/mặt bằng theo `02a §4.1`/`§4.2`.

FK ẢNH (`cover_media_id`/`map_media_id`) MANG THEO `tenant_id`, không chỉ `id`:
`media.id` là surrogate PK toàn cục (bigserial), tự nó KHÔNG chặn được việc dự án
của tenant A trỏ nhầm sang ảnh của tenant B (id chỉ cần đúng con số, không cần
đúng tenant). Nên thêm `UNIQUE(tenant_id, id)` trên `media` và FK tổ hợp
`(tenant_id, cover_media_id) → media(tenant_id, id)` — cùng triết lý FK tổ hợp
`(tenant_id, project_code)` mà tài liệu dùng cho mọi bảng con khác (`02 §2`).

`units.unit_code` CÓ INDEX NHƯNG KHÔNG UNIQUE (`02a §4.3`, khác hẳn `project_code`/
`zone_code`) — dữ liệu nhập tay có thể trùng mã căn giữa các đợt nhập, và đây
KHÔNG phải lỗi cần chặn ở tầng DB. Hệ quả: `media.unit_code` (gắn ảnh cho 1 căn,
`02a §4.5`) KHÔNG thể là FK tổ hợp thật (Postgres đòi cột đích phải UNIQUE) —
để trần thành cột tham chiếu MỀM (text + index), ghi rõ lý do tại chỗ khai cột.

`floor` (căn ở tầng số mấy) và `num_floors` (số tầng CỦA căn, biệt thự/duplex
nhiều tầng) là HAI THỨ KHÁC NHAU — `02a §4.3` tách riêng, dễ gộp nhầm vì tên gần
giống cột `floor_min`/`floor_max` của bản cũ (đã bỏ).

`documents` KHÔNG CÓ CỘT `category` (`02a §4.4` đánh dấu `⚠️`) — nó gộp
faq/hoàn thiện/vật liệu/pháp lý/CSBH/hướng dẫn thành MỘT loại nội dung, phân biệt
bằng `title` (breadcrumb), không lọc theo category.

NULLABLE: cột nào là ĐỊNH DANH/khoá (`project_code`/`zone_code`/`unit_code`/
`title`/`media_url`) thì NOT NULL + CHECK khác rỗng — thiếu thì dữ liệu vô nghĩa.
Cột nào là QUICK-FACT mô tả (`region`/`overview`/`amenities`/số liệu…) thì cho
phép thiếu ở giai đoạn `draft` — `02 §3`: "completeness tính lúc publish/đọc theo
luật của template (KHÔNG lưu cột)", và `02a §7` liệt kê đúng field nào cần đủ để
publish (`project`: name+region+overview; `unit`: price_vnd+area_built_m2+
sale_status) — nếu DB bắt NOT NULL ngay từ INSERT thì tenant không nhập nổi một
dự án nháp trước khi có đủ thông tin. Text mô tả dùng `NOT NULL DEFAULT ''` (giữ
nếp 0004: không cần xử lý `NULL` ở tầng code), numeric/smallint quick-fact để
NULL thật (không có sentinel rỗng hợp lý cho số).

Revision ID: 0400_bds_full
Revises: 0300_kb_files
"""

from alembic import op

revision = "0400_bds_full"
down_revision = "0300_kb_files"
branch_labels = None
depends_on = None

_TENANT_FK = "text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE"
_STATUS = "text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived'))"

_CATEGORY_VALUES = "'chung_cu', 'biet_thu', 'lien_ke', 'shophouse', 'dat_nen', 'van_phong'"
_PRODUCT_TYPE_VALUES = (
    "'chung_cu', 'studio', 'duplex', 'penthouse', 'officetel', 'condotel', "
    "'biet_thu', 'lien_ke', 'shophouse', 'nha_pho', 'dat_nen', 'van_phong'"
)
_DIRECTION_VALUES = "'dong', 'tay', 'nam', 'bac', 'dong_bac', 'dong_nam', 'tay_bac', 'tay_nam'"
_SALE_PHASE_VALUES = "'sap_mo_ban', 'dang_ban', 'ban_giao', 'dong_gio_hang'"
_MEDIA_CATEGORY_VALUES = "'tong_quan', 'ngoai_that', 'noi_that', 'tien_ich', 'mat_bang', 'vi_tri', 'tien_do'"


def upgrade() -> None:
    # ── Dọn hệ cũ (M4a — chưa release, xoá sạch rồi dựng lại đúng) ─────────────
    op.execute("DROP TABLE IF EXISTS tenant_data.import_jobs")
    op.execute("DROP TABLE IF EXISTS tenant_data.project_documents")
    op.execute("DROP TABLE IF EXISTS tenant_data.project_progress")
    op.execute("DROP TABLE IF EXISTS tenant_data.project_highlights")
    # View phải drop TRƯỚC bảng gốc (nó SELECT từ tenant_data.projects/units) —
    # ngược lại Postgres từ chối DROP TABLE vì còn object phụ thuộc. 0401 vốn
    # dựng lại hai view này theo hình dạng cũ; migration đó cũng viết lại ở một
    # task riêng (Task 6) vì đổi lớp đọc của agent là quyết định khác — tách ra
    # để revert được riêng phần đó mà không đụng 5 bảng KB.
    op.execute("DROP VIEW IF EXISTS agent_api.units")
    op.execute("DROP VIEW IF EXISTS agent_api.projects")
    op.execute("DROP TABLE IF EXISTS tenant_data.units")
    op.execute("DROP TABLE IF EXISTS tenant_data.projects")

    # KHÔNG có ALTER TABLE control.field_policy_live ở đây — xem "CỘT
    # form_visible/required_for_agent" ở header: bản cũ từng ADD hai cột đó
    # trong CHÍNH revision này; viết lại tại chỗ nghĩa là chúng không hề được
    # tạo ra, nên không có gì để DROP. `control.field_policy_live` (bảng của
    # M1, migration 0002) không bị đụng vào.

    # ── 1. projects — anchor của cả cây (02 §2, 02a §4.1) ──────────────────────
    # CHƯA có cover_media_id/map_media_id: xem "VÒNG FK" ở header.
    op.execute(
        f"""
        CREATE TABLE tenant_data.projects (
            id                    bigserial PRIMARY KEY,
            tenant_id             {_TENANT_FK},
            project_code          text NOT NULL CHECK (project_code <> ''),
            name                  text NOT NULL DEFAULT '',
            category              text[] NOT NULL DEFAULT '{{}}'
                                  CONSTRAINT projects_category_hop_le
                                  CHECK (category <@ ARRAY[{_CATEGORY_VALUES}]::text[]),
            region                text NOT NULL DEFAULT '',
            address               text NOT NULL DEFAULT '',
            investor              text NOT NULL DEFAULT '',
            developer             text NOT NULL DEFAULT '',
            total_land_area_m2    numeric,
            floor_area_m2         numeric,
            build_density_pct     numeric,
            product_scale         text NOT NULL DEFAULT '',
            amenities             text NOT NULL DEFAULT '',
            ownership_form        text NOT NULL DEFAULT '',
            handover_standard     text NOT NULL DEFAULT '',
            total_investment_vnd  bigint,
            sale_phase            text NOT NULL DEFAULT 'sap_mo_ban'
                                  CONSTRAINT projects_sale_phase_hop_le CHECK (sale_phase IN ({_SALE_PHASE_VALUES})),
            overview              text NOT NULL DEFAULT '',
            link_360              text NOT NULL DEFAULT '',
            status                {_STATUS},
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT projects_tenant_code_key UNIQUE (tenant_id, project_code)
        )
        """
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.projects')")

    # ── 2. zones — phân khu (02a §4.2) ─────────────────────────────────────────
    # CHƯA có cover_media_id/map_media_id, cùng lý do với projects.
    op.execute(
        f"""
        CREATE TABLE tenant_data.zones (
            id            bigserial PRIMARY KEY,
            tenant_id     {_TENANT_FK},
            project_code  text NOT NULL,
            zone_code     text NOT NULL CHECK (zone_code <> ''),
            name          text NOT NULL DEFAULT '',
            category      text CONSTRAINT zones_category_hop_le
                          CHECK (category IS NULL OR category IN ({_CATEGORY_VALUES})),
            product_scale text NOT NULL DEFAULT '',
            overview      text NOT NULL DEFAULT '',
            status        {_STATUS},
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT zones_tenant_project_zone_key UNIQUE (tenant_id, project_code, zone_code),
            CONSTRAINT zones_tenant_project_fk FOREIGN KEY (tenant_id, project_code)
                REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX zones_tenant_project_idx ON tenant_data.zones (tenant_id, project_code)")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.zones')")

    # ── 3. media — nguồn sự thật CMS cho ảnh/video (02a §4.5) ──────────────────
    # Tạo SAU projects/zones (đã có (tenant_id, project_code) và
    # (tenant_id, project_code, zone_code) để FK), TRƯỚC units/documents.
    # `UNIQUE(tenant_id, id)` tồn tại CHỈ để cho phép FK tổ hợp mang tenant_id từ
    # projects/zones trỏ vào đây — xem "FK ẢNH" ở header.
    op.execute(
        f"""
        CREATE TABLE tenant_data.media (
            id           bigserial PRIMARY KEY,
            tenant_id    {_TENANT_FK},
            project_code text NOT NULL,
            zone_code    text,
            -- `unit_code` KHÔNG có FK thật: units.unit_code không UNIQUE (xem
            -- header) nên Postgres không nhận nó làm cột đích FK. Tham chiếu mềm
            -- + index để tra theo căn vẫn nhanh.
            unit_code    text,
            content_type text NOT NULL CONSTRAINT media_content_type_hop_le CHECK (content_type IN ('image', 'video')),
            category     text NOT NULL CONSTRAINT media_category_hop_le CHECK (category IN ({_MEDIA_CATEGORY_VALUES})),
            caption      text NOT NULL DEFAULT '',
            media_url    text NOT NULL CHECK (media_url <> ''),
            thumb_url    text,
            content_hash text NOT NULL DEFAULT '',
            uploaded_by  text,
            status       {_STATUS},
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT media_tenant_id_key UNIQUE (tenant_id, id),
            CONSTRAINT media_tenant_project_fk FOREIGN KEY (tenant_id, project_code)
                REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE,
            CONSTRAINT media_tenant_zone_fk FOREIGN KEY (tenant_id, project_code, zone_code)
                REFERENCES tenant_data.zones (tenant_id, project_code, zone_code) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX media_tenant_project_idx ON tenant_data.media (tenant_id, project_code)")
    op.execute("CREATE INDEX media_tenant_unit_idx ON tenant_data.media (tenant_id, unit_code)")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.media')")

    # ── 4. units — từng căn/sản phẩm bán (02a §4.3) ────────────────────────────
    op.execute(
        f"""
        CREATE TABLE tenant_data.units (
            id                bigserial PRIMARY KEY,
            tenant_id         {_TENANT_FK},
            project_code      text NOT NULL,
            zone_code         text NOT NULL,
            -- Index, KHÔNG unique — 02a §4.3 nói rõ, khác project_code/zone_code.
            unit_code         text NOT NULL CHECK (unit_code <> ''),
            product_type      text NOT NULL CONSTRAINT units_product_type_hop_le
                              CHECK (product_type IN ({_PRODUCT_TYPE_VALUES})),
            bedrooms          smallint,
            block             text,
            -- floor = căn ở TẦNG SỐ MẤY (cao tầng). KHÔNG PHẢI num_floors.
            floor             smallint,
            -- num_floors = SỐ TẦNG CỦA CĂN (biệt thự/duplex nhiều tầng). Hai cột
            -- khác nhau — xem header, dễ gộp nhầm vì tên gần giống floor_min/max
            -- của bản cũ (đã bỏ).
            num_floors        smallint,
            direction         text CONSTRAINT units_direction_hop_le
                              CHECK (direction IS NULL OR direction IN ({_DIRECTION_VALUES})),
            area_built_m2     numeric,
            area_wall_m2      numeric,
            area_land_m2      numeric,
            price_vnd         numeric,
            price_per_m2_vnd  numeric,
            -- sale_status là trạng thái KINH DOANH, tách khỏi `status` hiển thị
            -- (02 §3): một căn có thể status=published (agent thấy) mà
            -- sale_status=sold (đã bán, vẫn hiện để trả lời "căn này còn không").
            sale_status       text NOT NULL DEFAULT 'available'
                              CONSTRAINT units_sale_status_hop_le
                              CHECK (sale_status IN ('available', 'booked', 'sold')),
            image_url         text,
            status            {_STATUS},
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT units_gia_dien_tich_khong_am CHECK (
                coalesce(price_vnd, 0) >= 0 AND coalesce(price_per_m2_vnd, 0) >= 0
                AND coalesce(area_built_m2, 0) >= 0 AND coalesce(area_wall_m2, 0) >= 0
                AND coalesce(area_land_m2, 0) >= 0
            ),
            CONSTRAINT units_tenant_project_fk FOREIGN KEY (tenant_id, project_code)
                REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE,
            CONSTRAINT units_tenant_zone_fk FOREIGN KEY (tenant_id, project_code, zone_code)
                REFERENCES tenant_data.zones (tenant_id, project_code, zone_code) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX units_tenant_project_idx ON tenant_data.units (tenant_id, project_code)")
    op.execute("CREATE INDEX units_tenant_unit_code_idx ON tenant_data.units (tenant_id, unit_code)")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.units')")

    # ── 5. documents — MỌI tri thức văn bản (02a §4.4, thay 3 bảng con hẹp) ────
    # KHÔNG có cột category — `⚠️` cố ý, xem header + 02a §4.4. project_code có
    # thể là sentinel "__ALL__" = tài liệu chung tenant (02 §2, 02a §4b); FK vẫn
    # hợp lệ vì đó là 1 row projects hệ thống seed sẵn (Task 5, ngoài phạm vi task này).
    op.execute(
        """
        CREATE TABLE tenant_data.documents (
            id           bigserial PRIMARY KEY,
            tenant_id    text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            project_code text NOT NULL,
            title        text NOT NULL CHECK (title <> ''),
            body         text NOT NULL DEFAULT '',
            file_url     text,
            status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT documents_tenant_project_fk FOREIGN KEY (tenant_id, project_code)
                REFERENCES tenant_data.projects (tenant_id, project_code) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX documents_tenant_project_idx ON tenant_data.documents (tenant_id, project_code)")
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.documents')")

    # ── Đóng vòng FK ảnh cover/mặt bằng (xem "VÒNG FK" ở header) ───────────────
    op.execute(
        """
        ALTER TABLE tenant_data.projects
            ADD COLUMN cover_media_id bigint,
            ADD COLUMN map_media_id   bigint
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_data.projects
            ADD CONSTRAINT projects_cover_media_fk FOREIGN KEY (tenant_id, cover_media_id)
                REFERENCES tenant_data.media (tenant_id, id) ON DELETE SET NULL,
            ADD CONSTRAINT projects_map_media_fk FOREIGN KEY (tenant_id, map_media_id)
                REFERENCES tenant_data.media (tenant_id, id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_data.zones
            ADD COLUMN cover_media_id bigint,
            ADD COLUMN map_media_id   bigint
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_data.zones
            ADD CONSTRAINT zones_cover_media_fk FOREIGN KEY (tenant_id, cover_media_id)
                REFERENCES tenant_data.media (tenant_id, id) ON DELETE SET NULL,
            ADD CONSTRAINT zones_map_media_fk FOREIGN KEY (tenant_id, map_media_id)
                REFERENCES tenant_data.media (tenant_id, id) ON DELETE SET NULL
        """
    )


def downgrade() -> None:
    # Chỉ tháo đúng những gì upgrade() vừa dựng — KHÔNG dựng lại hình dạng M4a
    # cũ (project_highlights/progress/documents, import_jobs, agent_api views,
    # projects/units kiểu cũ): bản đó đã bị khai tử theo tài liệu mới, dựng lại
    # ở downgrade() là chồng thêm một bản sao chép chết, không ai dùng.
    # `alembic downgrade -1` từ đây trả DB về đúng lúc "0300 vừa xong, 0400 chưa
    # chạy" — tenant_data KHÔNG có projects/units, đúng thực tế M4a cũ đã bị
    # xoá bỏ hoàn toàn, không phải trả về trạng thái M1 nguyên bản.
    op.execute("DROP TABLE tenant_data.documents")
    op.execute("DROP TABLE tenant_data.units")
    # CASCADE: projects/zones còn FK trỏ vào media (cover/map) — cả hai bảng đó
    # bị DROP ngay sau nên an toàn khi Postgres tự dọn constraint phụ thuộc.
    op.execute("DROP TABLE tenant_data.media CASCADE")
    op.execute("DROP TABLE tenant_data.zones")
    op.execute("DROP TABLE tenant_data.projects")
    # Không ADD lại form_visible/required_for_agent trên field_policy_live —
    # upgrade() ở trên không hề tạo chúng (xem header), nên không có gì để trả lại.
