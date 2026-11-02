"""Fixture module audit — cùng nếp tests/modules/billing/conftest.py.

KHÔNG mock `tenant_conn()`: nó là seam của cách ly. Dữ liệu chèn TRỰC TIẾP vào
`control.audit_log` bằng `pool` (migrator) với `luc` TƯỜNG MINH — mọi test phân
trang/khoảng ngày neo vào các mốc dưới đây, đừng để `DEFAULT now()`.

Bộ hàng được dựng để MỖI test có đúng thứ nó cần trong CÙNG một fixture:
- tenant A (`audw`): 10 hàng, trong đó 1 hàng máy (`agent`), 1 hàng hệ thống
  (`''`), 1 hàng actor không còn trong `users`, 3 hàng CÙNG `luc`, 1 hàng lúc
  23:30 giờ VN (= 16:30 UTC) để kiểm múi giờ.
- tenant B (`audx`): 1 hàng — không bao giờ được lộ.
- `tenant_id NULL`: 1 hàng — hàng hệ thống, màn theo workspace không bày (spec §2 #6).
"""

import json
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

TENANT = "audw"
TENANT_KHAC = "audx"
USER_QT = "u_aud_qt"
USER_XEM = "u_aud_xem"
USER_DA_XOA = "u_aud_da_xoa"  # KHÔNG chèn vào users — actor đã bị gỡ
EMAIL_QT = "aud.qt@noblex.vn"
EMAIL_XEM = "aud.xem@noblex.vn"
MAT_KHAU = "MatKhauDaiVaManh!1"

MOC = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
CUNG_LUC = MOC + timedelta(hours=7)  # 16:00Z = 23:00 VN 20/08 — còn TRONG ngày 20 (VN)
MUON_VN = datetime(2026, 8, 22, 16, 30, tzinfo=UTC)  # 23:30 22/08 giờ VN

# (tenant, hanh_dong, actor, chi_tiet, luc) — thứ tự chèn KHÔNG phải thứ tự luc,
# cố ý: id tăng theo chèn, luc thì không, để keyset theo `id` một mình sẽ lộ sai.
HANG = [
    (TENANT, "realestate.project.update", USER_QT, {"project_code": "NT2", "truong": ["name"]}, MOC),
    (TENANT, "role.sua", USER_QT, {"role_id": "r_x"}, MUON_VN),
    (TENANT, "thanh_vien.moi", USER_QT, {"email": "moi@noblex.vn"}, MOC + timedelta(hours=1)),
    (TENANT, "user.nhan_moi_ws", USER_XEM, {}, MOC + timedelta(hours=2)),
    (TENANT, "agent.runtime_credentials", "agent", {"agent_key_id": 1}, MOC + timedelta(hours=3)),
    # fixture dùng "" để kiểm ca actor rỗng (LEFT JOIN không khớp user nào);
    # thực tế job này ghi actor "cron" (`ingest/jobs.py`) — KHÔNG đổi giá trị ở
    # đây, test bám vào đúng chuỗi rỗng để canh nhánh `actor = ''`.
    (TENANT, "ingest.tenant_im_lang", "", {"gio_im_lang": 26}, MOC + timedelta(hours=4)),
    (TENANT, "kb.upload", USER_DA_XOA, {"ten_file": "a.pdf"}, MOC + timedelta(hours=5)),
    (TENANT, "agent_config.publish", USER_QT, {"version": 3}, CUNG_LUC),
    (TENANT, "agent_config.publish", USER_QT, {"version": 4}, CUNG_LUC),
    (TENANT, "agent_config.publish", USER_QT, {"version": 5}, CUNG_LUC),
    (TENANT_KHAC, "kb.delete", USER_QT, {"ten_file": "b.pdf"}, MOC + timedelta(hours=6)),
    (None, "user.doi_mat_khau", USER_QT, {}, MOC + timedelta(hours=7)),
]
SO_HANG_A = 10
SO_HANG_A_KHONG_MAY = 9


@pytest.fixture
async def workspace_audit(pool: asyncpg.Pool):
    """Hai user (Quản trị · Người xem) cùng workspace A; tenant B chỉ để chứa
    hàng không được lộ. Trả dict id các hàng theo `hanh_dong`+`version` để
    test đối chiếu."""
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        for uid, ten, email in ((USER_QT, "Quản Trị Viên", EMAIL_QT), (USER_XEM, "Người Xem", EMAIL_XEM)):
            await conn.execute(
                "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
                uid,
                ten,
                email,
                bam(MAT_KHAU),
            )
        for t, ten in ((TENANT, "Audit WS"), (TENANT_KHAC, "Audit Khac")):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, $3)", t, ten, USER_QT
            )
        r_qt = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        r_xem = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Người xem'")
        assert r_qt and r_xem, "0104/0105 chưa seed vai trò — fixture không dựng thay được"
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)", USER_QT, TENANT, r_qt
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)",
            USER_XEM,
            TENANT,
            r_xem,
        )
        ids: dict[str, int] = {}
        for t, hd, actor, ct, luc in HANG:
            id_ = await conn.fetchval(
                "INSERT INTO control.audit_log (tenant_id, hanh_dong, actor, chi_tiet, luc) "
                "VALUES ($1, $2, $3, $4::jsonb, $5) RETURNING id",
                t,
                hd,
                actor,
                json.dumps(ct, ensure_ascii=False),
                luc,
            )
            ids[f"{hd}:{ct.get('version', '')}"] = id_
    yield ids
    async with pool.acquire() as conn, conn.transaction():
        # Hàng có tenant đi theo `ON DELETE CASCADE` của tenants; hàng NULL và
        # hàng login (nếu có) dọn theo actor.
        await conn.execute("DELETE FROM control.audit_log WHERE actor = ANY($1::text[])", [USER_QT, USER_XEM])
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.users WHERE id = ANY($1::text[])", [USER_QT, USER_XEM])


async def dang_nhap(client, email: str) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r2 = await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT})
    assert r2.status_code == 200, r2.text
