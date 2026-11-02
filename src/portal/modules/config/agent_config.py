"""`tenant_data.agent_config` — NGUỒN SỰ THẬT DUY NHẤT của cấu hình agent (từ `0966`).

Agent (chế độ `AGENT_CONFIG_SOURCE=db`) đọc đúng bảng này. Từ `0966` Portal cũng chỉ còn
bảng này: bản nháp (`config_drafts`), lịch sử version (`config_versions`) và con trỏ
(`config_live`) đã DROP. Bấm Lưu = ghi thẳng ở đây = agent thấy ở hội thoại kế tiếp.

BA LUẬT CỦA FILE NÀY:

  1. MỖI ROLE MỘT HÀNG — role là hàng của `tenant_data.role_config` (`0967`, FK
     `(tenant_id, role)`), UPSERT theo `(tenant_id, role)`. Một lần Lưu ghi MỌI hàng trong
     cùng giao dịch (`service.luu_cau_hinh`), nên không có trạng thái "role này đã lưu, role
     kia lỗi". Role chưa lưu lần nào thì KHÔNG có hàng (`GET /config` trả bộ mặc định).
  2. `version` TĂNG MỖI LẦN LƯU (và mỗi lần thêm/đổi tên/xoá role) và mọi hàng của một
     tenant mang CÙNG một số. Nó không còn
     là "phiên bản" để quay lui — nó là bộ đếm để agent biết phải dựng lại runner (agent
     cache theo `(tenant, version)`). Không tăng thì hội thoại mới vẫn chạy cấu hình cũ.
  3. Bảng BẬT RLS + FORCE (`0956`) — mọi câu phải chạy trong `tenant_conn()`. Câu đọc vẫn
     mang HAI vị từ: `tenant_id = $1` (tham số từ `Principal`) VÀ `= portal.current_tenant()`
     — lệch nhau thì ra 0 hàng thay vì hàng của tenant khác, và cổng
     `tests/isolation/test_loc_tenant_o_tang_app.py` đòi đúng vị từ thứ hai.

Hàng phẳng ↔ `ConfigPayload`: `hang_phang()` đi một chiều, `tu_hang_phang()` đi chiều
ngược lại. ⚠️ Chiều ngược có MỘT chỗ mất mát đã biết: `tts_normalization` lưu dạng jsonb
OBJECT (agent đọc nó thế), và jsonb KHÔNG giữ thứ tự khoá — đọc ra thứ tự có thể khác
thứ tự người dùng nhập. Nội dung thì đủ.
"""

import json
from dataclasses import dataclass

import asyncpg

from portal.modules.config.contracts import ConfigPayload

# Thứ tự cột khớp thứ tự tham số $1..$16. Viết thẳng, không sinh bằng vòng lặp: lệch tham
# số ở câu viết tay là lỗi lúc ĐỌC, ở câu sinh động là lỗi lúc CHẠY.
_SQL_LUU = """
INSERT INTO tenant_data.agent_config (
    tenant_id, role, name, brand_name, self_pronoun, customer_pronoun, greeting,
    scope_does, scope_does_not, refusal_line, departments,
    tone, reply_length, skills, version, tts_normalization
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14::jsonb, $15, $16::jsonb)
ON CONFLICT (tenant_id, role) DO UPDATE SET
    name              = excluded.name,
    brand_name        = excluded.brand_name,
    self_pronoun      = excluded.self_pronoun,
    customer_pronoun  = excluded.customer_pronoun,
    greeting          = excluded.greeting,
    scope_does        = excluded.scope_does,
    scope_does_not    = excluded.scope_does_not,
    refusal_line      = excluded.refusal_line,
    departments       = excluded.departments,
    tone              = excluded.tone,
    reply_length      = excluded.reply_length,
    skills            = excluded.skills,
    version           = excluded.version,
    tts_normalization = excluded.tts_normalization,
    updated_at        = now()
"""
# `created_at` và `id` KHÔNG có trong SET: lần đầu tenant cấu hình, và một id bền cho hàng.

# Mọi cột dữ liệu của hàng phẳng, trừ `id`/`tenant_id`/`role`/`created_at`/`updated_at` —
# thứ `chep_hang()` chép sang role mới.
_COT_DU_LIEU = (
    "name, brand_name, self_pronoun, customer_pronoun, greeting, "
    "scope_does, scope_does_not, refusal_line, departments, "
    "tone, reply_length, skills, version, tts_normalization"
)

_SQL_DOC = """
SELECT role, name, brand_name, self_pronoun, customer_pronoun, greeting,
       scope_does, scope_does_not, refusal_line, departments,
       tone, reply_length, skills, tts_normalization, version
  FROM tenant_data.agent_config
 WHERE tenant_id = $1 AND tenant_id = portal.current_tenant()
"""


@dataclass(frozen=True)
class HangDaLuu:
    """Một hàng đã lưu, đã dịch ngược về hình dạng payload (CHƯA validate)."""

    role: str
    payload: dict
    version: int


def hang_phang(cfg: ConfigPayload, version: int) -> dict:
    """`ConfigPayload` (lồng, tiếng Việt) -> một hàng phẳng (cột tiếng Anh).

    Tách khỏi `luu()` để kiểm được phép ánh xạ mà không cần Postgres: sai một cột ở đây là
    kiểu lỗi ghi đúng dữ liệu vào sai chỗ, và nó không làm câu SQL nào đỏ.

    `skills` giữ ĐÚNG thứ tự người dùng bật trong `tools.enabled`, không sort: thứ tự đó là
    dữ liệu người dùng nhập.
    """
    return {
        "name": cfg.danh_tinh.ten_agent,
        "brand_name": cfg.danh_tinh.ten_thuong_hieu,
        "self_pronoun": cfg.danh_tinh.tu_xung,
        "customer_pronoun": cfg.danh_tinh.goi_khach,
        "greeting": cfg.danh_tinh.loi_chao,
        "scope_does": cfg.pham_vi.lam_gi,
        "scope_does_not": cfg.pham_vi.khong_lam_gi,
        "refusal_line": cfg.pham_vi.cau_tu_choi,
        # Giữ nguyên khoá tiếng Việt `ten`/`khi_nao` — trùng đúng hình dạng `pham_vi.phong_ban`.
        "departments": [{"ten": pb.ten, "khi_nao": pb.khi_nao} for pb in cfg.pham_vi.phong_ban],
        "tone": cfg.giong.giong_dieu,
        "reply_length": cfg.giong.do_dai,
        "skills": list(cfg.tools.enabled),
        # DANH SÁCH -> OBJECT (hình dạng agent đọc). Trùng khoá đã bị `ConfigPayload` chặn.
        "tts_normalization": {e.term: e.read_as for e in cfg.tts_normalization},
        "version": version,
    }


def _json(v):
    """asyncpg trả jsonb dạng chuỗi theo mặc định."""
    return json.loads(v) if isinstance(v, (str, bytes)) else v


def tu_hang_phang(r, schema_version: int) -> dict:
    """Hàng phẳng -> payload dict (hình dạng `ConfigPayload`). CHƯA validate.

    Trả dict chứ không `ConfigPayload`: hàng đã lưu có thể không còn hợp lệ với sổ hôm nay
    (vd tên kỹ năng đã gỡ — sự cố `aina_test` 2026-09-10). Validate là việc của caller,
    để nó chọn được giữa 409 và 500.

    `schema_version` do caller truyền: bảng phẳng không lưu nó, và hàng nào đọc được bằng
    ánh xạ này thì theo định nghĩa đang ở hình dạng hiện hành.
    """
    return {
        "schema_version": schema_version,
        "danh_tinh": {
            "ten_agent": r["name"],
            "ten_thuong_hieu": r["brand_name"],
            "tu_xung": r["self_pronoun"],
            "goi_khach": r["customer_pronoun"],
            "loi_chao": r["greeting"],
        },
        "pham_vi": {
            "lam_gi": r["scope_does"],
            "khong_lam_gi": r["scope_does_not"],
            "phong_ban": _json(r["departments"]) or [],
            "cau_tu_choi": r["refusal_line"],
        },
        "giong": {"giong_dieu": r["tone"], "do_dai": r["reply_length"]},
        "tools": {"enabled": _json(r["skills"]) or []},
        "tts_normalization": [
            {"term": term, "read_as": read_as} for term, read_as in (_json(r["tts_normalization"]) or {}).items()
        ],
    }


async def doc(conn: asyncpg.Connection, tenant_id: str, schema_version: int) -> dict[str, HangDaLuu]:
    """Các hàng đã lưu của tenant, theo role. Role chưa có hàng thì vắng khỏi dict."""
    rows = await conn.fetch(_SQL_DOC, tenant_id)
    return {
        r["role"]: HangDaLuu(role=r["role"], payload=tu_hang_phang(r, schema_version), version=r["version"])
        for r in rows
    }


async def version_tiep_theo(conn: asyncpg.Connection, tenant_id: str) -> int:
    """`MAX(version) + 1` của tenant — gọi SAU khoá tư vấn theo tenant (`service.luu_cau_hinh`).

    Đọc-rồi-ghi: hai lần Lưu song song không khoá sẽ tính ra cùng một số, và agent
    thấy "không có gì đổi" cho lần thứ hai.
    """
    return await conn.fetchval(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM tenant_data.agent_config"
        " WHERE tenant_id = $1 AND tenant_id = portal.current_tenant()",
        tenant_id,
    )


async def luu(conn: asyncpg.Connection, tenant_id: str, role: str, cfg: ConfigPayload, version: int) -> None:
    """UPSERT hàng của `(tenant_id, role)`. Role phải có trong `role_config` (FK — caller
    đã đối chiếu tập role trước, nên vi phạm ở đây là lỗi lập trình, không phải 409)."""
    h = hang_phang(cfg, version)
    await conn.execute(
        _SQL_LUU,
        tenant_id,
        role,
        h["name"],
        h["brand_name"],
        h["self_pronoun"],
        h["customer_pronoun"],
        h["greeting"],
        h["scope_does"],
        h["scope_does_not"],
        h["refusal_line"],
        json.dumps(h["departments"], ensure_ascii=False),
        h["tone"],
        h["reply_length"],
        json.dumps(h["skills"], ensure_ascii=False),
        h["version"],
        json.dumps(h["tts_normalization"], ensure_ascii=False),
    )


async def chep_hang(conn: asyncpg.Connection, tenant_id: str, tu_role: str, sang_role: str) -> bool:
    """Chép hàng cấu hình của `tu_role` sang `sang_role` (role vừa tạo). False = nguồn chưa
    từng lưu — role mới khi đó cũng không có hàng, tức dùng bộ mặc định như nguồn."""
    kq = await conn.execute(
        f"""INSERT INTO tenant_data.agent_config (tenant_id, role, {_COT_DU_LIEU})
            SELECT tenant_id, $3, {_COT_DU_LIEU}
              FROM tenant_data.agent_config
             WHERE tenant_id = $1 AND tenant_id = portal.current_tenant() AND role = $2""",
        tenant_id,
        tu_role,
        sang_role,
    )
    return kq.endswith(" 1")


async def tang_version(conn: asyncpg.Connection, tenant_id: str) -> int | None:
    """Đưa MỌI hàng của tenant lên cùng một số mới — dùng khi tập role đổi (thêm/đổi tên/
    xoá) mà không có lần Lưu nào: agent cache theo `(tenant, version)`, số không đổi thì nó
    không biết danh sách role đã khác. None = tenant chưa có hàng nào (không có gì để báo)."""
    moi = await version_tiep_theo(conn, tenant_id)
    kq = await conn.execute(
        "UPDATE tenant_data.agent_config SET version = $2, updated_at = now()"
        " WHERE tenant_id = $1 AND tenant_id = portal.current_tenant()",
        tenant_id,
        moi,
    )
    return None if kq == "UPDATE 0" else moi
