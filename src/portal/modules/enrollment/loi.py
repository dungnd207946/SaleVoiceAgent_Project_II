"""Sáu lỗi của M10. Ở file của module, không vào api/loi.py — nếp của M3.

Hợp đồng bàn giao: docs/contracts/dau-noi-agent.md §2 — nhưng CHỈ bốn lỗi đầu
thuộc hợp đồng đó (chúng là lỗi pod agent nhìn thấy). Hai lỗi 404 cuối là lỗi
người dùng portal nhìn thấy, không đi ra ngoài.
"""

from portal.api.loi import LoiPortal

_KHOA_KHONG_HOP_LE = "Khoá đấu nối không hợp lệ"
"""MỘT câu chữ cho cả bốn nhánh: thiếu header · sai định dạng · không khớp hàng
nào · đã thu hồi.

Khác `message` là máy dò chỉ cần đọc message để biết khoá nào từng có thật —
cùng lý do ba mã 401/403 của M2a dùng cùng câu chữ (contracts/auth.md).
"""


def khoa_khong_hop_le() -> LoiPortal:
    return LoiPortal("INVALID_AGENT_KEY", 401, _KHOA_KHONG_HOP_LE)


def tenant_khong_hoat_dong(lifecycle: str) -> LoiPortal:
    return LoiPortal("TENANT_SUSPENDED", 403, f"Workspace đang ở trạng thái {lifecycle}")


def vuot_gioi_han_nhip() -> LoiPortal:
    return LoiPortal("RATE_LIMITED", 429, "Quá nhiều lần đấu nối. Thử lại sau ít phút")


def chua_cap_phat(thieu: str) -> LoiPortal:
    return LoiPortal("NOT_PROVISIONED", 409, f"Deployment chưa cấp phát xong: thiếu {thieu}")


def khong_co_tenant(tenant_id: str) -> LoiPortal:
    return LoiPortal("NOT_FOUND", 404, f"Không có workspace {tenant_id}")


def khong_co_khoa(key_id: int) -> LoiPortal:
    """404 cho CẢ HAI nhánh: khoá không tồn tại, và khoá thuộc tenant khác.

    Không phân biệt hai nhánh là CỐ Ý, cùng lý lẽ `_KHOA_KHONG_HOP_LE` ở trên đã
    viết: phân biệt được là một đường để người ở workspace A dò xem workspace B
    đang có khoá id bao nhiêu. Một câu chữ, một mã.
    """
    return LoiPortal("NOT_FOUND", 404, f"Không có khoá {key_id}")
