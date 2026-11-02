"""Nhật ký hoạt động — HẠ TẦNG DÙNG CHUNG, không phải của module nào.

M5 ghi lúc áp dụng cấu hình (BR15), M6 ghi lúc nạp và xoá tài liệu (KB_01 BR09),
M8 đã dựng đường đọc: `modules/audit/` (`GET /audit`, 2026-08-25, spec
docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md). Retention vẫn chưa có.
Thêm một mã hành động mới ⇒ thêm vào `core/nhat_ky_ma.py` (cổng AST bắt buộc).

Trước bản này nó sống trong `modules/config/repo.py`, và M6 phải import ruột M3
để dùng — cổng ranh giới module (Luật 3) đỏ, đúng như thiết kế. Chỗ đúng của một
việc mà nhiều module cùng làm là `core/`, không phải module nào làm nó trước.

Bảng `control.audit_log` do migration 0201 tạo; đường đọc ở modules/audit.
"""

import json

import asyncpg


async def ghi(conn: asyncpg.Connection, tenant_id: str, hanh_dong: str, actor: str, chi_tiet: dict) -> None:
    """Ghi một hàng nhật ký. GỌI SAU KHI việc đã xong, không phải trước.

    Nhật ký ghi việc ĐÃ XẢY RA. Ghi trước rồi làm là cách chắc chắn để nhật ký
    nói agent đã đổi persona trong khi nó vẫn chạy bản cũ — và người đọc nhật ký
    thì tin vào nhật ký.

    Bảng chỉ GHI THÊM: migration 0201 rút UPDATE và DELETE của `portal_api`.
    """
    await conn.execute(
        "INSERT INTO control.audit_log (tenant_id, hanh_dong, actor, chi_tiet) VALUES ($1, $2, $3, $4::jsonb)",
        tenant_id,
        hanh_dong,
        actor or "",
        json.dumps(chi_tiet, ensure_ascii=False),
    )


async def ghi_he_thong(conn: asyncpg.Connection, hanh_dong: str, actor: str, chi_tiet: dict) -> None:
    """Nhật ký cấp HỆ THỐNG — hàng có `tenant_id` NULL.

    ĐỔI TÊN từ `ghi_to_chuc` và BỎ tham số `org_id` (2026-08-15): cột `org_id`
    biến mất cùng bảng `control.organizations` (migration 0106), và cùng lúc
    `audit_log_co_pham_vi_check` bị gỡ — giữ nó lại thì nó rút thành
    `tenant_id IS NOT NULL` và mọi hàng cũ của hàm này lập tức vi phạm.
    `tenant_id IS NULL` từ nay đọc là "hành động không thuộc workspace nào".

    VÌ SAO VẪN LÀ HÀM THỨ HAI thay vì thêm tham số cho `ghi()`: những việc như
    "tạo một tài khoản" không thuộc workspace nào, và không có giá trị `tenant_id`
    hợp lệ để điền (0201 khai FK tới `control.tenants`). Một hàm hai tham số tuỳ
    chọn đọc như lời mời truyền cả hai hoặc không truyền gì.

    Bảng chỉ GHI THÊM: 0201 đã rút UPDATE và DELETE của `portal_api`.
    """
    await conn.execute(
        "INSERT INTO control.audit_log (hanh_dong, actor, chi_tiet) VALUES ($1, $2, $3::jsonb)",
        hanh_dong,
        actor or "",
        json.dumps(chi_tiet, ensure_ascii=False),
    )
