"""Truy vấn của module workspace. CALLER quyết định giao dịch — khuôn `repo.py` chung.

BA BẢNG MODULE NÀY GHI: `control.tenants` · `control.tenant_verticals` ·
`control.audit_log` (qua `core/nhat_ky.py`).

`tenant_verticals` có NGƯỜI GHI THỨ HAI từ 2026-08-21: `modules/linh_vuc`
(công tắc màn /domains) INSERT/DELETE hàng theo thao tác người dùng — hàng
mà `them_vertical` ghi lúc tạo workspace có thể biến mất sau đó, đừng coi
«tạo xong là luôn có hàng realestate» là bất biến.

MỘT BẢNG NÓ CHỈ ĐỌC: `control.users` — để biết actor là ai và thuộc org nào.
Đọc bảng của module khác là được; cổng `test_module_boundaries.py` chặn **import
ruột module khác**, không chặn một câu SELECT. Cố ý KHÔNG import
`portal.modules.auth.repo.tim_user_theo_id` dù nó làm gần đúng việc này: import đó
là vi phạm cổng, và nó trả về cả hàng `users` (password_hash, lifecycle, …) trong
khi ở đây chỉ cần ba cột.

KHÔNG ghi `control.memberships`. Xem docstring `service.tao`.
"""

from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True, slots=True)
class HangActor:
    """Người đang thao tác. Chỉ còn `id`: `org_id`/`org_role` đã bỏ 2026-08-15.

    Giữ dataclass thay vì trả `str` trần để chỗ gọi không phải đổi hình dạng khi
    cần thêm cột — và để `None` (user vừa bị xoá) vẫn phân biệt được với id rỗng.
    """

    id: str


@dataclass(frozen=True, slots=True)
class HangTenant:
    id: str
    name: str
    lifecycle: str
    created_at: datetime
    created_by: str
    """AI TẠO ra workspace này — KHÔNG phải ai đang thao tác trên nó.

    `service.sua()` tra trùng tên theo cột này, vì UNIQUE INDEX
    `tenants_nguoi_tao_ten_key` (0106) đặt trên `(created_by, lower(btrim(name)))`.
    Một Quản trị được MỜI vào workspace của người khác có `actor_id != created_by`,
    và tra theo actor ở đó là tra nhầm vế: câu tra nói "không trùng", `UPDATE` nổ
    ra `UniqueViolation`, và người dùng nhận 500 thay vì 409 có thông điệp.
    """


async def tim_actor(conn: asyncpg.Connection, user_id: str) -> HangActor | None:
    r = await conn.fetchrow("SELECT id FROM control.users WHERE id = $1", user_id)
    return None if r is None else HangActor(r["id"])


async def ten_da_dung(conn: asyncpg.Connection, created_by: str, ten: str, tru_id: str | None = None) -> bool:
    """Trùng tên trong phạm vi MỘT NGƯỜI TẠO, so sánh đã chuẩn hoá.

    PHẠM VI ĐỔI TỪ TỔ CHỨC SANG NGƯỜI TẠO (2026-08-15): ai cũng tạo được
    workspace, nên hai người lạ đặt tên "Test" là chuyện bình thường và một ràng
    buộc toàn cục sẽ 409 vào mặt người thứ hai mà không giải thích được.

    `lower(btrim(...))` cả hai vế: với người dùng thì "Sàn A", "sàn a" và "Sàn A "
    là một cái tên, và hai workspace chỉ khác nhau ở chữ hoa là hai dòng không ai
    phân biệt được trong switcher.

    CỬA SỔ ĐUA ĐÃ ĐÓNG: migration 0106 dựng UNIQUE INDEX
    `tenants_nguoi_tao_ten_key` trên ĐÚNG biểu thức này. Hàm này giờ chỉ còn để
    trả 409 có thông điệp đẹp thay vì để INSERT nổ ra 500 — không còn là tuyến
    phòng thủ duy nhất như bản trước.

    `tru_id` LOẠI MỘT HÀNG khỏi phép so — đường đổi tên truyền id của chính
    workspace đang sửa. Thiếu nó thì "Lưu" mà không đổi chữ nào sẽ trả 409: hàng
    tự đụng chính nó. Người dùng bấm Lưu hai lần là chuyện bình thường, và lần thứ
    hai báo lỗi thì họ đi tìm một xung đột không tồn tại.
    """
    return await conn.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM control.tenants
              WHERE created_by = $1 AND lower(btrim(name)) = lower(btrim($2))
                AND ($3::text IS NULL OR id <> $3)
           )""",
        created_by,
        ten,
        tru_id,
    )


async def id_da_dung(conn: asyncpg.Connection, tenant_id: str) -> bool:
    """Tra TOÀN CỤC: `tenants.id` là PRIMARY KEY, và nó còn là tên role Postgres
    `agent_<id>` — hai người tạo khác nhau không được ra cùng một id."""
    return await conn.fetchval("SELECT EXISTS (SELECT 1 FROM control.tenants WHERE id = $1)", tenant_id)


async def them_tenant(conn: asyncpg.Connection, tenant_id: str, ten: str, created_by: str) -> HangTenant:
    """`RETURNING` chứ không SELECT lại: `lifecycle` và `created_at` do DB đặt
    (DEFAULT 'active' / now()), và đọc lại bằng một câu thứ hai là mở một cửa sổ
    để giá trị trả về không phải giá trị vừa ghi."""
    r = await conn.fetchrow(
        """INSERT INTO control.tenants (id, name, created_by)
                VALUES ($1, $2, $3)
             RETURNING id, name, lifecycle, created_at, created_by""",
        tenant_id,
        ten,
        created_by,
    )
    return _hang(r)


async def id_vai_tro_quan_tri(conn: asyncpg.Connection) -> str:
    """Id của vai trò "Quản trị" — tra theo TÊN, không suy bằng md5.

    Cùng lý lẽ 0104 đã ghi: một vai trò mẫu bị xoá qua API rồi tạo lại nhận id
    `uuid4()`, không phải `md5(...)`. Tra theo tên luôn trúng hàng THẬT đang tồn
    tại, bất kể id của nó sinh ra từ đâu.

    KHÔNG tìm thấy ⇒ nổ, không phải tạo workspace không membership: một workspace
    mà chính người tạo không vào được là trạng thái hỏng câm. Cờ
    `ROLES_CRUD_ENABLED=false` làm tình huống này không xảy ra được từ UI, nhưng
    một `DELETE` thẳng vào DB thì có.
    """
    rid = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
    if rid is None:
        raise RuntimeError(
            "không tìm thấy vai trò 'Quản trị' trong control.roles — seed vai trò "
            "đã bị xoá? Xem migration 0104 (seed) và 0105 (dedup)."
        )
    return rid


async def them_membership(conn: asyncpg.Connection, user_id: str, tenant_id: str, role_id: str) -> None:
    """Người tạo workspace trở thành thành viên của chính nó.

    Bắt buộc từ 2026-08-15: `core/auth/repo.doc_quyen()` đã bỏ nhánh owner, nên
    không có hàng này thì người vừa tạo workspace không có action nào ở đó.
    """
    await conn.execute(
        "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)",
        user_id,
        tenant_id,
        role_id,
    )


async def them_vertical(conn: asyncpg.Connection, tenant_id: str, vertical: str) -> None:
    """`control.tenant_verticals` — lĩnh vực đang bật của workspace.

    Trước bản này KHÔNG dòng code nào ghi bảng đó: nó có từ 0002 và được khai *cố
    ý* trong danh sách đóng `CONTROL_TABLES_DUOC_MANG_TENANT_ID` của
    `tests/isolation/test_isolation_catalog.py` với lý do "Portal đọc để dựng UI",
    nhưng luôn rỗng. Một bảng được khai là cố ý mà vĩnh viễn rỗng là tệ hơn cả
    việc xoá nó — nên đường tạo workspace ghi nó, và từ giờ nó là câu trả lời
    cấp-dữ liệu cho "workspace này lĩnh vực gì" TRƯỚC khi có config draft đầu tiên.
    Từ 2026-08-21 bảng còn một người ghi nữa — `modules/linh_vuc` (bật/tắt từ màn
    /domains), nên hàng này là TRẠNG THÁI ĐẦU, không phải bất biến.
    """
    await conn.execute(
        "INSERT INTO control.tenant_verticals (tenant_id, vertical) VALUES ($1, $2)",
        tenant_id,
        vertical,
    )


def _hang(r: asyncpg.Record) -> HangTenant:
    """Một chỗ dựng `HangTenant`, bốn câu SQL dùng.

    Dựng bằng vị trí ở mỗi chỗ gọi là cách chắc chắn để một cột thêm vào sau này
    lệch thứ tự ở đúng một trong bốn — và `id`/`name`/`created_by` đều là `text`,
    nên hoán vị hai cái bất kỳ KHÔNG nổ, nó chỉ trả sai.
    """
    return HangTenant(r["id"], r["name"], r["lifecycle"], r["created_at"], r["created_by"])


async def doc_tenant(conn: asyncpg.Connection, tenant_id: str) -> HangTenant | None:
    """Đọc một workspace. `None` = không tồn tại.

    KHÔNG lọc `lifecycle`: chỗ gọi cần phân biệt "không có" với "đã đóng", và một
    câu SELECT đã lọc sẵn thì gộp hai thứ đó thành `None`.
    """
    r = await conn.fetchrow(
        "SELECT id, name, lifecycle, created_at, created_by FROM control.tenants WHERE id = $1",
        tenant_id,
    )
    return None if r is None else _hang(r)


async def doi_ten(conn: asyncpg.Connection, tenant_id: str, ten: str) -> HangTenant:
    """Đổi ĐÚNG cột `name`. `id` không nằm trong câu `SET` — xem `SuaWorkspaceIn`."""
    r = await conn.fetchrow(
        """UPDATE control.tenants SET name = $2
            WHERE id = $1
        RETURNING id, name, lifecycle, created_at, created_by""",
        tenant_id,
        ten,
    )
    return _hang(r)


async def xoa_han(conn: asyncpg.Connection, tenant_id: str) -> bool:
    """XOÁ CỨNG một workspace. Trả `False` nếu hàng đã không còn.

    MỘT CÂU LỆNH, và nó cuốn theo 17 bảng `tenant_data` cộng ~14 bảng `control`: mọi
    bảng mang `tenant_id` đều khai `REFERENCES control.tenants(id) ON DELETE CASCADE`
    (đã đối chiếu toàn bộ `migrations/versions/`). Đừng thay bằng một danh sách
    `DELETE` chép tay ở tầng app — danh sách đó sẽ thiếu bảng mà module sau thêm vào,
    và thiếu âm thầm.

    ⚠️ BA THỨ CASCADE KHÔNG VỚI TỚI, vì chúng không ở trong Postgres:
    collection Qdrant `<id>_documents`/`<id>_media` · tiền tố `tenants/<id>/` trên
    kho tệp · role Postgres `agent_<id>` (là đối tượng cấp cluster, không phải hàng).
    Xem `service.don_ha_tang_ngoai`.

    ⚠️ NÓ CŨNG XOÁ NHẬT KÝ CỦA CHÍNH WORKSPACE: `control.audit_log.tenant_id` là FK
    cascade. Nên dòng ghi lại việc xoá phải là `nhat_ky.ghi_he_thong()`
    (`tenant_id IS NULL`), không phải `ghi()` — xem `service.xoa`.

    `RETURNING` chứ không `rowcount`: hai request xoá song song thì đúng một cái trả
    `True`, và chỉ cái đó ghi nhật ký.
    """
    return await conn.fetchval("DELETE FROM control.tenants WHERE id = $1 RETURNING id", tenant_id) is not None


async def workspace_dau_tien_con_lai(conn: asyncpg.Connection, user_id: str, tru_id: str) -> str | None:
    """Workspace user CÒN THẤY ĐƯỢC nếu `tru_id` biến mất — `None` = không còn cái nào.

    MỘT câu trả lời cho HAI câu hỏi của đường xoá: "có được xoá không" (`None` ⇒
    409, xem `loi.workspace_cuoi_cung`) và "chuyển phiên sang cái nào". Tách làm
    hai truy vấn là hai vị từ phải giữ đồng bộ, và lệch một vế thì phép kiểm nói
    còn workspace trong khi phép chọn không tìm ra cái nào.

    ⚠ PHẢI khớp định nghĩa "thấy được" của `modules/auth/repo.liet_ke_workspace`:
    membership còn hiệu lực VÀ workspace chưa đóng. Lệch thì hàm này đếm ra 1 trong
    khi switcher hiện 0 — và người dùng xoá được workspace cuối cùng qua đúng cái
    cửa dựng ra để chặn điều đó.

    `ORDER BY t.name` cũng lấy từ đó: phiên nhảy sang ĐÚNG mục đầu tiên của
    switcher, không phải một workspace ngẫu nhiên theo thứ tự vật lý của bảng.

    Hai file vì cổng ranh giới module cấm import ruột module khác; đọc bảng của
    module khác bằng một câu SELECT thì được (xem đầu file).
    """
    return await conn.fetchval(
        """SELECT t.id FROM control.memberships m
             JOIN control.tenants t ON t.id = m.tenant_id
            WHERE m.user_id = $1
              AND m.tenant_id <> $2
              AND (m.expires_at IS NULL OR m.expires_at > now())
              AND t.lifecycle <> 'closed'
         ORDER BY t.name
            LIMIT 1""",
        user_id,
        tru_id,
    )
