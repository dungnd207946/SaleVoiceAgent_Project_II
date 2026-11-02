"""403 thiếu quyền của M2b (spec §3.4) — lỗi phải nói LÝ DO, không phải câu
chung của `khong_du_quyen()`. Không cần DB — `thieu_quyen()` là hàm thuần.
"""

from portal.api.loi import thieu_quyen
from portal.core.auth.actions import ALL_ACTIONS, NHAN_HANH_DONG


def test_nhan_hanh_dong_khop_full_voi_all_actions():
    """Cổng chặn: thiếu một nhãn ở đây không làm sập `require()` — nó vẫn chặn
    đúng — nhưng làm 403 in ra MÃ MÁY (`convos.transcript.read`) thẳng vào mặt
    người dùng thay vì câu tiếng Việt. Ai thêm hành động thứ 14 mà quên thêm
    nhãn thì test này phải đỏ, không phải phát hiện qua ticket hỗ trợ."""
    assert set(NHAN_HANH_DONG) == set(ALL_ACTIONS)


def test_co_ten_vai_tro_thi_bao_ma_va_ca_ten_vai_tro():
    loi = thieu_quyen("catalog.write", "Người xem")
    assert loi.ma == "FORBIDDEN"
    assert loi.http == 403
    assert NHAN_HANH_DONG["catalog.write"] in loi.thong_diep
    assert "Người xem" in loi.thong_diep


def test_khong_co_ten_vai_tro_khong_lo_chu_None():
    """Không có membership → không có role_name thật để trích dẫn. Nhồi một
    cụm chung (vai trò hiện tại của bạn) vào cặp   làm như đó là TÊN vai
    trò — sai và lố. Câu phải nói thẳng sự thật, không đặt placeholder trong
    dấu trích dẫn của một cái tên."""
    loi = thieu_quyen("catalog.write", None)
    assert "None" not in loi.thong_diep
    assert "«" not in loi.thong_diep
    assert NHAN_HANH_DONG["catalog.write"] in loi.thong_diep


def test_hanh_dong_la_thieu_nhan_van_in_ra_ma_khong_raise():
    """Một mã hành động lạ (chưa kịp thêm nhãn, hoặc gõ sai) không được làm
    đường lỗi 403 vỡ thành 500 — thà in mã máy còn hơn sập."""
    loi = thieu_quyen("khong_ton_tai.action", "Người xem")
    assert loi.ma == "FORBIDDEN"
    assert "khong_ton_tai.action" in loi.thong_diep
