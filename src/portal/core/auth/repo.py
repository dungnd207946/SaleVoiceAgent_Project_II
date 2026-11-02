"""Một truy vấn của seam xác thực — `doc_quyen`.

VÌ SAO Ở `core/` CHỨ KHÔNG Ở `modules/auth/`: `require()` sống ở core, và nếu
truy vấn nó cần nằm ở modules thì core phải import modules — ngược chiều phụ
thuộc. Chia theo AI CẦN, không theo bảng nào: hàm này trả lời "người này có
được vào workspace này không, và làm được gì", tức chính seam cách ly mà core
sở hữu (spec §2.3, cùng hạng với portal.current_tenant() và tenant_conn()).

Giá phải trả: đọc control.memberships/roles/role_actions nằm ở hai file (đây
và `modules/auth/repo.py`). Chấp nhận, vì đổi lại core không phụ thuộc modules
nào.

SQL nghiệp vụ còn lại của users/memberships ở `modules/auth/repo.py`.

M2a có `doc_lifecycle` + `doc_membership` — hai lượt riêng. M2b (đây) gộp thành
MỘT hàm: ma trận vai trò × hành động cần đọc thêm `roles`/`role_actions`, và
tách nó ra một lượt thứ ba là trả thêm một round-trip cho mỗi request có
`require()` — tức MỌI request.
"""

from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True, slots=True)
class HangQuyen:
    lifecycle: str
    """'active' | 'suspended' | 'pending' (migration 0100 · 0103)."""
    role_name: str | None
    """Tên vai trò trong workspace đang xét. None = không có membership."""
    actions: frozenset[str]
    """Tập hành động hiệu lực. Không membership: rỗng.

    ⚠ RỖNG KHÔNG NGHĨA "không phải thành viên" — một vai trò 0 quyền là trạng
    thái HỢP LỆ (spec §2.1: "đã tạo, chưa cấu hình"), và §3.3 buộc sửa vai trò
    không được khoá cửa. Câu "có phải thành viên không" là `co_membership`,
    KHÔNG PHẢI `bool(actions)` — xem nó, và xem `doi_workspace` ở
    `modules/auth/router.py` cho hệ quả cụ thể của việc lẫn hai câu hỏi này.
    """
    co_membership: bool
    """CÓ một hàng `memberships` còn hiệu lực cho (user, tenant) này — độc lập
    với `actions`. Đây là câu hỏi "có phải thành viên workspace này không", thứ
    `liet_ke_workspace` dùng để quyết định hiện workspace trên switcher; `actions`
    là câu hỏi KHÁC ("làm được gì").

    Từ 2026-08-15 hai câu hỏi đó luôn cùng nguồn (`memberships`), nên
    `co_membership=False` kéo theo `actions` rỗng. Trước đó KHÔNG: owner của tổ
    chức có đủ 13 action mà `co_membership=False`.
    """
    tenant_lifecycle: str | None
    """`control.tenants.lifecycle` của workspace đang xét. `None` = không có hàng.

    CÂU HỎI THỨ TƯ, và nó KHÔNG suy được từ ba câu trên: membership vẫn còn, vai
    trò vẫn còn, 13 action vẫn còn — chỉ workspace là đã bị xoá. `require()` đọc
    trường này để đáp 403 `WORKSPACE_DA_DONG`.

    Đi CHUNG truy vấn chứ không thêm một lượt: hàm này chạy ở MỌI request có
    `require(action)`, nên một round-trip nữa ở đây là một round-trip nữa cho cả
    portal. Một `LEFT JOIN` trên khoá chính thì không.

    `None` xảy ra khi phiên trỏ vào một workspace đã bị xoá CỨNG. `require()` xử
    nó như đã đóng — cùng một câu trả lời cho người dùng, và fail-closed là mặc
    định đúng khi mất thông tin.
    """


async def doc_quyen(conn: asyncpg.Connection, user_id: str, tenant_id: str) -> HangQuyen | None:
    """MỘT truy vấn cho cả ba câu hỏi: còn hoạt động? · có vào được? · làm được gì?

    None = user không tồn tại.

    THAY CHO `doc_lifecycle` + `doc_membership` — hai lượt trước đây. Ít hơn một
    round-trip dù làm nhiều việc hơn. Đi trong transaction mà ràng buộc cách ly
    đã bắt buộc phải có.

    ⚠ VỊ TỪ `expires_at` NẰM TRONG `ON`, KHÔNG PHẢI `WHERE`. Ở `WHERE` nó biến
    LEFT JOIN thành INNER JOIN âm thầm: user không có membership sẽ mất luôn
    hàng và hàm trả None — không phân biệt được với "user không tồn tại", tức một
    người chưa được thêm vào workspace nào sẽ nhận 401 thay vì 403.

    `expires_at IS NULL OR expires_at > now()` là chỗ BR-Q08 được cài: vé hỗ trợ
    của NobleX tự hết hiệu lực, không ai phải nhớ thu hồi.

    KHÔNG CÒN NHÁNH OWNER. Trước 2026-08-15, `org_role='owner'` + tenant cùng tổ
    chức ⇒ đủ 13 action ở MỌI workspace, không cần hàng memberships. Tầng tổ chức
    đã bị bỏ (spec 2026-08-15-bo-organization-design §4), nên quyền giờ CHỈ đến
    từ `memberships`: không có hàng thì không có action nào. Đó cũng là lý do
    `workspace.service.tao()` buộc phải ghi membership 'Quản trị' cho người tạo —
    thiếu nó, người vừa tạo workspace không vào được chính nó.
    """
    r = await conn.fetchrow(
        """SELECT u.lifecycle,
                  r.name AS role_name,
                  t.lifecycle AS tenant_lifecycle,
                  bool_or(m.user_id IS NOT NULL) AS co_membership,
                  coalesce(
                    array_agg(ra.action_code) FILTER (WHERE ra.action_code IS NOT NULL),
                    '{}'
                  ) AS actions
             FROM control.users u
             LEFT JOIN control.memberships m
                    ON m.user_id = u.id
                   AND m.tenant_id = $2
                   AND (m.expires_at IS NULL OR m.expires_at > now())
             LEFT JOIN control.roles r         ON r.id = m.role_id
             LEFT JOIN control.role_actions ra ON ra.role_id = m.role_id
             LEFT JOIN control.tenants t       ON t.id = $2
            WHERE u.id = $1
            GROUP BY u.lifecycle, r.name, t.lifecycle""",
        user_id,
        tenant_id,
    )
    if r is None:
        return None
    return HangQuyen(
        r["lifecycle"],
        r["role_name"],
        frozenset(r["actions"]),
        r["co_membership"],
        r["tenant_lifecycle"],
    )
