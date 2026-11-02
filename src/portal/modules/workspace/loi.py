"""Mã lỗi RIÊNG của module workspace.

`api/loi.py` ghi: *"Module sau thêm hằng số của nó vào file của nó, không vào
đây."* `FORBIDDEN` (403, `khong_du_quyen()`) vẫn dùng bản chung — nó là hình dạng
lỗi của cả API, không của riêng module này.
"""

from portal.api.loi import LoiPortal


def ten_workspace_da_dung(ten: str) -> LoiPortal:
    """409, không 422: dữ liệu gửi lên đúng dạng, chỉ là thế giới đã có tên đó.

    PHẠM VI LÀ NGƯỜI TẠO, và thông điệp phải nói ra điều đó. UNIQUE INDEX
    `tenants_nguoi_tao_ten_key` (0106) chỉ chặn trùng tên TRONG workspace của
    chính bạn — hai người khác nhau đặt trùng tên là hợp lệ. Nói "tên này đã được
    dùng" trần trụi là để người dùng tưởng tên đó bị người ngoài chiếm và đi đặt
    một cái tên xấu hơn mà không cần.

    Trả kèm `ten` đã chuẩn hoá: người dùng gõ "Sàn A " trong khi đã có "sàn a" thì
    thông điệp phải cho họ thấy vì sao hai chuỗi họ nhìn khác nhau lại là một.
    """
    return LoiPortal(
        "WORKSPACE_TRUNG_TEN",
        409,
        f"Bạn đã có một workspace tên {ten!r}",
    )


def workspace_cuoi_cung() -> LoiPortal:
    """409 — không xoá được workspace CUỐI CÙNG mà người dùng còn thấy.

    Không phải một luật nghiệp vụ, mà là một lời thú nhận trung thực về thứ portal
    CHƯA CÓ: phiên không thuộc workspace nào là trạng thái hợp lệ ở backend từ
    2026-08-15 (spec bo-organization §5.0), nhưng FE chưa có màn nào cho nó —
    `SessionReady` (lib/session.tsx) ném "Phiên không có workspace nào" và người
    dùng nhận một màn trắng.

    409 chứ không 403: người dùng CÓ quyền (họ là Quản trị), chỉ là thế giới đang
    ở trạng thái không cho phép việc đó. 403 sẽ đẩy họ đi hỏi xin một quyền mà họ
    đã có.

    Ngày FE dựng màn "bạn chưa thuộc workspace nào", xoá hàm này và cái test canh
    nó — đừng nới nó thành cảnh báo.
    """
    return LoiPortal(
        "WORKSPACE_CUOI_CUNG",
        409,
        "Đây là workspace duy nhất của bạn. Tạo một workspace khác trước khi xoá cái này.",
    )
