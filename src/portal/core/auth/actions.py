"""13 nhóm hành động của PQ_01 §3.1 + 4 action mọc sau (billing.read · audit.read · kb_web.read/write) — NGUỒN DUY NHẤT.

VÌ SAO NGUỒN Ở ĐÂY, KHÔNG Ở FE: đây là tầng cưỡng chế thật. FE ẩn mục nav là
tiện mắt (PQ_01 §BR-Q03); BE chặn request là bảo vệ. Nguồn phải nằm ở chỗ chặn.

CÁCH FE ĐỌC ĐƯỢC NGUỒN NÀY SAU KHI TÁCH REPO: `contracts/actions.json` — sinh từ
file này bằng `make contracts`, commit vào git, và copy y nguyên sang repo
frontend. Bản trước của plan cho vitest đọc thẳng file .py qua đường
`../../backend/...`; đường đó chỉ tồn tại thời monorepo. Xem contracts/README.md.

Số trong docstring là SỐ DÒNG trong bảng PQ_01 §3.1 — đừng bỏ, nó là cách kiểm
13 nhóm không thiếu không thừa.

⚠ Tên là ĐỀ XUẤT của M2a, M2b chốt lần cuối. Đổi tên ở đây mà quên chạy
`make contracts` thì `tests/api/test_contracts.py` đỏ — đó là điều mong muốn.
"""

from typing import Final


class ACTIONS:
    """Namespace hằng số. Class thay vì dict để `ACTIONS.OVERVIEW_READ` bị
    kiểm lúc type-check — gõ sai tên là lỗi mypy/IDE, không phải KeyError lúc chạy."""

    OVERVIEW_READ: Final = "overview.read"
    """1 · Xem Tổng quan · số liệu"""
    CONVOS_READ: Final = "convos.read"
    """2 · Xem danh sách Hội thoại + tóm tắt"""
    CONVOS_TRANSCRIPT_READ: Final = "convos.transcript.read"
    """3 · Đọc bản ghi thoại — quyền RIÊNG (BR-Q06), mỗi lần đọc vào nhật ký (BR-Q07)"""
    CONVOS_HANDLE: Final = "convos.handle"
    """4 · Nhận chuyển tiếp · đánh dấu đã xử lý"""
    APPTS_READ: Final = "appts.read"
    """5 · Xem Lịch hẹn"""
    APPTS_WRITE: Final = "appts.write"
    """6 · Sửa · huỷ Lịch hẹn"""
    CATALOG_READ: Final = "catalog.read"
    """7 · Xem Dự án · Quỹ căn · Tài liệu · Media"""
    CATALOG_WRITE: Final = "catalog.write"
    """8 · Thêm · sửa · nhập tệp Dự án · Quỹ căn · Tài liệu · Media"""
    CATALOG_DELETE: Final = "catalog.delete"
    """9 · Xoá dự án · quỹ căn · tài liệu · media"""
    AGENT_CONFIG_READ: Final = "agent_config.read"
    """10 · Xem cấu hình agent (chỉ đọc)"""
    AGENT_CONFIG_WRITE: Final = "agent_config.write"
    """11 · Sửa bản nháp cấu hình agent"""
    AGENT_CONFIG_PUBLISH: Final = "agent_config.publish"
    """12 · Xuất bản · Quay lui"""
    WORKSPACE_ADMIN: Final = "workspace.admin"
    """13 · Khoá API · Thành viên · Cài đặt workspace · Yêu cầu của khách"""
    BILLING_READ: Final = "billing.read"
    """Xem Usage & Billing. TÁCH khỏi WORKSPACE_ADMIN có chủ ý: kế toán cần xem
    hoá đơn mà không cần quyền mời/gỡ thành viên."""
    AUDIT_READ: Final = "audit.read"
    """15 · Xem Nhật ký hoạt động của workspace (`control.audit_log`). Nằm ngoài 13
    nhóm gốc PQ_01 §3.1 như `billing.read`; thêm 2026-08-25 (`0956_audit_action`).
    Ai KHÔNG có action này thì không thấy mục nav «Nhật ký» và bị 403 ở
    `GET /audit` — phần «mọi vai trò xem việc của chính mình» (PQ_01 §3.1) là đợt 2,
    xem spec 2026-08-25-nhat-ky-hoat-dong-design.md §2 #6."""
    KB_WEB_READ: Final = "kb_web.read"
    """16 · Xem màn «Dữ liệu ngoài» (nguồn, chủ đề, lịch, hồ sơ dự án, nhật ký chạy) — `0972`."""
    KB_WEB_WRITE: Final = "kb_web.write"
    """17 · Sửa nguồn/chủ đề/lịch/giới hạn, ẩn mục hồ sơ, loại bài, bấm chạy ngay — `0972`."""


ALL_ACTIONS: Final[frozenset[str]] = frozenset(
    v for k, v in vars(ACTIONS).items() if not k.startswith("_") and isinstance(v, str)
)

# Nhãn hiển thị của 403 thiếu quyền (spec §3.4 — lỗi phải nói LÝ DO). BẢN SAO
# của 13 docstring ở trên (và của label_vi trong migration 0104) — chấp nhận
# trùng lặp vì đây là chuỗi NGƯỜI ĐỌC ở một chỗ hoàn toàn khác (thông điệp lỗi
# HTTP, không phải catalog DB), và tách nó ra một nguồn chung sẽ buộc `api/loi.py`
# phải import từ DB hoặc từ docstring bằng cách nào đó — cả hai đều nặng hơn cái
# lợi. Đổi một dòng ở trên mà quên đổi dòng tương ứng ở đây là lỗi hiển thị, không
# phải lỗi cưỡng chế — `require()` vẫn chặn đúng, chỉ câu giải thích cũ.
NHAN_HANH_DONG: Final[dict[str, str]] = {
    ACTIONS.OVERVIEW_READ: "Xem Tổng quan · số liệu",
    ACTIONS.CONVOS_READ: "Xem danh sách Hội thoại + tóm tắt",
    ACTIONS.CONVOS_TRANSCRIPT_READ: "Đọc bản ghi thoại",
    ACTIONS.CONVOS_HANDLE: "Nhận chuyển tiếp · đánh dấu đã xử lý",
    ACTIONS.APPTS_READ: "Xem Lịch hẹn",
    ACTIONS.APPTS_WRITE: "Sửa · huỷ Lịch hẹn",
    ACTIONS.CATALOG_READ: "Xem Dự án · Quỹ căn · Tài liệu · Media",
    ACTIONS.CATALOG_WRITE: "Thêm · sửa · nhập tệp Dự án · Quỹ căn · Tài liệu · Media",
    ACTIONS.CATALOG_DELETE: "Xoá dự án · quỹ căn · tài liệu · media",
    ACTIONS.AGENT_CONFIG_READ: "Xem cấu hình agent (chỉ đọc)",
    ACTIONS.AGENT_CONFIG_WRITE: "Sửa bản nháp cấu hình agent",
    ACTIONS.AGENT_CONFIG_PUBLISH: "Xuất bản · Quay lui",
    ACTIONS.WORKSPACE_ADMIN: "Khoá API · Thành viên · Cài đặt workspace · Yêu cầu của khách",
    ACTIONS.BILLING_READ: "Xem Usage & Billing · chi phí",
    ACTIONS.AUDIT_READ: "Xem Nhật ký hoạt động",
    ACTIONS.KB_WEB_READ: "Xem Dữ liệu ngoài",
    ACTIONS.KB_WEB_WRITE: "Cấu hình · chạy Dữ liệu ngoài",
}
