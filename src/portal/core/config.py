"""Cấu hình portal. Mọi biến môi trường khai ở đây, không đọc os.environ rải rác."""

import hashlib
import hmac

from pydantic_settings import BaseSettings, SettingsConfigDict

# HAI DSN, HAI ROLE — KHÔNG PHẢI MỘT DSN DÙNG CHO CẢ HAI VIỆC.
#
# Đây là điều kiện 2 của cách ly (xem docs/contracts/isolation.md §6) viết ở tầng
# cấu hình. `portal_migrator` là CHỦ SỞ HỮU của mọi schema và, ở container dev/test,
# chính là bootstrap superuser. Superuser bỏ qua RLS **bất kể FORCE**. Nên một
# tiến trình runtime nối bằng `portal_migrator` là một tiến trình mà toàn bộ ba lớp
# cách ly không áp dụng: một job handler quên WHERE sẽ ĐỌC VÀ GHI xuyên mọi tenant,
# âm thầm, không có lỗi nào.
#
# Trước bản này default của `database_url` là `portal_migrator`, và
# portal/worker/__main__.py nối bằng đúng nó — tức `make worker` chạy mọi handler ở
# chế độ không có cách ly. Đó là lý do hai hằng số dưới đây phải tách rời và default
# của runtime phải là role hẹp.
# CỔNG 5442, KHÔNG PHẢI 5433 — xem ../docs/dev-ports.md và docker-compose.local.yml.
# 5433 là `icr-postgres` của một project khác trên cùng máy dev, và nó ĐANG CHẠY.
# Default phải là cổng dùng thật, vì default là thứ chạy khi ai đó chưa có `.env`:
# trỏ vào DB của project khác thì `alembic upgrade` hoặc fail vì thiếu role, hoặc
# — nếu tên role trùng — chạy migration vào đúng DB của người khác.
_DEFAULT_RUNTIME_DSN = "postgresql://portal_api:apidev@localhost:5442/portal"
_DEFAULT_MIGRATOR_DSN = "postgresql://portal_migrator:dev@localhost:5442/portal"


def to_alembic_url(dsn: str) -> str:
    """Alembic chạy qua SQLAlchemy + psycopg (sync); runtime dùng asyncpg.

    Tách thành hàm vì cả Settings lẫn conftest đều cần phép đổi này — và chính
    việc hai chỗ tự đổi theo cách khác nhau đã từng sinh bug env.py migrate sai DB.
    """
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


class Settings(BaseSettings):
    """Cấu hình runtime + migration.

    VÌ SAO HAI CREDENTIAL: hai việc cần hai mức quyền khác nhau và không có mức nào
    an toàn cho cả hai. Migration cần DDL trên mọi schema (nó là owner). Runtime cần
    ĐÚNG những gì `enforce_tenant_isolation()` đã grant cho `portal_api`, và tuyệt
    đối KHÔNG được là owner — vì Postgres FORCE RLS chỉ có nghĩa khi kẻ truy vấn
    không phải chủ bảng.

    Trước bản này `alembic_url` chỉ là `database_url` đổi driver, nên hai việc dùng
    CÙNG một credential: đặt đúng cho runtime thì `alembic upgrade` hỏng, đặt đúng
    cho migration thì runtime chạy không có cách ly. Chỉ cấu hình KHÔNG an toàn là
    chạy được — đúng nghĩa một cái bẫy.

    LUẬT: KHÔNG tiến trình runtime nào (API, worker, script one-off phục vụ request)
    được dùng `migrator_url`. Nó chỉ dành cho `alembic`. Xem deploy/README.md §1–§2.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = _DEFAULT_RUNTIME_DSN
    """DSN RUNTIME (asyncpg) — role `portal_api`. API và worker dùng đúng cái này."""

    migrator_url: str = _DEFAULT_MIGRATOR_DSN
    """DSN chỉ-DDL — role `portal_migrator`. CHỈ `alembic` dùng, không tiến trình nào khác."""

    redis_url: str = "redis://localhost:6382/0"
    """Phiên đăng nhập. Cổng 6382 = redis của docker-compose.local.yml.

    KHÔNG phải 6379 (santa) và KHÔNG phải 6380 (icr-redis) — cả hai đang chạy trên
    máy dev. Nối sai cổng ở đây nghĩa là phiên đăng nhập của portal ghi vào Redis
    của project khác: không có lỗi nào, chỉ là người dùng bị đăng xuất ngẫu nhiên
    khi project kia flush. Xem ../docs/dev-ports.md.
    """

    worker_budget: int = 12
    """Số job chạy đồng thời trong MỘT worker. Trần từng loại việc khai ở register().

    Nhân số container worker sẽ NHÂN con số này lên — mỗi tiến trình đếm in-flight
    riêng, không ai biết tổng.
    """

    public_base_url: str = ""
    """Gốc URL CÔNG KHAI của portal. HAI người đọc, một giá trị (gộp 2026-08-17):

    ① ảnh/tệp agent gửi cho khách — `core/public_url.py` nối
      `{base}/api/v1/public/files/<khoá>`. Địa chỉ nội bộ (`localhost`…) ⇒ coi như
      chưa cấu hình, KHÔNG sinh link: khách không mở được thì thà không có ảnh.
      Đổi domain thì chạy lại `scripts/backfill_public_url.py` (script đó vẫn NÉM
      với địa chỉ nội bộ — nó GHI vào DB, chỗ đó ồn ào mới đúng).
    ② link đặt mật khẩu trong thư mời/đăng ký — `core/mailer.py::url_tuyet_doi()`
      nối `{base}/invite/<token>`.

    ⚠ Vì ② là một route của app FE còn ① là route của backend, biến này phải là
    origin phục vụ CẢ HAI — `/` ra app FE và `/api/` ra backend. Prod và dev
    (vite proxy `^/api/` → 8100) đều thoả. Một tunnel chỉ expose cổng 8100 thì
    KHÔNG: ảnh chạy, link mời 404.

    RỖNG = không sinh link ảnh VÀ mailer tắt (in thư ra stdout). An toàn ở dev."""

    # ─── Kho tệp (M3 — bundle + con trỏ LIVE) ────────────────────────────────
    #
    # Ở production đây là Amazon S3: `s3_endpoint_url` để trống, và credential
    # KHÔNG đi qua biến môi trường mà lấy từ IAM role của task — nên hai trường
    # khoá dưới đây rỗng ở prod là ĐÚNG, không phải thiếu cấu hình.
    # Ở dev/test là MinIO cùng giao thức. Xem deploy/README.md §6–§7.

    s3_endpoint_url: str | None = "http://localhost:9002"
    """Rỗng/None ⇒ dùng endpoint AWS thật. Cổng 9002 = minio của docker-compose.local.yml."""

    s3_bucket: str = "odyssey"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"

    s3_redirect_enabled: bool = False
    """Hai route phát tệp trả 307 tới URL kho có hạn thay vì tự tải byte về rồi gửi tiếp.

    ⚠️ MẶC ĐỊNH TẮT, và bật là một quyết định VẬN HÀNH có cổng kiểm chứng: URL có hạn trỏ
    vào host của KHO, không phải host Portal. Kho không mở được từ Internet công cộng thì
    307 làm ảnh vỡ phía khách mà không có lỗi nào phía ta — repo này đã vấp đúng chỗ đó hai
    lần (`thumb_url` từng trỏ vào kho nội bộ mà cả agent lẫn khách đều không với tới).
    Bật SAU khi đã mở một URL công khai từ trình duyệt ngoài mạng nội bộ.
    """

    s3_redirect_ttl_sec: int = 900
    """Hạn của URL 307. Không lưu ở đâu cả — sinh mới mỗi lượt xem, nên hết hạn không
    làm chết link nào: DB và payload giữ KHOÁ, không giữ URL."""

    # ─── Kho tri thức (M6 — một collection mỗi tenant) ───────────────────────
    #
    # Cổng 6343, KHÔNG phải 6333 mặc định — xem ../docs/dev-ports.md. Trỏ nhầm vào
    # Qdrant của project khác KHÔNG báo lỗi: nó nhận collection mới và trả kết quả
    # bình thường, chỉ là ở sai chỗ.

    qdrant_url: str = "http://localhost:6343"
    qdrant_api_key: str = ""
    """HAI VAI, cùng một chuỗi — phải TRÙNG `service.api_key` của Qdrant:
      1. Khoá portal tự dùng để GHI (`kb/index/store.py`) — quyền đầy đủ.
      2. Khoá KÝ token chỉ-đọc phát cho pod agent qua `/runtime-credentials`
         (`enrollment/qdrant_jwt.py`). JWT HS256 ký bằng chính nó.

    Một chuỗi cho hai vai không phải tiết kiệm mà là ràng buộc của Qdrant: nó
    verify JWT bằng đúng `service.api_key`, không có khoá ký thứ hai.

    RỖNG = môi trường chưa bật xác thực Qdrant ⇒ `/runtime-credentials` trả
    `kb.api_key: null` và pod nối không kèm khoá. Đó là hiện trạng, KHÔNG phải
    trạng thái đích — xem `docs/contracts/dau-noi-agent.md` §"Bật xác thực Qdrant"
    để biết thứ tự ba bước bật mà không gián đoạn."""

    token_enc_key: str = ""
    """Khoá mã hoá at-rest cho hai cột khoá THÔ (`core/bi_mat_luu.py`).

    KHOÁ RIÊNG, KHÔNG dẫn xuất từ `AGENT_MASTER_KEY` — và đây là quyết định về VÒNG
    ĐỜI, không phải về mật mã. Xoay `AGENT_MASTER_KEY` hôm nay nghĩa là mọi tenant
    suy lại mật khẩu Postgres/S3 (đã có `secret_version` cho đúng việc đó). Nếu nó
    còn giải mã cả token đang lưu thì một lần xoay mà quên mã hoá lại là **mất
    vĩnh viễn** mọi khoá thô — một thao tác vận hành bình thường biến thành mất dữ
    liệu. Hai bí mật để quản lý, đổi lấy hai vòng đời tách rời.

    RỖNG ở `development` ⇒ dẫn xuất từ khoá gốc dev, để máy dev và CI không phải
    thêm cấu hình. Ở `production` mà rỗng thì **ném** — im lặng ghi plaintext là
    đúng thứ bản vá này tồn tại để chấm dứt."""

    ingest_nhip_events_moi_phut: int = 120
    """Trần request/phút cho `POST …/events`, tính THEO TOKEN.

    120 × `TRAN_LO` (500) = 60.000 bản ghi/phút — thoải mái cho một lượt nạp ban
    đầu, mà vẫn chặn một vòng lặp hỏng ở 2 request/giây. Đếm REQUEST chứ không
    đếm bản ghi: xem docstring `modules/ingest/nhip.py`."""

    ingest_nhip_manifest_moi_gio: int = 30
    """Trần request/giờ cho `POST …/manifest`, tính THEO TOKEN.

    Thấp hơn hẳn `/events` vì mỗi lượt là một phép so trên TOÀN BỘ dữ liệu (tới
    20.000 mục), còn nhịp hợp lệ thì chỉ là hằng đêm. 30/giờ vẫn rộng rãi cho dev
    bên khách thử adapter, và vẫn chặn được vòng lặp quét toàn bảng."""

    ingest_loi_giu_ngay: int = 30
    """Giữ `ingest_errors` bao nhiêu ngày. Bảng này CHỈ LỚN LÊN nếu không ai dọn.

    30 ngày vì nó là bảng để dev bên khách ĐỌC RỒI ĐI SỬA adapter — một dòng lỗi
    của tháng trước thì hoặc đã sửa, hoặc không ai còn nhìn. Giữ lâu hơn không
    thêm câu trả lời nào, chỉ thêm dung lượng."""

    ingest_loi_tran_hang: int = 2000
    """Trần số dòng lỗi giữ lại MỖI TENANT, sau khi đã cắt theo tuổi.

    Cần cả hai vế: cắt theo tuổi không chặn được một ĐỢT BÙNG — adapter hỏng đẩy
    toàn payload sai ở nhịp tối đa sinh tới 60.000 dòng/phút, và chúng nằm đó trọn
    30 ngày. Giao diện chỉ đọc 200 dòng mới nhất (`TRAN_LOI_TRA_VE`), nên 2.000 đã
    là gấp mười lần thứ ai đó nhìn thấy."""

    ingest_im_lang_ngay: int = 3
    """Bao nhiêu ngày không nhận được bản kê đối soát thì coi tenant là «im lặng».

    3 = chịu được HAI lần lỡ của một job chạy hằng đêm. Đặt 1 là mọi trục trặc một
    đêm thành một cảnh báo, và cảnh báo kêu vì chuyện tự khỏi là cách dạy người
    trực bỏ qua nó.

    ⚠️ CẤU HÌNH ĐƯỢC vì con số đúng phụ thuộc thứ đã hứa với khách, mà hợp đồng
    hiện chỉ nói bản kê «nên chạy định kỳ» — chưa chốt tần suất. Chốt xong thì
    sửa mặc định ở đây cho khớp, đừng để mỗi môi trường một số."""

    # ─── Đấu nối agent ngoài (M10) ───────────────────────────────────────────

    environment: str = "development"
    """development | production. Quyết định app có từ chối bí mật yếu không."""

    agent_master_key: str = ""
    """Khoá gốc suy dẫn MỌI credential agent (modules/enrollment/bi_mat.py).

    BÍ MẬT HẠNG CAO NHẤT TRONG HỆ: rò nó là suy được credential của MỌI tenant.
    Không có mặc định ở production. Đổi nó = mọi tenant phải xoay bí mật.
    Sinh: python -c 'import secrets;print(secrets.token_urlsafe(32))'
    """

    gateway_base_domain: str = "agents-dev.noble.vn"
    """Tên miền gốc của gateway agent. `ENDPOINT_URL` của MỌI tenant suy từ nó —
    `wss://<tenant_id>.<đây>/v1/chat`, xem modules/enrollment/endpoint.py.

    KHÔNG phải bí mật: nó là hostname công khai, có thể để mặc định ở prod.

    Đổi giá trị này là đổi endpoint của TẤT CẢ tenant cùng lúc, và các khoá đã bàn
    giao trước đó vẫn dùng được (khoá không dính domain) — nhưng URL đã gửi cho
    đối tác thì hết trỏ đúng. Nên coi nó là hằng số một lần, không phải thứ tinh
    chỉnh theo môi trường.

    Không có dấu `.` đầu, không có `/` cuối — `url_endpoint_agent()` cố ý không gọt."""

    gateway_ws_base_url: str = "wss://agent-uat.noble.vn"
    """Origin WS của gateway — MỘT domain dùng chung, workspace suy từ khoá Bearer.

    Đây là mô hình ĐANG CHẠY từ 2026-08-10. `gateway_base_domain` ngay trên mô tả
    mô hình CŨ (một subdomain mỗi tenant) mà cả `gateway-voice-ws-spec.md` §1 lẫn
    handoff chat §1 tuyên bố lỗi thời — nên hai trường này không thay thế nhau và
    cũng không nên nhất quán với nhau; cái dưới đúng, cái trên còn vì
    `endpoint_*_url` chưa được sửa theo.

    Không có `/` cuối: `gateway_docs` ghép `{đây}/v1/chat`."""

    platform_admin_token: str = ""
    """Token cho route /admin/* của M10 — quản trị NỀN TẢNG, xuyên tenant.

    KHÔNG dùng ACTIONS: 13 nhóm của PQ_01 là quyền TRONG một workspace, và M2a
    phát cả 13 cho MỌI user — thêm một action quản trị vào đó là phát quyền nền
    tảng cho mọi người dùng. TẠM THỜI tới khi M2b có vai thật.
    """

    runtime_credentials_ttl_seconds: int = 3600
    """TTL của credential trả về từ `/runtime-credentials`. Pod tự làm mới trước khi hết."""

    def token_enc_key_bytes(self) -> bytes:
        """Khoá mã hoá at-rest. Ném nếu production chưa cấu hình.

        Ném lúc GỌI chứ không lúc dựng `Settings` — cùng lý lẽ `master_key_bytes`:
        `Settings()` được dựng ở đủ loại test và script, và một validator cứng làm
        vỡ những thứ không liên quan.
        """
        from portal.modules.enrollment.bi_mat import DO_DAI_MASTER_TOI_THIEU

        if not self.token_enc_key:
            if self.environment != "development":
                raise ValueError(
                    "TOKEN_ENC_KEY chưa đặt. Không có nó thì khoá thô nằm plaintext trong DB — "
                    "sinh một chuỗi: python -c 'import secrets;print(secrets.token_urlsafe(32))'"
                )
            # Dev: dẫn xuất từ khoá gốc dev để không phải thêm cấu hình. KHÔNG dùng
            # thẳng `master_key_bytes()` — hai vai phải khác chuỗi ngay cả ở dev,
            # nếu không thì thói quen «hai cái này giống nhau» đi thẳng vào prod.
            return hmac.new(self.master_key_bytes(), b"token-enc-dev", hashlib.sha256).digest()
        raw = self.token_enc_key.encode()
        if len(raw) < DO_DAI_MASTER_TOI_THIEU:
            raise ValueError(f"TOKEN_ENC_KEY phải từ {DO_DAI_MASTER_TOI_THIEU} byte, nhận {len(raw)}")
        return raw

    def master_key_bytes(self) -> bytes:
        """Khoá gốc dạng bytes. Ném ValueError nếu nó không đủ mạnh.

        Ném lúc GỌI chứ không phải lúc dựng Settings: `Settings()` được dựng
        trong test và script với đủ loại cấu hình, và một validator cứng ở đó làm
        mọi thứ không liên quan cũng vỡ. Chỗ duy nhất cần khoá mạnh là chỗ dùng nó.
        """
        from portal.modules.enrollment.bi_mat import DO_DAI_MASTER_TOI_THIEU

        if not self.agent_master_key and self.environment == "development":
            return b"khoa-goc-dev-32-byte-khong-dung-o-production"
        raw = self.agent_master_key.encode()
        if len(raw) < DO_DAI_MASTER_TOI_THIEU:
            raise ValueError(
                f"AGENT_MASTER_KEY phải từ {DO_DAI_MASTER_TOI_THIEU} byte, nhận {len(raw)}. "
                f"Sinh: python -c 'import secrets;print(secrets.token_urlsafe(32))'"
            )
        return raw

    # ─── Hai khối endpoint mất chủ sau khi bỏ tầng tổ chức (2026-08-15) ──────
    #
    # Cả hai TẮT mặc định. Chúng không bị xoá — bảng, code và test giữ nguyên để
    # bật lại khi có mô hình admin/quyền động. Xem spec bo-organization §6.2.

    roles_crud_enabled: bool = False
    """Cho phép GHI `control.roles` qua API (POST/PATCH/DELETE /roles).

    Vai trò đã TOÀN CỤC từ migration 0105 (một bộ 4 dùng chung cho mọi workspace),
    và cửa thật cũ của khối này là `users.org_role = 'owner'` — đã bị bỏ. Để mở
    thì một Quản trị của workspace BẤT KỲ sẽ sửa/xoá được vai trò của TẤT CẢ
    workspace khác. ĐỌC là chuyện khác và vẫn mở: FE cần `GET /roles` để dựng
    dropdown chọn vai trò khi mời thành viên.
    """

    users_admin_enabled: bool = False
    """Cho phép 6 đường quản trị user toàn hệ thống (`/users*`).

    Cùng lý do: không còn admin hệ thống nào làm chủ khối này. Tạo tài khoản giờ
    đi qua `POST /auth/register`, và quản lý người TRONG một workspace đi qua
    `/members` (gate `WORKSPACE_ADMIN`, không đổi).
    """

    # ─── Gửi thư (spec dang-ky-tu-phuc-vu §5.2) ──────────────────────────────

    smtp_host: str = ""
    """RỖNG ⇒ mailer in thư ra stdout thay vì gửi. Cùng lối `public_base_url`:
    một môi trường chưa cấu hình phải chạy được, không phải nổ."""

    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    """Địa chỉ gửi, ví dụ `no-reply@noblex.vn`. Phải là identity đã verify ở SES."""
    smtp_from_name: str = "NobleX"

    smtp_starttls: bool = True
    """⚠ TÊN NÀY CỐ Ý KHÁC `SMTP_SECURE` của Nodemailer.

    Cổng 587 + `secure=false` bên Nodemailer nghĩa là STARTTLS: mở plaintext rồi
    nâng cấp TLS TRƯỚC khi gửi credential. `secure=true` mới là TLS ngầm (465).
    Ai map `SMTP_SECURE=false` thẳng thành `use_tls=False` sẽ đẩy user/pass của
    SES qua Internet dưới dạng chữ thường, và không có triệu chứng nào."""

    # Gốc URL để mailer ghép link tuyệt đối từ `invitePath` tương đối: dùng
    # `public_base_url` khai ở trên, KHÔNG một biến riêng.
    #
    # Từng có `portal_base_url`/`PORTAL_BASE_URL` riêng cho việc này (2026-08-17
    # → 2026-08-17, gộp cùng ngày). Hai biến, một giá trị: link ảnh đi qua
    # `/api/v1/public/files/` — route của CHÍNH backend này, và ở mọi môi trường
    # nó ở cùng origin với app FE (prod: một domain; dev: vite proxy `^/api/`
    # sang cổng 8100). Nên «gốc công khai của ảnh» và «gốc của FE» chưa bao giờ
    # là hai địa chỉ khác nhau, chỉ là hai biến cùng phải đặt đúng — và
    # `deploy/odyssey-portal-backend.env.example` đặt được một biến, quên biến
    # kia, nên production chạy với mailer TẮT mà không ai thấy.
    #
    # ⚠ RỖNG ⇒ mailer coi như tắt (`mailer.dang_bat()`): gửi một thư chứa link
    # gãy còn tệ hơn không gửi.

    signup_enabled: bool = True
    """Công tắc `POST /auth/register`. MẶC ĐỊNH BẬT — quyết định người yêu cầu
    2026-08-15 (spec §7.1: không rào chống lạm dụng).

    Nó KHÔNG phải một tầng an toàn; nó là khả năng tắt đăng ký mà không cần
    deploy khi có sự cố."""

    # ─── Cửa Google (spec 2026-08-18) ────────────────────────────────────────

    google_client_id: str = ""
    """RỖNG ⇒ tắt hẳn cửa Google. Cùng lối `smtp_host`: một chuỗi rỗng là công
    tắc, không phải một cấu hình sai.

    Lấy ở Google Cloud Console → Credentials → OAuth client ID → Web application.
    Không tốn phí: đăng nhập bằng Google không phải API tính theo lượt gọi."""

    google_client_secret: str = ""
    """CHỈ sống ở backend. Nó đi cùng `code` trong lượt POST /token máy-chủ-tới-
    máy-chủ và không bao giờ đi qua trình duyệt — đó là toàn bộ lý do chọn
    Authorization Code thay vì để FE nhận id_token (spec §5)."""

    def google_bat(self) -> bool:
        """ĐÒI ĐỦ CẢ HAI BIẾN. Nửa cấu hình còn tệ hơn không cấu hình: nút hiện
        ra, người dùng bấm, rồi đổi code thất bại ở bước 7 và họ chỉ thấy một
        lần redirect về /login không lý do."""
        return bool(self.google_client_id and self.google_client_secret)

    def google_redirect_uri(self) -> str:
        """Suy từ `public_base_url`, KHÔNG một biến thứ ba — cùng lý lẽ file này
        đã ghi cho mailer: hai biến cùng phải đặt đúng thì có ngày một cái đúng
        một cái quên.

        `rstrip('/')` vì Google khớp redirect_uri theo TỪNG KÝ TỰ. Một dấu gạch
        chéo thừa ở `public_base_url` sinh ra `//api/v1/...` và Google từ chối
        với một thông báo không nói ra nguyên nhân.
        """
        return f"{self.public_base_url.rstrip('/')}/api/v1/auth/google/callback"

    def kiem_tra_google_mau_thuan_san_xuat(self) -> None:
        """Chặn GOOGLE_CLIENT_ID bật mà thiếu PUBLIC_BASE_URL ở production.

        CÙNG KHUÔN `_kiem_token`/`kiem_tra_dang_ky_mau_thuan_san_xuat`: kiểm LÚC
        GỌI, không phải lúc dựng `Settings()`.

        Cửa Google cần `public_base_url` để dựng redirect_uri. Thiếu nó thì
        redirect_uri thành "/api/v1/auth/google/callback" — Google từ chối, và
        nó từ chối ở production, LÚC CHẠY, với thông báo không nói ra vì sao.

        ⚠ NGƯỜI GỌI THẬT — và DUY NHẤT — là `_cau_hinh_google()`
        (`modules/auth/router.py`), tức `/auth/google/start` và
        `/auth/google/callback` (`/auth/providers` không đi qua nó — xem docstring
        `_cau_hinh_google()`). KHÔNG phải `POST /auth/register`: đường đăng ký
        không dựng `redirect_uri` nào cả, nên nó không có gì để phép kiểm này bảo
        vệ. Từng nằm lẫn trong `kiem_tra_dang_ky_mau_thuan_san_xuat()` (chỉ chạy
        khi có ai POST `/auth/register`) nên một production bật Google mà không
        ai đăng ký sau khi deploy sẽ không bao giờ chạm phép kiểm này — người
        dùng Google đầu tiên nhận `redirect_uri_mismatch` mù mờ từ Google, đúng
        thứ phép kiểm này viết ra để chặn. Tách hàm này ra để nó chạy trên đúng
        cửa cần nó, thay vì ăn theo nhịp gọi của một đường không liên quan.

        `tests/unit/test_config_google.py::test_dang_ky_mau_thuan_san_xuat_khong_con_kiem_google`
        neo NGƯỢC lại: `kiem_tra_dang_ky_mau_thuan_san_xuat()` không còn ném vì
        thiếu cấu hình Google.
        """
        if self.environment == "production" and self.google_bat() and not self.public_base_url:
            raise RuntimeError(
                "GOOGLE_CLIENT_ID đã đặt ở production nhưng thiếu PUBLIC_BASE_URL — "
                "không dựng được redirect_uri. Đặt PUBLIC_BASE_URL, hoặc bỏ trống GOOGLE_CLIENT_ID."
            )

    def kiem_tra_dang_ky_mau_thuan_san_xuat(self) -> None:
        """Chặn tổ hợp SIGNUP_ENABLED bật + mailer chưa đủ cấu hình ở production.

        CÙNG KHUÔN `_kiem_token` (`core/auth/quan_tri_nen_tang.py`): kiểm LÚC GỌI,
        không phải lúc dựng `Settings()` — `Settings()` được dựng trong test và
        script với đủ loại cấu hình, một validator cứng ở `__init__`/model_validator
        làm mọi thứ không liên quan cũng vỡ (giống lý do `master_key_bytes()` ném
        lúc gọi chứ không lúc dựng). Người gọi thật là `POST /auth/register`
        (`modules/auth/router.py`), ngay cạnh phép kiểm `signup_enabled`.

        CHỈ kiểm mailer/đăng ký — phép kiểm Google tách riêng ở
        `kiem_tra_google_mau_thuan_san_xuat()`, gọi từ `_cau_hinh_google()`
        (đường Google không đi qua `/auth/register` nên không chạm hàm này).

        VÌ SAO CẦN: ở dev, mailer tắt (thiếu SMTP_HOST/SMTP_FROM/PUBLIC_BASE_URL)
        đã được `core/mailer.py` xử lý an toàn — in thư ra stdout thay vì gửi.
        Nhưng `signup_enabled` mặc định BẬT trong khi ba biến mailer mặc định
        RỖNG, nên một production quên cấu hình SMTP vẫn trả 201/200 "đã gửi thư"
        cho `POST /auth/register` — người dùng có tài khoản `pending`, không mật
        khẩu, không link nào tới tay họ (thư chỉ in ra log container mà không ai
        đọc), và đăng ký lại cũng im lặng y hệt. Ở dev việc này CHẤP NHẬN được
        (nhánh in-ra-stdout của mailer là đường cứu); ở production thì không có
        console nào để đọc lại thư đã "gửi", nên phải chặn TRƯỚC khi có ai gặp
        phải, không phải sau khi tài khoản đầu tiên đã kẹt.
        """
        if not (self.environment == "production" and self.signup_enabled):
            return
        thieu = [
            ten
            for ten, gia_tri in (
                ("SMTP_HOST", self.smtp_host),
                ("SMTP_FROM", self.smtp_from),
                ("PUBLIC_BASE_URL", self.public_base_url),
            )
            if not gia_tri
        ]
        if thieu:
            raise RuntimeError(
                f"SIGNUP_ENABLED=true ở production nhưng mailer chưa đủ cấu hình — "
                f"thiếu {', '.join(thieu)}. Đặt đủ các biến này, hoặc tắt SIGNUP_ENABLED."
            )

    # ─── Cookie phiên ────────────────────────────────────────────────────────

    cookie_secure: bool = True
    """Cờ Secure của cookie phiên. ĐỂ NGUYÊN True trừ khi biết chính xác vì sao tắt.

    Tắt CHỈ để mở portal từ máy khác trong LAN qua `http://<IP>:5273` ở dev, hoặc
    để dev trên Safari: Chrome/Firefox miễn trừ Secure-trên-http cho `localhost`,
    Safari/WebKit thì KHÔNG, và không trình duyệt nào miễn trừ cho IP thô — mà
    `http://<IP>:5273` chính là URL «Network» vite in ra lúc khởi động.

    ⚠️ TRIỆU CHỨNG THẬT KHÁC THỨ DÒNG NÀY TỪNG GHI, và khác theo hướng khó truy hơn
    nhiều. Bản cũ nói «mọi màn bật về /login». Không phải: `LoginForm` của FE gọi
    `queryClient.setQueryData(['session'], phien)` — nó nhồi phiên vào cache client
    từ THÂN response đăng nhập, không chờ `GET /me`. Nên khi cookie bị từ chối:

      · đăng nhập vẫn 200 và app render ĐẦY ĐỦ như đã đăng nhập (switcher, nav, tên
        người dùng — tất cả đọc từ cache);
      · request ĐỌC đầu tiên trong 30s (`staleTime`) không xảy ra, nên không có gì
        lộ ra;
      · rồi cú GHI đầu tiên (xoá workspace, đổi tên, mời thành viên…) đi ra KHÔNG
        MANG COOKIE và nhận **401 «Chưa đăng nhập hoặc phiên đã hết hạn»** — một
        thông điệp trỏ vào phiên, trong khi phiên trong Redis vẫn sống nguyên và
        TTL còn hàng giờ.

    Đã truy hết một vòng vì thế (2026-08-19): đọc Redis thấy 12 phiên khoẻ, curl
    thẳng và curl qua proxy vite đều 204, nên mọi ngờ vực dồn về phía server trong
    khi lỗi nằm ở chỗ cookie chưa bao giờ được LƯU. Dấu hiệu phân biệt nhanh nhất:
    phiên còn trong Redis + `require()` không thể 401 cho nó ⇒ request không mang
    cookie ⇒ kiểm URL trên thanh địa chỉ và trình duyệt TRƯỚC khi đọc thêm code.

    Tắt ở production = cookie phiên đi qua đường không mã hoá, và cũng không có
    triệu chứng nào: mọi thứ chạy bình thường, chỉ là nghe lén được. Vì thế
    default ở đây là True và `tests/unit/test_cookie_secure.py` neo nó lại.
    """

    @property
    def alembic_url(self) -> str:
        """DSN cho Alembic — suy từ `migrator_url`, KHÔNG phải `database_url`.

        Suy từ đây là chỗ duy nhất nối hai khái niệm "credential DDL" và "driver
        SQLAlchemy" lại, nên không ai phải nhớ đổi driver bằng tay lần thứ hai.
        """
        return to_alembic_url(self.migrator_url)


def get_settings() -> Settings:
    return Settings()
