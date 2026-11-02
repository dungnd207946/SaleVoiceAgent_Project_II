"""Ba bậc độ trễ hiệu lực — HT01 §II.2.1, phần quan trọng nhất của giao diện.

Nói "Đã lưu" cho một thay đổi persona chưa xuất bản là **nói dối người dùng**:
họ đi gọi thử, không thấy gì đổi, rồi mất niềm tin vào cả sản phẩm.

Vì sao hàm thuần và vì sao có cả một file test riêng: logic này rải trong router
thì sai một nhánh là UI nói dối, và **không test nào đỏ**. Gom một chỗ, một bảng
test theo đúng bảng của spec.

`bay_gio` là tham số chứ không phải `datetime.now()` bên trong: đồng hồ ẩn làm
test "quá hạn 60 giây" phải ngủ thật 60 giây, hoặc phải monkeypatch — cả hai đều
tệ hơn là truyền vào.
"""

from datetime import UTC, datetime, timedelta

from portal.modules.config.service import Heartbeat, TrangThaiAgent, tinh_trang_thai_agent

BAY_GIO = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def _hb(running_version: int | None, tre_giay: int = 0) -> Heartbeat:
    return Heartbeat(
        running_version=running_version,
        bundle_sha="sha",
        last_seen_at=BAY_GIO - timedelta(seconds=tre_giay),
    )


def test_chua_co_heartbeat_thi_dang_cap():
    """Workspace vừa tạo, pod chưa lên. AG_01 ER_06: chat thử khoá, cấu hình vẫn lưu được."""
    assert tinh_trang_thai_agent(None, live_version=None, bay_gio=BAY_GIO) == TrangThaiAgent.DANG_CAP


def test_agent_chay_dung_version_dang_live_thi_san_sang():
    assert tinh_trang_thai_agent(_hb(12), live_version=12, bay_gio=BAY_GIO) == TrangThaiAgent.SAN_SANG


def test_agent_con_chay_version_cu_thi_dang_ap_dung():
    """Vừa publish v13, agent còn báo v12 — đúng bậc 3: ≤20s, chỉ phiên MỚI."""
    assert tinh_trang_thai_agent(_hb(12), live_version=13, bay_gio=BAY_GIO) == TrangThaiAgent.DANG_AP_DUNG


def test_agent_chua_bao_version_nao_thi_dang_ap_dung():
    """Pod vừa lên, đã gửi nhịp tim nhưng chưa nạp xong bundle."""
    assert tinh_trang_thai_agent(_hb(None), live_version=1, bay_gio=BAY_GIO) == TrangThaiAgent.DANG_AP_DUNG


def test_qua_han_nhip_tim_thi_mat_ket_noi():
    assert tinh_trang_thai_agent(_hb(12, tre_giay=61), live_version=12, bay_gio=BAY_GIO) == TrangThaiAgent.MAT_KET_NOI


def test_mat_ket_noi_thang_the_dang_ap_dung():
    """Thứ tự kiểm QUAN TRỌNG. Agent chết ngay sau khi publish thì nhịp tim đứng
    ở version cũ mãi mãi — hiện Đang áp dụng là hứa một thứ sẽ không bao giờ tới.
    Người dùng ngồi đợi thay vì đi gọi người vận hành."""
    assert tinh_trang_thai_agent(_hb(12, tre_giay=300), live_version=13, bay_gio=BAY_GIO) == TrangThaiAgent.MAT_KET_NOI


def test_dung_han_60_giay_van_con_san_sang():
    """Biên: đúng 60s chưa phải mất kết nối. Chu kỳ nhịp tim là 20s nên 60s là
    ba lượt lỡ — dưới ngưỡng đó thì một gói tin rớt không được biến thành báo động."""
    assert tinh_trang_thai_agent(_hb(12, tre_giay=60), live_version=12, bay_gio=BAY_GIO) == TrangThaiAgent.SAN_SANG
