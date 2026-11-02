"""agent_api.tenant_status + tenant_keys — agent tự xác thực ở db-mode, bỏ /bootstrap

ĐIỀU KIỆN CỦA 0906 ĐÃ THOẢ, ĐÂY LÀ CHỖ GHI LẠI ĐIỀU ĐÓ.
`0906_view_deployments_cho_agent.py:14-21` cố ý KHÔNG dựng hai view này và nêu rõ điều kiện:

    "Cả hai chỉ nên dựng nếu team agent chốt BỎ bootstrap"

Ngày 2026-08-05 team agent chốt đúng như vậy (`docs/support_agent_system_connect_db/
bug-portal-control-plane-missing.md`): gateway + worker chạy `AGENT_CONFIG_SOURCE=db`, KHÔNG
gọi `POST /api/v1/agent/bootstrap` nữa, và xác thực bằng cách đọc thẳng hash khoá từ Postgres.
Nên migration này KHÔNG lật lại quyết định của 0906 — nó là nhánh mà 0906 đã chừa sẵn.

⚠️ CÁI GIÁ PHẢI GHI RA, vì nó không lấy lại được:
  · `agent_keys.last_used_at` KHÔNG còn phản ánh nhánh db-mode. Đường đọc của agent là
    read-only và Postgres không có "SELECT trigger", nên không có cách nào cập nhật nó từ
    một câu SELECT. Cột "Dùng cuối" trên màn «Tích hợp & API» vì thế chỉ đúng cho khoá dùng
    qua `/bootstrap`. Muốn biết pod còn sống: dùng `control.agent_heartbeats`, không dùng cột
    đó. Team agent đã xác nhận và chọn phương án này (câu trả lời Q3, phương án (a)).
  · `audit_log` mất dấu vết mỗi lần xác thực. `/bootstrap` ghi một dòng `agent.bootstrap`;
    đường này không ghi gì. Portal không còn trả lời được "khoá X được dùng lúc nào".
  · Nhịp chống dò khoá (10 lần / 5 phút, Redis) KHÔNG áp cho đường này — nó nằm ở
    `service.bootstrap()`. Bù lại một phần: kẻ dò phải có credential Postgres mới chạm được
    view, tức đã qua một cổng khác rồi.

VÌ SAO LỘ `key_sha256` LÀ CHẤP NHẬN ĐƯỢC (mối lo lớn nhất của 0906):
  · View lọc `portal.current_tenant()` như bốn view kia, nên nó KHÔNG "đưa hash khoá của
    TOÀN BỘ tenant" như 0906 lo — mỗi lượt đọc chỉ thấy tenant đang khai.
  · `bam_khoa()` là `sha256(khoa_tho)` của một chuỗi 256-bit ngẫu nhiên đều. Biết hash không
    suy ngược ra khoá, và gateway so `sha256(plaintext)` chứ không nhận hash trực tiếp — nên
    đọc được hash không đăng nhập được.
  · Kẻ đọc được view này đã phải có credential Postgres. Với `odyssey_app` (thành viên
    `portal_api`) thì credential đó vốn đã đọc/ghi được cả schema `control` — hash khoá không
    phải mắt xích yếu nhất ở đó. Xem mục "việc còn lại" trong doc bàn giao.

CẢ HAI VIEW LỌC `portal.current_tenant()` — BẮT BUỘC, KHÔNG PHẢI LỰA CHỌN:
`tests/isolation/test_isolation_catalog.py::test_moi_view_agent_api_tu_loc_tenant` đỏ nếu
thiếu. View trong `agent_api` là view DEFINER (chạy bằng quyền owner) nên RLS KHÔNG áp bên
trong nó — vị từ tenant trong chính định nghĩa view là lớp lọc duy nhất.

HỆ QUẢ CHO PHÍA AGENT, PHẢI ĐỌC: agent BẮT BUỘC `set_config('app.tenant_id', <tenant>, true)`
trong cùng transaction TRƯỚC câu SELECT — kể cả câu xác thực. Không khai thì `current_tenant()`
trả NULL và view trả 0 hàng ⇒ xác thực trượt (fail-closed, đúng thiết kế) chứ không phải lỗi.

Revision ID: 0907_view_control_plane
Revises: 0906_view_deployments
"""

from alembic import op

revision = "0907_view_control_plane"
down_revision = "0906_view_deployments"
branch_labels = None
depends_on = None

HAU_TO_GIU_LAI = "_seed_agent_truoc_0907"
"""Hậu tố đặt cho BẢNG của bên khác trùng tên với view migration này sắp tạo.

VÌ SAO ĐỔI TÊN CHỨ KHÔNG `DROP`: xem `_nhuong_cho()`."""


def _nhuong_cho(ten: str) -> str:
    """SQL dọn chỗ cho view `agent_api.<ten>` — chịu được cả ba trạng thái đã gặp thật.

    LẦN DEPLOY 2026-08-05 VỠ Ở ĐÂY: `relation "tenant_status" already exists`. Nguyên nhân —
    team agent đã chạy "Phụ lục A" trong `bug-portal-control-plane-missing.md` (phần chính họ
    ghi "KHÔNG dùng cho prod") lên đúng DB dùng chung, tạo `agent_api.tenant_status` và
    `agent_api.tenant_keys` thành BẢNG THẬT kèm dữ liệu giả của tenant `dufake`.
    `CREATE VIEW` trần vỡ, và cả job deploy đỏ.

    BA TRẠNG THÁI, BA XỬ LÝ:
      · không có gì      → tạo view bình thường (DB sạch, máy dev, môi trường mới)
      · đã là VIEW       → `DROP` rồi tạo lại (migration chạy lại được, không phải sửa tay)
      · đang là BẢNG     → ĐỔI TÊN giữ lại, KHÔNG `DROP`

    VÌ SAO ĐỔI TÊN CHỨ KHÔNG XOÁ — điểm quan trọng nhất của hàm này: bảng đó **không phải của
    Portal**. Nó do team khác tạo, chứa dữ liệu họ đang dùng để tự test, và một migration
    không được phép xoá dữ liệu mà nó không sở hữu. `ALTER TABLE ... RENAME` giữ nguyên từng
    hàng và hoàn tác bằng đúng một câu lệnh; `DROP TABLE` thì không. Nếu sau khi đối chiếu
    thấy bảng cũ vô dụng thật, xoá nó là việc của người vận hành, làm tay, có chủ đích.

    `RAISE NOTICE` chứ không im lặng: nó hiện trong log job deploy, nên người bấm deploy biết
    ngay là có một bảng vừa bị dời chỗ — thay vì phát hiện ra ba tuần sau.
    """
    return f"""
        DO $$
        DECLARE v_kind "char";
        BEGIN
            SELECT c.relkind INTO v_kind
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'agent_api' AND c.relname = '{ten}';

            IF v_kind = 'v' THEN
                EXECUTE 'DROP VIEW agent_api.{ten}';
            ELSIF v_kind IS NOT NULL THEN
                EXECUTE 'ALTER TABLE agent_api.{ten} RENAME TO {ten}{HAU_TO_GIU_LAI}';
                RAISE NOTICE
                    'agent_api.{ten} đang là BẢNG (không phải view của Portal) — đã đổi tên '
                    'thành agent_api.{ten}{HAU_TO_GIU_LAI} và giữ nguyên dữ liệu. '
                    'View của Portal nay chiếm tên cũ. Đối chiếu rồi xoá bảng kia bằng tay.';
            END IF;
        END $$
    """


def upgrade() -> None:
    # ── tenant_status ────────────────────────────────────────────────────────
    # `active` = `lifecycle = 'active'` — ĐƠN GIẢN, KHÔNG dùng derive_tenant_status().
    #
    # Hai lý do. (1) Đây là cổng CHO PHÉP PHỤC VỤ, và điều kiện đó phải khớp đúng thứ
    # `service.bootstrap()` đang kiểm (`lifecycle != "active"` ⇒ 403) — hai đường xác thực
    # cho cùng một tenant mà kết luận khác nhau là một lỗi không ai truy ra được.
    # (2) `derive_tenant_status()` trộn thêm heartbeat và live_version để ra
    # provisioning/publishing/disconnected — đó là nhãn HIỂN THỊ cho màn hình người dùng.
    # Dùng nó ở đây thì một pod vừa khởi động (chưa kịp gửi nhịp tim ⇒ `provisioning`) sẽ tự
    # từ chối chính mình, và không bao giờ lên được.
    #
    # `id AS tenant_id`: cột trong `control.tenants` tên là `id`; hợp đồng agent gọi là
    # `tenant_id`. Đổi tên ở view chứ không đổi bảng.
    op.execute(_nhuong_cho("tenant_status"))
    op.execute(
        """
        CREATE VIEW agent_api.tenant_status AS
        SELECT t.id AS tenant_id, (t.lifecycle = 'active') AS active
          FROM control.tenants t
         WHERE t.id = portal.current_tenant()
        """
    )
    op.execute("GRANT SELECT ON agent_api.tenant_status TO agent_all")

    # ── tenant_keys ──────────────────────────────────────────────────────────
    # `control.agent_keys` KHÔNG có cột `tenant_id` — nó treo vào `deployment_id`, và tenant
    # suy qua `deployments`. JOIN ở đây chứ không thêm cột vào bảng: một cột `tenant_id` trên
    # `agent_keys` là nguồn sự thật thứ hai, và hai nguồn thì có ngày lệch.
    #
    # `active` = `revoked_at IS NULL`, cùng vị từ mà `repo.tra_khoa()` dùng cho `/bootstrap`.
    # Nhờ vậy thu hồi khoá từ màn «Tích hợp & API» có hiệu lực NGAY trên cả hai đường —
    # phía agent còn TTL cache riêng (gateway_cred_cache_ttl_sec) nên độ trễ thật là TTL đó.
    #
    # KHÔNG lộ `key_prefix`, `label`, `created_by`, `created_at`: gateway chỉ so hash. Mỗi cột
    # thừa là một cột phải bảo vệ mà không đổi lại được gì.
    op.execute(_nhuong_cho("tenant_keys"))
    op.execute(
        """
        CREATE VIEW agent_api.tenant_keys AS
        SELECT d.tenant_id, k.key_sha256, (k.revoked_at IS NULL) AS active
          FROM control.agent_keys k
          JOIN control.deployments d ON d.id = k.deployment_id
         WHERE d.tenant_id = portal.current_tenant()
        """
    )
    op.execute("GRANT SELECT ON agent_api.tenant_keys TO agent_all")

    # ── search_path cho role runtime dùng chung ──────────────────────────────
    # Agent query `agent_published_config` KHÔNG kèm schema (hợp đồng §1.1, và code của họ ở
    # `storage/agent_config_store.py`). 0901 đã giải đúng bài này bằng một dòng — nhưng cho
    # role `odyssey_agent`. Trên `agents-dev` role runtime thật là `odyssey_app`
    # (`.gitlab-ci.yml:150`), nên dòng của 0901 không chạm tới nó và query kia không resolve
    # được. Đó là nguyên nhân thật của "LLM init failed: no published config" — KHÔNG phải
    # thiếu view: `agent_api.agent_published_config` đã có từ 0904.
    #
    # AN TOÀN CHO PORTAL: `odyssey_app` cũng là role backend của Portal (nó được GRANT cả
    # `portal_api` lẫn `agent_all`). Đã kiểm toàn bộ `src/portal`: mọi câu SQL đều kèm schema
    # (`control.`/`tenant_data.`/`agent_api.`), chỗ duy nhất không kèm là `pg_roles` — luôn ở
    # `pg_catalog`, không bị search_path chi phối. Nên thêm `agent_api` không đổi hành vi nào
    # của Portal.
    #
    # KHÔNG thêm `control` vào search_path — cùng lý lẽ 0901:97: một câu truy vấn quên schema
    # chạm nhầm bảng `control` là thứ không có triệu chứng.
    #
    # IDEMPOTENT + CÓ ĐIỀU KIỆN: role thuộc phạm vi CLUSTER và được tạo TAY ở lần deploy đầu
    # (`.gitlab-ci.yml:158`), nên nó KHÔNG tồn tại trên DB dev/test. `ALTER ROLE` trần sẽ vỡ
    # ở đó — tức migration xanh trên Aurora nhưng đỏ trên máy dev, đúng loại lệch tệ nhất.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'odyssey_app') THEN
                ALTER ROLE odyssey_app SET search_path = agent_api, public;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'odyssey_app') THEN
                ALTER ROLE odyssey_app RESET search_path;
            END IF;
        END $$
        """
    )
    # `IF EXISTS` + CHỈ `DROP VIEW`: nếu upgrade đã đổi tên một bảng của bên khác sang
    # `*_seed_agent_truoc_0907`, downgrade KHÔNG đổi tên nó trở lại. Cố ý — hạ migration là
    # gỡ thứ Portal đã tạo, không phải dựng lại trạng thái của một hệ khác. Muốn khôi phục
    # bảng cũ thì một câu `ALTER TABLE ... RENAME` bằng tay, có chủ đích.
    op.execute("DROP VIEW IF EXISTS agent_api.tenant_keys")
    op.execute("DROP VIEW IF EXISTS agent_api.tenant_status")
