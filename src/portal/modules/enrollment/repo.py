"""SQL thô trên control.agent_keys · agent_credentials.

KHÔNG dùng `tenant_conn()`: cả ba bảng ở schema `control`, không có RLS, và admin
nền tảng đọc xuyên tenant. Cùng lý do đã ghi ở modules/config/repo.py:6.

Hệ quả phải nhớ: ở đây KHÔNG có RLS đỡ phía sau. Lấy sai `tenant_id` là đọc/ghi
credential của workspace khác, và không có lỗi nào.
"""

import asyncpg

from portal.core import bi_mat_luu
from portal.modules.enrollment.contracts import KhoaHopLe

Conn = asyncpg.Connection | asyncpg.Pool


async def liet_ke_tenant_van_hanh(conn: Conn) -> list[dict]:
    """Xuyên tenant — admin nền tảng xem tình trạng vận hành là quyền control plane,
    không phải quyền đọc dữ liệu tenant. Cùng lập luận với policy `hb_portal_all` của
    migration 0007.

    NGUỒN HÀNG ĐỔI Ở `0941`: trước là `control.deployments` (một hàng mỗi pod), giờ là
    `control.tenants` (một hàng mỗi workspace). Bảng kia đã bỏ, và nó chưa bao giờ mang
    thông tin nào mà bảng này không có.

    LEFT JOIN chứ không INNER: workspace chưa cấp phát khoá nào vẫn phải hiện trong bảng
    admin với `so_khoa_con_song = 0`. Ẩn nó đi là làm "chưa cấp phát" trông giống "không
    tồn tại" — đúng câu hỏi người ta mở màn này ra để trả lời.
    """
    rows = await conn.fetch(
        """
        SELECT t.id AS tenant_id, t.name, t.lifecycle,
               count(k.id) FILTER (WHERE k.revoked_at IS NULL) AS so_khoa_con_song
          FROM control.tenants t
          LEFT JOIN control.agent_keys k ON k.tenant_id = t.id
         GROUP BY t.id
         ORDER BY t.id
        """
    )
    return [dict(r) for r in rows]


async def tenant_da_co_khoa(conn: Conn, tenant_id: str) -> bool:
    """Tenant này đã đi qua `cap_phat` chưa. Thay `deployment_cua_tenant` (bỏ ở
    `0940`) làm tín hiệu cho đường owner workspace tự phát khoá chọn giữa
    `cap_phat` (áp hạ tầng + phát khoá) và `_phat_khoa` (chỉ thêm hàng khoá).

    VÌ SAO ĐẾM KHOÁ CHỨ KHÔNG ĐẾM `agent_credentials`: `doc_version()` tạo hàng
    `agent_credentials` NGAY LÚC ĐỌC (INSERT ... ON CONFLICT), nên sự tồn tại của
    hàng đó không phân biệt được "đã cấp phát" với "vừa có ai gọi
    /runtime-credentials". Khoá thì không bao giờ bị DELETE — chỉ đặt `revoked_at`
    — nên đây là dấu vết BỀN của "tenant này đã được cấp phát".

    KHÔNG lọc `revoked_at IS NULL`: tenant thu hồi hết khoá vẫn là tenant đã cấp
    phát. Lọc vào đây là bắt hạ tầng chạy lại mỗi lần workspace tắt khoá cuối.
    """
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM control.agent_keys WHERE tenant_id = $1)",
        tenant_id,
    )


async def liet_ke_khoa_cua_tenant(conn: Conn, tenant_id: str) -> list[dict]:
    """MỌI khoá của tenant — kể cả đã tắt — mới nhất trước.

    KHÔNG lọc `revoked_at IS NULL` (khác trước `0920`): màn hình owner cần thấy
    khoá đã tắt (`status: "inactive"`) để bật lại được — "biến mất" và "tắt" là
    hai tín hiệu khác nhau cho gateway lẫn người vận hành. Lọc theo trạng thái
    "dùng được" vẫn còn, chỉ chuyển sang `tra_khoa()` — chỗ THỰC SỰ cần nó.

    KHÔNG trả `key_sha256`: nó là băm của bí mật, không dùng để hiển thị được.
    CÓ trả `api_key` (từ `0918`) — khoá THÔ, `NULL` cho hàng tạo trước migration
    đó. FE `/thu-agent` cần giá trị thật để dựng `<select>` chọn theo tên mà vẫn
    nối WS được; đường xác thực (`tra_khoa`, `cham_last_used`) vẫn tra theo
    `key_sha256` như cũ, cột này không thay thế gì ở đó.
    """
    rows = await conn.fetch(
        """
        SELECT k.id, k.api_key, k.key_prefix, k.label, k.created_at, k.last_used_at,
               k.revoked_at,
               (CASE WHEN k.revoked_at IS NULL THEN 'active' ELSE 'inactive' END) AS status
          FROM control.agent_keys k
         WHERE k.tenant_id = $1
         ORDER BY k.created_at DESC, k.id DESC
        """,
        tenant_id,
    )
    # GIẢI MÃ ở tầng repo — chỗ duy nhất chạm SQL. `api_key` NULL (hàng trước
    # `0918`) và chuỗi thô chưa backfill đều đi qua nguyên vẹn; xem `bi_mat_luu`.
    return [{**dict(r), "api_key": bi_mat_luu.giai_ma(r["api_key"])} for r in rows]


async def tra_khoa(conn: Conn, sha: str) -> KhoaHopLe | None:
    """Tra khoá theo băm. Khoá ĐÃ THU HỒI trả về None.

    Lọc `revoked_at IS NULL` NGAY TRONG SQL chứ không trả cờ cho service kiểm:
    một chỗ quên kiểm cờ là một khoá đã thu hồi vẫn dùng được, và lỗi đó im lặng.
    """
    r = await conn.fetchrow(
        """
        SELECT k.id, k.tenant_id
          FROM control.agent_keys k
         WHERE k.key_sha256 = $1 AND k.revoked_at IS NULL
        """,
        sha,
    )
    return KhoaHopLe(r["tenant_id"], r["id"]) if r else None


async def them_khoa(conn: Conn, tenant_id: str, sha: str, api_key: str, prefix: str, label: str, boi: str) -> int:
    """`sha` vẫn là cột xác thực (`key_sha256`, không đổi). `api_key` là khoá THÔ
    — thêm từ `0918` để phục vụ đúng một việc: liệt kê lại được cho `<select>`
    của `/thu-agent`, KHÔNG dùng để xác thực."""
    return await conn.fetchval(
        """
        INSERT INTO control.agent_keys (tenant_id, key_sha256, api_key, key_prefix, label, created_by)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
        """,
        tenant_id,
        sha,
        bi_mat_luu.ma_hoa(api_key),
        prefix,
        label,
        boi,
    )


async def thu_hoi_khoa(conn: Conn, key_id: int) -> bool:
    """True nếu VỪA thu hồi. False nếu không có hàng, hoặc đã thu hồi từ trước.

    `revoked_at IS NULL` trong WHERE làm thao tác idempotent mà vẫn phân biệt
    được hai trường hợp — admin bấm hai lần không nên thấy lỗi, nhưng nhật ký
    cũng không nên có hai dòng.
    """
    ra = await conn.execute(
        "UPDATE control.agent_keys SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
        key_id,
    )
    return ra.endswith(" 1")


async def dat_trang_thai_khoa(conn: Conn, key_id: int, active: bool) -> dict | None:
    """Đặt/gỡ `revoked_at` — MỘT câu SQL cho cả hai chiều, cùng lý lẽ `datTrangThaiKhoa`
    phía FE (`api.ts`): trạng thái là một giá trị, không phải hai hành động.

    Dùng cho đường owner workspace (`router_tenant.py`) — KHÁC `thu_hoi_khoa`
    phía trên (đường admin nền tảng, chỉ một chiều, idempotent im lặng). Ở đây
    không cần WHERE `revoked_at IS NULL` để idempotent: đặt lại đúng trạng thái
    đang có là vô hại, và người gọi (service) cần hàng trả về để trả `KhoaOut`
    dù có đổi gì hay không.

    `None` nếu không có hàng khớp `id` — người gọi chịu trách nhiệm phân biệt
    "không tồn tại" với "thuộc tenant khác" TRƯỚC khi gọi hàm này.
    """
    r = await conn.fetchrow(
        """
        UPDATE control.agent_keys
           SET revoked_at = CASE WHEN $2 THEN NULL ELSE now() END
         WHERE id = $1
        RETURNING id, api_key, key_prefix, label, created_at, last_used_at, revoked_at,
                  (CASE WHEN revoked_at IS NULL THEN 'active' ELSE 'inactive' END) AS status
        """,
        key_id,
        active,
    )
    return {**dict(r), "api_key": bi_mat_luu.giai_ma(r["api_key"])} if r else None


async def tenant_cua_khoa(conn: Conn, key_id: int) -> str | None:
    return await conn.fetchval(
        "SELECT tenant_id FROM control.agent_keys WHERE id = $1",
        key_id,
    )


async def tenant_va_nhan_cua_khoa(conn: Conn, key_id: int) -> tuple[str, str] | None:
    """Cho đường xoay khoá — cần cả `tenant_id` (kiểm sở hữu) lẫn `label` (khoá
    mới giữ nguyên nhãn khoá cũ) trong một round trip thay vì hai."""
    r = await conn.fetchrow(
        "SELECT tenant_id, label FROM control.agent_keys WHERE id = $1",
        key_id,
    )
    return (r["tenant_id"], r["label"]) if r else None


async def cham_last_used(conn: Conn, sha: str) -> None:
    await conn.execute("UPDATE control.agent_keys SET last_used_at = now() WHERE key_sha256 = $1", sha)


async def doc_version(conn: Conn, tenant_id: str) -> int:
    """Đọc secret_version; tạo hàng mặc định 1 nếu tenant chưa từng cấp phát.

    Tạo-nếu-thiếu ở đây chứ không bắt caller nhớ: mọi đường đọc version đều cần
    một hàng tồn tại, và quên tạo là `/runtime-credentials` ném lỗi trên một tenant hợp lệ.
    """
    return await conn.fetchval(
        """
        INSERT INTO control.agent_credentials (tenant_id) VALUES ($1)
        ON CONFLICT (tenant_id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id
        RETURNING secret_version
        """,
        tenant_id,
    )


async def tang_version(conn: Conn, tenant_id: str, boi: str) -> int:
    return await conn.fetchval(
        """
        INSERT INTO control.agent_credentials (tenant_id, secret_version, rotated_by)
        VALUES ($1, 2, $2)
        ON CONFLICT (tenant_id) DO UPDATE
            SET secret_version = control.agent_credentials.secret_version + 1,
                rotated_at = now(), rotated_by = EXCLUDED.rotated_by
        RETURNING secret_version
        """,
        tenant_id,
        boi,
    )


async def lifecycle_tenant(conn: Conn, tenant_id: str) -> str | None:
    """Cột là `lifecycle` (ý chí người vận hành), KHÔNG phải `status`.
    `status` là thứ suy ra từ lifecycle + heartbeat, không lưu."""
    return await conn.fetchval("SELECT lifecycle FROM control.tenants WHERE id = $1", tenant_id)
