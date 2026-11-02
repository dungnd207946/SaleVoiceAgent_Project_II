"""tenant_data.agent_config — bảng PHẲNG của cấu hình agent đang chạy, ghi lúc «Lưu và áp dụng»

VẤN ĐỀ NÓ GIẢI: cấu hình tab «Agent & Kênh» hiện chỉ tồn tại dưới dạng một cục `jsonb` ở
`control.config_drafts.payload` (bản nháp) và `control.config_versions.payload` (bản đã xuất
bản). Đọc được bằng máy, nhưng KHÔNG đọc được bằng mắt và không query được bằng SQL thường
("tenant nào đã bật `booking`?" phải đi qua toán tử jsonb trên một payload lồng ba tầng). Bảng
này là một bản PHẲNG, mỗi trường của form một cột, cho những người/công cụ chỉ cần đọc nhanh.

⚠️ BẢNG NÀY LÀ BẢN PHÁI SINH, KHÔNG PHẢI NGUỒN SỰ THẬT. Nguồn sự thật của bản đang chạy vẫn là
`control.config_versions` + con trỏ `control.config_live` — đó là thứ agent đọc qua
`agent_api.agent_published_config`. Không ai được sửa hàng ở đây và mong agent đổi hành vi:
lần «Lưu và áp dụng» kế tiếp ghi đè lại toàn bộ hàng. Muốn đổi cấu hình thì đi qua Portal.

MỖI TENANT ĐÚNG MỘT HÀNG (`UNIQUE (tenant_id)`, UPSERT lúc publish). Không append lịch sử: lịch
sử ĐÃ có ở `config_versions` (bất biến, kèm `bundle_sha`), và hai bảng cùng giữ lịch sử thì
tới ngày chúng lệch nhau sẽ không có cách nào biết bảng nào đúng. Ở đây chỉ trả lời đúng một
câu: "cấu hình đang chạy của tenant này, dạng phẳng".

CỘT = ĐÚNG NHỮNG INPUT CÓ TRÊN FORM (`AgentStudio.tsx`), không thêm không bớt:

    Tên agent            -> name              (danh_tinh.ten_agent)
    Tên thương hiệu      -> brand_name        (danh_tinh.ten_thuong_hieu)
    Agent tự xưng        -> self_pronoun      (danh_tinh.tu_xung)
    Gọi khách là         -> customer_pronoun  (danh_tinh.goi_khach)
    Lời chào             -> greeting          (danh_tinh.loi_chao)
    Agent làm gì         -> scope_does        (pham_vi.lam_gi)
    Agent không làm gì   -> scope_does_not    (pham_vi.khong_lam_gi)
    Câu từ chối          -> refusal_line      (pham_vi.cau_tu_choi)
    Phòng ban (n dòng)   -> departments       (pham_vi.phong_ban)
    Giọng điệu           -> tone              (giong.giong_dieu)
    Độ dài trả lời       -> reply_length      (giong.do_dai)
    12 nút kỹ năng       -> skills            (tools.enabled)

`self_pronoun`/`customer_pronoun` là HAI cột vì form có HAI ô (schema payload v3, 2026-08-06:
`xung_ho` tách thành `tu_xung` + `goi_khach`). Một cột `addressing` chứa `"em ↔ anh/chị"` —
hình dạng của bản 0910 đầu tiên, đã sửa TẠI CHỖ vì nó chưa từng chạy ở đâu ngoài máy dev —
buộc mọi người đọc bảng phải tự tách chuỗi theo một quy ước không ai ghi ở đâu.

`pham_vi.linh_vuc` KHÔNG có cột: nó không phải input trên form (MVP khoá cứng `realestate`,
`contracts.py:LINH_VUC`). Ngày nó thành ô chọn thì thêm cột trong migration của ngày đó —
đặt sẵn một cột hằng số chỉ để "cho đủ" là mời người đọc tin rằng nó có nghĩa.

`departments` là `jsonb` mảng object `[{"ten": ..., "khi_nao": ...}]` chứ không phải bảng con:
danh sách này tối đa 8 dòng (`PhamVi.phong_ban`), luôn được đọc/ghi TRỌN GÓI cùng cấu hình, và
không có ai tham chiếu tới một phòng ban riêng lẻ. Một bảng con ở đây thêm một join cho mọi
câu đọc mà không mở ra khả năng nào.

`skills` là `jsonb` MẢNG MÃ ĐANG BẬT — `["find_project", "kb_search", ...]`, kỹ năng tắt thì
VẮNG MẶT, không phải `false`. Ba lý do, theo thứ tự quan trọng:
  · Catalogue kỹ năng còn tăng (hôm nay 12 — `tools.py:MUOI_HAI_KY_NANG`). Dạng object đủ
    12 khoá true/false thì thêm kỹ năng thứ 13 làm MỌI hàng cũ thiếu khoá, và người đọc
    phải biết "vắng khoá nghĩa là tắt" — đúng cái giả định mà dạng object hứa loại bỏ.
  · Query tự nhiên: `WHERE skills @> '["booking"]'` chạy bằng index GIN dưới đây.
  · Trùng đúng hình dạng `tools.enabled` trong payload, nên hàm ghi không phải diễn dịch gì
    (`agent_config.py`) — càng ít diễn dịch, càng ít chỗ để lệch.

VÌ SAO KHÔNG GỌI `control.enforce_tenant_isolation()` NHƯ MỌI BẢNG tenant_data TRƯỚC ĐÓ:
0909 đã DỠ RLS trên toàn bộ `tenant_data` (có chủ đích, xem header của nó). Bật RLS lại cho
đúng một bảng ở đây có hai hệ quả xấu và không hệ quả tốt nào:
  · `FORCE ROW LEVEL SECURITY` áp cho cả `portal_api`. Hàng này được ghi TRONG giao dịch
    publish, trên connection control-plane KHÔNG hề `set_config('app.tenant_id')` (xem
    `repo.py` đầu file: config_* cố tình không đi qua `tenant_conn()`). Bật RLS ở đây =
    mọi lần bấm «Lưu và áp dụng» vỡ với "new row violates row-level security policy".
  · Một bảng có RLS giữa 12 bảng không có RLS là thứ đọc như một sự bảo vệ trong khi nó
    không bảo vệ gì cả — dữ liệu tenant vẫn phơi ở 12 bảng kia.
Cách ly ở đây do TẦNG API giữ: `tenant_id` luôn lấy từ `Principal`, không nhận từ body.
⚠️ CỔNG 6 (`tests/isolation/test_isolation_catalog.py::test_moi_bang_tenant_data_da_bat_cach_ly`)
liệt kê bảng này cùng 12 bảng còn lại — cổng đó đỏ cho TOÀN BỘ `tenant_data` từ 0909, không
phải vì migration này. Ngày nào khôi phục RLS thì khôi phục cho cả schema, một lần.

GRANT phải viết TAY: `ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_data` chưa từng cấp gì cho
`portal_api` (0003 chỉ đặt default privileges cho schema `control`; ở `tenant_data` mỗi bảng
được cấp riêng bên trong `enforce_tenant_isolation()`). Không gọi hàm đó thì cũng không có
GRANT nào — và triệu chứng là publish chết vì "permission denied for table agent_config".
Quyền SELECT cho PUBLIC thì KHÔNG cần viết: 0909 đã đặt `ALTER DEFAULT PRIVILEGES ... GRANT
SELECT ON TABLES TO PUBLIC`, và bảng này do cùng role migrator tạo nên nó thừa hưởng.

Revision ID: 0910_agent_config
Revises: 0909_bo_rls_toan_bo
"""

from alembic import op

revision = "0910_agent_config"
down_revision = "0909_bo_rls_toan_bo"
branch_labels = None
depends_on = None

# Cùng một chuỗi với `contracts.Giong` — hai danh sách ĐÓNG do platform viết và kiểm thử
# (AG_01 BR07). Nhân đôi ở tầng DB là có chủ đích: bảng này được ĐỌC bởi người và công cụ
# ngoài Portal, và một `tone` lạ nằm đó im lặng thì người đọc không có cách nào biết nó
# tới từ bug hay từ một tính năng mới. Thêm preset thứ 4 ⇒ sửa cả hai chỗ, và cổng
# `test_agent_config.py::test_check_tone_khop_contracts` bắt được nếu chỉ sửa một chỗ.
_TONE = ("lich_su", "than_thien", "ngan_gon")
_DO_DAI = ("ngan", "trung_binh", "chi_tiet")


def _trong(gia_tri: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in gia_tri)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE tenant_data.agent_config (
            id               bigserial PRIMARY KEY,
            tenant_id        text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,

            -- Danh tính -----------------------------------------------------
            name             text NOT NULL CONSTRAINT agent_config_name_check CHECK (name <> ''),
            brand_name       text NOT NULL CONSTRAINT agent_config_brand_check CHECK (brand_name <> ''),
            -- Hai đại từ, hai cột. `''` được phép: `DanhTinh` có default nên ô không bao giờ
            -- rỗng qua Portal, nhưng CHECK `<> ''` ở đây làm một ô để trống thành 500 giữa
            -- giao dịch publish — đắt hơn hẳn cái nó ngăn.
            self_pronoun     text NOT NULL DEFAULT '',
            customer_pronoun text NOT NULL DEFAULT '',
            greeting         text NOT NULL DEFAULT '',

            -- Phạm vi -------------------------------------------------------
            scope_does       text NOT NULL DEFAULT '',
            scope_does_not   text NOT NULL DEFAULT '',
            refusal_line     text NOT NULL DEFAULT '',
            departments      jsonb NOT NULL DEFAULT '[]'::jsonb
                             CONSTRAINT agent_config_departments_array_check
                             CHECK (jsonb_typeof(departments) = 'array'),

            -- Giọng ---------------------------------------------------------
            tone             text NOT NULL
                             CONSTRAINT agent_config_tone_check CHECK (tone IN ({_trong(_TONE)})),
            reply_length     text NOT NULL
                             CONSTRAINT agent_config_reply_length_check
                             CHECK (reply_length IN ({_trong(_DO_DAI)})),

            -- Kỹ năng -------------------------------------------------------
            skills           jsonb NOT NULL DEFAULT '[]'::jsonb
                             CONSTRAINT agent_config_skills_array_check
                             CHECK (jsonb_typeof(skills) = 'array'),

            -- Siêu dữ liệu: KHÔNG phải input trên form -----------------------
            -- `version` là số version mà lần «Lưu và áp dụng» này sinh ra ở
            -- control.config_versions. Có nó thì đối chiếu được hàng phẳng này với
            -- payload gốc; thiếu nó thì không ai biết hàng đang xem thuộc bản nào.
            -- KHÔNG đặt FK về config_versions: bảng này bị ghi đè liên tục còn
            -- config_versions bất biến — một FK ở đây chỉ chặn được việc dọn bản cũ.
            version          integer NOT NULL
                             CONSTRAINT agent_config_version_check CHECK (version > 0),
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now(),

            -- Mỗi tenant đúng một hàng — xem header. Đây là đích của ON CONFLICT
            -- trong `agent_config.luu()`; bỏ nó đi thì UPSERT thành INSERT im lặng
            -- và bảng biến thành một lịch sử thứ hai không ai chủ ý tạo ra.
            CONSTRAINT agent_config_tenant_key UNIQUE (tenant_id)
        )
        """
    )

    # GIN cho `@>` — câu hỏi "tenant nào đang bật kỹ năng X" là lý do `skills` ở dạng mảng.
    # Không index `departments`: không có câu hỏi nào đi tìm theo tên phòng ban.
    op.execute("CREATE INDEX agent_config_skills_idx ON tenant_data.agent_config USING gin (skills)")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_data.agent_config TO portal_api")
    op.execute("GRANT USAGE ON SEQUENCE tenant_data.agent_config_id_seq TO portal_api")


def downgrade() -> None:
    # DROP TABLE mang theo index, constraint và mọi ACL trên bảng/sequence — không cần
    # REVOKE tay như 0003 (ở đó grant nằm trên schema/function nên sống lâu hơn bảng).
    op.execute("DROP TABLE tenant_data.agent_config")
