"""control.actions · roles · role_actions — vai trò là dữ liệu, không phải enum

Spec: docs/superpowers/specs/2026-08-04-phan-quyen-dong-design.md

BA BẢNG + MỘT ĐỔI CỘT, MỘT MIGRATION — chúng là một thay đổi nghiệp vụ duy nhất
("vai trò do tổ chức tự định nghĩa"), và tách ra thì có trạng thái trung gian
không chạy được: `roles` không có `role_actions` là vai trò không quyền nào, còn
`memberships.role_id` không có `roles` là một FK trỏ vào hư không.

VÌ SAO `control.actions` TỒN TẠI khi actions.py đã là nguồn: nó làm hai việc mà
code không làm được — cho UI nhãn vi/en có thứ tự, và cho role_actions một FK
thật. Đồng bộ bằng seed dưới đây; `test_migration_0104.py` canh hai bên bằng nhau.

VÌ SAO KHÔNG CÓ CỘT `is_system`: quyết định 2026-08-04 — 4 vai trò mẫu là dữ liệu
thường, sửa/xoá được như mọi hàng khác. Thêm cờ khoá là đẻ ra một nhánh UI phải
xử lý riêng, đổi lấy một sự an toàn mà §3.3 của spec đã bảo đảm bằng cách khác
(owner không đi qua ma trận, nên sửa vai trò không khoá cửa được).
"""

import sqlalchemy as sa
from alembic import op

revision = "0104_vai_tro_dong"
down_revision = "0501_kb_index_state"
branch_labels = None
depends_on = None

# 13 nhóm của PQ_01 §3.1. BẢN SAO ĐỌC của core/auth/actions.py — không có đường
# nào cho migration import code ứng dụng (migration phải chạy được ở phiên bản
# code bất kỳ). test_migration_0104.py canh hai bên khớp.
_ACTIONS = [
    ("overview.read", "operate", "Xem Tổng quan · số liệu", "View overview · metrics", 1),
    ("convos.read", "operate", "Xem danh sách Hội thoại + tóm tắt", "View conversations + summary", 2),
    ("convos.transcript.read", "operate", "Đọc bản ghi thoại", "Read transcripts", 3),
    ("convos.handle", "operate", "Nhận chuyển tiếp · đánh dấu đã xử lý", "Take handoff · mark handled", 4),
    ("appts.read", "operate", "Xem Lịch hẹn", "View appointments", 5),
    ("appts.write", "operate", "Sửa · huỷ Lịch hẹn", "Edit · cancel appointments", 6),
    ("catalog.read", "knowledge", "Xem Dự án · Quỹ căn · Tài liệu · Media", "View projects · units · docs · media", 7),
    (
        "catalog.write",
        "knowledge",
        "Thêm · sửa · nhập tệp Dự án · Quỹ căn · Tài liệu · Media",
        "Create · edit · import",
        8,
    ),
    ("catalog.delete", "knowledge", "Xoá dự án · quỹ căn · tài liệu · media", "Delete", 9),
    ("agent_config.read", "configure", "Xem cấu hình agent", "View agent config", 10),
    ("agent_config.write", "configure", "Sửa bản nháp cấu hình agent", "Edit agent config draft", 11),
    ("agent_config.publish", "configure", "Xuất bản · Quay lui", "Publish · rollback", 12),
    ("workspace.admin", "configure", "Khoá API · Thành viên · Cài đặt workspace", "API keys · members · settings", 13),
]

# Ma trận PQ_01 §3.1 — 4 vai trò mẫu seed cho MỖI tổ chức.
# Không phải bậc thang: CSKH và Biên tập là hai NGHỀ khác nhau, không phải hai
# cấp bậc (PQ_01 §2.2). Ép vào bậc thang thì hoặc CSKH sửa được quỹ căn, hoặc
# nhân viên nhập liệu đọc được hội thoại khách.
_MAU = {
    "Quản trị": [c for c, *_ in _ACTIONS],
    "CSKH": [
        "overview.read",
        "convos.read",
        "convos.transcript.read",
        "convos.handle",
        "appts.read",
        "appts.write",
        "catalog.read",
        "agent_config.read",
    ],
    "Biên tập": [
        "overview.read",
        "convos.read",
        "appts.read",
        "catalog.read",
        "catalog.write",
        "catalog.delete",
        "agent_config.read",
    ],
    "Người xem": [
        "overview.read",
        "convos.read",
        "appts.read",
        "catalog.read",
        "agent_config.read",
    ],
}

_MO_TA = {
    "Quản trị": "Toàn quyền: cấu hình agent, xuất bản, mời người, cài đặt",
    "CSKH": "Đọc hội thoại, nhận chuyển tiếp, quản lịch hẹn",
    "Biên tập": "Dự án, quỹ căn, tài liệu, media",
    "Người xem": "Chỉ đọc số liệu và tóm tắt",
}

# Mã vai trò cũ ở memberships.role → tên vai trò mẫu tương ứng.
_MAP_CU = {"admin": "Quản trị", "care": "CSKH", "editor": "Biên tập", "viewer": "Người xem"}


def upgrade() -> None:
    # --- ① Danh mục action -------------------------------------------------
    op.execute(
        """CREATE TABLE control.actions (
               code        text PRIMARY KEY,
               group_name  text NOT NULL CHECK (group_name IN ('operate','knowledge','configure')),
               label_vi    text NOT NULL,
               label_en    text NOT NULL,
               sort_order  int  NOT NULL UNIQUE
           )"""
    )
    for code, nhom, vi, en, thu_tu in _ACTIONS:
        op.execute(
            sa.text(
                "INSERT INTO control.actions (code, group_name, label_vi, label_en, sort_order)"
                " VALUES (:c, :g, :vi, :en, :o)"
            ).bindparams(c=code, g=nhom, vi=vi, en=en, o=thu_tu)
        )

    # --- ② Vai trò ---------------------------------------------------------
    # UNIQUE (org_id, id) KHÔNG thêm ràng buộc mới về tính duy nhất (id đã là PK);
    # nó tồn tại CHỈ để làm đích hợp lệ cho composite FK của memberships. Cùng
    # khuôn 0102 đã dùng cho tenants/users.
    op.execute(
        """CREATE TABLE control.roles (
               id           text PRIMARY KEY,
               org_id       text NOT NULL REFERENCES control.organizations(id) ON DELETE CASCADE,
               name         text NOT NULL,
               description  text,
               created_at   timestamptz NOT NULL DEFAULT now(),
               UNIQUE (org_id, name),
               UNIQUE (org_id, id)
           )"""
    )
    op.execute("CREATE INDEX roles_org_idx ON control.roles (org_id)")

    # action_code RESTRICT, không CASCADE: gỡ một action khỏi danh mục trong khi
    # vai trò còn tích nó là làm rơi quyền của người thật. Gỡ action phải là một
    # migration có chủ đích, DELETE role_actions trước — và như vậy nó hiện ra
    # trong diff.
    op.execute(
        """CREATE TABLE control.role_actions (
               role_id      text NOT NULL REFERENCES control.roles(id)      ON DELETE CASCADE,
               action_code  text NOT NULL REFERENCES control.actions(code)  ON DELETE RESTRICT,
               PRIMARY KEY (role_id, action_code)
           )"""
    )

    # --- ③ Seed 4 vai trò mẫu CHO TỪNG tổ chức -----------------------------
    # Theo từng org, không một bộ dùng chung: dùng chung nghĩa là tổ chức A sửa
    # vai trò thì đổi quyền của tổ chức B (spec §1.3).
    #
    # id = 'r_' + md5(org_id || name) — tất định, nên chạy lại migration trên
    # cùng dữ liệu cho ra cùng id. KHÔNG suy nghĩa: id chỉ cần ổn định, còn tên
    # thì đổi được (spec §2.1). API tạo vai trò mới dùng uuid4().hex.
    # Một HÀM, dùng cho cả backfill lẫn trigger — nên hai đường không thể lệch
    # nhau. Nếu backfill viết riêng một câu INSERT còn trigger viết một câu khác,
    # thì tổ chức cũ và tổ chức mới nhận hai bộ vai trò khác nhau, và không ai
    # phát hiện cho tới lúc một khách hàng mới hỏi vì sao họ thiếu một vai trò.
    #
    # Thân hàm sinh từ _MAU ở trên: ma trận PQ_01 §3.1 chỉ tồn tại MỘT chỗ trong
    # file này. `ON CONFLICT DO NOTHING` cho hàm gọi lại được — dev_seed và test
    # đều cần tính idempotent.
    #
    # ⚠ role_actions TRA id qua SELECT (org_id, name), KHÔNG suy lại bằng md5.
    # `ON CONFLICT (org_id, name) DO NOTHING` ở INSERT roles chỉ bảo đảm KHÔNG
    # tạo trùng tên — nó không bảo đảm hàng đang tồn tại mang đúng id md5. Một
    # vai trò mẫu bị xoá qua API rồi tạo lại cùng tên nhận id uuid4() (API luôn
    # dùng uuid4, xem quan_tri_vai_tro.tao), không phải md5(p_org||name); gọi
    # lại hàm này sau đó thì INSERT roles bị ON CONFLICT chặn (đúng tên đã có),
    # còn INSERT role_actions suy id bằng md5 sẽ nhắm vào một id KHÔNG hàng nào
    # có — FK role_actions.role_id → roles.id nổ ForeignKeyViolationError. Tra
    # theo (org_id, name) luôn trúng hàng THẬT đang tồn tại, bất kể id của nó
    # sinh ra từ đâu.
    nhanh = []
    for ten, codes in _MAU.items():
        ten_q = ten.replace("'", "''")
        mo_ta_q = _MO_TA[ten].replace("'", "''")
        ds = ", ".join("'" + c.replace("'", "''") + "'" for c in codes)
        nhanh.append(
            f"""
              INSERT INTO control.roles (id, org_id, name, description)
                   VALUES ('r_' || md5(p_org || '{ten_q}'), p_org, '{ten_q}', '{mo_ta_q}')
              ON CONFLICT (org_id, name) DO NOTHING;
              INSERT INTO control.role_actions (role_id, action_code)
                   SELECT r.id, c
                     FROM control.roles r, unnest(ARRAY[{ds}]::text[]) AS c
                    WHERE r.org_id = p_org AND r.name = '{ten_q}'
              ON CONFLICT DO NOTHING;
            """
        )
    op.execute(
        f"""CREATE FUNCTION control.seed_vai_tro_mau(p_org text) RETURNS void
            LANGUAGE plpgsql AS $fn$
            BEGIN
            {"".join(nhanh)}
            END $fn$"""
    )

    # Trigger: tổ chức tạo SAU migration này cũng có 4 vai trò. Không có nó thì
    # owner của một khách hàng mới đăng nhập lần đầu và thấy dropdown vai trò
    # rỗng — không ai gán được quyền cho ai, và lời hứa §1.1 của spec là sai.
    #
    # Ở trigger chứ không ở service: hôm nay CHƯA có API tạo tổ chức (thuộc M9),
    # nên org sinh ra từ dev_seed, từ migration, và từ psql tay. Chỉ trigger phủ
    # được cả ba. Khi M9 có API, nó không phải nhớ gọi gì.
    op.execute(
        """CREATE FUNCTION control.trg_seed_vai_tro_mau() RETURNS trigger
           LANGUAGE plpgsql AS $fn$
           BEGIN
             PERFORM control.seed_vai_tro_mau(NEW.id);
             RETURN NEW;
           END $fn$"""
    )
    op.execute(
        """CREATE TRIGGER organizations_seed_vai_tro
             AFTER INSERT ON control.organizations
             FOR EACH ROW EXECUTE FUNCTION control.trg_seed_vai_tro_mau()"""
    )

    # Backfill tổ chức đã có — gọi ĐÚNG hàm mà trigger gọi.
    op.execute("SELECT control.seed_vai_tro_mau(id) FROM control.organizations")

    # --- ④ memberships.role → role_id --------------------------------------
    op.execute("ALTER TABLE control.memberships ADD COLUMN role_id text")
    for ma_cu, ten in _MAP_CU.items():
        op.execute(
            sa.text(
                """UPDATE control.memberships m
                      SET role_id = r.id
                     FROM control.roles r
                    WHERE r.org_id = m.org_id AND r.name = :ten AND m.role = :ma_cu"""
            ).bindparams(ten=ten, ma_cu=ma_cu)
        )
    # Hàng nào còn NULL nghĩa là memberships.role có giá trị ngoài 4 mã — CHECK
    # của 0101 không cho phép, nên đây là bất khả. Vẫn kiểm: nếu nó xảy ra thì
    # SET NOT NULL sẽ nổ với một thông điệp không nói được nguyên nhân.
    op.execute(
        """DO $$
           DECLARE n int;
           BEGIN
             SELECT count(*) INTO n FROM control.memberships WHERE role_id IS NULL;
             IF n > 0 THEN
               RAISE EXCEPTION '0104: % hàng memberships có role ngoài 4 mã đã biết', n;
             END IF;
           END $$"""
    )
    op.execute("ALTER TABLE control.memberships ALTER COLUMN role_id SET NOT NULL")
    op.execute(
        """ALTER TABLE control.memberships
             ADD CONSTRAINT memberships_role_cung_to_chuc_fkey
             FOREIGN KEY (org_id, role_id) REFERENCES control.roles (org_id, id)
             ON DELETE RESTRICT"""
    )
    op.execute("ALTER TABLE control.memberships DROP COLUMN role")


def downgrade() -> None:
    """Ngược đúng thứ tự upgrade() — và TỪ CHỐI khi không ngược được.

    Khôi phục cột `role` cần map ngược tên vai trò → 4 mã cố định. Tổ chức đã đổi
    tên hoặc thêm vai trò thì không map được. Đoán bừa (gán hết về 'viewer') là âm
    thầm tước quyền của cả tổ chức; raise là câu trả lời duy nhất trung thực.
    """
    # DO block không nhận bind param, nên tên 4 vai trò gốc ghép thẳng vào chuỗi.
    # An toàn vì chúng là hằng số trong chính file này, không phải dữ liệu người
    # dùng — nhưng vẫn escape nháy đơn để nếu ai đó đổi _MAP_CU thì không vỡ.
    ten_goc = ", ".join("'" + t.replace("'", "''") + "'" for t in _MAP_CU.values())
    op.execute(
        f"""DO $$
            DECLARE v text;
            BEGIN
              SELECT string_agg(DISTINCT r.name, ', ') INTO v
                FROM control.memberships m
                JOIN control.roles r ON r.id = m.role_id
               WHERE r.name NOT IN ({ten_goc});
              IF v IS NOT NULL THEN
                RAISE EXCEPTION
                  '0104 downgrade TỪ CHỐI: có membership dùng vai trò tuỳ chỉnh (%). '
                  'Chuyển những người đó về 4 vai trò gốc trước khi hạ cấp.', v;
              END IF;
            END $$"""
    )
    op.execute(
        """ALTER TABLE control.memberships ADD COLUMN role text
             CHECK (role IN ('admin','care','editor','viewer'))"""
    )
    for ma_cu, ten in _MAP_CU.items():
        op.execute(
            sa.text(
                """UPDATE control.memberships m SET role = :ma_cu
                     FROM control.roles r
                    WHERE r.id = m.role_id AND r.name = :ten"""
            ).bindparams(ma_cu=ma_cu, ten=ten)
        )
    op.execute("ALTER TABLE control.memberships ALTER COLUMN role SET NOT NULL")
    op.execute("ALTER TABLE control.memberships DROP CONSTRAINT memberships_role_cung_to_chuc_fkey")
    op.execute("ALTER TABLE control.memberships DROP COLUMN role_id")

    op.execute("DROP TRIGGER organizations_seed_vai_tro ON control.organizations")
    op.execute("DROP FUNCTION control.trg_seed_vai_tro_mau()")
    op.execute("DROP FUNCTION control.seed_vai_tro_mau(text)")

    op.execute("DROP TABLE control.role_actions")
    op.execute("DROP INDEX control.roles_org_idx")
    op.execute("DROP TABLE control.roles")
    op.execute("DROP TABLE control.actions")
